#!/usr/bin/env python3
"""Phase 3H pipe adapter for yi_native_av_relay.

The finite Phase 3G file smoke proved that the decoded H264+AAC streams mux
correctly, but a continuous pipe exposed two independent live-stream issues:

1. FFmpeg's normal raw-input probing can wait for a large amount of data when
   there is no EOF.
2. The raw H264 packets reach the MPEG-TS muxer without timestamps. go2rtc can
   discover the tracks from the first TS packets, but RTP delivery needs a
   monotonic timestamp timeline for each access unit.

This adapter keeps the proven PPPP/TNP/media path unchanged. For the continuous
stdout path only it gives FFmpeg bounded probe windows, explicit packet PTS/DTS
and durations using the already-proven 20 fps video cadence and AAC-LC
1024/16000 = 64 ms cadence, raises input queues, forces packet flushing, and
explicitly pumps MPEG-TS stdout to the parent stdout. Diagnostics stay on
stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO

import yi_native_av_relay as base

_ORIGINAL_START_FFMPEG = base.start_ffmpeg
_PUMPS: list[threading.Thread] = []

MPEGTS_TIME_BASE = 90000
VIDEO_TICKS = MPEGTS_TIME_BASE // base.VIDEO_FPS  # 4500 ticks = 50 ms
AAC_SAMPLE_RATE = 16000
AAC_SAMPLES_PER_FRAME = 1024
AUDIO_TICKS = MPEGTS_TIME_BASE * AAC_SAMPLES_PER_FRAME // AAC_SAMPLE_RATE  # 5760 = 64 ms


def _setts(kind: str, start_ms: int) -> str:
    start_ticks = int(start_ms) * MPEGTS_TIME_BASE // 1000
    if kind == "video":
        step = VIDEO_TICKS
    elif kind == "audio":
        step = AUDIO_TICKS
    else:
        raise ValueError(kind)
    return (
        "setts=time_base=1/90000:"
        f"pts=N*{step}+{start_ticks}:"
        f"dts=N*{step}+{start_ticks}:"
        f"duration={step}"
    )


def _start_ffmpeg_with_explicit_stdout(
    ffmpeg: str,
    output: BinaryIO | None,
    video_offset_ms: int,
    audio_offset_ms: int,
):
    # Preserve the original finite-file path exactly. Phase 3H2 changes only
    # the continuous stdout path used by the isolated go2rtc test.
    if output is not None:
        return _ORIGINAL_START_FFMPEG(ffmpeg, output, video_offset_ms, audio_offset_ms)

    video_r, video_w = os.pipe()
    audio_r, audio_w = os.pipe()
    ts_r, ts_w = os.pipe()
    ts_writer = os.fdopen(ts_w, "wb", buffering=0)

    video_opts = [
        "-thread_queue_size", "512",
        "-probesize", "262144",
        "-analyzeduration", "500000",
        "-fflags", "+nobuffer",
        "-r", str(base.VIDEO_FPS),
        "-f", "h264",
        "-i", f"pipe:{video_r}",
    ]

    audio_opts = [
        "-thread_queue_size", "512",
        "-probesize", "32768",
        "-analyzeduration", "200000",
        "-f", "aac",
        "-i", f"pipe:{audio_r}",
    ]

    video_setts = _setts("video", video_offset_ms)
    audio_setts = _setts("audio", audio_offset_ms)

    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-nostdin",
        *video_opts,
        *audio_opts,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
        "-bsf:v", video_setts,
        "-bsf:a", audio_setts,
        "-flush_packets", "1",
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-mpegts_flags", "+resend_headers",
        "-f", "mpegts",
        "pipe:1",
    ]

    base.log(
        "mpegts_streaming_probe_tuning="
        "video_probe_262144/video_analyze_500ms/"
        "audio_probe_32768/audio_analyze_200ms/thread_queue_512/flush_packets"
    )
    base.log(
        "mpegts_timestamp_mode=SETTS_90KHZ; "
        f"video_step_ticks={VIDEO_TICKS}; audio_step_ticks={AUDIO_TICKS}; "
        f"video_offset_ms={video_offset_ms}; audio_offset_ms={audio_offset_ms}"
    )

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=ts_writer,
            stderr=sys.stderr.buffer,
            pass_fds=(video_r, audio_r),
            close_fds=True,
        )
    except Exception:
        for fd in (video_r, video_w, audio_r, audio_w, ts_r):
            try:
                os.close(fd)
            except OSError:
                pass
        ts_writer.close()
        raise
    else:
        os.close(video_r)
        os.close(audio_r)
        # The child owns its duplicated stdout fd. Keeping the parent writer
        # open would prevent the pump from observing EOF on shutdown.
        ts_writer.close()

    def pump() -> None:
        total = 0
        first = True
        next_report = 1024 * 1024
        try:
            while True:
                chunk = os.read(ts_r, 65536)
                if not chunk:
                    break
                if first:
                    base.log(
                        f"mpegts_stdout_first_chunk_bytes={len(chunk)}; "
                        f"sync_byte={'PASS' if chunk[0] == 0x47 else 'FAIL'}"
                    )
                    first = False
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                total += len(chunk)
                if total >= next_report:
                    base.log(f"mpegts_stdout_progress_bytes={total}")
                    next_report += 1024 * 1024
        except BrokenPipeError:
            base.log("mpegts_stdout_consumer_closed=true")
        finally:
            try:
                os.close(ts_r)
            except OSError:
                pass
            base.log(f"mpegts_stdout_pumped_bytes={total}")

    thread = threading.Thread(target=pump, name="yi-mpegts-stdout-pump", daemon=True)
    thread.start()
    _PUMPS.append(thread)
    return (
        proc,
        os.fdopen(video_w, "wb", buffering=0),
        os.fdopen(audio_w, "wb", buffering=0),
    )


base.start_ffmpeg = _start_ffmpeg_with_explicit_stdout


def _write_exit_marker(rc: int) -> None:
    """Optional test-only marker written after base.main() has fully returned.

    The marker contains no camera/account material. It lets an external harness
    prove that the relay completed its own native-worker and mux shutdown even
    after the parent go2rtc process has already stopped collecting stderr.
    """
    raw = os.getenv("YI_PHASE3_EXIT_MARKER", "").strip()
    if not raw:
        return
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"relay_exit_rc={rc}\n", encoding="utf-8")


if __name__ == "__main__":
    exit_rc = 1
    try:
        exit_rc = base.main()
    finally:
        try:
            _write_exit_marker(exit_rc)
        except Exception as exc:
            base.log(f"exit_marker_write=FAIL:{type(exc).__name__}")
    raise SystemExit(exit_rc)
