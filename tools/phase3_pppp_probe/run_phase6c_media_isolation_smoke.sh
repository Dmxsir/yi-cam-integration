#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"
GO2RTC="${GO2RTC:-$PROD_ROOT/.tools/go2rtc}"
FAULT_ID="${YI_PHASE6C_FAULT_STABLE_ID:-e2f22804fecdbd8c3561}"
PEER_ID="${YI_PHASE6C_PEER_STABLE_ID:-}"
PEER_NAME="${YI_PHASE6C_PEER_CAMERA_NAME:-pool}"
SERVICE_PORT="${YI_PHASE6C_ISOLATION_SERVICE_PORT:-18103}"
GO2RTC_API_PORT="${YI_PHASE6C_ISOLATION_API_PORT:-11985}"
GO2RTC_RTSP_PORT="${YI_PHASE6C_ISOLATION_RTSP_PORT:-18555}"
BASE="http://127.0.0.1:${SERVICE_PORT}/api/v1"
WORK="$(mktemp -d)"
STATE_DIR="$WORK/runtime"
CACHE_FILE="$WORK/capabilities.json"
SERVICE_PID=""
PUBLISHER_PID=""
FAULT_RELAY_PGID=""

cleanup() {
  if [[ -n "$FAULT_RELAY_PGID" ]]; then
    kill -CONT -- "-$FAULT_RELAY_PGID" 2>/dev/null || true
  fi
  if [[ -n "$SERVICE_PID" ]] && kill -0 "$SERVICE_PID" 2>/dev/null; then
    kill -TERM "$SERVICE_PID" 2>/dev/null || true
    for _ in $(seq 1 100); do
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
  for f in fault-status.json peer-status.json fault-recovery.json peer-recovery.json health.json health-recovery.json; do
    if [[ -f "$WORK/$f" ]]; then
      echo "--- $f ---" >&2
      cat "$WORK/$f" >&2 || true
      echo >&2
    fi
  done
  [[ -f "$WORK/service.log" ]] && { echo "--- service log ---" >&2; tail -n 160 "$WORK/service.log" >&2 || true; }
  if [[ -n "$FAULT_ID" && -f "$STATE_DIR/$FAULT_ID.log" ]]; then
    echo "--- fault camera runtime log ---" >&2
    tail -n 160 "$STATE_DIR/$FAULT_ID.log" >&2 || true
  fi
  if [[ -n "$PEER_ID" && -f "$STATE_DIR/$PEER_ID.log" ]]; then
    echo "--- peer camera runtime log ---" >&2
    tail -n 160 "$STATE_DIR/$PEER_ID.log" >&2 || true
  fi
  [[ -f "$STATE_DIR/publisher/go2rtc.log" ]] && { echo "--- managed go2rtc log ---" >&2; tail -n 160 "$STATE_DIR/publisher/go2rtc.log" >&2 || true; }
  exit 1
}

validate_id() {
  [[ "$1" =~ ^[0-9a-f]{20}$ ]]
}

stream_for() {
  printf 'yi_%s\n' "${1:0:12}"
}

rtsp_for() {
  printf 'rtsp://127.0.0.1:%s/%s\n' "$GO2RTC_RTSP_PORT" "$(stream_for "$1")"
}

wait_media_ready() {
  local stable_id="$1"
  local output="$2"
  local value=""
  for _ in $(seq 1 180); do
    curl -fsS --max-time 3 "$BASE/cameras/$stable_id/status" >"$output" 2>/dev/null || true
    value="$($PYTHON - "$output" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    status=obj.get('status') or {}
    runtime=status.get('runtime') or {}
    publication=status.get('publication') or {}
    pid=runtime.get('pid')
    generation=runtime.get('generation')
    ready=(
        runtime.get('runtime_state') == 'running'
        and runtime.get('process_alive') is True
        and isinstance(pid,int)
        and isinstance(generation,int)
        and int(runtime.get('published_bytes',0)) >= 65536
        and publication.get('configured') is True
        and publication.get('producer_registered') is True
        and int(publication.get('mpegts_producer_count',0)) >= 1
        and publication.get('producer_media_ready') is True
        and int(publication.get('mpegts_ready_producer_count',0)) >= 1
    )
    if ready:
        print(pid,generation)
except Exception:
    pass
PY
)"
    [[ -n "$value" ]] && { printf '%s\n' "$value"; return 0; }
    kill -0 "$SERVICE_PID" 2>/dev/null || return 1
    sleep 0.5
  done
  return 1
}

validate_rtsp() {
  local stable_id="$1"
  local output="$2"
  local err="$3"
  local url
  url="$(rtsp_for "$stable_id")"
  if ! timeout 25 ffprobe -v error -rtsp_transport tcp \
      -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
      -of json "$url" >"$output" 2>"$err"; then
    cat "$err" >&2 || true
    return 1
  fi
  "$PYTHON" - "$output" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
streams=obj.get('streams',[])
video=any(s.get('codec_type')=='video' and s.get('codec_name')=='h264' for s in streams)
audio=any(s.get('codec_type')=='audio' and s.get('codec_name')=='aac' for s in streams)
raise SystemExit(0 if video and audio else 1)
PY
}

find_fault_relay_pgid() {
  local supervisor_pid="$1"
  local stable_id="$2"
  "$PYTHON" - "$supervisor_pid" "$stable_id" <<'PY'
from pathlib import Path
import os,re,sys

supervisor=int(sys.argv[1])
stable_id=sys.argv[2]
candidates=[]
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    pid=int(entry.name)
    try:
        status=(entry/'status').read_text(encoding='utf-8',errors='replace')
        match=re.search(r'^PPid:\s+(\d+)$',status,re.MULTILINE)
        if not match or int(match.group(1)) != supervisor:
            continue
        argv=(entry/'cmdline').read_bytes().split(b'\0')
        args=[item.decode('utf-8','replace') for item in argv if item]
        command=' '.join(args)
        if 'yi_native_av_relay_stable.py' not in command:
            continue
        if '--stable-id' not in args or stable_id not in args:
            continue
        pgid=os.getpgid(pid)
        sid=os.getsid(pid)
    except (OSError,ValueError,ProcessLookupError):
        continue
    if pgid == pid and sid == pid:
        candidates.append(pid)

if len(candidates) != 1:
    raise SystemExit(2)
print(candidates[0])
PY
}

validate_id "$FAULT_ID" || fail "invalid fault camera stable_id"
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
echo "production_modified=false"
echo "production_go2rtc_ports_untouched=1984,8554"
echo "isolation_service_port=$SERVICE_PORT"
echo "isolation_go2rtc_api_port=$GO2RTC_API_PORT"
echo "isolation_go2rtc_rtsp_port=$GO2RTC_RTSP_PORT"

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
for _ in $(seq 1 100); do
  if curl -fsS --max-time 2 "$BASE/health" >"$WORK/health.json" 2>/dev/null && \
     "$PYTHON" - "$WORK/health.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj.get('media_publisher') or {}
raise SystemExit(0 if obj.get('ok') is True and p.get('ready') is True and int(p.get('stream_count',0)) >= 2 else 1)
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

curl -fsS --max-time 5 "$BASE/cameras" >"$WORK/cameras.json" || fail "camera inventory unavailable"
if [[ -z "$PEER_ID" ]]; then
  PEER_ID="$($PYTHON - "$WORK/cameras.json" "$FAULT_ID" "$PEER_NAME" <<'PY'
import json,re,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
fault=sys.argv[2]
preferred=sys.argv[3].casefold()
cameras=obj.get('cameras') or []
eligible=[]
for camera in cameras:
    sid=camera.get('stable_id')
    if not isinstance(sid,str) or not re.fullmatch(r'[0-9a-f]{20}',sid) or sid == fault:
        continue
    if camera.get('transport') != 'tnp' or camera.get('cloud_online_reported') is not True:
        continue
    eligible.append(camera)
if not eligible:
    raise SystemExit(2)
preferred_matches=[c for c in eligible if str(c.get('name','')).casefold() == preferred]
selected=(preferred_matches or sorted(eligible,key=lambda c:c['stable_id']))[0]
print(selected['stable_id'])
PY
)" || fail "could not auto-select an online TNP peer camera"
fi
validate_id "$PEER_ID" || fail "invalid peer camera stable_id"
[[ "$PEER_ID" != "$FAULT_ID" ]] || fail "fault and peer cameras must be different"

"$PYTHON" - "$WORK/cameras.json" "$FAULT_ID" "$PEER_ID" <<'PY' || fail "selected camera is not present in discovery inventory"
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
ids={c.get('stable_id') for c in (obj.get('cameras') or [])}
raise SystemExit(0 if sys.argv[2] in ids and sys.argv[3] in ids else 1)
PY

echo "fault_stable_id=$FAULT_ID"
echo "peer_stable_id=$PEER_ID"
echo "fault_stream=$(stream_for "$FAULT_ID")"
echo "peer_stream=$(stream_for "$PEER_ID")"

curl -fsS --max-time 12 -X POST "$BASE/cameras/$FAULT_ID/start" >"$WORK/fault-start.json" &
START_FAULT_PID=$!
curl -fsS --max-time 12 -X POST "$BASE/cameras/$PEER_ID/start" >"$WORK/peer-start.json" &
START_PEER_PID=$!
wait "$START_FAULT_PID" || fail "fault camera start request failed"
wait "$START_PEER_PID" || fail "peer camera start request failed"
echo "parallel_start_http=PASS"

FAULT_READY="$(wait_media_ready "$FAULT_ID" "$WORK/fault-status.json")" || fail "fault camera never became media-ready"
PEER_READY="$(wait_media_ready "$PEER_ID" "$WORK/peer-status.json")" || fail "peer camera never became media-ready"
read -r FAULT_PID_INITIAL FAULT_GEN_INITIAL <<<"$FAULT_READY"
read -r PEER_PID_INITIAL PEER_GEN_INITIAL <<<"$PEER_READY"
echo "fault_media_ready=PASS"
echo "peer_media_ready=PASS"
echo "fault_runtime_pid_initial=$FAULT_PID_INITIAL"
echo "fault_runtime_generation_initial=$FAULT_GEN_INITIAL"
echo "peer_runtime_pid_initial=$PEER_PID_INITIAL"
echo "peer_runtime_generation_initial=$PEER_GEN_INITIAL"

validate_rtsp "$FAULT_ID" "$WORK/fault-before.json" "$WORK/fault-before.err" || fail "fault camera RTSP did not validate before fault"
validate_rtsp "$PEER_ID" "$WORK/peer-before.json" "$WORK/peer-before.err" || fail "peer camera RTSP did not validate before fault"
echo "dual_rtsp_h264_aac=PASS"

FAULT_RELAY_PGID="$(find_fault_relay_pgid "$FAULT_PID_INITIAL" "$FAULT_ID")" || fail "could not identify exactly one relay process group for fault camera"
[[ "$FAULT_RELAY_PGID" =~ ^[0-9]+$ ]] || fail "invalid scoped relay process group"
kill -STOP -- "-$FAULT_RELAY_PGID" || fail "failed to freeze scoped fault-camera relay process group"
echo "fault_injection_scoped_relay_group=PASS"
echo "fault_relay_pgid=$FAULT_RELAY_PGID"

validate_rtsp "$PEER_ID" "$WORK/peer-during-fault.json" "$WORK/peer-during-fault.err" || fail "peer RTSP failed during selected-camera fault"
echo "peer_rtsp_during_fault=PASS"

RECOVERED=0
FAULT_PID_RECOVERED=""
FAULT_GEN_RECOVERED=""
for _ in $(seq 1 180); do
  curl -fsS --max-time 3 "$BASE/cameras/$FAULT_ID/status" >"$WORK/fault-recovery.json" 2>/dev/null || true
  curl -fsS --max-time 3 "$BASE/cameras/$PEER_ID/status" >"$WORK/peer-recovery.json" 2>/dev/null || true
  curl -fsS --max-time 3 "$BASE/health" >"$WORK/health-recovery.json" 2>/dev/null || true

  CHECK="$($PYTHON - "$WORK/fault-recovery.json" "$WORK/peer-recovery.json" "$WORK/health-recovery.json" \
      "$FAULT_PID_INITIAL" "$FAULT_GEN_INITIAL" "$PEER_PID_INITIAL" "$PEER_GEN_INITIAL" "$PUBLISHER_PID" <<'PY'
import json,sys
try:
    fault=json.load(open(sys.argv[1],encoding='utf-8')).get('status') or {}
    peer=json.load(open(sys.argv[2],encoding='utf-8')).get('status') or {}
    health=json.load(open(sys.argv[3],encoding='utf-8'))
    old_fault_pid=int(sys.argv[4]); old_fault_gen=int(sys.argv[5])
    peer_pid=int(sys.argv[6]); peer_gen=int(sys.argv[7]); publisher_pid=int(sys.argv[8])
    fr=fault.get('runtime') or {}; fp=fault.get('publication') or {}
    pr=peer.get('runtime') or {}; pub=health.get('media_publisher') or {}
    if pr.get('pid') != peer_pid or pr.get('generation') != peer_gen:
        print('PEER_CHANGED')
        raise SystemExit
    if pub.get('pid') != publisher_pid or pub.get('ready') is not True:
        print('PUBLISHER_CHANGED')
        raise SystemExit
    new_pid=fr.get('pid'); new_gen=fr.get('generation')
    ready=(
        fr.get('runtime_state') == 'running'
        and fr.get('process_alive') is True
        and isinstance(new_pid,int) and new_pid != old_fault_pid
        and isinstance(new_gen,int) and new_gen > old_fault_gen
        and int(fr.get('published_bytes',0)) >= 65536
        and fp.get('producer_media_ready') is True
        and int(fp.get('mpegts_ready_producer_count',0)) >= 1
    )
    if ready:
        print('RECOVERED',new_pid,new_gen)
    else:
        print('WAIT')
except Exception:
    print('WAIT')
PY
)"
  case "$CHECK" in
    PEER_CHANGED) fail "peer camera runtime changed during fault recovery" ;;
    PUBLISHER_CHANGED) fail "shared go2rtc changed during fault recovery" ;;
    RECOVERED\ *)
      read -r _ FAULT_PID_RECOVERED FAULT_GEN_RECOVERED <<<"$CHECK"
      RECOVERED=1
      break
      ;;
  esac
  kill -0 "$SERVICE_PID" 2>/dev/null || fail "service exited during fault recovery"
  sleep 0.5
done
[[ "$RECOVERED" == 1 ]] || fail "fault camera did not recover through lifecycle recreation"
echo "fault_camera_recreated=PASS"
echo "fault_runtime_pid_recovered=$FAULT_PID_RECOVERED"
echo "fault_runtime_generation_recovered=$FAULT_GEN_RECOVERED"
echo "peer_runtime_unchanged=PASS"
echo "publisher_survived_fault=PASS"

if kill -0 -- "-$FAULT_RELAY_PGID" 2>/dev/null; then
  kill -CONT -- "-$FAULT_RELAY_PGID" 2>/dev/null || true
  fail "original faulted relay process group remained alive after camera recovery"
fi
FAULT_RELAY_PGID=""
echo "faulted_runtime_descendant_cleanup=PASS"

validate_rtsp "$FAULT_ID" "$WORK/fault-after.json" "$WORK/fault-after.err" || fail "fault camera RTSP did not recover"
validate_rtsp "$PEER_ID" "$WORK/peer-after.json" "$WORK/peer-after.err" || fail "peer camera RTSP failed after recovery"
echo "dual_rtsp_after_recovery=PASS"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$FAULT_ID/stop" >"$WORK/fault-stop.json" || fail "fault camera stop failed"
curl -fsS --max-time 15 -X POST "$BASE/cameras/$PEER_ID/stop" >"$WORK/peer-stop.json" || fail "peer camera stop failed"
echo "dual_runtime_stop_http=PASS"

kill -TERM "$SERVICE_PID"
for _ in $(seq 1 100); do
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
echo "PHASE6C_MEDIA_ISOLATION_SMOKE=PASS"
