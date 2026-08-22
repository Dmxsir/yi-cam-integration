#!/usr/bin/env python3
"""Phase 3G preflight: characterize native TNP media timestamps from Phase 3F capture.

This is offline-only. It reads the ignored Phase 3F channel capture files and
prints timing metadata only; no media payload or secrets are emitted.
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

MAX_RECORD = 2 * 1024 * 1024 + 32


def records(path: Path) -> list[bytes]:
    data = path.read_bytes()
    result: list[bytes] = []
    offset = 0
    while offset < len(data):
        if len(data) - offset < 4:
            raise RuntimeError(f"truncated record length in {path.name}")
        length = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        if length < 32 or length > MAX_RECORD or offset + length > len(data):
            raise RuntimeError(f"invalid record length in {path.name}")
        result.append(data[offset:offset + length])
        offset += length
    return result


def media_meta(raw: bytes, expected_io_type: int) -> dict[str, int]:
    if len(raw) < 32 or raw[0] != 2 or raw[1] != expected_io_type:
        raise RuntimeError("unexpected TNP media record")
    size = int.from_bytes(raw[4:8], "big")
    if size != len(raw) - 8:
        raise RuntimeError("TNP size mismatch")
    frame = raw[8:32]
    return {
        "codec": int.from_bytes(frame[0:2], "big"),
        "flags": frame[2],
        "sequence": int.from_bytes(frame[6:8], "big"),
        "timestamp_s": int.from_bytes(frame[12:16], "big"),
        "timestamp_sub": int.from_bytes(frame[20:24], "big"),
    }


def delta32(current: int, previous: int) -> int:
    return (current - previous) & 0xFFFFFFFF


def summarize(name: str, items: list[dict[str, int]]) -> None:
    if not items:
        raise RuntimeError(f"no records for {name}")
    seq_deltas = [((b["sequence"] - a["sequence"]) & 0xFFFF) for a, b in zip(items, items[1:])]
    sec_deltas = [b["timestamp_s"] - a["timestamp_s"] for a, b in zip(items, items[1:])]
    sub_deltas = [delta32(b["timestamp_sub"], a["timestamp_sub"]) for a, b in zip(items, items[1:])]

    print(f"{name}_records={len(items)}")
    print(f"{name}_codec_id={items[0]['codec']}")
    print(f"{name}_first_sequence={items[0]['sequence']}")
    print(f"{name}_last_sequence={items[-1]['sequence']}")
    print(f"{name}_first_timestamp_s={items[0]['timestamp_s']}")
    print(f"{name}_last_timestamp_s={items[-1]['timestamp_s']}")
    print(f"{name}_first_timestamp_sub={items[0]['timestamp_sub']}")
    print(f"{name}_last_timestamp_sub={items[-1]['timestamp_sub']}")
    if seq_deltas:
        print(f"{name}_sequence_delta_min={min(seq_deltas)}")
        print(f"{name}_sequence_delta_max={max(seq_deltas)}")
    if sec_deltas:
        print(f"{name}_timestamp_s_delta_min={min(sec_deltas)}")
        print(f"{name}_timestamp_s_delta_max={max(sec_deltas)}")
    if sub_deltas:
        ordered = sorted(sub_deltas)
        print(f"{name}_timestamp_sub_delta_min={ordered[0]}")
        print(f"{name}_timestamp_sub_delta_median={int(statistics.median(ordered))}")
        print(f"{name}_timestamp_sub_delta_max={ordered[-1]}")
        common: dict[int, int] = {}
        for value in sub_deltas:
            common[value] = common.get(value, 0) + 1
        for index, (value, count) in enumerate(sorted(common.items(), key=lambda kv: (-kv[1], kv[0]))[:5], 1):
            print(f"{name}_timestamp_sub_delta_common_{index}={value}:{count}")


def parse_adts(payload: bytes) -> tuple[int, int, int]:
    if len(payload) < 7 or payload[0] != 0xFF or (payload[1] & 0xF0) != 0xF0:
        raise RuntimeError("decrypted AAC output does not start with ADTS")
    rates = (96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350)
    idx = (payload[2] >> 2) & 0x0F
    if idx >= len(rates):
        raise RuntimeError("invalid ADTS frequency index")
    channels = ((payload[2] & 0x01) << 2) | ((payload[3] >> 6) & 0x03)
    object_type = ((payload[2] >> 6) & 0x03) + 1
    return rates[idx], channels, object_type


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=Path(".analysis/phase3/bionic-root/data/local/tmp/yi-phase3f"),
    )
    args = parser.parse_args()

    audio_raw = records(args.capture_dir / "channel1-audio.tnp")
    iframe_raw = records(args.capture_dir / "channel2-iframes.tnp")
    pframe_raw = records(args.capture_dir / "channel3-pframes.tnp")

    audio = [media_meta(raw, 2) for raw in audio_raw]
    video = [media_meta(raw, 1) for raw in iframe_raw + pframe_raw]
    if not video:
        raise RuntimeError("no video records")
    video_base = video[0]["sequence"]
    video.sort(key=lambda item: (item["sequence"] - video_base) & 0xFFFF)

    print("phase3g_timebase=START")
    print("source=existing_phase3f_capture")
    print("media_payload_logged=false")
    summarize("audio", audio)
    summarize("video", video)

    aac_path = args.capture_dir / "warehouse-adts.aac"
    aac = aac_path.read_bytes()
    sample_rate, channels, object_type = parse_adts(aac)
    print(f"aac_adts_sample_rate_hz={sample_rate}")
    print(f"aac_adts_channels={channels}")
    print(f"aac_adts_object_type={object_type}")
    print(f"aac_frame_duration_us={round(1024 * 1_000_000 / sample_rate)}")

    print("phase3g_timebase=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
