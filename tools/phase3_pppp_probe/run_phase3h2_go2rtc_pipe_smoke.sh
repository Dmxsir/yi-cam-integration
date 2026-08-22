#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
GO2RTC="${GO2RTC:-$PROD_ROOT/.tools/go2rtc}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
FFPROBE="${FFPROBE:-ffprobe}"
FFMPEG="${FFMPEG:-ffmpeg}"
ENV_FILE="${1:-$PROD_ROOT/.env.local}"
RUNTIME="$ROOT/.analysis/phase3/bionic-root"
WORKER_DIR="$RUNTIME/data/local/tmp/yi-phase3g"
ANALYSIS_DIR="$ROOT/.analysis/phase3"
CONFIG="$ANALYSIS_DIR/go2rtc-phase3h2.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3h2.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3h2-stream.json"
PROBE_JSON="$ANALYSIS_DIR/go2rtc-phase3h2-ffprobe.json"
PROBE_ERR="$ANALYSIS_DIR/go2rtc-phase3h2-ffprobe.err"
API_PORT="${PHASE3H2_API_PORT:-11984}"
RTSP_PORT="${PHASE3H2_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_pipe.py"

for tool in "$GO2RTC" "$PYTHON" "$FFPROBE" "$FFMPEG" curl timeout ss; do
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
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$PROBE_JSON" "$PROBE_ERR"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3H2 port already in use: $port" >&2
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
  ${STREAM}: 'exec:${PYTHON} ${RELAY} --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ${FFMPEG} --ffprobe ${FFPROBE} --stdout#killsignal=2#killtimeout=20'
preload:
  ${STREAM}: "video&audio"
EOF
chmod 600 "$CONFIG"

echo "=== PHASE 3H2: EXPLICIT MPEG-TS PIPE PUMP TO go2rtc ==="
echo "production_go2rtc_service_touched=false"
echo "isolated_api=127.0.0.1:${API_PORT}"
echo "isolated_rtsp=127.0.0.1:${RTSP_PORT}"
echo "stream=${STREAM}"
echo "relay_stdout_mode=explicit_python_pump"
echo "preload=video&audio"

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

for _ in $(seq 1 100); do
    if curl -fsS --max-time 1 "http://127.0.0.1:${API_PORT}/" >/dev/null 2>&1; then
        echo "go2rtc_isolated_start=PASS"
        break
    fi
    sleep 0.1
done

API_URL="http://127.0.0.1:${API_PORT}/api/streams?src=${STREAM}"
source_ready=0
for second in $(seq 1 60); do
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    if "$PYTHON" - "$API_SNAPSHOT" <<'PY' >/dev/null 2>&1
import json, sys
try:
    obj = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(1)
for producer in obj.get("producers", []) or []:
    if producer.get("format_name") != "mpegts":
        continue
    text = "\n".join(str(x) for x in producer.get("medias", []))
    if "video, recvonly, H264" in text and "audio, recvonly, MPEG4-GENERIC/16000/1" in text:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
        source_ready=1
        echo "go2rtc_preload_source=PASS"
        break
    fi
    if (( second % 5 == 0 )); then
        echo "go2rtc_preload_wait_seconds=${second}"
        tail -n 12 "$LOG" | sed 's/^/[go2rtc-tail] /'
    fi
    sleep 1
done

if [[ "$source_ready" != 1 ]]; then
    echo "go2rtc_preload_source=FAIL" >&2
    echo "--- PASSIVE STREAM SNAPSHOT ---" >&2
    cat "$API_SNAPSHOT" >&2 || true
    echo "--- go2rtc LOG TAIL ---" >&2
    tail -n 220 "$LOG" >&2 || true
    echo "PHASE3H2_GO2RTC=FAIL" >&2
    exit 8
fi

RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"
set +e
timeout 30 "$FFPROBE" -v error -rtsp_transport tcp \
    -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
    -of json "$RTSP_URL" >"$PROBE_JSON" 2>"$PROBE_ERR"
PROBE_RC=$?
set -e
if [[ "$PROBE_RC" -ne 0 ]]; then
    echo "go2rtc_ffprobe_rc=$PROBE_RC" >&2
    tail -n 80 "$PROBE_ERR" >&2 || true
    tail -n 220 "$LOG" >&2 || true
    echo "PHASE3H2_GO2RTC=FAIL" >&2
    exit 9
fi

cat "$PROBE_JSON" | "$PYTHON" -c '
import json, sys
obj=json.load(sys.stdin); streams=obj.get("streams",[])
print("go2rtc_ffprobe="+json.dumps(streams,separators=(",",":"),sort_keys=True))
v=next((s for s in streams if s.get("codec_type")=="video"),None)
a=next((s for s in streams if s.get("codec_type")=="audio"),None)
ok=(v and v.get("codec_name")=="h264" and int(v.get("width",0))==1920 and int(v.get("height",0))==1080 and a and a.get("codec_name")=="aac" and str(a.get("sample_rate"))=="16000" and int(a.get("channels",0))==1)
print("go2rtc_tracks=PASS" if ok else "go2rtc_tracks=FAIL")
raise SystemExit(0 if ok else 1)
'

echo "go2rtc_decode_smoke=START"
timeout 25 "$FFMPEG" -hide_banner -loglevel error -rtsp_transport tcp -i "$RTSP_URL" -t 6 -map 0:v:0 -map 0:a:0 -f null -
echo "go2rtc_decode_smoke=PASS"
echo "--- go2rtc LOG TAIL ---"
tail -n 120 "$LOG" || true
echo "PHASE3H2_GO2RTC=PASS"
