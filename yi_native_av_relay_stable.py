#!/usr/bin/env python3
"""Development adapter: run the proven native AV relay by camera stable_id.

The future Add-on will call the reusable camera/runtime core directly. This
small CLI exists only to prove Phase 6B without modifying production streams or
re-introducing camera-name/model whitelists.

For long-running HA OS diagnostics this adapter also converts the relay's
existing secret-safe terminal summary and exception type into distinct process
exit codes. Known hard-coded RuntimeError messages are classified internally
into fixed safe stages; the exception message itself is never emitted. The
lifecycle manager already exposes the last exit code, so Home Assistant gets
useful failure-stage observability without exposing raw runtime logs,
credentials, DIDs, device keys or camera material.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Any

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

    # Keep the proven relay/mux/worker unchanged. Only replace its Phase 3
    # name/model-specific material resolver with the generic stable-id provider.
    original_resolver = relay.phase3e._fresh_exact_target
    original_log = relay.log
    original_argv = sys.argv
    native_summary: tuple[int, int, int, int] | None = None

    def diagnostic_log(message: str) -> None:
        nonlocal native_summary
        match = _NATIVE_SUMMARY_RE.fullmatch(message)
        if match is not None:
            native_summary = tuple(int(value) for value in match.groups())  # type: ignore[assignment]
        original_log(message)

    try:
        relay.phase3e._fresh_exact_target = fresh_stable_target
        relay.log = diagnostic_log
        sys.argv = [original_argv[0], *remaining]
        try:
            rc = relay.main()
        except Exception as exc:
            # Never emit the exception message: it may contain runtime material.
            # Exception class plus a fixed stage/code is sufficient for diagnosis.
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
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
