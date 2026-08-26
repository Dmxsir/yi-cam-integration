#!/usr/bin/env python3
"""Transparent live-only FFmpeg state diagnostic shim.

The YI live relay launches FFmpeg through PATH. This shim execs the real FFmpeg
unchanged for every non-live invocation. For the known live MPEG-TS path it
changes only FFmpeg log verbosity from warning to info, captures stderr in a
small filter process, and emits a fixed set of secret-safe state markers.

A temporary A/B experiment is scoped to the PTZ stable-id only. The normal H264
and AAC output mapping remains intact, while only the live raw-input probe
settings are restored to the known Phase-6G baseline. PPPP/TNP, the native
worker, timestamps, watchdogs, other cameras, and finite validation are left
unchanged.

No FFmpeg stderr text, arguments, paths, credentials, payload bytes, PIDs or
camera material are copied into the diagnostic output.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


SAFE_PREFIX = b"[phase3g-relay] ffmpeg_state="
FFMPEG_STABLE_ID_ENV = "YI_FFMPEG_STABLE_ID"
PTZ_STABLE_ID_TEXT = "e2f22804fecdbd8c3561"
PTZ_STABLE_ID = PTZ_STABLE_ID_TEXT.encode("ascii")
PTZ_LOG_NAME = "e2f22804fecdbd8c3561.log"
MAX_ANCESTOR_SCAN = 8


def _is_yi_live_mux(args: list[str]) -> bool:
    """Match only the relay's live stdout MPEG-TS invocation."""
    return (
        "pipe:1" in args
        and "-bsf:v" in args
        and "-bsf:a" in args
        and "-flush_packets" in args
        and any(value.startswith("setts=") for value in args)
    )


def _normalized_fd_target_name(pid: int, fd: int = 2) -> str | None:
    """Return only a basename for one proc fd target; never surface the path."""
    try:
        target = os.readlink(f"/proc/{pid}/fd/{fd}")
    except OSError:
        return None
    name = Path(target).name
    deleted_suffix = " (deleted)"
    if name.endswith(deleted_suffix):
        name = name[: -len(deleted_suffix)]
    return name


def _stderr_is_ptz_runtime(pid: int) -> bool:
    """Identify the PTZ from a process' inherited per-camera stderr log."""
    return _normalized_fd_target_name(pid, 2) == PTZ_LOG_NAME


def _cmdline_is_ptz_runtime(pid: int) -> bool:
    """Check one process for the PTZ stable-id without logging cmdline data."""
    try:
        values = [
            value
            for value in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if value
        ]
    except OSError:
        return False
    for index, value in enumerate(values[:-1]):
        if value == b"--stable-id" and values[index + 1] == PTZ_STABLE_ID:
            return True
    return False


def _parent_pid(pid: int) -> int | None:
    """Return one Linux parent PID from /proc without exposing process data."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        tail = raw.rsplit(") ", 1)[1].split()
        parent = int(tail[1])
    except (OSError, UnicodeError, ValueError, IndexError):
        return None
    return parent if parent > 0 and parent != pid else None


def _detect_ptz_runtime() -> str:
    """Return one fixed, secret-safe detector label or ``none``."""
    if os.environ.get(FFMPEG_STABLE_ID_ENV, "").strip() == PTZ_STABLE_ID_TEXT:
        return "stable_id_env"
    if _stderr_is_ptz_runtime(os.getpid()):
        return "self_stderr"

    pid = os.getppid()
    seen: set[int] = set()
    for _ in range(MAX_ANCESTOR_SCAN):
        if pid <= 1 or pid in seen:
            break
        seen.add(pid)
        if _stderr_is_ptz_runtime(pid):
            return "ancestor_stderr"
        if _cmdline_is_ptz_runtime(pid):
            return "ancestor_cmdline"
        parent = _parent_pid(pid)
        if parent is None:
            break
        pid = parent
    return "none"


def _with_info_loglevel(args: list[str]) -> list[str]:
    """Raise only the live diagnostic verbosity; media options stay untouched."""
    result = list(args)
    for index in range(len(result) - 1):
        if result[index] == "-loglevel" and result[index + 1] == "warning":
            result[index + 1] = "info"
            break
    return result


def _with_phase6g_probe_baseline(args: list[str]) -> list[str]:
    """Restore only the two live raw-input probe windows to Phase-6G values."""
    result: list[str] = []
    probesize_values = ("262144", "32768")
    analyzeduration_values = ("500000", "200000")
    probesize_index = 0
    analyzeduration_index = 0
    index = 0

    while index < len(args):
        option = args[index]
        if option == "-fpsprobesize" and index + 1 < len(args):
            # Phase 6G had no explicit fpsprobesize override.
            index += 2
            continue
        if option == "-probesize" and index + 1 < len(args):
            if probesize_index < len(probesize_values):
                result.extend((option, probesize_values[probesize_index]))
                probesize_index += 1
                index += 2
                continue
        if option == "-analyzeduration" and index + 1 < len(args):
            if analyzeduration_index < len(analyzeduration_values):
                result.extend((option, analyzeduration_values[analyzeduration_index]))
                analyzeduration_index += 1
                index += 2
                continue
        result.append(option)
        index += 1

    return result


def _safe_write(fd: int, marker: str) -> None:
    """Write one fixed ASCII marker to the relay's original stderr."""
    try:
        os.write(fd, SAFE_PREFIX + marker.encode("ascii") + b"\n")
    except (BrokenPipeError, OSError, UnicodeError):
        pass


def _filter_ffmpeg_stderr(
    read_fd: int,
    safe_fd: int,
    phase6g_probe: bool,
    detection_source: str,
) -> None:
    """Consume all FFmpeg stderr while exposing only allowlisted milestones."""
    seen: set[str] = set()
    states = {
        "video_input_open": False,
        "video_stream_info": False,
        "audio_input_open": False,
        "audio_stream_info": False,
        "stream_mapping_ready": False,
        "output_mpegts_ready": False,
    }

    def emit(marker: str) -> None:
        if marker in seen:
            return
        seen.add(marker)
        states[marker] = True
        _safe_write(safe_fd, marker)

    _safe_write(safe_fd, "diagnostic_active")
    _safe_write(safe_fd, f"ptz_detection={detection_source}")
    if phase6g_probe:
        _safe_write(safe_fd, "ptz_phase6g_probe_ab_active")
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as stream:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("Input #0, h264,"):
                    emit("video_input_open")
                elif line.startswith("Input #1, aac,"):
                    emit("audio_input_open")
                elif line.startswith("Stream #0:0") and "Video: h264" in line:
                    emit("video_stream_info")
                elif line.startswith("Stream #1:0") and "Audio: aac" in line:
                    emit("audio_stream_info")
                elif line.startswith("Stream mapping:"):
                    emit("stream_mapping_ready")
                elif line.startswith("Output #0, mpegts,"):
                    emit("output_mpegts_ready")
    except (OSError, ValueError):
        _safe_write(safe_fd, "filter_error")
    finally:
        summary = (
            "stderr_eof;"
            "video_only=0;"
            f"phase6g_probe={int(phase6g_probe)};"
            f"video_input={int(states['video_input_open'])};"
            f"video_stream={int(states['video_stream_info'])};"
            f"audio_input={int(states['audio_input_open'])};"
            f"audio_stream={int(states['audio_stream_info'])};"
            f"mapping={int(states['stream_mapping_ready'])};"
            f"output={int(states['output_mpegts_ready'])}"
        )
        _safe_write(safe_fd, summary)
        try:
            os.close(safe_fd)
        except OSError:
            pass


def _exec_real(real_ffmpeg: str, args: list[str]) -> None:
    os.execv(real_ffmpeg, [real_ffmpeg, *args])


def main() -> int:
    real_ffmpeg = os.environ.get("YI_REAL_FFMPEG", "").strip()
    if not real_ffmpeg or not os.path.isabs(real_ffmpeg):
        return 127

    args = sys.argv[1:]
    if not _is_yi_live_mux(args):
        _exec_real(real_ffmpeg, args)
        return 127

    detection_source = _detect_ptz_runtime()
    phase6g_probe = detection_source != "none"
    diagnostic_args = _with_info_loglevel(args)
    if phase6g_probe:
        diagnostic_args = _with_phase6g_probe_baseline(diagnostic_args)

    try:
        read_fd, write_fd = os.pipe()
        safe_fd = os.dup(2)
        pid = os.fork()
    except OSError:
        for fd_name in ("read_fd", "write_fd", "safe_fd"):
            fd = locals().get(fd_name)
            if isinstance(fd, int):
                try:
                    os.close(fd)
                except OSError:
                    pass
        _exec_real(real_ffmpeg, args)
        return 127

    if pid == 0:
        try:
            os.close(write_fd)
            _filter_ffmpeg_stderr(read_fd, safe_fd, phase6g_probe, detection_source)
        finally:
            os._exit(0)

    os.close(read_fd)
    os.dup2(write_fd, 2)
    os.close(write_fd)
    os.close(safe_fd)
    _exec_real(real_ffmpeg, diagnostic_args)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
