from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yi_native_session_supervisor as supervisor


class YiNativeSessionSupervisorDiagnosticsTests(unittest.TestCase):
    def test_startup_stall_has_distinct_code(self) -> None:
        self.assertEqual(supervisor.EXIT_STARTUP_STALL, 74)
        self.assertNotEqual(supervisor.EXIT_STARTUP_STALL, supervisor.EXIT_MEDIA_STALL)

    def test_process_state_unavailable_preserves_generic_media_stall_code(self) -> None:
        self.assertEqual(
            supervisor._classify_stall_processes(None),
            (supervisor.EXIT_MEDIA_STALL, "process_state_unavailable"),
        )

    def test_classifies_qemu_and_ffmpeg_alive(self) -> None:
        self.assertEqual(
            supervisor._classify_stall_processes({"qemu-aarch64", "ffmpeg"}),
            (
                supervisor.EXIT_MEDIA_STALL_QEMU_FFMPEG_ALIVE,
                "qemu_alive_ffmpeg_alive",
            ),
        )

    def test_classifies_qemu_alive_ffmpeg_missing(self) -> None:
        self.assertEqual(
            supervisor._classify_stall_processes({"qemu-aarch64"}),
            (
                supervisor.EXIT_MEDIA_STALL_QEMU_ALIVE_FFMPEG_MISSING,
                "qemu_alive_ffmpeg_missing",
            ),
        )

    def test_classifies_qemu_missing_ffmpeg_alive(self) -> None:
        self.assertEqual(
            supervisor._classify_stall_processes({"ffmpeg"}),
            (
                supervisor.EXIT_MEDIA_STALL_QEMU_MISSING_FFMPEG_ALIVE,
                "qemu_missing_ffmpeg_alive",
            ),
        )

    def test_classifies_qemu_and_ffmpeg_missing(self) -> None:
        self.assertEqual(
            supervisor._classify_stall_processes(set()),
            (
                supervisor.EXIT_MEDIA_STALL_QEMU_FFMPEG_MISSING,
                "qemu_missing_ffmpeg_missing",
            ),
        )

    def test_reads_secret_safe_relay_state_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            path.write_text(
                "qemu_alive=1\nffmpeg_alive=0\n",
                encoding="ascii",
            )
            self.assertEqual(
                supervisor._read_child_state_marker(path),
                {"qemu-aarch64"},
            )

    def test_media_stall_prefers_relay_marker_over_proc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state"
            path.write_text(
                "qemu_alive=1\nffmpeg_alive=1\n",
                encoding="ascii",
            )
            with patch.object(supervisor, "_descendant_comms") as proc_snapshot:
                self.assertEqual(
                    supervisor._media_stall_diagnostic(12345, path),
                    (
                        supervisor.EXIT_MEDIA_STALL_QEMU_FFMPEG_ALIVE,
                        "qemu_alive_ffmpeg_alive",
                        "relay_marker",
                    ),
                )
            proc_snapshot.assert_not_called()

    def test_media_stall_falls_back_to_proc_when_marker_unavailable(self) -> None:
        with patch.object(
            supervisor,
            "_descendant_comms",
            return_value={"ffmpeg"},
        ):
            self.assertEqual(
                supervisor._media_stall_diagnostic(12345, None),
                (
                    supervisor.EXIT_MEDIA_STALL_QEMU_MISSING_FFMPEG_ALIVE,
                    "qemu_missing_ffmpeg_alive",
                    "proc_fallback",
                ),
            )


if __name__ == "__main__":
    unittest.main()
