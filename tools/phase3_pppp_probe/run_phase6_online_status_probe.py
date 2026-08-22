#!/usr/bin/env python3
"""Secret-safe parity probe for the YI Home TNP online/offline state.

The current official Android client uses PPPP_CheckDevOnline(p2pid,
serverString, 2, int[1]) for TNP devices whose feature configuration enables
onlineStatusP2p. This development probe calls the same native API without
opening a live-view session. DID/server material is passed to the AArch64 worker
through stdin only and is never emitted.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yi_cloud_probe as cloud
import yi_tnp_oracle as oracle
from yi_camera_manager import YiCameraManager

STABLE_ID_RE = re.compile(r"^[0-9a-f]{20}$")


def _field(value: str) -> bytes:
    raw = value.encode("utf-8")
    if not raw or len(raw) >= 4096 or b"\0" in raw:
        raise RuntimeError("TNP online-check material has an invalid shape")
    return raw


def _payload(p2pid: str, server: str) -> bytes:
    did = _field(p2pid)
    init = _field(server)
    return b"YON1" + struct.pack(">II", len(did), len(init)) + did + init


def _parse_worker_output(raw: bytes) -> dict[str, Any]:
    values: dict[str, str] = {}
    text = raw.decode("utf-8", "replace")
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    status = values.get("device_online")
    if status not in {"online", "offline", "unknown"}:
        raise RuntimeError("native online worker returned no valid status")
    try:
        native_rc = int(values.get("PPPP_CheckDevOnline_rc", ""))
        last_online_time = int(values.get("last_online_time", "0"))
    except ValueError as exc:
        raise RuntimeError("native online worker returned malformed diagnostics") from exc
    return {
        "availability_state": status,
        "native_result": native_rc,
        "last_online_time": last_online_time,
    }


def _safe_epoch(value: int) -> str | None:
    # The official response carries a 32-bit lastOnlineTime. Convert only
    # plausible Unix seconds; preserve zero/unknown without inventing a date.
    if value < 946684800 or value > 4102444800:
        return None
    return datetime.fromtimestamp(value, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_scalar(value: Any) -> str | int | bool | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe YI TNP online status using the official PPPP_CheckDevOnline path")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True, help="host path used only for preflight existence checking")
    parser.add_argument("--guest-library", default="/data/local/tmp/yi-online-status/libPPPP_API.so")
    parser.add_argument("--qemu", default="qemu-aarch64")
    parser.add_argument("--camera-timeout", type=float, default=12.0)
    args = parser.parse_args()

    for path, label in (
        (args.env_file, "env file"),
        (args.runtime, "Bionic runtime"),
        (args.worker, "online worker"),
        (args.library, "PPPP library"),
    ):
        if not path.exists():
            raise SystemExit(f"{label} missing: {path}")
    if args.camera_timeout <= 0:
        raise SystemExit("--camera-timeout must be greater than zero")
    if not args.guest_library.startswith("/"):
        raise SystemExit("--guest-library must be an absolute Bionic guest path")

    oracle.load_env_file(args.env_file)
    manager = YiCameraManager(timeout=10.0)
    results: list[dict[str, Any]] = []
    try:
        manager.login_and_list()
        devices = manager.discover(fetch_tnp=False)
        for device in devices:
            item: dict[str, Any] = {
                "stable_id": device.stable_id,
                "name": device.name,
                "transport": device.transport,
                "cloud_list_online": device.cloud_online_reported,
                "availability_state": "unknown",
                "availability_source": "unsupported_transport" if device.transport != "tnp" else "pppp_check_dev_online",
                "last_online_time": None,
                "last_online_at": None,
                "native_result": None,
                "probe_error": None,
                "secrets_exposed": False,
            }

            raw_camera = manager._cameras.get(device.stable_id, {})  # development parity diagnostics only
            item["cloud_state"] = _safe_scalar(raw_camera.get("state"))
            item["cloud_online_time"] = _safe_scalar(raw_camera.get("onlineTime"))
            item["cloud_active_time"] = _safe_scalar(raw_camera.get("activeTime"))
            try:
                ipc = cloud._ipc_params(raw_camera)
                item["cloud_powerstate"] = _safe_scalar(ipc.get("powerstate"))
            except Exception:
                item["cloud_powerstate"] = None

            if device.transport != "tnp":
                results.append(item)
                continue

            if not STABLE_ID_RE.fullmatch(device.stable_id):
                item["probe_error"] = "invalid_stable_id"
                results.append(item)
                continue

            secret_values: list[bytes] = []
            try:
                tnp = manager._tnp_info(device.stable_id)
                p2pid = tnp.get("DID")
                server = tnp.get("InitString")
                if not isinstance(p2pid, str) or not p2pid or not isinstance(server, str) or not server:
                    raise RuntimeError("online check material is unavailable")
                secret_values = [p2pid.encode("utf-8"), server.encode("utf-8")]
                payload = _payload(p2pid, server)

                command = [
                    args.qemu,
                    "-L",
                    str(args.runtime),
                    "-E",
                    "LD_LIBRARY_PATH=/data/local/tmp/yi-online-status:/system/lib64",
                    str(args.worker),
                    args.guest_library,
                ]
                proc = subprocess.run(
                    command,
                    input=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=args.camera_timeout,
                    check=False,
                )
                combined = proc.stdout + b"\n" + proc.stderr
                if any(secret and secret in combined for secret in secret_values):
                    raise RuntimeError("native worker attempted to expose online-check material")
                if proc.returncode != 0:
                    raise RuntimeError("native online worker failed")
                parsed = _parse_worker_output(proc.stdout)
                item.update(parsed)
                item["last_online_at"] = _safe_epoch(int(parsed["last_online_time"]))
            except subprocess.TimeoutExpired:
                item["probe_error"] = "online_check_timeout"
            except (cloud.YiCloudError, RuntimeError, OSError, ValueError):
                item["probe_error"] = "online_check_failed"
            finally:
                # Do not retain transport material between cameras.
                secret_values.clear()

            results.append(item)
    finally:
        manager.close()

    online = sum(1 for item in results if item["availability_state"] == "online")
    offline = sum(1 for item in results if item["availability_state"] == "offline")
    unknown = sum(1 for item in results if item["availability_state"] == "unknown")
    tnp_count = sum(1 for item in results if item["transport"] == "tnp")
    resolved_tnp = sum(
        1 for item in results
        if item["transport"] == "tnp" and item["availability_state"] in {"online", "offline"}
    )

    print(
        json.dumps(
            {
                "ok": True,
                "evidence": "CURRENT_YI_APP_PPPP_CHECK_DEV_ONLINE_PARITY",
                "camera_count": len(results),
                "tnp_camera_count": tnp_count,
                "resolved_tnp_count": resolved_tnp,
                "online_count": online,
                "offline_count": offline,
                "unknown_count": unknown,
                "cameras": results,
                "secrets_exposed": False,
                "production_modified": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if resolved_tnp == tnp_count and tnp_count > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
