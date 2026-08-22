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

# Always rebuild from a clean directory so stale compatibility DSOs from an
# older probe cannot shadow the real GNU/Linux runtime libraries.
rm -rf "$BUILD"
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

# Android/Bionic tags ordinary imports with the `LIBC` symbol-version
# namespace. glibc uses GLIBC_* instead. patchelf can clear individual symbol
# versions, but it intentionally leaves the ELF VERNEED record itself. The
# glibc loader validates that record before dlopen succeeds, so normalize both
# the undefined-symbol version indexes and DT_VERNEEDNUM.
python3 "$SRC_DIR/clear_android_versions.py" "$BUILD/libPPPP_API.so"

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

echo "--- DYNAMIC VERSION STATE ---"
readelf -d "$BUILD/libPPPP_API.so" | grep -E 'VERNEED|VERSYM' || true

echo

echo "--- UNDEFINED SYMBOLS STILL VERSIONED ---"
readelf -Ws "$BUILD/libPPPP_API.so" |
awk '$7 == "UND" && $8 ~ /@/ {print $8}' |
sort -u || true

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
