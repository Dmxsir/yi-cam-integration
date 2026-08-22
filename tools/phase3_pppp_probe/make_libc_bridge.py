#!/usr/bin/env python3
"""Generate an AArch64 libc.so compatibility bridge for Android/Bionic imports.

The YI PPPP DSO requires ordinary libc symbols under Android's `LIBC` version
namespace and names its dependency `libc.so`. GNU/Linux uses `libc.so.6` and
GLIBC_* versions. Instead of rewriting the PPPP ELF version metadata, generate
a small DSO named `libc.so` that exports the requested `symbol@@LIBC` names and
tail-jumps to the real functions resolved explicitly from `libc.so.6`.

The tail-jump trampolines preserve the complete AArch64 calling convention, so
we do not need to guess C prototypes for socket, pthread, stdio, or varargs
functions.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SYMBOL_RE = re.compile(r"\bUND\b.*\s([A-Za-z0-9_]+)@LIBC(?:\s|$)")


def die(message: str) -> "NoReturn":
    raise SystemExit(f"ERROR: {message}")


def get_libc_symbols(library: Path) -> list[str]:
    proc = subprocess.run(
        ["readelf", "-Ws", str(library)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        die(proc.stderr.strip() or "readelf failed")

    symbols: set[str] = set()
    for line in proc.stdout.splitlines():
        match = SYMBOL_RE.search(line)
        if match:
            symbols.add(match.group(1))

    if not symbols:
        die("no undefined @LIBC imports were found")
    return sorted(symbols)


def c_ident(symbol: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        die(f"unsupported symbol name: {symbol!r}")
    return symbol


def write_resolver(path: Path, symbols: list[str]) -> None:
    lines = [
        "#define _GNU_SOURCE",
        "#include <dlfcn.h>",
        "#include <stddef.h>",
        "",
    ]
    for symbol in symbols:
        ident = c_ident(symbol)
        lines.append(f"void *yi_real_{ident};")

    lines += [
        "",
        "__attribute__((constructor))",
        "static void yi_libc_bridge_init(void) {",
        '    void *handle = dlopen("libc.so.6", RTLD_NOW | RTLD_LOCAL);',
        "    if (handle == NULL) return;",
    ]

    for symbol in symbols:
        ident = c_ident(symbol)
        target = "__errno_location" if symbol == "__errno" else symbol
        lines.append(f'    yi_real_{ident} = dlsym(handle, "{target}");')

    lines += ["}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_trampolines(path: Path, symbols: list[str]) -> None:
    lines = [".text", ".p2align 2", ""]
    for symbol in symbols:
        ident = c_ident(symbol)
        wrapper = f"yi_wrap_{ident}"
        slot = f"yi_real_{ident}"
        lines += [
            f".global {wrapper}",
            f".type {wrapper}, %function",
            f"{wrapper}:",
            f"    adrp x16, {slot}",
            f"    ldr x16, [x16, :lo12:{slot}]",
            "    br x16",
            f".size {wrapper}, .-{wrapper}",
            f".symver {wrapper}, {symbol}@@LIBC",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_version_script(path: Path) -> None:
    path.write_text("LIBC {\n};\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 3:
        die("usage: make_libc_bridge.py <libPPPP_API.so> <output-dir>")

    library = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    if not library.is_file():
        die(f"library not found: {library}")

    out_dir.mkdir(parents=True, exist_ok=True)
    symbols = get_libc_symbols(library)
    write_resolver(out_dir / "libc_bridge_resolver.c", symbols)
    write_trampolines(out_dir / "libc_bridge_trampolines.S", symbols)
    write_version_script(out_dir / "libc_bridge.map")
    (out_dir / "libc_bridge_symbols.txt").write_text(
        "\n".join(symbols) + "\n", encoding="utf-8"
    )

    print(f"libc_bridge_generate=OK symbols={len(symbols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
