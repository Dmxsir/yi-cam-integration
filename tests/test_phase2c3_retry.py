import unittest

import phase2c3_retry as retry


class Phase2C3RetryTests(unittest.TestCase):
    def _base_report(self):
        return {
            "selected_camera": "POOL",
            "raw_model": "83",
            "normalized_model": "y291ga",
            "p2p_type": 2,
            "cloud_online": True,
            "events": [
                {"event": "PPPP_Check", "returnValue": 0, "mode": 0, "timestampNanos": 1_000_000},
                {
                    "event": "startup_burst",
                    "blockingReadBetweenCommands": False,
                    "elapsedMillis": 2,
                    "timestampNanos": 2_000_000,
                },
            ],
            "raw_frame_counts": {"channel2": 0, "channel3": 0},
        }

    def test_phase2c3_constants_match_runtime_evidence(self):
        self.assertEqual(retry.TARGET, "POOL")
        self.assertEqual(retry.EXPECTED_TNP_VERSION, 2)
        self.assertEqual(retry.EXPECTED_STARTUP, (4881, 9029, 768))

    def test_full_success_requires_4882_and_both_video_channels(self):
        report = self._base_report()
        report["events"].append(
            {
                "event": "TNP_authentication",
                "responseCommand": 4882,
                "responseCommandNumber": 1,
                "authResult": 0,
                "timestampNanos": 3_000_000,
            }
        )
        report["raw_frame_counts"] = {"channel2": 1, "channel3": 3}
        summary = retry.classify(report)
        self.assertEqual(summary["outcome"], "FULL_SUCCESS")
        self.assertEqual(summary["startup_burst_hypothesis"], "SUPPORTED")
        self.assertTrue(summary["4882_received"])
        self.assertTrue(summary["channel_2_observed"])
        self.assertTrue(summary["channel_3_observed"])
        self.assertFalse(summary["blocking_read_between_commands"])
        self.assertEqual(summary["fresh_cloud_identity"], "VERIFIED")
        self.assertEqual(summary["PPPP_mode"], "DIRECT_P2P")

    def test_control_success_accepts_4882_without_video_yet(self):
        report = self._base_report()
        report["events"].append(
            {
                "event": "TNP_authentication",
                "responseCommand": 4882,
                "responseCommandNumber": 1,
                "authResult": 0,
                "timestampNanos": 3_000_000,
            }
        )
        summary = retry.classify(report)
        self.assertEqual(summary["outcome"], "CONTROL_SUCCESS")
        self.assertEqual(summary["startup_burst_hypothesis"], "SUPPORTED")
        self.assertTrue(summary["4882_received"])

    def test_same_failure_detects_remote_close_minus_3012(self):
        report = self._base_report()
        report["events"].append(
            {
                "event": "PPPP_Read",
                "returnValue": -3012,
                "channel": 0,
                "timestampNanos": 12_000_000,
            }
        )
        summary = retry.classify(report)
        self.assertEqual(summary["outcome"], "SAME_FAILURE")
        self.assertEqual(summary["startup_burst_hypothesis"], "WEAKENED")
        self.assertTrue(summary["remote_-3012"])
        self.assertFalse(summary["4882_received"])

    def test_identity_mismatch_is_not_reported_as_verified(self):
        report = self._base_report()
        report["selected_camera"] = "מחסן"
        summary = retry.classify(report)
        self.assertEqual(summary["fresh_cloud_identity"], "FAILED")


if __name__ == "__main__":
    unittest.main()
