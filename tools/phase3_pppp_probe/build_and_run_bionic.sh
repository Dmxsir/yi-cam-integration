#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-phase3"
LIB="${1:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"

for tool in "$CC" "$QEMU" readelf file; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done

for f in \
    "$RUNTIME/system/bin/linker64" \
    "$RUNTIME/system/lib64/libc.so" \
    "$RUNTIME/system/lib64/libdl.so" \
    "$RUNTIME/system/lib64/ld-android.so" \
    "$LIB"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: required file missing: $f" >&2
        echo "Run ./tools/phase3_pppp_probe/bootstrap_bionic_runtime.sh first." >&2
        exit 3
    fi
done

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -f "$LIB" "$TARGET_DIR/libPPPP_API.so"

# Minimal no-libc compatibility DSOs for dependencies that this PPPP build
# names but does not import ABI-sensitive symbols from during the smoke test.
"$CC" -nostdlib -shared -fPIC -fno-stack-protector \
    -Wl,-soname,liblog.so \
    -o "$TARGET_DIR/liblog.so" "$SRC_DIR/android_liblog_stub.c"

for name in libm.so libstdc++.so; do
    "$CC" -nostdlib -shared -fPIC -fno-stack-protector \
        -Wl,-soname,"$name" \
        -o "$TARGET_DIR/$name" "$SRC_DIR/empty_shim.c"
done

# Build an Android/Bionic-targeted ARM64 executable without glibc startup code.
# libc.so and libdl.so depend on loader-private symbols exported by
# ld-android.so, so make that support DSO visible to GNU ld at link time too.
"$CC" -nostdlib -fPIE -pie -fno-stack-protector -fno-builtin \
    -Wl,-e,_start \
    -Wl,--dynamic-linker,/system/bin/linker64 \
    -Wl,--no-as-needed \
    -Wl,-rpath-link,"$RUNTIME/system/lib64" \
    -o "$TARGET_DIR/android_pppp_probe" \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_probe.c" \
    -L"$RUNTIME/system/lib64" \
    -Wl,-l:libdl.so \
    -Wl,-l:libc.so \
    -Wl,-l:ld-android.so

chmod +x "$TARGET_DIR/android_pppp_probe"

echo "=== PHASE 3B2: NATIVE BIONIC RUNTIME SMOKE PROBE ==="
echo "The runtime was copied earlier; this run does NOT use adb or the phone."
echo "The YI DSO is unmodified and executes with Android's own linker/libc."
echo

echo "--- ANDROID LINKER ---"
file "$RUNTIME/system/bin/linker64"

echo

echo "--- BIONIC LIBC / LOADER SUPPORT ---"
file "$RUNTIME/system/lib64/libc.so"
file "$RUNTIME/system/lib64/libdl.so"
file "$RUNTIME/system/lib64/ld-android.so"
readelf -d "$RUNTIME/system/lib64/libdl.so" | grep NEEDED || true
readelf -V "$RUNTIME/system/lib64/libc.so" | grep -E 'Name: LIBC|Rev:' | head -20 || true

echo

echo "--- PROBE ---"
file "$TARGET_DIR/android_pppp_probe"
readelf -l "$TARGET_DIR/android_pppp_probe" | grep -F 'Requesting program interpreter' || true
readelf -d "$TARGET_DIR/android_pppp_probe" | grep NEEDED || true

echo

echo "--- YI PPPP DSO (UNMODIFIED) ---"
file "$TARGET_DIR/libPPPP_API.so"
readelf -d "$TARGET_DIR/libPPPP_API.so" | grep NEEDED || true
readelf -V "$TARGET_DIR/libPPPP_API.so" | grep -E 'File: libc\.so|Name: LIBC' || true

echo

echo "--- RUN WITHOUT ADB ---"
set +e
"$QEMU" -L "$RUNTIME" \
    -E LD_LIBRARY_PATH=/data/local/tmp/yi-phase3:/system/lib64 \
    "$TARGET_DIR/android_pppp_probe" \
    /data/local/tmp/yi-phase3/libPPPP_API.so
RC=$?
set -e

echo
echo "probe_exit_code=$RC"
if [[ $RC -eq 0 ]]; then
    echo "PHASE3B2_BIONIC=PASS"
else
    echo "PHASE3B2_BIONIC=FAIL"
fi
exit "$RC"
