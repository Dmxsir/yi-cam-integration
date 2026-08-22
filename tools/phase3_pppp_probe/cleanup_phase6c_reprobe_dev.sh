#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STABLE_ID="${YI_PHASE6C_TEST_STABLE_ID:-e2f22804fecdbd8c3561}"
PORT="${YI_PHASE6C_REPROBE_PORT:-18101}"
SERVICE_PATTERN="$ROOT/yi_addon_service.py.*--port $PORT"
CAMERA_PATTERN="$ROOT/yi_native_av_relay_stable.py.*--stable-id $STABLE_ID"

[[ "$STABLE_ID" =~ ^[0-9a-f]{20}$ ]] || { echo "invalid stable_id" >&2; exit 2; }
command -v pgrep >/dev/null || { echo "pgrep is required" >&2; exit 2; }
command -v ps >/dev/null || { echo "ps is required" >&2; exit 2; }

signal_pid() {
  local pid="$1"
  local sig="$2"
  kill "-$sig" "$pid" 2>/dev/null || true
}

signal_process_group() {
  local pid="$1"
  local sig="$2"
  local pgid
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [[ -n "$pgid" ]]; then
    kill "-$sig" -- "-$pgid" 2>/dev/null || true
  else
    signal_pid "$pid" "$sig"
  fi
}

wait_pattern_clear() {
  local pattern="$1"
  local loops="$2"
  for _ in $(seq 1 "$loops"); do
    if ! pgrep -f "$pattern" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

echo "phase6c_reprobe_cleanup=START"
echo "test_port=$PORT"
echo "test_stable_id=$STABLE_ID"
echo "production_modified=false"

# Stop an interrupted test API first. Otherwise it may recreate the camera
# runtime while the cleanup is trying to remove it.
SERVICE_PIDS="$(pgrep -f "$SERVICE_PATTERN" || true)"
if [[ -n "$SERVICE_PIDS" ]]; then
  echo "stale_test_service_detected=true"
  for pid in $SERVICE_PIDS; do
    echo "stale_test_service_pid=$pid"
    signal_pid "$pid" TERM
  done
  if ! wait_pattern_clear "$SERVICE_PATTERN" 80; then
    for pid in $(pgrep -f "$SERVICE_PATTERN" || true); do
      signal_pid "$pid" KILL
    done
    wait_pattern_clear "$SERVICE_PATTERN" 30 || {
      echo "ERROR: stale test API service could not be cleared" >&2
      pgrep -af "$SERVICE_PATTERN" >&2 || true
      exit 1
    }
  fi
  echo "stale_test_service_cleanup=PASS"
else
  echo "stale_test_service_detected=false"
fi

# Now remove only supervisor/relay process groups whose argv explicitly names
# the selected non-production stable_id. The production warehouse/pool stable
# IDs do not match this pattern and are not touched.
CAMERA_PIDS="$(pgrep -f "$CAMERA_PATTERN" || true)"
if [[ -n "$CAMERA_PIDS" ]]; then
  echo "stale_test_runtime_detected=true"
  for pid in $CAMERA_PIDS; do
    echo "stale_test_runtime_pid=$pid"
    signal_process_group "$pid" TERM
  done
  if ! wait_pattern_clear "$CAMERA_PATTERN" 50; then
    for pid in $(pgrep -f "$CAMERA_PATTERN" || true); do
      signal_process_group "$pid" KILL
    done
    wait_pattern_clear "$CAMERA_PATTERN" 30 || {
      echo "ERROR: stale test camera runtime could not be cleared" >&2
      pgrep -af "$CAMERA_PATTERN" >&2 || true
      exit 1
    }
  fi
  echo "stale_test_runtime_cleanup=PASS"
else
  echo "stale_test_runtime_detected=false"
fi

# A final diagnostic guard catches a service that somehow reappeared.
if pgrep -f "$SERVICE_PATTERN" >/dev/null 2>&1; then
  echo "ERROR: test service reappeared during cleanup" >&2
  pgrep -af "$SERVICE_PATTERN" >&2 || true
  exit 1
fi
if pgrep -f "$CAMERA_PATTERN" >/dev/null 2>&1; then
  echo "ERROR: test camera runtime reappeared during cleanup" >&2
  pgrep -af "$CAMERA_PATTERN" >&2 || true
  exit 1
fi

echo "phase6c_reprobe_cleanup=PASS"
