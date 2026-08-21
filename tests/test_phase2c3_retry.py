import unittest
from pathlib import Path

import phase2c3_retry as retry


ROOT = Path(__file__).resolve().parents[1]
JAVA_ORACLE = ROOT / "oracle" / "android" / "src" / "com" / "local" / "yitnporacle" / "OracleActivity.java"


class Phase2C3RetryTests(unittest.TestCase):
    def _base_report(self, target="POOL"):
        return {
            "selected_camera": target,
            "raw_model": "83",
            "normalized_model": "y291ga",
            "p2p_type": 2,
            "cloud_online": True,
            "events": [
                {"event": "PPPP_Check", "returnValue": 0, "mode": 0, "timestampNanos": 1_000_000},
                {
                    "event": "startup_burst",
                    "blockingReadBetweenCommands": False,
                    "diagnosticFlushBetweenCommands": False,
                    "ppppWriteCount": 3,
                    "elapsedMicros": 900,
                    "timestampNanos": 2_000_000,
                },
            ],
            "raw_frame_counts": {"channel2": 0, "channel3": 0},
        }

    def test_phase2c3_constants_match_runtime_evidence(self):
        self.assertEqual(retry.DEFAULT_TARGET, "POOL")
        self.assertEqual(retry.ALLOWED_TARGETS, ("POOL", "מחסן"))
        self.assertEqual(retry.EXPECTED_TNP_VERSION, 2)
        self.assertEqual(retry.EXPECTED_STARTUP, (4881, 9029, 768))

    def test_parser_has_explicit_target_and_no_automatic_fallback(self):
        default_args = retry.parser().parse_args(["preflight"])
        warehouse_args = retry.parser().parse_args(["preflight", "--target", "מחסן"])
        self.assertEqual(default_args.target, "POOL")
        self.assertEqual(warehouse_args.target, "מחסן")

    def test_full_success_requires_4882_and_both_video_channels(self):
        report = self._base_report()
        report["events"].append(
            {
                "event": "TNP_authentication",
                "responseCommand": 4882,
                "responseCommandNumber": 1,
                "authResult": 0,
                "responseLatencyMicros": 34_209,
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
        self.assertFalse(summary["diagnostic_flush_between_commands"])
        self.assertEqual(summary["startup_pppp_write_count"], 3)
        self.assertEqual(summary["startup_burst_elapsed_ms"], 0.9)
        self.assertEqual(summary["first_response_latency_ms"], 34.209)
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

    def test_explicit_warehouse_identity_can_be_verified(self):
        report = self._base_report("מחסן")
        summary = retry.classify(report, "מחסן")
        self.assertEqual(summary["target"], "מחסן")
        self.assertEqual(summary["fresh_cloud_identity"], "VERIFIED")

    def test_identity_mismatch_is_not_reported_as_verified(self):
        report = self._base_report("מחסן")
        summary = retry.classify(report, "POOL")
        self.assertEqual(summary["fresh_cloud_identity"], "FAILED")

    def test_java_oracle_has_uninterrupted_three_command_burst_before_read(self):
        source = JAVA_ORACLE.read_text(encoding="utf-8")
        first = source.index("sendCommand(SET_RESOLUTION, resolutionPayload, false)")
        second = source.index("sendCommand(START_REALTIME, startPayload, false)", first)
        third = source.index("sendCommand(START_AUDIO, audioPayload, false)", second)
        first_read = source.index("CommandResponse authentication = readCommandResponse()", third)
        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertLess(third, first_read)
        burst_source = source[first:first_read]
        self.assertNotIn("readCommandResponse()", burst_source)
        self.assertIn("diagnosticFlushBetweenCommands\", false", source)
        self.assertIn("private static final int START_AUDIO = 768;", source)


if __name__ == "__main__":
    unittest.main()
