#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-phase3f"
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
chmod 700 "$TARGET_DIR"
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
    -o "$TARGET_DIR/android_pppp_av_capture" \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_av_capture.c" \
    -L"$RUNTIME/system/lib64" \
    -Wl,-l:libdl.so \
    -Wl,-l:libc.so \
    -Wl,-l:ld-android.so

chmod +x "$TARGET_DIR/android_pppp_av_capture"

echo "=== PHASE 3F: PHONELESS NATIVE A/V ELEMENTARY STREAM CAPTURE ==="
echo "The exact warehouse camera is opened through the proven Bionic PPPP/TNP path."
echo "Channels 1, 2 and 3 are consumed concurrently: AAC audio + H.264 I/P video."
echo "Raw TNP media is stored only under ignored .analysis with mode 0600."
echo "The Linux host mirrors the APK media transforms, then frames AAC and validates both streams."
echo "If ffprobe/ffmpeg are installed, both elementary streams are validated locally."
echo "No ADB or USB phone is used."
echo

echo "--- PROBE ---"
file "$TARGET_DIR/android_pppp_av_capture"
readelf -l "$TARGET_DIR/android_pppp_av_capture" | grep -F 'Requesting program interpreter' || true
readelf -d "$TARGET_DIR/android_pppp_av_capture" | grep NEEDED || true

echo
echo "--- RUN WITHOUT ADB ---"
"$PYTHON" "$SRC_DIR/run_phase3f_av_capture_v2.py" \
    --env-file "$ENV_FILE" \
    --runtime "$RUNTIME" \
    --target-dir "$TARGET_DIR" \
    --qemu "$QEMU"
