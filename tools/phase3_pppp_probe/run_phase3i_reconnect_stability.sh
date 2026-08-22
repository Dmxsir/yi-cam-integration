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
        echo "ERROR: isolated Phase 3I port is already in use: $port" >&2
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

echo "=== PHASE 3I: GENERATION-AWARE NATIVE A/V RECONNECT + STABILITY ==="
echo "production_go2rtc_service_touched=false"
echo "stream=${STREAM}"
echo "source=phoneless_native_PPPP_TNP"
echo "preload=video&audio"
echo "counter_validation=receiver_id_generation_aware"

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

# Output: VIDEO_RECEIVER_ID VIDEO_PACKETS AUDIO_RECEIVER_ID AUDIO_PACKETS
receiver_state() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    print('0 0 0 0')
    raise SystemExit(0)
v_id=v_n=a_id=a_n=0
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts':
        continue
    for r in p.get('receivers',[]) or []:
        codec=(r.get('codec') or {}).get('codec_name')
        rid=int(r.get('id',0) or 0)
        packets=int(r.get('packets',0) or 0)
        if codec=='h264':
            v_id, v_n = rid, packets
        elif codec=='aac':
            a_id, a_n = rid, packets
print(v_id, v_n, a_id, a_n)
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

wait_for_log_count() {
    local pattern="$1" wanted="$2" label="$3" limit="$4"
    for second in $(seq 1 "$limit"); do
        local count
        count="$(grep -c "$pattern" "$LOG" || true)"
        if (( count >= wanted )); then
            echo "${label}=PASS"
            return 0
        fi
        if (( second % 5 == 0 )); then
            echo "${label}_wait_seconds=${second}"
        fi
        sleep 1
    done
    echo "${label}=FAIL" >&2
    tail -n 180 "$LOG" >&2 || true
    return 1
}

wait_source "initial_source_ready" 35

read -r PRE_VID PRE_V0 PRE_AID PRE_A0 < <(receiver_state)
echo "pre_generation_video_receiver_id=${PRE_VID}"
echo "pre_generation_audio_receiver_id=${PRE_AID}"
echo "pre_growth_start_video_packets=${PRE_V0}"
echo "pre_growth_start_audio_packets=${PRE_A0}"
sleep 12
read -r PRE_VID1 PRE_V1 PRE_AID1 PRE_A1 < <(receiver_state)
echo "pre_growth_end_video_packets=${PRE_V1}"
echo "pre_growth_end_audio_packets=${PRE_A1}"
if [[ "$PRE_VID1" != "$PRE_VID" || "$PRE_AID1" != "$PRE_AID" ]] || (( PRE_V1 <= PRE_V0 || PRE_A1 <= PRE_A0 )); then
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
echo "old_relay_pid_detected=true"
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
    if [[ -n "$candidate" && "$candidate" != "$OLD_RELAY_PID" ]]; then
        NEW_RELAY_PID="$candidate"
        echo "replacement_relay_process=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "replacement_relay_wait_seconds=${second}"
        tail -n 10 "$LOG" | sed 's/^/[go2rtc-tail] /'
    fi
    sleep 1
done
if [[ -z "$NEW_RELAY_PID" ]]; then
    echo "replacement_relay_process=FAIL" >&2
    tail -n 220 "$LOG" >&2 || true
    exit 12
fi

# Do not use producer packet counters until the replacement PPPP/TNP session is
# authenticated. go2rtc keeps the old receiver nodes visible while reconnect()
# is preparing the replacement and then swaps in fresh Receiver objects. Their
# counters restart from zero, so comparing across that swap is a false failure.
wait_for_log_count 'phase3g_tnp_auth=PASS' 2 "second_native_session_authenticated" 35
wait_for_log_count 'PPPP_DeInitialize_rc_hex=0x00000000' 1 "first_session_clean_native_shutdown" 20

# Wait until go2rtc has actually swapped receiver generations. The new receiver
# IDs are the boundary that makes packet counters comparable again.
GENERATION_CHANGED=0
for second in $(seq 1 35); do
    read -r POST_VID POST_V0 POST_AID POST_A0 < <(receiver_state)
    if (( POST_VID > 0 && POST_AID > 0 && POST_V0 >= 5 && POST_A0 >= 5 )) \
       && [[ "$POST_VID" != "$PRE_VID" && "$POST_AID" != "$PRE_AID" ]]; then
        GENERATION_CHANGED=1
        echo "go2rtc_receiver_generation_swap=PASS"
        echo "post_generation_video_receiver_id=${POST_VID}"
        echo "post_generation_audio_receiver_id=${POST_AID}"
        echo "post_reconnect_initial_video_packets=${POST_V0}"
        echo "post_reconnect_initial_audio_packets=${POST_A0}"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "receiver_generation_swap_wait_seconds=${second}"
    fi
    sleep 1
done
if [[ "$GENERATION_CHANGED" != 1 ]]; then
    echo "go2rtc_receiver_generation_swap=FAIL" >&2
    tail -n 220 "$LOG" >&2 || true
    exit 13
fi

echo "go2rtc_source_reconnect=PASS"
echo "post_reconnect_media_resume=PASS"

# Prove growth inside one receiver generation before and after an A/V consumer.
sleep 5
read -r POST_VID_A POST_VA POST_AID_A POST_AA < <(receiver_state)
if [[ "$POST_VID_A" != "$POST_VID" || "$POST_AID_A" != "$POST_AID" ]] || (( POST_VA <= POST_V0 || POST_AA <= POST_A0 )); then
    echo "post_reconnect_settle_growth=FAIL" >&2
    exit 14
fi
echo "post_reconnect_settle_growth=PASS"

av_decode "post_reconnect_av_decode" "$POST_AV_LOG"

read -r GROW_VID0 GROW_V0 GROW_AID0 GROW_A0 < <(receiver_state)
echo "post_growth_baseline_video_packets=${GROW_V0}"
echo "post_growth_baseline_audio_packets=${GROW_A0}"
sleep 15
read -r GROW_VID1 GROW_V1 GROW_AID1 GROW_A1 < <(receiver_state)
echo "post_growth_end_video_packets=${GROW_V1}"
echo "post_growth_end_audio_packets=${GROW_A1}"
if [[ "$GROW_VID1" != "$GROW_VID0" || "$GROW_AID1" != "$GROW_AID0" ]]; then
    echo "post_reconnect_packet_growth=FAIL_RECEIVER_GENERATION_CHANGED_AGAIN" >&2
    exit 15
fi
if (( GROW_V1 <= GROW_V0 || GROW_A1 <= GROW_A0 )); then
    echo "post_reconnect_packet_growth=FAIL" >&2
    exit 16
fi
echo "post_reconnect_packet_growth=PASS"

AUTH_COUNT="$(grep -c 'phase3g_tnp_auth=PASS' "$LOG" || true)"
DEINIT_COUNT="$(grep -c 'PPPP_DeInitialize_rc_hex=0x00000000' "$LOG" || true)"
echo "tnp_auth_pass_count=${AUTH_COUNT}"
echo "pppp_deinitialize_success_count=${DEINIT_COUNT}"
if (( AUTH_COUNT < 2 )); then
    echo "two_native_sessions_authenticated=FAIL" >&2
    exit 17
fi
echo "two_native_sessions_authenticated=PASS"
if (( DEINIT_COUNT < 1 )); then
    echo "first_session_clean_native_shutdown=FAIL" >&2
    exit 18
fi

echo "first_session_clean_native_shutdown=PASS"
echo "PHASE3I_STABILITY=PASS"
