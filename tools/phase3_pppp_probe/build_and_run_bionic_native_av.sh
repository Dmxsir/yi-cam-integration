#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
LIB="${YI_PPPP_LIB:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"
PYTHON="${PYTHON:-python3}"
FFMPEG="${FFMPEG:-ffmpeg}"
FFPROBE="${FFPROBE:-ffprobe}"
ENV_FILE="${1:-$ROOT/.env.local}"
DURATION="${PHASE3G_DURATION:-12}"
OUTPUT="$TARGET_DIR/warehouse-native-av.ts"

for tool in "$CC" "$QEMU" "$PYTHON" "$FFMPEG" "$FFPROBE" readelf file; do
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

# GCC 13 enables AArch64 outlined atomics by default and may emit helper calls
# such as __aarch64_swp4_sync.  This worker is intentionally linked with
# -nostdlib against the copied Bionic runtime, so those libgcc helper symbols
# are not available.  Force the lock primitive to be emitted inline as native
# AArch64 LL/SC instructions instead of adding a new runtime dependency.
"$CC" -nostdlib -fPIE -pie -fno-stack-protector -fno-builtin -mno-outline-atomics \
    -Wl,-e,_start \
    -Wl,--dynamic-linker,/system/bin/linker64 \
    -Wl,--no-as-needed \
    -Wl,-rpath-link,"$RUNTIME/system/lib64" \
    -o "$TARGET_DIR/android_pppp_av_stream" \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_av_stream.c" \
    -L"$RUNTIME/system/lib64" \
    -Wl,-l:libdl.so \
    -Wl,-l:libc.so \
    -Wl,-l:ld-android.so

chmod +x "$TARGET_DIR/android_pppp_av_stream"
rm -f "$OUTPUT"

echo "=== PHASE 3G: PHONELESS CONTINUOUS H264 + AAC MPEG-TS SMOKE ==="
echo "The native PPPP worker streams channels 1/2/3 continuously over stdout framing."
echo "The Linux host decrypts native AAC/H264, reorders video and muxes both with FFmpeg stream-copy."
echo "TNP timing proven by Phase 3G preflight is used: video 20 fps, AAC 64 ms/frame, live initial A/V offset."
echo "The current production yi-go2rtc service is not modified or restarted."
echo "No ADB or USB phone is used."
echo

echo "--- WORKER ---"
file "$TARGET_DIR/android_pppp_av_stream"
readelf -l "$TARGET_DIR/android_pppp_av_stream" | grep -F 'Requesting program interpreter' || true
readelf -d "$TARGET_DIR/android_pppp_av_stream" | grep NEEDED || true

echo
echo "--- ${DURATION}s LIVE A/V SMOKE WITHOUT ADB ---"
"$PYTHON" "$ROOT/yi_native_av_relay.py" \
    --env-file "$ENV_FILE" \
    --runtime "$RUNTIME" \
    --worker-dir "$TARGET_DIR" \
    --qemu "$QEMU" \
    --ffmpeg "$FFMPEG" \
    --ffprobe "$FFPROBE" \
    --duration "$DURATION" \
    --output "$OUTPUT"

echo "phase3g_output=$OUTPUT"
echo "PHASE3G_SMOKE=PASS"
