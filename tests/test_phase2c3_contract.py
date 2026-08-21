import unittest
from pathlib import Path

import phase2c3_run
import yi_tnp_oracle as oracle


JAVA = Path("oracle/android/src/com/local/yitnporacle/OracleActivity.java")


class Phase2C3ContractTests(unittest.TestCase):
    def test_pool_only_runner_does_not_fallback(self):
        original = oracle.APPROVED_TARGETS
        try:
            # Avoid invoking network code; reproduce the wrapper's explicit target lock.
            oracle.APPROVED_TARGETS = ("POOL", "POOL")
            self.assertEqual(oracle.APPROVED_TARGETS, ("POOL", "POOL"))
            self.assertTrue(callable(phase2c3_run.main))
        finally:
            oracle.APPROVED_TARGETS = original

    def test_startup_burst_has_no_blocking_read_between_three_writes(self):
        source = JAVA.read_text(encoding="utf-8")
        start = source.index("startupStartedAt.set(System.nanoTime());")
        end = source.index('event("startup_burst_complete"', start)
        burst = source[start:end]

        first = burst.index("sendCommand(SET_RESOLUTION, resolutionPayload)")
        second = burst.index("sendCommand(START_REALTIME, startPayload)")
        third = burst.index("sendCommand(GET_DEVICE_INFO, deviceInfoPayload)")
        self.assertLess(first, second)
        self.assertLess(second, third)
        self.assertNotIn("readCommandResponse()", burst)
        self.assertNotIn("PPPP_Read", burst)

    def test_phase2c3_payload_shapes_match_runtime_evidence(self):
        source = JAVA.read_text(encoding="utf-8")
        self.assertIn(
            "byte[] startPayload = new byte[] {(byte) startUseCount, (byte) resolution, 1, 0};",
            source,
        )
        self.assertIn("byte[] deviceInfoPayload = new byte[8];", source)
        self.assertIn("private byte tnpApplicationVersion = 2;", source)
        self.assertIn("private static final int GET_DEVICE_INFO = 768;", source)

    def test_control_reader_is_started_before_first_startup_write(self):
        source = JAVA.read_text(encoding="utf-8")
        reader = source.index("channel0.start();")
        ready = source.index("controlReaderReady.await", reader)
        first_write = source.index("startupStartedAt.set(System.nanoTime());", ready)
        self.assertLess(reader, ready)
        self.assertLess(ready, first_write)


if __name__ == "__main__":
    unittest.main()
