#!/usr/bin/env python3
"""Inventory little-endian ELF64 shared objects without external packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any


MACHINES = {62: "x86-64", 183: "AArch64"}


def _cstring(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", "replace")


def read_export_code(path: Path, symbol_name: str, max_bytes: int = 64) -> dict[str, Any]:
    """Return bounded code bytes for one defined dynamic export."""
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError(f"{path} is not little-endian ELF64")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    section_offset, section_size, section_count, names_index = (
        header[5], header[10], header[11], header[12]
    )
    sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, section_offset + index * section_size)
        for index in range(section_count)
    ]
    names_section = sections[names_index]
    names = data[names_section[4] : names_section[4] + names_section[5]]
    by_name = {_cstring(names, section[0]): section for section in sections}
    symbols = by_name.get(".dynsym")
    if not symbols:
        raise ValueError(f"{path} has no .dynsym section")
    strings_section = sections[symbols[6]]
    strings = data[strings_section[4] : strings_section[4] + strings_section[5]]
    entry_size = symbols[9] or 24
    for offset in range(symbols[4], symbols[4] + symbols[5], entry_size):
        name, _, _, section_index, value, size = struct.unpack_from("<IBBHQQ", data, offset)
        if name and _cstring(strings, name) == symbol_name and section_index:
            section = sections[section_index]
            file_offset = section[4] + value - section[3]
            length = min(size or max_bytes, max_bytes)
            return {
                "virtual_address": value,
                "file_offset": file_offset,
                "declared_size": size,
                "code": data[file_offset : file_offset + length],
            }
    raise KeyError(f"export not found: {symbol_name}")


def inspect_elf(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError(f"{path} is not little-endian ELF64")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    machine, section_offset, section_size, section_count, names_index = (
        header[1], header[5], header[10], header[11], header[12]
    )
    sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, section_offset + index * section_size)
        for index in range(section_count)
    ]
    names_section = sections[names_index]
    names = data[names_section[4] : names_section[4] + names_section[5]]
    by_name = {_cstring(names, section[0]): section for section in sections}

    needed: list[str] = []
    soname: str | None = None
    dynamic = by_name.get(".dynamic")
    if dynamic:
        strings_section = sections[dynamic[6]]
        strings = data[strings_section[4] : strings_section[4] + strings_section[5]]
        entry_size = dynamic[9] or 16
        for offset in range(dynamic[4], dynamic[4] + dynamic[5], entry_size):
            tag, value = struct.unpack_from("<qQ", data, offset)
            if tag == 1:
                needed.append(_cstring(strings, value))
            elif tag == 14:
                soname = _cstring(strings, value)

    exports: list[str] = []
    symbols = by_name.get(".dynsym")
    if symbols:
        strings_section = sections[symbols[6]]
        strings = data[strings_section[4] : strings_section[4] + strings_section[5]]
        entry_size = symbols[9] or 24
        for offset in range(symbols[4], symbols[4] + symbols[5], entry_size):
            name, info, other, section_index, _, _ = struct.unpack_from("<IBBHQQ", data, offset)
            binding, visibility = info >> 4, other & 3
            if name and section_index and binding in (1, 2) and visibility in (0, 3):
                exports.append(_cstring(strings, name))

    return {
        "filename": path.name,
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "format": "ELF64",
        "architecture": MACHINES.get(machine, f"machine-{machine}"),
        "size": len(data),
        "soname": soname,
        "needed": needed,
        "export_count": len(set(exports)),
        "exports": sorted(set(exports)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps([inspect_elf(path) for path in args.paths], indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
