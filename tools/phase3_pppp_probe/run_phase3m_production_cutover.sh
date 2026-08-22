#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PROD_CONFIG="${PROD_CONFIG:-$PROD_ROOT/go2rtc.yaml}"
PROD_GO2RTC="${PROD_GO2RTC:-$PROD_ROOT/.tools/go2rtc}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"
RELAY="$ROOT/yi_native_av_relay.py"
REFERENCE="$ROOT/yi_native_av_relay_integrated.py"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
WORKER_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
SERVICE="${YI_GO2RTC_SERVICE:-yi-go2rtc.service}"
API_PORT="${YI_GO2RTC_API_PORT:-1984}"
RTSP_PORT="${YI_GO2RTC_RTSP_PORT:-8554}"
STREAM="yi_warehouse"
STATE_ROOT="${YI_CUTOVER_STATE_ROOT:-$HOME/.local/state/yi-cam-integration}"
MODE="${1:---preflight}"
ROLLBACK_DIR="${2:-}"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

for tool in "$PYTHON" "$PROD_GO2RTC" cmp curl ffmpeg ffprobe qemu-aarch64 systemctl ss; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        fail "required tool missing: $tool"
    fi
done
for f in "$PROD_CONFIG" "$ENV_FILE" "$RELAY" "$REFERENCE" \
         "$ROOT/tools/phase3_pppp_probe/run_phase3e_tnp.py" \
         "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so" \
         "$RUNTIME/system/bin/linker64"; do
    [[ -f "$f" ]] || fail "required file missing: $f"
done

SERVICE_SCOPE=""
if systemctl --user show "$SERVICE" >/dev/null 2>&1; then
    SERVICE_SCOPE="user"
elif systemctl show "$SERVICE" >/dev/null 2>&1; then
    SERVICE_SCOPE="system"
else
    fail "systemd service not found: $SERVICE"
fi

service_is_active() {
    if [[ "$SERVICE_SCOPE" == "user" ]]; then
        systemctl --user is-active --quiet "$SERVICE"
    else
        systemctl is-active --quiet "$SERVICE"
    fi
}

service_restart() {
    if [[ "$SERVICE_SCOPE" == "user" ]]; then
        systemctl --user restart "$SERVICE"
    elif [[ "$EUID" -eq 0 ]]; then
        systemctl restart "$SERVICE"
    else
        sudo systemctl restart "$SERVICE"
    fi
}

service_status_tail() {
    if [[ "$SERVICE_SCOPE" == "user" ]]; then
        systemctl --user status "$SERVICE" --no-pager -l 2>/dev/null | tail -n 30 || true
    else
        systemctl status "$SERVICE" --no-pager -l 2>/dev/null | tail -n 30 || true
    fi
}

api_url="http://127.0.0.1:${API_PORT}/api/streams?src=${STREAM}"
rtsp_url="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"

source_json() {
    curl -fsS --max-time 2 "$api_url"
}

native_state() {
    local snapshot="$1"
    "$PYTHON" - "$snapshot" <<'PY'
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    raise SystemExit(1)
video=audio=None
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts':
        continue
    for r in p.get('receivers',[]) or []:
        codec=(r.get('codec') or {}).get('codec_name')
        row=(int(r.get('id',0) or 0), int(r.get('packets',0) or 0))
        if codec=='h264': video=row
        elif codec=='aac': audio=row
if not video or not audio:
    raise SystemExit(1)
print(video[0],video[1],audio[0],audio[1])
PY
}

validate_native_live() {
    local work="$1"
    local snapshot="$work/streams.json"
    local probe="$work/ffprobe.json"
    local decode_log="$work/decode.log"
    local state0 state1

    local ready=0
    for second in $(seq 1 60); do
        if curl -fsS --max-time 2 -o "$snapshot" "$api_url" 2>/dev/null \
           && state0="$(native_state "$snapshot" 2>/dev/null)"; then
            ready=1
            echo "production_native_source_ready=PASS"
            break
        fi
        if (( second % 10 == 0 )); then
            echo "production_native_source_wait_seconds=${second}"
        fi
        sleep 1
    done
    [[ "$ready" == 1 ]] || return 1

    if ! ffprobe -v error -rtsp_transport tcp \
        -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
        -of json "$rtsp_url" >"$probe" 2>/dev/null; then
        echo "production_native_tracks=FAIL" >&2
        return 1
    fi
    if ! "$PYTHON" - "$probe" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
streams=obj.get('streams',[])
v=any(s.get('codec_type')=='video' and s.get('codec_name')=='h264' and s.get('width')==1920 and s.get('height')==1080 for s in streams)
a=any(s.get('codec_type')=='audio' and s.get('codec_name')=='aac' and str(s.get('sample_rate'))=='16000' and int(s.get('channels',0) or 0)==1 for s in streams)
raise SystemExit(0 if v and a else 1)
PY
    then
        echo "production_native_tracks=FAIL" >&2
        cat "$probe" >&2 || true
        return 1
    fi
    echo "production_native_tracks=PASS"

    set +e
    timeout 15 ffmpeg -hide_banner -nostdin -loglevel error \
        -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 \
        -i "$rtsp_url" -t 3 -map 0:v:0 -map 0:a:0 -f null - \
        >/dev/null 2>"$decode_log"
    local decode_rc=$?
    set -e
    echo "production_native_av_decode_rc=${decode_rc}"
    if [[ "$decode_rc" -ne 0 ]]; then
        echo "production_native_av_decode=FAIL" >&2
        tail -n 80 "$decode_log" >&2 || true
        return 1
    fi
    echo "production_native_av_decode=PASS"

    read -r v_id0 v0 a_id0 a0 <<<"$state0"
    sleep 6
    if ! curl -fsS --max-time 2 -o "$snapshot" "$api_url" 2>/dev/null \
       || ! state1="$(native_state "$snapshot" 2>/dev/null)"; then
        echo "production_native_packet_growth=FAIL" >&2
        return 1
    fi
    read -r v_id1 v1 a_id1 a1 <<<"$state1"
    if [[ "$v_id0" != "$v_id1" || "$a_id0" != "$a_id1" ]] || (( v1 <= v0 || a1 <= a0 )); then
        echo "production_native_packet_growth=FAIL" >&2
        return 1
    fi
    echo "production_native_packet_growth=PASS"
    return 0
}

write_candidate_config() {
    local path="$1"
    cat >"$path" <<EOF
streams:
  yi_warehouse: 'exec:${PYTHON} ${RELAY} --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ffmpeg --ffprobe ffprobe --stdout#killsignal=2#killtimeout=20#starttimeout=45'

preload:
  yi_warehouse: "video&audio"
EOF
    chmod 600 "$path"
}

preflight() {
    echo "=== PHASE 3M: PRODUCTION CUTOVER PREFLIGHT ==="
    echo "production_modified=false"
    echo "service=${SERVICE}"
    echo "service_scope=${SERVICE_SCOPE}"
    echo "production_config=${PROD_CONFIG}"
    echo "candidate_relay=${RELAY}"

    "$PYTHON" -m py_compile "$RELAY"
    echo "final_relay_python_compile=PASS"
    cmp -s "$RELAY" "$REFERENCE" || fail "final relay differs from Phase 3K2 integrated candidate"
    echo "final_relay_exact_integrated_blob=PASS"

    service_is_active || fail "$SERVICE is not active before cutover"
    echo "production_service_active=PASS"

    if grep -q 'yi_production_relay.py' "$PROD_CONFIG"; then
        echo "production_source_before=ADB_ORACLE_RELAY"
    elif grep -q 'yi_native_av_relay.py' "$PROD_CONFIG"; then
        echo "production_source_before=NATIVE_RELAY_ALREADY_CONFIGURED"
    else
        fail "production go2rtc.yaml has an unknown yi_warehouse source; refusing automated cutover"
    fi

    grep -q 'yi_warehouse' "$PROD_CONFIG" || fail "yi_warehouse stream missing from production config"
    [[ -d "$RUNTIME" ]] || fail "Bionic runtime missing"
    echo "native_runtime_present=PASS"
    echo "native_worker_present=PASS"

    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${API_PORT}$"; then
        echo "production_api_port_listening=PASS"
    else
        fail "production go2rtc API port ${API_PORT} is not listening"
    fi
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${RTSP_PORT}$"; then
        echo "production_rtsp_port_listening=PASS"
    else
        fail "production go2rtc RTSP port ${RTSP_PORT} is not listening"
    fi

    local tmp
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' RETURN
    write_candidate_config "$tmp"
    echo "candidate_config_render=PASS"
    echo "rollback_strategy=atomic_config_backup+service_restart"
    echo "PHASE3M_PREFLIGHT=PASS"
}

rollback() {
    [[ -n "$ROLLBACK_DIR" ]] || fail "usage: $0 --rollback <backup-dir>"
    local before="$ROLLBACK_DIR/go2rtc.yaml.before"
    [[ -f "$before" ]] || fail "rollback backup missing: $before"
    echo "=== PHASE 3M: ROLLBACK ==="
    cp -f "$before" "$PROD_CONFIG"
    chmod 600 "$PROD_CONFIG"
    service_restart
    for second in $(seq 1 45); do
        if service_is_active && curl -fsS --max-time 2 "$api_url" >/dev/null 2>&1; then
            echo "rollback_service_recovered=PASS"
            echo "PHASE3M_ROLLBACK=PASS"
            return 0
        fi
        sleep 1
    done
    echo "rollback_service_recovered=FAIL" >&2
    service_status_tail >&2
    return 1
}

apply_cutover() {
    preflight
    if grep -q 'yi_native_av_relay.py' "$PROD_CONFIG" && grep -q 'video&audio' "$PROD_CONFIG"; then
        echo "production_native_config_already_present=true"
        fail "production config already appears cut over; use validation/rollback rather than applying twice"
    fi

    mkdir -p "$STATE_ROOT"
    chmod 700 "$STATE_ROOT"
    local stamp backup candidate
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="$STATE_ROOT/cutover-$stamp"
    mkdir -p "$backup"
    chmod 700 "$backup"
    cp -p "$PROD_CONFIG" "$backup/go2rtc.yaml.before"
    candidate="$backup/go2rtc.yaml.native"
    write_candidate_config "$candidate"

    cat >"$backup/ROLLBACK.txt" <<EOF
Restore command:
cd ${ROOT} && bash tools/phase3_pppp_probe/run_phase3m_production_cutover.sh --rollback ${backup}
EOF
    chmod 600 "$backup/ROLLBACK.txt"

    echo "production_backup_dir=${backup}"
    echo "production_config_backup=PASS"

    cp -f "$candidate" "$PROD_CONFIG"
    chmod 600 "$PROD_CONFIG"
    echo "production_native_config_installed=PASS"

    if ! service_restart; then
        echo "production_service_restart=FAIL" >&2
        echo "automatic_rollback=START"
        cp -f "$backup/go2rtc.yaml.before" "$PROD_CONFIG"
        service_restart || true
        fail "native restart failed; previous config restored"
    fi
    echo "production_service_restart=PASS"

    if ! validate_native_live "$backup"; then
        echo "native_validation=FAIL" >&2
        echo "automatic_rollback=START"
        cp -f "$backup/go2rtc.yaml.before" "$PROD_CONFIG"
        chmod 600 "$PROD_CONFIG"
        service_restart || true
        for _ in $(seq 1 45); do
            service_is_active && curl -fsS --max-time 2 "$api_url" >/dev/null 2>&1 && break
            sleep 1
        done
        echo "automatic_rollback=DONE"
        echo "rollback_dir=${backup}"
        return 20
    fi

    echo "native_validation=PASS"
    echo "phone_runtime_required=false"
    echo "adb_runtime_required=false"
    echo "production_stream=H264_1920x1080+AACLС_16000_MONO"
    echo "rollback_dir=${backup}"
    echo "PHASE3M_PRODUCTION_CUTOVER=PASS"
}

case "$MODE" in
    --preflight) preflight ;;
    --apply) apply_cutover ;;
    --rollback) rollback ;;
    *) fail "usage: $0 [--preflight|--apply|--rollback <backup-dir>]" ;;
esac
