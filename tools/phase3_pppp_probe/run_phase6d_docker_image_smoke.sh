#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
APP_DIR="$ROOT/yi_home"
IMAGE="${YI_PHASE6D_IMAGE:-yi-home:phase6d}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
docker info >/dev/null 2>&1 || fail "docker daemon is not available to the current user"
[[ -x "$PYTHON" ]] || command -v "$PYTHON" >/dev/null 2>&1 || fail "python is unavailable: $PYTHON"

echo "production_modified=false"
echo "image_name=$IMAGE"

"$PYTHON" -m py_compile "$ROOT/tools/prepare_ha_app_context.py"
"$PYTHON" "$ROOT/tools/prepare_ha_app_context.py"
echo "app_context_prepare=PASS"

docker build --pull \
  --build-arg BUILD_VERSION=0.1.0 \
  --build-arg BUILD_ARCH=amd64 \
  -t "$IMAGE" \
  "$APP_DIR"
echo "docker_build=PASS"

ARCH="$(docker image inspect "$IMAGE" --format '{{.Architecture}}')"
OS="$(docker image inspect "$IMAGE" --format '{{.Os}}')"
[[ "$ARCH" == "amd64" ]] || fail "unexpected image architecture: $ARCH"
[[ "$OS" == "linux" ]] || fail "unexpected image OS: $OS"
echo "image_architecture=amd64"
echo "image_platform=linux/amd64"

docker run --rm --entrypoint /bin/sh "$IMAGE" -ec '
  command -v python3 >/dev/null
  command -v ffmpeg >/dev/null
  command -v ffprobe >/dev/null
  command -v qemu-aarch64 >/dev/null
  test -x /usr/local/bin/go2rtc
  test -x /run.sh
  test -f /opt/yi-home/app/yi_addon_service.py
  test -f /opt/yi-home/app/yi_vendor_bootstrap.py
  test -x /opt/yi-home/runtime/bionic-root/system/bin/linker64
  test -x /opt/yi-home/runtime/bionic-root/data/local/tmp/yi-online-status/android_pppp_online_probe
  test -z "$(find /opt/yi-home \( -iname libPPPP_API.so -o -iname yi-home.apk \) -print -quit)"
  cd /opt/yi-home/app
  python3 - <<"PY"
import cryptography
import yi_addon_service
import yi_online_status
print("container_python_imports=PASS")
PY
  ffmpeg -version >/dev/null 2>&1
  ffprobe -version >/dev/null 2>&1
  qemu-aarch64 --version >/dev/null 2>&1
  /usr/local/bin/go2rtc -version >/dev/null 2>&1 || /usr/local/bin/go2rtc --version >/dev/null 2>&1
  bash -n /run.sh
'
echo "container_runtime_dependencies=PASS"

# The build context deliberately excludes persistent state and account secrets.
# Verify the resulting filesystem contains none of those known file names.
docker run --rm --entrypoint /bin/sh "$IMAGE" -ec '
  leaked="$(find /opt/yi-home -type f \( \
      -name ".env" -o \
      -name ".env.local" -o \
      -name "options.json" -o \
      -name "backend-api-token" -o \
      -name "runtime-policy.json" -o \
      -name "capabilities.json" \
    \) -print -quit)"
  test -z "$leaked"
'
echo "image_secret_state_scan=PASS"
echo "image_vendor_artifact_scan=PASS"

# No container is started with /run.sh here, so this proof does not open YI
# cloud/PPPP sessions and does not bind the production RTSP/API ports.
echo "camera_sessions_started=false"
echo "production_go2rtc_ports_untouched=1984,8554"
echo "PHASE6D_DOCKER_IMAGE_SMOKE=PASS"
