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

for tool in "$CC" "$QEMU" readelf file patchelf; do
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

mkdir -p "$COMPAT"
cp -f "$LIB" "$BUILD/libPPPP_API.so"

"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,liblog.so \
    -o "$COMPAT/liblog.so" "$SRC_DIR/liblog_shim.c"

"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -Wl,-soname,libandroid_compat.so \
    -o "$COMPAT/libandroid_compat.so" "$SRC_DIR/libc_shim.c"

# Re-target Android/Bionic SONAMEs to the GNU/Linux ARM64 runtime libraries.
patchelf --replace-needed libc.so libc.so.6 "$BUILD/libPPPP_API.so"
patchelf --replace-needed libm.so libm.so.6 "$BUILD/libPPPP_API.so"
patchelf --replace-needed libdl.so libdl.so.2 "$BUILD/libPPPP_API.so"
patchelf --replace-needed libstdc++.so libstdc++.so.6 "$BUILD/libPPPP_API.so"
patchelf --add-needed libandroid_compat.so "$BUILD/libPPPP_API.so"

# Bionic symbols may carry Android version labels (for example LIBC). glibc
# exposes the same named functions under GLIBC_* versions, so clear only the
# version requirement on undefined imports.
while IFS= read -r symbol; do
    [[ -n "$symbol" ]] || continue
    patchelf --clear-symbol-version "$symbol" "$BUILD/libPPPP_API.so" || true
done < <(
    readelf -Ws "$BUILD/libPPPP_API.so" |
    awk '$7 == "UND" && $8 != "" {name=$8; sub(/@.*/, "", name); print name}' |
    sort -u
)

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

echo "--- PATCHED LIBRARY ---"
file "$BUILD/libPPPP_API.so"
readelf -d "$BUILD/libPPPP_API.so" | grep NEEDED || true

echo

echo "--- REMAINING VERSION REQUIREMENTS ---"
readelf -V "$BUILD/libPPPP_API.so" | grep -E 'Name: (LIBC|LIBM|LIBDL|LIBSTDCPP|LIBLOG)' || true

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
