#!/usr/bin/env python3
"""Secret-safe host coordinator for Phase 3E3 native audio-channel smoke.

The exact warehouse camera is connected through the proven Bionic PPPP/TNP
path. The normal 4881 -> 9029 -> 768 startup burst is preserved, 4882 auth is
verified in the native child, and one complete TNP unit is consumed from PPPP
channel 1. Only outer TNP audio metadata is printed; compressed audio bytes are
consumed and discarded in this smoke phase.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = Path(__file__).resolve().parent
for path in (ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_phase3e_tnp as phase3e
import yi_tnp_oracle as oracle


def _payload(material: oracle.CameraMaterial, units: tuple[bytes, bytes, bytes, bytes]) -> bytes:
    did = phase3e._field(material.pppp_did)
    server = phase3e._field(material.server)
    key = phase3e._field(material.device_key)
    lengths = (len(did), len(server), len(key), *(len(unit) for unit in units))
    header = b"Y3A1" + bytes((1 if material.wakeup else 0, phase3e.CONNECTION_FLAG)) + struct.pack(">H", 0)
    header += struct.pack(">IIIIIII", *lengths)
    return header + did + server + key + b"".join(units)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--qemu", default="qemu-aarch64")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    if not args.env_file.is_file():
        raise RuntimeError(f"env file not found: {args.env_file}")

    oracle.load_env_file(args.env_file)
    material: oracle.CameraMaterial | None = None
    try:
        material, preflight = phase3e._fresh_exact_target(timeout=10.0)
        units = phase3e._build_units(material)
        payload = _payload(material, units)
        exe = args.target_dir / "android_pppp_audio_probe"
        if not exe.is_file():
            raise RuntimeError(f"Phase 3E3 probe executable missing: {exe}")

        secret_values = [
            value.encode("utf-8")
            for value in (material.cloud_uid, material.pppp_did, material.server, material.device_key, material.password)
            if value
        ]
        for unit in units:
            auth = unit[16:48].rstrip(b"\0")
            if auth:
                secret_values.append(auth)

        print("phase3e3_host=START")
        print(f"target={material.name}")
        print(f"raw_cloud_model={material.raw_model}")
        print(f"model={material.normalized_model}")
        print(f"cloud_online_reported={str(preflight['cloud_online_reported']).lower()}")
        print("runtime_reachability_source=PPPP_transport")
        print("audio_channel=1")
        print("audio_start_command=768")
        print("expected_tnp_io_type=2")
        print("audio_codec=NOT_CLASSIFIED_YET")
        print("media_bytes_logged=false")
        print("secret_transport=stdin_only")
        print("phone_required=false")

        command = [
            args.qemu,
            "-L",
            str(args.runtime),
            "-E",
            "LD_LIBRARY_PATH=/data/local/tmp/yi-phase3e3:/system/lib64",
            str(exe),
            "/data/local/tmp/yi-phase3e3/libPPPP_API.so",
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
            print("PHASE3E3_AUDIO=TIMEOUT", file=sys.stderr)
            return 124

        combined = proc.stdout + b"\n" + proc.stderr
        if any(secret and secret in combined for secret in secret_values):
            raise RuntimeError("Phase 3E3 child attempted to expose secret connection/auth material")

        if proc.stdout:
            sys.stdout.buffer.write(proc.stdout)
            if not proc.stdout.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            if not proc.stderr.endswith(b"\n"):
                sys.stderr.buffer.write(b"\n")

        print(f"probe_exit_code={proc.returncode}")
        if proc.returncode == 0 and b"phase3e3_audio_probe=PASS" in proc.stdout:
            print("PHASE3E3_AUDIO=PASS")
            return 0
        print("PHASE3E3_AUDIO=FAIL")
        return proc.returncode if proc.returncode else 1
    finally:
        if material is not None:
            material.clear()


if __name__ == "__main__":
    raise SystemExit(main())
