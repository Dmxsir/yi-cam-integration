#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PROD_CONFIG="${PROD_CONFIG:-$PROD_ROOT/go2rtc.yaml}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"
RELAY="$ROOT/yi_native_av_relay.py"
SELECTOR="$ROOT/yi_native_av_relay_camera.py"
SUPERVISOR="$ROOT/yi_native_session_supervisor.py"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
WORKER_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
SERVICE="${YI_GO2RTC_SERVICE:-yi-go2rtc.service}"
STATE_ROOT="${YI_CUTOVER_STATE_ROOT:-$HOME/.local/state/yi-cam-integration}"
RTSP_PORT="${YI_GO2RTC_RTSP_PORT:-8554}"
STARTUP_TIMEOUT="${YI_SUPERVISOR_STARTUP_TIMEOUT:-45}"
STALL_TIMEOUT="${YI_SUPERVISOR_STALL_TIMEOUT:-12}"
MODE="${1:---apply}"
ROLLBACK_DIR="${2:-}"

fail() { echo "ERROR: $*" >&2; exit 1; }

service_restart() {
    if systemctl --user show "$SERVICE" -p LoadState --value 2>/dev/null | grep -qx loaded; then
        systemctl --user restart "$SERVICE"
    elif [[ "$EUID" -eq 0 ]]; then
        systemctl restart "$SERVICE"
    else
        sudo systemctl restart "$SERVICE"
    fi
}

service_active() {
    systemctl --user is-active --quiet "$SERVICE" 2>/dev/null || systemctl is-active --quiet "$SERVICE" 2>/dev/null
}

validate_stream() {
    local stream="$1"
    local out="$2"
    local url="rtsp://127.0.0.1:${RTSP_PORT}/${stream}"
    local ok=0
    for second in $(seq 1 60); do
        if timeout 8 ffprobe -v error -rtsp_transport tcp \
            -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
            -of json "$url" >"$out" 2>/dev/null; then
            if "$PYTHON" - "$out" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
s=obj.get('streams',[])
v=any(x.get('codec_type')=='video' and x.get('codec_name')=='h264' and x.get('width')==1920 and x.get('height')==1080 for x in s)
a=any(x.get('codec_type')=='audio' and x.get('codec_name')=='aac' and str(x.get('sample_rate'))=='16000' and int(x.get('channels',0) or 0)==1 for x in s)
raise SystemExit(0 if v and a else 1)
PY
            then
                ok=1
                break
            fi
        fi
        if (( second % 10 == 0 )); then
            echo "${stream}_wait_seconds=${second}"
        fi
        sleep 1
    done
    [[ "$ok" == 1 ]]
}

render_supervised_config() {
    local source="$1"
    local target="$2"
    "$PYTHON" - "$source" "$target" "$PYTHON" "$SUPERVISOR" "$RELAY" "$SELECTOR" "$ENV_FILE" "$RUNTIME" "$WORKER_DIR" "$STARTUP_TIMEOUT" "$STALL_TIMEOUT" <<'PY'
from pathlib import Path
import sys

(src, dst, python, supervisor, relay, selector, env_file, runtime,
 worker_dir, startup_timeout, stall_timeout) = sys.argv[1:]
lines = Path(src).read_text(encoding="utf-8").splitlines()


def section_bounds(name: str):
    marker = f"{name}:"
    try:
        start = next(i for i, line in enumerate(lines)
                     if line.strip() == marker and not line.startswith((" ", "\t")))
    except StopIteration:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line and not line.startswith((" ", "\t", "#")):
            end = i
            break
    return start, end

streams = section_bounds("streams")
if streams is None:
    raise SystemExit("top-level streams section missing")
s0, s1 = streams
found = {"yi_warehouse": False, "yi_pool": False}

common = (
    f"{python} {supervisor} --startup-timeout {startup_timeout} "
    f"--stall-timeout {stall_timeout} -- "
)
warehouse_relay = (
    f"{python} {relay} --env-file {env_file} --runtime {runtime} "
    f"--worker-dir {worker_dir} --qemu qemu-aarch64 --ffmpeg ffmpeg "
    f"--ffprobe ffprobe --stdout"
)
pool_relay = (
    f"{python} {selector} --camera pool --env-file {env_file} --runtime {runtime} "
    f"--worker-dir {worker_dir} --qemu qemu-aarch64 --ffmpeg ffmpeg "
    f"--ffprobe ffprobe --stdout"
)

for i in range(s0 + 1, s1):
    stripped = lines[i].lstrip()
    indent = lines[i][:len(lines[i]) - len(stripped)]
    if stripped.startswith("yi_warehouse:"):
        lines[i] = (
            f"{indent}yi_warehouse: 'exec:{common}{warehouse_relay}"
            "#killsignal=2#killtimeout=20#starttimeout=60'"
        )
        found["yi_warehouse"] = True
    elif stripped.startswith("yi_pool:"):
        lines[i] = (
            f"{indent}yi_pool: 'exec:{common}{pool_relay}"
            "#killsignal=2#killtimeout=20#starttimeout=60'"
        )
        found["yi_pool"] = True

missing = [name for name, present in found.items() if not present]
if missing:
    raise SystemExit("missing streams: " + ",".join(missing))

Path(dst).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
    chmod 600 "$target"
}

rollback() {
    [[ -n "$ROLLBACK_DIR" ]] || fail "usage: $0 --rollback <backup-dir>"
    [[ -f "$ROLLBACK_DIR/go2rtc.yaml" ]] || fail "backup config not found: $ROLLBACK_DIR/go2rtc.yaml"
    cp -f "$ROLLBACK_DIR/go2rtc.yaml" "$PROD_CONFIG"
    service_restart
    service_active || fail "$SERVICE failed after rollback"
    echo "rollback_config_restored=PASS"
    echo "PHASE5B_SUPERVISOR_ROLLBACK=PASS"
}

apply() {
    for f in "$PROD_CONFIG" "$ENV_FILE" "$RELAY" "$SELECTOR" "$SUPERVISOR" \
             "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so"; do
        [[ -f "$f" ]] || fail "required file missing: $f"
    done
    [[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
    command -v ffprobe >/dev/null || fail "ffprobe missing"
    command -v qemu-aarch64 >/dev/null || fail "qemu-aarch64 missing"
    service_active || fail "$SERVICE is not active before supervisor cutover"

    "$PYTHON" -m py_compile "$SUPERVISOR" "$RELAY" "$SELECTOR"
    echo "python_compile=PASS"

    local stamp backup candidate work
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="$STATE_ROOT/phase5b-supervisor-$stamp"
    work="$(mktemp -d)"
    candidate="$work/go2rtc.yaml"
    mkdir -p "$backup"
    cp -f "$PROD_CONFIG" "$backup/go2rtc.yaml"
    echo "production_backup_dir=$backup"

    render_supervised_config "$PROD_CONFIG" "$candidate"
    echo "existing_config_preserved=PASS"
    grep -q 'yi_native_session_supervisor.py' "$candidate" || fail "supervisor not rendered"
    cp -f "$candidate" "$PROD_CONFIG"
    echo "supervisor_config_installed=PASS"

    if ! service_restart || ! service_active; then
        echo "service_restart=FAIL; rolling_back=true" >&2
        cp -f "$backup/go2rtc.yaml" "$PROD_CONFIG"
        service_restart || true
        fail "service failed after supervisor cutover"
    fi
    echo "production_service_restart=PASS"

    if ! validate_stream yi_warehouse "$work/warehouse.json"; then
        echo "yi_warehouse_validation=FAIL; rolling_back=true" >&2
        cp -f "$backup/go2rtc.yaml" "$PROD_CONFIG"
        service_restart || true
        fail "warehouse failed after supervisor cutover"
    fi
    echo "yi_warehouse_validation=PASS"

    if ! validate_stream yi_pool "$work/pool.json"; then
        echo "yi_pool_validation=FAIL; rolling_back=true" >&2
        cp -f "$backup/go2rtc.yaml" "$PROD_CONFIG"
        service_restart || true
        fail "pool failed after supervisor cutover"
    fi
    echo "yi_pool_validation=PASS"

    if pgrep -af 'yi_native_session_supervisor.py' >/dev/null 2>&1; then
        echo "supervisor_process_present=PASS"
    else
        echo "supervisor_process_present=WARN"
    fi

    echo "supervised_streams=yi_warehouse,yi_pool"
    echo "startup_timeout_seconds=$STARTUP_TIMEOUT"
    echo "stall_timeout_seconds=$STALL_TIMEOUT"
    echo "rollback_dir=$backup"
    echo "PHASE5B_SUPERVISOR_CUTOVER=PASS"
    rm -rf "$work"
}

case "$MODE" in
    --apply) apply ;;
    --rollback) rollback ;;
    *) fail "usage: $0 --apply | --rollback <backup-dir>" ;;
esac
