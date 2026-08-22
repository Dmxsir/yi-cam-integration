#!/usr/bin/env python3
from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import run_phase3f_av_capture as base

_current_material = None
_original_target = base.phase3e._fresh_exact_target
_original_audio_stream = base._audio_stream


def _target(*args, **kwargs):
    global _current_material
    material, preflight = _original_target(*args, **kwargs)
    _current_material = material
    return material, preflight


def _audio_stream(records: list[bytes]):
    material = _current_material
    if material is None:
        raise RuntimeError("Phase 3F media material is unavailable")

    converted: list[bytes] = []
    blocks = 0
    tails = 0
    for raw in records:
        if len(raw) < 32:
            raise RuntimeError("short TNP audio record")
        payload = raw[32:]
        if material.encrypted:
            media_key = (material.password + "0").encode("ascii")
            if len(media_key) != 16:
                raise RuntimeError("TNP media key length mismatch")
            aligned = (len(payload) // 16) * 16
            if aligned:
                transform = Cipher(algorithms.AES(media_key), modes.ECB()).decryptor()
                payload = transform.update(payload[:aligned]) + transform.finalize() + payload[aligned:]
                blocks += aligned // 16
                tails += len(raw[32:]) - aligned
        converted.append(raw[:32] + payload)

    print("audio_payload_transform=" + ("APK_AES_ECB_COMPLETE_BLOCKS" if material.encrypted else "NONE"))
    print(f"audio_transformed_blocks={blocks}")
    print(f"audio_unmodified_tail_bytes={tails}")
    return _original_audio_stream(converted)


base.phase3e._fresh_exact_target = _target
base._audio_stream = _audio_stream

if __name__ == "__main__":
    raise SystemExit(base.main())
