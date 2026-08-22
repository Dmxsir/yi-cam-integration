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
API_PORT="${PHASE3H_API_PORT:-11984}"
RTSP_PORT="${PHASE3H_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"

for tool in "$GO2RTC" "$PYTHON" "$FFPROBE" "$FFMPEG" curl timeout; do
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
rm -f "$CONFIG" "$LOG"

# Keep this instance isolated from the production go2rtc service. The
# production defaults (1984/8554/8555) are never used here.
for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3H port is already in use: $port" >&2
        exit 4
    fi
done

cat >"$CONFIG" <<EOF
api:
  listen: "127.0.0.1:${API_PORT}"
rtsp:
  listen: "127.0.0.1:${RTSP_PORT}"
webrtc:
  listen: ""
streams:
  ${STREAM}: 'exec:${PYTHON} ${ROOT}/yi_native_av_relay.py --env-file ${ENV_FILE} --runtime ${RUNTIME} --worker-dir ${WORKER_DIR} --qemu qemu-aarch64 --ffmpeg ${FFMPEG} --ffprobe ${FFPROBE} --stdout#killsignal=2#killtimeout=20#starttimeout=45'
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
echo

"$GO2RTC" -config "$CONFIG" >"$LOG" 2>&1 &
GO2RTC_PID=$!

cleanup() {
    if kill -0 "$GO2RTC_PID" 2>/dev/null; then
        kill -INT "$GO2RTC_PID" 2>/dev/null || true
        for _ in $(seq 1 40); do
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
        tail -n 80 "$LOG" >&2 || true
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
    tail -n 80 "$LOG" >&2 || true
    exit 6
fi

echo "go2rtc_isolated_start=PASS"
RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"

PROBE_JSON="$(timeout 45 "$FFPROBE" \
    -v error \
    -rtsp_transport tcp \
    -analyzeduration 8000000 \
    -probesize 8000000 \
    -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
    -of json \
    "$RTSP_URL")"

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
timeout 30 "$FFMPEG" \
    -hide_banner \
    -loglevel error \
    -rtsp_transport tcp \
    -i "$RTSP_URL" \
    -t 8 \
    -map 0:v:0 \
    -map 0:a:0 \
    -f null -
echo "go2rtc_decode_smoke=PASS"

echo "--- ISOLATED go2rtc LOG TAIL ---"
tail -n 80 "$LOG" || true

echo "PHASE3H_GO2RTC=PASS"
