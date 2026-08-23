from __future__ import annotations

import subprocess
import unittest

import yi_native_av_relay_stable as stable


class YiNativeAvRelayStableDiagnosticsTests(unittest.TestCase):
    def test_preserves_non_failure_exit_codes(self) -> None:
        self.assertEqual(stable._classify_relay_failure(0, None), (0, None))
        self.assertEqual(stable._classify_relay_failure(75, None), (75, None))

    def test_classifies_native_worker_failure(self) -> None:
        self.assertEqual(
            stable._classify_relay_failure(1, (7, 0, 100, 100)),
            (stable.EXIT_NATIVE_WORKER, "native_worker_exit"),
        )

    def test_classifies_mpegts_mux_failure(self) -> None:
        self.assertEqual(
            stable._classify_relay_failure(1, (0, 9, 100, 100)),
            (stable.EXIT_MPEGTS_MUX, "mpegts_mux_exit"),
        )

    def test_classifies_missing_media(self) -> None:
        self.assertEqual(
            stable._classify_relay_failure(1, (0, 0, 0, 100)),
            (stable.EXIT_NO_VIDEO_FRAMES, "no_video_frames"),
        )
        self.assertEqual(
            stable._classify_relay_failure(1, (0, 0, 100, 0)),
            (stable.EXIT_NO_AUDIO_FRAMES, "no_audio_frames"),
        )

    def test_unclassified_failure_never_exposes_raw_log_data(self) -> None:
        self.assertEqual(
            stable._classify_relay_failure(1, None),
            (stable.EXIT_RELAY_FAILURE_UNCLASSIFIED, "relay_failure_unclassified"),
        )

    def test_classifies_common_uncaught_exception_types(self) -> None:
        cases = [
            (EOFError("secret"), stable.EXIT_RELAY_EOF, "relay_eof"),
            (RuntimeError("secret"), stable.EXIT_RELAY_RUNTIME_ERROR, "relay_runtime_error"),
            (
                subprocess.TimeoutExpired(["hidden"], 1),
                stable.EXIT_RELAY_TIMEOUT,
                "relay_timeout",
            ),
            (BrokenPipeError("secret"), stable.EXIT_RELAY_BROKEN_PIPE, "relay_broken_pipe"),
            (OSError("secret"), stable.EXIT_RELAY_OS_ERROR, "relay_os_error"),
            (ValueError("secret"), stable.EXIT_RELAY_VALUE_ERROR, "relay_value_error"),
        ]
        for exc, code, stage in cases:
            with self.subTest(stage=stage):
                self.assertEqual(stable._classify_relay_exception(exc), (code, stage))

    def test_unknown_exception_uses_generic_safe_code(self) -> None:
        class CustomFailure(Exception):
            pass

        self.assertEqual(
            stable._classify_relay_exception(CustomFailure("secret")),
            (stable.EXIT_RELAY_EXCEPTION, "relay_exception"),
        )


if __name__ == "__main__":
    unittest.main()
