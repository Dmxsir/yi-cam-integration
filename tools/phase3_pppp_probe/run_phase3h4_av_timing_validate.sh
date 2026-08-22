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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3h4.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3h4.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3h4-stream.json"
VIDEO_LOG="$ANALYSIS_DIR/go2rtc-phase3h4-video.log"
AUDIO_LOG="$ANALYSIS_DIR/go2rtc-phase3h4-audio.log"
COMBINED_LOG="$ANALYSIS_DIR/go2rtc-phase3h4-combined.log"
API_PORT="${PHASE3H4_API_PORT:-11984}"
RTSP_PORT="${PHASE3H4_RTSP_PORT:-18554}"
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
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$VIDEO_LOG" "$AUDIO_LOG" "$COMBINED_LOG"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3H4 port already in use: $port" >&2
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

echo "=== PHASE 3H4: RTSP A/V DECODE + CADENCE VALIDATION ==="
echo "production_go2rtc_service_touched=false"
echo "stream=${STREAM}"
echo "expected_video=H264/1920x1080/~20fps"
echo "expected_audio=AAC-LC/16000/mono/64ms_per_AU"

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
for second in $(seq 1 30); do
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || true
    if "$PYTHON" - "$API_SNAPSHOT" <<'PY' >/dev/null 2>&1
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
    tail -n 180 "$LOG" >&2 || true
    exit 8
fi

RTSP_URL="rtsp://127.0.0.1:${RTSP_PORT}/${STREAM}"
COMMON=(-hide_banner -nostdin -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 -i "$RTSP_URL")

set +e
timeout 18 "$FFMPEG" "${COMMON[@]}" -loglevel info -map 0:v:0 -an -frames:v 40 -vf showinfo -f null - >/dev/null 2>"$VIDEO_LOG"
VIDEO_RC=$?
timeout 18 "$FFMPEG" "${COMMON[@]}" -loglevel info -map 0:a:0 -vn -frames:a 50 -af ashowinfo -f null - >/dev/null 2>"$AUDIO_LOG"
AUDIO_RC=$?
timeout 15 "$FFMPEG" "${COMMON[@]}" -loglevel info -t 4 -map 0:v:0 -map 0:a:0 -f null - >/dev/null 2>"$COMBINED_LOG"
COMBINED_RC=$?
set -e

echo "rtsp_video_40frames_rc=${VIDEO_RC}"
echo "rtsp_audio_50frames_rc=${AUDIO_RC}"
echo "rtsp_combined_4s_rc=${COMBINED_RC}"

"$PYTHON" - "$VIDEO_LOG" "$AUDIO_LOG" "$VIDEO_RC" "$AUDIO_RC" "$COMBINED_RC" <<'PY'
import re, statistics, sys
vpath, apath, vrc_s, arc_s, crc_s = sys.argv[1:]

def read(path):
    return open(path, encoding='utf-8', errors='replace').read()

def times(text):
    # showinfo/ashowinfo both expose pts_time:<seconds>
    vals=[float(x) for x in re.findall(r'pts_time:([-+0-9.eE]+)', text)]
    return vals

def positive_deltas(vals):
    return [b-a for a,b in zip(vals, vals[1:]) if b > a]

vt=times(read(vpath)); at=times(read(apath))
vd=positive_deltas(vt); ad=positive_deltas(at)
vm=statistics.median(vd) if vd else None
am=statistics.median(ad) if ad else None
print(f"video_showinfo_frames={len(vt)}")
print(f"audio_ashowinfo_frames={len(at)}")
print("video_pts_delta_median_ms=" + (f"{vm*1000:.3f}" if vm is not None else "NA"))
print("audio_pts_delta_median_ms=" + (f"{am*1000:.3f}" if am is not None else "NA"))
video_cadence = vm is not None and 0.045 <= vm <= 0.055
audio_cadence = am is not None and 0.060 <= am <= 0.068
video_decode = int(vrc_s) == 0 and len(vt) >= 30
audio_decode = int(arc_s) == 0 and len(at) >= 40
combined = int(crc_s) == 0
print("rtsp_video_decode=" + ("PASS" if video_decode else "FAIL"))
print("rtsp_audio_decode=" + ("PASS" if audio_decode else "FAIL"))
print("video_20fps_cadence=" + ("PASS" if video_cadence else "FAIL"))
print("audio_64ms_cadence=" + ("PASS" if audio_cadence else "FAIL"))
print("rtsp_combined_timed_decode=" + ("PASS" if combined else ("TIMEOUT" if int(crc_s)==124 else "FAIL")))
if video_decode and audio_decode and video_cadence and audio_cadence and combined:
    print("phase3h4_classification=AV_DECODE_AND_TIMING_PASS")
    print("PHASE3H4_AV=PASS")
elif video_decode and audio_decode and audio_cadence and not video_cadence:
    print("phase3h4_classification=VIDEO_ACCESS_UNIT_TIMESTAMP_BOUNDARY_NEEDS_FIX")
    print("PHASE3H4_AV=DIAG_PASS")
elif video_decode and audio_decode:
    print("phase3h4_classification=CODECS_PASS_TIMING_NEEDS_FIX")
    print("PHASE3H4_AV=DIAG_PASS")
else:
    print("phase3h4_classification=DECODE_PATH_NEEDS_FIX")
    print("PHASE3H4_AV=FAIL")
PY

if [[ "$VIDEO_RC" -ne 0 ]]; then
    echo "--- VIDEO LOG TAIL ---" >&2
    tail -n 100 "$VIDEO_LOG" >&2 || true
fi
if [[ "$AUDIO_RC" -ne 0 ]]; then
    echo "--- AUDIO LOG TAIL ---" >&2
    tail -n 100 "$AUDIO_LOG" >&2 || true
fi
if [[ "$COMBINED_RC" -ne 0 ]]; then
    echo "--- COMBINED LOG TAIL ---" >&2
    tail -n 100 "$COMBINED_LOG" >&2 || true
fi
