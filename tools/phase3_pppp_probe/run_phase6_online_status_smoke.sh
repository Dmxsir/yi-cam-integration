#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/tools/phase3_pppp_probe"
PYTHON="${PYTHON:-python3}"
ENV_FILE="${ENV_FILE:-$HOME/Documents/yi-cam-integration/.env.local}"
RUNTIME="${YI_PHASE6_ONLINE_RUNTIME:-$ROOT/.analysis/phase3/bionic-root}"
TARGET_DIR="$RUNTIME/data/local/tmp/yi-online-status"
LIB="${YI_PPPP_LIB:-$ROOT/.analysis/phase3/native/libPPPP_API.so}"
CC="${CC:-aarch64-linux-gnu-gcc}"
QEMU="${QEMU:-qemu-aarch64}"
WORK="$(mktemp -d)"
RESULT="$WORK/online-status.json"

cleanup() {
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

fail() {
  echo "ERROR: $*" >&2
  [[ -f "$RESULT" ]] && { echo "--- online status result ---" >&2; cat "$RESULT" >&2 || true; }
  exit 1
}

for tool in "$CC" "$QEMU" readelf file "$PYTHON"; do
  if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
    fail "required tool missing: $tool"
  fi
done

for f in \
  "$RUNTIME/system/bin/linker64" \
  "$RUNTIME/system/lib64/libc.so" \
  "$RUNTIME/system/lib64/libdl.so" \
  "$RUNTIME/system/lib64/ld-android.so" \
  "$LIB" \
  "$ENV_FILE" \
  "$SRC_DIR/android_start.S" \
  "$SRC_DIR/android_pppp_online_probe.c" \
  "$SRC_DIR/android_liblog_stub.c" \
  "$SRC_DIR/empty_shim.c"; do
  [[ -f "$f" ]] || fail "required file missing: $f"
done

echo "production_modified=false"
echo "live_view_started=false"
echo "status_source=PPPP_CheckDevOnline"
echo "official_check_mode=2"

"$PYTHON" -m py_compile "$SRC_DIR/run_phase6_online_status_probe.py"
echo "python_compile=PASS"

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
  -o "$TARGET_DIR/android_pppp_online_probe" \
  "$SRC_DIR/android_start.S" \
  "$SRC_DIR/android_pppp_online_probe.c" \
  -L"$RUNTIME/system/lib64" \
  -Wl,-l:libdl.so \
  -Wl,-l:libc.so \
  -Wl,-l:ld-android.so
chmod +x "$TARGET_DIR/android_pppp_online_probe"

echo "native_online_worker_build=PASS"
if ! readelf -Ws "$TARGET_DIR/libPPPP_API.so" | grep -q 'PPPP_CheckDevOnline'; then
  fail "PPPP library does not export PPPP_CheckDevOnline"
fi
echo "pppp_check_dev_online_export=PASS"

set +e
"$PYTHON" "$SRC_DIR/run_phase6_online_status_probe.py" \
  --env-file "$ENV_FILE" \
  --runtime "$RUNTIME" \
  --worker "$TARGET_DIR/android_pppp_online_probe" \
  --library "$TARGET_DIR/libPPPP_API.so" \
  --guest-library "/data/local/tmp/yi-online-status/libPPPP_API.so" \
  --qemu "$QEMU" \
  >"$RESULT"
PROBE_RC=$?
set -e

"$PYTHON" - "$RESULT" <<'PY'
import json,sys
from pathlib import Path

path=Path(sys.argv[1])
try:
    obj=json.loads(path.read_text(encoding='utf-8'))
except Exception as exc:
    raise SystemExit(f"invalid probe JSON: {exc}")

for camera in obj.get('cameras',[]):
    safe={
        'name': camera.get('name'),
        'stable_id': camera.get('stable_id'),
        'availability': camera.get('availability_state'),
        'source': camera.get('availability_source'),
        'cloud_list_online': camera.get('cloud_list_online'),
        'cloud_state': camera.get('cloud_state'),
        'cloud_online_time': camera.get('cloud_online_time'),
        'cloud_active_time': camera.get('cloud_active_time'),
        'cloud_powerstate': camera.get('cloud_powerstate'),
        'last_online_at': camera.get('last_online_at'),
        'native_result': camera.get('native_result'),
        'probe_error': camera.get('probe_error'),
    }
    print('camera_status=' + json.dumps(safe,ensure_ascii=False,separators=(',',':')))

print(f"camera_count={int(obj.get('camera_count',0))}")
print(f"tnp_camera_count={int(obj.get('tnp_camera_count',0))}")
print(f"resolved_tnp_count={int(obj.get('resolved_tnp_count',0))}")
print(f"online_count={int(obj.get('online_count',0))}")
print(f"offline_count={int(obj.get('offline_count',0))}")
print(f"unknown_count={int(obj.get('unknown_count',0))}")

disagreements=sum(
    1 for camera in obj.get('cameras',[])
    if camera.get('availability_state') in {'online','offline'}
    and isinstance(camera.get('cloud_list_online'),bool)
    and camera.get('cloud_list_online') != (camera.get('availability_state') == 'online')
)
print(f"cloud_hint_disagreement_count={disagreements}")

if obj.get('secrets_exposed') is not False or obj.get('production_modified') is not False:
    raise SystemExit('secret/production safety assertion failed')
PY

[[ "$PROBE_RC" == 0 ]] || fail "one or more TNP online checks were unresolved"
echo "all_tnp_online_checks_resolved=PASS"
echo "secret_safe_status_output=PASS"
echo "PHASE6_ONLINE_STATUS_PROBE=PASS"
