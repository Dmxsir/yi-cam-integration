#!/usr/bin/env python3
"""Compare two secret-free structural descriptions of TNP packets.

This tool deliberately does not accept raw packets.  Authentication material
must be represented only by length fields such as ``authInfo_length``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


UNKNOWN = object()
SECRET_KEYS = {
    "account",
    "authorization",
    "authinfo",
    "cookie",
    "did",
    "hmac",
    "initstring",
    "license",
    "nonce",
    "password",
    "rawpacket",
    "token",
    "tokensecret",
}


def _fold(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _is_length_key(key: str) -> bool:
    folded = _fold(key)
    return folded.endswith("length") or folded.endswith("size")


def _validate(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            folded = _fold(key)
            if any(secret in folded for secret in SECRET_KEYS) and not _is_length_key(key):
                raise ValueError(f"forbidden secret-bearing field: {'.'.join(path + (key,))}")
            _validate(child, path + (key,))
        return
    if isinstance(value, list):
        raise ValueError(f"arrays are not accepted; use named structural fields at {'.'.join(path)}")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError(f"unsupported value at {'.'.join(path)}")


def _flatten(value: Any, path: tuple[str, ...] = ()) -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            result.update(_flatten(child, path + (key,)))
        return result
    if isinstance(value, list):
        result = {}
        for index, child in enumerate(value):
            result.update(_flatten(child, path + (str(index),)))
        return result
    return {".".join(path): value}


def _known(value: Any) -> bool:
    return value is not UNKNOWN and value is not None and not (
        isinstance(value, str) and value.casefold() == "unknown"
    )


def _display(path: str, value: Any) -> Any:
    if value is UNKNOWN:
        return "UNKNOWN"
    folded = _fold(path)
    if isinstance(value, int) and (folded.endswith("length") or folded.endswith("size")):
        if "authinfo" in folded:
            return f"<AUTHINFO:{value}>"
        if "nonce" in folded:
            return f"<NONCE:{value}>"
        if "hmac" in folded:
            return f"<HMAC:{value}>"
    return value


def compare(old: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    _validate(old)
    _validate(current)
    old_fields = _flatten(old)
    current_fields = _flatten(current)
    fields: dict[str, Any] = {}
    counts = {"MATCH": 0, "DIFFERENT": 0, "UNKNOWN": 0}
    for path in sorted(old_fields.keys() | current_fields.keys()):
        old_value = old_fields.get(path, UNKNOWN)
        current_value = current_fields.get(path, UNKNOWN)
        if not _known(old_value) or not _known(current_value):
            result = "UNKNOWN"
        elif old_value == current_value:
            result = "MATCH"
        else:
            result = "DIFFERENT"
        counts[result] += 1
        fields[path] = {
            "old": _display(path, old_value),
            "current": _display(path, current_value),
            "result": result,
        }
    return {"summary": counts, "fields": fields}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a top-level JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare secret-free TNP structural JSON; raw packets are rejected."
    )
    parser.add_argument("old", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    try:
        result = compare(_load(args.old), _load(args.current))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
