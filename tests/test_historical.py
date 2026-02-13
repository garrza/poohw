"""Tests for historical data decoder and command builders."""

import struct
import math

import pytest

from poohw.protocol import (
    PacketType,
    Command,
    HistoricalRecordType,
    build_packet,
    parse_packet,
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
from poohw.decoders.packet import PacketDecoder
from poohw.decoders.historical import (
    HistoricalDecoder,
    ComprehensiveRecord,
    HistoricalHRRecord,
    HistoricalAccelBatch,
    HistoricalEventRecord,
    HistoricalSpO2RawRecord,
    HistoricalTempRecord,
    compute_rmssd,
    lnrmssd_score,
    estimate_spo2_from_ratio,
)


# ---------------------------------------------------------------------------
# HRV helper tests
# ---------------------------------------------------------------------------


class TestHRVHelpers:
    def test_rmssd_two_intervals(self):
        # RR = [800, 810] → diff = [10] → RMSSD = 10.0
        assert compute_rmssd([800.0, 810.0]) == 10.0

    def test_rmssd_three_intervals(self):
        # diffs = [10, -10] → sq = [100, 100] → mean = 100 → sqrt = 10.0
        assert compute_rmssd([800.0, 810.0, 800.0]) == 10.0

    def test_rmssd_single_returns_none(self):
        assert compute_rmssd([800.0]) is None

    def test_rmssd_empty_returns_none(self):
        assert compute_rmssd([]) is None

    def test_lnrmssd_score_typical(self):
        # ln(50) ≈ 3.912 → 3.912 / 6.5 * 100 ≈ 60.2
        score = lnrmssd_score(50.0)
        assert 59.0 <= score <= 61.0

    def test_lnrmssd_score_zero(self):
        assert lnrmssd_score(0.0) == 0.0

    def test_lnrmssd_score_negative(self):
        assert lnrmssd_score(-5.0) == 0.0


class TestSpO2Estimation:
    def test_ratio_0_4(self):
        # SpO2 = 110 - 25 * 0.4 = 100.0
        assert estimate_spo2_from_ratio(0.4) == 100.0

    def test_ratio_0_8(self):
        # SpO2 = 110 - 25 * 0.8 = 90.0
        assert estimate_spo2_from_ratio(0.8) == 90.0

    def test_ratio_1_0(self):
        # SpO2 = 110 - 25 * 1.0 = 85.0
        assert estimate_spo2_from_ratio(1.0) == 85.0

    def test_clamped_high(self):
        # Very low R → high SpO2, clamped to 100
        assert estimate_spo2_from_ratio(0.0) == 100.0

    def test_clamped_low(self):
        # Very high R → SpO2 below 0, clamped
        assert estimate_spo2_from_ratio(5.0) == 0.0


# ---------------------------------------------------------------------------
# Command builder tests
# ---------------------------------------------------------------------------


class TestCommandBuilders:
    """Verify high-level command builders produce valid packets."""

    def _verify_packet(self, pkt: bytes, expected_cmd: int, expected_data: bytes = b""):
        parsed = parse_packet(pkt)
        assert parsed is not None
        assert parsed["packet_type"] == PacketType.COMMAND
        assert parsed["command"] == expected_cmd
        assert parsed["payload"] == expected_data
        assert parsed["crc32_valid"] is True
        assert parsed["header_crc8_valid"] is True

    def test_toggle_hr_enable(self):
        self._verify_packet(
            build_toggle_realtime_hr(True),
            Command.TOGGLE_REALTIME_HR,
            b"\x01",
        )

    def test_toggle_hr_disable(self):
        self._verify_packet(
            build_toggle_realtime_hr(False),
            Command.TOGGLE_REALTIME_HR,
            b"\x00",
        )

    def test_toggle_imu_enable(self):
        self._verify_packet(
            build_toggle_imu(True),
            Command.TOGGLE_IMU_MODE,
            b"\x01",
        )

    def test_toggle_imu_disable(self):
        self._verify_packet(
            build_toggle_imu(False),
            Command.TOGGLE_IMU_MODE,
            b"\x00",
        )

    def test_toggle_imu_historical(self):
        self._verify_packet(
            build_toggle_imu_historical(True),
            Command.TOGGLE_IMU_MODE_HISTORICAL,
            b"\x01",
        )

    def test_get_data_range(self):
        self._verify_packet(
            build_get_data_range(),
            Command.GET_DATA_RANGE,
        )

    def test_set_read_pointer(self):
        pkt = build_set_read_pointer(0x00001000)
        parsed = parse_packet(pkt)
        assert parsed["command"] == Command.SET_READ_POINTER
        assert parsed["payload"] == struct.pack("<I", 0x00001000)
        assert parsed["crc32_valid"] is True

    def test_send_historical_data(self):
        self._verify_packet(
            build_send_historical_data(),
            Command.SEND_HISTORICAL_DATA,
        )

    def test_abort_historical(self):
        self._verify_packet(
            build_abort_historical(),
            Command.ABORT_HISTORICAL_TRANSMITS,
        )

    def test_get_battery(self):
        self._verify_packet(
            build_get_battery(),
            Command.GET_BATTERY_LEVEL,
        )

    def test_get_hello(self):
        self._verify_packet(
            build_get_hello(),
            Command.GET_HELLO,
        )

    def test_set_clock(self):
        epoch = 1707840000  # 2024-02-13 12:00:00 UTC
        pkt = build_set_clock(epoch)
        parsed = parse_packet(pkt)
        assert parsed["command"] == Command.SET_CLOCK
        assert parsed["payload"] == struct.pack("<I", epoch)
        assert parsed["crc32_valid"] is True

    def test_seq_numbers(self):
        """Sequence numbers propagate correctly."""
        pkt = build_toggle_realtime_hr(True, seq=42)
        parsed = parse_packet(pkt)
        assert parsed["seq"] == 42


# ---------------------------------------------------------------------------
# Historical decoder tests
# ---------------------------------------------------------------------------


def _build_historical_packet(record_subtype: int, payload: bytes) -> bytes:
    """Helper: build a HISTORICAL_DATA packet with the given subtype and payload."""
    return build_packet(PacketType.HISTORICAL_DATA, record_subtype, payload)


def _make_comprehensive_payload(
    timestamp: int = 1707840000,
    hr_bpm: int = 72,
    rr_intervals: list[int] | None = None,
    pad_to: int = 92,
) -> bytes:
    """Build a synthetic 0x5C comprehensive record payload."""
    if rr_intervals is None:
        rr_intervals = [830, 820, 840, 825]
    rr_count = len(rr_intervals)

    buf = bytearray()
    buf += struct.pack("<I", timestamp)  # [0:4]
    buf.append(hr_bpm)  # [4]
    buf.append(rr_count)  # [5]
    for rr in rr_intervals:
        buf += struct.pack("<H", rr)  # [6:6+2N]

    # Pad to offset 22 for temperature field
    while len(buf) < 22:
        buf.append(0x00)

    # Temperature: encode 36.50°C → 36.5 * 100_000 = 3_650_000
    # As a 4-byte LE integer (fits in uint32), padded to 12 bytes
    temp_raw = int(36.50 * 100_000)
    temp_bytes = struct.pack("<I", temp_raw) + b"\x00" * 8
    buf += temp_bytes  # [22:34]

    # SpO2 raw section: 4 uint32 values simulating AC/DC readings
    # R = (ac_red/dc_red) / (ac_ir/dc_ir) ≈ 0.5 → SpO2 ≈ 97.5%
    ac_red, dc_red = 500, 10000
    ac_ir, dc_ir = 1000, 10000
    buf += struct.pack("<IIII", ac_red, dc_red, ac_ir, dc_ir)  # [34:50]

    # Pad to desired size
    while len(buf) < pad_to:
        buf.append(0x00)

    return bytes(buf)


class TestHistoricalDecoder:
    """Test the HistoricalDecoder on synthetic packets."""

    def test_can_decode_historical(self):
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, b"\x00" * 20)
        wp = PacketDecoder.decode(pkt_bytes)
        assert HistoricalDecoder.can_decode(wp)

    def test_cannot_decode_command(self):
        pkt_bytes = build_packet(PacketType.COMMAND, Command.GET_BATTERY_LEVEL)
        wp = PacketDecoder.decode(pkt_bytes)
        assert not HistoricalDecoder.can_decode(wp)

    def test_comprehensive_hr(self):
        payload = _make_comprehensive_payload(hr_bpm=72, rr_intervals=[830, 820, 840])
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, ComprehensiveRecord)
        assert result.hr is not None
        assert result.hr.hr_bpm == 72
        assert result.hr.rr_intervals_ms == [830.0, 820.0, 840.0]
        assert result.hr.hrv_rmssd_ms is not None
        assert result.hr.hrv_lnrmssd_score is not None

    def test_comprehensive_temperature(self):
        payload = _make_comprehensive_payload()
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, ComprehensiveRecord)
        assert result.temperature is not None
        assert 36.0 <= result.temperature.skin_temp_c <= 37.0

    def test_comprehensive_spo2_raw(self):
        payload = _make_comprehensive_payload()
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, ComprehensiveRecord)
        assert result.spo2_raw is not None
        # R = (500/10000) / (1000/10000) = 0.05 / 0.1 = 0.5
        # SpO2 = 110 - 25*0.5 = 97.5
        assert result.spo2_raw.estimated_spo2 == 97.5
        assert result.spo2_raw.red_ir_ratio == 0.5

    def test_comprehensive_timestamp(self):
        ts = 1707840000
        payload = _make_comprehensive_payload(timestamp=ts)
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert result.timestamp == ts

    def test_comprehensive_repr(self):
        payload = _make_comprehensive_payload()
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)
        text = repr(result)
        assert "hr=72bpm" in text
        assert "temp=" in text

    def test_hr_rr_record(self):
        payload = bytearray()
        payload += struct.pack("<I", 1707840000)  # timestamp
        payload.append(65)  # HR
        payload.append(2)  # rr count
        payload += struct.pack("<HH", 920, 930)  # RR intervals

        pkt_bytes = _build_historical_packet(HistoricalRecordType.HR_RR, bytes(payload))
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, HistoricalHRRecord)
        assert result.hr_bpm == 65
        assert result.rr_intervals_ms == [920.0, 930.0]

    def test_event_record(self):
        payload = bytearray()
        payload += struct.pack("<I", 1707840000)
        payload.append(0x3C)  # HAPTICS_FIRED
        payload += b"\x01\x02"  # event data

        pkt_bytes = _build_historical_packet(HistoricalRecordType.EVENT, bytes(payload))
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, HistoricalEventRecord)
        assert result.event_id == 0x3C
        assert result.event_data == b"\x01\x02"

    def test_accel_batch(self):
        payload = bytearray()
        payload += struct.pack("<I", 1707840000)  # timestamp
        # 2 samples of 3 axes (int16 each)
        payload += struct.pack("<hhh", 2048, -2048, 0)  # 1g, -1g, 0g
        payload += struct.pack("<hhh", 0, 0, 2048)  # 0, 0, 1g

        pkt_bytes = _build_historical_packet(HistoricalRecordType.ACCEL_BATCH, bytes(payload))
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, HistoricalAccelBatch)
        assert len(result.samples) == 2
        assert abs(result.samples[0][0] - 1.0) < 0.01  # x ≈ 1g
        assert abs(result.samples[0][1] - (-1.0)) < 0.01  # y ≈ -1g

    def test_imu_packet_type(self):
        """HISTORICAL_IMU_DATA packets are also decoded."""
        payload = bytearray()
        payload += struct.pack("<I", 1707840000)
        payload += struct.pack("<hhh", 1024, 512, 256)

        pkt_bytes = build_packet(PacketType.HISTORICAL_IMU_DATA, 0x00, bytes(payload))
        wp = PacketDecoder.decode(pkt_bytes)
        assert HistoricalDecoder.can_decode(wp)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalAccelBatch)

    def test_unknown_subtype(self):
        payload = b"\x00" * 20
        pkt_bytes = _build_historical_packet(0xFF, payload)
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)

        assert isinstance(result, dict)
        assert result["type"] == "unknown_historical"
        assert result["subtype"] == 0xFF

    def test_short_payload_returns_none(self):
        pkt_bytes = _build_historical_packet(HistoricalRecordType.COMPREHENSIVE, b"\x00\x01")
        wp = PacketDecoder.decode(pkt_bytes)
        result = HistoricalDecoder.decode(wp)
        # 2-byte payload is too short for comprehensive but >= 6 check may fail
        # Either None or a record with partial data is acceptable
        # The decoder requires >= 6 bytes, so this should be None
        assert result is None


class TestHistoricalRecordType:
    """Ensure HistoricalRecordType enum values are correct."""

    def test_comprehensive_is_0x5c(self):
        assert HistoricalRecordType.COMPREHENSIVE == 0x5C

    def test_hr_rr_is_0x2f(self):
        assert HistoricalRecordType.HR_RR == 0x2F

    def test_event_is_0x30(self):
        assert HistoricalRecordType.EVENT == 0x30

    def test_accel_batch_is_0x34(self):
        assert HistoricalRecordType.ACCEL_BATCH == 0x34
