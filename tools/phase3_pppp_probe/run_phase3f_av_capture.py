#!/usr/bin/env python3
"""Phase 3F: capture native PPPP/TNP video+audio without Android and validate media elementary streams."""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = Path(__file__).resolve().parent
for path in (ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_phase3e_tnp as phase3e
import yi_live_relay
import yi_tnp_oracle as oracle

AUDIO_CODEC_AAC = 138
MAX_RECORD = 2 * 1024 * 1024 + 32


def _payload(material: oracle.CameraMaterial, units: tuple[bytes, bytes, bytes, bytes]) -> bytes:
    did = phase3e._field(material.pppp_did)
    server = phase3e._field(material.server)
    key = phase3e._field(material.device_key)
    lengths = (len(did), len(server), len(key), *(len(unit) for unit in units))
    header = b"Y3F1" + bytes((1 if material.wakeup else 0, phase3e.CONNECTION_FLAG)) + struct.pack(">H", 0)
    header += struct.pack(">IIIIIII", *lengths)
    return header + did + server + key + b"".join(units)


def _records(path: Path) -> list[bytes]:
    data = path.read_bytes()
    records: list[bytes] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 4:
            raise RuntimeError(f"truncated record length in {path.name}")
        length = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        if length < 32 or length > MAX_RECORD or offset + length > len(data):
            raise RuntimeError(f"invalid record length in {path.name}")
        records.append(data[offset:offset + length])
        offset += length
    return records


def _video_stream(records2: list[bytes], records3: list[bytes], material: oracle.CameraMaterial) -> tuple[bytes, dict[str, int]]:
    frames = [yi_live_relay._decode_video_unit(2, raw, material.password, material.encrypted) for raw in records2]
    frames += [yi_live_relay._decode_video_unit(3, raw, material.password, material.encrypted) for raw in records3]
    first_i = next((frame for frame in frames if frame.get("frame_type") == "I"), None)
    if first_i is None:
        raise RuntimeError("Phase 3F captured no I-frame")
    base = int(first_i["sequence"]) & 0xFFFF
    unique: dict[int, dict] = {}
    for frame in frames:
        sequence = int(frame["sequence"]) & 0xFFFF
        unique.setdefault(sequence, frame)
    ordered = sorted(unique.values(), key=lambda frame: (int(frame["sequence"]) - base) & 0xFFFF)
    ordered = [frame for frame in ordered if ((int(frame["sequence"]) - base) & 0xFFFF) < 0x8000]
    if not ordered or ordered[0].get("frame_type") != "I":
        raise RuntimeError("Phase 3F stream does not begin on the captured I-frame")
    output = b"".join(frame["output_payload"] for frame in ordered)
    if not output:
        raise RuntimeError("Phase 3F produced an empty H.264 stream")
    return output, {
        "video_frames": len(ordered),
        "first_sequence": base,
        "last_sequence": int(ordered[-1]["sequence"]) & 0xFFFF,
    }


def _audio_stream(records: list[bytes]) -> tuple[bytes, dict[str, int | bool]]:
    payloads: list[bytes] = []
    first_sequence: int | None = None
    last_sequence: int | None = None
    for raw in records:
        if len(raw) < 32 or raw[0] != 2 or raw[1] != 2:
            raise RuntimeError("Phase 3F received malformed TNP audio unit")
        data_size = int.from_bytes(raw[4:8], "big")
        if data_size != len(raw) - 8:
            raise RuntimeError("Phase 3F audio TNP size mismatch")
        media = raw[8:32]
        codec = int.from_bytes(media[0:2], "big")
        if codec != AUDIO_CODEC_AAC:
            raise RuntimeError(f"Phase 3F expected AAC codec id 138, got {codec}")
        sequence = int.from_bytes(media[6:8], "big")
        if first_sequence is None:
            first_sequence = sequence
        last_sequence = sequence
        payloads.append(raw[32:])
    elementary = b"".join(payloads)
    if not elementary:
        raise RuntimeError("Phase 3F produced an empty AAC stream")
    adts = len(elementary) >= 2 and elementary[0] == 0xFF and (elementary[1] & 0xF0) == 0xF0
    return elementary, {
        "audio_frames": len(payloads),
        "first_sequence": first_sequence or 0,
        "last_sequence": last_sequence or 0,
        "adts_sync": adts,
    }


def _ffprobe(path: Path, forced_format: str) -> dict[str, object] | None:
    tool = shutil.which("ffprobe")
    if not tool:
        return None
    proc = subprocess.run(
        [tool, "-v", "error", "-f", forced_format, "-show_entries", "stream=codec_name,codec_type,width,height,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if proc.returncode != 0:
        return {"ok": False}
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False}
    streams = parsed.get("streams") if isinstance(parsed, dict) else None
    if not isinstance(streams, list) or not streams:
        return {"ok": False}
    stream = streams[0]
    return {"ok": True, **{key: stream.get(key) for key in ("codec_name", "codec_type", "width", "height", "sample_rate", "channels") if key in stream}}


def _ffmpeg_decode(path: Path, forced_format: str) -> bool | None:
    tool = shutil.which("ffmpeg")
    if not tool:
        return None
    proc = subprocess.run(
        [tool, "-v", "error", "-f", forced_format, "-i", str(path), "-f", "null", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--qemu", default="qemu-aarch64")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    oracle.load_env_file(args.env_file)
    material: oracle.CameraMaterial | None = None
    try:
        material, preflight = phase3e._fresh_exact_target(timeout=10.0)
        units = phase3e._build_units(material)
        payload = _payload(material, units)
        exe = args.target_dir / "android_pppp_av_capture"
        audio_tnp = args.target_dir / "channel1-audio.tnp"
        iframe_tnp = args.target_dir / "channel2-iframes.tnp"
        pframe_tnp = args.target_dir / "channel3-pframes.tnp"
        h264_path = args.target_dir / "warehouse.h264"
        aac_path = args.target_dir / "warehouse.aac"
        for path in (audio_tnp, iframe_tnp, pframe_tnp, h264_path, aac_path):
            path.unlink(missing_ok=True)

        print("phase3f_host=START")
        print(f"target={material.name}")
        print(f"raw_cloud_model={material.raw_model}")
        print(f"model={material.normalized_model}")
        print(f"cloud_online_reported={str(preflight['cloud_online_reported']).lower()}")
        print("media_channels=1:AAC,2:H264-I,3:H264-P")
        print("video_resolution_request=1")
        print("phone_required=false")
        print("media_output_scope=.analysis_only")

        secret_values = [value.encode() for value in (material.cloud_uid, material.pppp_did, material.server, material.device_key, material.password) if value]
        command = [
            args.qemu, "-L", str(args.runtime), "-E", "LD_LIBRARY_PATH=/data/local/tmp/yi-phase3f:/system/lib64",
            str(exe), "/data/local/tmp/yi-phase3f/libPPPP_API.so",
            str(audio_tnp), str(iframe_tnp), str(pframe_tnp),
        ]
        try:
            proc = subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout, check=False)
        except subprocess.TimeoutExpired:
            print("PHASE3F_AV=TIMEOUT", file=sys.stderr)
            return 124

        combined = proc.stdout + b"\n" + proc.stderr
        if any(secret and secret in combined for secret in secret_values):
            raise RuntimeError("Phase 3F child attempted to expose secret material")
        if proc.stdout:
            sys.stdout.buffer.write(proc.stdout)
            if not proc.stdout.endswith(b"\n"):
                sys.stdout.buffer.write(b"\n")
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            if not proc.stderr.endswith(b"\n"):
                sys.stderr.buffer.write(b"\n")
        print(f"probe_exit_code={proc.returncode}")
        if proc.returncode != 0 or b"phase3f_av_capture=PASS" not in proc.stdout:
            print("PHASE3F_AV=FAIL")
            return proc.returncode or 1

        records1 = _records(audio_tnp)
        records2 = _records(iframe_tnp)
        records3 = _records(pframe_tnp)
        h264, video_meta = _video_stream(records2, records3, material)
        aac, audio_meta = _audio_stream(records1)
        h264_path.write_bytes(h264)
        aac_path.write_bytes(aac)

        print(f"host_channel1_records={len(records1)}")
        print(f"host_channel2_records={len(records2)}")
        print(f"host_channel3_records={len(records3)}")
        print(f"h264_output_bytes={len(h264)}")
        print(f"h264_output_frames={video_meta['video_frames']}")
        print(f"aac_output_bytes={len(aac)}")
        print(f"aac_output_frames={audio_meta['audio_frames']}")
        print(f"aac_adts_sync={str(bool(audio_meta['adts_sync'])).lower()}")

        video_probe = _ffprobe(h264_path, "h264")
        audio_probe = _ffprobe(aac_path, "aac")
        video_decode = _ffmpeg_decode(h264_path, "h264")
        audio_decode = _ffmpeg_decode(aac_path, "aac") if audio_meta["adts_sync"] else False
        if video_probe is not None:
            print(f"ffprobe_video={json.dumps(video_probe, sort_keys=True, separators=(',', ':'))}")
        if audio_probe is not None:
            print(f"ffprobe_audio={json.dumps(audio_probe, sort_keys=True, separators=(',', ':'))}")
        print(f"ffmpeg_video_decode={'SKIPPED' if video_decode is None else 'PASS' if video_decode else 'FAIL'}")
        print(f"ffmpeg_audio_decode={'SKIPPED' if audio_decode is None else 'PASS' if audio_decode else 'FAIL'}")

        video_ok = len(h264) > 0 and (video_decode is not False)
        audio_ok = len(aac) > 0 and bool(audio_meta["adts_sync"]) and (audio_decode is not False)
        if video_ok and audio_ok:
            print("phase3f_elementary_streams=PASS")
            print("PHASE3F_AV=PASS")
            return 0
        if not audio_meta["adts_sync"]:
            print("audio_elementary_stream=NEEDS_FRAMING")
        print("phase3f_elementary_streams=FAIL")
        print("PHASE3F_AV=FAIL")
        return 1
    finally:
        if material is not None:
            material.clear()


if __name__ == "__main__":
    raise SystemExit(main())
