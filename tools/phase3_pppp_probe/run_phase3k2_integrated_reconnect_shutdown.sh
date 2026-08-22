#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
GO2RTC="${GO2RTC:-$PROD_ROOT/.tools/go2rtc}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
FFMPEG="${FFMPEG:-ffmpeg}"
ENV_FILE="${1:-$PROD_ROOT/.env.local}"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
WORKER_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
ANALYSIS_DIR="$ROOT/.analysis/phase3"
CONFIG="$ANALYSIS_DIR/go2rtc-phase3k2.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3k2.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3k2-stream.json"
POST_LOG="$ANALYSIS_DIR/go2rtc-phase3k2-post.log"
EXIT_MARKER="$ANALYSIS_DIR/phase3k2-relay-exit.marker"
API_PORT="${PHASE3K2_API_PORT:-11984}"
RTSP_PORT="${PHASE3K2_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_integrated.py"

for tool in "$GO2RTC" "$PYTHON" "$FFMPEG" curl timeout ss pgrep; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done
for f in "$ENV_FILE" "$RELAY" "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so" "$RUNTIME/system/bin/linker64"; do
    [[ -f "$f" ]] || { echo "ERROR: required file missing: $f" >&2; exit 3; }
done

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$POST_LOG" "$EXIT_MARKER"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3K2 port already in use: $port" >&2
        exit 4
    fi
done

"$PYTHON" -m py_compile "$RELAY"
echo "integrated_relay_python_compile=PASS"

cat >"$CONFIG" <<EOF
log:
  level: info
  exec: debug
  streams: debug
  rtsp: debug
api:
  listen: "127.0.0.1:${API_PORT}"
rtsp:
  listen: "127.0.0.1:${RTSP_PORT}"
webrtc:
  listen: ""
streams:
  ${STREAM}: 'exec:/usr/bin/env YI_PHASE3_EXIT_MARKER=${EXIT_MARKER} ${PYTHON} ${RELAY} --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ${FFMPEG} --ffprobe ffprobe --stdout#killsignal=2#killtimeout=20'
preload:
  ${STREAM}: "video&audio"
EOF
chmod 600 "$CONFIG"

echo "=== PHASE 3K2: GENERATION-AWARE INTEGRATED RECONNECT + SHUTDOWN ==="
echo "production_go2rtc_service_touched=false"
echo "relay=yi_native_av_relay_integrated.py"
echo "counter_validation=receiver_id_generation_aware"

"$GO2RTC" -config "$CONFIG" >"$LOG" 2>&1 &
GO2RTC_PID=$!
STOPPED=0
cleanup() {
    if [[ "$STOPPED" == 1 ]]; then return; fi
    STOPPED=1
    if kill -0 "$GO2RTC_PID" 2>/dev/null; then kill -TERM "$GO2RTC_PID" 2>/dev/null || true; fi
    wait "$GO2RTC_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 100); do
    if curl -fsS --max-time 1 "http://127.0.0.1:${API_PORT}/" >/dev/null 2>&1; then
        echo "go2rtc_isolated_start=PASS"
        break
    fi
    sleep 0.1
done

API_URL="http://127.0.0.1:${API_PORT}/api/streams?src=${STREAM}"
RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"

state() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || return 1
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json,sys
try: obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception: raise SystemExit(1)
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts': continue
    v=a=None
    for r in p.get('receivers',[]) or []:
        c=(r.get('codec') or {}).get('codec_name')
        row=(int(r.get('id',0) or 0),int(r.get('packets',0) or 0))
        if c=='h264': v=row
        elif c=='aac': a=row
    if v and a:
        print(v[0],v[1],a[0],a[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

relay_pid() {
    pgrep -P "$GO2RTC_PID" -f 'yi_native_av_relay_integrated.py' | head -n 1 || true
}

wait_log_count() {
    local pattern="$1" wanted="$2" label="$3" limit="$4"
    for second in $(seq 1 "$limit"); do
        local count
        count="$(grep -c "$pattern" "$LOG" || true)"
        if (( count >= wanted )); then echo "${label}=PASS"; return 0; fi
        if (( second % 5 == 0 )); then echo "${label}_wait_seconds=${second}"; fi
        sleep 1
    done
    echo "${label}=FAIL" >&2
    tail -n 180 "$LOG" >&2 || true
    return 1
}

READY=0
for second in $(seq 1 40); do
    if STATE="$(state 2>/dev/null)"; then READY=1; echo "integrated_source_ready=PASS"; break; fi
    if (( second % 5 == 0 )); then echo "source_ready_wait_seconds=${second}"; fi
    sleep 1
done
[[ "$READY" == 1 ]] || { echo "integrated_source_ready=FAIL" >&2; tail -n 180 "$LOG" >&2; exit 5; }

read -r PRE_VID PRE_V0 PRE_AID PRE_A0 <<<"$STATE"
echo "pre_generation_video_receiver_id=${PRE_VID}"
echo "pre_generation_audio_receiver_id=${PRE_AID}"
sleep 5
read -r PRE_VID1 PRE_V1 PRE_AID1 PRE_A1 <<<"$(state)"
if [[ "$PRE_VID" != "$PRE_VID1" || "$PRE_AID" != "$PRE_AID1" ]] || (( PRE_V1 <= PRE_V0 || PRE_A1 <= PRE_A0 )); then
    echo "integrated_pre_reconnect_growth=FAIL" >&2
    exit 6
fi
echo "integrated_pre_reconnect_growth=PASS"

OLD_PID="$(relay_pid)"
[[ -n "$OLD_PID" ]] || { echo "integrated_relay_pid=FAIL" >&2; exit 7; }
echo "integrated_relay_pid=PASS"
rm -f "$EXIT_MARKER"
kill -INT "$OLD_PID"
for _ in $(seq 1 200); do ! kill -0 "$OLD_PID" 2>/dev/null && break; sleep 0.1; done
! kill -0 "$OLD_PID" 2>/dev/null || { echo "integrated_old_relay_exit=FAIL" >&2; exit 8; }
echo "integrated_old_relay_exit=PASS"

# The first integrated relay must itself finish cleanly before we trust any
# replacement producer state. The safe marker contains only the exit code.
OLD_MARKER=0
for second in $(seq 1 20); do
    if [[ -s "$EXIT_MARKER" ]]; then OLD_MARKER=1; break; fi
    sleep 1
done
[[ "$OLD_MARKER" == 1 ]] || { echo "integrated_old_relay_marker=FAIL" >&2; exit 9; }
OLD_VALUE="$(tr -d '\r\n' <"$EXIT_MARKER")"
echo "integrated_old_relay_marker_value=${OLD_VALUE}"
[[ "$OLD_VALUE" == "relay_exit_rc=0" ]] || { echo "integrated_old_relay_cleanup=FAIL" >&2; exit 10; }
echo "integrated_old_relay_cleanup=PASS"
rm -f "$EXIT_MARKER"

NEW_PID=""
for second in $(seq 1 45); do
    CAND="$(relay_pid)"
    if [[ -n "$CAND" && "$CAND" != "$OLD_PID" ]]; then NEW_PID="$CAND"; echo "integrated_replacement_relay_process=PASS"; break; fi
    if (( second % 5 == 0 )); then echo "integrated_replacement_wait_seconds=${second}"; fi
    sleep 1
done
[[ -n "$NEW_PID" ]] || { echo "integrated_replacement_relay_process=FAIL" >&2; tail -n 180 "$LOG" >&2; exit 11; }

wait_log_count 'phase3g_tnp_auth=PASS' 2 "integrated_second_native_session_authenticated" 35
wait_log_count 'PPPP_DeInitialize_rc_hex=0x00000000' 1 "integrated_first_session_deinitialized" 20

GEN_SWAP=0
for second in $(seq 1 35); do
    if NEW_STATE="$(state 2>/dev/null)"; then
        read -r NEW_VID NEW_V0 NEW_AID NEW_A0 <<<"$NEW_STATE"
        if (( NEW_VID > 0 && NEW_AID > 0 && NEW_V0 >= 5 && NEW_A0 >= 5 )) && [[ "$NEW_VID" != "$PRE_VID" && "$NEW_AID" != "$PRE_AID" ]]; then
            GEN_SWAP=1
            echo "integrated_receiver_generation_swap=PASS"
            echo "post_generation_video_receiver_id=${NEW_VID}"
            echo "post_generation_audio_receiver_id=${NEW_AID}"
            break
        fi
    fi
    if (( second % 5 == 0 )); then echo "integrated_generation_swap_wait_seconds=${second}"; fi
    sleep 1
done
[[ "$GEN_SWAP" == 1 ]] || { echo "integrated_receiver_generation_swap=FAIL" >&2; tail -n 180 "$LOG" >&2; exit 12; }

echo "integrated_reconnect_auth_and_cleanup=PASS"

set +e
timeout 15 "$FFMPEG" -hide_banner -nostdin -loglevel error -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 -i "$RTSP_URL" -t 3 -map 0:v:0 -map 0:a:0 -f null - >/dev/null 2>"$POST_LOG"
POST_RC=$?
set -e
[[ "$POST_RC" -eq 0 ]] || { echo "integrated_post_reconnect_av=FAIL" >&2; tail -n 80 "$POST_LOG" >&2; exit 13; }
echo "integrated_post_reconnect_av=PASS"

read -r G_VID0 G_V0 G_AID0 G_A0 <<<"$(state)"
sleep 8
read -r G_VID1 G_V1 G_AID1 G_A1 <<<"$(state)"
if [[ "$G_VID0" != "$G_VID1" || "$G_AID0" != "$G_AID1" ]] || (( G_V1 <= G_V0 || G_A1 <= G_A0 )); then
    echo "integrated_post_reconnect_growth=FAIL" >&2
    exit 14
fi
echo "integrated_post_reconnect_growth=PASS"

rm -f "$EXIT_MARKER"
mapfile -t CHILDREN < <(pgrep -P "$NEW_PID" || true)
echo "integrated_parent_shutdown_signal=SIGINT"
kill -INT "$GO2RTC_PID"
for _ in $(seq 1 120); do ! kill -0 "$GO2RTC_PID" 2>/dev/null && break; sleep 0.1; done
! kill -0 "$GO2RTC_PID" 2>/dev/null || { echo "integrated_go2rtc_exit=FAIL" >&2; exit 15; }
wait "$GO2RTC_PID" 2>/dev/null || true
STOPPED=1
echo "integrated_go2rtc_exit=PASS"

MARKER=0
for second in $(seq 1 30); do
    if [[ -s "$EXIT_MARKER" ]]; then MARKER=1; break; fi
    sleep 1
done
[[ "$MARKER" == 1 ]] || { echo "integrated_parent_exit_marker=FAIL" >&2; exit 16; }
VALUE="$(tr -d '\r\n' <"$EXIT_MARKER")"
echo "integrated_parent_exit_marker_value=${VALUE}"
[[ "$VALUE" == "relay_exit_rc=0" ]] || { echo "integrated_parent_shutdown_cleanup=FAIL" >&2; exit 17; }
! kill -0 "$NEW_PID" 2>/dev/null || { echo "integrated_relay_exit_after_parent=FAIL" >&2; exit 18; }
for pid in "${CHILDREN[@]}"; do
    [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null || { echo "integrated_orphan_child=FAIL" >&2; exit 19; }
done
echo "integrated_parent_shutdown_cleanup=PASS"
echo "PHASE3K2_INTEGRATED=PASS"
