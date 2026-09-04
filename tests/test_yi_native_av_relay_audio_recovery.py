from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yi_native_av_relay as relay


class YiNativeAvRelayAudioRecoveryTests(unittest.TestCase):
    def test_native_record_probe_reports_only_safe_media_metadata(self) -> None:
        raw = bytearray(32)
        raw[0] = 2
        raw[1] = 1
        raw[4:8] = (24).to_bytes(4, "big")
        raw[8:10] = (78).to_bytes(2, "big")
        raw[10] = 1
        raw[11] = 1
        raw[13] = 2
        raw[14:16] = (65535).to_bytes(2, "big")
        raw[16:18] = (1920).to_bytes(2, "big")
        raw[18:20] = (1080).to_bytes(2, "big")
        raw[20:24] = (0xFFFFFFFE).to_bytes(4, "big")
        raw[26] = 4
        raw[27] = 5
        raw[28:32] = (0xFFFFFFF0).to_bytes(4, "big")

        # Payload content must never be copied into diagnostics.
        raw.extend(b"secret-camera-payload")
        raw[4:8] = (len(raw) - 8).to_bytes(4, "big")
        line, current = relay._format_native_record_probe(
            2,
            bytes(raw),
            1,
            (65534, 0xFFFFFFFD, 0xFFFFFFE0),
        )

        self.assertEqual(current, (65535, 0xFFFFFFFE, 0xFFFFFFF0))
        self.assertIn("native_header=YAV1/2/000000/53", line)
        self.assertIn("codec_id=78", line)
        self.assertIn("sequence=65535; sequence_delta=1", line)
        self.assertIn("timestamp=4294967294; timestamp_delta=1", line)
        self.assertIn("timestamp_ms=4294967280; timestamp_ms_delta=16", line)
        self.assertIn("dimensions=1920x1080", line)
        self.assertNotIn("secret-camera-payload", line)

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
