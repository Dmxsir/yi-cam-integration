from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_classifies_known_runtime_error_stages_without_exposing_message(self) -> None:
        cases = [
            (
                RuntimeError("truncated native stream header"),
                stable.EXIT_RELAY_NATIVE_STREAM_HEADER,
                "relay_native_stream_header",
            ),
            (
                RuntimeError("invalid native stream framing"),
                stable.EXIT_RELAY_NATIVE_STREAM_HEADER,
                "relay_native_stream_header",
            ),
            (
                RuntimeError("invalid native media record"),
                stable.EXIT_RELAY_NATIVE_MEDIA_RECORD,
                "relay_native_media_record",
            ),
            (
                RuntimeError("decrypted AAC payload has no native ADTS header"),
                stable.EXIT_RELAY_AUDIO_UNIT_VALIDATION,
                "relay_audio_unit_validation",
            ),
            (
                RuntimeError("AAC format changed during live session"),
                stable.EXIT_RELAY_AUDIO_FORMAT_CHANGED,
                "relay_audio_format_changed",
            ),
            (
                RuntimeError("Phase 2E expected H.264 codec id 78, got 999"),
                stable.EXIT_RELAY_VIDEO_UNIT_VALIDATION,
                "relay_video_unit_validation",
            ),
            (
                RuntimeError("Phase 2E received an unrecognized H.264 payload framing"),
                stable.EXIT_RELAY_VIDEO_UNIT_VALIDATION,
                "relay_video_unit_validation",
            ),
            (
                RuntimeError("failed to create native worker pipes"),
                stable.EXIT_RELAY_WORKER_PIPE_SETUP,
                "relay_worker_pipe_setup",
            ),
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

    def test_stage_marker_contains_only_fixed_safe_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marker"
            with patch.dict(
                os.environ,
                {stable.relay.CHILD_STATE_MARKER_ENV: str(path)},
                clear=False,
            ):
                stable._write_safe_child_state_marker(
                    True,
                    True,
                    "audio_pipe_write",
                )
            self.assertEqual(
                path.read_text(encoding="ascii"),
                "qemu_alive=1\n"
                "ffmpeg_alive=1\n"
                "relay_stage=audio_pipe_write\n",
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_stage_marker_rejects_unknown_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marker"
            with patch.dict(
                os.environ,
                {stable.relay.CHILD_STATE_MARKER_ENV: str(path)},
                clear=False,
            ):
                stable._write_safe_child_state_marker(True, True, "secret-data")
            self.assertEqual(
                path.read_text(encoding="ascii"),
                "qemu_alive=1\n"
                "ffmpeg_alive=1\n"
                "relay_stage=native_header_read\n",
            )

    def test_live_ffmpeg_command_bounds_interleave_buffering(self) -> None:
        original = [
            "ffmpeg",
            "-hide_banner",
            "-f",
            "mpegts",
            "pipe:1",
        ]
        bounded = stable._bound_live_interleave_command(original)
        self.assertIsInstance(bounded, list)
        assert isinstance(bounded, list)
        self.assertEqual(bounded[-1], "pipe:1")
        index = bounded.index("-max_interleave_delta")
        self.assertEqual(
            bounded[index + 1],
            str(stable.LIVE_MAX_INTERLEAVE_DELTA_US),
        )
        self.assertEqual(stable.LIVE_MAX_INTERLEAVE_DELTA_US, 500_000)
        self.assertNotIn("-max_interleave_delta", original)

    def test_non_pipe_command_is_not_modified(self) -> None:
        original = ["ffmpeg", "-f", "mpegts", "capture.ts"]
        self.assertEqual(stable._bound_live_interleave_command(original), original)


if __name__ == "__main__":
    unittest.main()
