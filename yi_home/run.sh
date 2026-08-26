#!/usr/bin/with-contenv bashio
set -euo pipefail

APP_ROOT="/opt/yi-home/app"
RUNTIME_ROOT="/opt/yi-home/runtime/bionic-root"
API_PORT=8099
RTSP_PORT=8554
TOKEN_FILE="/data/backend-api-token"
ENV_FILE="/data/yi.env"
BACKEND_PID=""
DIAG_PID=""
BACKEND_STOP_TIMEOUT_SECONDS=20

mkdir -p /data
chmod 0700 /data 2>/dev/null || true

TOKEN_STATE="reused"
if [[ ! -s "${TOKEN_FILE}" ]]; then
  TOKEN_STATE="created"
  umask 077
  python3 - <<'PY' >"${TOKEN_FILE}"
import secrets
print(secrets.token_urlsafe(48))
PY
fi
chmod 0600 "${TOKEN_FILE}"
TOKEN_MODE="$(python3 - "${TOKEN_FILE}" <<'PY'
import os
import stat
import sys

print(f"{stat.S_IMODE(os.stat(sys.argv[1]).st_mode):03o}")
PY
)"
if [[ "${TOKEN_MODE}" != "600" ]]; then
  bashio::exit.nok "Backend API token permissions are not restrictive."
fi
bashio::log.info "Backend API token ${TOKEN_STATE}; mode=${TOKEN_MODE}; value_exposed=false."
API_TOKEN="$(cat "${TOKEN_FILE}")"

# Phase 6D.2 will populate this file through the authenticated internal API.
# Keeping an empty restrictive file lets the App/API boot before account setup.
if [[ ! -e "${ENV_FILE}" ]]; then
  umask 077
  : >"${ENV_FILE}"
fi
chmod 0600 "${ENV_FILE}"

export YI_ADDON_API_TOKEN="${API_TOKEN}"
export PYTHONUNBUFFERED=1

terminate_backend() {
  local pid="${BACKEND_PID}"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return
  fi

  bashio::log.info "Stopping YI Home backend gracefully..."
  kill -TERM "${pid}" 2>/dev/null || true

  # Never let an App stop/restart block indefinitely on the backend. The
  # backend normally shuts down in a few seconds; this bounded grace period
  # still gives camera runtimes and go2rtc time to terminate cleanly.
  local ticks=$((BACKEND_STOP_TIMEOUT_SECONDS * 2))
  for _ in $(seq 1 "${ticks}"); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      wait "${pid}" 2>/dev/null || true
      bashio::log.info "YI Home backend stopped cleanly."
      return
    fi
    sleep 0.5
  done

  bashio::log.warning "YI Home backend exceeded the shutdown grace period; forcing termination."
  kill -KILL "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}

terminate_diagnostics() {
  local pid="${DIAG_PID}"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" 2>/dev/null; then
    return
  fi
  kill -TERM "${pid}" 2>/dev/null || true
  wait "${pid}" 2>/dev/null || true
}

cleanup() {
  terminate_backend
  terminate_diagnostics
}
trap cleanup TERM INT EXIT

# Per-camera runtimes intentionally keep their full stderr inside /data/runtime.
# Mirror only fixed, secret-safe diagnostic lines to stdout so
# `ha apps logs local_yi_home` can diagnose restart loops without exposing raw
# relay output, command lines, credentials, UID/DID values or API tokens.
python3 -u - <<'PY' &
from pathlib import Path
import time

root = Path("/data/runtime")
positions: dict[Path, int] = {}
safe_worker_prefixes = (
    "[phase3g-worker] PPPP_Initialize_rc_hex=",
    "[phase3g-worker] PPPP_Connect_rc_hex=",
    "[phase3g-worker] PPPP_Write_4881_rc_hex=",
    "[phase3g-worker] PPPP_Write_9029_rc_hex=",
    "[phase3g-worker] PPPP_Write_768_rc_hex=",
    "[phase3g-worker] tnp_response_version=",
    "[phase3g-worker] tnp_response_command=",
    "[phase3g-worker] tnp_response_command_number=",
    "[phase3g-worker] tnp_auth_result=",
    "[phase3g-worker] phase3g_tnp_auth=PASS",
    "[phase3g-worker] phase3g_media_readers=STARTED",
    "[phase3g-worker] channel1_records=",
    "[phase3g-worker] channel2_records=",
    "[phase3g-worker] channel3_records=",
)
safe_relay_prefixes = (
    "[phase3g-relay] native_worker_exit=",
    "[phase3g-relay] initial_av_delta_ms=",
    "[phase3g-relay] mpegts_mux=STARTED",
    "[phase3g-relay] mpegts_stdout_first_chunk_bytes=",
    "[phase3g-relay] mpegts_stdout_pumped_bytes=",
)

# Existing files may contain historical runtime material. Start at their current
# EOF so only diagnostics produced by this App run are surfaced.
if root.is_dir():
    for path in root.glob("*.log"):
        try:
            positions[path] = path.stat().st_size
        except OSError:
            pass

while True:
    try:
        root.mkdir(parents=True, exist_ok=True)
        for path in root.glob("*.log"):
            try:
                size = path.stat().st_size
                offset = positions.get(path, 0)
                if size < offset:
                    offset = 0
                if size == offset:
                    positions[path] = offset
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(offset)
                    for raw in handle:
                        line = raw.rstrip("\r\n")
                        if (
                            line.startswith("[yi-session-supervisor]")
                            or line.startswith(safe_relay_prefixes)
                            or line.startswith(safe_worker_prefixes)
                        ):
                            print(
                                f"[yi-runtime-diagnostic] camera={path.stem[:12]} {line}",
                                flush=True,
                            )
                    positions[path] = handle.tell()
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    time.sleep(1.0)
PY
DIAG_PID=$!

bashio::log.info "Starting YI Home backend..."
cd "${APP_ROOT}"
python3 yi_addon_service.py \
  --env-file "${ENV_FILE}" \
  --bind 0.0.0.0 \
  --port "${API_PORT}" \
  --data-dir /data \
  --runtime-root "${RUNTIME_ROOT}" \
  --worker-dir "${RUNTIME_ROOT}/data/local/tmp/yi-phase3g" \
  --go2rtc-bin /usr/local/bin/go2rtc \
  --go2rtc-state-dir /data/publisher \
  --go2rtc-api-port 1984 \
  --go2rtc-rtsp-port "${RTSP_PORT}" \
  --go2rtc-rtsp-bind 0.0.0.0 \
  --discovery-retry-interval 30 &
BACKEND_PID=$!

ready=false
for _ in $(seq 1 120); do
  if curl -fsS --max-time 2 \
      -H "Authorization: Bearer ${API_TOKEN}" \
      "http://127.0.0.1:${API_PORT}/api/v1/health" >/dev/null 2>&1; then
    ready=true
    break
  fi
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    wait "${BACKEND_PID}" || true
    bashio::exit.nok "YI Home backend exited before its health API became ready."
  fi
  sleep 0.5
done

if [[ "${ready}" != true ]]; then
  terminate_backend
  bashio::exit.nok "YI Home backend health API did not become ready."
fi

# Supervisor discovery carries only the App-internal API credential and
# connection metadata. YI account/camera credentials are never included.
bashio::log.info "Publishing YI Home discovery endpoint host=local-yi-home port=${API_PORT}; credentials_exposed=false."
ha_config="$(
  bashio::var.json \
    host "local-yi-home" \
    port "^${API_PORT}" \
    api_version "v1" \
    api_token "${API_TOKEN}" \
    rtsp_port "^${RTSP_PORT}"
)"
if bashio::discovery "yi_home" "${ha_config}" >/dev/null; then
  bashio::log.info "Published YI Home discovery information to Home Assistant."
else
  bashio::log.warning "Could not publish YI Home discovery information yet; the backend remains available."
fi

bashio::log.info "YI Home backend is ready."
set +e
wait "${BACKEND_PID}"
rc=$?
set -e
BACKEND_PID=""
exit "${rc}"
