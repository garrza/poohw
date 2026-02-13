"""Tests for poohw.analytics.spo2 -- SpO2 estimation and aggregation."""

import pytest

from poohw.analytics.spo2 import (
    estimate_spo2_from_ratio,
    is_quality_reading,
    analyze_spo2_session,
    SpO2Result,
    R_MIN,
    R_MAX,
    DC_MIN,
)


class TestEstimateSpO2:
    def test_r_equals_0_4(self):
        # 110 - 25*0.4 = 100
        assert estimate_spo2_from_ratio(0.4) == 100.0

    def test_r_equals_1_0(self):
        # 110 - 25*1.0 = 85
        assert estimate_spo2_from_ratio(1.0) == 85.0

    def test_r_equals_0_5(self):
        # 110 - 25*0.5 = 97.5
        assert estimate_spo2_from_ratio(0.5) == 97.5

    def test_clamped_low(self):
        # Very high R → negative SpO2 → clamped to 0
        assert estimate_spo2_from_ratio(5.0) == 0.0

    def test_clamped_high(self):
        # Negative R → SpO2 > 100 → clamped to 100
        assert estimate_spo2_from_ratio(-1.0) == 100.0

    def test_zero_r(self):
        # 110 - 0 = 110 → clamped to 100
        assert estimate_spo2_from_ratio(0.0) == 100.0


class TestIsQualityReading:
    def test_good_reading(self):
        assert is_quality_reading(0.6) is True

    def test_r_too_low(self):
        assert is_quality_reading(0.1) is False

    def test_r_too_high(self):
        assert is_quality_reading(1.5) is False

    def test_r_at_min_boundary(self):
        assert is_quality_reading(R_MIN) is True

    def test_r_at_max_boundary(self):
        assert is_quality_reading(R_MAX) is True

    def test_dc_red_too_low(self):
        assert is_quality_reading(0.6, dc_red=10) is False

    def test_dc_ir_too_low(self):
        assert is_quality_reading(0.6, dc_ir=10) is False

    def test_dc_above_threshold(self):
        assert is_quality_reading(0.6, dc_red=100, dc_ir=100) is True


class TestAnalyzeSpO2Session:
    def test_empty(self):
        result = analyze_spo2_session([])
        assert result.median_pct == 0.0
        assert result.quality_score == 0.0
        assert len(result.readings) == 0

    def test_all_good_readings(self):
        ratios = [0.5, 0.5, 0.5]  # all SpO2 ≈ 97.5
        result = analyze_spo2_session(ratios)
        assert result.median_pct == 97.5
        assert result.min_pct == 97.5
        assert result.quality_score == 1.0
        assert len(result.readings) == 3

    def test_some_bad_readings(self):
        ratios = [0.5, 0.1, 0.5, 2.0, 0.5]  # 2 out of range
        result = analyze_spo2_session(ratios)
        assert result.quality_score == pytest.approx(3 / 5, abs=0.01)
        assert len(result.readings) == 3

    def test_all_bad_readings(self):
        ratios = [0.1, 0.1, 2.0]
        result = analyze_spo2_session(ratios)
        assert result.quality_score == 0.0
        assert len(result.readings) == 0

    def test_time_below_90(self):
        # R > 0.8 → SpO2 < 90; R=0.9 → SpO2=87.5; R=1.0 → SpO2=85
        ratios = [0.5, 0.5, 0.5, 0.9, 1.0]
        result = analyze_spo2_session(ratios)
        assert result.time_below_90 > 0

    def test_with_dc_filtering(self):
        ratios = [0.5, 0.5, 0.5]
        dc_reds = [100.0, 10.0, 100.0]  # middle one bad
        dc_irs = [100.0, 100.0, 100.0]
        result = analyze_spo2_session(ratios, dc_reds, dc_irs)
        assert len(result.readings) == 2
        assert result.quality_score == pytest.approx(2 / 3, abs=0.01)

    def test_result_repr(self):
        result = SpO2Result(
            median_pct=97.0, min_pct=94.0,
            readings=[97.0, 96.0, 94.0],
            quality_score=0.9,
        )
        s = repr(result)
        assert "97.0" in s
        assert "94.0" in s
