#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
DOCKER_CMD="${DOCKER_CMD:-docker}"
APP_DIR="$ROOT/yi_home"
ROOTFS="$APP_DIR/rootfs"
RUNTIME="$ROOTFS/opt/yi-home/runtime/bionic-root"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

"$PYTHON" -m py_compile "$ROOT/tools/prepare_ha_app_context.py"
echo "python_compile=PASS"

"$PYTHON" "$ROOT/tools/prepare_ha_app_context.py"
echo "app_context_prepare=PASS"

for file in \
  "$ROOT/repository.yaml" \
  "$APP_DIR/config.yaml" \
  "$APP_DIR/Dockerfile" \
  "$APP_DIR/run.sh" \
  "$APP_DIR/apparmor.txt" \
  "$ROOTFS/opt/yi-home/app/yi_addon_service.py" \
  "$ROOTFS/opt/yi-home/app/yi_vendor_bootstrap.py" \
  "$RUNTIME/system/bin/linker64" \
  "$RUNTIME/data/local/tmp/yi-online-status/android_pppp_online_probe" \
  "$ROOTFS/opt/yi-home/runtime-manifest.json"; do
  [[ -e "$file" ]] || fail "required App artifact missing: $file"
done
echo "required_app_artifacts=PASS"

if find "$ROOTFS" -type f \( -name '.env' -o -name '.env.local' -o -name 'options.json' -o -name 'backend-api-token' \) -print -quit | grep -q .; then
  fail "secret/state file leaked into generated build context"
fi
echo "build_context_secret_scan=PASS"

if find "$APP_DIR" \( -iname 'libPPPP_API.so' -o -iname 'yi-home.apk' \) -print -quit | grep -q .; then
  fail "proprietary vendor artifact leaked into Docker build context"
fi
echo "build_context_vendor_artifact_scan=PASS"

if grep -REn '(~/Documents|/home/[^/]+/Documents|\.analysis/phase3)' \
    "$APP_DIR/Dockerfile" "$APP_DIR/run.sh" >/dev/null; then
  fail "App runtime still contains a development-machine path"
fi
echo "development_paths_removed=PASS"

if ! grep -q '^  - amd64$' "$APP_DIR/config.yaml"; then
  fail "amd64 is not the declared initial App architecture"
fi
if grep -Eq '^(host_network|full_access|docker_api):[[:space:]]*true' "$APP_DIR/config.yaml"; then
  fail "unsafe Home Assistant App privilege requested"
fi
if ! grep -q '^discovery:' "$APP_DIR/config.yaml" || ! grep -q '  - yi_home' "$APP_DIR/config.yaml"; then
  fail "Supervisor discovery service is not declared"
fi
if ! grep -q '^map:' "$APP_DIR/config.yaml" || ! grep -q '  - share:ro' "$APP_DIR/config.yaml"; then
  fail "read-only /share import mapping is not declared"
fi
echo "app_security_config=PASS"

if ! grep -q '^ARG FFMPEG_VERSION=6\.0\.1$' "$APP_DIR/Dockerfile"; then
  fail "proven FFmpeg 6.0.1 runtime is not pinned"
fi
if ! grep -q '^ARG FFMPEG_SHA256=28268bf402f1083833ea269331587f60a242848880073be8016501d864bd07a5$' "$APP_DIR/Dockerfile"; then
  fail "pinned FFmpeg archive checksum changed unexpectedly"
fi
if ! grep -Fq 'echo "${FFMPEG_SHA256}  /tmp/ffmpeg-static.tar.xz" | sha256sum -c -' "$APP_DIR/Dockerfile"; then
  fail "pinned FFmpeg archive is not checksum-verified"
fi
if grep -Eq '^[[:space:]]+ffmpeg[[:space:]]*\\$' "$APP_DIR/Dockerfile"; then
  fail "App Dockerfile still installs the unpinned Alpine ffmpeg package"
fi
if ! grep -q '/usr/local/bin/ffmpeg' "$APP_DIR/Dockerfile" \
    || ! grep -q '/usr/local/bin/ffprobe' "$APP_DIR/Dockerfile"; then
  fail "pinned FFmpeg binaries are not installed into the runtime PATH"
fi
echo "pinned_ffmpeg_runtime=PASS"

if ! grep -q 'bashio::discovery "yi_home"' "$APP_DIR/run.sh"; then
  fail "run.sh does not publish Supervisor discovery"
fi
if ! grep -q 'backend-api-token' "$APP_DIR/run.sh" || ! grep -q 'chmod 0600' "$APP_DIR/run.sh"; then
  fail "internal API token persistence is not restrictive"
fi
if ! grep -q 'TOKEN_STATE="reused"' "$APP_DIR/run.sh" \
    || ! grep -q 'TOKEN_STATE="created"' "$APP_DIR/run.sh" \
    || ! grep -q 'value_exposed=false' "$APP_DIR/run.sh"; then
  fail "secret-safe backend token create/reuse marker is missing"
fi
if ! grep -q -- '--data-dir /data' "$APP_DIR/run.sh"; then
  fail "backend persistence is not rooted under /data"
fi
if ! grep -q 'yi_vendor_bootstrap.py' "$APP_DIR/run.sh" \
    || ! grep -q -- '--share-dir /share/yi_rtsp' "$APP_DIR/run.sh"; then
  fail "local vendor bootstrap is not wired before backend startup"
fi
if ! grep -q '"managed_runtime_count"' "$ROOTFS/opt/yi-home/app/yi_addon_service.py"; then
  fail "bootstrap runtime-count marker is missing"
fi
echo "startup_policy_wiring=PASS"
echo "restart_persistence_markers=PASS"
echo "vendor_runtime_packaged=false"

mapfile -d '' PY_FILES < <(find "$ROOTFS/opt/yi-home/app" -maxdepth 1 -type f -name '*.py' -print0)
[[ "${#PY_FILES[@]}" -gt 0 ]] || fail "no Python application modules were staged"
"$PYTHON" -m py_compile "${PY_FILES[@]}"
echo "staged_python_compile=PASS"

if [[ "${YI_PHASE6D_DOCKER_BUILD:-0}" == "1" ]]; then
  read -r -a DOCKER_PARTS <<<"$DOCKER_CMD"
  [[ "${#DOCKER_PARTS[@]}" -gt 0 ]] || fail "DOCKER_CMD is empty"
  command -v "${DOCKER_PARTS[0]}" >/dev/null || fail "Docker command is unavailable: ${DOCKER_PARTS[0]}"
  "${DOCKER_PARTS[@]}" build --pull -t yi-home:phase6d "$APP_DIR"
  "${DOCKER_PARTS[@]}" run --rm --entrypoint /bin/sh yi-home:phase6d -c \
    'ffmpeg -version 2>&1 | grep -m1 -F "ffmpeg version 6.0.1-static" >/dev/null && ffprobe -version 2>&1 | grep -m1 -F "ffprobe version 6.0.1-static" >/dev/null'
  echo "docker_ffmpeg_pin=PASS"
  echo "docker_build=PASS"
else
  echo "docker_build=SKIPPED"
fi

echo "production_modified=false"
echo "PHASE6D_APP_CONTEXT_SMOKE=PASS"
