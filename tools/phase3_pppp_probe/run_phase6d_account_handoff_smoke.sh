#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
APP_DIR="$ROOT/yi_home"
STAGED_APP="$APP_DIR/rootfs/opt/yi-home/app"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

"$PYTHON" -m py_compile \
  "$ROOT/yi_account_credentials.py" \
  "$ROOT/yi_addon_service.py" \
  "$ROOT/tests/test_yi_account_credentials.py"
echo "account_handoff_python_compile=PASS"

PYTHONPATH="$ROOT" "$PYTHON" -m unittest discover \
  -s "$ROOT/tests" -p 'test_yi_account_credentials.py'
echo "account_handoff_unit_tests=PASS"

if ! grep -q 'ACCOUNT_PATH = "/api/v1/account"' "$ROOT/yi_addon_service.py"; then
  fail "account API endpoint is missing"
fi
if ! grep -q 'self._authorized()' "$ROOT/yi_addon_service.py"; then
  fail "account API is not behind the shared bearer preflight"
fi
if ! grep -q 'MAX_JSON_BODY' "$ROOT/yi_addon_service.py"; then
  fail "account request body is not bounded"
fi
echo "account_handoff_authenticated_api=PASS"

if ! grep -q 'os.fchmod(fd, 0o600)' "$ROOT/yi_account_credentials.py" || \
   ! grep -q 'os.replace(tmp, self.path)' "$ROOT/yi_account_credentials.py"; then
  fail "credential persistence is not atomic mode-0600"
fi
if grep -Eq 'YI_(TOKEN|TOKEN_SECRET|UID|DID|INITSTRING|LICENSE)' "$ROOT/yi_account_credentials.py"; then
  fail "forbidden YI session/camera material is configured for persistence"
fi
echo "account_handoff_secret_persistence=PASS"

"$PYTHON" "$ROOT/tools/prepare_ha_app_context.py" >/tmp/yi-phase6d-account-context.log
cat /tmp/yi-phase6d-account-context.log
[[ -f "$STAGED_APP/yi_account_credentials.py" ]] || fail "credential module was not staged into the App"
"$PYTHON" -m py_compile "$STAGED_APP/yi_account_credentials.py" "$STAGED_APP/yi_addon_service.py"
echo "account_handoff_app_packaging=PASS"

if find "$APP_DIR/rootfs" -type f \( -name 'yi.env' -o -name 'backend-api-token' \) -print -quit | grep -q .; then
  fail "runtime credential/state file leaked into App image context"
fi
echo "account_handoff_build_context_secret_scan=PASS"

echo "production_modified=false"
echo "PHASE6D_ACCOUNT_HANDOFF_SMOKE=PASS"
