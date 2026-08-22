"""Controlled Phase 2F quality probe for one YI TNP resolution value.

Runs the already-proven Android PPPP/TNP relay for a short finite interval,
changes only the resolution value sent in commands 4881 and 9029, writes a
raw H.264 Annex-B sample, and asks ffprobe for the decoded dimensions.

No credentials or camera identifiers are printed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yi_live_relay as relay
import yi_tnp_oracle as oracle


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Probe one YI TNP live-view resolution value")
    p.add_argument("--target", choices=relay.ALLOWED_TARGETS, default=relay.DEFAULT_TARGET)
    p.add_argument("--resolution", type=int, required=True, choices=range(0, 5))
    p.add_argument("--duration", type=int, default=10, choices=range(5, 31))
    p.add_argument("--env-file", type=Path, default=Path(".env.local"))
    p.add_argument("--timeout", type=float, default=10.0)
    default_adb = shutil.which("adb")
    p.add_argument("--adb", type=Path, default=Path(default_adb) if default_adb else None)
    p.add_argument("--apk", type=Path, default=Path("oracle/android/build/yi-tnp-oracle.apk"))
    return p


def ffprobe_dimensions(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe was not found")
    proc = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,profile,level",
            "-of", "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    value = json.loads(proc.stdout)
    streams = value.get("streams")
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        raise RuntimeError("ffprobe did not find a video stream")
    return streams[0]


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    material: oracle.CameraMaterial | None = None
    output_path: Path | None = None

    try:
        if not args.env_file.is_file():
            raise RuntimeError(".env.local is missing")
        if args.adb is None:
            raise RuntimeError("adb was not found")

        oracle.load_env_file(args.env_file)
        oracle.APPROVED_TARGETS = (args.target, args.target)
        material, preflight = oracle.fresh_cloud_preflight(args.timeout)
        relay._safe_identity(material, preflight, args.target)

        # The Android oracle already takes its resolution from the host config.
        # Change only this one runtime value; startup order/auth/transport remain
        # exactly the proven Phase 2C.3 / Phase 2E path.
        original_resolution = oracle.OFFICIAL_DEFAULT_RESOLUTION
        oracle.OFFICIAL_DEFAULT_RESOLUTION = args.resolution

        captures = Path("captures")
        captures.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = captures / f"quality-r{args.resolution}-{stamp}.h264"

        try:
            with output_path.open("xb") as sink:
                report = relay.run_relay(
                    material,
                    preflight,
                    args.adb,
                    args.apk,
                    args.duration,
                    sink,
                )
        finally:
            oracle.OFFICIAL_DEFAULT_RESOLUTION = original_resolution

        stream = ffprobe_dimensions(output_path)
        live_seconds = float(report.get("live_video_seconds", 0.0) or 0.0)
        emitted_bytes = int(report.get("emitted_bytes", 0) or 0)
        approx_kbps = round((emitted_bytes * 8 / 1000) / live_seconds, 1) if live_seconds > 0 else None

        result = {
            "target": args.target,
            "requested_resolution_value": args.resolution,
            "PPPP_mode": report.get("PPPP_mode"),
            "TNP_authentication": report.get("TNP_authentication"),
            "codec": stream.get("codec_name"),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "profile": stream.get("profile"),
            "level": stream.get("level"),
            "live_video_seconds": report.get("live_video_seconds"),
            "emitted_frames": report.get("emitted_frames"),
            "emitted_bytes": emitted_bytes,
            "approx_kbps": approx_kbps,
            "oracle_finished": report.get("oracle_finished"),
            "sample_path": str(output_path),
        }
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    except Exception as failure:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "category": "quality_probe_failed",
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
