import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.yi_pppp_pcap import analyze_capture


PHONE = "10.0.0.2"
PEER = "10.0.0.3"


def pppp(message_type, payload=b""):
    return struct.pack(">BBH", 0xF1, message_type, len(payload)) + payload


def tnp_ioctrl(command, payload, command_number=1, auth=None, version=2):
    auth = auth or (b"N" * 15 + b"," + b"H" * 15 + b"\0")
    assert len(auth) == 32
    body = struct.pack(">HHHH", command, command_number, 0, len(payload)) + auth + payload
    return struct.pack(">BBHI", version, 3, 0, len(body)) + body


def yi_drw(channel, sequence, application):
    payload = b"\0\0\xd1" + bytes([channel]) + sequence.to_bytes(2, "big") + application
    return pppp(0xD0, payload)


def cs2_drw(channel, sequence, application):
    return pppp(0xD0, b"\xd1" + bytes([channel]) + sequence.to_bytes(2, "big") + application)


def ipv4_udp(payload, source=PHONE, destination=PEER, source_port=40000, destination_port=50000):
    source_bytes = bytes(map(int, source.split(".")))
    destination_bytes = bytes(map(int, destination.split(".")))
    udp = struct.pack(">HHHH", source_port, destination_port, 8 + len(payload), 0) + payload
    ip = bytes([0x45, 0]) + struct.pack(">HHHBBH", 20 + len(udp), 1, 0, 64, 17, 0) + source_bytes + destination_bytes
    ethernet = b"\x02\0\0\0\0\x02\x02\0\0\0\0\x01\x08\x00"
    return ethernet + ip + udp


def pcap(records):
    result = bytearray(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
    for seconds, microseconds, packet in records:
        result.extend(struct.pack("<IIII", seconds, microseconds, len(packet), len(packet)))
        result.extend(packet)
    return bytes(result)


def pcapng(packet):
    def block(kind, body):
        padding = b"\0" * ((-len(body)) & 3)
        length = 12 + len(body) + len(padding)
        return struct.pack("<II", kind, length) + body + padding + struct.pack("<I", length)

    section = block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    interface = block(1, struct.pack("<HHI", 1, 0, 65535))
    enhanced = block(6, struct.pack("<IIIII", 0, 0, 1_000_000, len(packet), len(packet)) + packet)
    return section + interface + enhanced


class YiPpppPcapTests(unittest.TestCase):
    def analyze(self, capture):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.pcap"
            path.write_bytes(capture)
            return analyze_capture(path, PHONE)

    def test_decodes_expected_control_packet_lengths_and_sequence(self):
        packets = []
        for index, (command, payload) in enumerate(((9029, b"\1\0\1\0"), (4881, b"\0" * 8), (816, b"\0" * 4))):
            packets.append((10, index * 100_000, ipv4_udp(yi_drw(0, index, tnp_ioctrl(command, payload, index + 1)))))

        report = self.analyze(pcap(packets))
        flow = report["flows"][0]

        self.assertEqual(flow["first_three_phone_commands"], [9029, 4881, 816])
        self.assertEqual(flow["route_inference"], "MAIN")
        self.assertEqual(flow["drw_layouts"], ["YI_EXTENDED"])
        events = flow["control_events"]
        self.assertEqual([item["tnp"]["total_length"] for item in events], [52, 56, 52])
        self.assertEqual([item["message_length"] for item in events], [62, 66, 62])
        self.assertEqual(events[0]["tnp"]["ioctrl"]["auth"]["actual_authInfo_length"], 31)
        self.assertEqual(events[0]["tnp"]["ioctrl"]["auth"]["nonce_length"], 15)
        self.assertEqual(events[0]["tnp"]["ioctrl"]["auth"]["hmac_base64_component_length"], 15)

    def test_decodes_video_message_counts_and_pppp_message_types(self):
        video = struct.pack(">BBHI", 2, 1, 0, 92) + b"V" * 92
        records = [
            (20, 0, ipv4_udp(pppp(0xE0))),
            (20, 10_000, ipv4_udp(pppp(0xE1), PEER, PHONE, 50000, 40000)),
            (20, 15_000, ipv4_udp(yi_drw(1, 0, video), PEER, PHONE, 50000, 40000)),
            (20, 20_000, ipv4_udp(yi_drw(2, 0, video), PEER, PHONE, 50000, 40000)),
            (20, 30_000, ipv4_udp(yi_drw(3, 0, video), PEER, PHONE, 50000, 40000)),
            (20, 40_000, ipv4_udp(pppp(0xF0), PEER, PHONE, 50000, 40000)),
        ]

        flow = self.analyze(pcap(records))["flows"][0]

        self.assertEqual(flow["pppp_message_counts"]["MSG_P2P_ALIVE"], 1)
        self.assertEqual(flow["pppp_message_counts"]["MSG_P2P_ALIVE_ACK"], 1)
        self.assertEqual(flow["pppp_message_counts"]["MSG_CLOSE"], 1)
        self.assertEqual(flow["video_channels"]["1"]["drw_message_count"], 1)
        self.assertEqual(flow["video_channels"]["2"]["drw_message_count"], 1)
        self.assertEqual(flow["video_channels"]["3"]["drw_message_count"], 1)
        self.assertEqual(flow["video_channels"]["2"]["application_length_min"], 100)

    def test_supports_base_drw_and_pcapng(self):
        packet = ipv4_udp(cs2_drw(0, 7, tnp_ioctrl(9029, b"\1\0\1\0")))

        flow = self.analyze(pcapng(packet))["flows"][0]

        self.assertEqual(flow["drw_layouts"], ["CS2_BASE"])
        self.assertEqual(flow["first_three_phone_commands"], [9029])

    def test_decodes_tnp_v3_resolution_and_event_list_shapes(self):
        burst = b"".join((
            tnp_ioctrl(4881, b"\0\0\0\2\0\0\0\1", version=3),
            tnp_ioctrl(9029, b"\2\2\1\0", command_number=2, version=3),
            tnp_ioctrl(9031, b"\0" * 24, command_number=3, version=3),
        ))

        flow = self.analyze(pcap([(40, 0, ipv4_udp(cs2_drw(0, 0, burst))) ]))["flows"][0]
        events = flow["control_events"]

        self.assertEqual(flow["phone_command_sequence"], [4881, 9029, 9031])
        self.assertEqual([event["tnp"]["application_version"] for event in events], [3, 3, 3])
        self.assertEqual([event["tnp"]["total_length"] for event in events], [56, 52, 72])
        self.assertEqual(events[1]["tnp"]["ioctrl"]["fixed_payload"]["hex"], "02 02 01 00")
        self.assertEqual(events[2]["drw"]["batch_index"], 2)

    def test_reassembles_a_tnp_unit_across_drw_sequences(self):
        unit = tnp_ioctrl(9031, b"\0" * 24, version=2)
        records = [
            (50, 0, ipv4_udp(cs2_drw(0, 10, unit[:31]))),
            (50, 10_000, ipv4_udp(cs2_drw(0, 11, unit[31:]))),
        ]

        flow = self.analyze(pcap(records))["flows"][0]
        event = flow["control_events"][0]

        self.assertEqual(event["tnp"]["ioctrl"]["command"], 9031)
        self.assertEqual(event["tnp"]["total_length"], 72)
        self.assertEqual(event["drw"]["sequences"], [10, 11])
        self.assertEqual(event["drw"]["pppp_message_count"], 2)
        self.assertEqual(flow["reassembly_incomplete_bytes"], {})

    def test_reassembles_out_of_capture_order_by_drw_sequence(self):
        unit = tnp_ioctrl(9032, b"\0" * 80, version=2)
        records = [
            (55, 10_000, ipv4_udp(cs2_drw(0, 21, unit[40:]), PEER, PHONE, 50000, 40000)),
            (55, 20_000, ipv4_udp(cs2_drw(0, 20, unit[:40]), PEER, PHONE, 50000, 40000)),
        ]

        flow = self.analyze(pcap(records))["flows"][0]
        event = flow["control_events"][0]

        self.assertEqual(event["tnp"]["ioctrl"]["command"], 9032)
        self.assertEqual(event["drw"]["sequences"], [20, 21])
        self.assertEqual(flow["reassembly_incomplete_bytes"], {})

    def test_zero_reserved_control_payload_is_reported_without_bytes(self):
        unit = tnp_ioctrl(768, b"\0" * 8, version=2)

        event = self.analyze(pcap([(58, 0, ipv4_udp(cs2_drw(0, 0, unit)))]))["flows"][0]["control_events"][0]

        self.assertEqual(
            event["tnp"]["ioctrl"]["fixed_payload"],
            {"all_zero": True, "reserved_length": 8},
        )

    def test_reports_alive_payload_shape_without_raw_bytes(self):
        capture = pcap([(60, 0, ipv4_udp(pppp(0xE0, bytes.fromhex("A2050401"))))])

        alive = self.analyze(capture)["flows"][0]["alive"]

        self.assertEqual(alive["payload_lengths"], {"4": 1})
        self.assertEqual(alive["payload_u32_values"], ["0xA2050401"])
        self.assertEqual(alive["by_direction"]["PHONE_TO_PEER"]["count"], 1)

    def test_secret_bytes_never_appear_in_report(self):
        forbidden = [
            "YI_PASSWORD_MUST_NOT_APPEAR",
            "TRANSFORMED_PASSWORD_MUST_NOT_APPEAR",
            "TOKEN_MUST_NOT_APPEAR",
            "TOKEN_SECRET_MUST_NOT_APPEAR",
            "CAMERA_PASSWORD_MUST_NOT_APPEAR",
            "FULL_DID_MUST_NOT_APPEAR",
            "INIT_STRING_MUST_NOT_APPEAR",
            "LICENSE_MUST_NOT_APPEAR",
        ]
        auth = b"UID_SECRET_1234,TOKEN_SECRET_12\0"
        self.assertEqual(len(auth), 32)
        records = [(30, 0, ipv4_udp(yi_drw(0, 1, tnp_ioctrl(9029, b"\0" * 4, auth=auth))))]
        for index, secret in enumerate(forbidden, 1):
            records.append((30, index, ipv4_udp(pppp(0x41, secret.encode("ascii")))))

        encoded = json.dumps(self.analyze(pcap(records)))

        for secret in forbidden + [auth.decode("ascii", errors="ignore").rstrip("\0")]:
            self.assertNotIn(secret, encoded)


if __name__ == "__main__":
    unittest.main()
