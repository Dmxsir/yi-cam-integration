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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3j2.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3j2.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3j2-stream.json"
DECODE_LOG="$ANALYSIS_DIR/go2rtc-phase3j2-decode.log"
EXIT_MARKER="$ANALYSIS_DIR/phase3j2-relay-exit.marker"
API_PORT="${PHASE3J2_API_PORT:-11984}"
RTSP_PORT="${PHASE3J2_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_pipe.py"

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

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$DECODE_LOG" "$EXIT_MARKER"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3J2 port already in use: $port" >&2
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
  ${STREAM}: 'exec:/usr/bin/env YI_PHASE3_EXIT_MARKER=${EXIT_MARKER} ${PYTHON} ${RELAY} --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ${FFMPEG} --ffprobe ffprobe --stdout#killsignal=2#killtimeout=20'
preload:
  ${STREAM}: "video&audio"
EOF
chmod 600 "$CONFIG"

echo "=== PHASE 3J2: PARENT go2rtc SHUTDOWN VALIDATION ==="
echo "production_go2rtc_service_touched=false"
echo "stream=${STREAM}"
echo "shutdown_trigger=SIGINT_to_isolated_go2rtc"
echo "relay_exit_observation=external_safe_marker"

"$GO2RTC" -config "$CONFIG" >"$LOG" 2>&1 &
GO2RTC_PID=$!
STOPPED=0

cleanup() {
    if [[ "$STOPPED" == 1 ]]; then
        return
    fi
    STOPPED=1
    if kill -0 "$GO2RTC_PID" 2>/dev/null; then
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

source_state() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || return 1
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
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
print(video[0], video[1], audio[0], audio[1])
PY
}

READY=0
for second in $(seq 1 40); do
    if STATE="$(source_state 2>/dev/null)"; then
        READY=1
        echo "parent_shutdown_source_ready=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "source_ready_wait_seconds=${second}"
    fi
    sleep 1
done
if [[ "$READY" != 1 ]]; then
    echo "parent_shutdown_source_ready=FAIL" >&2
    tail -n 180 "$LOG" >&2 || true
    exit 5
fi

read -r V_ID V0 A_ID A0 <<<"$STATE"
sleep 10
read -r V_ID2 V1 A_ID2 A1 <<<"$(source_state)"
echo "pre_shutdown_video_packets_start=${V0}"
echo "pre_shutdown_video_packets_end=${V1}"
echo "pre_shutdown_audio_packets_start=${A0}"
echo "pre_shutdown_audio_packets_end=${A1}"
if [[ "$V_ID2" != "$V_ID" || "$A_ID2" != "$A_ID" ]] || (( V1 <= V0 || A1 <= A0 )); then
    echo "pre_shutdown_packet_growth=FAIL" >&2
    exit 6
fi
echo "pre_shutdown_packet_growth=PASS"

set +e
timeout 12 "$FFMPEG" \
    -hide_banner -nostdin -loglevel error \
    -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 \
    -i "$RTSP_URL" -t 2 -map 0:v:0 -map 0:a:0 -f null - \
    >/dev/null 2>"$DECODE_LOG"
DECODE_RC=$?
set -e
echo "pre_shutdown_av_decode_rc=${DECODE_RC}"
if [[ "$DECODE_RC" -ne 0 ]]; then
    echo "pre_shutdown_av_decode=FAIL" >&2
    tail -n 100 "$DECODE_LOG" >&2 || true
    exit 7
fi
echo "pre_shutdown_av_decode=PASS"

RELAY_PID="$(pgrep -P "$GO2RTC_PID" -f 'yi_native_av_relay_pipe.py' | head -n 1 || true)"
if [[ -z "$RELAY_PID" ]]; then
    # With /usr/bin/env as argv[0], Linux may expose the relay as a descendant
    # rather than an immediate child. Restrict discovery to this unique marker.
    RELAY_PID="$(pgrep -f "yi_native_av_relay_pipe.py.*YI_PHASE3_EXIT_MARKER=${EXIT_MARKER}" | head -n 1 || true)"
fi
if [[ -z "$RELAY_PID" ]]; then
    # Final safe fallback: the isolated go2rtc config carries a unique marker,
    # so match both relay path and env marker in /proc command lines.
    RELAY_PID="$(pgrep -f "yi_native_av_relay_pipe.py.*phase3j2-relay-exit.marker" | head -n 1 || true)"
fi
if [[ -z "$RELAY_PID" ]]; then
    echo "relay_process_discovery=FAIL" >&2
    tail -n 160 "$LOG" >&2 || true
    exit 8
fi
echo "relay_process_discovery=PASS"
echo "relay_pid_detected=true"

mapfile -t DESCENDANTS < <(pgrep -P "$RELAY_PID" || true)
echo "relay_direct_child_count=${#DESCENDANTS[@]}"

echo "go2rtc_parent_shutdown_signal=SIGINT"
kill -INT "$GO2RTC_PID"

GO2RTC_EXITED=0
for _ in $(seq 1 120); do
    if ! kill -0 "$GO2RTC_PID" 2>/dev/null; then
        GO2RTC_EXITED=1
        break
    fi
    sleep 0.1
done
if [[ "$GO2RTC_EXITED" != 1 ]]; then
    echo "isolated_go2rtc_exit=FAIL" >&2
    exit 9
fi
wait "$GO2RTC_PID" 2>/dev/null || true
STOPPED=1
echo "isolated_go2rtc_exit=PASS"

MARKER_READY=0
for second in $(seq 1 30); do
    if [[ -s "$EXIT_MARKER" ]]; then
        MARKER_READY=1
        echo "relay_post_parent_exit_marker=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "relay_exit_marker_wait_seconds=${second}"
    fi
    sleep 1
done
if [[ "$MARKER_READY" != 1 ]]; then
    echo "relay_post_parent_exit_marker=FAIL" >&2
    ps -eo pid,ppid,stat,args | grep -E 'yi_native_av_relay_pipe.py|qemu-aarch64.*android_pppp_av_stream' | grep -v grep >&2 || true
    exit 10
fi

MARKER_VALUE="$(tr -d '\r\n' <"$EXIT_MARKER")"
echo "relay_exit_marker_value=${MARKER_VALUE}"
if [[ "$MARKER_VALUE" != "relay_exit_rc=0" ]]; then
    echo "relay_internal_shutdown=FAIL" >&2
    exit 11
fi
echo "relay_internal_shutdown=PASS"

if kill -0 "$RELAY_PID" 2>/dev/null; then
    echo "relay_process_exit_after_parent=FAIL" >&2
    exit 12
fi
echo "relay_process_exit_after_parent=PASS"

ORPHAN=0
for pid in "${DESCENDANTS[@]}"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        ORPHAN=1
        echo "orphan_child_pid_detected=true" >&2
    fi
done
if [[ "$ORPHAN" == 1 ]]; then
    echo "relay_children_exit_after_parent=FAIL" >&2
    exit 13
fi
echo "relay_children_exit_after_parent=PASS"

echo "PHASE3J2_PARENT_SHUTDOWN=PASS"
