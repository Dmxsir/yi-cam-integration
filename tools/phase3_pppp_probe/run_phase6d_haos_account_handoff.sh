#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
HA_HOST="${YI_HA_HOST:-10.0.0.16}"
ENV_FILE="${YI_ENV_FILE:-$ROOT/.env.local}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

if [[ ! -f "$ENV_FILE" ]]; then
  fallback="$HOME/Documents/yi-cam-integration/.env.local"
  if [[ -f "$fallback" ]]; then
    ENV_FILE="$fallback"
  else
    fail "YI env file not found. Set YI_ENV_FILE to the existing private .env.local used for live tests."
  fi
fi

command -v ssh >/dev/null || fail "ssh is required"
"$PYTHON" - "$ENV_FILE" <<'PY' | ssh -T "root@${HA_HOST}" 'set -eu
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required in Terminal & SSH" >&2; exit 1; }
: "${SUPERVISOR_TOKEN:?SUPERVISOR_TOKEN is unavailable in Terminal & SSH}"
DISCOVERY="$(curl -fsS -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" http://supervisor/discovery)"
APP_TOKEN="$(printf "%s" "$DISCOVERY" | jq -r '\''(.data.discovery // .discovery // []) | map(select(.addon == "local_yi_home" and .service == "yi_home")) | last | .config.token // empty'\'')"
unset DISCOVERY
[ -n "$APP_TOKEN" ] || { echo "ERROR: YI Home discovery token was not found" >&2; exit 1; }
BEFORE="$(curl -fsS -H "Authorization: Bearer ${APP_TOKEN}" http://local-yi-home:8099/api/v1/account)"
printf "account_status_before=%s\n" "$BEFORE"
unset BEFORE
curl -fsS \
  -H "Authorization: Bearer ${APP_TOKEN}" \
  -H "Content-Type: application/json" \
  --data-binary @- \
  http://local-yi-home:8099/api/v1/account
printf "\n"
unset APP_TOKEN
'
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent))
sys.path.insert(0, str(Path.cwd()))
from yi_tnp_oracle import load_env_file

load_env_file(Path(sys.argv[1]))
required = {
    "region": "YI_REGION",
    "country": "YI_COUNTRY",
    "account": "YI_ACCOUNT",
    "password": "YI_PASSWORD",
    "device_brand": "YI_DEVICE_BRAND",
    "device_model": "YI_DEVICE_MODEL",
    "android_version": "YI_ANDROID_VERSION",
    "language": "YI_LANGUAGE",
}
payload = {}
missing = []
for out_key, env_key in required.items():
    value = os.getenv(env_key)
    if not value:
        missing.append(env_key)
    else:
        payload[out_key] = value
if missing:
    raise SystemExit("Missing private env values: " + ", ".join(missing))
json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
PY

echo "PHASE6D_HAOS_ACCOUNT_HANDOFF_REQUEST=COMPLETE"
