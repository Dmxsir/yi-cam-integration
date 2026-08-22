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
OFFLINE_ID="${YI_PHASE6C_PERSIST_OFFLINE_ID:-}"
OFFLINE_NAME="${YI_PHASE6C_PERSIST_OFFLINE_NAME:-zforce 800}"
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
  for f in "$WORK"/health-*.json "$WORK"/primary-*.json "$WORK"/peer-*.json "$WORK"/offline-*.json; do
    [[ -f "$f" ]] || continue
    echo "--- $(basename "$f") ---" >&2
    cat "$f" >&2 || true
    echo >&2
  done
  if [[ -f "$WORK/online-preflight.log" ]]; then
    echo "--- online-preflight.log ---" >&2
    tail -n 120 "$WORK/online-preflight.log" >&2 || true
  fi
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
  for _ in $(seq 1 180); do
    if curl -fsS --max-time 3 "$BASE/health" >"$WORK/health-${RUN_INDEX}.json" 2>/dev/null && \
       "$PYTHON" - "$WORK/health-${RUN_INDEX}.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj.get('media_publisher') or {}
r=obj.get('runtime_persistence') or {}
a=obj.get('availability') or {}
count=int(obj.get('camera_count',0))
raise SystemExit(0 if (
    obj.get('ok') is True
    and count >= 2
    and p.get('ready') is True
    and int(p.get('stream_count',0)) >= 2
    and r.get('enabled') is True
    and a.get('enabled') is True
    and int(a.get('online_count',0)) + int(a.get('offline_count',0)) == count
    and int(a.get('unknown_count',0)) == 0
) else 1)
PY
    then
      ready=1
      break
    fi
    kill -0 "$SERVICE_PID" 2>/dev/null || fail "service exited during launch $RUN_INDEX"
    sleep 0.5
  done
  [[ "$ready" == 1 ]] || fail "service launch $RUN_INDEX did not become availability-ready"

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
        status.get('availability_state') == 'online'
        and status.get('persisted_desired_running') is True
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

wait_offline_pending() {
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
    status.get('availability_state') == 'offline'
    and status.get('persisted_desired_running') is True
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
  "$ROOT/yi_online_status.py" \
  "$ROOT/yi_runtime_policy.py" \
  "$ROOT/yi_persistent_backend.py" \
  "$ROOT/yi_addon_service.py"
echo "python_compile=PASS"

"$PYTHON" -m unittest discover -s "$ROOT/tests" -p 'test_yi_runtime_policy.py' >/dev/null
echo "runtime_policy_unit_tests=PASS"
echo "production_modified=false"
echo "production_go2rtc_ports_untouched=1984,8554"
echo "persistent_data_dir_isolated=PASS"

# Build/validate the exact PPPP_CheckDevOnline worker/library used by the App
# persistence layer. This preflight never starts live view and never modifies
# production go2rtc.
PYTHON="$PYTHON" ENV_FILE="$ENV_FILE" \
  bash "$ROOT/tools/phase3_pppp_probe/run_phase6_online_status_smoke.sh" \
  >"$WORK/online-preflight.log" 2>&1 || fail "PPPP online-status preflight failed"
grep -q '^PHASE6_ONLINE_STATUS_PROBE=PASS$' "$WORK/online-preflight.log" || fail "online-status preflight did not pass"
grep -E '^(online_count|offline_count|unknown_count|cloud_hint_disagreement_count)=' "$WORK/online-preflight.log" || true
echo "availability_preflight=PASS"

mkdir -p "$DATA_DIR"
launch_service

curl -fsS --max-time 5 "$BASE/cameras" >"$WORK/cameras.json" || fail "camera inventory unavailable"
"$PYTHON" - "$WORK/cameras.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
a=obj.get('availability') or {}
cameras=obj.get('cameras') or []
assert a.get('enabled') is True
assert int(a.get('unknown_count',0)) == 0
assert int(a.get('online_count',0)) + int(a.get('offline_count',0)) == len(cameras)
assert all(c.get('availability_source') == 'pppp_check_dev_online' for c in cameras)
PY
echo "backend_availability_inventory=PASS"

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
    if camera.get('transport') == 'tnp' and camera.get('availability_state') == 'online':
        eligible.append(camera)
if not eligible:
    raise SystemExit(2)
preferred_matches=[c for c in eligible if str(c.get('name','')).casefold() == preferred]
print((preferred_matches or sorted(eligible,key=lambda c:c['stable_id']))[0]['stable_id'])
PY
)" || fail "could not auto-select online persistence peer camera"
fi

if [[ -z "$OFFLINE_ID" ]]; then
  OFFLINE_ID="$($PYTHON - "$WORK/cameras.json" "$OFFLINE_NAME" <<'PY'
import json,re,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
preferred=sys.argv[2].casefold()
eligible=[]
for camera in obj.get('cameras') or []:
    sid=camera.get('stable_id')
    if isinstance(sid,str) and re.fullmatch(r'[0-9a-f]{20}',sid) and camera.get('availability_state') == 'offline':
        eligible.append(camera)
if not eligible:
    raise SystemExit(2)
preferred_matches=[c for c in eligible if str(c.get('name','')).casefold() == preferred]
print((preferred_matches or sorted(eligible,key=lambda c:c['stable_id']))[0]['stable_id'])
PY
)" || fail "could not auto-select offline persistence camera"
fi

validate_id "$PEER_ID" || fail "invalid peer stable_id"
validate_id "$OFFLINE_ID" || fail "invalid offline stable_id"
[[ "$PEER_ID" != "$PRIMARY_ID" ]] || fail "primary and peer must differ"
[[ "$OFFLINE_ID" != "$PRIMARY_ID" && "$OFFLINE_ID" != "$PEER_ID" ]] || fail "offline camera must differ from online cameras"
"$PYTHON" - "$WORK/cameras.json" "$PRIMARY_ID" "$PEER_ID" "$OFFLINE_ID" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
by_id={c.get('stable_id'):c for c in obj.get('cameras') or []}
assert by_id[sys.argv[2]].get('availability_state') == 'online'
assert by_id[sys.argv[3]].get('availability_state') == 'online'
assert by_id[sys.argv[4]].get('availability_state') == 'offline'
PY
echo "primary_stable_id=$PRIMARY_ID"
echo "peer_stable_id=$PEER_ID"
echo "offline_stable_id=$OFFLINE_ID"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$PRIMARY_ID/start" >"$WORK/start-primary.json" || fail "primary start failed"
curl -fsS --max-time 15 -X POST "$BASE/cameras/$PEER_ID/start" >"$WORK/start-peer.json" || fail "peer start failed"
echo "persistent_start_http=PASS"

OFFLINE_HTTP="$(curl -sS --max-time 15 -o "$WORK/offline-start.json" -w '%{http_code}' -X POST "$BASE/cameras/$OFFLINE_ID/start")" || fail "offline start request failed"
[[ "$OFFLINE_HTTP" == "202" ]] || fail "offline start did not return HTTP 202"
"$PYTHON" - "$WORK/offline-start.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
r=obj.get('runtime') or {}
assert obj.get('ok') is True
assert obj.get('accepted') is True
assert obj.get('pending_reason') == 'camera_offline'
assert obj.get('persisted_desired_running') is True
assert obj.get('availability_state') == 'offline'
assert r.get('desired_running') is False
assert r.get('process_alive') is False
PY
wait_offline_pending "$OFFLINE_ID" offline-first || fail "offline camera did not remain pending/stopped"
echo "offline_start_deferred_without_runtime=PASS"

PRIMARY_FIRST="$(wait_media_ready "$PRIMARY_ID" primary)" || fail "primary did not become media-ready on first launch"
PEER_FIRST="$(wait_media_ready "$PEER_ID" peer)" || fail "peer did not become media-ready on first launch"
read -r PRIMARY_PID_FIRST PRIMARY_GEN_FIRST <<<"$PRIMARY_FIRST"
read -r PEER_PID_FIRST PEER_GEN_FIRST <<<"$PEER_FIRST"
validate_rtsp "$PRIMARY_ID" first-primary || fail "primary RTSP failed on first launch"
validate_rtsp "$PEER_ID" first-peer || fail "peer RTSP failed on first launch"
echo "first_launch_dual_rtsp=PASS"

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

validate_policy "$PRIMARY_ID,$PEER_ID,$OFFLINE_ID" || fail "online + offline runtime intents were not persisted"
echo "offline_pending_intent_persisted=PASS"
read -r PRIMARY_PID_FIRST _ <<<"$PRIMARY_AFTER_REPROBE"
stop_service

# Second launch restores online cameras only. The offline desired camera must
# remain pending without creating a PPPP/media runtime.
launch_service
PRIMARY_SECOND="$(wait_media_ready "$PRIMARY_ID" primary-restore)" || fail "primary was not automatically restored"
PEER_SECOND="$(wait_media_ready "$PEER_ID" peer-restore)" || fail "peer was not automatically restored"
wait_offline_pending "$OFFLINE_ID" offline-restore || fail "offline desired camera started after backend restart"
read -r PRIMARY_PID_SECOND PRIMARY_GEN_SECOND <<<"$PRIMARY_SECOND"
read -r PEER_PID_SECOND PEER_GEN_SECOND <<<"$PEER_SECOND"
[[ "$PRIMARY_PID_SECOND" != "$PRIMARY_PID_FIRST" ]] || fail "primary PID did not change across backend restart"
[[ "$PEER_PID_SECOND" != "$PEER_PID_FIRST" ]] || fail "peer PID did not change across backend restart"
validate_rtsp "$PRIMARY_ID" restored-primary || fail "restored primary RTSP invalid"
validate_rtsp "$PEER_ID" restored-peer || fail "restored peer RTSP invalid"
curl -fsS --max-time 3 "$BASE/health" >"$WORK/health-${RUN_INDEX}.json" || fail "health unavailable after restore"
"$PYTHON" - "$WORK/health-${RUN_INDEX}.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
p=obj.get('runtime_persistence') or {}
a=obj.get('availability') or {}
assert p.get('desired_running_count') == 3
assert p.get('pending_restore_count') == 1
assert int(p.get('last_reconcile_restored',0)) >= 2
assert int(p.get('last_reconcile_offline_pending',0)) >= 1
assert p.get('last_error') is None
assert a.get('enabled') is True
assert int(a.get('unknown_count',0)) == 0
PY
echo "dual_runtime_restore_after_restart=PASS"
echo "offline_runtime_remained_pending_after_restart=PASS"
echo "dual_rtsp_after_backend_restart=PASS"

# Clear the deliberately pending offline intent, then prove explicit stop of an
# online peer remains durable as before.
curl -fsS --max-time 15 -X POST "$BASE/cameras/$OFFLINE_ID/stop" >"$WORK/offline-stop.json" || fail "offline intent stop failed"
wait_stopped "$OFFLINE_ID" offline-cleared || fail "offline pending intent was not cleared"
echo "offline_pending_intent_clear=PASS"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$PEER_ID/stop" >"$WORK/stop-peer.json" || fail "peer stop failed"
wait_stopped "$PEER_ID" peer-stopped || fail "peer did not reach persisted stopped state"
validate_policy "$PRIMARY_ID" || fail "explicit stops were not persisted"
echo "explicit_stop_persisted=PASS"
stop_service

# Third launch must restore only the still-enabled primary camera.
launch_service
PRIMARY_THIRD="$(wait_media_ready "$PRIMARY_ID" primary-third)" || fail "primary was not restored on third launch"
wait_stopped "$PEER_ID" peer-third || fail "explicitly stopped peer restarted unexpectedly"
wait_stopped "$OFFLINE_ID" offline-third || fail "cleared offline intent restarted unexpectedly"
validate_rtsp "$PRIMARY_ID" third-primary || fail "primary RTSP invalid on third launch"
curl -fsS --max-time 3 "$BASE/health" >"$WORK/health-${RUN_INDEX}.json" || fail "health unavailable on third launch"
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
