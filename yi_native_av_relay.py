#!/usr/bin/env python3
"""Continuous phoneless YI PPPP/TNP relay producing H.264 + AAC in MPEG-TS.

The proprietary ARM64 PPPP library runs under the already-proven Bionic/qemu
bridge. A tiny worker emits framed TNP channel 1/2/3 units to this host process.
The host mirrors the YI APK media transforms, reorders H.264, preserves native
AAC/ADTS, derives the initial A/V offset from the live TNP millisecond clock,
and asks FFmpeg to mux both elementary streams with stream copy only.

stdout is reserved for MPEG-TS when --stdout is used. Diagnostics are stderr
only. No ADB/Android phone is used at runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parent
PROBE_DIR = ROOT / "tools" / "phase3_pppp_probe"
for path in (ROOT, PROBE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_phase3e_tnp as phase3e
import yi_live_relay
import yi_tnp_oracle as oracle

VIDEO_FPS = 20
MAX_RECORD = 2 * 1024 * 1024 + 32
STREAM_MAGIC = b"YAV1"


def log(message: str) -> None:
    print(f"[phase3g-relay] {message}", file=sys.stderr, flush=True)


def payload(material: oracle.CameraMaterial, units: tuple[bytes, bytes, bytes, bytes]) -> bytes:
    did = phase3e._field(material.pppp_did)
    server = phase3e._field(material.server)
    key = phase3e._field(material.device_key)
    lengths = (len(did), len(server), len(key), *(len(unit) for unit in units))
    header = b"Y3F1" + bytes((1 if material.wakeup else 0, phase3e.CONNECTION_FLAG)) + struct.pack(">H", 0)
    header += struct.pack(">IIIIIII", *lengths)
    return header + did + server + key + b"".join(units)


def read_exact(stream: BinaryIO, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = stream.read(length - len(result))
        if not chunk:
            raise EOFError("native PPPP worker closed its media pipe")
        result.extend(chunk)
    return bytes(result)


def signed_delta32(current: int, base: int) -> int:
    value = (current - base) & 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def decrypt_audio_unit(raw: bytes, password: str) -> tuple[int, bytes, dict[str, int]]:
    if len(raw) < 39 or raw[0] < 2 or raw[1] != 2:
        raise RuntimeError("malformed TNP v2 audio unit")
    if int.from_bytes(raw[4:8], "big") != len(raw) - 8:
        raise RuntimeError("TNP audio size mismatch")
    media = raw[8:32]
    if int.from_bytes(media[0:2], "big") != 138:
        raise RuntimeError("native relay expected AAC codec id 138")

    access_unit = raw[32:]
    key = (password + "0").encode("ascii")
    if len(key) != 16:
        raise RuntimeError("TNP audio AES key is not 16 bytes")
    aligned = (len(access_unit) // 16) * 16
    if aligned:
        decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        access_unit = decryptor.update(access_unit[:aligned]) + decryptor.finalize() + access_unit[aligned:]

    if len(access_unit) < 7 or access_unit[0] != 0xFF or (access_unit[1] & 0xF0) != 0xF0:
        raise RuntimeError("decrypted AAC payload has no native ADTS header")
    rates = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)
    freq_index = (access_unit[2] >> 2) & 0x0F
    if freq_index >= len(rates):
        raise RuntimeError("invalid native ADTS sample-rate index")
    channels = ((access_unit[2] & 0x01) << 2) | ((access_unit[3] >> 6) & 0x03)
    object_type = ((access_unit[2] >> 6) & 0x03) + 1
    timestamp_ms = int.from_bytes(media[20:24], "big")
    return timestamp_ms, access_unit, {
        "sample_rate": rates[freq_index],
        "channels": channels,
        "object_type": object_type,
    }


def start_ffmpeg(
    ffmpeg: str,
    output: BinaryIO | None,
    video_offset_ms: int,
    audio_offset_ms: int,
) -> tuple[subprocess.Popen[bytes], BinaryIO, BinaryIO]:
    video_r, video_w = os.pipe()
    audio_r, audio_w = os.pipe()

    video_opts = ["-fflags", "+genpts"]
    if video_offset_ms:
        video_opts += ["-itsoffset", f"{video_offset_ms / 1000:.3f}"]
    video_opts += ["-r", str(VIDEO_FPS), "-f", "h264", "-i", f"pipe:{video_r}"]

    audio_opts: list[str] = []
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
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-mpegts_flags", "+resend_headers",
        "-f", "mpegts",
        "pipe:1",
    ]
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=sys.stderr.buffer,
            pass_fds=(video_r, audio_r),
            close_fds=True,
        )
    finally:
        os.close(video_r)
        os.close(audio_r)

    return proc, os.fdopen(video_w, "wb", buffering=0), os.fdopen(audio_w, "wb", buffering=0)


def validate_ts(path: Path, ffprobe: str) -> bool:
    proc = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "stream=codec_name,codec_type,width,height,sample_rate,channels",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if proc.returncode != 0:
        log("ffprobe_mpegts=FAIL")
        return False
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log("ffprobe_mpegts=FAIL")
        return False
    streams = parsed.get("streams", []) if isinstance(parsed, dict) else []
    safe = [
        {key: stream.get(key) for key in ("codec_name", "codec_type", "width", "height", "sample_rate", "channels") if key in stream}
        for stream in streams if isinstance(stream, dict)
    ]
    log("ffprobe_mpegts=" + json.dumps(safe, sort_keys=True, separators=(",", ":")))
    video_ok = any(s.get("codec_type") == "video" and s.get("codec_name") == "h264" and s.get("width") == 1920 and s.get("height") == 1080 for s in safe)
    audio_ok = any(s.get("codec_type") == "audio" and s.get("codec_name") == "aac" and str(s.get("sample_rate")) == "16000" and int(s.get("channels", 0)) == 1 for s in safe)
    return video_ok and audio_ok


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phoneless native YI H264+AAC MPEG-TS relay")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    p.add_argument("--runtime", type=Path, default=ROOT / ".analysis/phase3/bionic-root")
    p.add_argument("--worker-dir", type=Path, default=ROOT / ".analysis/phase3/bionic-root/data/local/tmp/yi-phase3g")
    p.add_argument("--qemu", default="qemu-aarch64")
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    p.add_argument("--duration", type=float, default=0.0, help="0 means continuous until consumer/signal")
    p.add_argument("--stdout", action="store_true", help="write MPEG-TS to stdout for go2rtc")
    p.add_argument("--output", type=Path, help="write MPEG-TS to a file for validation")
    return p


def main() -> int:
    args = parser().parse_args()
    if args.stdout == bool(args.output):
        raise SystemExit("choose exactly one of --stdout or --output")
    if not args.env_file.is_file():
        raise SystemExit(".env.local is missing")
    worker = args.worker_dir / "android_pppp_av_stream"
    library = args.worker_dir / "libPPPP_API.so"
    if not worker.is_file() or not library.is_file():
        raise SystemExit("Phase 3G worker is not built")

    oracle.load_env_file(args.env_file)
    material: oracle.CameraMaterial | None = None
    child: subprocess.Popen[bytes] | None = None
    mux: subprocess.Popen[bytes] | None = None
    video_pipe: BinaryIO | None = None
    audio_pipe: BinaryIO | None = None
    output_file: BinaryIO | None = None
    stop_lock = threading.Lock()
    stop_sent = False

    try:
        material, preflight = phase3e._fresh_exact_target(timeout=10.0)
        units = phase3e._build_units(material)
        config = payload(material, units)
        log(f"target={material.name}; raw_model={material.raw_model}; model={material.normalized_model}")
        log(f"cloud_online_reported={str(preflight['cloud_online_reported']).lower()}; runtime_reachability=PPPP")
        log("media=H264/1920x1080@20fps + native AAC-LC/16000/mono; transcoding=false")
        log("phone_required=false")

        command = [
            args.qemu,
            "-L", str(args.runtime),
            "-E", "LD_LIBRARY_PATH=/data/local/tmp/yi-phase3g:/system/lib64",
            str(worker),
            "/data/local/tmp/yi-phase3g/libPPPP_API.so",
        ]
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if child.stdin is None or child.stdout is None or child.stderr is None:
            raise RuntimeError("failed to create native worker pipes")
        child.stdin.write(config)
        child.stdin.flush()
        del config

        def drain_stderr() -> None:
            assert child is not None and child.stderr is not None
            for line in iter(child.stderr.readline, b""):
                sys.stderr.buffer.write(b"[phase3g-worker] " + line)
                sys.stderr.buffer.flush()

        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stderr_thread.start()

        def request_stop() -> None:
            nonlocal stop_sent
            with stop_lock:
                if stop_sent:
                    return
                stop_sent = True
                if child is not None and child.stdin is not None:
                    try:
                        child.stdin.write(b"\x00")
                        child.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass

        def signal_stop(_signum: int, _frame: object) -> None:
            request_stop()

        signal.signal(signal.SIGINT, signal_stop)
        signal.signal(signal.SIGTERM, signal_stop)
        timer = threading.Timer(args.duration, request_stop) if args.duration > 0 else None
        if timer is not None:
            timer.daemon = True
            timer.start()

        reorder = yi_live_relay.SequenceReorderBuffer(max_pending=24, max_wait_seconds=0.35)
        pre_video: list[tuple[int, bytes]] = []
        pre_audio: list[tuple[int, bytes]] = []
        first_video_ts: int | None = None
        first_audio_ts: int | None = None
        audio_format: dict[str, int] | None = None
        video_frames = 0
        audio_frames = 0

        def start_mux_if_ready() -> None:
            nonlocal mux, video_pipe, audio_pipe, output_file
            if mux is not None or first_video_ts is None or first_audio_ts is None:
                return
            delta = signed_delta32(first_audio_ts, first_video_ts)
            video_offset_ms = max(0, -delta)
            audio_offset_ms = max(0, delta)
            log(f"tnp_timebase=milliseconds; video_fps={VIDEO_FPS}; aac_frame_ms=64")
            log(f"initial_av_delta_ms={delta}; video_offset_ms={video_offset_ms}; audio_offset_ms={audio_offset_ms}")
            if audio_format is not None:
                log(
                    f"native_aac=object_type_{audio_format['object_type']}/"
                    f"{audio_format['sample_rate']}Hz/{audio_format['channels']}ch"
                )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                output_file = args.output.open("wb")
                mux_output: BinaryIO | None = output_file
            else:
                mux_output = None
            mux, video_pipe, audio_pipe = start_ffmpeg(args.ffmpeg, mux_output, video_offset_ms, audio_offset_ms)
            for _, frame in pre_video:
                video_pipe.write(frame)
            for _, frame in pre_audio:
                audio_pipe.write(frame)
            pre_video.clear()
            pre_audio.clear()
            log("mpegts_mux=STARTED")

        try:
            while True:
                header = child.stdout.read(12)
                if not header:
                    break
                if len(header) != 12:
                    raise RuntimeError("truncated native stream header")
                if header[:4] != STREAM_MAGIC or header[5:8] != b"\0\0\0":
                    raise RuntimeError("invalid native stream framing")
                channel = header[4]
                length = int.from_bytes(header[8:12], "big")
                if channel not in (1, 2, 3) or length < 32 or length > MAX_RECORD:
                    raise RuntimeError("invalid native media record")
                raw = read_exact(child.stdout, length)

                if channel == 1:
                    timestamp_ms, aac, fmt = decrypt_audio_unit(raw, material.password)
                    if audio_format is None:
                        audio_format = fmt
                    elif fmt != audio_format:
                        raise RuntimeError("AAC format changed during live session")
                    if first_audio_ts is None:
                        first_audio_ts = timestamp_ms
                    audio_frames += 1
                    if mux is None:
                        pre_audio.append((timestamp_ms, aac))
                        start_mux_if_ready()
                    else:
                        assert audio_pipe is not None
                        audio_pipe.write(aac)
                    continue

                frame = yi_live_relay._decode_video_unit(channel, raw, material.password, material.encrypted)
                for ready in reorder.push(frame):
                    timestamp_ms = int(ready["timestamp_ms"])
                    if first_video_ts is None:
                        first_video_ts = timestamp_ms
                    video_frames += 1
                    data = ready["output_payload"]
                    if mux is None:
                        pre_video.append((timestamp_ms, data))
                        start_mux_if_ready()
                    else:
                        assert video_pipe is not None
                        video_pipe.write(data)

                if mux is not None and mux.poll() is not None:
                    if args.stdout:
                        log("consumer/mux closed output; stopping native source")
                        request_stop()
                        break
                    raise RuntimeError(f"FFmpeg MPEG-TS mux exited early with {mux.returncode}")
        except BrokenPipeError:
            if args.stdout:
                log("consumer closed MPEG-TS output")
                request_stop()
            else:
                raise
        finally:
            request_stop()
            if timer is not None:
                timer.cancel()

        child_rc = child.wait(timeout=20)
        if video_pipe is not None:
            video_pipe.close()
        if audio_pipe is not None:
            audio_pipe.close()
        mux_rc = mux.wait(timeout=20) if mux is not None else 1
        if output_file is not None:
            output_file.close()
            output_file = None

        log(f"native_worker_exit={child_rc}; mpegts_mux_exit={mux_rc}; video_frames={video_frames}; audio_frames={audio_frames}")
        if child_rc != 0 or mux_rc != 0 or video_frames == 0 or audio_frames == 0:
            log("PHASE3G_NATIVE_AV=FAIL")
            return 1

        if args.output:
            ok = validate_ts(args.output, args.ffprobe)
            log("PHASE3G_NATIVE_AV=PASS" if ok else "PHASE3G_NATIVE_AV=FAIL")
            return 0 if ok else 1

        return 0
    finally:
        if video_pipe is not None and not video_pipe.closed:
            video_pipe.close()
        if audio_pipe is not None and not audio_pipe.closed:
            audio_pipe.close()
        if output_file is not None and not output_file.closed:
            output_file.close()
        if child is not None and child.poll() is None:
            child.kill()
        if mux is not None and mux.poll() is None:
            mux.kill()
        if material is not None:
            material.clear()


if __name__ == "__main__":
    raise SystemExit(main())
