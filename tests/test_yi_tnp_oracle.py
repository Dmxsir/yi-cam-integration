import json
import os
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import yi_tnp_oracle as oracle


class YiTnpOracleTests(unittest.TestCase):
    def test_exact_realtime_payload_matches_apk_default_path(self):
        self.assertEqual(oracle.realtime_payload(), bytes((2, 2, 1, 0)))

    def test_dotenv_loads_without_output_or_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("ORACLE_TEST_SECRET='fake-password'\n", encoding="utf-8")
            oracle.load_env_file(path)
            self.assertEqual(os.environ.pop("ORACLE_TEST_SECRET"), "fake-password")

    def test_secret_bearing_oracle_event_is_rejected(self):
        secret = b"fake-secret-value"
        with self.assertRaises(RuntimeError):
            oracle._safe_event(json.dumps({"event": "x", "safe": secret.decode()}).encode(), (secret,))
        with self.assertRaises(RuntimeError):
            oracle._safe_event(json.dumps({"event": "x", "password": "redacted"}).encode(), ())

    def test_annex_b_and_length_prefixed_nals(self):
        annex = b"\x00\x00\x00\x01\x67abc\x00\x00\x01\x68de"
        framing, types, output = oracle.analyze_nals(annex, 78)
        self.assertEqual((framing, types, output), ("ANNEX_B", [7, 8], annex))
        length = b"\x00\x00\x00\x04\x67abc\x00\x00\x00\x03\x68de"
        framing, types, output = oracle.analyze_nals(length, 78)
        self.assertEqual((framing, types), ("LENGTH_PREFIXED", [7, 8]))
        self.assertTrue(output.startswith(b"\x00\x00\x00\x01"))

    def test_encrypted_iframe_two_blocks_decrypt(self):
        password = "123456789012345"
        plaintext = b"\x00\x00\x00\x01" + bytes(range(32)) + b"tail"
        encryptor = Cipher(algorithms.AES((password + "0").encode()), modes.ECB()).encryptor()
        encrypted = plaintext[:4] + encryptor.update(plaintext[4:36]) + encryptor.finalize() + plaintext[36:]
        frame = bytearray(24)
        frame[0:2] = (78).to_bytes(2, "big")
        frame[2] = 1
        frame[5] = 2
        frame[6:8] = (9).to_bytes(2, "big")
        frame[8:10] = (1920).to_bytes(2, "big")
        frame[10:12] = (1080).to_bytes(2, "big")
        body = bytes(frame) + encrypted
        raw = bytes((2, 1, 0, 0)) + len(body).to_bytes(4, "big") + body
        parsed = oracle._parse_unit(2, raw, password, True)
        self.assertEqual(parsed["payload"], plaintext)
        self.assertEqual((parsed["width"], parsed["height"], parsed["sequence"]), (1920, 1080, 9))


if __name__ == "__main__":
    unittest.main()
