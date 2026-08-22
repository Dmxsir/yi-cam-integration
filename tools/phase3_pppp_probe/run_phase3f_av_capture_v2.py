#!/usr/bin/env python3
from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import run_phase3f_av_capture as base

# APK evidence from com.tutk.IOTC.AVFrame static constants:
# AUDIO_SAMPLE_8K=0, 11K=1, 12K=2, 16K=3, 22K=4,
# 24K=5, 32K=6, 44K=7, 48K=8.
base.TNP_SAMPLE_RATES.clear()
base.TNP_SAMPLE_RATES.update({
    0: 8000,
    1: 11025,
    2: 12000,
    3: 16000,
    4: 22050,
    5: 24000,
    6: 32000,
    7: 44100,
    8: 48000,
})

ADTS_INDEX_TO_RATE = {
    0: 96000,
    1: 88200,
    2: 64000,
    3: 48000,
    4: 44100,
    5: 32000,
    6: 24000,
    7: 22050,
    8: 16000,
    9: 12000,
    10: 11025,
    11: 8000,
    12: 7350,
}

_current_material = None
_original_target = base.phase3e._fresh_exact_target
_original_audio_stream = base._audio_stream


def _target(*args, **kwargs):
    global _current_material
    material, preflight = _original_target(*args, **kwargs)
    _current_material = material
    print("audio_sample_rate_mapping_source=APK_AVFrame_static_constants")
    return material, preflight


def _is_adts(payload: bytes) -> bool:
    return len(payload) >= 7 and payload[0] == 0xFF and (payload[1] & 0xF6) == 0xF0


def _parse_adts(payload: bytes) -> dict[str, int]:
    if not _is_adts(payload):
        raise RuntimeError("payload does not begin with an ADTS header")
    protection_absent = payload[1] & 0x01
    header_size = 7 if protection_absent else 9
    if len(payload) < header_size:
        raise RuntimeError("truncated ADTS header")
    object_type = ((payload[2] >> 6) & 0x03) + 1
    frequency_index = (payload[2] >> 2) & 0x0F
    sample_rate = ADTS_INDEX_TO_RATE.get(frequency_index)
    if sample_rate is None:
        raise RuntimeError(f"unsupported ADTS sampling-frequency index {frequency_index}")
    channels = ((payload[2] & 0x01) << 2) | ((payload[3] >> 6) & 0x03)
    frame_length = ((payload[3] & 0x03) << 11) | (payload[4] << 3) | ((payload[5] >> 5) & 0x07)
    if frame_length < header_size or frame_length > len(payload):
        raise RuntimeError(f"invalid ADTS frame length {frame_length}/{len(payload)}")
    return {
        "header_size": header_size,
        "object_type": object_type,
        "frequency_index": frequency_index,
        "sample_rate": sample_rate,
        "channels": channels,
        "frame_length": frame_length,
    }


def _audio_stream(records: list[bytes]):
    material = _current_material
    if material is None:
        raise RuntimeError("Phase 3F media material is unavailable")

    media_key = (material.password + "0").encode("ascii")
    if len(media_key) != 16:
        raise RuntimeError("TNP media key length mismatch")

    converted: list[bytes] = []
    blocks = 0
    tails = 0
    transformed_records = 0
    for raw in records:
        if len(raw) < 32:
            raise RuntimeError("short TNP audio record")
        payload = raw[32:]
        # Exact APK path: TnpCamera.ThreadRecvAudio calls
        # AntsUtil.decryptAudioFrame for TNP header version >= 2.
        # AntsUtil decrypts every complete 16-byte frmData block with
        # AES/ECB/NoPadding and leaves only the final partial block untouched.
        if raw[0] >= 2:
            aligned = (len(payload) // 16) * 16
            if aligned:
                transform = Cipher(algorithms.AES(media_key), modes.ECB()).decryptor()
                payload = transform.update(payload[:aligned]) + transform.finalize() + payload[aligned:]
                blocks += aligned // 16
            tails += len(raw[32:]) - aligned
            transformed_records += 1
        converted.append(raw[:32] + payload)

    print("audio_payload_transform=APK_TNP_V2_AES_ECB_COMPLETE_BLOCKS")
    print(f"audio_transformed_records={transformed_records}")
    print(f"audio_transformed_blocks={blocks}")
    print(f"audio_unmodified_tail_bytes={tails}")

    # Important: y291ga firmware-family tooling treats camera-produced AAC
    # frames as ADTS.  Check the post-decryption frmData before synthesizing
    # another ADTS header; double-framing an already-ADTS access unit makes
    # FFmpeg identify AAC but fail to decode it.
    payloads = [raw[32:] for raw in converted]
    native_adts_count = sum(1 for payload in payloads if _is_adts(payload))
    print(f"audio_post_decrypt_adts_records={native_adts_count}")

    if native_adts_count == len(payloads) and payloads:
        parsed = [_parse_adts(payload) for payload in payloads]
        first = parsed[0]
        for info in parsed[1:]:
            if (
                info["object_type"] != first["object_type"]
                or info["sample_rate"] != first["sample_rate"]
                or info["channels"] != first["channels"]
            ):
                raise RuntimeError("native ADTS format changed during Phase 3F capture")

        raw_access_units: list[bytes] = []
        native_frames: list[bytes] = []
        for payload, info in zip(payloads, parsed):
            frame = payload[: info["frame_length"]]
            native_frames.append(frame)
            raw_access_units.append(frame[info["header_size"] :])

        # Retain TNP metadata as a cross-check, but treat the native ADTS
        # header as authoritative for AAC elementary-stream framing.
        media = converted[0][8:32]
        flags = media[2]
        tnp_meta = base._decode_audio_flags(flags)
        print("audio_framing_mode=DECRYPTED_PAYLOAD_ALREADY_ADTS")
        print(f"audio_native_adts_sample_rate_hz={first['sample_rate']}")
        print(f"audio_native_adts_channels={first['channels']}")
        print(f"audio_native_adts_object_type={first['object_type']}")
        print(f"audio_tnp_flags_sample_rate_hz={tnp_meta['sample_rate']}")
        print(f"audio_tnp_flags_channels={tnp_meta['channels']}")

        elementary = b"".join(raw_access_units)
        adts_stream = b"".join(native_frames)
        first_sequence = int.from_bytes(converted[0][14:16], "big")
        last_sequence = int.from_bytes(converted[-1][14:16], "big")
        return elementary, adts_stream, {
            "audio_frames": len(native_frames),
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
            "flags": flags,
            "sample_rate_code": (flags >> 2) & 0x3F,
            "sample_rate": first["sample_rate"],
            "databits_code": (flags >> 1) & 0x01,
            "databits": 16,
            "channel_code": flags & 0x01,
            "channels": first["channels"],
            "object_type": first["object_type"],
            "adts_sync": True,
        }

    print("audio_framing_mode=SYNTHETIC_ADTS_FALLBACK")
    return _original_audio_stream(converted)


base.phase3e._fresh_exact_target = _target
base._audio_stream = _audio_stream

if __name__ == "__main__":
    raise SystemExit(base.main())
