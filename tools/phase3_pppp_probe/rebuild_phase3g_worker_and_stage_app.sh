#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
WORKER="$TARGET_DIR/android_pppp_av_stream"
STAGED_WORKER="$ROOT/yi_home/rootfs/opt/yi-home/runtime/bionic-root/data/local/tmp/yi-phase3g/android_pppp_av_stream"
CC="${CC:-aarch64-linux-gnu-gcc}"
PYTHON="${PYTHON:-python3}"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

command -v "$CC" >/dev/null 2>&1 || fail "AArch64 cross compiler is unavailable: $CC"
command -v "$PYTHON" >/dev/null 2>&1 || fail "Python is unavailable: $PYTHON"

for file in \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_av_stream.c" \
    "$RUNTIME/system/bin/linker64" \
    "$RUNTIME/system/lib64/libc.so" \
    "$RUNTIME/system/lib64/libdl.so" \
    "$RUNTIME/system/lib64/ld-android.so" \
    "$TARGET_DIR/libPPPP_API.so"; do
    [[ -f "$file" ]] || fail "required proven runtime/build artifact missing: $file"
done

mkdir -p "$TARGET_DIR"
TEMP_WORKER="$TARGET_DIR/.android_pppp_av_stream.new"
rm -f "$TEMP_WORKER"
trap 'rm -f "$TEMP_WORKER"' EXIT

"$CC" -nostdlib -fPIE -pie -fno-stack-protector -fno-builtin -mno-outline-atomics \
    -Wl,-e,_start \
    -Wl,--dynamic-linker,/system/bin/linker64 \
    -Wl,--no-as-needed \
    -Wl,-rpath-link,"$RUNTIME/system/lib64" \
    -o "$TEMP_WORKER" \
    "$SRC_DIR/android_start.S" \
    "$SRC_DIR/android_pppp_av_stream.c" \
    -L"$RUNTIME/system/lib64" \
    -Wl,-l:libdl.so \
    -Wl,-l:libc.so \
    -Wl,-l:ld-android.so

chmod 0755 "$TEMP_WORKER"
mv -f "$TEMP_WORKER" "$WORKER"
trap - EXIT

echo "phase3g_worker_build=PASS"
sha256sum "$WORKER"

"$PYTHON" "$ROOT/tools/prepare_ha_app_context.py"
[[ -x "$STAGED_WORKER" ]] || fail "staged App worker missing after context preparation: $STAGED_WORKER"

SOURCE_SHA="$(sha256sum "$WORKER" | awk '{print $1}')"
STAGED_SHA="$(sha256sum "$STAGED_WORKER" | awk '{print $1}')"
[[ "$SOURCE_SHA" == "$STAGED_SHA" ]] || fail "staged worker hash does not match rebuilt runtime worker"

echo "phase3g_worker_stage_sha256=$STAGED_SHA"
echo "PHASE3G_WORKER_STAGE=PASS"
