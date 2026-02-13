"""Tests for decoders/historical.py — HRV math, SpO2 estimation, historical record decoder."""

import struct
import math

import pytest

from poohw.protocol import PacketType, Command, HistoricalRecordType, build_packet
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
    HISTORICAL_PACKET_TYPES,
)

from tests.conftest import (
    make_packet,
    make_command_packet,
    make_historical_packet,
    make_historical_imu_packet,
    make_comprehensive_payload,
)


# ===================================================================
# HRV helpers
# ===================================================================


class TestComputeRMSSD:
    def test_two_intervals(self):
        assert compute_rmssd([800.0, 810.0]) == 10.0

    def test_three_intervals_symmetric(self):
        # diffs = [10, -10] → sq = [100, 100] → mean = 100 → sqrt = 10
        assert compute_rmssd([800.0, 810.0, 800.0]) == 10.0

    def test_identical_intervals(self):
        assert compute_rmssd([800.0, 800.0, 800.0]) == 0.0

    def test_large_difference(self):
        result = compute_rmssd([500.0, 1000.0])
        assert result == 500.0

    def test_many_intervals(self):
        rr = [800.0 + i for i in range(10)]
        result = compute_rmssd(rr)
        assert result is not None
        # All diffs = 1.0 → RMSSD = 1.0
        assert abs(result - 1.0) < 0.01

    def test_single_returns_none(self):
        assert compute_rmssd([800.0]) is None

    def test_empty_returns_none(self):
        assert compute_rmssd([]) is None

    def test_returns_rounded_float(self):
        result = compute_rmssd([800.0, 813.0, 800.0])
        assert isinstance(result, float)


class TestLnRMSSDScore:
    def test_typical_value(self):
        # ln(50) ≈ 3.912 → 3.912 / 6.5 * 100 ≈ 60.2
        score = lnrmssd_score(50.0)
        assert 59.0 <= score <= 61.0

    def test_high_hrv(self):
        # ln(100) ≈ 4.605 → 4.605 / 6.5 * 100 ≈ 70.8
        score = lnrmssd_score(100.0)
        assert 70.0 <= score <= 72.0

    def test_low_hrv(self):
        # ln(10) ≈ 2.303 → 2.303 / 6.5 * 100 ≈ 35.4
        score = lnrmssd_score(10.0)
        assert 34.0 <= score <= 37.0

    def test_zero_returns_zero(self):
        assert lnrmssd_score(0.0) == 0.0

    def test_negative_returns_zero(self):
        assert lnrmssd_score(-5.0) == 0.0

    def test_one_ms(self):
        # ln(1) = 0 → score = 0
        assert lnrmssd_score(1.0) == 0.0


class TestEstimateSpO2FromRatio:
    def test_ratio_0_4_gives_100(self):
        assert estimate_spo2_from_ratio(0.4) == 100.0

    def test_ratio_0_6_gives_95(self):
        assert estimate_spo2_from_ratio(0.6) == 95.0

    def test_ratio_0_8_gives_90(self):
        assert estimate_spo2_from_ratio(0.8) == 90.0

    def test_ratio_1_0_gives_85(self):
        assert estimate_spo2_from_ratio(1.0) == 85.0

    def test_clamped_above_100(self):
        assert estimate_spo2_from_ratio(0.0) == 100.0
        assert estimate_spo2_from_ratio(-1.0) == 100.0

    def test_clamped_below_0(self):
        assert estimate_spo2_from_ratio(5.0) == 0.0
        assert estimate_spo2_from_ratio(10.0) == 0.0

    def test_typical_healthy(self):
        """R = 0.5 → SpO2 = 97.5%."""
        assert estimate_spo2_from_ratio(0.5) == 97.5


# ===================================================================
# HistoricalDecoder.can_decode
# ===================================================================


class TestHistoricalDecoderCanDecode:
    def test_historical_data_yes(self):
        wp = make_historical_packet(data=b"\x00" * 20)
        assert HistoricalDecoder.can_decode(wp) is True

    def test_historical_imu_yes(self):
        wp = make_historical_imu_packet(data=b"\x00" * 20)
        assert HistoricalDecoder.can_decode(wp) is True

    def test_command_no(self):
        wp = make_command_packet()
        assert HistoricalDecoder.can_decode(wp) is False

    def test_realtime_no(self):
        wp = make_packet(PacketType.REALTIME_DATA, 0x00, b"\x00" * 10)
        assert HistoricalDecoder.can_decode(wp) is False

    def test_packet_types_set(self):
        assert PacketType.HISTORICAL_DATA in HISTORICAL_PACKET_TYPES
        assert PacketType.HISTORICAL_IMU_DATA in HISTORICAL_PACKET_TYPES


# ===================================================================
# Comprehensive record (0x5C)
# ===================================================================


class TestComprehensiveRecord:
    def test_hr_extraction(self):
        payload = make_comprehensive_payload(hr_bpm=72, rr_intervals=[830, 820, 840])
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, ComprehensiveRecord)
        assert result.hr is not None
        assert result.hr.hr_bpm == 72
        assert result.hr.rr_intervals_ms == [830.0, 820.0, 840.0]

    def test_hrv_computed(self):
        payload = make_comprehensive_payload(rr_intervals=[800, 810, 800])
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.hr.hrv_rmssd_ms is not None
        assert result.hr.hrv_lnrmssd_score is not None

    def test_no_rr_intervals(self):
        payload = make_comprehensive_payload(rr_intervals=[])
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, ComprehensiveRecord)
        assert result.hr.rr_intervals_ms == []
        assert result.hr.hrv_rmssd_ms is None
        assert result.hr.hrv_lnrmssd_score is None

    def test_single_rr_interval(self):
        payload = make_comprehensive_payload(rr_intervals=[850])
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.hr.rr_intervals_ms == [850.0]
        assert result.hr.hrv_rmssd_ms is None

    def test_many_rr_intervals(self):
        rr = list(range(800, 816))  # 16 intervals
        payload = make_comprehensive_payload(rr_intervals=rr)
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert len(result.hr.rr_intervals_ms) == 16

    def test_temperature_extraction(self):
        payload = make_comprehensive_payload(temp_c=36.50)
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.temperature is not None
        assert 36.0 <= result.temperature.skin_temp_c <= 37.0

    def test_temperature_various_values(self):
        for temp in (30.0, 33.5, 36.5, 38.0, 40.0):
            payload = make_comprehensive_payload(temp_c=temp)
            wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
            result = HistoricalDecoder.decode(wp)
            if result.temperature is not None:
                assert abs(result.temperature.skin_temp_c - temp) < 0.1

    def test_spo2_raw_extraction(self):
        payload = make_comprehensive_payload(
            ac_red=500, dc_red=10000, ac_ir=1000, dc_ir=10000
        )
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.spo2_raw is not None
        assert result.spo2_raw.red_ir_ratio == 0.5
        assert result.spo2_raw.estimated_spo2 == 97.5

    def test_spo2_ratio_out_of_range_no_estimation(self):
        """When AC/DC values don't produce a sensible ratio."""
        payload = make_comprehensive_payload(
            ac_red=0, dc_red=10000, ac_ir=1000, dc_ir=10000
        )
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.spo2_raw is not None
        # R = 0/10000 / (1000/10000) = 0 → 0 is outside [0.2, 1.5]
        assert result.spo2_raw.red_ir_ratio is None

    def test_timestamp(self):
        ts = 1707840000
        payload = make_comprehensive_payload(timestamp=ts)
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.timestamp == ts

    def test_short_payload_returns_none(self):
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, b"\x00\x01")
        result = HistoricalDecoder.decode(wp)
        assert result is None

    def test_payload_too_short_for_temp(self):
        """Payload long enough for HR but not temp — temp is None."""
        buf = bytearray(struct.pack("<I", 1707840000))  # timestamp
        buf.append(72)   # hr
        buf.append(0)    # rr_count = 0
        # Only 6 bytes — not enough for temp at offset 22
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, bytes(buf))
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, ComprehensiveRecord)
        assert result.hr.hr_bpm == 72
        assert result.temperature is None
        assert result.spo2_raw is None

    def test_raw_payload_preserved(self):
        payload = make_comprehensive_payload()
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        assert result.raw_payload == payload


class TestComprehensiveRecordRepr:
    def test_repr_full(self):
        payload = make_comprehensive_payload()
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, payload)
        result = HistoricalDecoder.decode(wp)
        r = repr(result)
        assert "ComprehensiveRecord" in r
        assert "hr=72bpm" in r
        assert "temp=" in r

    def test_repr_no_temp(self):
        buf = bytearray(struct.pack("<I", 1707840000))
        buf.append(72)
        buf.append(0)
        wp = make_historical_packet(HistoricalRecordType.COMPREHENSIVE, bytes(buf))
        result = HistoricalDecoder.decode(wp)
        r = repr(result)
        assert "temp=" not in r


# ===================================================================
# HR + RR record (0x2F)
# ===================================================================


class TestHRRRRecord:
    def test_basic(self):
        buf = bytearray()
        buf += struct.pack("<I", 1707840000)
        buf.append(65)  # HR
        buf.append(2)   # rr count
        buf += struct.pack("<HH", 920, 930)
        wp = make_historical_packet(HistoricalRecordType.HR_RR, bytes(buf))
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalHRRecord)
        assert result.hr_bpm == 65
        assert result.rr_intervals_ms == [920.0, 930.0]
        assert result.timestamp == 1707840000

    def test_no_rr_intervals(self):
        buf = struct.pack("<I", 1707840000) + bytes([60])  # 5 bytes, no rr_count
        wp = make_historical_packet(HistoricalRecordType.HR_RR, buf)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalHRRecord)
        assert result.hr_bpm == 60
        assert result.rr_intervals_ms == []

    def test_truncated_rr_data(self):
        """rr_count says 3 but only 2 intervals present."""
        buf = bytearray()
        buf += struct.pack("<I", 1707840000)
        buf.append(70)  # HR
        buf.append(3)   # claims 3 intervals
        buf += struct.pack("<HH", 800, 810)  # only 2
        wp = make_historical_packet(HistoricalRecordType.HR_RR, bytes(buf))
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalHRRecord)
        assert len(result.rr_intervals_ms) == 2  # gracefully decoded what was available

    def test_hrv_computed(self):
        buf = bytearray()
        buf += struct.pack("<I", 1707840000)
        buf.append(72)
        buf.append(3)
        buf += struct.pack("<HHH", 800, 810, 800)
        wp = make_historical_packet(HistoricalRecordType.HR_RR, bytes(buf))
        result = HistoricalDecoder.decode(wp)
        assert result.hrv_rmssd_ms is not None
        assert result.hrv_lnrmssd_score is not None

    def test_too_short_returns_none(self):
        wp = make_historical_packet(HistoricalRecordType.HR_RR, b"\x00\x01\x02")
        result = HistoricalDecoder.decode(wp)
        assert result is None


class TestHRRecordRepr:
    def test_repr_basic(self):
        d = HistoricalHRRecord(timestamp=100, hr_bpm=72, rr_intervals_ms=[])
        r = repr(d)
        assert "HistHR" in r
        assert "72bpm" in r

    def test_repr_with_rr(self):
        d = HistoricalHRRecord(timestamp=100, hr_bpm=72, rr_intervals_ms=[800.0, 810.0])
        assert "rr=" in repr(d)

    def test_repr_with_hrv(self):
        d = HistoricalHRRecord(
            timestamp=100, hr_bpm=72, rr_intervals_ms=[800.0, 810.0],
            hrv_rmssd_ms=10.0,
        )
        assert "hrv=" in repr(d)

    def test_repr_with_score(self):
        d = HistoricalHRRecord(
            timestamp=100, hr_bpm=72, rr_intervals_ms=[800.0, 810.0],
            hrv_rmssd_ms=10.0, hrv_lnrmssd_score=35.4,
        )
        assert "score=" in repr(d)


# ===================================================================
# Event record (0x30)
# ===================================================================


class TestEventRecord:
    def test_basic(self):
        buf = struct.pack("<I", 1707840000) + bytes([0x3C, 0x01, 0x02])
        wp = make_historical_packet(HistoricalRecordType.EVENT, buf)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalEventRecord)
        assert result.event_id == 0x3C
        assert result.event_data == b"\x01\x02"
        assert result.timestamp == 1707840000

    def test_minimal_event(self):
        """Event with no extra data."""
        buf = struct.pack("<I", 1707840000) + bytes([0x64])
        wp = make_historical_packet(HistoricalRecordType.EVENT, buf)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalEventRecord)
        assert result.event_data == b""

    def test_too_short_returns_none(self):
        wp = make_historical_packet(HistoricalRecordType.EVENT, b"\x00\x01\x02")
        result = HistoricalDecoder.decode(wp)
        assert result is None

    def test_repr(self):
        d = HistoricalEventRecord(timestamp=100, event_id=0x3C, event_data=b"\xAB")
        r = repr(d)
        assert "HistEvent" in r
        assert "0x3C" in r


# ===================================================================
# Accelerometer batch (0x34 / IMU)
# ===================================================================


class TestAccelBatch:
    def test_multiple_samples(self):
        buf = bytearray()
        buf += struct.pack("<I", 1707840000)
        buf += struct.pack("<hhh", 2048, -2048, 0)   # 1g, -1g, 0g
        buf += struct.pack("<hhh", 0, 0, 2048)       # 0g, 0g, 1g
        wp = make_historical_packet(HistoricalRecordType.ACCEL_BATCH, bytes(buf))
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalAccelBatch)
        assert len(result.samples) == 2
        assert abs(result.samples[0][0] - 1.0) < 0.01
        assert abs(result.samples[0][1] - (-1.0)) < 0.01
        assert abs(result.samples[1][2] - 1.0) < 0.01

    def test_scaling(self):
        """int16 2048 → 1.0g at the default scale."""
        buf = struct.pack("<I", 0) + struct.pack("<hhh", 2048, 4096, -2048)
        wp = make_historical_packet(HistoricalRecordType.ACCEL_BATCH, buf)
        result = HistoricalDecoder.decode(wp)
        assert abs(result.samples[0][0] - 1.0) < 0.01
        assert abs(result.samples[0][1] - 2.0) < 0.01
        assert abs(result.samples[0][2] - (-1.0)) < 0.01

    def test_too_short_returns_none(self):
        wp = make_historical_packet(HistoricalRecordType.ACCEL_BATCH, b"\x00" * 5)
        result = HistoricalDecoder.decode(wp)
        assert result is None

    def test_partial_sample_ignored(self):
        buf = struct.pack("<I", 0) + struct.pack("<hhh", 100, 200, 300) + b"\x01\x02"
        wp = make_historical_packet(HistoricalRecordType.ACCEL_BATCH, buf)
        result = HistoricalDecoder.decode(wp)
        assert len(result.samples) == 1

    def test_imu_packet_type(self):
        """HISTORICAL_IMU_DATA packets go through accel batch decoder."""
        buf = struct.pack("<I", 1707840000) + struct.pack("<hhh", 1024, 512, 256)
        wp = make_historical_imu_packet(data=buf)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, HistoricalAccelBatch)

    def test_repr(self):
        d = HistoricalAccelBatch(timestamp=100, samples=[(1.0, 0.0, 0.0)])
        r = repr(d)
        assert "HistAccelBatch" in r
        assert "1 samples" in r


# ===================================================================
# Unknown subtype
# ===================================================================


class TestUnknownSubtype:
    def test_returns_dict(self):
        wp = make_historical_packet(0xFF, b"\x00" * 20)
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, dict)
        assert result["type"] == "unknown_historical"
        assert result["subtype"] == 0xFF
        assert result["payload_len"] == 20

    def test_extracts_timestamp(self):
        buf = struct.pack("<I", 1707840000) + b"\x00" * 16
        wp = make_historical_packet(0xFE, buf)
        result = HistoricalDecoder.decode(wp)
        assert result["timestamp"] == 1707840000

    def test_short_payload(self):
        wp = make_historical_packet(0xFD, b"\x01\x02")
        result = HistoricalDecoder.decode(wp)
        assert isinstance(result, dict)
        assert result["payload_hex"] == "0102"


# ===================================================================
# SpO2 raw record repr
# ===================================================================


class TestSpO2RawRecordRepr:
    def test_repr_no_estimation(self):
        d = HistoricalSpO2RawRecord(timestamp=100, raw_bytes=b"\x00" * 10)
        r = repr(d)
        assert "HistSpO2Raw" in r
        assert "10B" in r
        assert "spo2" not in r

    def test_repr_with_estimation(self):
        d = HistoricalSpO2RawRecord(
            timestamp=100, raw_bytes=b"\x00" * 16,
            red_ir_ratio=0.5, estimated_spo2=97.5,
        )
        r = repr(d)
        assert "spo2≈97.5%" in r


class TestTempRecordRepr:
    def test_repr(self):
        d = HistoricalTempRecord(timestamp=100, skin_temp_c=36.5, skin_temp_f=97.7)
        r = repr(d)
        assert "HistTemp" in r
        assert "36.50" in r
