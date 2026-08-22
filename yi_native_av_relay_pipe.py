#!/usr/bin/env python3
"""Phase 3H pipe adapter for yi_native_av_relay.

The finite Phase 3G file smoke proved that the decoded H264+AAC streams mux
correctly, but a continuous pipe exposed a different problem: FFmpeg's normal
raw-input probing can wait for a large amount of data when there is no EOF.
That is harmless for a finite capture and fatal for an exec producer whose
consumer is waiting for the first MPEG-TS byte.

This adapter keeps the proven PPPP/TNP/media path unchanged, gives FFmpeg small
bounded probe windows for the already-known H264 and ADTS/AAC inputs, raises
its input queues, forces packet flushing, and explicitly pumps MPEG-TS stdout
to the parent stdout. Diagnostics stay on stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import BinaryIO

import yi_native_av_relay as base

_ORIGINAL_START_FFMPEG = base.start_ffmpeg
_PUMPS: list[threading.Thread] = []


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
        "-fflags", "+genpts+nobuffer",
    ]
    if video_offset_ms:
        video_opts += ["-itsoffset", f"{video_offset_ms / 1000:.3f}"]
    video_opts += ["-r", str(base.VIDEO_FPS), "-f", "h264", "-i", f"pipe:{video_r}"]

    audio_opts = [
        "-thread_queue_size", "512",
        "-probesize", "32768",
        "-analyzeduration", "200000",
    ]
    if audio_offset_ms:
        audio_opts += ["-itsoffset", f"{audio_offset_ms / 1000:.3f}"]
    audio_opts += ["-f", "aac", "-i", f"pipe:{audio_r}"]

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

if __name__ == "__main__":
    raise SystemExit(base.main())
