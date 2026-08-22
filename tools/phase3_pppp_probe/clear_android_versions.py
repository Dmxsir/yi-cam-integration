#!/usr/bin/env python3
"""Remove Android/Bionic symbol-version requirements from an ELF64 AArch64 DSO.

The YI PPPP library imports ordinary libc symbols tagged with Android's `LIBC`
version namespace. GNU glibc exports the same names under `GLIBC_*`, so the
loader rejects the DSO before ordinary symbol-name matching can happen.

For this controlled compatibility probe we do two things:

1. Make every undefined import unversioned (VER_NDX_GLOBAL) in `.gnu.version`.
2. Neutralize DT_VERNEED, DT_VERNEEDNUM, and DT_VERSYM in the dynamic table.

The second step is important: merely setting DT_VERNEEDNUM to zero is not
sufficient for glibc's loader. We replace those three dynamic tags with harmless
DT_BIND_NOW entries instead of inserting DT_NULL, because DT_NULL would truncate
the dynamic table and hide later entries such as DT_RELACOUNT.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import NoReturn

ELF_MAGIC = b"\x7fELF"
ELFCLASS64 = 2
ELFDATA2LSB = 1
SHN_UNDEF = 0
DT_NULL = 0
DT_BIND_NOW = 24
DT_VERSYM = 0x6FFFFFF0
DT_VERNEED = 0x6FFFFFFE
DT_VERNEEDNUM = 0x6FFFFFFF
VER_NDX_GLOBAL = 1


def die(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


def c_string(blob: bytes, offset: int) -> str:
    end = blob.find(b"\0", offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode("utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) != 2:
        die("usage: clear_android_versions.py <ELF shared object>")

    path = Path(sys.argv[1])
    data = bytearray(path.read_bytes())

    if data[:4] != ELF_MAGIC:
        die("not an ELF file")
    if data[4] != ELFCLASS64 or data[5] != ELFDATA2LSB:
        die("expected little-endian ELF64")

    e_shoff = struct.unpack_from("<Q", data, 40)[0]
    e_shentsize = struct.unpack_from("<H", data, 58)[0]
    e_shnum = struct.unpack_from("<H", data, 60)[0]
    e_shstrndx = struct.unpack_from("<H", data, 62)[0]

    if not e_shoff or not e_shnum or e_shentsize < 64:
        die("ELF section table is unavailable")
    if e_shstrndx >= e_shnum:
        die("invalid section-name string-table index")

    sections: list[dict[str, int | str]] = []
    for index in range(e_shnum):
        off = e_shoff + index * e_shentsize
        values = struct.unpack_from("<IIQQQQIIQQ", data, off)
        sections.append(
            {
                "index": index,
                "header_offset": off,
                "name_offset": values[0],
                "type": values[1],
                "offset": values[4],
                "size": values[5],
                "link": values[6],
                "entsize": values[9],
            }
        )

    shstr = sections[e_shstrndx]
    shstr_blob = bytes(
        data[int(shstr["offset"]): int(shstr["offset"]) + int(shstr["size"])]
    )
    by_name: dict[str, dict[str, int | str]] = {}
    for section in sections:
        name = c_string(shstr_blob, int(section["name_offset"]))
        section["name"] = name
        by_name[name] = section

    try:
        dynsym = by_name[".dynsym"]
        versym = by_name[".gnu.version"]
        dynamic = by_name[".dynamic"]
    except KeyError as exc:
        die(f"required ELF section missing: {exc.args[0]}")

    dynsym_entsize = int(dynsym["entsize"]) or 24
    if dynsym_entsize < 24:
        die("unexpected .dynsym entry size")

    symbol_count = int(dynsym["size"]) // dynsym_entsize
    versym_count = int(versym["size"]) // 2
    count = min(symbol_count, versym_count)

    cleared = 0
    for index in range(count):
        sym_off = int(dynsym["offset"]) + index * dynsym_entsize
        st_shndx = struct.unpack_from("<H", data, sym_off + 6)[0]
        if st_shndx != SHN_UNDEF:
            continue

        ver_off = int(versym["offset"]) + index * 2
        raw_version = struct.unpack_from("<H", data, ver_off)[0]
        version_index = raw_version & 0x7FFF
        if version_index > VER_NDX_GLOBAL:
            # Drop both the version index and the hidden bit for undefined imports.
            struct.pack_into("<H", data, ver_off, VER_NDX_GLOBAL)
            cleared += 1

    dynamic_entsize = int(dynamic["entsize"]) or 16
    if dynamic_entsize < 16:
        die("unexpected .dynamic entry size")

    target_tags = {DT_VERNEED, DT_VERNEEDNUM, DT_VERSYM}
    found_tags: set[int] = set()
    dynamic_count = int(dynamic["size"]) // dynamic_entsize

    for index in range(dynamic_count):
        entry_off = int(dynamic["offset"]) + index * dynamic_entsize
        tag, _value = struct.unpack_from("<qQ", data, entry_off)
        if tag == DT_NULL:
            break
        if tag in target_tags:
            found_tags.add(tag)
            # Keep the dynamic table structurally intact while making the loader
            # ignore Android version metadata. Duplicate DT_BIND_NOW entries are
            # harmless; their value is ignored.
            struct.pack_into("<qQ", data, entry_off, DT_BIND_NOW, 0)

    missing = target_tags - found_tags
    if missing:
        missing_text = ", ".join(f"0x{tag:x}" for tag in sorted(missing))
        die(f"expected dynamic version tag(s) not found: {missing_text}")

    path.write_bytes(data)
    print(
        "compat_version_patch=OK "
        f"cleared_undefined_symbols={cleared} "
        f"version_tags_neutralized={len(found_tags)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
