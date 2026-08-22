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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3l.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3l.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3l-stream.json"
DECODE_LOG="$ANALYSIS_DIR/go2rtc-phase3l-decode.log"
EXIT_MARKER="$ANALYSIS_DIR/phase3l-relay-exit.marker"
API_PORT="${PHASE3L_API_PORT:-11984}"
RTSP_PORT="${PHASE3L_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay.py"
REFERENCE="$ROOT/yi_native_av_relay_integrated.py"

for tool in "$GO2RTC" "$PYTHON" "$FFMPEG" curl timeout ss pgrep cmp; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done
for f in "$ENV_FILE" "$RELAY" "$REFERENCE" "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so" "$RUNTIME/system/bin/linker64"; do
    [[ -f "$f" ]] || { echo "ERROR: required file missing: $f" >&2; exit 3; }
done

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$DECODE_LOG" "$EXIT_MARKER"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3L port already in use: $port" >&2
        exit 4
    fi
done

"$PYTHON" -m py_compile "$RELAY"
echo "final_relay_python_compile=PASS"
if cmp -s "$RELAY" "$REFERENCE"; then
    echo "final_relay_exact_integrated_blob=PASS"
else
    echo "final_relay_exact_integrated_blob=FAIL" >&2
    exit 5
fi

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

echo "=== PHASE 3L: FINAL-NAME NATIVE RELAY SMOKE ==="
echo "production_go2rtc_service_touched=false"
echo "relay=yi_native_av_relay.py"
echo "reference=exact_blob_previously_passed_phase3k2"

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

source_state() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || return 1
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json,sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    raise SystemExit(1)
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts':
        continue
    v=a=None
    for r in p.get('receivers',[]) or []:
        codec=(r.get('codec') or {}).get('codec_name')
        row=(int(r.get('id',0) or 0),int(r.get('packets',0) or 0))
        if codec=='h264': v=row
        elif codec=='aac': a=row
    if v and a:
        print(v[0],v[1],a[0],a[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

READY=0
for second in $(seq 1 40); do
    if STATE="$(source_state 2>/dev/null)"; then
        READY=1
        echo "final_source_ready=PASS"
        break
    fi
    if (( second % 5 == 0 )); then echo "source_ready_wait_seconds=${second}"; fi
    sleep 1
done
[[ "$READY" == 1 ]] || { echo "final_source_ready=FAIL" >&2; tail -n 180 "$LOG" >&2; exit 6; }

read -r V_ID V0 A_ID A0 <<<"$STATE"
sleep 6
read -r V_ID2 V1 A_ID2 A1 <<<"$(source_state)"
if [[ "$V_ID" == "$V_ID2" && "$A_ID" == "$A_ID2" ]] && (( V1 > V0 && A1 > A0 )); then
    echo "final_packet_growth=PASS"
else
    echo "final_packet_growth=FAIL" >&2
    exit 7
fi

set +e
timeout 15 "$FFMPEG" \
    -hide_banner -nostdin -loglevel error \
    -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 \
    -i "$RTSP_URL" -t 3 \
    -map 0:v:0 -map 0:a:0 -f null - \
    >/dev/null 2>"$DECODE_LOG"
DECODE_RC=$?
set -e
echo "final_av_decode_rc=${DECODE_RC}"
[[ "$DECODE_RC" -eq 0 ]] || { echo "final_av_decode=FAIL" >&2; tail -n 100 "$DECODE_LOG" >&2; exit 8; }
echo "final_av_decode=PASS"

RELAY_PID="$(pgrep -P "$GO2RTC_PID" -f 'yi_native_av_relay.py' | head -n 1 || true)"
[[ -n "$RELAY_PID" ]] || { echo "final_relay_process_discovery=FAIL" >&2; exit 9; }
echo "final_relay_process_discovery=PASS"
mapfile -t CHILDREN < <(pgrep -P "$RELAY_PID" || true)

rm -f "$EXIT_MARKER"
echo "final_parent_shutdown_signal=SIGINT"
kill -INT "$GO2RTC_PID"
for _ in $(seq 1 120); do
    ! kill -0 "$GO2RTC_PID" 2>/dev/null && break
    sleep 0.1
done
! kill -0 "$GO2RTC_PID" 2>/dev/null || { echo "final_go2rtc_exit=FAIL" >&2; exit 10; }
wait "$GO2RTC_PID" 2>/dev/null || true
STOPPED=1
echo "final_go2rtc_exit=PASS"

MARKER=0
for second in $(seq 1 30); do
    if [[ -s "$EXIT_MARKER" ]]; then MARKER=1; break; fi
    sleep 1
done
[[ "$MARKER" == 1 ]] || { echo "final_parent_exit_marker=FAIL" >&2; exit 11; }
VALUE="$(tr -d '\r\n' <"$EXIT_MARKER")"
echo "final_parent_exit_marker_value=${VALUE}"
[[ "$VALUE" == "relay_exit_rc=0" ]] || { echo "final_parent_shutdown_cleanup=FAIL" >&2; exit 12; }

# The safe exit marker is written from the relay's finalizer immediately before
# SystemExit. On a fast parent shutdown there is a small process-table race:
# the marker may be visible a few milliseconds before the relay PID disappears.
# Wait for actual process exit instead of sampling kill -0 only once.
RELAY_GONE=0
for tick in $(seq 1 50); do
    if ! kill -0 "$RELAY_PID" 2>/dev/null; then
        RELAY_GONE=1
        echo "final_relay_exit_wait_ms=$(( (tick - 1) * 100 ))"
        break
    fi
    sleep 0.1
done
[[ "$RELAY_GONE" == 1 ]] || { echo "final_relay_exit_after_parent=FAIL" >&2; exit 13; }
echo "final_relay_exit_after_parent=PASS"

# Direct children were captured before shutdown. Give them the same bounded
# grace period so a normal qemu/FFmpeg exit is not mistaken for an orphan.
for pid in "${CHILDREN[@]}"; do
    [[ -z "$pid" ]] && continue
    CHILD_GONE=0
    for _ in $(seq 1 50); do
        if ! kill -0 "$pid" 2>/dev/null; then
            CHILD_GONE=1
            break
        fi
        sleep 0.1
    done
    [[ "$CHILD_GONE" == 1 ]] || { echo "final_orphan_child=FAIL" >&2; exit 14; }
done

echo "final_children_exit_after_parent=PASS"
echo "final_parent_shutdown_cleanup=PASS"
echo "PHASE3L_FINAL_RELAY=PASS"
