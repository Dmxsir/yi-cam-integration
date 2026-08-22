"""Phase 2G production supervisor for the proven YI y291ga live relay.

The underlying Android oracle remains a finite session engine. This supervisor
turns it into an effectively continuous source for go2rtc by rotating long
sessions, refreshing cloud/TNP connection material before every session, and
reconnecting automatically after transient failures while keeping the H.264
stdout pipe open.

The consumer lifecycle remains on-demand: go2rtc starts this process only when
a client asks for the stream and stops it with SIGINT when the last consumer
leaves. All diagnostics are secret-safe and go to stderr; stdout contains H.264
Annex-B bytes only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO

import yi_live_relay as relay
import yi_tnp_oracle as oracle

DEFAULT_TARGET = "מחסן"
DEFAULT_RESOLUTION = 1  # Proven y291ga 1920x1080 / H.264 High profile.
DEFAULT_SESSION_SECONDS = 86_400
DEFAULT_RECONNECT_BASE = 2.0
DEFAULT_RECONNECT_MAX = 30.0
CONSUMER_CLOSED_MESSAGE = "H.264 consumer closed the output pipe"


def _log(message: str) -> None:
    print(f"[yi-production-relay] {message}", file=sys.stderr, flush=True)


def retry_delay(failure_count: int, base: float = DEFAULT_RECONNECT_BASE, maximum: float = DEFAULT_RECONNECT_MAX) -> float:
    if failure_count <= 0:
        return 0.0
    if base <= 0 or maximum <= 0:
        raise ValueError("reconnect delays must be positive")
    return min(maximum, base * (2 ** (failure_count - 1)))


def is_consumer_closed(failure: BaseException) -> bool:
    return isinstance(failure, RuntimeError) and str(failure) == CONSUMER_CLOSED_MESSAGE


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase 2G continuous YI -> H.264 production relay")
    p.add_argument("--target", choices=relay.ALLOWED_TARGETS, default=DEFAULT_TARGET)
    p.add_argument("--env-file", type=Path, default=Path(".env.local"))
    p.add_argument("--timeout", type=float, default=10.0)
    default_adb = shutil.which("adb")
    p.add_argument("--adb", type=Path, default=Path(default_adb) if default_adb else None)
    p.add_argument("--apk", type=Path, default=Path("oracle/android/build/yi-tnp-oracle.apk"))
    p.add_argument(
        "--resolution",
        type=int,
        default=DEFAULT_RESOLUTION,
        choices=range(0, 5),
        help="YI TNP quality value; y291ga value 1 is proven 1920x1080",
    )
    p.add_argument(
        "--session-seconds",
        type=int,
        default=DEFAULT_SESSION_SECONDS,
        help="planned native session rotation interval; the supervisor itself has no duration limit",
    )
    p.add_argument("--reconnect-base", type=float, default=DEFAULT_RECONNECT_BASE)
    p.add_argument("--reconnect-max", type=float, default=DEFAULT_RECONNECT_MAX)
    p.add_argument("--reorder-pending", type=int, default=24)
    p.add_argument("--reorder-wait", type=float, default=0.35)
    p.add_argument("--stdout", action="store_true", help="required for go2rtc; emit H.264 bytes only")
    return p


def _validate_args(args: argparse.Namespace) -> None:
    if not args.stdout:
        raise RuntimeError("production relay requires --stdout")
    if not args.env_file.is_file():
        raise RuntimeError(".env.local is missing")
    if args.adb is None or not args.adb.is_file():
        raise RuntimeError("adb was not found; pass --adb explicitly")
    if not args.apk.is_file():
        raise RuntimeError("the built Android oracle APK is missing")
    if args.session_seconds < 60 or args.session_seconds > 604_800:
        raise RuntimeError("--session-seconds must be between 60 and 604800")
    if args.reconnect_base <= 0 or args.reconnect_max <= 0 or args.reconnect_base > args.reconnect_max:
        raise RuntimeError("invalid reconnect delay settings")


def _fresh_material(args: argparse.Namespace) -> tuple[oracle.CameraMaterial, dict[str, Any]]:
    oracle.APPROVED_TARGETS = (args.target, args.target)
    material, preflight = oracle.fresh_cloud_preflight(args.timeout)
    relay._safe_identity(material, preflight, args.target)
    return material, preflight


def supervise(args: argparse.Namespace, sink: BinaryIO) -> int:
    failures = 0
    session_number = 0

    while True:
        material: oracle.CameraMaterial | None = None
        try:
            material, preflight = _fresh_material(args)
            session_number += 1
            _log(
                f"session={session_number}; target={args.target}; resolution={args.resolution}; "
                f"planned_rotation={args.session_seconds}s"
            )

            report = relay.run_relay(
                material,
                preflight,
                args.adb,
                args.apk,
                args.session_seconds,
                sink,
                args.resolution,
                args.reorder_pending,
                args.reorder_wait,
            )

            failures = 0
            _log(
                json.dumps(
                    {
                        "event": "session_rotation",
                        "session": session_number,
                        "PPPP_mode": report.get("PPPP_mode"),
                        "TNP_authentication": report.get("TNP_authentication"),
                        "live_video_seconds": report.get("live_video_seconds"),
                        "emitted_frames": report.get("emitted_frames"),
                        "emitted_bytes": report.get("emitted_bytes"),
                        "oracle_finished": report.get("oracle_finished"),
                    },
                    sort_keys=True,
                )
            )
            # Planned rotation is intentionally immediate. A new cloud preflight
            # refreshes DID/server/license state before the next PPPP session.
            continue

        except Exception as failure:
            if is_consumer_closed(failure):
                _log("consumer closed output pipe; stopping on-demand source")
                return 0

            failures += 1
            delay = retry_delay(failures, args.reconnect_base, args.reconnect_max)
            _log(
                json.dumps(
                    {
                        "event": "session_retry",
                        "session": session_number,
                        "exception_type": failure.__class__.__name__,
                        "failure_count": failures,
                        "reconnect_in_seconds": delay,
                    },
                    sort_keys=True,
                )
            )
            time.sleep(delay)
        finally:
            if material is not None:
                material.clear()


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        _validate_args(args)
        oracle.load_env_file(args.env_file)
        return supervise(args, sys.stdout.buffer)
    except KeyboardInterrupt:
        _log("shutdown requested; Android/PPPP cleanup completed")
        return 0
    except Exception as failure:
        _log(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "category": "phase_2g_failed",
                        "exception_type": failure.__class__.__name__,
                    },
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
