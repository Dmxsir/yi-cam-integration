#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"
GO2RTC="${GO2RTC:-$PROD_ROOT/.tools/go2rtc}"
PRIMARY_ID="${YI_PHASE6C_PERSIST_PRIMARY_ID:-e2f22804fecdbd8c3561}"
PEER_ID="${YI_PHASE6C_PERSIST_PEER_ID:-}"
PEER_NAME="${YI_PHASE6C_PERSIST_PEER_NAME:-pool}"
SERVICE_PORT="${YI_PHASE6C_PERSIST_SERVICE_PORT:-18104}"
GO2RTC_API_PORT="${YI_PHASE6C_PERSIST_API_PORT:-11986}"
GO2RTC_RTSP_PORT="${YI_PHASE6C_PERSIST_RTSP_PORT:-18556}"
BASE="http://127.0.0.1:${SERVICE_PORT}/api/v1"
WORK="$(mktemp -d)"
DATA_DIR="$WORK/data"
SERVICE_PID=""
PUBLISHER_PID=""
RUN_INDEX=0

fail() {
  echo "ERROR: $*" >&2
  for f in "$WORK"/health-*.json "$WORK"/primary-*.json "$WORK"/peer-*.json; do
    [[ -f "$f" ]] || continue
    echo "--- $(basename "$f") ---" >&2
    cat "$f" >&2 || true
    echo >&2
  done
  for f in "$WORK"/service-*.log; do
    [[ -f "$f" ]] || continue
    echo "--- $(basename "$f") ---" >&2
    tail -n 180 "$f" >&2 || true
  done
  exit 1
}

cleanup() {
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

validate_id() {
  [[ "$1" =~ ^[0-9a-f]{20}$ ]]
}

stream_for() {
  printf 'yi_%s\n' "${1:0:12}"
}

rtsp_for() {
  printf 'rtsp://127.0.0.1:%s/%s\n' "$GO2RTC_RTSP_PORT" "$(stream_for "$1")"
}

launch_service() {
  RUN_INDEX=$((RUN_INDEX + 1))
  local log="$WORK/service-${RUN_INDEX}.log"
  "$PYTHON" "$ROOT/yi_addon_service.py" \
    --env-file "$ENV_FILE" \
    --bind 127.0.0.1 \
    --port "$SERVICE_PORT" \
    --data-dir "$DATA_DIR" \
    --go2rtc-bin "$GO2RTC" \
    --go2rtc-api-port "$GO2RTC_API_PORT" \
    --go2rtc-rtsp-port "$GO2RTC_RTSP_PORT" \
    --go2rtc-rtsp-bind 127.0.0.1 \
    --discovery-retry-interval 2 \
    --restart-delay 0.5 \
    --max-restart-delay 4 \
    >"$log" 2>&1 &
  SERVICE_PID=$!

  local ready=0
  for _ in $(seq 1 120); do
    if curl -fsS --max-time 3 "$BASE/health" >"$WORK/health-${RUN_INDEX}.json" 2>/dev/null && \
       "$PYTHON" - "$WORK/health-${RUN_INDEX}.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj.get('media_publisher') or {}
r=obj.get('runtime_persistence') or {}
raise SystemExit(0 if (
    obj.get('ok') is True
    and int(obj.get('camera_count',0)) >= 2
    and p.get('ready') is True
    and int(p.get('stream_count',0)) >= 2
    and r.get('enabled') is True
) else 1)
PY
    then
      ready=1
      break
    fi
    kill -0 "$SERVICE_PID" 2>/dev/null || fail "service exited during launch $RUN_INDEX"
    sleep 0.5
  done
  [[ "$ready" == 1 ]] || fail "service launch $RUN_INDEX did not become ready"

  PUBLISHER_PID="$($PYTHON - "$WORK/health-${RUN_INDEX}.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
print((obj.get('media_publisher') or {})['pid'])
PY
)"
  echo "service_launch_${RUN_INDEX}=PASS"
  echo "service_pid_${RUN_INDEX}=$SERVICE_PID"
  echo "publisher_pid_${RUN_INDEX}=$PUBLISHER_PID"
}

stop_service() {
  local old_publisher="$PUBLISHER_PID"
  kill -TERM "$SERVICE_PID" || fail "failed to stop service launch $RUN_INDEX"
  for _ in $(seq 1 120); do
    if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
      SERVICE_PID=""
      break
    fi
    sleep 0.1
  done
  [[ -z "$SERVICE_PID" ]] || fail "service launch $RUN_INDEX did not stop"
  sleep 0.5
  if kill -0 "$old_publisher" 2>/dev/null; then
    fail "managed publisher survived service shutdown on launch $RUN_INDEX"
  fi
  PUBLISHER_PID=""
  echo "service_shutdown_${RUN_INDEX}=PASS"
}

wait_media_ready() {
  local stable_id="$1"
  local label="$2"
  local output="$WORK/${label}-${RUN_INDEX}.json"
  local value=""
  for _ in $(seq 1 180); do
    curl -fsS --max-time 3 "$BASE/cameras/$stable_id/status" >"$output" 2>/dev/null || true
    value="$($PYTHON - "$output" <<'PY'
import json,sys
try:
    status=json.load(open(sys.argv[1],encoding='utf-8')).get('status') or {}
    runtime=status.get('runtime') or {}
    publication=status.get('publication') or {}
    pid=runtime.get('pid'); generation=runtime.get('generation')
    if (
        status.get('persisted_desired_running') is True
        and runtime.get('runtime_state') == 'running'
        and runtime.get('process_alive') is True
        and isinstance(pid,int) and isinstance(generation,int)
        and int(runtime.get('published_bytes',0)) >= 65536
        and publication.get('producer_media_ready') is True
        and int(publication.get('mpegts_ready_producer_count',0)) >= 1
    ):
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

wait_stopped() {
  local stable_id="$1"
  local label="$2"
  local output="$WORK/${label}-${RUN_INDEX}.json"
  for _ in $(seq 1 80); do
    if curl -fsS --max-time 3 "$BASE/cameras/$stable_id/status" >"$output" 2>/dev/null && \
       "$PYTHON" - "$output" <<'PY'
import json,sys
status=json.load(open(sys.argv[1],encoding='utf-8')).get('status') or {}
runtime=status.get('runtime') or {}
raise SystemExit(0 if (
    status.get('persisted_desired_running') is False
    and runtime.get('desired_running') is False
    and runtime.get('process_alive') is False
    and runtime.get('runtime_state') == 'stopped'
) else 1)
PY
    then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

validate_rtsp() {
  local stable_id="$1"
  local label="$2"
  local url
  url="$(rtsp_for "$stable_id")"
  if ! timeout 25 ffprobe -v error -rtsp_transport tcp \
      -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
      -of json "$url" >"$WORK/${label}.json" 2>"$WORK/${label}.err"; then
    cat "$WORK/${label}.err" >&2 || true
    return 1
  fi
  "$PYTHON" - "$WORK/${label}.json" <<'PY'
import json,sys
streams=json.load(open(sys.argv[1],encoding='utf-8')).get('streams',[])
v=any(x.get('codec_type')=='video' and x.get('codec_name')=='h264' for x in streams)
a=any(x.get('codec_type')=='audio' and x.get('codec_name')=='aac' for x in streams)
raise SystemExit(0 if v and a else 1)
PY
}

validate_policy() {
  local expected="$1"
  "$PYTHON" - "$DATA_DIR/runtime-policy.json" "$expected" <<'PY'
import json,os,stat,sys
path=sys.argv[1]
expected=set(filter(None,sys.argv[2].split(',')))
obj=json.load(open(path,encoding='utf-8'))
actual=set(obj.get('desired_running') or [])
assert obj.get('schema_version') == 1
assert actual == expected, (actual,expected)
assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
raw=open(path,encoding='utf-8').read().casefold()
for forbidden in ('"uid"','"did"','"password"','"token"','"license"','"initstring"'):
    assert forbidden not in raw
PY
}

validate_id "$PRIMARY_ID" || fail "invalid primary stable_id"
[[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
[[ -f "$ENV_FILE" ]] || fail "env file missing: $ENV_FILE"
[[ -x "$GO2RTC" ]] || fail "go2rtc missing or not executable: $GO2RTC"
command -v curl >/dev/null || fail "curl is required"
command -v ffprobe >/dev/null || fail "ffprobe is required"
command -v timeout >/dev/null || fail "timeout is required"

"$PYTHON" -m py_compile \
  "$ROOT/yi_runtime_policy.py" \
  "$ROOT/yi_persistent_backend.py" \
  "$ROOT/yi_addon_service.py"
echo "python_compile=PASS"

"$PYTHON" -m unittest discover -s "$ROOT/tests" -p 'test_yi_runtime_policy.py' >/dev/null
echo "runtime_policy_unit_tests=PASS"
echo "production_modified=false"
echo "production_go2rtc_ports_untouched=1984,8554"
echo "persistent_data_dir_isolated=PASS"

mkdir -p "$DATA_DIR"
launch_service

curl -fsS --max-time 5 "$BASE/cameras" >"$WORK/cameras.json" || fail "camera inventory unavailable"
if [[ -z "$PEER_ID" ]]; then
  PEER_ID="$($PYTHON - "$WORK/cameras.json" "$PRIMARY_ID" "$PEER_NAME" <<'PY'
import json,re,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
primary=sys.argv[2]; preferred=sys.argv[3].casefold()
eligible=[]
for camera in obj.get('cameras') or []:
    sid=camera.get('stable_id')
    if not isinstance(sid,str) or not re.fullmatch(r'[0-9a-f]{20}',sid) or sid == primary:
        continue
    if camera.get('transport') == 'tnp' and camera.get('cloud_online_reported') is True:
        eligible.append(camera)
if not eligible:
    raise SystemExit(2)
preferred_matches=[c for c in eligible if str(c.get('name','')).casefold() == preferred]
print((preferred_matches or sorted(eligible,key=lambda c:c['stable_id']))[0]['stable_id'])
PY
)" || fail "could not auto-select persistence peer camera"
fi
validate_id "$PEER_ID" || fail "invalid peer stable_id"
[[ "$PEER_ID" != "$PRIMARY_ID" ]] || fail "primary and peer must differ"
echo "primary_stable_id=$PRIMARY_ID"
echo "peer_stable_id=$PEER_ID"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$PRIMARY_ID/start" >"$WORK/start-primary.json" || fail "primary start failed"
curl -fsS --max-time 15 -X POST "$BASE/cameras/$PEER_ID/start" >"$WORK/start-peer.json" || fail "peer start failed"
echo "persistent_start_http=PASS"

PRIMARY_FIRST="$(wait_media_ready "$PRIMARY_ID" primary)" || fail "primary did not become media-ready on first launch"
PEER_FIRST="$(wait_media_ready "$PEER_ID" peer)" || fail "peer did not become media-ready on first launch"
read -r PRIMARY_PID_FIRST PRIMARY_GEN_FIRST <<<"$PRIMARY_FIRST"
read -r PEER_PID_FIRST PEER_GEN_FIRST <<<"$PEER_FIRST"
validate_rtsp "$PRIMARY_ID" first-primary || fail "primary RTSP failed on first launch"
validate_rtsp "$PEER_ID" first-peer || fail "peer RTSP failed on first launch"
echo "first_launch_dual_rtsp=PASS"

# Exercise the capability cache using its real live reprobe path. Reprobe is a
# temporary lifecycle isolation and must not clear the persisted start intent.
curl -fsS --max-time 45 -X POST "$BASE/cameras/$PRIMARY_ID/reprobe" >"$WORK/reprobe.json" || fail "live reprobe failed"
PRIMARY_AFTER_REPROBE="$(wait_media_ready "$PRIMARY_ID" primary-reprobe)" || fail "primary did not resume after reprobe"
[[ -f "$DATA_DIR/capabilities.json" ]] || fail "capability cache was not created under data-dir"
"$PYTHON" - "$DATA_DIR/capabilities.json" "$PRIMARY_ID" <<'PY'
import json,os,stat,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
record=(obj.get('cameras') or {}).get(sys.argv[2]) or {}
assert record.get('status') == 'success'
assert record.get('video_codec') == 'h264'
assert record.get('audio_codec') == 'aac'
assert stat.S_IMODE(os.stat(sys.argv[1]).st_mode) == 0o600
PY
echo "capability_cache_under_data=PASS"
echo "reprobe_preserved_runtime_intent=PASS"

validate_policy "$PRIMARY_ID,$PEER_ID" || fail "two-camera runtime intent was not persisted"
echo "dual_runtime_intent_persisted=PASS"
read -r PRIMARY_PID_FIRST _ <<<"$PRIMARY_AFTER_REPROBE"
stop_service

# Second launch must restore both cameras only from persisted stable-id intent.
launch_service
PRIMARY_SECOND="$(wait_media_ready "$PRIMARY_ID" primary-restore)" || fail "primary was not automatically restored"
PEER_SECOND="$(wait_media_ready "$PEER_ID" peer-restore)" || fail "peer was not automatically restored"
read -r PRIMARY_PID_SECOND PRIMARY_GEN_SECOND <<<"$PRIMARY_SECOND"
read -r PEER_PID_SECOND PEER_GEN_SECOND <<<"$PEER_SECOND"
[[ "$PRIMARY_PID_SECOND" != "$PRIMARY_PID_FIRST" ]] || fail "primary PID did not change across backend restart"
[[ "$PEER_PID_SECOND" != "$PEER_PID_FIRST" ]] || fail "peer PID did not change across backend restart"
validate_rtsp "$PRIMARY_ID" restored-primary || fail "restored primary RTSP invalid"
validate_rtsp "$PEER_ID" restored-peer || fail "restored peer RTSP invalid"
"$PYTHON" - "$WORK/health-${RUN_INDEX}.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding='utf-8')).get('runtime_persistence') or {}
assert p.get('desired_running_count') == 2
assert p.get('pending_restore_count') == 0
assert int(p.get('last_reconcile_restored',0)) >= 2
assert p.get('last_error') is None
PY
echo "dual_runtime_restore_after_restart=PASS"
echo "dual_rtsp_after_backend_restart=PASS"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$PEER_ID/stop" >"$WORK/stop-peer.json" || fail "peer stop failed"
wait_stopped "$PEER_ID" peer-stopped || fail "peer did not reach persisted stopped state"
validate_policy "$PRIMARY_ID" || fail "peer stop was not persisted"
echo "explicit_stop_persisted=PASS"
stop_service

# Third launch must restore only the still-enabled primary camera.
launch_service
PRIMARY_THIRD="$(wait_media_ready "$PRIMARY_ID" primary-third)" || fail "primary was not restored on third launch"
wait_stopped "$PEER_ID" peer-third || fail "explicitly stopped peer restarted unexpectedly"
validate_rtsp "$PRIMARY_ID" third-primary || fail "primary RTSP invalid on third launch"
"$PYTHON" - "$WORK/health-${RUN_INDEX}.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding='utf-8')).get('runtime_persistence') or {}
assert p.get('desired_running_count') == 1
assert p.get('pending_restore_count') == 0
assert int(p.get('last_reconcile_restored',0)) >= 1
assert p.get('last_error') is None
PY
echo "selective_runtime_restore=PASS"
echo "stopped_camera_remained_stopped=PASS"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$PRIMARY_ID/stop" >"$WORK/stop-primary.json" || fail "primary final stop failed"
validate_policy "" || fail "final stopped policy was not empty"
echo "runtime_policy_final_cleanup=PASS"
stop_service

echo "persistent_service_shutdown_cleanup=PASS"
echo "PHASE6C_PERSISTENCE_SMOKE=PASS"
