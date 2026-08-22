#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PROD_CONFIG="${PROD_CONFIG:-$PROD_ROOT/go2rtc.yaml}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"
RELAY="$ROOT/yi_native_av_relay.py"
SELECTOR="$ROOT/yi_native_av_relay_camera.py"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
WORKER_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
SERVICE="${YI_GO2RTC_SERVICE:-yi-go2rtc.service}"
STATE_ROOT="${YI_CUTOVER_STATE_ROOT:-$HOME/.local/state/yi-cam-integration}"
RTSP_PORT="${YI_GO2RTC_RTSP_PORT:-8554}"
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

render_dual_config() {
    local source="$1"
    local target="$2"
    "$PYTHON" - "$source" "$target" "$PYTHON" "$SELECTOR" "$ENV_FILE" "$RUNTIME" "$WORKER_DIR" <<'PY'
from pathlib import Path
import sys

src, dst, python, selector, env_file, runtime, worker_dir = sys.argv[1:]
text = Path(src).read_text(encoding="utf-8")
lines = text.splitlines()


def section_bounds(name: str):
    marker = f"{name}:"
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == marker and not line.startswith((" ", "\t")))
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
stream_block = lines[s0 + 1:s1]
if not any(line.startswith("  yi_warehouse:") for line in stream_block):
    raise SystemExit("yi_warehouse missing from streams section")
if not any(line.startswith("  yi_pool:") for line in stream_block):
    pool = (
        f"  yi_pool: 'exec:{python} {selector} --camera pool --env-file {env_file} "
        f"--runtime {runtime} --worker-dir {worker_dir} --qemu qemu-aarch64 --ffmpeg ffmpeg "
        f"--ffprobe ffprobe --stdout#killsignal=2#killtimeout=20#starttimeout=45'"
    )
    lines.insert(s1, pool)

preload = section_bounds("preload")
if preload is None:
    lines.extend(["", "preload:", '  yi_pool: "video&audio"'])
else:
    p0, p1 = preload
    preload_block = lines[p0 + 1:p1]
    if not any(line.startswith("  yi_pool:") for line in preload_block):
        lines.insert(p1, '  yi_pool: "video&audio"')

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
    echo "PHASE5_POOL_ROLLBACK=PASS"
}

apply() {
    for f in "$PROD_CONFIG" "$ENV_FILE" "$RELAY" "$SELECTOR" \
             "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so"; do
        [[ -f "$f" ]] || fail "required file missing: $f"
    done
    command -v ffprobe >/dev/null || fail "ffprobe missing"
    command -v qemu-aarch64 >/dev/null || fail "qemu-aarch64 missing"
    [[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
    service_active || fail "$SERVICE is not active before Phase 5"

    local stamp backup candidate work
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="$STATE_ROOT/phase5-pool-$stamp"
    work="$(mktemp -d)"
    candidate="$work/go2rtc.yaml"
    mkdir -p "$backup"
    cp -f "$PROD_CONFIG" "$backup/go2rtc.yaml"
    echo "production_backup_dir=$backup"

    render_dual_config "$PROD_CONFIG" "$candidate"
    echo "existing_config_preserved=PASS"
    cp -f "$candidate" "$PROD_CONFIG"
    echo "yi_pool_config_installed=PASS"

    if ! service_restart || ! service_active; then
        echo "service_restart=FAIL; rolling_back=true" >&2
        cp -f "$backup/go2rtc.yaml" "$PROD_CONFIG"
        service_restart || true
        fail "service failed after dual-stream config"
    fi
    echo "production_service_restart=PASS"

    if ! validate_stream yi_warehouse "$work/warehouse.json"; then
        echo "yi_warehouse_validation=FAIL; rolling_back=true" >&2
        cp -f "$backup/go2rtc.yaml" "$PROD_CONFIG"
        service_restart || true
        fail "warehouse stream failed after Phase 5 change"
    fi
    echo "yi_warehouse_validation=PASS"

    if ! validate_stream yi_pool "$work/pool.json"; then
        echo "yi_pool_validation=FAIL; rolling_back=true" >&2
        cp -f "$backup/go2rtc.yaml" "$PROD_CONFIG"
        service_restart || true
        fail "pool stream failed; original production config restored"
    fi
    echo "yi_pool_validation=PASS"

    echo "parallel_native_streams=yi_warehouse,yi_pool"
    echo "warehouse_rtsp=rtsp://127.0.0.1:${RTSP_PORT}/yi_warehouse"
    echo "pool_rtsp=rtsp://127.0.0.1:${RTSP_PORT}/yi_pool"
    echo "rollback_dir=$backup"
    echo "PHASE5_POOL_PARALLEL=PASS"
    rm -rf "$work"
}

case "$MODE" in
    --apply) apply ;;
    --rollback) rollback ;;
    *) fail "usage: $0 --apply | --rollback <backup-dir>" ;;
esac
