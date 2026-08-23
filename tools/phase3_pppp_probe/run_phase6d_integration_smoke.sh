#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
COMPONENT="$ROOT/custom_components/yi_home"
DIST="$ROOT/dist"
BUNDLE="$DIST/yi_home-integration.tar.gz"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

for file in manifest.json __init__.py api.py config_flow.py const.py coordinator.py entity.py binary_sensor.py sensor.py switch.py strings.json translations/he.json; do
  [[ -f "$COMPONENT/$file" ]] || fail "missing integration artifact: $file"
done
printf 'integration_required_artifacts=PASS\n'

"$PYTHON" -m py_compile \
  "$COMPONENT/__init__.py" \
  "$COMPONENT/api.py" \
  "$COMPONENT/config_flow.py" \
  "$COMPONENT/const.py" \
  "$COMPONENT/coordinator.py" \
  "$COMPONENT/entity.py" \
  "$COMPONENT/binary_sensor.py" \
  "$COMPONENT/sensor.py" \
  "$COMPONENT/switch.py"
printf 'integration_python_compile=PASS\n'

"$PYTHON" - "$COMPONENT/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert manifest["domain"] == "yi_home"
assert manifest["config_flow"] is True
assert manifest["version"]
print("integration_manifest=PASS")
PY

grep -q 'async_step_hassio' "$COMPONENT/config_flow.py" || fail "async_step_hassio is missing"
grep -q 'HassioServiceInfo' "$COMPONENT/config_flow.py" || fail "HassioServiceInfo is missing"
grep -q 'return self.async_abort(reason="app_required")' "$COMPONENT/config_flow.py" || fail "manual user flow must not bypass App discovery"
printf 'integration_hassio_discovery_flow=PASS\n'

grep -q 'Platform.BINARY_SENSOR' "$COMPONENT/__init__.py" || fail "binary_sensor platform missing"
grep -q 'Platform.SENSOR' "$COMPONENT/__init__.py" || fail "sensor platform missing"
grep -q 'Platform.SWITCH' "$COMPONENT/__init__.py" || fail "switch platform missing"
grep -q 'availability_state' "$COMPONENT/binary_sensor.py" || fail "authoritative availability entity missing"
grep -q 'persisted_desired_running' "$COMPONENT/switch.py" || fail "stream switch is not tied to persisted desired state"
printf 'integration_camera_entities=PASS\n'

if grep -RIlE 'YI_PASSWORD=|token_secret=|backend-api-token|\.env\.local' "$COMPONENT" >/dev/null; then
  fail "secret/state material leaked into integration package"
fi
printf 'integration_secret_state_scan=PASS\n'

mkdir -p "$DIST"
rm -f "$BUNDLE" "$BUNDLE.sha256"
tar -czf "$BUNDLE" -C "$ROOT" custom_components/yi_home
sha256sum "$BUNDLE" >"$BUNDLE.sha256"
printf 'integration_bundle=%s\n' "$BUNDLE"
printf 'integration_bundle_bytes=%s\n' "$(stat -c %s "$BUNDLE")"
printf 'production_modified=false\n'
printf 'PHASE6D_INTEGRATION_SMOKE=PASS\n'
