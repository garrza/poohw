"""Tests for heart_rate.py — standard BLE Heart Rate Measurement (0x2A37) parser."""

import struct

import pytest

from poohw.heart_rate import parse_heart_rate


class TestParseHeartRateUint8:
    """HR format flag bit 0 = 0 → uint8 HR value."""

    def test_basic_uint8_hr(self):
        """Flags=0x00 (uint8, no RR, no energy), HR=72."""
        data = bytearray([0x00, 72])
        result = parse_heart_rate(data)
        assert result["hr_bpm"] == 72
        assert result["rr_intervals_ms"] == []
        assert result["energy_expended_kj"] is None

    def test_hr_zero(self):
        data = bytearray([0x00, 0])
        assert parse_heart_rate(data)["hr_bpm"] == 0

    def test_hr_max_uint8(self):
        data = bytearray([0x00, 255])
        assert parse_heart_rate(data)["hr_bpm"] == 255


class TestParseHeartRateUint16:
    """HR format flag bit 0 = 1 → uint16 LE HR value."""

    def test_basic_uint16_hr(self):
        """Flags=0x01 (uint16), HR=300 (tachycardic)."""
        data = bytearray([0x01]) + bytearray(struct.pack("<H", 300))
        result = parse_heart_rate(data)
        assert result["hr_bpm"] == 300

    def test_uint16_normal_hr(self):
        data = bytearray([0x01]) + bytearray(struct.pack("<H", 72))
        assert parse_heart_rate(data)["hr_bpm"] == 72


class TestParseHeartRateSensorContact:
    def test_no_contact_support(self):
        """Flags bit 1 = 0 → sensor_contact is None."""
        data = bytearray([0x00, 72])
        result = parse_heart_rate(data)
        assert result["sensor_contact"] is None

    def test_contact_supported_detected(self):
        """Bits 1+2 both set → supported=True, detected=True."""
        data = bytearray([0x06, 72])  # 0b00000110
        result = parse_heart_rate(data)
        assert result["sensor_contact"] is True

    def test_contact_supported_not_detected(self):
        """Bit 1 set, bit 2 clear → supported=True, detected=False."""
        data = bytearray([0x02, 72])  # 0b00000010
        result = parse_heart_rate(data)
        assert result["sensor_contact"] is False


class TestParseHeartRateEnergyExpended:
    def test_energy_present(self):
        """Flags bit 3 set → uint16 energy follows HR."""
        flags = 0x08  # energy expended present
        data = bytearray([flags, 72]) + bytearray(struct.pack("<H", 150))  # 150 kJ
        result = parse_heart_rate(data)
        assert result["hr_bpm"] == 72
        assert result["energy_expended_kj"] == 150

    def test_energy_not_present(self):
        data = bytearray([0x00, 72])
        assert parse_heart_rate(data)["energy_expended_kj"] is None


class TestParseHeartRateRRIntervals:
    def test_single_rr_interval(self):
        """Flags bit 4 set → RR intervals follow."""
        flags = 0x10  # RR present
        # RR raw value in 1/1024 sec units:  800ms ≈ 819.2 in 1/1024s → raw = 819
        rr_raw = 819  # ≈ 799.8ms
        data = bytearray([flags, 72]) + bytearray(struct.pack("<H", rr_raw))
        result = parse_heart_rate(data)
        assert len(result["rr_intervals_ms"]) == 1
        rr_ms = result["rr_intervals_ms"][0]
        assert 798.0 <= rr_ms <= 802.0

    def test_multiple_rr_intervals(self):
        flags = 0x10
        rr1, rr2, rr3 = 820, 830, 810
        data = (
            bytearray([flags, 72])
            + bytearray(struct.pack("<HHH", rr1, rr2, rr3))
        )
        result = parse_heart_rate(data)
        assert len(result["rr_intervals_ms"]) == 3

    def test_rr_conversion_to_ms(self):
        """Verify the 1/1024s → ms conversion."""
        flags = 0x10
        rr_raw = 1024  # exactly 1 second = 1000ms
        data = bytearray([flags, 72]) + bytearray(struct.pack("<H", rr_raw))
        result = parse_heart_rate(data)
        assert result["rr_intervals_ms"][0] == 1000.0

    def test_no_rr_when_flag_clear(self):
        data = bytearray([0x00, 72])
        assert parse_heart_rate(data)["rr_intervals_ms"] == []


class TestParseHeartRateCombined:
    def test_all_fields(self):
        """uint16 HR + energy + RR intervals."""
        flags = 0x01 | 0x08 | 0x10  # uint16 + energy + RR
        hr = struct.pack("<H", 85)
        energy = struct.pack("<H", 200)
        rr = struct.pack("<HH", 820, 830)
        data = bytearray([flags]) + bytearray(hr) + bytearray(energy) + bytearray(rr)

        result = parse_heart_rate(data)
        assert result["hr_bpm"] == 85
        assert result["energy_expended_kj"] == 200
        assert len(result["rr_intervals_ms"]) == 2

    def test_uint8_with_rr(self):
        """uint8 HR + RR intervals."""
        flags = 0x10
        data = bytearray([flags, 65]) + bytearray(struct.pack("<H", 900))
        result = parse_heart_rate(data)
        assert result["hr_bpm"] == 65
        assert len(result["rr_intervals_ms"]) == 1
        assert result["energy_expended_kj"] is None

    def test_uint8_with_energy_and_rr(self):
        """uint8 HR + energy + RR."""
        flags = 0x08 | 0x10
        data = (
            bytearray([flags, 70])
            + bytearray(struct.pack("<H", 50))   # energy
            + bytearray(struct.pack("<H", 850))  # RR
        )
        result = parse_heart_rate(data)
        assert result["hr_bpm"] == 70
        assert result["energy_expended_kj"] == 50
        assert len(result["rr_intervals_ms"]) == 1
