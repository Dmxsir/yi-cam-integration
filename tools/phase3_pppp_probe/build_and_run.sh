#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
LIB="${1:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
BUILD="$ROOT/.analysis/phase3/linux-smoke"
COMPAT="$BUILD/compat"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"
SYSROOT="${QEMU_SYSROOT:-/usr/aarch64-linux-gnu}"

for tool in "$CC" "$QEMU" readelf file; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: required tool missing: $tool" >&2
        echo "Ubuntu packages: sudo apt-get install qemu-user gcc-aarch64-linux-gnu libc6-dev-arm64-cross" >&2
        exit 2
    fi
done

if [[ ! -f "$LIB" ]]; then
    echo "ERROR: libPPPP_API.so not found: $LIB" >&2
    exit 3
fi

mkdir -p "$COMPAT"
cp -f "$LIB" "$BUILD/libPPPP_API.so"

"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,liblog.so \
    -o "$COMPAT/liblog.so" "$SRC_DIR/liblog_shim.c"

"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,libc.so \
    -o "$COMPAT/libc.so" "$SRC_DIR/libc_shim.c"

for name in libm.so libdl.so libstdc++.so; do
    "$CC" -shared -fPIC -O2 -Wall -Wextra \
        -Wl,-soname,"$name" \
        -o "$COMPAT/$name" "$SRC_DIR/empty_shim.c"
done

"$CC" -O2 -Wall -Wextra \
    -o "$BUILD/pppp_probe" "$SRC_DIR/pppp_probe.c" -ldl

echo "=== PHASE 3B: GLIBC-COMPAT SMOKE PROBE ==="
echo "This probe calls PPPP_GetAPIVersion only."
echo "It does NOT initialize PPPP, open a network session, or contact a camera."
echo

echo "--- PROBE ---"
file "$BUILD/pppp_probe"
readelf -l "$BUILD/pppp_probe" | grep -F 'Requesting program interpreter' || true

echo

echo "--- LIBRARY ---"
file "$BUILD/libPPPP_API.so"

echo

echo "--- COMPAT SHIMS ---"
for f in "$COMPAT"/*.so; do
    printf '%s: ' "$(basename "$f")"
    file -b "$f"
done

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
