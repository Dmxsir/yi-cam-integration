#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$HOME/Documents/yi-cam-integration/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$HOME/Documents/yi-cam-integration/.env.local}"
RUNTIME="${RUNTIME:-$ROOT/.analysis/phase3/bionic-root}"
WORKER_DIR="${WORKER_DIR:-$RUNTIME/data/local/tmp/yi-phase3g}"
DURATION="${DURATION:-20}"
OUTPUT=""
STABLE_ID=""

usage() {
  cat <<'EOF'
Usage:
  run_phase6b_stable_probe.sh --stable-id <id> [--output <file>] [--duration <seconds>]

Environment overrides:
  PYTHON, ENV_FILE, RUNTIME, WORKER_DIR, DURATION

This is development/proof tooling. It resolves the selected camera only by
stable_id through yi_camera_runtime.py, runs the proven native PPPP/TNP relay,
and validates the resulting MPEG-TS for H264 video and AAC audio. It does not
modify production go2rtc configuration.
EOF
}

while (($#)); do
  case "$1" in
    --stable-id)
      STABLE_ID="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:-}"
      shift 2
      ;;
    --duration)
      DURATION="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$STABLE_ID" ]]; then
  echo "--stable-id is required" >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "python not executable: $PYTHON" >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "env file not found: $ENV_FILE" >&2
  exit 2
fi
if [[ ! -f "$ROOT/yi_native_av_relay_stable.py" ]]; then
  echo "stable-id relay adapter missing" >&2
  exit 2
fi
if [[ ! -d "$RUNTIME" || ! -d "$WORKER_DIR" ]]; then
  echo "native runtime/worker directory missing" >&2
  exit 2
fi
if ! [[ "$DURATION" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "--duration must be numeric" >&2
  exit 2
fi

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="/tmp/yi-phase6b-${STABLE_ID:0:8}.ts"
fi
rm -f "$OUTPUT"

echo "phase6b_stable_probe=START"
echo "stable_id=$STABLE_ID"
echo "duration_seconds=$DURATION"
echo "output=$OUTPUT"
echo "production_modified=false"

set +e
"$PYTHON" \
  "$ROOT/yi_native_av_relay_stable.py" \
  --stable-id "$STABLE_ID" \
  --env-file "$ENV_FILE" \
  --runtime "$RUNTIME" \
  --worker-dir "$WORKER_DIR" \
  --qemu qemu-aarch64 \
  --ffmpeg ffmpeg \
  --ffprobe ffprobe \
  --duration "$DURATION" \
  --output "$OUTPUT"
relay_rc=$?
set -e

echo "relay_rc=$relay_rc"
if ((relay_rc != 0)); then
  echo "PHASE6B_STABLE_PROBE=FAIL"
  exit "$relay_rc"
fi
if [[ ! -s "$OUTPUT" ]]; then
  echo "output_file_missing_or_empty=true"
  echo "PHASE6B_STABLE_PROBE=FAIL"
  exit 1
fi

probe="$(ffprobe -v error \
  -show_entries stream=codec_name,codec_type,width,height,sample_rate,channels \
  -of compact=p=0:nk=1 \
  "$OUTPUT")"
printf '%s\n' "$probe"

if ! grep -Eq '^h264\|video\|[0-9]+\|[0-9]+$' <<<"$probe"; then
  echo "video_validation=FAIL"
  echo "PHASE6B_STABLE_PROBE=FAIL"
  exit 1
fi
if ! grep -Eq '^aac\|audio\|[0-9]+\|[0-9]+$' <<<"$probe"; then
  echo "audio_validation=FAIL"
  echo "PHASE6B_STABLE_PROBE=FAIL"
  exit 1
fi

echo "video_validation=PASS"
echo "audio_validation=PASS"
echo "output_file=$OUTPUT"
echo "PHASE6B_STABLE_PROBE=PASS"
