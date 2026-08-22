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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3h3.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3h3.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3h3-stream.json"
CLIENT_LOG="$ANALYSIS_DIR/go2rtc-phase3h3-ffmpeg-video.log"
API_PORT="${PHASE3H3_API_PORT:-11984}"
RTSP_PORT="${PHASE3H3_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_pipe.py"

for tool in "$GO2RTC" "$PYTHON" "$FFMPEG" curl timeout ss; do
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
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$CLIENT_LOG"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3H3 port already in use: $port" >&2
        exit 4
    fi
done

cat >"$CONFIG" <<EOF
log:
  level: debug
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

echo "=== PHASE 3H3: RTSP PACKET-FLOW DIAGNOSTIC v2 ==="
echo "production_go2rtc_service_touched=false"
echo "stream=${STREAM}"
echo "goal=prove_real_rtsp_client_attachment_and_video_decode"
echo "ffmpeg_rw_timeout_option_used=false"

"$GO2RTC" -config "$CONFIG" >"$LOG" 2>&1 &
GO2RTC_PID=$!
cleanup() {
    if kill -0 "$GO2RTC_PID" 2>/dev/null; then
        kill -INT "$GO2RTC_PID" 2>/dev/null || true
        for _ in $(seq 1 60); do
            kill -0 "$GO2RTC_PID" 2>/dev/null || break
            sleep 0.1
        done
        kill -TERM "$GO2RTC_PID" 2>/dev/null || true
    fi
    wait "$GO2RTC_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ready=0
for _ in $(seq 1 100); do
    if curl -fsS --max-time 1 "http://127.0.0.1:${API_PORT}/" >/dev/null 2>&1; then
        ready=1
        echo "go2rtc_isolated_start=PASS"
        break
    fi
    sleep 0.1
done
if [[ "$ready" != 1 ]]; then
    echo "go2rtc_isolated_start=FAIL" >&2
    tail -n 120 "$LOG" >&2 || true
    exit 5
fi

API_URL="http://127.0.0.1:${API_PORT}/api/streams?src=${STREAM}"
source_ready=0
for second in $(seq 1 30); do
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    if "$PYTHON" - "$API_SNAPSHOT" <<'PY' >/dev/null 2>&1
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception:
    raise SystemExit(1)
for p in obj.get('producers',[]) or []:
    if p.get('format_name')=='mpegts' and len(p.get('receivers',[]) or []) >= 2:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
        source_ready=1
        echo "go2rtc_preload_source=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "source_wait_seconds=${second}"
    fi
    sleep 1
done
if [[ "$source_ready" != 1 ]]; then
    echo "go2rtc_preload_source=FAIL" >&2
    tail -n 160 "$LOG" >&2 || true
    exit 8
fi

snapshot_summary() {
    local label="$1"
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    "$PYTHON" - "$API_SNAPSHOT" "$label" <<'PY'
import json, sys
path,label=sys.argv[1:3]
try:
    obj=json.load(open(path,encoding='utf-8'))
except Exception as exc:
    print(f"flow[{label}]=snapshot_error:{type(exc).__name__}")
    raise SystemExit(0)
producers=obj.get('producers',[]) or []
consumers=obj.get('consumers',[]) or []
recv=[]
for p in producers:
    if p.get('format_name')!='mpegts':
        continue
    for r in p.get('receivers',[]) or []:
        c=r.get('codec') or {}
        recv.append((c.get('codec_name'),int(r.get('packets',0) or 0),int(r.get('bytes',0) or 0),len(r.get('childs',[]) or [])))
send=[]
for c in consumers:
    for s in c.get('senders',[]) or []:
        cc=s.get('codec') or {}
        send.append((cc.get('codec_name'),int(s.get('packets',0) or 0),int(s.get('bytes',0) or 0),int(s.get('drops',0) or 0)))
print(f"flow[{label}].producer_receivers={recv}")
print(f"flow[{label}].consumer_count={len(consumers)}")
print(f"flow[{label}].consumer_senders={send}")
PY
}

consumer_count() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json, sys
try:
    obj=json.load(open(sys.argv[1],encoding='utf-8'))
    print(len(obj.get('consumers',[]) or []))
except Exception:
    print(0)
PY
}

snapshot_summary "baseline0"
sleep 2
snapshot_summary "baseline2s"
BASELINE_CONSUMERS="$(consumer_count)"
echo "baseline_consumer_count=${BASELINE_CONSUMERS}"

echo "rtsp_video_client=START"
RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"
# The previous Phase 3H3 used -rw_timeout, but this installed FFmpeg build does
# not expose that input option. The outer GNU timeout already bounds the test,
# so use only portable RTSP/FFmpeg options here.
set +e
timeout 15 "$FFMPEG" \
    -hide_banner -nostdin -loglevel info -stats_period 1 \
    -rtsp_transport tcp \
    -probesize 1000000 -analyzeduration 1000000 \
    -i "$RTSP_URL" \
    -map 0:v:0 -an -frames:v 30 -f null - \
    >/dev/null 2>"$CLIENT_LOG" &
CLIENT_PID=$!
set -e

MAX_CONSUMERS="$BASELINE_CONSUMERS"
CLIENT_ATTACHED=0
for second in $(seq 1 12); do
    sleep 1
    snapshot_summary "client_${second}s"
    CURRENT_CONSUMERS="$(consumer_count)"
    if (( CURRENT_CONSUMERS > MAX_CONSUMERS )); then
        MAX_CONSUMERS="$CURRENT_CONSUMERS"
    fi
    if (( CURRENT_CONSUMERS > BASELINE_CONSUMERS )); then
        CLIENT_ATTACHED=1
    fi
    if ! kill -0 "$CLIENT_PID" 2>/dev/null; then
        break
    fi
done

set +e
wait "$CLIENT_PID"
CLIENT_RC=$?
set -e

echo "rtsp_video_client_rc=$CLIENT_RC"
echo "rtsp_client_attached=${CLIENT_ATTACHED}"
echo "max_consumer_count=${MAX_CONSUMERS}"
echo "--- FFMPEG CLIENT LOG TAIL ---"
tail -n 120 "$CLIENT_LOG" || true
echo "--- go2rtc LOG TAIL ---"
tail -n 180 "$LOG" || true

"$PYTHON" - "$CLIENT_LOG" "$CLIENT_RC" "$CLIENT_ATTACHED" <<'PY'
import re, sys
path, rc_s, attached_s = sys.argv[1:4]
text=open(path,encoding='utf-8',errors='replace').read() if __import__('os').path.exists(path) else ''
frame_hits=[int(x) for x in re.findall(r'frame=\s*(\d+)', text)]
max_frame=max(frame_hits) if frame_hits else 0
rc=int(rc_s)
attached=int(attached_s)
print(f"ffmpeg_max_reported_frame={max_frame}")
if rc == 0:
    print('phase3h3_classification=RTSP_VIDEO_DECODE_PASS')
    print('PHASE3H3_DIAG=PASS')
elif attached:
    print('phase3h3_classification=RTSP_CLIENT_ATTACHED_BUT_30_FRAMES_NOT_DECODED')
    print('PHASE3H3_DIAG=PASS')
else:
    print('phase3h3_classification=RTSP_CLIENT_DID_NOT_ATTACH')
    print('PHASE3H3_DIAG=PASS')
PY
