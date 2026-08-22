#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$HOME/Documents/yi-cam-integration/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$HOME/Documents/yi-cam-integration/.env.local}"
STABLE_ID="${YI_PHASE6C_TEST_STABLE_ID:-e2f22804fecdbd8c3561}"
PORT="${YI_PHASE6C_REPROBE_PORT:-18101}"
BASE="http://127.0.0.1:${PORT}/api/v1"
WORK="$(mktemp -d)"
STATE_DIR="$WORK/runtime"
CACHE_FILE="$WORK/capabilities.json"
PROBE_LOG="$STATE_DIR/probes/$STABLE_ID-last.log"
PID=""

cleanup() {
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID" 2>/dev/null || true
    for _ in $(seq 1 60); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "$PID" 2>/dev/null || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

fail() {
  echo "ERROR: $*" >&2
  if [[ -f "$WORK/reprobe.json" ]]; then
    echo "--- reprobe response ---" >&2
    cat "$WORK/reprobe.json" >&2 || true
    echo >&2
  fi
  if [[ -f "$PROBE_LOG" ]]; then
    echo "--- reprobe log ---" >&2
    cat "$PROBE_LOG" >&2 || true
  fi
  if [[ -f "$WORK/service.log" ]]; then
    echo "--- service log ---" >&2
    cat "$WORK/service.log" >&2 || true
  fi
  if [[ -f "$STATE_DIR/$STABLE_ID.log" ]]; then
    echo "--- camera runtime log (tail) ---" >&2
    tail -n 100 "$STATE_DIR/$STABLE_ID.log" >&2 || true
  fi
  exit 1
}

[[ "$STABLE_ID" =~ ^[0-9a-f]{20}$ ]] || fail "invalid test stable_id"
[[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
[[ -f "$ENV_FILE" ]] || fail "env file missing: $ENV_FILE"
command -v curl >/dev/null || fail "curl is required"
command -v pgrep >/dev/null || fail "pgrep is required"

"$PYTHON" -m py_compile \
  "$ROOT/yi_capability_probe_runtime.py" \
  "$ROOT/yi_addon_backend.py" \
  "$ROOT/yi_addon_service.py" \
  "$ROOT/yi_runtime_lifecycle.py" \
  "$ROOT/yi_capability_cache.py"
echo "python_compile=PASS"

echo "test_stable_id=$STABLE_ID"
echo "production_modified=false"
echo "isolated_capability_cache=true"

# A previous interrupted development probe must not occupy this non-production
# test camera. Refuse to hide the condition; terminate only matching stable-id
# relay process groups from this project before starting the isolated smoke run.
STALE_PIDS="$(pgrep -f "$ROOT/yi_native_av_relay_stable.py.*--stable-id $STABLE_ID" || true)"
if [[ -n "$STALE_PIDS" ]]; then
  echo "stale_test_runtime_detected=true"
  for stale_pid in $STALE_PIDS; do
    pgid="$(ps -o pgid= -p "$stale_pid" 2>/dev/null | tr -d ' ' || true)"
    if [[ -n "$pgid" ]]; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
    else
      kill -TERM "$stale_pid" 2>/dev/null || true
    fi
  done
  sleep 2
  if pgrep -f "$ROOT/yi_native_av_relay_stable.py.*--stable-id $STABLE_ID" >/dev/null 2>&1; then
    fail "stale test camera runtime could not be cleared"
  fi
  echo "stale_test_runtime_cleanup=PASS"
else
  echo "stale_test_runtime_detected=false"
fi

YI_CAPABILITY_CACHE="$CACHE_FILE" \
"$PYTHON" "$ROOT/yi_addon_service.py" \
  --env-file "$ENV_FILE" \
  --bind 127.0.0.1 \
  --port "$PORT" \
  --runtime-state-dir "$STATE_DIR" \
  --restart-delay 0.5 \
  --max-restart-delay 4 \
  --probe-duration 8 \
  >"$WORK/service.log" 2>&1 &
PID=$!

echo "phase6c_service_pid=$PID"
echo "phase6c_api_base=$BASE"

ready=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "$BASE/health" >"$WORK/health.json" 2>/dev/null; then
    ready=1
    break
  fi
  kill -0 "$PID" 2>/dev/null || fail "service exited before health became ready"
  sleep 0.5
done
[[ "$ready" == 1 ]] || fail "health endpoint did not become ready"

"$PYTHON" - "$WORK/health.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
assert obj.get('ok') is True
assert obj.get('runtime_lifecycle_ready') is True
assert obj.get('reprobe_ready') is True
print('reprobe_health=PASS')
PY

curl -fsS --max-time 10 -X POST "$BASE/cameras/$STABLE_ID/start" >"$WORK/start.json"
echo "start_http=PASS"

FIRST_PID=""
for _ in $(seq 1 80); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-running.json" || true
  FIRST_PID="$($PYTHON - "$WORK/status-running.json" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    r=obj.get('status',{}).get('runtime') or {}
    if r.get('runtime_state')=='running' and r.get('process_alive') is True and isinstance(r.get('pid'),int):
        print(r['pid'])
except Exception:
    pass
PY
)"
  [[ -n "$FIRST_PID" ]] && break
  sleep 0.5
done
[[ -n "$FIRST_PID" ]] || fail "camera runtime never reached running before reprobe"
echo "runtime_before_reprobe=PASS"
echo "runtime_pid_before=$FIRST_PID"

MEDIA_READY=0
for _ in $(seq 1 80); do
  if [[ -f "$STATE_DIR/$STABLE_ID.log" ]] && \
     grep -q 'phase3g_media_readers=STARTED' "$STATE_DIR/$STABLE_ID.log" && \
     grep -q 'mpegts_mux=STARTED' "$STATE_DIR/$STABLE_ID.log"; then
    MEDIA_READY=1
    break
  fi
  sleep 0.5
done
[[ "$MEDIA_READY" == 1 ]] || fail "initial camera runtime never reached native media"
INITIAL_MEDIA_COUNT="$(grep -c 'phase3g_media_readers=STARTED' "$STATE_DIR/$STABLE_ID.log" || true)"
echo "runtime_media_before_reprobe=PASS"

# Give the established session a short steady-state window, then let the API
# own stop -> handoff -> bounded probe -> resume.
sleep 2
set +e
HTTP_CODE="$(curl -sS --max-time 75 \
  -o "$WORK/reprobe.json" \
  -w '%{http_code}' \
  -X POST "$BASE/cameras/$STABLE_ID/reprobe")"
CURL_RC=$?
set -e
if (( CURL_RC != 0 )); then
  echo "reprobe_curl_rc=$CURL_RC" >&2
  echo "reprobe_http_code=${HTTP_CODE:-none}" >&2
  fail "HTTP reprobe request did not complete within its bounded client window"
fi
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "reprobe_http_code=$HTTP_CODE" >&2
  fail "HTTP reprobe returned a non-success response"
fi

"$PYTHON" - "$WORK/reprobe.json" "$STABLE_ID" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
stable=sys.argv[2]
assert obj.get('ok') is True
assert obj.get('operation') == 'reprobe'
assert obj.get('runtime_was_running') is True
assert obj.get('runtime_resumed') is True
probe=obj.get('probe') or {}
assert probe.get('stable_id') == stable
assert int(probe.get('attempts_used',0)) >= 1
cap=probe.get('capability') or {}
assert cap.get('status') == 'success'
assert cap.get('source') == 'addon_api_reprobe'
assert cap.get('video_codec') == 'h264'
assert int(cap.get('video_width',0)) > 0
assert int(cap.get('video_height',0)) > 0
assert cap.get('audio_codec') == 'aac'
assert int(cap.get('audio_sample_rate',0)) > 0
assert int(cap.get('audio_channels',0)) > 0
assert obj.get('secrets_exposed') is False
print('reprobe_http=PASS')
print('capability_cache_refresh=PASS')
print('reprobe_media_validation=PASS')
print('reprobe_attempts_used=' + str(probe.get('attempts_used')))
print('observed_at=' + str(cap.get('observed_at')))
PY

[[ -s "$CACHE_FILE" ]] || fail "isolated capability cache was not written"
"$PYTHON" "$ROOT/yi_capability_cache.py" --cache "$CACHE_FILE" show --stable-id "$STABLE_ID" >"$WORK/cache.json"
"$PYTHON" - "$WORK/cache.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
assert obj.get('ok') is True and obj.get('found') is True
r=obj.get('record') or {}
assert r.get('status') == 'success'
assert r.get('source') == 'addon_api_reprobe'
assert obj.get('secrets_exposed') is False
print('isolated_cache_readback=PASS')
PY

SECOND_PID=""
for _ in $(seq 1 100); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-resumed.json" || true
  SECOND_PID="$($PYTHON - "$WORK/status-resumed.json" "$FIRST_PID" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    old=int(sys.argv[2])
    status=obj.get('status') or {}
    runtime=status.get('runtime') or {}
    pid=runtime.get('pid')
    if runtime.get('runtime_state')=='running' and runtime.get('process_alive') is True and isinstance(pid,int) and pid != old:
        print(pid)
except Exception:
    pass
PY
)"
  [[ -n "$SECOND_PID" ]] && break
  sleep 0.5
done
[[ -n "$SECOND_PID" ]] || fail "camera runtime did not resume with a new PID after reprobe"
echo "runtime_resume_after_reprobe=PASS"
echo "runtime_pid_after=$SECOND_PID"

RESUMED_MEDIA=0
for _ in $(seq 1 80); do
  current_count="$(grep -c 'phase3g_media_readers=STARTED' "$STATE_DIR/$STABLE_ID.log" 2>/dev/null || true)"
  if [[ "$current_count" =~ ^[0-9]+$ ]] && (( current_count > INITIAL_MEDIA_COUNT )); then
    RESUMED_MEDIA=1
    break
  fi
  sleep 0.5
done
[[ "$RESUMED_MEDIA" == 1 ]] || fail "resumed runtime did not reach native media after reprobe"
echo "runtime_media_resume_after_reprobe=PASS"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$STABLE_ID/stop" >"$WORK/stop.json"
STOPPED=0
for _ in $(seq 1 60); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-stopped.json" || true
  if "$PYTHON" - "$WORK/status-stopped.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
r=obj.get('status',{}).get('runtime') or {}
raise SystemExit(0 if r.get('runtime_state')=='stopped' and r.get('process_alive') is False else 1)
PY
  then
    STOPPED=1
    break
  fi
  sleep 0.5
done
[[ "$STOPPED" == 1 ]] || fail "camera runtime did not stop after reprobe test"
echo "runtime_stop=PASS"

kill -TERM "$PID"
for _ in $(seq 1 60); do
  if ! kill -0 "$PID" 2>/dev/null; then
    PID=""
    break
  fi
  sleep 0.1
done
[[ -z "$PID" ]] || fail "service did not stop after SIGTERM"

if pgrep -f "$ROOT/yi_native_av_relay_stable.py.*--stable-id $STABLE_ID" >/dev/null 2>&1; then
  fail "test camera relay remained after service shutdown"
fi

echo "graceful_shutdown=PASS"
echo "probe_runtime_cleanup=PASS"
echo "PHASE6C_REPROBE_SMOKE=PASS"
