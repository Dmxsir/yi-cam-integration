#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
ADB="${ADB:-adb}"

if ! command -v "$ADB" >/dev/null 2>&1; then
    echo "ERROR: adb not found" >&2
    exit 2
fi

if [[ "$($ADB get-state 2>/dev/null || true)" != "device" ]]; then
    echo "ERROR: Android device is not available over ADB" >&2
    exit 3
fi

mkdir -p "$RUNTIME/system/bin" "$RUNTIME/system/lib64"

echo "=== BOOTSTRAP AOSP/BIONIC RUNTIME FROM CONNECTED TEST PHONE ==="
echo "Read-only pull only; no package install, no app stop, no camera commands."

pull_first() {
    local dest="$1"
    shift
    local src
    for src in "$@"; do
        if "$ADB" shell "test -r '$src'" >/dev/null 2>&1; then
            echo "pull: $src"
            "$ADB" pull "$src" "$dest" >/dev/null
            return 0
        fi
    done
    echo "ERROR: none of the candidate paths were readable for $dest" >&2
    printf '  %s\n' "$@" >&2
    return 1
}

pull_first "$RUNTIME/system/bin/linker64" \
    /apex/com.android.runtime/bin/linker64 \
    /system/bin/linker64

pull_first "$RUNTIME/system/lib64/libc.so" \
    /apex/com.android.runtime/lib64/bionic/libc.so \
    /system/lib64/libc.so

pull_first "$RUNTIME/system/lib64/libdl.so" \
    /apex/com.android.runtime/lib64/bionic/libdl.so \
    /system/lib64/libdl.so

# Modern Bionic libc/libdl reference loader-private exports such as
# __loader_shared_globals through the ld-android.so support DSO. GNU ld also
# needs this file present while we build the tiny Android-targeted probe.
pull_first "$RUNTIME/system/lib64/ld-android.so" \
    /apex/com.android.runtime/lib64/ld-android.so \
    /system/lib64/ld-android.so

chmod +x "$RUNTIME/system/bin/linker64"

echo
echo "--- RUNTIME FILES ---"
file "$RUNTIME/system/bin/linker64"
file "$RUNTIME/system/lib64/libc.so"
file "$RUNTIME/system/lib64/libdl.so"
file "$RUNTIME/system/lib64/ld-android.so"

echo
echo "--- LOADER SUPPORT EXPORT ---"
readelf -Ws "$RUNTIME/system/lib64/ld-android.so" \
    | grep -E '__loader_shared_globals|__loader_dlopen|__loader_dlsym' \
    | head -20 || true

echo
echo "BIONIC_BOOTSTRAP=PASS"
echo "runtime=$RUNTIME"
