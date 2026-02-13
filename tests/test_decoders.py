"""Tests for realtime sensor decoders — HR, Accel, Temperature, SpO2."""

import struct
import math

import pytest

from poohw.protocol import PacketType, Command, build_packet
from poohw.decoders.packet import PacketDecoder, WhoopPacket
from poohw.decoders.hr import HeartRateDecoder, HeartRateData, HR_PACKET_TYPES
from poohw.decoders.accel import AccelDecoder, AccelSample, AccelData, ACCEL_PACKET_TYPES
from poohw.decoders.temperature import TemperatureDecoder, TemperatureData, TEMP_PACKET_TYPES
from poohw.decoders.spo2 import SpO2Decoder, SpO2Data, SPO2_PACKET_TYPES

from tests.conftest import (
    make_packet,
    make_realtime_packet,
    make_realtime_raw_packet,
    make_imu_packet,
    make_historical_imu_packet,
    make_command_packet,
)


# ===================================================================
# HeartRateDecoder
# ===================================================================


class TestHeartRateDecoderCanDecode:
    def test_realtime_data_yes(self):
        wp = make_realtime_packet(data=b"\x00\x48")
        assert HeartRateDecoder.can_decode(wp) is True

    def test_realtime_raw_data_yes(self):
        wp = make_realtime_raw_packet(data=b"\x00\x48")
        assert HeartRateDecoder.can_decode(wp) is True

    def test_command_no(self):
        wp = make_command_packet()
        assert HeartRateDecoder.can_decode(wp) is False

    def test_historical_data_no(self):
        wp = make_packet(PacketType.HISTORICAL_DATA, 0x2F, b"\x00" * 10)
        assert HeartRateDecoder.can_decode(wp) is False

    def test_imu_data_no(self):
        wp = make_imu_packet(data=b"\x00" * 10)
        assert HeartRateDecoder.can_decode(wp) is False

    def test_packet_types_set(self):
        assert PacketType.REALTIME_DATA in HR_PACKET_TYPES
        assert PacketType.REALTIME_RAW_DATA in HR_PACKET_TYPES


class TestHeartRateDecoderDecode:
    def test_hr_at_offset_1(self):
        """HR byte at offset 1 (after cmd byte), value 72."""
        payload = bytes([0x00, 72])  # cmd=0, hr=72
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        assert result.hr_bpm == 72

    def test_hr_at_offset_2(self):
        """HR byte at offset 2 (cmd + sub_cmd)."""
        payload = bytes([0x00, 0x01, 80])  # cmd, sub, hr=80
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        assert result.hr_bpm == 80

    def test_hr_at_offset_3(self):
        """HR byte at offset 3."""
        # Offsets 1 and 2 are out of HR range, offset 3 = 65
        payload = bytes([0x00, 0x01, 0x02, 65])
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        assert result.hr_bpm == 65

    def test_hr_uint16_fallback(self):
        """uint16 LE at offset 1 when no uint8 candidate found."""
        # byte[1]=0x00 (not in 30-220), byte[2]=0x00, byte[3] not present
        # uint16 at offset 1 = 150 (0x96, 0x00)
        payload = bytes([0x00, 0x96, 0x00])
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        assert result.hr_bpm == 150

    def test_too_short_returns_none(self):
        wp = make_realtime_packet(data=b"\x00")
        result = HeartRateDecoder.decode(wp)
        assert result is None

    def test_no_plausible_hr_returns_none(self):
        """All bytes are outside 30-220 range."""
        payload = bytes([0x00, 0x00, 0x00, 0x00, 0x00])
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is None

    def test_with_rr_intervals(self):
        """HR at offset 1, followed by plausible RR intervals."""
        rr1, rr2 = 800, 820
        payload = bytes([0x00, 72]) + struct.pack("<HH", rr1, rr2)
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        assert result.hr_bpm == 72
        assert len(result.rr_intervals_ms) >= 1

    def test_rmssd_computed_when_enough_rr(self):
        """RMSSD is computed when >= 2 RR intervals."""
        rr1, rr2 = 800, 810
        payload = bytes([0x00, 72]) + struct.pack("<HH", rr1, rr2)
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        if len(result.rr_intervals_ms) >= 2:
            assert result.hrv_rmssd_ms is not None

    def test_preserves_raw_payload(self):
        payload = bytes([0x00, 72, 0x01, 0x02])
        wp = make_realtime_packet(data=payload)
        result = HeartRateDecoder.decode(wp)
        assert result is not None
        assert result.raw_payload == payload


class TestHeartRateDataRepr:
    def test_basic_repr(self):
        d = HeartRateData(hr_bpm=72, rr_intervals_ms=[])
        r = repr(d)
        assert "72bpm" in r
        assert "HeartRateData" in r

    def test_repr_with_rr(self):
        d = HeartRateData(hr_bpm=72, rr_intervals_ms=[800.0, 810.0])
        r = repr(d)
        assert "rr=" in r

    def test_repr_with_hrv(self):
        d = HeartRateData(hr_bpm=72, rr_intervals_ms=[800.0, 810.0], hrv_rmssd_ms=10.0)
        r = repr(d)
        assert "hrv=" in r


# ===================================================================
# AccelDecoder
# ===================================================================


class TestAccelDecoderCanDecode:
    def test_realtime_imu_yes(self):
        wp = make_imu_packet(data=b"\x00" * 10)
        assert AccelDecoder.can_decode(wp) is True

    def test_historical_imu_yes(self):
        wp = make_historical_imu_packet(data=b"\x00" * 10)
        assert AccelDecoder.can_decode(wp) is True

    def test_realtime_data_no(self):
        wp = make_realtime_packet(data=b"\x00" * 10)
        assert AccelDecoder.can_decode(wp) is False

    def test_command_no(self):
        wp = make_command_packet()
        assert AccelDecoder.can_decode(wp) is False

    def test_packet_types_set(self):
        assert PacketType.REALTIME_IMU_DATA in ACCEL_PACKET_TYPES
        assert PacketType.HISTORICAL_IMU_DATA in ACCEL_PACKET_TYPES


class TestAccelDecoderDecode:
    def test_single_sample(self):
        """One 3-axis sample after the command byte."""
        # 1g on x-axis: int16 2048 * (1/2048) = 1.0
        sample = struct.pack("<hhh", 2048, 0, 0)
        payload = b"\x00" + sample  # cmd byte + 1 sample
        wp = make_imu_packet(data=payload)
        result = AccelDecoder.decode(wp)
        assert result is not None
        assert len(result.samples) == 1
        assert abs(result.samples[0].x - 1.0) < 0.01
        assert abs(result.samples[0].y) < 0.01
        assert abs(result.samples[0].z) < 0.01

    def test_multiple_samples(self):
        s1 = struct.pack("<hhh", 2048, -2048, 0)
        s2 = struct.pack("<hhh", 0, 0, 2048)
        s3 = struct.pack("<hhh", 1024, 1024, 1024)
        payload = b"\x00" + s1 + s2 + s3
        wp = make_imu_packet(data=payload)
        result = AccelDecoder.decode(wp)
        assert result is not None
        assert len(result.samples) == 3

    def test_negative_values(self):
        """Negative int16 → negative g."""
        sample = struct.pack("<hhh", -4096, -4096, -4096)
        payload = b"\x00" + sample
        wp = make_imu_packet(data=payload)
        result = AccelDecoder.decode(wp)
        assert result is not None
        assert result.samples[0].x < 0
        assert result.samples[0].y < 0
        assert result.samples[0].z < 0

    def test_custom_scale(self):
        sample = struct.pack("<hhh", 1000, 0, 0)
        payload = b"\x00" + sample
        wp = make_imu_packet(data=payload)
        result = AccelDecoder.decode(wp, scale=1.0 / 1000.0)
        assert result is not None
        assert abs(result.samples[0].x - 1.0) < 0.01

    def test_too_short_returns_none(self):
        wp = make_imu_packet(data=b"\x00\x01")
        result = AccelDecoder.decode(wp)
        assert result is None

    def test_partial_last_sample_ignored(self):
        """Trailing bytes that don't form a complete sample are skipped."""
        sample = struct.pack("<hhh", 2048, 0, 0)
        payload = b"\x00" + sample + b"\x01\x02"  # 2 trailing bytes
        wp = make_imu_packet(data=payload)
        result = AccelDecoder.decode(wp)
        assert result is not None
        assert len(result.samples) == 1

    def test_preserves_raw_payload(self):
        sample = struct.pack("<hhh", 100, 200, 300)
        payload = b"\x00" + sample
        wp = make_imu_packet(data=payload)
        result = AccelDecoder.decode(wp)
        assert result.raw_payload == payload


class TestAccelSample:
    def test_magnitude_at_rest(self):
        s = AccelSample(x=0.0, y=0.0, z=1.0)
        assert abs(s.magnitude - 1.0) < 0.001

    def test_magnitude_diagonal(self):
        s = AccelSample(x=1.0, y=1.0, z=1.0)
        expected = math.sqrt(3)
        assert abs(s.magnitude - expected) < 0.001

    def test_magnitude_zero(self):
        s = AccelSample(x=0.0, y=0.0, z=0.0)
        assert s.magnitude == 0.0

    def test_repr(self):
        s = AccelSample(x=0.5, y=-0.5, z=1.0)
        r = repr(s)
        assert "Accel" in r
        assert "0.500g" in r
        assert "mag=" in r


class TestAccelDataRepr:
    def test_repr_shows_count(self):
        d = AccelData(samples=[AccelSample(0, 0, 1), AccelSample(0, 1, 0)])
        r = repr(d)
        assert "2 samples" in r


# ===================================================================
# TemperatureDecoder
# ===================================================================


class TestTemperatureDecoderCanDecode:
    def test_realtime_data_yes(self):
        wp = make_realtime_packet(data=b"\x00\x00\x00")
        assert TemperatureDecoder.can_decode(wp) is True

    def test_command_no(self):
        wp = make_command_packet()
        assert TemperatureDecoder.can_decode(wp) is False

    def test_imu_no(self):
        wp = make_imu_packet(data=b"\x00" * 10)
        assert TemperatureDecoder.can_decode(wp) is False

    def test_packet_types_set(self):
        assert PacketType.REALTIME_DATA in TEMP_PACKET_TYPES


class TestTemperatureDecoderDecode:
    def test_hundredths_c(self):
        """uint16 LE at offset 1, hundredths of °C — 3650 = 36.50°C."""
        raw = struct.pack("<H", 3650)
        payload = b"\x00" + raw
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result is not None
        assert result.skin_temp_c == 36.50
        assert abs(result.skin_temp_f - 97.7) < 0.1

    def test_tenths_c(self):
        """int16 LE at offset 1, tenths of °C — 370 = 37.0°C."""
        # The uint16 path (370 / 100 = 3.70) is outside [25, 45], so
        # it falls through to the int16/tenths path.
        raw = struct.pack("<h", 370)
        payload = b"\x00" + raw
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result is not None
        assert result.skin_temp_c == 37.0

    def test_direct_byte(self):
        """uint8 at offset 1, direct Celsius — 36."""
        # byte[1]=36, but uint16 at [1:3] = 36 + 256*0 = 36 → 0.36°C (out of range)
        # int16 at [1:3] = same → 3.6°C (out of range)
        # uint8 at [1] = 36 → 36°C ✓
        payload = bytes([0x00, 36, 0x00])
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result is not None
        assert result.skin_temp_c == 36.0

    def test_out_of_range_all_strategies(self):
        """No encoding yields a valid temperature."""
        # All values out of [25, 45] range
        payload = bytes([0x00, 0x01, 0x00])  # uint16=1→0.01C, int16=1→0.1C, uint8=1
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result is None

    def test_too_short_returns_none(self):
        wp = make_realtime_packet(data=b"\x00\x01")
        result = TemperatureDecoder.decode(wp)
        assert result is None

    def test_fahrenheit_conversion(self):
        """Verify C→F conversion: 37°C = 98.6°F."""
        raw = struct.pack("<H", 3700)  # 37.00°C
        payload = b"\x00" + raw
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result is not None
        assert abs(result.skin_temp_f - 98.6) < 0.1

    def test_preserves_raw_value(self):
        raw = struct.pack("<H", 3650)
        payload = b"\x00" + raw
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result.raw_value == 3650

    def test_preserves_raw_payload(self):
        raw = struct.pack("<H", 3650)
        payload = b"\x00" + raw
        wp = make_realtime_packet(data=payload)
        result = TemperatureDecoder.decode(wp)
        assert result.raw_payload == payload


class TestTemperatureDataRepr:
    def test_repr(self):
        d = TemperatureData(skin_temp_c=36.5, skin_temp_f=97.7, raw_value=3650)
        r = repr(d)
        assert "Temperature" in r
        assert "36.50" in r
        assert "97.70" in r


# ===================================================================
# SpO2Decoder
# ===================================================================


class TestSpO2DecoderCanDecode:
    def test_realtime_data_yes(self):
        wp = make_realtime_packet(data=b"\x00\x62")
        assert SpO2Decoder.can_decode(wp) is True

    def test_command_no(self):
        wp = make_command_packet()
        assert SpO2Decoder.can_decode(wp) is False

    def test_imu_no(self):
        wp = make_imu_packet(data=b"\x00" * 10)
        assert SpO2Decoder.can_decode(wp) is False

    def test_packet_types_set(self):
        assert PacketType.REALTIME_DATA in SPO2_PACKET_TYPES


class TestSpO2DecoderDecode:
    def test_uint8_direct(self):
        """uint8 at offset 1 = 98 → 98%."""
        payload = bytes([0x00, 98])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.spo2_percent == 98.0

    def test_uint8_with_confidence(self):
        """uint8 SpO2 + confidence byte."""
        payload = bytes([0x00, 97, 85])  # SpO2=97%, confidence=85%
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.spo2_percent == 97.0
        assert result.confidence == 85

    def test_uint8_confidence_out_of_range_ignored(self):
        """Confidence byte > 100 is not treated as confidence."""
        payload = bytes([0x00, 98, 200])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.confidence is None

    def test_uint16_tenths(self):
        """uint16 LE at offset 1, tenths of % — 970 = 97.0%."""
        # byte[1] must be outside [70, 100] for the uint16 path
        raw = struct.pack("<H", 970)
        # 970 as bytes: [0xCA, 0x03] — byte[1]=0xCA=202, outside [70,100]
        payload = b"\x00" + raw
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.spo2_percent == 97.0

    def test_uint16_with_confidence(self):
        raw = struct.pack("<H", 980)
        payload = b"\x00" + raw + bytes([90])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.spo2_percent == 98.0
        assert result.confidence == 90

    def test_out_of_range_returns_none(self):
        """No encoding yields a valid SpO2."""
        # byte[1]=10 (not in 70-100), uint16=10 → 1.0% (not in 70-100)
        payload = bytes([0x00, 10, 0x00])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is None

    def test_too_short_returns_none(self):
        wp = make_realtime_packet(data=b"\x00")
        result = SpO2Decoder.decode(wp)
        assert result is None

    def test_edge_value_70(self):
        payload = bytes([0x00, 70])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.spo2_percent == 70.0

    def test_edge_value_100(self):
        payload = bytes([0x00, 100])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result is not None
        assert result.spo2_percent == 100.0

    def test_preserves_raw(self):
        payload = bytes([0x00, 98])
        wp = make_realtime_packet(data=payload)
        result = SpO2Decoder.decode(wp)
        assert result.raw_value == 98
        assert result.raw_payload == payload


class TestSpO2DataRepr:
    def test_repr_no_confidence(self):
        d = SpO2Data(spo2_percent=98.0)
        r = repr(d)
        assert "SpO2" in r
        assert "98.0%" in r
        assert "confidence" not in r

    def test_repr_with_confidence(self):
        d = SpO2Data(spo2_percent=97.0, confidence=85)
        r = repr(d)
        assert "confidence=85%" in r
