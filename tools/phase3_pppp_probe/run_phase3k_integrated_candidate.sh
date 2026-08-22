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
CONFIG="$ANALYSIS_DIR/go2rtc-phase3k.yaml"
LOG="$ANALYSIS_DIR/go2rtc-phase3k.log"
API_SNAPSHOT="$ANALYSIS_DIR/go2rtc-phase3k-stream.json"
VIDEO_LOG="$ANALYSIS_DIR/go2rtc-phase3k-video.log"
AUDIO_LOG="$ANALYSIS_DIR/go2rtc-phase3k-audio.log"
POST_LOG="$ANALYSIS_DIR/go2rtc-phase3k-post.log"
EXIT_MARKER="$ANALYSIS_DIR/phase3k-relay-exit.marker"
API_PORT="${PHASE3K_API_PORT:-11984}"
RTSP_PORT="${PHASE3K_RTSP_PORT:-18554}"
STREAM="yi_warehouse_phase3"
RELAY="$ROOT/yi_native_av_relay_integrated.py"

for tool in "$GO2RTC" "$PYTHON" "$FFMPEG" curl timeout ss pgrep ps; do
    if ! command -v "$tool" >/dev/null 2>&1 && [[ ! -x "$tool" ]]; then
        echo "ERROR: required tool missing: $tool" >&2
        exit 2
    fi
done
for f in "$ENV_FILE" "$RELAY" "$WORKER_DIR/android_pppp_av_stream" "$WORKER_DIR/libPPPP_API.so" "$RUNTIME/system/bin/linker64"; do
    [[ -f "$f" ]] || { echo "ERROR: required file missing: $f" >&2; exit 3; }
done

mkdir -p "$ANALYSIS_DIR"
chmod 700 "$ANALYSIS_DIR"
rm -f "$CONFIG" "$LOG" "$API_SNAPSHOT" "$VIDEO_LOG" "$AUDIO_LOG" "$POST_LOG" "$EXIT_MARKER"

for port in "$API_PORT" "$RTSP_PORT"; do
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"; then
        echo "ERROR: isolated Phase 3K port already in use: $port" >&2
        exit 4
    fi
done

"$PYTHON" -m py_compile "$RELAY"
echo "integrated_relay_python_compile=PASS"

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

echo "=== PHASE 3K: INTEGRATED NATIVE RELAY REGRESSION ==="
echo "production_go2rtc_service_touched=false"
echo "relay=yi_native_av_relay_integrated.py"
echo "checks=tracks+cadence+reconnect+parent_shutdown"

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

state() {
    curl -sS --max-time 1 -o "$API_SNAPSHOT" "$API_URL" || return 1
    "$PYTHON" - "$API_SNAPSHOT" <<'PY'
import json,sys
try: obj=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception: raise SystemExit(1)
for p in obj.get('producers',[]) or []:
    if p.get('format_name')!='mpegts': continue
    v=a=None
    for r in p.get('receivers',[]) or []:
        c=(r.get('codec') or {}).get('codec_name')
        row=(int(r.get('id',0) or 0),int(r.get('packets',0) or 0))
        if c=='h264': v=row
        elif c=='aac': a=row
    if v and a:
        print(v[0],v[1],a[0],a[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

READY=0
for second in $(seq 1 40); do
    if STATE="$(state 2>/dev/null)"; then READY=1; echo "integrated_source_ready=PASS"; break; fi
    if (( second % 5 == 0 )); then echo "source_ready_wait_seconds=${second}"; tail -n 8 "$LOG" | sed 's/^/[go2rtc-tail] /'; fi
    sleep 1
done
[[ "$READY" == 1 ]] || { echo "integrated_source_ready=FAIL" >&2; tail -n 180 "$LOG" >&2; exit 5; }

read -r PRE_VID PRE_V0 PRE_AID PRE_A0 <<<"$STATE"
sleep 5
read -r PRE_VID1 PRE_V1 PRE_AID1 PRE_A1 <<<"$(state)"
if [[ "$PRE_VID" == "$PRE_VID1" && "$PRE_AID" == "$PRE_AID1" ]] && (( PRE_V1 > PRE_V0 && PRE_A1 > PRE_A0 )); then
    echo "integrated_packet_growth=PASS"
else
    echo "integrated_packet_growth=FAIL" >&2; exit 6
fi

set +e
timeout 15 "$FFMPEG" -hide_banner -nostdin -loglevel info -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 -i "$RTSP_URL" -map 0:v:0 -an -frames:v 40 -vf showinfo -f null - >/dev/null 2>"$VIDEO_LOG"
VRC=$?
timeout 15 "$FFMPEG" -hide_banner -nostdin -loglevel info -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 -i "$RTSP_URL" -map 0:a:0 -vn -frames:a 50 -af ashowinfo -f null - >/dev/null 2>"$AUDIO_LOG"
ARC=$?
set -e
"$PYTHON" - "$VIDEO_LOG" "$AUDIO_LOG" "$VRC" "$ARC" <<'PY'
import re,statistics,sys
vp,ap,vrc,arc=sys.argv[1:]
def vals(p): return [float(x) for x in re.findall(r'pts_time:([-+0-9.eE]+)',open(p,encoding='utf-8',errors='replace').read())]
def med(v):
 d=[b-a for a,b in zip(v,v[1:]) if b>a]
 return statistics.median(d) if d else None
v=vals(vp); a=vals(ap); vm=med(v); am=med(a)
print(f"integrated_video_frames={len(v)}")
print(f"integrated_audio_frames={len(a)}")
print("integrated_video_pts_median_ms="+(f"{vm*1000:.3f}" if vm is not None else "NA"))
print("integrated_audio_pts_median_ms="+(f"{am*1000:.3f}" if am is not None else "NA"))
ok=int(vrc)==0 and int(arc)==0 and len(v)>=30 and len(a)>=40 and vm is not None and 0.045<=vm<=0.055 and am is not None and 0.060<=am<=0.068
print("integrated_av_cadence="+("PASS" if ok else "FAIL"))
raise SystemExit(0 if ok else 1)
PY

echo "integrated_pre_reconnect_av=PASS"

relay_pid() { pgrep -P "$GO2RTC_PID" -f 'yi_native_av_relay_integrated.py' | head -n 1 || true; }
OLD_PID="$(relay_pid)"
[[ -n "$OLD_PID" ]] || { echo "integrated_relay_pid=FAIL" >&2; exit 7; }
echo "integrated_relay_pid=PASS"
kill -INT "$OLD_PID"
for _ in $(seq 1 200); do ! kill -0 "$OLD_PID" 2>/dev/null && break; sleep 0.1; done
! kill -0 "$OLD_PID" 2>/dev/null || { echo "integrated_old_relay_exit=FAIL" >&2; exit 8; }
echo "integrated_old_relay_exit=PASS"

NEW_PID=""
for second in $(seq 1 45); do
    CAND="$(relay_pid)"
    if [[ -n "$CAND" && "$CAND" != "$OLD_PID" ]] && NEW_STATE="$(state 2>/dev/null)"; then NEW_PID="$CAND"; break; fi
    if (( second % 5 == 0 )); then echo "integrated_reconnect_wait_seconds=${second}"; fi
    sleep 1
done
[[ -n "$NEW_PID" ]] || { echo "integrated_reconnect=FAIL" >&2; tail -n 180 "$LOG" >&2; exit 9; }
read -r NEW_VID NEW_V0 NEW_AID NEW_A0 <<<"$NEW_STATE"
[[ "$NEW_VID" != "$PRE_VID" && "$NEW_AID" != "$PRE_AID" ]] || { echo "integrated_receiver_generation_swap=FAIL" >&2; exit 10; }
echo "integrated_receiver_generation_swap=PASS"
AUTH_COUNT="$(grep -c 'phase3g_tnp_auth=PASS' "$LOG" || true)"
DEINIT_COUNT="$(grep -c 'PPPP_DeInitialize_rc_hex=0x00000000' "$LOG" || true)"
(( AUTH_COUNT >= 2 )) || { echo "integrated_second_auth=FAIL" >&2; exit 11; }
(( DEINIT_COUNT >= 1 )) || { echo "integrated_first_shutdown=FAIL" >&2; exit 12; }
echo "integrated_reconnect_auth_and_cleanup=PASS"

set +e
timeout 15 "$FFMPEG" -hide_banner -nostdin -loglevel error -rtsp_transport tcp -probesize 1000000 -analyzeduration 1000000 -i "$RTSP_URL" -t 3 -map 0:v:0 -map 0:a:0 -f null - >/dev/null 2>"$POST_LOG"
POST_RC=$?
set -e
[[ "$POST_RC" -eq 0 ]] || { echo "integrated_post_reconnect_av=FAIL" >&2; tail -n 80 "$POST_LOG" >&2; exit 13; }
echo "integrated_post_reconnect_av=PASS"

# The first graceful relay restart wrote its own safe marker. Remove it so the
# next marker can only come from shutdown of the currently active relay.
rm -f "$EXIT_MARKER"
mapfile -t CHILDREN < <(pgrep -P "$NEW_PID" || true)
echo "integrated_parent_shutdown_signal=SIGINT"
kill -INT "$GO2RTC_PID"
for _ in $(seq 1 120); do ! kill -0 "$GO2RTC_PID" 2>/dev/null && break; sleep 0.1; done
! kill -0 "$GO2RTC_PID" 2>/dev/null || { echo "integrated_go2rtc_exit=FAIL" >&2; exit 14; }
wait "$GO2RTC_PID" 2>/dev/null || true
STOPPED=1
echo "integrated_go2rtc_exit=PASS"

MARKER=0
for second in $(seq 1 30); do
    if [[ -s "$EXIT_MARKER" ]]; then MARKER=1; break; fi
    sleep 1
done
[[ "$MARKER" == 1 ]] || { echo "integrated_parent_exit_marker=FAIL" >&2; exit 15; }
VALUE="$(tr -d '\r\n' <"$EXIT_MARKER")"
echo "integrated_parent_exit_marker_value=${VALUE}"
[[ "$VALUE" == "relay_exit_rc=0" ]] || { echo "integrated_parent_shutdown_cleanup=FAIL" >&2; exit 16; }
! kill -0 "$NEW_PID" 2>/dev/null || { echo "integrated_relay_exit_after_parent=FAIL" >&2; exit 17; }
for pid in "${CHILDREN[@]}"; do
    [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null || { echo "integrated_orphan_child=FAIL" >&2; exit 18; }
done
echo "integrated_parent_shutdown_cleanup=PASS"
echo "PHASE3K_INTEGRATED=PASS"
