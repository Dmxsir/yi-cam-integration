#!/usr/bin/env python3
"""Development adapter: run the proven native AV relay by camera stable_id.

The future Add-on will call the reusable camera/runtime core directly. This
small CLI exists only to prove Phase 6B without modifying production streams or
re-introducing camera-name/model whitelists.

For long-running HA OS diagnostics this adapter converts the relay's existing
secret-safe terminal summary and exception type into distinct process exit
codes. It also annotates the relay-owned child-state marker with one fixed,
secret-safe blocking stage so a post-start watchdog stall can distinguish a
native source wait from a blocked FFmpeg input pipe. Exception messages, raw
logs, PIDs, command lines, credentials, DIDs and device keys are never written
to the marker.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, BinaryIO, Callable

import yi_camera_runtime
import yi_native_av_relay as relay


EXIT_NATIVE_WORKER = 81
EXIT_MPEGTS_MUX = 82
EXIT_NO_VIDEO_FRAMES = 83
EXIT_NO_AUDIO_FRAMES = 84
EXIT_RELAY_EXCEPTION = 85
EXIT_RELAY_FAILURE_UNCLASSIFIED = 86
EXIT_RELAY_EOF = 87
EXIT_RELAY_RUNTIME_ERROR = 88
EXIT_RELAY_TIMEOUT = 89
EXIT_RELAY_BROKEN_PIPE = 90
EXIT_RELAY_OS_ERROR = 91
EXIT_RELAY_VALUE_ERROR = 92
EXIT_RELAY_NATIVE_STREAM_HEADER = 93
EXIT_RELAY_NATIVE_MEDIA_RECORD = 94
EXIT_RELAY_AUDIO_UNIT_VALIDATION = 95
EXIT_RELAY_AUDIO_FORMAT_CHANGED = 96
EXIT_RELAY_VIDEO_UNIT_VALIDATION = 97
EXIT_RELAY_WORKER_PIPE_SETUP = 98

SAFE_RELAY_STAGES = {
    "native_header_read",
    "native_payload_read",
    "audio_pipe_write",
    "video_pipe_write",
    "mux_starting",
    "audio_processing",
    "video_processing",
}

_NATIVE_SUMMARY_RE = re.compile(
    r"native_worker_exit=(-?\d+); mpegts_mux_exit=(-?\d+); "
    r"video_frames=(\d+); audio_frames=(\d+)"
)

_AUDIO_RUNTIME_ERRORS = {
    "malformed TNP v2 audio unit",
    "TNP audio size mismatch",
    "native relay expected AAC codec id 138",
    "TNP audio AES key is not 16 bytes",
    "decrypted AAC payload has no native ADTS header",
    "invalid native ADTS sample-rate index",
}


class _StagePipe:
    """Transparent pipe proxy that exposes only a fixed blocking stage."""

    def __init__(
        self,
        stream: BinaryIO,
        stage: str,
        set_stage: Callable[[str], None],
    ) -> None:
        self._stream = stream
        self._stage = stage
        self._set_stage = set_stage

    def write(self, data: bytes) -> int | None:
        self._set_stage(self._stage)
        try:
            return self._stream.write(data)
        finally:
            self._set_stage("native_header_read")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _write_safe_child_state_marker(
    qemu_alive: bool,
    ffmpeg_alive: bool,
    relay_stage: str,
) -> None:
    """Atomically publish fixed child booleans plus one allowlisted stage."""
    if relay_stage not in SAFE_RELAY_STAGES:
        relay_stage = "native_header_read"
    raw = os.getenv(relay.CHILD_STATE_MARKER_ENV, "").strip()
    if not raw:
        return
    path = Path(raw)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            f"qemu_alive={1 if qemu_alive else 0}\n"
            f"ffmpeg_alive={1 if ffmpeg_alive else 0}\n"
            f"relay_stage={relay_stage}\n",
            encoding="ascii",
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except (OSError, UnicodeError):
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _classify_relay_failure(
    rc: int,
    summary: tuple[int, int, int, int] | None,
) -> tuple[int, str | None]:
    """Map relay rc=1 to a secret-safe diagnostic stage/code."""
    if rc != 1:
        return rc, None
    if summary is None:
        return EXIT_RELAY_FAILURE_UNCLASSIFIED, "relay_failure_unclassified"

    native_rc, mux_rc, video_frames, audio_frames = summary
    if native_rc != 0:
        return EXIT_NATIVE_WORKER, "native_worker_exit"
    if mux_rc != 0:
        return EXIT_MPEGTS_MUX, "mpegts_mux_exit"
    if video_frames == 0:
        return EXIT_NO_VIDEO_FRAMES, "no_video_frames"
    if audio_frames == 0:
        return EXIT_NO_AUDIO_FRAMES, "no_audio_frames"
    return EXIT_RELAY_FAILURE_UNCLASSIFIED, "relay_validation_failure"


def _classify_runtime_error(exc: RuntimeError) -> tuple[int, str]:
    """Classify only known relay RuntimeErrors without exposing their text."""
    message = str(exc)
    if message in {"truncated native stream header", "invalid native stream framing"}:
        return EXIT_RELAY_NATIVE_STREAM_HEADER, "relay_native_stream_header"
    if message == "invalid native media record":
        return EXIT_RELAY_NATIVE_MEDIA_RECORD, "relay_native_media_record"
    if message in _AUDIO_RUNTIME_ERRORS:
        return EXIT_RELAY_AUDIO_UNIT_VALIDATION, "relay_audio_unit_validation"
    if message == "AAC format changed during live session":
        return EXIT_RELAY_AUDIO_FORMAT_CHANGED, "relay_audio_format_changed"
    if (
        message.startswith("Phase 2E expected H.264 codec id 78, got ")
        or message == "Phase 2E received an unrecognized H.264 payload framing"
    ):
        return EXIT_RELAY_VIDEO_UNIT_VALIDATION, "relay_video_unit_validation"
    if message == "failed to create native worker pipes":
        return EXIT_RELAY_WORKER_PIPE_SETUP, "relay_worker_pipe_setup"
    return EXIT_RELAY_RUNTIME_ERROR, "relay_runtime_error"


def _classify_relay_exception(exc: Exception) -> tuple[int, str]:
    """Classify an uncaught relay exception without exposing its message."""
    if isinstance(exc, EOFError):
        return EXIT_RELAY_EOF, "relay_eof"
    if isinstance(exc, subprocess.TimeoutExpired):
        return EXIT_RELAY_TIMEOUT, "relay_timeout"
    if isinstance(exc, BrokenPipeError):
        return EXIT_RELAY_BROKEN_PIPE, "relay_broken_pipe"
    if isinstance(exc, OSError):
        return EXIT_RELAY_OS_ERROR, "relay_os_error"
    if isinstance(exc, ValueError):
        return EXIT_RELAY_VALUE_ERROR, "relay_value_error"
    if isinstance(exc, RuntimeError):
        return _classify_runtime_error(exc)
    return EXIT_RELAY_EXCEPTION, "relay_exception"


def main() -> int:
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--stable-id", required=True)
    selected, remaining = selector.parse_known_args()

    stable_id = selected.stable_id.strip()
    if not stable_id:
        raise SystemExit("--stable-id must not be empty")

    def fresh_stable_target(timeout: float) -> tuple[Any, dict[str, Any]]:
        material, descriptor = yi_camera_runtime.runtime_material_for(
            stable_id,
            timeout=timeout,
        )
        safe = descriptor.safe_dict()
        return material, {
            "selected_camera": descriptor.name,
            "stable_id": descriptor.stable_id,
            "raw_model": descriptor.raw_model,
            "normalized_model": descriptor.normalized_model,
            "p2p_type": 2,
            "cloud_online_reported": descriptor.cloud_online_reported,
            "p2p_encrypt": descriptor.encrypted,
            "wakeup": descriptor.wakeup,
            "profile_candidate": descriptor.profile_candidate,
            "evidence": "PHASE6_STABLE_ID_RUNTIME",
            "safe_descriptor": safe,
        }

    original_resolver = relay.phase3e._fresh_exact_target
    original_log = relay.log
    original_argv = sys.argv
    original_marker_writer = relay._write_child_state_marker
    original_read_exact = relay.read_exact
    original_decrypt_audio = relay.decrypt_audio_unit
    original_start_ffmpeg = relay.start_ffmpeg
    original_decode_video = relay.yi_live_relay._decode_video_unit
    native_summary: tuple[int, int, int, int] | None = None
    relay_stage = "native_header_read"

    def set_stage(stage: str) -> None:
        nonlocal relay_stage
        relay_stage = stage if stage in SAFE_RELAY_STAGES else "native_header_read"

    def diagnostic_log(message: str) -> None:
        nonlocal native_summary
        match = _NATIVE_SUMMARY_RE.fullmatch(message)
        if match is not None:
            native_summary = tuple(int(value) for value in match.groups())  # type: ignore[assignment]
        original_log(message)

    def diagnostic_marker_writer(qemu_alive: bool, ffmpeg_alive: bool) -> None:
        _write_safe_child_state_marker(qemu_alive, ffmpeg_alive, relay_stage)

    def diagnostic_read_exact(stream: BinaryIO, length: int) -> bytes:
        set_stage("native_payload_read")
        try:
            return original_read_exact(stream, length)
        finally:
            set_stage("native_header_read")

    def diagnostic_decrypt_audio(raw: bytes, password: str):
        set_stage("audio_processing")
        try:
            return original_decrypt_audio(raw, password)
        finally:
            set_stage("native_header_read")

    def diagnostic_decode_video(channel: int, raw: bytes, password: str, encrypted: bool):
        set_stage("video_processing")
        try:
            return original_decode_video(channel, raw, password, encrypted)
        finally:
            set_stage("native_header_read")

    def diagnostic_start_ffmpeg(
        ffmpeg: str,
        output: BinaryIO | None,
        video_offset_ms: int,
        audio_offset_ms: int,
    ):
        set_stage("mux_starting")
        try:
            mux, video_pipe, audio_pipe = original_start_ffmpeg(
                ffmpeg,
                output,
                video_offset_ms,
                audio_offset_ms,
            )
            return (
                mux,
                _StagePipe(video_pipe, "video_pipe_write", set_stage),
                _StagePipe(audio_pipe, "audio_pipe_write", set_stage),
            )
        finally:
            set_stage("native_header_read")

    try:
        relay.phase3e._fresh_exact_target = fresh_stable_target
        relay.log = diagnostic_log
        relay._write_child_state_marker = diagnostic_marker_writer
        relay.read_exact = diagnostic_read_exact
        relay.decrypt_audio_unit = diagnostic_decrypt_audio
        relay.start_ffmpeg = diagnostic_start_ffmpeg
        relay.yi_live_relay._decode_video_unit = diagnostic_decode_video
        sys.argv = [original_argv[0], *remaining]
        set_stage("native_header_read")
        try:
            rc = relay.main()
        except Exception as exc:
            diagnostic_rc, stage = _classify_relay_exception(exc)
            original_log(
                f"safe_failure_stage={stage}; "
                f"exception_type={type(exc).__name__}; diagnostic_exit_code={diagnostic_rc}"
            )
            return diagnostic_rc

        diagnostic_rc, stage = _classify_relay_failure(rc, native_summary)
        if stage is not None:
            original_log(
                f"safe_failure_stage={stage}; diagnostic_exit_code={diagnostic_rc}"
            )
        return diagnostic_rc
    finally:
        relay.phase3e._fresh_exact_target = original_resolver
        relay.log = original_log
        relay._write_child_state_marker = original_marker_writer
        relay.read_exact = original_read_exact
        relay.decrypt_audio_unit = original_decrypt_audio
        relay.start_ffmpeg = original_start_ffmpeg
        relay.yi_live_relay._decode_video_unit = original_decode_video
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
