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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3i.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3i.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3i-stream.json"
PRE_AV_LOG="$ANALYSIS_DIR/go2rtc-phase3i-pre-av.log"
POST_AV_LOG="$ANALYSIS_DIR/go2rtc-phase3i-post-av.log"
API_PORT="${PHASE3I_API_PORT:-11984}"
RTSP_PORT="${PHASE3I_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_pipe.py"

for tool in "$GO2RTC" "$PYTHON" "$FFMPEG" curl timeout ss pgrep; do
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

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$PRE_AV_LOG" "$POST_AV_LOG"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3I port already in use: $port" >&2
        exit 4
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

echo "=== PHASE 3I: ISOLATED NATIVE A/V RECONNECT + STABILITY ==="
echo "production_go2rtc_service_touched=false"
echo "stream=${STREAM}"
echo "source=phoneless_native_PPPP_TNP"
echo "preload=video&audio"
echo "test=packet_growth + AV_decode + graceful_source_restart + go2rtc_reconnect + AV_decode"

"$GO2RTC" -config "$CONFIG" >"$LOG" 2>&1 &
GO2RTC_PID=$!

cleanup() {
    if kill -0 "$GO2RTC_PID" 2>/dev/null; then
        kill -INT "$GO2RTC_PID" 2>/dev/null || true
        for _ in $(seq 1 80); do
            kill -0 "$GO2RTC_PID" 2>/dev/null || break
            sleep 0.1
        done
        kill -TERM "$GO2RTC_PID" 2>/dev/null || true
    fi
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

source_ready() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || return 1
    "$PYTHON" - "$API_SNAPSHOT" <<'PY' >/dev/null 2>&1
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    raise SystemExit(1)
for p in obj.get('producers',[]) or []:
    if p.get('format_name') != 'mpegts':
        continue
    medias='\n'.join(str(x) for x in p.get('medias',[]) or [])
    if 'video, recvonly, H264' in medias and 'audio, recvonly, MPEG4-GENERIC/16000/1' in medias:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

wait_source() {
    local label="$1" limit="$2"
    for second in $(seq 1 "$limit"); do
        if source_ready; then
            echo "${label}=PASS"
            return 0
        fi
        if (( second % 5 == 0 )); then
            echo "${label}_wait_seconds=${second}"
            tail -n 10 "$LOG" | sed 's/^/[go2rtc-tail] /'
        fi
        sleep 1
    done
    echo "${label}=FAIL" >&2
    tail -n 180 "$LOG" >&2 || true
    return 1
}

packet_counts() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    print('0 0')
    raise SystemExit(0)
v=a=0
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts':
        continue
    for r in p.get('receivers',[]) or []:
        c=(r.get('codec') or {}).get('codec_name')
        n=int(r.get('packets',0) or 0)
        if c=='h264': v=max(v,n)
        elif c=='aac': a=max(a,n)
print(v,a)
PY
}

relay_pid() {
    pgrep -P "$GO2RTC_PID" -f 'yi_native_av_relay_pipe.py' | head -n 1 || true
}

av_decode() {
    local label="$1" logfile="$2"
    set +e
    timeout 15 "$FFMPEG" \
        -hide_banner -nostdin -loglevel error \
        -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 \
        -i "$RTSP_URL" -t 3 \
        -map 0:v:0 -map 0:a:0 -f null - \
        >/dev/null 2>"$logfile"
    local rc=$?
    set -e
    echo "${label}_rc=${rc}"
    if [[ "$rc" -eq 0 ]]; then
        echo "${label}=PASS"
        return 0
    fi
    echo "${label}=FAIL" >&2
    tail -n 100 "$logfile" >&2 || true
    return 1
}

wait_source "initial_source_ready" 35

read -r PRE_V0 PRE_A0 < <(packet_counts)
echo "pre_growth_start_video_packets=${PRE_V0}"
echo "pre_growth_start_audio_packets=${PRE_A0}"
sleep 15
read -r PRE_V1 PRE_A1 < <(packet_counts)
echo "pre_growth_end_video_packets=${PRE_V1}"
echo "pre_growth_end_audio_packets=${PRE_A1}"
if (( PRE_V1 <= PRE_V0 || PRE_A1 <= PRE_A0 )); then
    echo "pre_reconnect_packet_growth=FAIL" >&2
    exit 9
fi
echo "pre_reconnect_packet_growth=PASS"

av_decode "pre_reconnect_av_decode" "$PRE_AV_LOG"

OLD_RELAY_PID="$(relay_pid)"
if [[ -z "$OLD_RELAY_PID" ]]; then
    echo "relay_process_discovery=FAIL" >&2
    tail -n 180 "$LOG" >&2 || true
    exit 10
fi
echo "relay_process_discovery=PASS"
echo "relay_restart_signal=SIGINT"
kill -INT "$OLD_RELAY_PID"

old_exited=0
for _ in $(seq 1 200); do
    if ! kill -0 "$OLD_RELAY_PID" 2>/dev/null; then
        old_exited=1
        break
    fi
    sleep 0.1
done
if [[ "$old_exited" != 1 ]]; then
    echo "old_relay_graceful_exit=FAIL" >&2
    exit 11
fi
echo "old_relay_graceful_exit=PASS"

NEW_RELAY_PID=""
for second in $(seq 1 45); do
    candidate="$(relay_pid)"
    if [[ -n "$candidate" && "$candidate" != "$OLD_RELAY_PID" ]] && source_ready; then
        NEW_RELAY_PID="$candidate"
        echo "go2rtc_source_reconnect=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "reconnect_wait_seconds=${second}"
        tail -n 12 "$LOG" | sed 's/^/[go2rtc-tail] /'
    fi
    sleep 1
done
if [[ -z "$NEW_RELAY_PID" ]]; then
    echo "go2rtc_source_reconnect=FAIL" >&2
    tail -n 220 "$LOG" >&2 || true
    exit 12
fi

# Give the replacement producer time to accumulate enough fresh media before
# validating both tracks again.
sleep 5
read -r POST_V0 POST_A0 < <(packet_counts)
echo "post_reconnect_initial_video_packets=${POST_V0}"
echo "post_reconnect_initial_audio_packets=${POST_A0}"
if (( POST_V0 < 5 || POST_A0 < 5 )); then
    echo "post_reconnect_media_resume=FAIL" >&2
    exit 13
fi
echo "post_reconnect_media_resume=PASS"

av_decode "post_reconnect_av_decode" "$POST_AV_LOG"

sleep 20
read -r POST_V1 POST_A1 < <(packet_counts)
echo "post_growth_end_video_packets=${POST_V1}"
echo "post_growth_end_audio_packets=${POST_A1}"
if (( POST_V1 <= POST_V0 || POST_A1 <= POST_A0 )); then
    echo "post_reconnect_packet_growth=FAIL" >&2
    exit 14
fi
echo "post_reconnect_packet_growth=PASS"

AUTH_COUNT="$(grep -c 'phase3g_tnp_auth=PASS' "$LOG" || true)"
DEINIT_COUNT="$(grep -c 'PPPP_DeInitialize_rc_hex=0x00000000' "$LOG" || true)"
echo "tnp_auth_pass_count=${AUTH_COUNT}"
echo "pppp_deinitialize_success_count=${DEINIT_COUNT}"
if (( AUTH_COUNT < 2 )); then
    echo "two_native_sessions_authenticated=FAIL" >&2
    exit 15
fi
echo "two_native_sessions_authenticated=PASS"
if (( DEINIT_COUNT < 1 )); then
    echo "first_session_clean_native_shutdown=FAIL" >&2
    exit 16
fi
echo "first_session_clean_native_shutdown=PASS"

echo "PHASE3I_STABILITY=PASS"
