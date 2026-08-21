"""Single-attempt Phase 2C.3 runner for an approved y291ga camera.

This wrapper intentionally does not call analyze_capture(). The experiment is
about the startup state machine only: 4881 -> 9029 -> 768 before the first
blocking channel-0 read. It reports secret-safe control/video evidence and
stops after one oracle connection attempt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yi_tnp_oracle as oracle

DEFAULT_TARGET = "POOL"
ALLOWED_TARGETS = ("POOL", "מחסן")
EXPECTED_TNP_VERSION = 2
EXPECTED_STARTUP = (4881, 9029, 768)
REMOTE_CLOSED = -3012


def _event(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next((item for item in report.get("events", []) if item.get("event") == name), {})


def _events(report: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [item for item in report.get("events", []) if item.get("event") == name]


def classify(report: dict[str, Any], target: str = DEFAULT_TARGET) -> dict[str, Any]:
    """Return a secret-safe Phase 2C.3 outcome summary."""
    connect = _event(report, "PPPP_Check")
    auth = _event(report, "TNP_authentication")
    burst = _event(report, "startup_burst")
    reads = _events(report, "PPPP_Read")
    frames = report.get("raw_frame_counts", {})
    channel2 = int(frames.get("channel2", 0) or 0)
    channel3 = int(frames.get("channel3", 0) or 0)
    got_4882 = auth.get("responseCommand") == 4882 and auth.get("authResult") == 0
    remote_closed = any(item.get("returnValue") == REMOTE_CLOSED for item in reads)
    errors = _events(report, "oracle_error")

    if got_4882 and channel2 > 0 and channel3 > 0:
        outcome = "FULL_SUCCESS"
        hypothesis = "SUPPORTED"
    elif got_4882:
        outcome = "CONTROL_SUCCESS"
        hypothesis = "SUPPORTED"
    elif remote_closed:
        outcome = "SAME_FAILURE"
        hypothesis = "WEAKENED"
    elif errors:
        outcome = "DIFFERENT_FAILURE"
        hypothesis = "INCONCLUSIVE"
    elif reads:
        outcome = "PARTIAL_SUCCESS"
        hypothesis = "INCONCLUSIVE"
    else:
        outcome = "DIFFERENT_FAILURE"
        hypothesis = "INCONCLUSIVE"

    timestamps = [
        item.get("timestampNanos")
        for item in report.get("events", [])
        if isinstance(item.get("timestampNanos"), int)
    ]
    session_ms = None
    if len(timestamps) >= 2:
        session_ms = round((max(timestamps) - min(timestamps)) / 1_000_000, 3)

    response_latency_us = auth.get("responseLatencyMicros", "UNKNOWN")
    response_latency_ms: float | str = "UNKNOWN"
    if isinstance(response_latency_us, int):
        response_latency_ms = round(response_latency_us / 1000, 3)

    burst_elapsed_us = burst.get("elapsedMicros", "UNKNOWN")
    burst_elapsed_ms: float | str = "UNKNOWN"
    if isinstance(burst_elapsed_us, int):
        burst_elapsed_ms = round(burst_elapsed_us / 1000, 3)

    return {
        "target": target,
        "fresh_cloud_identity": "VERIFIED"
        if report.get("selected_camera") == target
        and report.get("raw_model") == "83"
        and report.get("normalized_model") == "y291ga"
        and report.get("p2p_type") == 2
        else "FAILED",
        "fresh_online_status": "ONLINE" if report.get("cloud_online") is True else "OFFLINE",
        "camera_attempts": 1,
        "PPPP_connect": "SUCCESS" if connect.get("returnValue") == 0 else "FAIL",
        "PPPP_mode": {0: "DIRECT_P2P", 1: "RELAY", 2: "TCP", 3: "SDEV"}.get(connect.get("mode"), "UNKNOWN"),
        "TNP_version": EXPECTED_TNP_VERSION,
        "transmitted_startup": list(EXPECTED_STARTUP),
        "blocking_read_between_commands": burst.get("blockingReadBetweenCommands", "UNKNOWN"),
        "diagnostic_flush_between_commands": burst.get("diagnosticFlushBetweenCommands", "UNKNOWN"),
        "startup_pppp_write_count": burst.get("ppppWriteCount", "UNKNOWN"),
        "startup_burst_elapsed_ms": burst_elapsed_ms,
        "first_camera_channel0_response": auth.get("responseCommand", "NONE"),
        "first_response_command_number": auth.get("responseCommandNumber", "UNKNOWN"),
        "first_response_latency_ms": response_latency_ms,
        "4882_received": got_4882,
        "channel_2_observed": channel2 > 0,
        "channel_2_units": channel2,
        "channel_3_observed": channel3 > 0,
        "channel_3_units": channel3,
        "remote_-3012": remote_closed,
        "session_duration_ms": session_ms if session_ms is not None else "UNKNOWN",
        "outcome": outcome,
        "startup_burst_hypothesis": hypothesis,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Phase 2C.3 single controlled y291ga retry")
    result.add_argument("command", choices=("preflight", "run"))
    result.add_argument("--target", choices=ALLOWED_TARGETS, default=DEFAULT_TARGET)
    result.add_argument("--env-file", type=Path, default=Path(".env.local"))
    result.add_argument("--timeout", type=float, default=10.0)
    result.add_argument("--adb", type=Path)
    result.add_argument("--apk", type=Path, default=Path("oracle/android/build/yi-tnp-oracle.apk"))
    result.add_argument("--capture-seconds", type=int, default=5, choices=range(5, 16))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    material: oracle.CameraMaterial | None = None
    try:
        if not args.env_file.is_file():
            raise RuntimeError(".env.local is missing")
        oracle.load_env_file(args.env_file)

        # The historical host picks the first online camera from APPROVED_TARGETS.
        # Repeat the explicitly requested camera twice to make selection exact and
        # to prevent automatic fallback to the other y291ga camera.
        oracle.APPROVED_TARGETS = (args.target, args.target)
        material, preflight = oracle.fresh_cloud_preflight(args.timeout)
        if (
            material.name != args.target
            or material.raw_model != "83"
            or material.normalized_model != "y291ga"
            or preflight.get("p2p_type") != 2
            or preflight.get("cloud_online") is not True
        ):
            raise RuntimeError("Phase 2C.3 target identity mismatch")

        if args.command == "preflight":
            print(json.dumps(preflight, indent=2, sort_keys=True, ensure_ascii=False))
            return 0

        if args.adb is None:
            raise RuntimeError("--adb is required for the controlled Android retry")

        report, run_dir = oracle.run_android_oracle(
            material,
            preflight,
            args.adb,
            args.apk,
            args.capture_seconds,
        )
        summary = classify(report, args.target)
        summary["run_dir"] = str(run_dir)
        summary["next_highest_value_step"] = (
            "Inspect the successful control/video evidence before any further protocol change."
            if summary["outcome"] in {"FULL_SUCCESS", "CONTROL_SUCCESS", "PARTIAL_SUCCESS"}
            else "Reassess native/DRW session behavior; do not auto-retry."
        )
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if summary["outcome"] in {"FULL_SUCCESS", "CONTROL_SUCCESS", "PARTIAL_SUCCESS"} else 1
    except Exception as failure:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "category": "phase_2c3_failed",
                        "exception_type": failure.__class__.__name__,
                    },
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if material is not None:
            material.clear()


if __name__ == "__main__":
    raise SystemExit(main())
