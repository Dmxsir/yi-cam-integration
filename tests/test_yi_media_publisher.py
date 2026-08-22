from __future__ import annotations

import unittest

from yi_media_publisher import YiGo2RTCPublisher


class YiMediaPublisherSnapshotTests(unittest.TestCase):
    def test_registered_mpegts_without_medias_is_not_ready(self) -> None:
        snapshot = {
            "producers": [
                {
                    "format_name": "mpegts",
                    "medias": [],
                }
            ]
        }

        self.assertEqual(YiGo2RTCPublisher._registered_mpegts_producers(snapshot), 1)
        self.assertEqual(YiGo2RTCPublisher._ready_mpegts_producers(snapshot), 0)

    def test_registered_mpegts_with_media_is_ready(self) -> None:
        snapshot = {
            "producers": [
                {
                    "format_name": "mpegts",
                    "medias": [
                        {
                            "kind": "video",
                            "direction": "recvonly",
                        }
                    ],
                }
            ]
        }

        self.assertEqual(YiGo2RTCPublisher._registered_mpegts_producers(snapshot), 1)
        self.assertEqual(YiGo2RTCPublisher._ready_mpegts_producers(snapshot), 1)


if __name__ == "__main__":
    unittest.main()
