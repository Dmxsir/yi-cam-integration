from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yi_runtime_lifecycle as lifecycle


class _FakeProcess:
    def poll(self) -> int | None:
        return 0


class _FakeResponse:
    status = 200

    def read(self, size: int = -1) -> bytes:
        return b""


class _RecordingStream(io.BytesIO):
    def __init__(self, payload: bytes, events: list[str]) -> None:
        super().__init__(payload)
        self.events = events

    def read(self, size: int = -1) -> bytes:
        self.events.append("stream_read")
        return super().read(size)


class _FakeHTTPConnection:
    events: list[str] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.events.append("http_connection")
        self.sent = bytearray()

    def putrequest(self, method: str, path: str) -> None:
        self.events.append("putrequest")

    def putheader(self, name: str, value: str) -> None:
        pass

    def endheaders(self) -> None:
        self.events.append("endheaders")

    def send(self, data: bytes) -> None:
        self.sent.extend(data)

    def getresponse(self) -> _FakeResponse:
        return _FakeResponse()

    def close(self) -> None:
        pass


class YiRuntimeLifecyclePublisherTests(unittest.TestCase):
    def test_runtime_probe_lines_return_only_current_safe_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "camera.log"
            path.write_text("[phase3g-relay] native_record_probe=old\n", encoding="utf-8")
            offset = path.stat().st_size
            with path.open("a", encoding="utf-8") as stream:
                stream.write("secret native_record_probe=do-not-forward\n")
                stream.write("[phase3g-relay] native_record_probe=true; payload_logged=false\n")
                stream.write("[phase3g-relay] native_video_payload_probe=true; nal_types=7,8,5\n")

            lines = lifecycle._runtime_probe_lines(path, offset)

        self.assertEqual(
            lines,
            [
                "[phase3g-relay] native_record_probe=true; payload_logged=false",
                "[phase3g-relay] native_video_payload_probe=true; nal_types=7,8,5",
            ],
        )
        self.assertNotIn("secret", "".join(lines))

    def test_mpegts_is_prebuffered_before_http_ingest_is_opened(self) -> None:
        events: list[str] = []
        _FakeHTTPConnection.events = events
        payload = b"\x47" * 65536
        stream = _RecordingStream(payload, events)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = lifecycle.RuntimeLifecycleConfig(
                python=sys.executable,
                env_file=root / "env",
                runtime_root=root,
                worker_dir=root,
                stable_relay=root / "relay.py",
                supervisor=root / "supervisor.py",
                state_dir=root,
                media_ingest_host="127.0.0.1",
                media_ingest_port=11984,
            )
            controller = lifecycle._CameraRuntimeController(
                "e2f22804fecdbd8c3561",
                config,
            )

            with patch.object(lifecycle.http.client, "HTTPConnection", _FakeHTTPConnection):
                controller._publish_mpegts(stream, _FakeProcess())

        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0], "stream_read")
        self.assertLess(events.index("stream_read"), events.index("http_connection"))
        self.assertEqual(controller.published_bytes, 65536)
        self.assertIsNone(controller.publisher_error)


if __name__ == "__main__":
    unittest.main()
