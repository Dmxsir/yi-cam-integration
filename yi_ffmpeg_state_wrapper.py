#!/usr/bin/env python3
"""Transparent live-only FFmpeg state diagnostic shim.

The YI live relay launches FFmpeg through PATH. This shim execs the real FFmpeg
unchanged for every non-live invocation. For the known live MPEG-TS path it
changes only FFmpeg log verbosity from warning to info, captures stderr in a
small filter process, and emits a fixed set of secret-safe state markers.

A temporary A/B experiment is also scoped to the PTZ stable-id only. Its AAC
input remains open and consumed normally, but the AAC stream is removed from
the MPEG-TS output mapping so the live mux publishes H264 video only. This
isolates output interleave/timestamp behavior without changing PPPP/TNP, the
native worker, H264 framing, watchdogs, other cameras, or finite validation.

No FFmpeg stderr text, arguments, paths, credentials, payload bytes, PIDs or
camera material are copied into the diagnostic output.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


SAFE_PREFIX = b"[phase3g-relay] ffmpeg_state="
PTZ_VIDEO_ONLY_STABLE_ID = b"e2f22804fecd"


def _is_yi_live_mux(args: list[str]) -> bool:
    """Match only the relay's live stdout MPEG-TS invocation."""
    return (
        "pipe:1" in args
        and "-bsf:v" in args
        and "-bsf:a" in args
        and "-flush_packets" in args
        and any(value.startswith("setts=") for value in args)
    )


def _parent_is_ptz_runtime() -> bool:
    """Identify only the direct stable-id relay parent; never log cmdline data."""
    try:
        values = [
            value
            for value in Path(f"/proc/{os.getppid()}/cmdline").read_bytes().split(b"\0")
            if value
        ]
    except OSError:
        return False
    for index, value in enumerate(values[:-1]):
        if value == b"--stable-id" and values[index + 1] == PTZ_VIDEO_ONLY_STABLE_ID:
            return True
    return False


def _with_info_loglevel(args: list[str]) -> list[str]:
    """Raise only the live diagnostic verbosity; media options stay untouched."""
    result = list(args)
    for index in range(len(result) - 1):
        if result[index] == "-loglevel" and result[index + 1] == "warning":
            result[index + 1] = "info"
            break
    return result


def _with_video_only_output(args: list[str]) -> list[str]:
    """Keep both inputs but remove only AAC from the PTZ MPEG-TS output map."""
    result: list[str] = []
    index = 0
    while index < len(args):
        option = args[index]
        if option == "-map" and index + 1 < len(args) and args[index + 1] == "1:a:0":
            index += 2
            continue
        if option == "-bsf:a" and index + 1 < len(args):
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


def _filter_ffmpeg_stderr(read_fd: int, safe_fd: int, video_only: bool) -> None:
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
    if video_only:
        _safe_write(safe_fd, "ptz_video_only_ab_active")
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
            f"video_only={int(video_only)};"
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

    video_only = _parent_is_ptz_runtime()
    diagnostic_args = _with_info_loglevel(args)
    if video_only:
        diagnostic_args = _with_video_only_output(diagnostic_args)

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
            _filter_ffmpeg_stderr(read_fd, safe_fd, video_only)
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
