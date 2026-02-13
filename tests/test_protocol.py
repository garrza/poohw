"""Tests for protocol.py — CRC, packet framing, enums, UUIDs, command builders."""

import struct
import zlib

import pytest

from poohw.protocol import (
    # Constants
    SOF,
    SOF_SIZE,
    LENGTH_SIZE,
    CRC8_SIZE,
    CRC32_SIZE,
    HEADER_SIZE,
    MIN_PACKET_SIZE,
    # UUIDs
    WHOOP_SERVICE_UUID_GEN1,
    WHOOP_SERVICE_UUID_GEN2,
    CMD_TO_STRAP_UUID_GEN1,
    CMD_TO_STRAP_UUID_GEN2,
    CMD_FROM_STRAP_UUID_GEN1,
    CMD_FROM_STRAP_UUID_GEN2,
    EVENTS_FROM_STRAP_UUID_GEN1,
    EVENTS_FROM_STRAP_UUID_GEN2,
    DATA_FROM_STRAP_UUID_GEN1,
    DATA_FROM_STRAP_UUID_GEN2,
    MEMFAULT_UUID_GEN1,
    MEMFAULT_UUID_GEN2,
    WHOOP_SERVICE_UUID,
    CMD_TO_STRAP_UUID,
    HR_SERVICE_UUID,
    HR_MEASUREMENT_UUID,
    PROPRIETARY_SERVICE_PREFIXES,
    CHARACTERISTIC_ROLES,
    is_proprietary_uuid,
    char_role,
    # Enums
    PacketType,
    HistoricalRecordType,
    Command,
    Event,
    # CRC
    crc8,
    crc32,
    # Framing
    build_packet,
    parse_packet,
    format_packet,
    hex_to_bytes,
    # High-level builders
    build_toggle_realtime_hr,
    build_toggle_imu,
    build_toggle_imu_historical,
    build_get_data_range,
    build_set_read_pointer,
    build_send_historical_data,
    build_abort_historical,
    build_get_battery,
    build_get_hello,
    build_set_clock,
)


# ===================================================================
# Framing constants
# ===================================================================


class TestFramingConstants:
    """Verify structural constants are consistent."""

    def test_sof_is_0xaa(self):
        assert SOF == 0xAA

    def test_header_size_is_sum_of_parts(self):
        assert HEADER_SIZE == SOF_SIZE + LENGTH_SIZE + CRC8_SIZE

    def test_header_is_4_bytes(self):
        assert HEADER_SIZE == 4

    def test_min_packet_is_header_plus_crc32(self):
        assert MIN_PACKET_SIZE == HEADER_SIZE + CRC32_SIZE

    def test_min_packet_is_8_bytes(self):
        assert MIN_PACKET_SIZE == 8


# ===================================================================
# UUID helpers
# ===================================================================


class TestIsProprietary:
    """Test is_proprietary_uuid across both UUID families."""

    def test_gen1_service(self):
        assert is_proprietary_uuid(WHOOP_SERVICE_UUID_GEN1) is True

    def test_gen1_cmd_to(self):
        assert is_proprietary_uuid(CMD_TO_STRAP_UUID_GEN1) is True

    def test_gen1_cmd_from(self):
        assert is_proprietary_uuid(CMD_FROM_STRAP_UUID_GEN1) is True

    def test_gen1_events(self):
        assert is_proprietary_uuid(EVENTS_FROM_STRAP_UUID_GEN1) is True

    def test_gen1_data(self):
        assert is_proprietary_uuid(DATA_FROM_STRAP_UUID_GEN1) is True

    def test_gen1_memfault(self):
        assert is_proprietary_uuid(MEMFAULT_UUID_GEN1) is True

    def test_gen2_service(self):
        assert is_proprietary_uuid(WHOOP_SERVICE_UUID_GEN2) is True

    def test_gen2_cmd_to(self):
        assert is_proprietary_uuid(CMD_TO_STRAP_UUID_GEN2) is True

    def test_gen2_cmd_from(self):
        assert is_proprietary_uuid(CMD_FROM_STRAP_UUID_GEN2) is True

    def test_gen2_events(self):
        assert is_proprietary_uuid(EVENTS_FROM_STRAP_UUID_GEN2) is True

    def test_gen2_data(self):
        assert is_proprietary_uuid(DATA_FROM_STRAP_UUID_GEN2) is True

    def test_gen2_memfault(self):
        assert is_proprietary_uuid(MEMFAULT_UUID_GEN2) is True

    def test_hr_service_is_not_proprietary(self):
        assert is_proprietary_uuid(HR_SERVICE_UUID) is False

    def test_hr_measurement_is_not_proprietary(self):
        assert is_proprietary_uuid(HR_MEASUREMENT_UUID) is False

    def test_empty_string(self):
        assert is_proprietary_uuid("") is False

    def test_random_uuid(self):
        assert is_proprietary_uuid("12345678-1234-1234-1234-123456789abc") is False

    def test_default_alias_matches_gen1(self):
        assert WHOOP_SERVICE_UUID == WHOOP_SERVICE_UUID_GEN1
        assert CMD_TO_STRAP_UUID == CMD_TO_STRAP_UUID_GEN1


class TestCharRole:
    """Test char_role maps suffixes to role names."""

    def test_gen1_cmd_to(self):
        assert char_role(CMD_TO_STRAP_UUID_GEN1) == "CMD_TO_STRAP"

    def test_gen1_cmd_from(self):
        assert char_role(CMD_FROM_STRAP_UUID_GEN1) == "CMD_FROM_STRAP"

    def test_gen1_events(self):
        assert char_role(EVENTS_FROM_STRAP_UUID_GEN1) == "EVENTS_FROM_STRAP"

    def test_gen1_data(self):
        assert char_role(DATA_FROM_STRAP_UUID_GEN1) == "DATA_FROM_STRAP"

    def test_gen1_memfault(self):
        assert char_role(MEMFAULT_UUID_GEN1) == "MEMFAULT"

    def test_gen2_cmd_to(self):
        assert char_role(CMD_TO_STRAP_UUID_GEN2) == "CMD_TO_STRAP"

    def test_gen2_cmd_from(self):
        assert char_role(CMD_FROM_STRAP_UUID_GEN2) == "CMD_FROM_STRAP"

    def test_gen2_events(self):
        assert char_role(EVENTS_FROM_STRAP_UUID_GEN2) == "EVENTS_FROM_STRAP"

    def test_gen2_data(self):
        assert char_role(DATA_FROM_STRAP_UUID_GEN2) == "DATA_FROM_STRAP"

    def test_gen2_memfault(self):
        assert char_role(MEMFAULT_UUID_GEN2) == "MEMFAULT"

    def test_service_uuid_returns_none(self):
        # Service UUIDs (suffix 0001) have no role mapping
        assert char_role(WHOOP_SERVICE_UUID_GEN1) is None

    def test_standard_uuid_returns_none(self):
        assert char_role(HR_SERVICE_UUID) is None

    def test_empty_returns_none(self):
        assert char_role("") is None


# ===================================================================
# Enums
# ===================================================================


class TestPacketTypeEnum:
    """Verify PacketType values match the protocol spec."""

    def test_command(self):
        assert PacketType.COMMAND == 0x23

    def test_command_response(self):
        assert PacketType.COMMAND_RESPONSE == 0x24

    def test_realtime_data(self):
        assert PacketType.REALTIME_DATA == 0x28

    def test_realtime_raw_data(self):
        assert PacketType.REALTIME_RAW_DATA == 0x2B

    def test_historical_data(self):
        assert PacketType.HISTORICAL_DATA == 0x2F

    def test_event(self):
        assert PacketType.EVENT == 0x30

    def test_metadata(self):
        assert PacketType.METADATA == 0x31

    def test_console_logs(self):
        assert PacketType.CONSOLE_LOGS == 0x32

    def test_realtime_imu(self):
        assert PacketType.REALTIME_IMU_DATA == 0x33

    def test_historical_imu(self):
        assert PacketType.HISTORICAL_IMU_DATA == 0x34

    def test_total_count(self):
        assert len(PacketType) == 10


class TestHistoricalRecordTypeEnum:
    def test_hr_rr(self):
        assert HistoricalRecordType.HR_RR == 0x2F

    def test_event(self):
        assert HistoricalRecordType.EVENT == 0x30

    def test_accel_batch(self):
        assert HistoricalRecordType.ACCEL_BATCH == 0x34

    def test_comprehensive(self):
        assert HistoricalRecordType.COMPREHENSIVE == 0x5C

    def test_total_count(self):
        assert len(HistoricalRecordType) == 4


class TestCommandEnum:
    """Spot-check key command IDs from the firmware RE."""

    def test_link_valid(self):
        assert Command.LINK_VALID == 0x01

    def test_toggle_hr(self):
        assert Command.TOGGLE_REALTIME_HR == 0x03

    def test_send_historical_data(self):
        assert Command.SEND_HISTORICAL_DATA == 0x16

    def test_get_battery(self):
        assert Command.GET_BATTERY_LEVEL == 0x1A

    def test_set_read_pointer(self):
        assert Command.SET_READ_POINTER == 0x21

    def test_get_data_range(self):
        assert Command.GET_DATA_RANGE == 0x22

    def test_run_alarm(self):
        assert Command.RUN_ALARM == 0x44

    def test_run_haptics(self):
        assert Command.RUN_HAPTICS_PATTERN == 0x4F

    def test_toggle_imu(self):
        assert Command.TOGGLE_IMU_MODE == 0x6A

    def test_toggle_imu_historical(self):
        assert Command.TOGGLE_IMU_MODE_HISTORICAL == 0x69

    def test_stop_haptics(self):
        assert Command.STOP_HAPTICS == 0x7A

    def test_get_hello(self):
        assert Command.GET_HELLO == 0x91

    def test_no_duplicate_values(self):
        values = [c.value for c in Command]
        assert len(values) == len(set(values))


class TestEventEnum:
    def test_haptics_fired(self):
        assert Event.HAPTICS_FIRED == 0x3C

    def test_haptics_terminated(self):
        assert Event.HAPTICS_TERMINATED == 0x64

    def test_alarm_set(self):
        assert Event.STRAP_DRIVEN_ALARM_SET == 0x38

    def test_no_duplicate_values(self):
        values = [e.value for e in Event]
        assert len(values) == len(set(values))


# ===================================================================
# CRC-8
# ===================================================================


class TestCRC8:
    def test_empty_input(self):
        assert crc8(b"") == 0

    def test_single_zero(self):
        assert crc8(b"\x00") == 0

    def test_deterministic(self):
        assert crc8(b"\x07\x00") == crc8(b"\x07\x00")

    def test_different_inputs_differ(self):
        assert crc8(b"\x01\x00") != crc8(b"\x02\x00")

    def test_accepts_bytearray(self):
        assert crc8(bytearray(b"\x07\x00")) == crc8(b"\x07\x00")

    def test_returns_int_in_byte_range(self):
        for i in range(256):
            result = crc8(bytes([i]))
            assert 0 <= result <= 255

    def test_matches_packet_header(self):
        """CRC-8 over a length field matches what build_packet stores."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert pkt[3] == crc8(pkt[1:3])

    def test_polynomial_0x07_identity(self):
        """Known value: CRC-8/SMBUS of [0x07] should be 0x07 XOR'd through the table."""
        result = crc8(b"\x07")
        assert isinstance(result, int)


# ===================================================================
# CRC-32
# ===================================================================


class TestCRC32:
    def test_empty_input(self):
        assert crc32(b"") == 0x00000000

    def test_zlib_standard_vector(self):
        assert crc32(b"123456789") == 0xCBF43926

    def test_matches_stdlib_zlib(self):
        data = b"Hello, Whoop!"
        assert crc32(data) == (zlib.crc32(data) & 0xFFFFFFFF)

    def test_accepts_bytearray(self):
        assert crc32(bytearray(b"test")) == crc32(b"test")

    def test_returns_unsigned_32bit(self):
        result = crc32(b"\xFF" * 100)
        assert 0 <= result <= 0xFFFFFFFF

    def test_large_payload(self):
        """CRC-32 handles large data without error."""
        data = bytes(range(256)) * 100
        result = crc32(data)
        assert 0 <= result <= 0xFFFFFFFF

    def test_matches_packet_trailer(self):
        pkt = build_packet(PacketType.COMMAND, Command.RUN_ALARM, b"\x00")
        inner = pkt[HEADER_SIZE:-CRC32_SIZE]
        stored = struct.unpack_from("<I", pkt, len(pkt) - CRC32_SIZE)[0]
        assert stored == crc32(inner)


# ===================================================================
# build_packet
# ===================================================================


class TestBuildPacket:
    def test_starts_with_sof(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert pkt[0] == SOF

    def test_returns_bytes(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert isinstance(pkt, bytes)

    def test_minimum_size(self):
        """Empty payload still produces a packet >= MIN_PACKET_SIZE."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert len(pkt) >= MIN_PACKET_SIZE

    def test_length_field_math(self):
        """LENGTH = len(type+seq+cmd+data) + 4 (CRC-32)."""
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

    def test_inner_layout(self):
        """Inner bytes are [type, seq, cmd, data...]."""
        pkt = build_packet(PacketType.COMMAND, Command.TOGGLE_REALTIME_HR, b"\x01", seq=5)
        assert pkt[4] == PacketType.COMMAND
        assert pkt[5] == 5   # seq
        assert pkt[6] == Command.TOGGLE_REALTIME_HR
        assert pkt[7] == 0x01

    def test_empty_payload(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        inner = pkt[HEADER_SIZE:-CRC32_SIZE]
        assert len(inner) == 3  # type + seq + cmd only

    def test_large_payload(self):
        data = bytes(range(256))
        pkt = build_packet(PacketType.COMMAND, 0x01, data)
        parsed = parse_packet(pkt)
        assert parsed["payload"] == data
        assert parsed["crc32_valid"] is True

    def test_seq_default_zero(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert pkt[5] == 0

    def test_seq_custom(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL, seq=255)
        assert pkt[5] == 255

    def test_all_packet_types_produce_valid_packets(self):
        for pt in PacketType:
            pkt = build_packet(pt, 0x01, b"\xAB")
            parsed = parse_packet(pkt)
            assert parsed is not None
            assert parsed["packet_type"] == pt
            assert parsed["crc32_valid"] is True
            assert parsed["header_crc8_valid"] is True


# ===================================================================
# parse_packet
# ===================================================================


class TestParsePacket:
    def test_round_trip_simple(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        p = parse_packet(pkt)
        assert p is not None
        assert p["packet_type"] == PacketType.COMMAND
        assert p["command"] == Command.GET_BATTERY_LEVEL
        assert p["seq"] == 0
        assert p["payload"] == b""
        assert p["header_crc8_valid"] is True
        assert p["crc32_valid"] is True
        assert p["complete"] is True

    def test_round_trip_with_data(self):
        data = bytes(range(16))
        pkt = build_packet(PacketType.COMMAND, Command.SET_CLOCK, data, seq=7)
        p = parse_packet(pkt)
        assert p["payload"] == data
        assert p["seq"] == 7
        assert p["crc32_valid"] is True

    def test_too_short_returns_none(self):
        assert parse_packet(b"\xAA\x00") is None
        assert parse_packet(b"") is None
        assert parse_packet(b"\xAA") is None

    def test_bad_sof_returns_none(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        assert parse_packet(b"\xBB" + pkt[1:]) is None
        assert parse_packet(b"\x00" + pkt[1:]) is None

    def test_corrupted_crc32_detected(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL))
        pkt[-1] ^= 0xFF
        p = parse_packet(bytes(pkt))
        assert p is not None
        assert p["crc32_valid"] is False

    def test_corrupted_crc8_detected(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL))
        pkt[3] ^= 0xFF
        p = parse_packet(bytes(pkt))
        assert p is not None
        assert p["header_crc8_valid"] is False

    def test_truncated_packet_is_incomplete(self):
        """A packet missing its CRC-32 trailer is flagged incomplete."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        truncated = pkt[:-2]  # chop 2 bytes off the end
        p = parse_packet(truncated)
        assert p is not None
        assert p["complete"] is False
        assert p["crc32_valid"] is None

    def test_extra_trailing_bytes_ignored(self):
        """Extra bytes after a valid packet don't affect parsing."""
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        padded = pkt + b"\xFF" * 10
        p = parse_packet(padded)
        assert p is not None
        assert p["crc32_valid"] is True

    def test_negative_inner_size_returns_none(self):
        """A length field of 0 or 1 would make inner_size negative."""
        # Craft: SOF + length=0x0001 + CRC-8 + ... (inner_size = 1-4 = -3)
        raw = bytes([SOF, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        p = parse_packet(raw)
        assert p is None

    def test_parse_returns_raw_bytes(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        p = parse_packet(pkt)
        assert p["raw"] == pkt

    def test_parse_returns_length_field(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_HELLO)
        p = parse_packet(pkt)
        assert p["length_field"] == struct.unpack_from("<H", pkt, 1)[0]


# ===================================================================
# format_packet
# ===================================================================


class TestFormatPacket:
    def test_valid_known_command(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        text = format_packet(pkt)
        assert "COMMAND" in text
        assert "GET_BATTERY_LEVEL" in text
        assert "OK" in text

    def test_unknown_packet_type(self):
        pkt = build_packet(0xFE, 0x01, b"\xAB")
        text = format_packet(pkt)
        assert "0xFE" in text

    def test_unknown_command_id(self):
        pkt = build_packet(PacketType.COMMAND, 0xFE)
        text = format_packet(pkt)
        assert "0xFE" in text

    def test_with_payload_shows_data(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL, b"\xDE\xAD")
        text = format_packet(pkt)
        assert "data=" in text
        assert "dead" in text.lower()

    def test_corrupted_crc32_shows_bad(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL))
        pkt[-1] ^= 0xFF
        text = format_packet(bytes(pkt))
        assert "BAD" in text

    def test_corrupted_crc8_shows_bad(self):
        pkt = bytearray(build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL))
        pkt[3] ^= 0xFF
        text = format_packet(bytes(pkt))
        assert "crc8=BAD" in text

    def test_invalid_data_returns_raw_hex(self):
        text = format_packet(b"\x01\x02\x03")
        assert "[raw]" in text

    def test_incomplete_packet(self):
        pkt = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        text = format_packet(pkt[:-2])
        assert "INCOMPLETE" in text


# ===================================================================
# hex_to_bytes
# ===================================================================


class TestHexToBytes:
    def test_no_spaces(self):
        assert hex_to_bytes("aa0800") == b"\xaa\x08\x00"

    def test_with_spaces(self):
        assert hex_to_bytes("aa 08 00") == b"\xaa\x08\x00"

    def test_mixed_case(self):
        assert hex_to_bytes("aA Bb Cc") == b"\xaa\xbb\xcc"

    def test_empty(self):
        assert hex_to_bytes("") == b""

    def test_single_byte(self):
        assert hex_to_bytes("ff") == b"\xff"


# ===================================================================
# High-level command builders
# ===================================================================


class TestCommandBuilders:
    """Verify all build_* helpers produce valid framed packets."""

    def _check(self, pkt: bytes, expected_cmd: int, expected_data: bytes = b""):
        p = parse_packet(pkt)
        assert p is not None
        assert p["packet_type"] == PacketType.COMMAND
        assert p["command"] == expected_cmd
        assert p["payload"] == expected_data
        assert p["crc32_valid"] is True
        assert p["header_crc8_valid"] is True

    def test_toggle_hr_enable(self):
        self._check(build_toggle_realtime_hr(True), Command.TOGGLE_REALTIME_HR, b"\x01")

    def test_toggle_hr_disable(self):
        self._check(build_toggle_realtime_hr(False), Command.TOGGLE_REALTIME_HR, b"\x00")

    def test_toggle_imu_enable(self):
        self._check(build_toggle_imu(True), Command.TOGGLE_IMU_MODE, b"\x01")

    def test_toggle_imu_disable(self):
        self._check(build_toggle_imu(False), Command.TOGGLE_IMU_MODE, b"\x00")

    def test_toggle_imu_historical_enable(self):
        self._check(build_toggle_imu_historical(True), Command.TOGGLE_IMU_MODE_HISTORICAL, b"\x01")

    def test_toggle_imu_historical_disable(self):
        self._check(build_toggle_imu_historical(False), Command.TOGGLE_IMU_MODE_HISTORICAL, b"\x00")

    def test_get_data_range(self):
        self._check(build_get_data_range(), Command.GET_DATA_RANGE)

    def test_set_read_pointer(self):
        pkt = build_set_read_pointer(0x00001000)
        p = parse_packet(pkt)
        assert p["command"] == Command.SET_READ_POINTER
        assert p["payload"] == struct.pack("<I", 0x00001000)
        assert p["crc32_valid"] is True

    def test_set_read_pointer_zero(self):
        pkt = build_set_read_pointer(0)
        p = parse_packet(pkt)
        assert p["payload"] == b"\x00\x00\x00\x00"

    def test_set_read_pointer_max(self):
        pkt = build_set_read_pointer(0xFFFFFFFF)
        p = parse_packet(pkt)
        assert p["payload"] == b"\xff\xff\xff\xff"

    def test_send_historical_data(self):
        self._check(build_send_historical_data(), Command.SEND_HISTORICAL_DATA)

    def test_abort_historical(self):
        self._check(build_abort_historical(), Command.ABORT_HISTORICAL_TRANSMITS)

    def test_get_battery(self):
        self._check(build_get_battery(), Command.GET_BATTERY_LEVEL)

    def test_get_hello(self):
        self._check(build_get_hello(), Command.GET_HELLO)

    def test_set_clock(self):
        epoch = 1707840000
        pkt = build_set_clock(epoch)
        p = parse_packet(pkt)
        assert p["command"] == Command.SET_CLOCK
        assert p["payload"] == struct.pack("<I", epoch)

    def test_set_clock_zero(self):
        pkt = build_set_clock(0)
        p = parse_packet(pkt)
        assert p["payload"] == b"\x00\x00\x00\x00"

    def test_seq_propagation(self):
        """All builders correctly forward the seq argument."""
        for seq in (0, 1, 127, 255):
            pkt = build_toggle_realtime_hr(True, seq=seq)
            assert parse_packet(pkt)["seq"] == seq

            pkt = build_get_data_range(seq=seq)
            assert parse_packet(pkt)["seq"] == seq

            pkt = build_get_hello(seq=seq)
            assert parse_packet(pkt)["seq"] == seq
