from __future__ import annotations

import unittest

import yi_native_session_supervisor as supervisor


class YiNativeSessionSupervisorDiagnosticsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
