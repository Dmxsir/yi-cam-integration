#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$HOME/Documents/yi-cam-integration/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$HOME/Documents/yi-cam-integration/.env.local}"
STABLE_ID="${YI_PHASE6C_TEST_STABLE_ID:-e2f22804fecdbd8c3561}"
PORT="${YI_PHASE6C_LIFECYCLE_PORT:-18100}"
BASE="http://127.0.0.1:${PORT}/api/v1"
WORK="$(mktemp -d)"
STATE_DIR="$WORK/runtime"
PID=""

cleanup() {
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID" 2>/dev/null || true
    for _ in $(seq 1 50); do
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
  if [[ -f "$WORK/service.log" ]]; then
    echo "--- service log ---" >&2
    cat "$WORK/service.log" >&2 || true
  fi
  if [[ -f "$STATE_DIR/$STABLE_ID.log" ]]; then
    echo "--- camera runtime log (tail) ---" >&2
    tail -n 80 "$STATE_DIR/$STABLE_ID.log" >&2 || true
  fi
  exit 1
}

[[ "$STABLE_ID" =~ ^[0-9a-f]{20}$ ]] || fail "invalid test stable_id"
[[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
[[ -f "$ENV_FILE" ]] || fail "env file missing: $ENV_FILE"
command -v curl >/dev/null || fail "curl is required"
command -v pgrep >/dev/null || fail "pgrep is required"

"$PYTHON" -m py_compile \
  "$ROOT/yi_runtime_lifecycle.py" \
  "$ROOT/yi_addon_backend.py" \
  "$ROOT/yi_addon_service.py" \
  "$ROOT/yi_native_session_supervisor.py" \
  "$ROOT/yi_native_av_relay_stable.py"
echo "python_compile=PASS"

echo "test_stable_id=$STABLE_ID"
echo "production_modified=false"

"$PYTHON" "$ROOT/yi_addon_service.py" \
  --env-file "$ENV_FILE" \
  --bind 127.0.0.1 \
  --port "$PORT" \
  --runtime-state-dir "$STATE_DIR" \
  --restart-delay 0.5 \
  --max-restart-delay 4 \
  >"$WORK/service.log" 2>&1 &
PID=$!

echo "phase6c_service_pid=$PID"
echo "phase6c_api_base=$BASE"

ready=0
for _ in $(seq 1 50); do
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
print('lifecycle_health=PASS')
PY

curl -fsS --max-time 5 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-before.json" 
"$PYTHON" - "$WORK/status-before.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
assert obj['status']['runtime_state'] == 'stopped'
print('initial_runtime_state=stopped')
PY

curl -fsS --max-time 10 -X POST "$BASE/cameras/$STABLE_ID/start" >"$WORK/start.json"
echo "start_http=PASS"

FIRST_PID=""
for _ in $(seq 1 60); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-running.json" || true
  FIRST_PID="$($PYTHON - "$WORK/status-running.json" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    runtime=obj.get('status',{}).get('runtime') or {}
    if runtime.get('runtime_state') == 'running' and runtime.get('process_alive') is True and isinstance(runtime.get('pid'), int):
        print(runtime['pid'])
except Exception:
    pass
PY
)"
  [[ -n "$FIRST_PID" ]] && break
  sleep 0.5
done
[[ -n "$FIRST_PID" ]] || fail "camera runtime never reached running"
echo "runtime_running=PASS"
echo "runtime_pid_initial=$FIRST_PID"

MEDIA_READY=0
for _ in $(seq 1 60); do
  if [[ -f "$STATE_DIR/$STABLE_ID.log" ]] && \
     grep -q 'phase3g_media_readers=STARTED' "$STATE_DIR/$STABLE_ID.log" && \
     grep -q 'mpegts_mux=STARTED' "$STATE_DIR/$STABLE_ID.log"; then
    MEDIA_READY=1
    break
  fi
  sleep 0.5
done
[[ "$MEDIA_READY" == 1 ]] || fail "native runtime did not prove media readers/mux startup"
echo "native_media_runtime=PASS"

sleep 2
curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-stable.json"
STABLE_PID="$($PYTHON - "$WORK/status-stable.json" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
r=obj['status']['runtime']
assert r['runtime_state']=='running' and r['process_alive'] is True
print(r['pid'])
PY
)"
[[ "$STABLE_PID" == "$FIRST_PID" ]] || fail "runtime restarted unexpectedly before manual restart"
echo "runtime_stability=PASS"

if ! pgrep -af "yi_native_av_relay_stable.py.*--stable-id $STABLE_ID" >"$WORK/relay-process.txt"; then
  fail "stable-id relay child process not found"
fi
echo "stable_relay_process=PASS"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$STABLE_ID/restart" >"$WORK/restart.json"
echo "restart_http=PASS"

SECOND_PID=""
for _ in $(seq 1 80); do
  curl -fsS --max-time 3 "$BASE/cameras/$STABLE_ID/status" >"$WORK/status-restarted.json" || true
  SECOND_PID="$($PYTHON - "$WORK/status-restarted.json" "$FIRST_PID" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    old=int(sys.argv[2])
    r=obj.get('status',{}).get('runtime') or {}
    pid=r.get('pid')
    if r.get('runtime_state')=='running' and r.get('process_alive') is True and isinstance(pid,int) and pid != old:
        print(pid)
except Exception:
    pass
PY
)"
  [[ -n "$SECOND_PID" ]] && break
  sleep 0.5
done
[[ -n "$SECOND_PID" ]] || fail "camera did not reach running with a new lifecycle PID after restart"
echo "runtime_restart=PASS"
echo "runtime_pid_restarted=$SECOND_PID"

curl -fsS --max-time 15 -X POST "$BASE/cameras/$STABLE_ID/stop" >"$WORK/stop.json"
echo "stop_http=PASS"

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
[[ "$STOPPED" == 1 ]] || fail "camera runtime did not stop cleanly"
echo "runtime_stop=PASS"

sleep 1
if pgrep -af "yi_native_av_relay_stable.py.*--stable-id $STABLE_ID" >/dev/null; then
  fail "stable relay process remained after stop"
fi
echo "relay_cleanup_after_stop=PASS"

echo "graceful_shutdown=REQUESTED"
kill -TERM "$PID"
for _ in $(seq 1 50); do
  if ! kill -0 "$PID" 2>/dev/null; then
    PID=""
    break
  fi
  sleep 0.1
done
[[ -z "$PID" ]] || fail "service did not stop after SIGTERM"

if pgrep -af "yi_native_av_relay_stable.py.*--stable-id $STABLE_ID" >/dev/null; then
  fail "camera relay remained after service shutdown"
fi

echo "graceful_shutdown=PASS"
echo "runtime_descendant_cleanup=PASS"
echo "PHASE6C_LIFECYCLE_SMOKE=PASS"
