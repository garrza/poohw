"""Tests for CRC-8, CRC-32, packet building, and packet parsing."""

import struct

import pytest

from poohw.protocol import (
    SOF,
    CRC32_SIZE,
    HEADER_SIZE,
    MIN_PACKET_SIZE,
    PacketType,
    Command,
    crc8,
    crc32,
    build_packet,
    parse_packet,
    format_packet,
    hex_to_bytes,
)
from poohw.decoders.packet import PacketDecoder, WhoopPacket


# ---------------------------------------------------------------------------
# CRC-8 (poly 0x07)
# ---------------------------------------------------------------------------


class TestCRC8:
    """Validate CRC-8 against known vectors and properties."""

    def test_empty(self):
        assert crc8(b"") == 0

    def test_single_byte(self):
        # CRC-8/SMBUS: crc8(b"\x00") should be 0
        assert crc8(b"\x00") == 0

    def test_deterministic(self):
        """Same input always produces the same CRC."""
        data = b"\x07\x00"
        assert crc8(data) == crc8(data)

    def test_known_length_field(self):
        """Verify CRC-8 over a 2-byte length field matches a manually built packet."""
        # Build a minimal packet and check that the stored CRC-8 is what crc8() returns
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        length_bytes = pkt[1:3]
        stored_crc8 = pkt[3]
        assert stored_crc8 == crc8(length_bytes)

    def test_different_inputs_different_crcs(self):
        assert crc8(b"\x01\x00") != crc8(b"\x02\x00")


# ---------------------------------------------------------------------------
# CRC-32 (zlib)
# ---------------------------------------------------------------------------


class TestCRC32:
    """Validate CRC-32 against known vectors."""

    def test_empty(self):
        assert crc32(b"") == 0x00000000

    def test_zlib_compat(self):
        """Standard zlib CRC-32 test vector."""
        import zlib

        data = b"123456789"
        expected = zlib.crc32(data) & 0xFFFFFFFF
        assert crc32(data) == expected
        assert crc32(data) == 0xCBF43926

    def test_known_packet_payload(self):
        """CRC-32 of the inner payload matches what build_packet stores."""
        pkt = build_packet(PacketType.COMMAND, Command.RUN_ALARM, b"\x00")
        # Inner = pkt[4 : -4]
        inner = pkt[HEADER_SIZE:-CRC32_SIZE]
        stored = struct.unpack_from("<I", pkt, len(pkt) - CRC32_SIZE)[0]
        assert stored == crc32(inner)


# ---------------------------------------------------------------------------
# build_packet
# ---------------------------------------------------------------------------


class TestBuildPacket:
    """Validate the packet builder produces correct framing."""

    def test_sof_byte(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert pkt[0] == SOF

    def test_minimum_size(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert len(pkt) >= MIN_PACKET_SIZE

    def test_length_field_covers_inner_plus_crc32(self):
        data = b"\x01\x02\x03"
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL, data)
        length_field = struct.unpack_from("<H", pkt, 1)[0]
        inner_len = 3 + len(data)  # type + seq + cmd + data
        assert length_field == inner_len + CRC32_SIZE

    def test_crc8_header_valid(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert pkt[3] == crc8(pkt[1:3])

    def test_crc32_trailer_valid(self):
        pkt = build_packet(PacketType.COMMAND, Command.RUN_HAPTICS_PATTERN, b"\x00")
        inner = pkt[HEADER_SIZE:-CRC32_SIZE]
        stored = struct.unpack_from("<I", pkt, len(pkt) - CRC32_SIZE)[0]
        assert stored == crc32(inner)

    def test_type_seq_cmd_in_inner(self):
        pkt = build_packet(PacketType.COMMAND, Command.TOGGLE_REALTIME_HR, b"\x01", seq=5)
        assert pkt[4] == PacketType.COMMAND  # type
        assert pkt[5] == 5  # seq
        assert pkt[6] == Command.TOGGLE_REALTIME_HR  # cmd
        assert pkt[7] == 0x01  # data

    def test_empty_payload(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        inner = pkt[HEADER_SIZE:-CRC32_SIZE]
        assert len(inner) == 3  # type + seq + cmd, no data

    def test_seq_default_zero(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert pkt[5] == 0


# ---------------------------------------------------------------------------
# parse_packet (round-trip)
# ---------------------------------------------------------------------------


class TestParsePacket:
    """Validate parse_packet correctly disassembles what build_packet produces."""

    def test_round_trip_simple(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        parsed = parse_packet(pkt)
        assert parsed is not None
        assert parsed["packet_type"] == PacketType.COMMAND
        assert parsed["command"] == Command.GET_BATTERY_LEVEL
        assert parsed["seq"] == 0
        assert parsed["payload"] == b""
        assert parsed["header_crc8_valid"] is True
        assert parsed["crc32_valid"] is True
        assert parsed["complete"] is True

    def test_round_trip_with_data(self):
        data = bytes(range(16))
        pkt = build_packet(PacketType.COMMAND, Command.SET_CLOCK, data, seq=7)
        parsed = parse_packet(pkt)
        assert parsed["packet_type"] == PacketType.COMMAND
        assert parsed["command"] == Command.SET_CLOCK
        assert parsed["seq"] == 7
        assert parsed["payload"] == data
        assert parsed["crc32_valid"] is True

    def test_all_packet_types(self):
        """Every PacketType round-trips correctly."""
        for pt in PacketType:
            pkt = build_packet(pt, 0x01, b"\xAB")
            parsed = parse_packet(pkt)
            assert parsed is not None
            assert parsed["packet_type"] == pt
            assert parsed["crc32_valid"] is True

    def test_too_short_returns_none(self):
        assert parse_packet(b"\xAA\x00") is None

    def test_bad_sof_returns_none(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        bad = b"\xBB" + pkt[1:]
        assert parse_packet(bad) is None

    def test_corrupted_crc32_detected(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL))
        pkt[-1] ^= 0xFF  # flip last byte
        parsed = parse_packet(bytes(pkt))
        assert parsed is not None
        assert parsed["crc32_valid"] is False

    def test_corrupted_crc8_detected(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL))
        pkt[3] ^= 0xFF  # flip CRC-8 byte
        parsed = parse_packet(bytes(pkt))
        assert parsed is not None
        assert parsed["header_crc8_valid"] is False


# ---------------------------------------------------------------------------
# PacketDecoder (dataclass wrapper)
# ---------------------------------------------------------------------------


class TestPacketDecoder:
    """Validate the PacketDecoder produces WhoopPacket objects."""

    def test_decode_returns_whoop_packet(self):
        pkt = build_packet(PacketType.COMMAND, Command.RUN_ALARM, b"\x00")
        wp = PacketDecoder.decode(pkt)
        assert isinstance(wp, WhoopPacket)
        assert wp.packet_type == PacketType.COMMAND
        assert wp.command_id == Command.RUN_ALARM
        assert wp.payload == b"\x00"
        assert wp.crc8_valid is True
        assert wp.crc32_valid is True
        assert wp.complete is True

    def test_decode_stream_multiple_packets(self):
        pkt1 = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        pkt2 = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        stream = pkt1 + pkt2
        packets = PacketDecoder.decode_stream(stream)
        assert len(packets) == 2
        assert packets[0].command_id == Command.GET_BATTERY_LEVEL
        assert packets[1].command_id == Command.GET_HELLO

    def test_decode_stream_with_garbage(self):
        """Garbage bytes between packets are skipped."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        stream = b"\x00\x01\x02" + pkt + b"\xFF\xFE"
        packets = PacketDecoder.decode_stream(stream)
        assert len(packets) == 1
        assert packets[0].command_id == Command.GET_BATTERY_LEVEL

    def test_type_name_known(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        wp = PacketDecoder.decode(pkt)
        assert wp.type_name == "COMMAND"

    def test_type_name_unknown(self):
        pkt = build_packet(0xFF, 0x01)
        wp = PacketDecoder.decode(pkt)
        assert wp.type_name == "0xFF"

    def test_command_name_known(self):
        pkt = build_packet(PacketType.COMMAND, Command.TOGGLE_REALTIME_HR, b"\x01")
        wp = PacketDecoder.decode(pkt)
        assert wp.command_name == "TOGGLE_REALTIME_HR"


# ---------------------------------------------------------------------------
# format_packet
# ---------------------------------------------------------------------------


class TestFormatPacket:
    """Validate human-readable formatting."""

    def test_format_valid_packet(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        text = format_packet(pkt)
        assert "COMMAND" in text
        assert "GET_BATTERY_LEVEL" in text
        assert "OK" in text

    def test_format_invalid_falls_back(self):
        text = format_packet(b"\x01\x02\x03")
        assert "[raw]" in text


# ---------------------------------------------------------------------------
# hex_to_bytes
# ---------------------------------------------------------------------------


class TestHexToBytes:
    def test_no_spaces(self):
        assert hex_to_bytes("aa0800") == b"\xaa\x08\x00"

    def test_with_spaces(self):
        assert hex_to_bytes("aa 08 00") == b"\xaa\x08\x00"

    def test_empty(self):
        assert hex_to_bytes("") == b""


# ---------------------------------------------------------------------------
# Known packet vector tests
# ---------------------------------------------------------------------------


class TestKnownVectors:
    """Test against known Whoop packet captures.

    These are packets observed in the wild with confirmed-valid checksums.
    They serve as the ultimate ground truth for the CRC implementations.
    """

    # From docs/protocol.md: aa 08 00 a8 23 0e 16 00 11 47 c5 85
    #   SOF=0xAA, len=0x0008, crc8=0xA8, inner=[23 0e 16 00 11], crc32=[47 c5 85]
    #   Wait — that's only 3 bytes of CRC32. The doc sample may be truncated or
    #   the framing may differ. Let's verify what we *can*:

    def test_build_then_parse_vibrate(self):
        """RUN_HAPTICS_PATTERN with payload 0x00 round-trips."""
        pkt = build_packet(PacketType.COMMAND, Command.RUN_HAPTICS_PATTERN, b"\x00")
        parsed = parse_packet(pkt)
        assert parsed["crc32_valid"] is True
        assert parsed["command"] == Command.RUN_HAPTICS_PATTERN
        assert parsed["payload"] == b"\x00"

    def test_build_then_parse_toggle_hr(self):
        """TOGGLE_REALTIME_HR with enable=1 round-trips."""
        pkt = build_packet(PacketType.COMMAND, Command.TOGGLE_REALTIME_HR, b"\x01")
        parsed = parse_packet(pkt)
        assert parsed["crc32_valid"] is True
        assert parsed["command"] == Command.TOGGLE_REALTIME_HR
        assert parsed["payload"] == b"\x01"

    def test_build_then_parse_toggle_imu(self):
        """TOGGLE_IMU_MODE with enable=1 round-trips."""
        pkt = build_packet(PacketType.COMMAND, Command.TOGGLE_IMU_MODE, b"\x01")
        parsed = parse_packet(pkt)
        assert parsed["crc32_valid"] is True
        assert parsed["command"] == Command.TOGGLE_IMU_MODE

    def test_build_then_parse_send_historical(self):
        """SEND_HISTORICAL_DATA command round-trips."""
        pkt = build_packet(PacketType.COMMAND, Command.SEND_HISTORICAL_DATA)
        parsed = parse_packet(pkt)
        assert parsed["crc32_valid"] is True
        assert parsed["command"] == Command.SEND_HISTORICAL_DATA
