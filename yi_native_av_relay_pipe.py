#!/usr/bin/env python3
"""Phase 3H pipe adapter for yi_native_av_relay.

The base relay normally lets FFmpeg inherit the relay stdout directly. This
adapter keeps the same media pipeline but makes the relay explicitly own the
FFmpeg MPEG-TS stdout pipe and pumps it to its own stdout. Diagnostics remain
on stderr. This isolates go2rtc pipe-probing issues from PPPP/TNP and media
processing without changing the proven base relay.
"""

from __future__ import annotations

import os
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
    if output is not None:
        return _ORIGINAL_START_FFMPEG(ffmpeg, output, video_offset_ms, audio_offset_ms)

    read_fd, write_fd = os.pipe()
    writer = os.fdopen(write_fd, "wb", buffering=0)
    try:
        proc, video_pipe, audio_pipe = _ORIGINAL_START_FFMPEG(
            ffmpeg, writer, video_offset_ms, audio_offset_ms
        )
    finally:
        writer.close()

    def pump() -> None:
        total = 0
        first = True
        try:
            while True:
                chunk = os.read(read_fd, 65536)
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
                os.close(read_fd)
            except OSError:
                pass
            base.log(f"mpegts_stdout_pumped_bytes={total}")

    thread = threading.Thread(target=pump, name="yi-mpegts-stdout-pump", daemon=True)
    thread.start()
    _PUMPS.append(thread)
    return proc, video_pipe, audio_pipe


base.start_ffmpeg = _start_ffmpeg_with_explicit_stdout

if __name__ == "__main__":
    raise SystemExit(base.main())
