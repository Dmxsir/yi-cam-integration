import unittest

from tools.compare_tnp_packets import compare


class CompareTnpPacketsTests(unittest.TestCase):
    def test_compares_structural_fields_and_canonicalizes_auth_lengths(self):
        old = {
            "total_length": 56,
            "outer": {"size": 8, "version": 2, "endian": "big"},
            "ioctrl": {
                "command": 4881,
                "size": 40,
                "auth": {
                    "authInfo_length": 31,
                    "nonce_length": 15,
                    "hmac_component_length": 15,
                },
            },
        }
        current = {
            "total_length": 52,
            "outer": {"size": 8, "version": "UNKNOWN", "endian": "big"},
            "ioctrl": {
                "command": 9029,
                "size": 40,
                "auth": {
                    "authInfo_length": 31,
                    "nonce_length": 15,
                    "hmac_component_length": 15,
                },
            },
        }

        result = compare(old, current)

        self.assertEqual(result["fields"]["outer.size"]["result"], "MATCH")
        self.assertEqual(result["fields"]["outer.version"]["result"], "UNKNOWN")
        self.assertEqual(result["fields"]["ioctrl.command"]["result"], "DIFFERENT")
        self.assertEqual(
            result["fields"]["ioctrl.auth.authInfo_length"]["old"], "<AUTHINFO:31>"
        )
        self.assertEqual(
            result["fields"]["ioctrl.auth.nonce_length"]["old"], "<NONCE:15>"
        )
        self.assertEqual(
            result["fields"]["ioctrl.auth.hmac_component_length"]["old"], "<HMAC:15>"
        )

    def test_rejects_secret_or_raw_packet_fields(self):
        for key in ("authInfo", "nonce", "hmac", "password", "token_secret", "raw_packet"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare({key: "must-not-be-emitted"}, {})
        with self.assertRaises(ValueError):
            compare({"payload": [1, 2, 3, 4]}, {})

    def test_successful_official_and_failed_oracle_4881_structure_matches(self):
        shared = {
            "channel": 0,
            "total_length": 56,
            "outer": {"size": 8, "version": 2, "stream_type": 3, "data_size": 48},
            "ioctrl": {
                "size": 40,
                "command": 4881,
                "command_number": 1,
                "extra_header_size": 0,
                "payload_size": 8,
                "auth": {
                    "authInfo_length": 31,
                    "nonce_length": 15,
                    "hmac_component_length": 15,
                    "zero_terminated": True,
                },
            },
            "payload_shape": {"resolution": 2, "use_count": 1},
        }
        official = {**shared, "startup_group_count": 3}
        oracle = {**shared, "startup_group_count": 1}

        result = compare(official, oracle)

        self.assertEqual(result["fields"]["outer.version"]["result"], "MATCH")
        self.assertEqual(result["fields"]["ioctrl.command"]["result"], "MATCH")
        self.assertEqual(result["fields"]["payload_shape.use_count"]["result"], "MATCH")
        self.assertEqual(result["fields"]["startup_group_count"]["result"], "DIFFERENT")


if __name__ == "__main__":
    unittest.main()
