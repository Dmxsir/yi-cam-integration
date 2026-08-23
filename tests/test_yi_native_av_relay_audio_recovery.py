from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yi_native_av_relay as relay


class YiNativeAvRelayAudioRecoveryTests(unittest.TestCase):
    def test_malformed_audio_unit_is_recoverable_packet_error(self) -> None:
        with self.assertRaises(relay.AudioUnitValidationError):
            relay.decrypt_audio_unit(b"\x00" * 10, "123456789012345")

    def test_invalid_audio_codec_is_recoverable_packet_error(self) -> None:
        raw = bytearray(39)
        raw[0] = 2
        raw[1] = 2
        raw[4:8] = (31).to_bytes(4, "big")
        raw[8:10] = (999).to_bytes(2, "big")
        with self.assertRaises(relay.AudioUnitValidationError):
            relay.decrypt_audio_unit(bytes(raw), "123456789012345")

    def test_bad_audio_key_length_remains_session_fatal(self) -> None:
        raw = bytearray(39)
        raw[0] = 2
        raw[1] = 2
        raw[4:8] = (31).to_bytes(4, "big")
        raw[8:10] = (138).to_bytes(2, "big")
        with self.assertRaises(RuntimeError) as caught:
            relay.decrypt_audio_unit(bytes(raw), "short")
        self.assertNotIsInstance(caught.exception, relay.AudioUnitValidationError)

    def test_child_state_marker_contains_only_safe_booleans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "child-state"
            with patch.dict(
                os.environ,
                {relay.CHILD_STATE_MARKER_ENV: str(path)},
            ):
                relay._write_child_state_marker(True, False)

            self.assertEqual(
                path.read_text(encoding="ascii"),
                "qemu_alive=1\nffmpeg_alive=0\n",
            )
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
