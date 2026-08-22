#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
LIB="${1:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
BUILD="$ROOT/.analysis/phase3/linux-smoke"
COMPAT="$BUILD/compat"
BRIDGE_SRC="$BUILD/libc-bridge-src"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"
SYSROOT="${QEMU_SYSROOT:-/usr/aarch64-linux-gnu}"

for tool in "$CC" "$QEMU" readelf file patchelf python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: required tool missing: $tool" >&2
        echo "Ubuntu packages: sudo apt-get install qemu-user gcc-aarch64-linux-gnu libc6-dev-arm64-cross patchelf" >&2
        exit 2
    fi
done

if [[ ! -f "$LIB" ]]; then
    echo "ERROR: libPPPP_API.so not found: $LIB" >&2
    exit 3
fi

# Always rebuild from a clean directory. The previous experiment rewrote the
# Android symbol-version metadata; this probe deliberately starts again from
# the untouched YI DSO and preserves its original `LIBC` requirements.
rm -rf "$BUILD"
mkdir -p "$COMPAT" "$BRIDGE_SRC"
cp -f "$LIB" "$BUILD/libPPPP_API.so"

# Android logging is the only non-libc undefined import in this PPPP build.
"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,liblog.so \
    -o "$COMPAT/liblog.so" "$SRC_DIR/liblog_shim.c"

# Build a compatibility DSO *named libc.so*. It exports every symbol requested
# as symbol@@LIBC and tail-jumps to the real GNU libc.so.6 implementation. This
# keeps the PPPP ELF version tables intact and avoids forcing glibc to interpret
# Android/Bionic version indexes as native GLIBC_* indexes.
python3 "$SRC_DIR/make_libc_bridge.py" "$BUILD/libPPPP_API.so" "$BRIDGE_SRC"

"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,libc.so \
    -Wl,--version-script="$BRIDGE_SRC/libc_bridge.map" \
    -o "$COMPAT/libc.so" \
    "$BRIDGE_SRC/libc_bridge_resolver.c" \
    "$BRIDGE_SRC/libc_bridge_trampolines.S" \
    -ldl

# These Android SONAMEs do not carry the LIBC version contract in this DSO, so
# map them directly to their GNU/Linux ARM64 counterparts. Keep libc.so exactly
# as-is so the loader selects our compatibility bridge for the LIBC namespace.
patchelf --replace-needed libm.so libm.so.6 "$BUILD/libPPPP_API.so"
patchelf --replace-needed libdl.so libdl.so.2 "$BUILD/libPPPP_API.so"
patchelf --replace-needed libstdc++.so libstdc++.so.6 "$BUILD/libPPPP_API.so"

"$CC" -O2 -Wall -Wextra \
    -o "$BUILD/pppp_probe" "$SRC_DIR/pppp_probe.c" -ldl

echo "=== PHASE 3B: VERSIONED LIBC BRIDGE SMOKE PROBE ==="
echo "This probe calls PPPP_GetAPIVersion only."
echo "It does NOT initialize PPPP, open a network session, or contact a camera."
echo

echo "--- PROBE ---"
file "$BUILD/pppp_probe"
readelf -l "$BUILD/pppp_probe" | grep -F 'Requesting program interpreter' || true

echo

echo "--- PPPP LIBRARY ---"
file "$BUILD/libPPPP_API.so"
readelf -d "$BUILD/libPPPP_API.so" | grep NEEDED || true

echo

echo "--- ORIGINAL ANDROID VERSION REQUIREMENT (EXPECTED) ---"
readelf -V "$BUILD/libPPPP_API.so" | grep -E 'File: libc\.so|Name: LIBC' || true

echo

echo "--- GENERATED LIBC BRIDGE ---"
file "$COMPAT/libc.so"
readelf -d "$COMPAT/libc.so" | grep NEEDED || true
readelf -V "$COMPAT/libc.so" | grep -E 'Name: LIBC|Rev:' || true
printf 'bridge_symbol_count='
wc -l < "$BRIDGE_SRC/libc_bridge_symbols.txt"

echo

echo "--- OTHER COMPAT SHIMS ---"
file "$COMPAT/liblog.so"

echo

echo "--- RUN ---"
set +e
"$QEMU" -L "$SYSROOT" \
    -E "LD_LIBRARY_PATH=$COMPAT" \
    "$BUILD/pppp_probe" "$BUILD/libPPPP_API.so"
RC=$?
set -e

echo
echo "probe_exit_code=$RC"

if [[ $RC -eq 0 ]]; then
    echo "PHASE3B_SMOKE=PASS"
else
    echo "PHASE3B_SMOKE=FAIL"
fi

exit "$RC"
