#!/usr/bin/env python3
"""Secret-safe Yi PPPP/TNP structural decoder for PCAP and PCAPNG files.

Only protocol metadata is retained.  Packet bodies, authentication bytes,
device IDs, licenses, passwords, and media bytes are never returned or saved.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


PPPP_TYPES = {
    0xD0: "MSG_DRW",
    0xD1: "MSG_DRW_ACK",
    0xE0: "MSG_P2P_ALIVE",
    0xE1: "MSG_P2P_ALIVE_ACK",
    0xF0: "MSG_CLOSE",
}

COMMANDS = {
    767: "STOP_VIDEO",
    768: "AUDIO_START",
    769: "AUDIO_STOP",
    816: "DEVICE_INFO",
    817: "DEVICE_INFO_RESPONSE",
    849: "SPEAKER_STOP",
    4864: "UPDATE_CHECK_PHONE",
    4865: "UPDATE_CHECK_PHONE_RESPONSE",
    4881: "SET_RESOLUTION",
    4882: "SET_RESOLUTION_RESPONSE",
    9029: "START_REALTIME",
    9031: "TNP_EVENT_LIST_REQUEST",
    9032: "TNP_EVENT_LIST_RESPONSE",
    12718: "RECORD_PLAYCONTROL2",
}


@dataclass(frozen=True)
class CapturedPacket:
    timestamp: float
    link_type: int
    data: bytes


@dataclass(frozen=True)
class TransportPayload:
    timestamp: float
    protocol: str
    source_ip: str
    source_port: int
    destination_ip: str
    destination_port: int
    data: bytes
    tcp_sequence: int | None = None


def _capture_packets(path: Path) -> Iterator[CapturedPacket]:
    data = path.read_bytes()
    if len(data) < 4:
        raise ValueError("capture is too short")
    if data[:4] == b"\x0a\x0d\x0d\x0a":
        yield from _pcapng_packets(data)
    else:
        yield from _pcap_packets(data)


def _pcap_packets(data: bytes) -> Iterator[CapturedPacket]:
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
    }
    try:
        endian, divisor = formats[data[:4]]
    except KeyError as error:
        raise ValueError("unsupported capture format") from error
    if len(data) < 24:
        raise ValueError("truncated PCAP header")
    link_type = struct.unpack_from(endian + "I", data, 20)[0]
    offset = 24
    while offset + 16 <= len(data):
        seconds, fraction, captured, _original = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        end = offset + captured
        if end > len(data):
            raise ValueError("truncated PCAP packet")
        yield CapturedPacket(seconds + fraction / divisor, link_type, data[offset:end])
        offset = end
    if offset != len(data):
        raise ValueError("trailing truncated PCAP record")


def _pcapng_options(body: bytes, offset: int, endian: str) -> dict[int, list[bytes]]:
    result: dict[int, list[bytes]] = defaultdict(list)
    while offset + 4 <= len(body):
        code, length = struct.unpack_from(endian + "HH", body, offset)
        offset += 4
        if code == 0:
            break
        end = offset + length
        if end > len(body):
            break
        result[code].append(body[offset:end])
        offset = (end + 3) & ~3
    return result


def _pcapng_packets(data: bytes) -> Iterator[CapturedPacket]:
    offset = 0
    endian: str | None = None
    interfaces: list[tuple[int, float]] = []
    while offset + 12 <= len(data):
        block_type_bytes = data[offset:offset + 4]
        if block_type_bytes == b"\x0a\x0d\x0d\x0a":
            if offset + 12 > len(data):
                raise ValueError("truncated PCAPNG section header")
            byte_order = data[offset + 8:offset + 12]
            if byte_order == b"\x4d\x3c\x2b\x1a":
                endian = "<"
            elif byte_order == b"\x1a\x2b\x3c\x4d":
                endian = ">"
            else:
                raise ValueError("invalid PCAPNG byte-order marker")
            block_length = struct.unpack_from(endian + "I", data, offset + 4)[0]
            interfaces = []
        else:
            if endian is None:
                raise ValueError("PCAPNG data precedes a section header")
            block_length = struct.unpack_from(endian + "I", data, offset + 4)[0]
        if block_length < 12 or offset + block_length > len(data):
            raise ValueError("invalid PCAPNG block length")
        if struct.unpack_from(endian + "I", data, offset + block_length - 4)[0] != block_length:
            raise ValueError("PCAPNG block length mismatch")
        block_type = struct.unpack_from(endian + "I", data, offset)[0]
        body = data[offset + 8:offset + block_length - 4]
        if block_type == 1 and len(body) >= 8:  # Interface Description Block
            link_type = struct.unpack_from(endian + "H", body, 0)[0]
            resolution = 1_000_000.0
            options = _pcapng_options(body, 8, endian)
            if options.get(9) and options[9][0]:
                value = options[9][0][0]
                resolution = float(2 ** (value & 0x7F) if value & 0x80 else 10 ** value)
            interfaces.append((link_type, resolution))
        elif block_type == 6 and len(body) >= 20:  # Enhanced Packet Block
            interface_id, high, low, captured, _original = struct.unpack_from(endian + "IIIII", body, 0)
            if interface_id >= len(interfaces) or 20 + captured > len(body):
                raise ValueError("invalid PCAPNG enhanced packet")
            link_type, resolution = interfaces[interface_id]
            timestamp = ((high << 32) | low) / resolution
            yield CapturedPacket(timestamp, link_type, body[20:20 + captured])
        offset += block_length
    if offset != len(data):
        raise ValueError("trailing truncated PCAPNG block")


def _network_packet(link_type: int, data: bytes) -> bytes | None:
    if link_type == 1:  # Ethernet
        if len(data) < 14:
            return None
        offset = 14
        ether_type = int.from_bytes(data[12:14], "big")
        while ether_type in (0x8100, 0x88A8, 0x9100) and len(data) >= offset + 4:
            ether_type = int.from_bytes(data[offset + 2:offset + 4], "big")
            offset += 4
        return data[offset:] if ether_type in (0x0800, 0x86DD) else None
    if link_type in (101, 228, 229):  # Raw IP / IPv4 / IPv6
        return data
    if link_type == 113:  # Linux cooked capture v1
        if len(data) < 16:
            return None
        return data[16:] if int.from_bytes(data[14:16], "big") in (0x0800, 0x86DD) else None
    if link_type == 276:  # Linux cooked capture v2
        if len(data) < 20:
            return None
        return data[20:] if int.from_bytes(data[0:2], "big") in (0x0800, 0x86DD) else None
    return None


def _transport(packet: CapturedPacket) -> TransportPayload | None:
    data = _network_packet(packet.link_type, packet.data)
    if not data:
        return None
    version = data[0] >> 4
    if version == 4:
        if len(data) < 20:
            return None
        header_length = (data[0] & 0x0F) * 4
        total_length = int.from_bytes(data[2:4], "big")
        fragment = int.from_bytes(data[6:8], "big")
        if header_length < 20 or total_length < header_length or len(data) < total_length or fragment & 0x3FFF:
            return None
        protocol = data[9]
        source_ip = str(ipaddress.ip_address(data[12:16]))
        destination_ip = str(ipaddress.ip_address(data[16:20]))
        payload = data[header_length:total_length]
    elif version == 6:
        if len(data) < 40:
            return None
        payload_length = int.from_bytes(data[4:6], "big")
        if len(data) < 40 + payload_length:
            return None
        protocol = data[6]
        source_ip = str(ipaddress.ip_address(data[8:24]))
        destination_ip = str(ipaddress.ip_address(data[24:40]))
        payload = data[40:40 + payload_length]
    else:
        return None
    if protocol == 17 and len(payload) >= 8:
        source_port, destination_port, length = struct.unpack_from(">HHH", payload, 0)
        if length < 8 or length > len(payload):
            return None
        return TransportPayload(packet.timestamp, "UDP", source_ip, source_port, destination_ip, destination_port, payload[8:length])
    if protocol == 6 and len(payload) >= 20:
        source_port, destination_port = struct.unpack_from(">HH", payload, 0)
        sequence = int.from_bytes(payload[4:8], "big")
        header_length = (payload[12] >> 4) * 4
        if header_length < 20 or header_length > len(payload):
            return None
        return TransportPayload(packet.timestamp, "TCP", source_ip, source_port, destination_ip, destination_port, payload[header_length:], sequence)
    return None


def _pppp_messages(data: bytes) -> Iterator[tuple[int, int, bytes, int]]:
    """Yield (header variant, type, payload, total length) without retaining bytes."""
    offset = 0
    while offset + 4 <= len(data):
        if data[offset] not in (0xF1, 0xF2):
            break
        variant = data[offset]
        message_type = data[offset + 1]
        payload_length = int.from_bytes(data[offset + 2:offset + 4], "big")
        header_length = 4 if variant == 0xF1 else 28
        end = offset + header_length + payload_length
        if end > len(data):
            break
        yield variant, message_type, data[offset + header_length:end], header_length + payload_length
        offset = end


def _drw(payload: bytes) -> tuple[str, int, int, bytes] | None:
    # Yi firmware analyzed by Talos places D1 at message offset 6 (payload +2).
    # The related CS2 layout places it at payload offset 0.  Supporting both is
    # structural detection, not a protocol guess; the selected layout is reported.
    if len(payload) >= 6 and payload[2] == 0xD1:
        return "YI_EXTENDED", payload[3], int.from_bytes(payload[4:6], "big"), payload[6:]
    if len(payload) >= 4 and payload[0] == 0xD1:
        return "CS2_BASE", payload[1], int.from_bytes(payload[2:4], "big"), payload[4:]
    return None


def _auth_shape(field: bytes) -> dict[str, int | bool | str]:
    terminator = field.find(b"\x00")
    actual = field if terminator < 0 else field[:terminator]
    comma = actual.find(b",")
    result: dict[str, int | bool | str] = {
        "authInfo_field_size": len(field),
        "actual_authInfo_length": len(actual),
        "zero_terminated": terminator >= 0,
    }
    if comma >= 0:
        result.update({
            "shape": "TWO_COMPONENT_ASCII",
            "nonce_length": comma,
            "hmac_base64_component_length": len(actual) - comma - 1,
        })
    else:
        result["shape"] = "BINARY_OR_EMPTY"
        result["auth_result"] = int.from_bytes(field[:4], "big") if len(field) >= 4 else 0
    return result


def _fixed_payload(command: int, payload: bytes) -> dict[str, object] | None:
    if command in (767, 768, 769, 849) and len(payload) == 8:
        return {
            "all_zero": payload == b"\0" * 8,
            "reserved_length": 8,
        }
    if command == 9029 and len(payload) == 4:
        return {
            "hex": " ".join(f"{value:02X}" for value in payload),
            "use_count": payload[0],
            "resolution": payload[1],
            "command_version": payload[2],
            "reserved": payload[3],
        }
    if command == 4881 and len(payload) == 8:
        return {
            "resolution": int.from_bytes(payload[:4], "big"),
            "use_count": int.from_bytes(payload[4:], "big"),
        }
    return None


def _tnp(application: bytes) -> dict[str, object] | None:
    if len(application) < 8:
        return None
    version, stream_type = application[0], application[1]
    data_size = int.from_bytes(application[4:8], "big")
    complete = data_size == len(application) - 8
    result: dict[str, object] = {
        "total_length": len(application),
        "outer_header_size": 8,
        "application_version": version,
        "stream_type": stream_type,
        "reserved_zero": application[2:4] == b"\0\0",
        "declared_data_size": data_size,
        "complete_reassembled": complete,
    }
    if stream_type != 3 or len(application) < 48:
        return result
    command, command_number, extra_size, payload_size = struct.unpack_from(">HHHH", application, 8)
    ioctrl: dict[str, object] = {
        "header_size": 40,
        "command": command,
        "command_name": COMMANDS.get(command, "UNKNOWN"),
        "command_number": command_number,
        "extra_header_size": extra_size,
        "payload_length": payload_size,
        "auth": _auth_shape(application[16:48]),
        "length_consistent": data_size == 40 + extra_size + payload_size,
    }
    payload_offset = 48 + extra_size
    if payload_offset + payload_size <= len(application):
        fixed = _fixed_payload(command, application[payload_offset:payload_offset + payload_size])
        if fixed is not None:
            ioctrl["fixed_payload"] = fixed
    result["ioctrl"] = ioctrl
    return result


def _frame_shape(application: bytes) -> dict[str, object] | None:
    tnp = _tnp(application)
    if not tnp or not tnp.get("complete_reassembled") or tnp.get("stream_type") not in (1, 2):
        return None
    shape: dict[str, object] = {
        "application_version": tnp["application_version"],
        "stream_type": tnp["stream_type"],
        "total_length": tnp["total_length"],
        "declared_data_size": tnp["declared_data_size"],
    }
    if tnp["stream_type"] == 1 and len(application) >= 32:
        frame = application[8:32]
        shape.update({
            "frame_header_size": 24,
            "codec_id": int.from_bytes(frame[0:2], "big"),
            "flags": frame[2],
            "live_flag": frame[3],
            "online_count": frame[4],
            "use_count": frame[5],
            "sequence": int.from_bytes(frame[6:8], "big"),
            "width": int.from_bytes(frame[8:10], "big"),
            "height": int.from_bytes(frame[10:12], "big"),
        })
    return shape


def _reassemble_tnp(events: list[dict[str, object]]) -> tuple[list[dict[str, object]], int, int]:
    """Reassemble complete TNP units while discarding all returned packet bytes."""
    units: list[dict[str, object]] = []
    buffer = bytearray()
    first_event: dict[str, object] | None = None
    sequences: list[int] = []
    malformed = 0
    batch_index = 0
    for event in events:
        application = event.get("_application")
        if not isinstance(application, bytes):
            continue
        if not buffer:
            first_event = event
            sequences = []
            batch_index = 0
        buffer.extend(application)
        sequence = int(event["drw"]["sequence"])
        if not sequences or sequences[-1] != sequence:
            sequences.append(sequence)
        while len(buffer) >= 8:
            version, stream_type = buffer[0], buffer[1]
            data_size = int.from_bytes(buffer[4:8], "big")
            if version not in (1, 2, 3) or stream_type not in (1, 2, 3) or data_size > 8 * 1024 * 1024:
                malformed += 1
                buffer.clear()
                first_event = None
                sequences = []
                break
            total = 8 + data_size
            if len(buffer) < total:
                break
            application_unit = bytes(buffer[:total])
            del buffer[:total]
            assert first_event is not None
            parsed_tnp = _tnp(application_unit)
            unit = {
                "direction": first_event["direction"],
                "header_variant": first_event["header_variant"],
                "message_type": first_event["message_type"],
                "message_length": first_event["message_length"],
                "relative_ms": first_event["relative_ms"],
                "drw": {
                    "layout": first_event["drw"]["layout"],
                    "channel": first_event["drw"]["channel"],
                    "sequence": first_event["drw"]["sequence"],
                    "sequences": list(sequences),
                    "pppp_message_count": len(sequences),
                    "batch_index": batch_index,
                    "application_length": total,
                },
                "tnp": parsed_tnp,
            }
            frame_shape = _frame_shape(application_unit)
            if frame_shape is not None:
                unit["frame_shape"] = frame_shape
            units.append(unit)
            batch_index += 1
            if buffer:
                first_event = event
                sequences = [sequence]
            else:
                first_event = None
                sequences = []
    return units, len(buffer), malformed


def _endpoint_key(ip: str, port: int) -> tuple[int, bytes, int]:
    address = ipaddress.ip_address(ip)
    return address.version, address.packed, port


def _flow_key(item: TransportPayload) -> tuple[str, tuple[str, int], tuple[str, int]]:
    first = (item.source_ip, item.source_port)
    second = (item.destination_ip, item.destination_port)
    if _endpoint_key(*first) > _endpoint_key(*second):
        first, second = second, first
    return item.protocol, first, second


def _tcp_streams(items: Iterable[TransportPayload]) -> Iterator[TransportPayload]:
    groups: dict[tuple[str, int, str, int], list[TransportPayload]] = defaultdict(list)
    for item in items:
        if item.data:
            groups[(item.source_ip, item.source_port, item.destination_ip, item.destination_port)].append(item)
    for segments in groups.values():
        segments.sort(key=lambda item: item.tcp_sequence or 0)
        data = bytearray()
        start = segments[0].tcp_sequence or 0
        timestamp = segments[0].timestamp
        expected = start
        for segment in segments:
            sequence = segment.tcp_sequence or 0
            end = sequence + len(segment.data)
            if end <= expected:
                continue
            if sequence > expected:
                break
            overlap = max(0, expected - sequence)
            data.extend(segment.data[overlap:])
            expected = end
        first = segments[0]
        yield TransportPayload(timestamp, "TCP", first.source_ip, first.source_port, first.destination_ip, first.destination_port, bytes(data), start)


def analyze_capture(path: Path, phone_ip: str | None = None) -> dict[str, object]:
    packets = list(_capture_packets(path))
    transports = [item for packet in packets if (item := _transport(packet)) is not None]
    datagrams = [item for item in transports if item.protocol == "UDP" and item.data]
    datagrams.extend(_tcp_streams(item for item in transports if item.protocol == "TCP"))

    grouped: dict[tuple[str, tuple[str, int], tuple[str, int]], list[dict[str, object]]] = defaultdict(list)
    for item in datagrams:
        for variant, message_type, payload, total_length in _pppp_messages(item.data):
            event: dict[str, object] = {
                "timestamp": item.timestamp,
                "direction_endpoints": ((item.source_ip, item.source_port), (item.destination_ip, item.destination_port)),
                "header_variant": f"F{variant & 0x0F}",
                "message_type": PPPP_TYPES.get(message_type, f"0x{message_type:02X}"),
                "message_length": total_length,
                "payload_length": len(payload),
            }
            if message_type == 0xE0 and len(payload) == 4:
                event["payload_u32_hex"] = f"0x{int.from_bytes(payload, 'big'):08X}"
            if message_type == 0xD0 and (parsed := _drw(payload)) is not None:
                layout, channel, sequence, application = parsed
                event["drw"] = {
                    "layout": layout,
                    "channel": channel,
                    "sequence": sequence,
                    "application_length": len(application),
                }
                event["_application"] = application
            grouped[_flow_key(item)].append(event)

    flows = []
    for (protocol, endpoint_a, endpoint_b), events in sorted(grouped.items(), key=lambda pair: str(pair[0])):
        events.sort(key=lambda event: float(event["timestamp"]))
        start = float(events[0]["timestamp"])
        counts = Counter(str(event["message_type"]) for event in events)
        payload_lengths_by_type = {
            message_type: dict(sorted(Counter(
                str(event["payload_length"])
                for event in events
                if event["message_type"] == message_type
            ).items()))
            for message_type in sorted(counts)
        }
        channel_events: dict[int, list[dict[str, object]]] = defaultdict(list)
        unique_channel_events: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
        seen_drw: set[tuple[str, int, int, bytes]] = set()
        retransmissions = 0
        for event in events:
            source, destination = event.pop("direction_endpoints")  # fixed metadata only
            if phone_ip:
                direction = "PHONE_TO_PEER" if source[0] == phone_ip else "PEER_TO_PHONE" if destination[0] == phone_ip else "OTHER"
            else:
                direction = "A_TO_B" if source == endpoint_a else "B_TO_A"
            event["direction"] = direction
            event["relative_ms"] = round((float(event.pop("timestamp")) - start) * 1000, 3)
            if isinstance(event.get("drw"), dict):
                channel = int(event["drw"]["channel"])
                channel_events[channel].append(event)
                application = event.get("_application")
                if isinstance(application, bytes):
                    identity = (direction, channel, int(event["drw"]["sequence"]), application)
                    if identity in seen_drw:
                        retransmissions += 1
                    else:
                        seen_drw.add(identity)
                        unique_channel_events[(direction, channel)].append(event)

        reassembled: dict[int, list[dict[str, object]]] = defaultdict(list)
        incomplete: dict[str, int] = {}
        malformed: dict[str, int] = {}
        for (direction, channel), selected in unique_channel_events.items():
            selected.sort(key=lambda event: int(event["drw"]["sequence"]))
            units, remaining, bad = _reassemble_tnp(selected)
            reassembled[channel].extend(units)
            key = f"{direction}:channel_{channel}"
            if remaining:
                incomplete[key] = remaining
            if bad:
                malformed[key] = bad
        for selected in reassembled.values():
            selected.sort(key=lambda event: float(event["relative_ms"]))

        control = [
            event for event in reassembled.get(0, [])
            if isinstance(event.get("tnp"), dict) and isinstance(event["tnp"].get("ioctrl"), dict)
        ]
        video = {}
        for channel in (1, 2, 3):
            selected = channel_events.get(channel, [])
            unique = [
                event
                for (_direction, selected_channel), items in unique_channel_events.items()
                if selected_channel == channel
                for event in items
            ]
            units = reassembled.get(channel, [])
            frame_units = [unit for unit in units if isinstance(unit.get("frame_shape"), dict)]
            use_counts = Counter(
                str(unit["frame_shape"]["use_count"])
                for unit in frame_units
                if "use_count" in unit["frame_shape"]
            )
            first_by_use_count: dict[str, float] = {}
            dimensions = Counter()
            for unit in frame_units:
                shape = unit["frame_shape"]
                if "use_count" in shape:
                    first_by_use_count.setdefault(str(shape["use_count"]), float(unit["relative_ms"]))
                if "width" in shape and "height" in shape:
                    dimensions[f"{shape['width']}x{shape['height']}"] += 1
            video[str(channel)] = {
                "drw_message_count": len(selected),
                "unique_drw_message_count": len(unique),
                "tnp_unit_count": len(units),
                "first_data_relative_ms": selected[0]["relative_ms"] if selected else None,
                "first_unit_relative_ms": units[0]["relative_ms"] if units else None,
                "application_length_min": min((event["drw"]["application_length"] for event in selected), default=None),
                "application_length_max": max((event["drw"]["application_length"] for event in selected), default=None),
                "first_frame_shape": units[0].get("frame_shape") if units else None,
                "frame_use_count_counts": dict(sorted(use_counts.items())),
                "first_frame_by_use_count_relative_ms": dict(sorted(first_by_use_count.items())),
                "frame_dimensions": dict(sorted(dimensions.items())),
            }
        phone_writes = [event for event in control if event["direction"] == "PHONE_TO_PEER"] if phone_ip else control
        sequence = [event["tnp"]["ioctrl"]["command"] for event in phone_writes]
        first_phone_ms = float(phone_writes[0]["relative_ms"]) if phone_writes else None
        if first_phone_ms is not None:
            for event in control:
                event["relative_to_first_phone_command_ms"] = round(float(event["relative_ms"]) - first_phone_ms, 3)
            for channel in video.values():
                for field in ("first_data_relative_ms", "first_unit_relative_ms"):
                    value = channel.get(field)
                    channel[field.replace("relative_ms", "relative_to_first_phone_command_ms")] = (
                        round(float(value) - first_phone_ms, 3) if value is not None else None
                    )
                channel["first_frame_by_use_count_relative_to_first_phone_command_ms"] = {
                    key: round(float(value) - first_phone_ms, 3)
                    for key, value in channel["first_frame_by_use_count_relative_ms"].items()
                }
        first = sequence[0] if sequence else None
        route = "MAIN" if first == 9029 else "BALL" if first == 4881 else "UNKNOWN"
        peer = None
        if phone_ip:
            peer = endpoint_b if endpoint_a[0] == phone_ip else endpoint_a if endpoint_b[0] == phone_ip else None
        connection_mode = "DIRECT_P2P" if peer and ipaddress.ip_address(peer[0]).is_private else "UNKNOWN"
        alive = [event for event in events if event["message_type"] == "MSG_P2P_ALIVE"]
        alive_by_direction = {}
        for direction in sorted({str(event["direction"]) for event in alive}):
            selected_alive = [event for event in alive if event["direction"] == direction]
            alive_by_direction[direction] = {
                "count": len(selected_alive),
                "payload_lengths": dict(sorted(Counter(str(event["payload_length"]) for event in selected_alive).items())),
                "payload_u32_values": sorted({
                    str(event["payload_u32_hex"])
                    for event in selected_alive
                    if "payload_u32_hex" in event
                }),
            }
        flows.append({
            "transport": protocol,
            "endpoint_a": {"ip": endpoint_a[0], "port": endpoint_a[1]},
            "endpoint_b": {"ip": endpoint_b[0], "port": endpoint_b[1]},
            "peer": {"ip": peer[0], "port": peer[1]} if peer else None,
            "connection_mode": connection_mode,
            "pppp_message_counts": dict(sorted(counts.items())),
            "pppp_payload_lengths_by_type": payload_lengths_by_type,
            "alive": {
                "count": len(alive),
                "payload_lengths": dict(sorted(Counter(str(event["payload_length"]) for event in alive).items())),
                "payload_u32_values": sorted({str(event["payload_u32_hex"]) for event in alive if "payload_u32_hex" in event}),
                "by_direction": alive_by_direction,
            },
            "drw_retransmission_count": retransmissions,
            "drw_layouts": sorted({event["drw"]["layout"] for event in events if isinstance(event.get("drw"), dict)}),
            "control_events": control,
            "first_three_phone_commands": sequence[:3],
            "phone_command_sequence": sequence,
            "route_inference": route,
            "video_channels": video,
            "reassembly_incomplete_bytes": incomplete,
            "reassembly_malformed_units": malformed,
        })
    return {
        "report_version": 1,
        "decoder": "YI_PPPP_TNP_SECRET_SAFE",
        "packets_read": len(packets),
        "transport_payloads": len(transports),
        "pppp_flow_count": len(flows),
        "phone_ip_configured": phone_ip is not None,
        "flows": flows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secret-safe Yi PPPP/TNP PCAP structure decoder")
    parser.add_argument("capture", type=Path, help="PCAP or PCAPNG file")
    parser.add_argument("--phone-ip", help="phone VPN/LAN address used only to label direction")
    parser.add_argument("--output", type=Path, help="write the sanitized JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = analyze_capture(args.capture, args.phone_ip)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
