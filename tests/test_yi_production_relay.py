from __future__ import annotations

import unittest
from pathlib import Path

import yi_production_relay as production


ROOT = Path(__file__).resolve().parents[1]
GO2RTC_CONFIG = ROOT / "go2rtc.yaml"


class YiProductionRelayTests(unittest.TestCase):
    def test_production_defaults_are_1080p_and_day_rotation(self) -> None:
        args = production.parser().parse_args(["--stdout"])
        self.assertEqual(args.target, "מחסן")
        self.assertEqual(args.resolution, 1)
        self.assertEqual(args.session_seconds, 86_400)
        self.assertEqual(args.reconnect_base, 2.0)
        self.assertEqual(args.reconnect_max, 30.0)

    def test_retry_delay_is_bounded_exponential(self) -> None:
        self.assertEqual(production.retry_delay(0), 0.0)
        self.assertEqual(production.retry_delay(1), 2.0)
        self.assertEqual(production.retry_delay(2), 4.0)
        self.assertEqual(production.retry_delay(3), 8.0)
        self.assertEqual(production.retry_delay(10), 30.0)

    def test_consumer_closed_is_a_clean_stop_condition(self) -> None:
        failure = RuntimeError(production.CONSUMER_CLOSED_MESSAGE)
        self.assertTrue(production.is_consumer_closed(failure))
        self.assertFalse(production.is_consumer_closed(RuntimeError("different failure")))
        self.assertFalse(production.is_consumer_closed(ValueError(production.CONSUMER_CLOSED_MESSAGE)))

    def test_go2rtc_uses_production_supervisor_without_hour_limit(self) -> None:
        source = GO2RTC_CONFIG.read_text(encoding="utf-8")
        self.assertIn("yi_production_relay.py", source)
        self.assertIn("--resolution 1", source)
        self.assertIn("--stdout", source)
        self.assertNotIn("--duration 3600", source)


if __name__ == "__main__":
    unittest.main()
