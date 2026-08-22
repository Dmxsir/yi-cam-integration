#!/usr/bin/env python3
from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import run_phase3f_av_capture as base

# APK evidence from com.tutk.IOTC.AVFrame static constants:
# AUDIO_SAMPLE_8K=0, 11K=1, 12K=2, 16K=3, 22K=4,
# 24K=5, 32K=6, 44K=7, 48K=8.
# The previous Phase 3F table omitted 12K and shifted every code >= 2.
# For warehouse flags=27: samplerate_code=(27 >> 2)=6 => 32000 Hz.
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

_current_material = None
_original_target = base.phase3e._fresh_exact_target
_original_audio_stream = base._audio_stream


def _target(*args, **kwargs):
    global _current_material
    material, preflight = _original_target(*args, **kwargs)
    _current_material = material
    print("audio_sample_rate_mapping_source=APK_AVFrame_static_constants")
    return material, preflight


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
        # APK TnpCamera.ThreadRecvAudio applies AntsUtil.decryptAudioFrame when
        # the TNP header version is >= 2. AntsUtil transforms every complete
        # 16-byte block and leaves the trailing partial block unchanged.
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
    return _original_audio_stream(converted)


base.phase3e._fresh_exact_target = _target
base._audio_stream = _audio_stream

if __name__ == "__main__":
    raise SystemExit(base.main())
