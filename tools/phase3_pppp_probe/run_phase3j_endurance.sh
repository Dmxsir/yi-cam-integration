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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3j.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3j.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3j-stream.json"
DECODE_LOG="$ANALYSIS_DIR/go2rtc-phase3j-decode.log"
API_PORT="${PHASE3J_API_PORT:-11984}"
RTSP_PORT="${PHASE3J_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_pipe.py"
DURATION="${PHASE3J_DURATION:-180}"
INTERVAL="${PHASE3J_INTERVAL:-15}"
DECODE_EVERY="${PHASE3J_DECODE_EVERY:-60}"

for tool in "$GO2RTC" "$PYTHON" "$FFMPEG" curl timeout ss pgrep ps; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done
for f in "$ENV_FILE" "$RELAY" "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so" "$RUNTIME/system/bin/linker64"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: required file missing: $f" >&2
        exit 3
    fi
done
if (( DURATION < 60 || INTERVAL < 5 || DECODE_EVERY < INTERVAL )); then
    echo "ERROR: invalid endurance timing" >&2
    exit 4
fi

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$DECODE_LOG"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3J port already in use: $port" >&2
        exit 5
    fi
done

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
  ${STREAM}: 'exec:${PYTHON} ${RELAY} --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ${FFMPEG} --ffprobe ffprobe --stdout#killsignal=2#killtimeout=20'
preload:
  ${STREAM}: "video&audio"
EOF
chmod 600 "$CONFIG"

echo "=== PHASE 3J: ISOLATED NATIVE A/V ENDURANCE ==="
echo "production_go2rtc_service_touched=false"
echo "stream=${STREAM}"
echo "source=phoneless_native_PPPP_TNP"
echo "preload=video&audio"
echo "duration_seconds=${DURATION}"
echo "heartbeat_seconds=${INTERVAL}"
echo "decode_check_seconds=${DECODE_EVERY}"

"$GO2RTC" -config "$CONFIG" >"$LOG" 2>&1 &
GO2RTC_PID=$!
STOPPED=0

shutdown_stack() {
    if [[ "$STOPPED" == 1 ]]; then
        return
    fi
    STOPPED=1
    if kill -0 "$GO2RTC_PID" 2>/dev/null; then
        kill -INT "$GO2RTC_PID" 2>/dev/null || true
        for _ in $(seq 1 120); do
            kill -0 "$GO2RTC_PID" 2>/dev/null || break
            sleep 0.1
        done
        kill -TERM "$GO2RTC_PID" 2>/dev/null || true
    fi
    wait "$GO2RTC_PID" 2>/dev/null || true
}
trap shutdown_stack EXIT INT TERM

for _ in $(seq 1 100); do
    if curl -fsS --max-time 1 "http://127.0.0.1:${API_PORT}/" >/dev/null 2>&1; then
        echo "go2rtc_isolated_start=PASS"
        break
    fi
    sleep 0.1
done

API_URL="http://127.0.0.1:${API_PORT}/api/streams?src=${STREAM}"
RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"

source_state() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || return 1
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    raise SystemExit(1)
video=None; audio=None
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts':
        continue
    for r in p.get('receivers',[]) or []:
        codec=(r.get('codec') or {}).get('codec_name')
        row=(int(r.get('id',0) or 0), int(r.get('packets',0) or 0), int(r.get('bytes',0) or 0))
        if codec=='h264': video=row
        elif codec=='aac': audio=row
if not video or not audio:
    raise SystemExit(1)
print(*video, *audio)
PY
}

ready=0
for second in $(seq 1 40); do
    if STATE="$(source_state 2>/dev/null)"; then
        ready=1
        echo "endurance_source_ready=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "source_ready_wait_seconds=${second}"
        tail -n 10 "$LOG" | sed 's/^/[go2rtc-tail] /'
    fi
    sleep 1
done
if [[ "$ready" != 1 ]]; then
    echo "endurance_source_ready=FAIL" >&2
    tail -n 180 "$LOG" >&2 || true
    exit 6
fi

read -r V_ID V_PKTS V_BYTES A_ID A_PKTS A_BYTES <<<"$STATE"
BASE_V_ID="$V_ID"; BASE_A_ID="$A_ID"
PREV_V="$V_PKTS"; PREV_A="$A_PKTS"
echo "baseline_video_receiver_id=${BASE_V_ID}"
echo "baseline_audio_receiver_id=${BASE_A_ID}"
echo "baseline_video_packets=${PREV_V}"
echo "baseline_audio_packets=${PREV_A}"

RELAY_PID="$(pgrep -P "$GO2RTC_PID" -f 'yi_native_av_relay_pipe.py' | head -n 1 || true)"
if [[ -n "$RELAY_PID" ]]; then
    START_RSS="$(ps -o rss= -p "$RELAY_PID" 2>/dev/null | tr -d ' ' || true)"
else
    START_RSS=""
fi
echo "relay_rss_start_kb=${START_RSS:-NA}"

av_decode() {
    local elapsed="$1"
    set +e
    timeout 12 "$FFMPEG" \
        -hide_banner -nostdin -loglevel error \
        -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 \
        -i "$RTSP_URL" -t 2 \
        -map 0:v:0 -map 0:a:0 -f null - \
        >/dev/null 2>"$DECODE_LOG"
    local rc=$?
    set -e
    echo "endurance_av_decode_${elapsed}s_rc=${rc}"
    if [[ "$rc" -ne 0 ]]; then
        echo "endurance_av_decode_${elapsed}s=FAIL" >&2
        tail -n 100 "$DECODE_LOG" >&2 || true
        return 1
    fi
    echo "endurance_av_decode_${elapsed}s=PASS"
}

elapsed=0
next_decode="$DECODE_EVERY"
while (( elapsed < DURATION )); do
    step="$INTERVAL"
    if (( elapsed + step > DURATION )); then
        step=$((DURATION - elapsed))
    fi
    sleep "$step"
    elapsed=$((elapsed + step))

    if ! STATE="$(source_state 2>/dev/null)"; then
        echo "endurance_source_state_${elapsed}s=FAIL" >&2
        tail -n 180 "$LOG" >&2 || true
        exit 7
    fi
    read -r V_ID V_PKTS V_BYTES A_ID A_PKTS A_BYTES <<<"$STATE"
    echo "heartbeat_${elapsed}s=video_id:${V_ID},video_packets:${V_PKTS},audio_id:${A_ID},audio_packets:${A_PKTS}"

    if [[ "$V_ID" != "$BASE_V_ID" || "$A_ID" != "$BASE_A_ID" ]]; then
        echo "unexpected_receiver_generation_change=FAIL" >&2
        echo "expected_video_id=${BASE_V_ID}; actual_video_id=${V_ID}" >&2
        echo "expected_audio_id=${BASE_A_ID}; actual_audio_id=${A_ID}" >&2
        exit 8
    fi
    if (( V_PKTS <= PREV_V || A_PKTS <= PREV_A )); then
        echo "heartbeat_packet_growth_${elapsed}s=FAIL" >&2
        exit 9
    fi
    echo "heartbeat_packet_growth_${elapsed}s=PASS"
    PREV_V="$V_PKTS"; PREV_A="$A_PKTS"

    if (( elapsed >= next_decode )); then
        av_decode "$elapsed"
        next_decode=$((next_decode + DECODE_EVERY))
    fi
done

echo "continuous_receiver_generation=PASS"
echo "continuous_packet_growth=PASS"

# One final A/V consumer check at the end of the endurance window.
av_decode "final"

AUTH_COUNT="$(grep -c 'phase3g_tnp_auth=PASS' "$LOG" || true)"
echo "tnp_auth_pass_count_before_shutdown=${AUTH_COUNT}"
if (( AUTH_COUNT != 1 )); then
    echo "unexpected_native_session_restart=FAIL" >&2
    exit 10
fi
echo "single_native_session_for_full_endurance=PASS"

if [[ -n "$RELAY_PID" ]] && kill -0 "$RELAY_PID" 2>/dev/null; then
    END_RSS="$(ps -o rss= -p "$RELAY_PID" 2>/dev/null | tr -d ' ' || true)"
else
    END_RSS=""
fi
echo "relay_rss_end_kb=${END_RSS:-NA}"
if [[ -n "$START_RSS" && -n "$END_RSS" ]]; then
    echo "relay_rss_delta_kb=$((END_RSS - START_RSS))"
fi

shutdown_stack
trap - EXIT INT TERM

DEINIT_COUNT="$(grep -c 'PPPP_DeInitialize_rc_hex=0x00000000' "$LOG" || true)"
STOP_COUNT="$(grep -c 'PPPP_Write_767_rc_hex=' "$LOG" || true)"
echo "pppp_deinitialize_success_count=${DEINIT_COUNT}"
echo "tnp_stop_767_count=${STOP_COUNT}"
if (( DEINIT_COUNT < 1 )); then
    echo "endurance_clean_native_shutdown=FAIL" >&2
    tail -n 160 "$LOG" >&2 || true
    exit 11
fi
echo "endurance_clean_native_shutdown=PASS"
echo "PHASE3J_ENDURANCE=PASS"
