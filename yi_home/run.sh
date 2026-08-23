#!/usr/bin/with-contenv bashio
set -euo pipefail

APP_ROOT="/opt/yi-home/app"
RUNTIME_ROOT="/opt/yi-home/runtime/bionic-root"
API_PORT=8099
RTSP_PORT=8554
APP_DNS_HOST="local-yi-home"
TOKEN_FILE="/data/backend-api-token"
ENV_FILE="/data/yi.env"
BACKEND_PID=""

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

# Phase 6D.2 populates this file through the authenticated internal API.
# Keeping an empty restrictive file lets the App/API boot before account setup.
if [[ ! -e "${ENV_FILE}" ]]; then
  umask 077
  : >"${ENV_FILE}"
fi
chmod 0600 "${ENV_FILE}"

export YI_ADDON_API_TOKEN="${API_TOKEN}"
export PYTHONUNBUFFERED=1

terminate_backend() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill -TERM "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap terminate_backend TERM INT

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
# Use the stable Supervisor DNS hostname for a local App rather than the
# container's transient Docker hostname, which Home Assistant Core cannot
# reliably resolve.
ha_config="$(
  bashio::var.json \
    host "${APP_DNS_HOST}" \
    port "^${API_PORT}" \
    api_version "v1" \
    token "${API_TOKEN}" \
    rtsp_port "^${RTSP_PORT}"
)"
bashio::log.info "Publishing YI Home discovery endpoint host=${APP_DNS_HOST} port=${API_PORT}; credentials_exposed=false."
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
