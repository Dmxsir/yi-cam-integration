from __future__ import annotations

import unittest

from yi_live_relay import SequenceReorderBuffer


class YiLiveRelayTests(unittest.TestCase):
    @staticmethod
    def frame(sequence: int, frame_type: str = "P") -> dict:
        return {
            "sequence": sequence,
            "frame_type": frame_type,
            "output_payload": b"x",
        }

    def test_starts_on_first_iframe_and_keeps_forward_prestart_frame(self) -> None:
        reorder = SequenceReorderBuffer(max_pending=8, max_wait_seconds=1.0)
        self.assertEqual(reorder.push(self.frame(101), now=0.00), [])
        ready = reorder.push(self.frame(100, "I"), now=0.01)
        self.assertEqual([item["sequence"] for item in ready], [100, 101])

    def test_interleaved_channels_are_emitted_in_sequence_order(self) -> None:
        reorder = SequenceReorderBuffer(max_pending=8, max_wait_seconds=1.0)
        self.assertEqual([item["sequence"] for item in reorder.push(self.frame(100, "I"), now=0.0)], [100])
        self.assertEqual(reorder.push(self.frame(102), now=0.01), [])
        ready = reorder.push(self.frame(101), now=0.02)
        self.assertEqual([item["sequence"] for item in ready], [101, 102])

    def test_uint16_sequence_wrap(self) -> None:
        reorder = SequenceReorderBuffer(max_pending=8, max_wait_seconds=1.0)
        first = reorder.push(self.frame(65535, "I"), now=0.0)
        second = reorder.push(self.frame(0), now=0.01)
        self.assertEqual([item["sequence"] for item in first], [65535])
        self.assertEqual([item["sequence"] for item in second], [0])

    def test_duplicate_is_suppressed(self) -> None:
        reorder = SequenceReorderBuffer(max_pending=8, max_wait_seconds=1.0)
        self.assertEqual([item["sequence"] for item in reorder.push(self.frame(10, "I"), now=0.0)], [10])
        self.assertEqual(reorder.push(self.frame(10, "I"), now=0.01), [])
        self.assertEqual([item["sequence"] for item in reorder.push(self.frame(11), now=0.02)], [11])

    def test_gap_is_bounded_and_advances_after_wait(self) -> None:
        reorder = SequenceReorderBuffer(max_pending=8, max_wait_seconds=0.2)
        self.assertEqual([item["sequence"] for item in reorder.push(self.frame(50, "I"), now=0.0)], [50])
        self.assertEqual(reorder.push(self.frame(52), now=0.05), [])
        ready = reorder.push(self.frame(53), now=0.30)
        self.assertEqual([item["sequence"] for item in ready], [52, 53])


if __name__ == "__main__":
    unittest.main()
