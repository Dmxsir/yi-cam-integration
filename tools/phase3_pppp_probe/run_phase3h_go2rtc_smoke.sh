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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3h.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3h.log"
PROBE_ERR="$ANALYSIS_DIR/go2rtc-phase3h-ffprobe.err"
PROBE_JSON_FILE="$ANALYSIS_DIR/go2rtc-phase3h-ffprobe.json"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3h-stream.json"
API_PORT="${PHASE3H_API_PORT:-11984}"
RTSP_PORT="${PHASE3H_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"

for tool in "$GO2RTC" "$PYTHON" "$FFPROBE" "$FFMPEG" curl timeout ss; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done

for f in \
    "$ENV_FILE" \
    "$ROOT/yi_native_av_relay.py" \
    "$WORKER_DIR/android_pppp_av_stream" \
    "$WORKER_DIR/libPPPP_API.so" \
    "$RUNTIME/system/bin/linker64"; do
    if [[ ! -f "$f" ]]; then
        echo "ERROR: required Phase 3G artifact missing: $f" >&2
        echo "Run the Phase 3G native A/V smoke first, then retry Phase 3H." >&2
        exit 3
    fi
done

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$PROBE_ERR" "$PROBE_JSON_FILE" "$API_SNAPSHOT"

# Keep this instance isolated from the production go2rtc service. The
# production defaults (1984/8554/8555) are never used here.
for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3H port is already in use: $port" >&2
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
  ${STREAM}: 'exec:${PYTHON} ${ROOT}/yi_native_av_relay.py --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ${FFMPEG} --ffprobe ${FFPROBE} --stdout#killsignal=2#killtimeout=20#starttimeout=45'
preload:
  ${STREAM}: "video&audio"
EOF
chmod 600 "$CONFIG"

echo "=== PHASE 3H: ISOLATED go2rtc LIVE H264 + AAC SMOKE ==="
echo "production_go2rtc_service_touched=false"
echo "isolated_api=127.0.0.1:${API_PORT}"
echo "isolated_rtsp=127.0.0.1:${RTSP_PORT}"
echo "stream=${STREAM}"
echo "source=phoneless_native_PPPP_TNP"
echo "expected_video=H264/1920x1080"
echo "expected_audio=AAC/16000/mono"
echo "transcoding_in_relay=false"
echo "isolated_preload=video&audio"
echo

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

ready=0
for _ in $(seq 1 100); do
    if ! kill -0 "$GO2RTC_PID" 2>/dev/null; then
        echo "ERROR: isolated go2rtc exited during startup" >&2
        tail -n 160 "$LOG" >&2 || true
        exit 5
    fi
    if curl -fsS --max-time 1 "http://127.0.0.1:${API_PORT}/" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.1
done
if [[ "$ready" != 1 ]]; then
    echo "ERROR: isolated go2rtc API did not become ready" >&2
    tail -n 160 "$LOG" >&2 || true
    exit 6
fi

echo "go2rtc_isolated_start=PASS"

rtsp_ready=0
for _ in $(seq 1 50); do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$RTSP_PORT$"; then
        rtsp_ready=1
        break
    fi
    sleep 0.1
done
if [[ "$rtsp_ready" != 1 ]]; then
    echo "go2rtc_rtsp_listener=FAIL" >&2
    echo "ERROR: isolated RTSP listener did not bind to port ${RTSP_PORT}" >&2
    tail -n 160 "$LOG" >&2 || true
    exit 7
fi
echo "go2rtc_rtsp_listener=PASS"

RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"
API_URL="http://127.0.0.1:${API_PORT}/api/streams?src=${STREAM}"

# The previous diagnostic used video=all&audio=all here. That creates a real
# temporary probe consumer; once curl returns, go2rtc immediately tears down
# the exec producer. Starting ffprobe right after that can race the PPPP/TNP
# shutdown. Phase 3H now mirrors production behavior instead: a preload
# consumer owns the source for the whole test, and this polling GET contains no
# media selectors, so it only observes state and never changes producer life.
source_ready=0
API_HTTP=000
for _ in $(seq 1 450); do
    API_HTTP="$(curl -sS --max-time 1 -o "$API_SNAPSHOT" -w '%{http_code}' "$API_URL" || true)"
    if [[ "$API_HTTP" == 200 ]] && "$PYTHON" - "$API_SNAPSHOT" <<'PY' >/dev/null 2>&1
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
producers = obj.get("producers", []) if isinstance(obj, dict) else []
for producer in producers:
    if not isinstance(producer, dict) or producer.get("format_name") != "mpegts":
        continue
    medias = producer.get("medias", [])
    text = "\n".join(str(item) for item in medias)
    if "video, recvonly, H264" in text and "audio, recvonly, MPEG4-GENERIC/16000/1" in text:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
        source_ready=1
        break
    fi
    sleep 0.1
done

echo "go2rtc_stream_api_http=${API_HTTP:-000}"
if [[ "$source_ready" != 1 ]]; then
    echo "go2rtc_preload_source=FAIL" >&2
    if [[ -s "$API_SNAPSHOT" ]]; then
        echo "--- PASSIVE go2rtc STREAM SNAPSHOT ---" >&2
        cat "$API_SNAPSHOT" >&2 || true
    fi
    echo "--- ISOLATED go2rtc LOG TAIL ---" >&2
    tail -n 220 "$LOG" >&2 || true
    echo "PHASE3H_GO2RTC=FAIL" >&2
    exit 8
fi
echo "go2rtc_preload_source=PASS"

set +e
timeout 45 "$FFPROBE" \
    -v error \
    -rtsp_transport tcp \
    -analyzeduration 8000000 \
    -probesize 8000000 \
    -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
    -of json \
    "$RTSP_URL" >"$PROBE_JSON_FILE" 2>"$PROBE_ERR"
PROBE_RC=$?
set -e

if [[ "$PROBE_RC" -ne 0 ]]; then
    echo "go2rtc_ffprobe_rc=$PROBE_RC" >&2
    if [[ "$PROBE_RC" -eq 124 ]]; then
        echo "go2rtc_ffprobe_failure=TIMEOUT" >&2
    else
        echo "go2rtc_ffprobe_failure=ERROR" >&2
    fi
    curl -sS --max-time 2 -o "$API_SNAPSHOT" "$API_URL" || true
    if [[ -s "$PROBE_ERR" ]]; then
        echo "--- FFPROBE STDERR ---" >&2
        tail -n 120 "$PROBE_ERR" >&2 || true
    fi
    if [[ -s "$API_SNAPSHOT" ]]; then
        echo "--- PASSIVE go2rtc STREAM SNAPSHOT ---" >&2
        "$PYTHON" - "$API_SNAPSHOT" <<'PY' >&2 || true
import json, sys
try:
    obj = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:16000])
except Exception as exc:
    print(f"snapshot_parse_error={type(exc).__name__}")
PY
    fi
    echo "--- ISOLATED go2rtc LOG TAIL ---" >&2
    tail -n 260 "$LOG" >&2 || true
    echo "PHASE3H_GO2RTC=FAIL" >&2
    exit 9
fi

PROBE_JSON="$(cat "$PROBE_JSON_FILE")"
printf '%s' "$PROBE_JSON" | "$PYTHON" -c '
import json, sys
obj = json.load(sys.stdin)
streams = obj.get("streams", [])
video = next((s for s in streams if s.get("codec_type") == "video"), None)
audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
print("go2rtc_ffprobe=" + json.dumps(streams, separators=(",", ":"), sort_keys=True))
ok = (
    video is not None
    and video.get("codec_name") == "h264"
    and int(video.get("width", 0)) == 1920
    and int(video.get("height", 0)) == 1080
    and audio is not None
    and audio.get("codec_name") == "aac"
    and str(audio.get("sample_rate")) == "16000"
    and int(audio.get("channels", 0)) == 1
)
print("go2rtc_tracks=PASS" if ok else "go2rtc_tracks=FAIL")
raise SystemExit(0 if ok else 1)
'

echo "go2rtc_decode_smoke=START"
set +e
timeout 30 "$FFMPEG" \
    -hide_banner \
    -loglevel error \
    -rtsp_transport tcp \
    -i "$RTSP_URL" \
    -t 8 \
    -map 0:v:0 \
    -map 0:a:0 \
    -f null -
DECODE_RC=$?
set -e
if [[ "$DECODE_RC" -ne 0 ]]; then
    echo "go2rtc_decode_smoke=FAIL" >&2
    echo "go2rtc_decode_rc=$DECODE_RC" >&2
    curl -sS --max-time 2 -o "$API_SNAPSHOT" "$API_URL" || true
    if [[ -s "$API_SNAPSHOT" ]]; then
        echo "--- PASSIVE go2rtc STREAM SNAPSHOT ---" >&2
        cat "$API_SNAPSHOT" >&2 || true
    fi
    echo "--- ISOLATED go2rtc LOG TAIL ---" >&2
    tail -n 260 "$LOG" >&2 || true
    echo "PHASE3H_GO2RTC=FAIL" >&2
    exit 10
fi
echo "go2rtc_decode_smoke=PASS"

echo "--- ISOLATED go2rtc LOG TAIL ---"
tail -n 120 "$LOG" || true

echo "PHASE3H_GO2RTC=PASS"
