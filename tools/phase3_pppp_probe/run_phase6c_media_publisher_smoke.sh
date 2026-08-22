#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"
GO2RTC="${GO2RTC:-$PROD_ROOT/.tools/go2rtc}"
STABLE_ID="${YI_PHASE6C_TEST_STABLE_ID:-e2f22804fecdbd8c3561}"
SERVICE_PORT="${YI_PHASE6C_MEDIA_SERVICE_PORT:-18102}"
GO2RTC_API_PORT="${YI_PHASE6C_MEDIA_API_PORT:-11984}"
GO2RTC_RTSP_PORT="${YI_PHASE6C_MEDIA_RTSP_PORT:-18554}"
BASE="http://127.0.0.1:${SERVICE_PORT}/api/v1"
STREAM="yi_${STABLE_ID:0:12}"
RTSP="rtsp://127.0.0.1:${GO2RTC_RTSP_PORT}/${STREAM}"
WORK="$(mktemp -d)"
STATE_DIR="$WORK/runtime"
CACHE_FILE="$WORK/capabilities.json"
SERVICE_PID=""
PUBLISHER_PID=""

cleanup() {
  if [[ -n "$SERVICE_PID" ]] && kill -0 "$SERVICE_PID" 2>/dev/null; then
    kill -TERM "$SERVICE_PID" 2>/dev/null || true
    for _ in $(seq 1 80); do
      kill -0 "$SERVICE_PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "$SERVICE_PID" 2>/dev/null || true
  fi
  if [[ -n "$PUBLISHER_PID" ]] && kill -0 "$PUBLISHER_PID" 2>/dev/null; then
    kill -TERM "$PUBLISHER_PID" 2>/dev/null || true
    sleep 0.5
    kill -KILL "$PUBLISHER_PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

fail() {
  echo "ERROR: $*" >&2
  [[ -f "$WORK/status.json" ]] && { echo "--- camera status ---" >&2; cat "$WORK/status.json" >&2 || true; echo >&2; }
  [[ -f "$WORK/status-restart.json" ]] && { echo "--- camera restart status ---" >&2; cat "$WORK/status-restart.json" >&2 || true; echo >&2; }
  [[ -f "$WORK/service.log" ]] && { echo "--- service log ---" >&2; cat "$WORK/service.log" >&2 || true; }
  [[ -f "$STATE_DIR/$STABLE_ID.log" ]] && { echo "--- camera runtime log ---" >&2; tail -n 120 "$STATE_DIR/$STABLE_ID.log" >&2 || true; }
  [[ -f "$STATE_DIR/publisher/go2rtc.log" ]] && { echo "--- managed go2rtc log ---" >&2; tail -n 120 "$STATE_DIR/publisher/go2rtc.log" >&2 || true; }
  exit 1
}

[[ "$STABLE_ID" =~ ^[0-9a-f]{20}$ ]] || fail "invalid test stable_id"
[[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
[[ -f "$ENV_FILE" ]] || fail "env file missing: $ENV_FILE"
[[ -x "$GO2RTC" ]] || fail "go2rtc missing or not executable: $GO2RTC"
command -v curl >/dev/null || fail "curl is required"
command -v ffprobe >/dev/null || fail "ffprobe is required"
command -v timeout >/dev/null || fail "timeout is required"

"$PYTHON" -m py_compile \
  "$ROOT/yi_stream_identity.py" \
  "$ROOT/yi_media_publisher.py" \
  "$ROOT/yi_runtime_lifecycle.py" \
  "$ROOT/yi_addon_backend.py" \
  "$ROOT/yi_addon_service.py"
echo "python_compile=PASS"

echo "test_stable_id=$STABLE_ID"
echo "managed_stream=$STREAM"
echo "managed_rtsp=$RTSP"
echo "production_modified=false"
echo "production_go2rtc_ports_untouched=1984,8554"

YI_CAPABILITY_CACHE="$CACHE_FILE" \
"$PYTHON" "$ROOT/yi_addon_service.py" \
  --env-file "$ENV_FILE" \
  --bind 127.0.0.1 \
  --port "$SERVICE_PORT" \
  --runtime-state-dir "$STATE_DIR" \
  --go2rtc-bin "$GO2RTC" \
  --go2rtc-state-dir "$STATE_DIR/publisher" \
  --go2rtc-api-port "$GO2RTC_API_PORT" \
  --go2rtc-rtsp-port "$GO2RTC_RTSP_PORT" \
  --go2rtc-rtsp-bind 127.0.0.1 \
  --restart-delay 0.5 \
  --max-restart-delay 4 \
  >"$WORK/service.log" 2>&1 &
SERVICE_PID=$!
echo "phase6c_service_pid=$SERVICE_PID"

READY=0
for _ in $(seq 1 80); do
  if curl -fsS --max-time 2 "$BASE/health" >"$WORK/health.json" 2>/dev/null && \
     "$PYTHON" - "$WORK/health.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj.get('media_publisher') or {}
raise SystemExit(0 if obj.get('ok') is True and p.get('ready') is True and int(p.get('stream_count',0)) >= 1 else 1)
PY
  then
    READY=1
    break
  fi
  kill -0 "$SERVICE_PID" 2>/dev/null || fail "service exited before managed publisher became ready"
  sleep 0.5
done
[[ "$READY" == 1 ]] || fail "managed go2rtc publisher did not become ready"

read -r PUBLISHER_PID STREAM_COUNT <<<"$($PYTHON - "$WORK/health.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj['media_publisher']
print(p['pid'],p['stream_count'])
PY
)"
echo "managed_publisher_ready=PASS"
echo "managed_publisher_pid=$PUBLISHER_PID"
echo "managed_publisher_stream_count=$STREAM_COUNT"

curl -fsS --max-time 10 -X POST "$BASE/cameras/$STABLE_ID/start" >"$WORK/start.json"
echo "start_http=PASS"

FIRST_RUNTIME_PID=""
for _ in $(seq 1 120); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status.json" || true
  FIRST_RUNTIME_PID="$($PYTHON - "$WORK/status.json" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    status=obj.get('status') or {}
    r=status.get('runtime') or {}
    publication=status.get('publication') or {}
    if (r.get('runtime_state')=='running' and r.get('process_alive') is True
        and int(r.get('published_bytes',0)) >= 65536
        and publication.get('configured') is True
        and publication.get('producer_registered') is True
        and int(publication.get('mpegts_producer_count',0)) >= 1
        and isinstance(r.get('pid'),int)):
        print(r['pid'])
except Exception:
    pass
PY
)"
  [[ -n "$FIRST_RUNTIME_PID" ]] && break
  sleep 0.5
done
[[ -n "$FIRST_RUNTIME_PID" ]] || fail "go2rtc never registered the camera MPEG-TS producer"
echo "mpegts_ingest_attached=PASS"
echo "go2rtc_producer_registered=PASS"
echo "runtime_pid_initial=$FIRST_RUNTIME_PID"

if ! timeout 25 ffprobe -v error -rtsp_transport tcp \
  -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
  -of json "$RTSP" >"$WORK/ffprobe-before.json" 2>"$WORK/ffprobe-before.err"; then
  cat "$WORK/ffprobe-before.err" >&2 || true
  fail "managed RTSP endpoint did not probe"
fi
"$PYTHON" - "$WORK/ffprobe-before.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
streams=obj.get('streams',[])
v=any(s.get('codec_type')=='video' and s.get('codec_name')=='h264' and int(s.get('width',0))==1920 and int(s.get('height',0))==1080 for s in streams)
a=any(s.get('codec_type')=='audio' and s.get('codec_name')=='aac' and str(s.get('sample_rate'))=='16000' and int(s.get('channels',0))==1 for s in streams)
assert v and a
print('managed_rtsp_h264_aac=PASS')
PY

curl -fsS --max-time 15 -X POST "$BASE/cameras/$STABLE_ID/restart" >"$WORK/restart.json"
echo "restart_http=PASS"

SECOND_RUNTIME_PID=""
for _ in $(seq 1 140); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-restart.json" || true
  SECOND_RUNTIME_PID="$($PYTHON - "$WORK/status-restart.json" "$FIRST_RUNTIME_PID" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    old=int(sys.argv[2])
    status=obj.get('status') or {}
    r=status.get('runtime') or {}
    publication=status.get('publication') or {}
    pid=r.get('pid')
    if (r.get('runtime_state')=='running' and r.get('process_alive') is True
        and int(r.get('published_bytes',0)) >= 65536
        and publication.get('producer_registered') is True
        and int(publication.get('mpegts_producer_count',0)) >= 1
        and isinstance(pid,int) and pid != old):
        print(pid)
except Exception:
    pass
PY
)"
  [[ -n "$SECOND_RUNTIME_PID" ]] && break
  sleep 0.5
done
[[ -n "$SECOND_RUNTIME_PID" ]] || fail "camera did not re-register its MPEG-TS producer after restart"
echo "runtime_republish_after_restart=PASS"
echo "go2rtc_producer_reregistered=PASS"
echo "runtime_pid_restarted=$SECOND_RUNTIME_PID"

curl -fsS --max-time 3 "$BASE/health" >"$WORK/health-after.json"
PUBLISHER_PID_AFTER="$($PYTHON - "$WORK/health-after.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj.get('media_publisher') or {}
assert p.get('ready') is True
print(p['pid'])
PY
)"
[[ "$PUBLISHER_PID_AFTER" == "$PUBLISHER_PID" ]] || fail "camera restart unexpectedly restarted shared go2rtc publisher"
echo "publisher_survived_camera_restart=PASS"

if ! timeout 25 ffprobe -v error -rtsp_transport tcp \
  -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
  -of json "$RTSP" >"$WORK/ffprobe-after.json" 2>"$WORK/ffprobe-after.err"; then
  cat "$WORK/ffprobe-after.err" >&2 || true
  fail "managed RTSP endpoint did not recover after camera restart"
fi
"$PYTHON" - "$WORK/ffprobe-after.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
streams=obj.get('streams',[])
v=any(s.get('codec_type')=='video' and s.get('codec_name')=='h264' for s in streams)
a=any(s.get('codec_type')=='audio' and s.get('codec_name')=='aac' for s in streams)
assert v and a
print('managed_rtsp_after_restart=PASS')
PY

curl -fsS --max-time 15 -X POST "$BASE/cameras/$STABLE_ID/stop" >"$WORK/stop.json"
echo "runtime_stop_http=PASS"

kill -TERM "$SERVICE_PID"
for _ in $(seq 1 80); do
  if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
    SERVICE_PID=""
    break
  fi
  sleep 0.1
done
[[ -z "$SERVICE_PID" ]] || fail "service did not stop after SIGTERM"

sleep 0.5
if kill -0 "$PUBLISHER_PID" 2>/dev/null; then
  fail "managed go2rtc publisher remained after service shutdown"
fi
PUBLISHER_PID=""
echo "graceful_shutdown=PASS"
echo "managed_publisher_cleanup=PASS"
echo "PHASE6C_MEDIA_PUBLISHER_SMOKE=PASS"
