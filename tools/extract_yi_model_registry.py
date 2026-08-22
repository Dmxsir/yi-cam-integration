#!/usr/bin/env python3
"""Extract non-secret raw-model metadata from YI Home APK feature configs.

The output is deliberately derived metadata only; no native library, DEX, user
credential, UID, DID, token, password, or cloud response is copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


FIELDS = (
    "serverModel",
    "model",
    "identifier",
    "firmwareBranch",
    "baseVersion",
    "version",
    "platform",
    "deviceType",
    "onlineStatusP2p",
    "powerSupplyType",
    "h265Support",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _entry(name: str, value: dict[str, Any]) -> dict[str, Any] | None:
    raw = value.get("serverModel")
    model = value.get("model")
    if raw in (None, "") or not isinstance(model, str) or not model or model == "config_base":
        return None
    return {
        "server_model": str(raw),
        "model": model,
        "identifier": str(value.get("identifier") or ""),
        "firmware_branch": str(value.get("firmwareBranch") or ""),
        "base_version": value.get("baseVersion"),
        "config_version": value.get("version"),
        "platform": value.get("platform"),
        "device_type": value.get("deviceType"),
        "online_status_p2p": value.get("onlineStatusP2p"),
        "power_supply_type": value.get("powerSupplyType"),
        "h265_support": value.get("h265Support"),
        "feature_config": Path(name).name,
    }


def extract(apk: Path, app_version: str | None, app_version_code: int | None) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(apk) as archive:
        names = sorted(
            name for name in archive.namelist()
            if name.startswith("assets/feature_config/config_") and name.endswith(".json")
        )
        for name in names:
            try:
                value = json.loads(archive.read(name).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            item = _entry(name, value)
            if item is not None:
                entries.append(item)

    entries.sort(
        key=lambda item: (
            int(item["server_model"]) if item["server_model"].isdigit() else 1 << 30,
            item["server_model"],
            item["model"],
            item["feature_config"],
        )
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in entries:
        grouped[item["server_model"]].append(item)
    ambiguous = [
        raw for raw, items in grouped.items()
        if len({item["model"] for item in items}) > 1
    ]
    ambiguous.sort(key=lambda value: int(value) if value.isdigit() else 1 << 30)

    return {
        "schema_version": 1,
        "source": {
            "artifact": apk.name,
            "apk_version": app_version,
            "apk_version_code": app_version_code,
            "apk_sha256": _sha256(apk),
            "feature_config_count": len(names),
            "mapped_entry_count": len(entries),
        },
        "resolution_notes": {
            "raw_model_field": "/v4/devices/list data[].model",
            "server_model_relation": "feature_config serverModel",
            "special_server_model_10000": "resolve by first five characters of device did against identifier",
            "firmware_branch_semantics": "APK model-family metadata; not the running camera firmware version",
            "firmware_version_source": "not /v4/devices/list; obtain later from device info / pre-version control responses",
            "ambiguous_server_models": ambiguous,
        },
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("apk", type=Path)
    parser.add_argument("--app-version")
    parser.add_argument("--app-version-code", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if not args.apk.is_file():
        parser.error(f"APK not found: {args.apk}")

    result = extract(args.apk, args.app_version, args.app_version_code)
    encoded = json.dumps(result, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"model_registry=OK entries={len(result['entries'])} output={args.output}")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
