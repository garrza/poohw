"""Tests for decoders/packet.py — PacketDecoder and WhoopPacket dataclass."""

import struct

import pytest

from poohw.protocol import (
    SOF,
    HEADER_SIZE,
    CRC32_SIZE,
    MIN_PACKET_SIZE,
    PacketType,
    Command,
    build_packet,
)
from poohw.decoders.packet import PacketDecoder, WhoopPacket


# ===================================================================
# WhoopPacket properties
# ===================================================================


class TestWhoopPacketHex:
    def test_hex_property(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(pkt)
        assert wp.hex == pkt.hex()

    def test_hex_is_lowercase(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(pkt)
        assert wp.hex == wp.hex.lower()


class TestWhoopPacketTypeName:
    def test_known_type(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(pkt)
        assert wp.type_name == "COMMAND"

    def test_all_known_types(self):
        for pt in PacketType:
            pkt = build_packet(pt, 0x01)
            wp = PacketDecoder.decode(pkt)
            assert wp.type_name == pt.name

    def test_unknown_type_hex_fallback(self):
        pkt = build_packet(0xFE, 0x01)
        wp = PacketDecoder.decode(pkt)
        assert wp.type_name == "0xFE"

    def test_none_type_returns_question_mark(self):
        """A manually crafted WhoopPacket with None type."""
        wp = WhoopPacket(
            raw=b"", packet_type=None, seq=None, command_id=None,
            payload=b"", crc8_valid=True, crc32_value=None,
            crc32_valid=None, complete=False,
        )
        assert wp.type_name == "?"


class TestWhoopPacketCommandName:
    def test_known_command(self):
        pkt = build_packet(PacketType.COMMAND, Command.TOGGLE_REALTIME_HR, b"\x01")
        wp = PacketDecoder.decode(pkt)
        assert wp.command_name == "TOGGLE_REALTIME_HR"

    def test_unknown_command_hex_fallback(self):
        pkt = build_packet(PacketType.COMMAND, 0xFE)
        wp = PacketDecoder.decode(pkt)
        assert wp.command_name == "0xFE"

    def test_none_command_returns_question_mark(self):
        wp = WhoopPacket(
            raw=b"", packet_type=None, seq=None, command_id=None,
            payload=b"", crc8_valid=True, crc32_value=None,
            crc32_valid=None, complete=False,
        )
        assert wp.command_name == "?"


class TestWhoopPacketRepr:
    def test_repr_valid_complete(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(pkt)
        r = repr(wp)
        assert "WhoopPacket" in r
        assert "COMMAND" in r
        assert "GET_HELLO" in r
        assert "crc32=OK" in r
        assert "INCOMPLETE" not in r

    def test_repr_bad_crc(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_HELLO))
        pkt[-1] ^= 0xFF
        wp = PacketDecoder.decode(bytes(pkt))
        r = repr(wp)
        assert "crc32=BAD" in r

    def test_repr_incomplete(self):
        wp = WhoopPacket(
            raw=b"", packet_type=0x23, seq=0, command_id=0x91,
            payload=b"", crc8_valid=True, crc32_value=None,
            crc32_valid=None, complete=False,
        )
        r = repr(wp)
        assert "INCOMPLETE" in r

    def test_repr_with_payload(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL, b"\xDE\xAD")
        wp = PacketDecoder.decode(pkt)
        r = repr(wp)
        assert "payload=dead" in r


# ===================================================================
# PacketDecoder.decode
# ===================================================================


class TestPacketDecoderDecode:
    def test_valid_packet(self):
        pkt = build_packet(PacketType.COMMAND, Command.RUN_ALARM, b"\x00")
        wp = PacketDecoder.decode(pkt)
        assert isinstance(wp, WhoopPacket)
        assert wp.packet_type == PacketType.COMMAND
        assert wp.command_id == Command.RUN_ALARM
        assert wp.payload == b"\x00"
        assert wp.crc8_valid is True
        assert wp.crc32_valid is True
        assert wp.complete is True

    def test_too_short_returns_none(self):
        assert PacketDecoder.decode(b"\xAA") is None
        assert PacketDecoder.decode(b"") is None
        assert PacketDecoder.decode(b"\xAA\x00\x00") is None

    def test_bad_sof_returns_none(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        assert PacketDecoder.decode(b"\x00" + pkt[1:]) is None

    def test_accepts_bytearray(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(bytearray(pkt))
        assert wp is not None
        assert wp.crc32_valid is True

    def test_corrupted_crc8(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_HELLO))
        pkt[3] ^= 0xFF
        wp = PacketDecoder.decode(bytes(pkt))
        assert wp is not None
        assert wp.crc8_valid is False

    def test_corrupted_crc32(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_HELLO))
        pkt[-1] ^= 0xFF
        wp = PacketDecoder.decode(bytes(pkt))
        assert wp is not None
        assert wp.crc32_valid is False

    def test_negative_inner_size_returns_none(self):
        # LENGTH = 0x0002 → inner_size = 2 - 4 = -2
        raw = bytes([SOF, 0x02, 0x00, 0x00] + [0x00] * 4)
        assert PacketDecoder.decode(raw) is None

    def test_incomplete_packet(self):
        """Packet with valid header but missing CRC-32 trailer."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        truncated = pkt[:-3]
        wp = PacketDecoder.decode(truncated)
        assert wp is not None
        assert wp.complete is False
        assert wp.crc32_valid is None
        assert wp.crc32_value is None

    def test_preserves_raw_bytes(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(pkt)
        assert wp.raw == pkt

    def test_various_payload_sizes(self):
        for size in (0, 1, 10, 50, 200):
            data = bytes([0xAB] * size)
            pkt = build_packet(PacketType.COMMAND, 0x01, data)
            wp = PacketDecoder.decode(pkt)
            assert wp.payload == data
            assert wp.crc32_valid is True


# ===================================================================
# PacketDecoder.decode_stream
# ===================================================================


class TestDecodeStream:
    def test_multiple_packets(self):
        pkt1 = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        pkt2 = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        pkt3 = build_packet(PacketType.COMMAND, Command.RUN_ALARM, b"\x00")
        stream = pkt1 + pkt2 + pkt3
        packets = PacketDecoder.decode_stream(stream)
        assert len(packets) == 3
        assert packets[0].command_id == Command.GET_BATTERY_LEVEL
        assert packets[1].command_id == Command.GET_HELLO
        assert packets[2].command_id == Command.RUN_ALARM

    def test_garbage_between_packets(self):
        pkt1 = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        pkt2 = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        stream = b"\x00\x01\x02" + pkt1 + b"\xFF\xFE" + pkt2 + b"\x00"
        packets = PacketDecoder.decode_stream(stream)
        assert len(packets) == 2

    def test_empty_stream(self):
        assert PacketDecoder.decode_stream(b"") == []

    def test_single_packet(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        packets = PacketDecoder.decode_stream(pkt)
        assert len(packets) == 1

    def test_truncated_tail_skipped(self):
        """A valid packet followed by an incomplete one yields only the first."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        partial = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)[:-3]
        stream = pkt + partial
        packets = PacketDecoder.decode_stream(stream)
        assert len(packets) == 1
        assert packets[0].command_id == Command.GET_HELLO

    def test_accepts_bytearray(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        packets = PacketDecoder.decode_stream(bytearray(pkt))
        assert len(packets) == 1

    def test_only_garbage(self):
        assert PacketDecoder.decode_stream(b"\x01\x02\x03\x04\x05") == []

    def test_sof_byte_in_payload_does_not_false_start(self):
        """A payload containing 0xAA doesn't create a false packet start."""
        # Build a packet whose payload contains 0xAA bytes
        data = b"\xAA\xAA\xAA\xAA"
        pkt = build_packet(PacketType.COMMAND, 0x01, data)
        packets = PacketDecoder.decode_stream(pkt)
        assert len(packets) == 1
        assert packets[0].payload == data
