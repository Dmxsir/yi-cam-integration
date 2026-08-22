#!/usr/bin/env python3
"""Secret-safe host coordinator for the Phase 3D PPPP connect probe.

Fresh cloud material is obtained on the Linux host, but DID / InitString /
device key are passed to the Bionic/QEMU probe only through stdin. They never
appear in argv or normal diagnostics. The exact target is mandatory; no camera
fallback is permitted.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yi_cloud_probe as cloud
import yi_tnp_oracle as oracle


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def _fresh_exact_target(target: str, timeout: float = 10.0) -> tuple[oracle.CameraMaterial, dict[str, Any]]:
    """Fetch fresh PPPP material for exactly one named camera, with no fallback.

    Phase 2C's shared helper intentionally allows an approved fallback camera and
    historically required the raw cloud model to equal ``83``. Phase 3D must be
    stricter about identity but more tolerant of equivalent cloud model encoding:
    the exact name must match, the normalized model must still be y291ga, the
    transport must still be type-2/TNP, and the camera must be online.
    """

    region = os.getenv("YI_REGION", "eu").casefold()
    country = _required_env("YI_COUNTRY").upper()
    if region != "eu" or country != "IL":
        raise RuntimeError("Phase 3D is restricted to the explicitly configured EU/IL account")

    host = cloud.GATEWAY_HOSTS[region]
    headers = cloud.request_headers(
        country,
        _required_env("YI_DEVICE_MODEL"),
        _required_env("YI_ANDROID_VERSION"),
        _required_env("YI_LANGUAGE"),
    )
    account = _required_env("YI_ACCOUNT")
    account_password = _required_env("YI_PASSWORD")

    login, login_diag = cloud.get_json(
        host,
        "/v4/users/login",
        cloud.login_params(
            region,
            account,
            account_password,
            _required_env("YI_DEVICE_BRAND"),
            _required_env("YI_DEVICE_MODEL"),
            _required_env("YI_ANDROID_VERSION"),
        ),
        headers,
        timeout,
        auth_request=True,
    )
    login_data = login.get("data")
    if not isinstance(login_data, dict):
        raise RuntimeError("Unexpected login schema")
    user_id = cloud._user_id(login_data.get("userid"))
    token = login_data.get("token")
    token_secret = login_data.get("token_secret")
    if user_id is None or not isinstance(token, str) or not token or not isinstance(token_secret, str) or not token_secret:
        raise RuntimeError("Required live authentication state is unavailable")

    devices, devices_diag = cloud.get_json(
        host,
        "/v4/devices/list",
        cloud.device_list_params(user_id, token, token_secret),
        headers,
        timeout,
    )
    cameras = devices.get("data")
    if not isinstance(cameras, list) or not all(isinstance(item, dict) for item in cameras):
        raise RuntimeError("Unexpected devices/list schema")

    selected = next((item for item in cameras if str(item.get("name", "")) == target), None)
    if selected is None:
        raise RuntimeError(f"Exact Phase 3D target {target!r} was not found; fallback refused")

    raw_model = str(selected.get("model", ""))
    normalized = cloud.normalize_model(selected.get("model"), selected.get("did"))
    p2p_type = selected.get("type")
    online = selected.get("online") is True
    if not online or normalized != "y291ga" or p2p_type != 2:
        raise RuntimeError(
            "Phase 3D exact-target identity check failed: "
            f"online={online}, raw_model={raw_model!r}, normalized_model={normalized!r}, p2p_type={p2p_type!r}"
        )

    uid = selected.get("uid")
    if not isinstance(uid, str) or not uid:
        raise RuntimeError("Exact Phase 3D target has no usable cloud UID")

    ipc = cloud._ipc_params(selected)
    p2p_encrypt = cloud._p2p_encrypt(ipc.get("p2p_encrypt"))

    tnp, tnp_diag = cloud.get_json(
        host,
        "/v4/tnp/device_info",
        cloud.tnp_device_info_params(user_id, uid, token, token_secret),
        headers,
        timeout,
    )
    tnp_data = tnp.get("data")
    if not isinstance(tnp_data, dict):
        raise RuntimeError("Unexpected tnp/device_info schema")

    pppp_did = tnp_data.get("DID")
    server = tnp_data.get("InitString")
    license_value = tnp_data.get("License")
    if not all(isinstance(value, str) and value for value in (pppp_did, server, license_value)):
        raise RuntimeError("Exact Phase 3D target is missing required TNP connection material")
    device_key = license_value.split(":", 1)[0]
    if not device_key:
        raise RuntimeError("TNP license has no usable device-key component")

    material = oracle.CameraMaterial(
        name=target,
        raw_model=raw_model,
        normalized_model=normalized,
        cloud_uid=uid,
        pppp_did=pppp_did,
        server=server,
        device_key=device_key,
        password="",
        encrypted=p2p_encrypt,
        wakeup=ipc.get("wakeup") is True,
    )
    report = {
        "selected_camera": target,
        "raw_model": raw_model,
        "normalized_model": normalized,
        "p2p_type": p2p_type,
        "cloud_online": online,
        "DID": "AVAILABLE",
        "InitString": "AVAILABLE",
        "license_device_key": "AVAILABLE",
        "p2p_encrypt": p2p_encrypt,
        "wakeup": material.wakeup,
        "gateway": host,
        "requests": [login_diag, devices_diag, tnp_diag],
        "evidence": "LIVE_CLOUD_EXACT_TARGET",
    }

    # Remove references to account/session secrets before returning. The
    # CameraMaterial keeps only the minimum connection material needed by the
    # child probe and is cleared in main()'s finally block.
    del account_password, token, token_secret, license_value, tnp_data, login, devices, tnp
    return material, report


def _field(value: str) -> bytes:
    raw = value.encode("utf-8")
    if not raw or len(raw) >= 4096 or b"\0" in raw:
        raise RuntimeError("Phase 3D connection material has an invalid shape")
    return raw


def _payload(material: oracle.CameraMaterial) -> bytes:
    did = _field(material.pppp_did)
    server = _field(material.server)
    key = _field(material.device_key)
    header = b"Y3D1" + bytes((1 if material.wakeup else 0, 0x4B)) + struct.pack(">HIII", 0, len(did), len(server), len(key))
    return header + did + server + key


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
            raise RuntimeError("Phase 3D exact-target selection invariant failed")
        if (
            material.normalized_model != "y291ga"
            or preflight.get("p2p_type") != 2
            or preflight.get("cloud_online") is not True
        ):
            raise RuntimeError("Phase 3D exact-target identity check failed after preflight")

        secret_values = tuple(
            value.encode("utf-8")
            for value in (material.pppp_did, material.server, material.device_key)
            if value
        )
        payload = _payload(material)
        exe = args.target_dir / "android_pppp_connect_probe"
        if not exe.is_file():
            raise RuntimeError(f"Phase 3D probe executable missing: {exe}")

        print("phase3d_host=START")
        print(f"target={material.name}")
        print(f"raw_cloud_model={material.raw_model}")
        print(f"model={material.normalized_model}")
        print(f"wakeup={str(material.wakeup).lower()}")
        print("connection_flag=0x4B")
        print("secret_transport=stdin_only")
        print("phone_required=false")

        command = [
            args.qemu,
            "-L",
            str(args.runtime),
            "-E",
            "LD_LIBRARY_PATH=/data/local/tmp/yi-phase3d:/system/lib64",
            str(exe),
            "/data/local/tmp/yi-phase3d/libPPPP_API.so",
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
            print("PHASE3D_CONNECT=TIMEOUT", file=sys.stderr)
            return 124

        combined = proc.stdout + b"\n" + proc.stderr
        if any(secret in combined for secret in secret_values):
            raise RuntimeError("Phase 3D child attempted to expose secret connection material")

        if proc.stdout:
            sys.stdout.buffer.write(proc.stdout)
            if not proc.stdout.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            if not proc.stderr.endswith(b"\n"):
                sys.stderr.buffer.write(b"\n")

        print(f"probe_exit_code={proc.returncode}")
        if proc.returncode == 0 and b"phase3d_connect_probe=PASS" in proc.stdout:
            print("PHASE3D_CONNECT=PASS")
            return 0
        print("PHASE3D_CONNECT=FAIL")
        return proc.returncode if proc.returncode else 1
    finally:
        if material is not None:
            material.clear()


if __name__ == "__main__":
    raise SystemExit(main())
