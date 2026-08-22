#!/usr/bin/env python3
"""Secret-safe host coordinator for the Phase 3D PPPP_Check probe."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yi_tnp_oracle as oracle
from tools.phase3_pppp_probe.run_phase3d_connect import _fresh_exact_target, _payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--qemu", default="qemu-aarch64")
    parser.add_argument("--target", default="מחסן")
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    if not args.env_file.is_file():
        raise RuntimeError(f"env file not found: {args.env_file}")

    oracle.load_env_file(args.env_file)
    material: oracle.CameraMaterial | None = None
    try:
        material, preflight = _fresh_exact_target(args.target, timeout=10.0)
        if material.name != args.target:
            raise RuntimeError("Phase 3D check exact-target selection invariant failed")
        if (
            material.normalized_model != "y291ga"
            or preflight.get("p2p_type") != 2
            or preflight.get("cloud_online") is not True
        ):
            raise RuntimeError("Phase 3D check exact-target identity check failed")

        secret_values = tuple(
            value.encode("utf-8")
            for value in (material.pppp_did, material.server, material.device_key)
            if value
        )
        payload = _payload(material)
        exe = args.target_dir / "android_pppp_check_probe"
        if not exe.is_file():
            raise RuntimeError(f"Phase 3D check probe executable missing: {exe}")

        print("phase3d_check_host=START")
        print(f"target={material.name}")
        print(f"raw_cloud_model={material.raw_model}")
        print(f"model={material.normalized_model}")
        print("check_scope=PPPP_Check_only_after_connect")
        print("session_fields_logged=false")
        print("secret_transport=stdin_only")
        print("phone_required=false")

        command = [
            args.qemu,
            "-L",
            str(args.runtime),
            "-E",
            "LD_LIBRARY_PATH=/data/local/tmp/yi-phase3d-check:/system/lib64",
            str(exe),
            "/data/local/tmp/yi-phase3d-check/libPPPP_API.so",
        ]
        try:
            proc = subprocess.run(
                command,
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=args.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print("PHASE3D_CHECK=TIMEOUT", file=sys.stderr)
            return 124

        combined = proc.stdout + b"\n" + proc.stderr
        if any(secret in combined for secret in secret_values):
            raise RuntimeError("Phase 3D check child attempted to expose secret connection material")

        if proc.stdout:
            sys.stdout.buffer.write(proc.stdout)
            if not proc.stdout.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            if not proc.stderr.endswith(b"\n"):
                sys.stderr.buffer.write(b"\n")

        print(f"probe_exit_code={proc.returncode}")
        if proc.returncode == 0 and b"phase3d_check_probe=PASS" in proc.stdout:
            print("PHASE3D_CHECK=PASS")
            return 0
        print("PHASE3D_CHECK=FAIL")
        return proc.returncode if proc.returncode else 1
    finally:
        if material is not None:
            material.clear()


if __name__ == "__main__":
    raise SystemExit(main())
