#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
APP_DIR="$ROOT/yi_home"
DIST_DIR="$ROOT/dist"
BUNDLE="$DIST_DIR/yi_home-local-amd64.tar.gz"
SHA_FILE="$BUNDLE.sha256"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v tar >/dev/null 2>&1 || fail "tar is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"
[[ -x "$PYTHON" ]] || command -v "$PYTHON" >/dev/null 2>&1 || fail "python is unavailable: $PYTHON"

"$PYTHON" -m py_compile "$ROOT/tools/prepare_ha_app_context.py"
"$PYTHON" "$ROOT/tools/prepare_ha_app_context.py"
echo "app_context_prepare=PASS"

for file in \
  "$APP_DIR/config.yaml" \
  "$APP_DIR/Dockerfile" \
  "$APP_DIR/run.sh" \
  "$APP_DIR/apparmor.txt" \
  "$APP_DIR/rootfs/opt/yi-home/app/yi_addon_service.py" \
  "$APP_DIR/rootfs/opt/yi-home/runtime/bionic-root/system/bin/linker64" \
  "$APP_DIR/rootfs/opt/yi-home/runtime/bionic-root/data/local/tmp/yi-online-status/android_pppp_online_probe" \
  "$APP_DIR/rootfs/opt/yi-home/runtime/bionic-root/data/local/tmp/yi-online-status/libPPPP_API.so"; do
  [[ -e "$file" ]] || fail "required Local App artifact missing: $file"
done
echo "local_app_required_artifacts=PASS"

if grep -Eq '^image:' "$APP_DIR/config.yaml"; then
  fail "local App config must not set image: Supervisor must build the local Dockerfile"
fi
echo "local_supervisor_build_mode=PASS"

LEAKED="$(find "$APP_DIR/rootfs" -type f \( \
    -name '.env' -o \
    -name '.env.local' -o \
    -name 'options.json' -o \
    -name 'backend-api-token' -o \
    -name 'runtime-policy.json' -o \
    -name 'capabilities.json' -o \
    -name 'yi.env' \
  \) -print -quit)"
[[ -z "$LEAKED" ]] || fail "credential/state file present in Local App rootfs: $LEAKED"
echo "local_app_secret_state_scan=PASS"

# Reject actual development-host paths everywhere in the package. A few engine
# modules intentionally retain a repo-relative .analysis fallback for legacy
# development callers, but the packaged App must never select that fallback.
if grep -REn '(~/Documents|/home/[^/]+/Documents)' \
    "$APP_DIR/Dockerfile" "$APP_DIR/run.sh" "$APP_DIR/rootfs/opt/yi-home/app" >/dev/null; then
  fail "absolute development-machine path leaked into Local App package"
fi

# Runtime startup configuration itself must be fully package-native. This is
# stronger than scanning library source text: it proves the HA App entrypoint
# selects the staged /opt/yi-home runtime and worker directories explicitly.
if grep -En '(~/Documents|/home/[^/]+/Documents|\.analysis)' \
    "$APP_DIR/Dockerfile" "$APP_DIR/run.sh" >/dev/null; then
  fail "App startup configuration contains a development runtime path"
fi
if ! grep -Fq 'RUNTIME_ROOT="/opt/yi-home/runtime/bionic-root"' "$APP_DIR/run.sh"; then
  fail "run.sh does not select the packaged Bionic runtime root"
fi
if ! grep -Fq -- '--runtime-root "${RUNTIME_ROOT}"' "$APP_DIR/run.sh"; then
  fail "run.sh does not pass the packaged runtime root to the backend"
fi
if ! grep -Fq -- '--worker-dir "${RUNTIME_ROOT}/data/local/tmp/yi-phase3g"' "$APP_DIR/run.sh"; then
  fail "run.sh does not pass the packaged Phase 3G worker directory"
fi
echo "local_app_development_paths_removed=PASS"
echo "local_app_runtime_wiring=PASS"

mkdir -p "$DIST_DIR"
rm -f "$BUNDLE" "$SHA_FILE"

# Keep the top-level yi_home directory in the archive. Extracting the archive
# directly under /addons therefore produces /addons/yi_home/config.yaml.
tar \
  --exclude='yi_home/.gitignore' \
  --exclude='yi_home/rootfs/.gitkeep' \
  -C "$ROOT" \
  -czf "$BUNDLE" \
  yi_home

[[ -s "$BUNDLE" ]] || fail "Local App bundle was not created"
sha256sum "$BUNDLE" >"$SHA_FILE"

if tar -tzf "$BUNDLE" | grep -Eq '(^|/)(\.env|\.env\.local|options\.json|backend-api-token|runtime-policy\.json|capabilities\.json|yi\.env)$'; then
  fail "forbidden credential/state filename exists in Local App archive"
fi

echo "local_app_bundle=$BUNDLE"
echo "local_app_bundle_sha256_file=$SHA_FILE"
echo "local_app_bundle_bytes=$(stat -c %s "$BUNDLE")"
echo "local_app_bundle_secret_scan=PASS"
echo "production_modified=false"
echo "PHASE6D_LOCAL_APP_BUNDLE=PASS"
