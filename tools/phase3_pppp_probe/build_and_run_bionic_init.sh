#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-phase3c"
LIB="${1:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"

for tool in "$CC" "$QEMU" readelf file timeout; do
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
        echo "Run ./tools/phase3_pppp_probe/bootstrap_bionic_runtime.sh once while the test phone is connected." >&2
        exit 3
    fi
done

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -f "$LIB" "$TARGET_DIR/libPPPP_API.so"

# Same minimal support DSOs used by the successful Phase 3B2 loader probe.
"$CC" -nostdlib -shared -fPIC -fno-stack-protector \
    -Wl,-soname,liblog.so \
    -o "$TARGET_DIR/liblog.so" "$SRC_DIR/android_liblog_stub.c"

for name in libm.so libstdc++.so; do
    "$CC" -nostdlib -shared -fPIC -fno-stack-protector \
        -Wl,-soname,"$name" \
        -o "$TARGET_DIR/$name" "$SRC_DIR/empty_shim.c"
done

# Build a Bionic-targeted executable without glibc startup code. The probe
# exercises only PPPP_Initialize({0}, 12), PPPP_GetAPIVersion(), and
# PPPP_DeInitialize(). It does not have a DID and cannot connect to a camera.
"$CC" -nostdlib -fPIE -pie -fno-stack-protector -fno-builtin \
    -Wl,-e,_start \
    -Wl,--dynamic-linker,/system/bin/linker64 \
    -Wl,--no-as-needed \
    -Wl,-rpath-link,"$RUNTIME/system/lib64" \
    -o "$TARGET_DIR/android_pppp_init_probe" \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_init_probe.c" \
    -L"$RUNTIME/system/lib64" \
    -Wl,-l:libdl.so \
    -Wl,-l:libc.so \
    -Wl,-l:ld-android.so

chmod +x "$TARGET_DIR/android_pppp_init_probe"

echo "=== PHASE 3C: BIONIC PPPP INITIALIZE/DEINITIALIZE PROBE ==="
echo "No ADB, USB phone, cloud login, DID, camera password, or camera connection is used."
echo "Lifecycle inputs match the proven Android oracle: initString={0}, maxSessions=12."
echo

echo "--- PROBE ---"
file "$TARGET_DIR/android_pppp_init_probe"
readelf -l "$TARGET_DIR/android_pppp_init_probe" | grep -F 'Requesting program interpreter' || true
readelf -d "$TARGET_DIR/android_pppp_init_probe" | grep NEEDED || true

echo

echo "--- YI PPPP DSO ---"
file "$TARGET_DIR/libPPPP_API.so"

echo

echo "--- RUN WITHOUT ADB ---"
set +e
timeout --signal=KILL 20s \
    "$QEMU" -L "$RUNTIME" \
    -E LD_LIBRARY_PATH=/data/local/tmp/yi-phase3c:/system/lib64 \
    "$TARGET_DIR/android_pppp_init_probe" \
    /data/local/tmp/yi-phase3c/libPPPP_API.so
RC=$?
set -e

echo
echo "probe_exit_code=$RC"
case "$RC" in
    0)
        echo "PHASE3C_INIT=PASS"
        ;;
    124|137)
        echo "PHASE3C_INIT=TIMEOUT"
        ;;
    *)
        echo "PHASE3C_INIT=FAIL"
        ;;
esac
exit "$RC"
