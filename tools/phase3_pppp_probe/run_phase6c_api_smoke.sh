#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$HOME/Documents/yi-cam-integration/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$HOME/Documents/yi-cam-integration/.env.local}"
PORT="${YI_PHASE6C_SMOKE_PORT:-18099}"
BASE="http://127.0.0.1:${PORT}/api/v1"
WORK="$(mktemp -d)"
PID=""

cleanup() {
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill -TERM "$PID" 2>/dev/null || true
    for _ in $(seq 1 20); do
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
  exit 1
}

[[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
[[ -f "$ENV_FILE" ]] || fail "env file missing: $ENV_FILE"
command -v curl >/dev/null || fail "curl is required for the smoke test"

"$PYTHON" -m py_compile \
  "$ROOT/yi_addon_backend.py" \
  "$ROOT/yi_addon_service.py" \
  "$ROOT/yi_camera_manager.py" \
  "$ROOT/yi_capability_cache.py"
echo "python_compile=PASS"

"$PYTHON" "$ROOT/yi_addon_service.py" \
  --env-file "$ENV_FILE" \
  --bind 127.0.0.1 \
  --port "$PORT" \
  >"$WORK/service.log" 2>&1 &
PID=$!

echo "phase6c_service_pid=$PID"
echo "phase6c_api_base=$BASE"

ready=0
for second in $(seq 1 40); do
  if curl -fsS --max-time 2 "$BASE/health" >"$WORK/health.json" 2>/dev/null; then
    ready=1
    break
  fi
  kill -0 "$PID" 2>/dev/null || fail "service exited before health endpoint became ready"
  sleep 1
done
[[ "$ready" == 1 ]] || fail "health endpoint did not become ready"
echo "health_http=PASS"

curl -fsS --max-time 5 "$BASE/cameras" >"$WORK/cameras.json"
curl -fsS --max-time 20 -X POST "$BASE/discover" >"$WORK/discover.json"
curl -fsS --max-time 5 "$BASE/cameras" >"$WORK/cameras_after.json"

"$PYTHON" - "$WORK/health.json" "$WORK/cameras.json" "$WORK/discover.json" "$WORK/cameras_after.json" <<'PY'
import json
import sys
from pathlib import Path

health, cameras, discover, cameras_after = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:]]

for name, payload in (
    ("health", health),
    ("cameras", cameras),
    ("discover", discover),
    ("cameras_after", cameras_after),
):
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise SystemExit(f"{name} payload is not ok")

if health.get("service") != "yi-home-addon" or health.get("api_version") != "v1":
    raise SystemExit("health service/api identity mismatch")

items = cameras_after.get("cameras")
if not isinstance(items, list) or not items:
    raise SystemExit("camera inventory is empty")
if cameras_after.get("camera_count") != len(items):
    raise SystemExit("camera_count does not match inventory")
if discover.get("camera_count") != len(items):
    raise SystemExit("discover camera_count does not match inventory")

proven = [item for item in items if isinstance(item, dict) and item.get("capability_state") == "proven"]
if not proven:
    raise SystemExit("no proven cached capability is visible through the API")

forbidden = {
    "uid", "did", "password", "token", "token_secret", "license",
    "initstring", "device_key", "cloud_uid", "pppp_did", "server",
}

def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in forbidden:
                raise SystemExit(f"forbidden secret-bearing API field: {key}")
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)

walk(health)
walk(cameras)
walk(discover)
walk(cameras_after)

print(f"camera_count={len(items)}")
print(f"proven_capability_count={len(proven)}")
print("secret_field_scan=PASS")
print("discover_refresh=PASS")
PY

echo "graceful_shutdown=REQUESTED"
kill -TERM "$PID"
for _ in $(seq 1 30); do
  if ! kill -0 "$PID" 2>/dev/null; then
    PID=""
    echo "graceful_shutdown=PASS"
    echo "PHASE6C_API_SMOKE=PASS"
    exit 0
  fi
  sleep 0.1
done
fail "service did not stop after SIGTERM"
