#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-phase3e"
LIB="${YI_PPPP_LIB:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"
PYTHON="${PYTHON:-python3}"
ENV_FILE="${1:-$ROOT/.env.local}"

for tool in "$CC" "$QEMU" readelf file "$PYTHON"; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done

for f in \
    "$RUNTIME/system/bin/linker64" \
    "$RUNTIME/system/lib64/libc.so" \
    "$RUNTIME/system/lib64/libdl.so" \
    "$RUNTIME/system/lib64/ld-android.so" \
    "$LIB" \
    "$ENV_FILE"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: required file missing: $f" >&2
        exit 3
    fi
done

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -f "$LIB" "$TARGET_DIR/libPPPP_API.so"

"$CC" -nostdlib -shared -fPIC -fno-stack-protector \
    -Wl,-soname,liblog.so \
    -o "$TARGET_DIR/liblog.so" "$SRC_DIR/android_liblog_stub.c"

for name in libm.so libstdc++.so; do
    "$CC" -nostdlib -shared -fPIC -fno-stack-protector \
        -Wl,-soname,"$name" \
        -o "$TARGET_DIR/$name" "$SRC_DIR/empty_shim.c"
done

"$CC" -nostdlib -fPIE -pie -fno-stack-protector -fno-builtin \
    -Wl,-e,_start \
    -Wl,--dynamic-linker,/system/bin/linker64 \
    -Wl,--no-as-needed \
    -Wl,-rpath-link,"$RUNTIME/system/lib64" \
    -o "$TARGET_DIR/android_pppp_tnp_probe" \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_tnp_probe.c" \
    -L"$RUNTIME/system/lib64" \
    -Wl,-l:libdl.so \
    -Wl,-l:libc.so \
    -Wl,-l:ld-android.so

chmod +x "$TARGET_DIR/android_pppp_tnp_probe"

echo "=== PHASE 3E: PHONELESS BIONIC TNP CHANNEL-0 PROBE ==="
echo "This phase performs a real PPPP connection to the exact warehouse camera."
echo "It sends the proven uninterrupted TNP startup burst 4881 -> 9029 -> 768 on channel 0."
echo "It reads and validates the first 4882 authentication response, then sends STOP_LIVE 767."
echo "Video channels are not consumed in this phase; the live session is stopped immediately after auth."
echo "No ADB or USB phone is used. Secrets/auth units travel through stdin only."
echo

echo "--- PROBE ---"
file "$TARGET_DIR/android_pppp_tnp_probe"
readelf -l "$TARGET_DIR/android_pppp_tnp_probe" | grep -F 'Requesting program interpreter' || true
readelf -d "$TARGET_DIR/android_pppp_tnp_probe" | grep NEEDED || true

echo
echo "--- RUN WITHOUT ADB ---"
"$PYTHON" "$SRC_DIR/run_phase3e_tnp.py" \
    --env-file "$ENV_FILE" \
    --runtime "$RUNTIME" \
    --target-dir "$TARGET_DIR" \
    --qemu "$QEMU"
