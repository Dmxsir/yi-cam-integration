#!/usr/bin/env python3
"""Development adapter: run the proven native AV relay by camera stable_id.

The future Add-on will call the reusable camera/runtime core directly. This
small CLI exists only to prove Phase 6B without modifying production streams or
re-introducing camera-name/model whitelists.

For long-running HA OS diagnostics this adapter also converts the relay's
existing secret-safe terminal summary into distinct process exit codes. The
lifecycle manager already exposes the last exit code, so this gives Home
Assistant useful failure-stage observability without exposing raw runtime logs,
credentials, DIDs, device keys or camera material.
"""

from __future__ import annotations

import argparse
import re
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

_NATIVE_SUMMARY_RE = re.compile(
    r"native_worker_exit=(-?\d+); mpegts_mux_exit=(-?\d+); "
    r"video_frames=(\d+); audio_frames=(\d+)"
)


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
            # Do not emit the exception message: it may contain runtime material.
            # The type and fixed stage label are sufficient for the next
            # diagnostic gate and are safe to surface through logs/status.
            original_log(
                "safe_failure_stage=relay_exception; "
                f"exception_type={type(exc).__name__}; diagnostic_exit_code={EXIT_RELAY_EXCEPTION}"
            )
            return EXIT_RELAY_EXCEPTION

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
