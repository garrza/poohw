"""Tests for poohw.analytics.strain -- strain / TRIMP scoring."""

import pytest

from poohw.analytics.strain import (
    score_strain,
    StrainResult,
    _classify_zone,
    ZONE_LABELS,
    ZONE_WEIGHTS,
    STRAIN_MAX,
)


class TestClassifyZone:
    def test_below_zone_1(self):
        assert _classify_zone(0.40) == 0  # below 50%

    def test_zone_1(self):
        assert _classify_zone(0.55) == 1  # 50-60%

    def test_zone_2(self):
        assert _classify_zone(0.65) == 2  # 60-70%

    def test_zone_3(self):
        assert _classify_zone(0.75) == 3  # 70-80%

    def test_zone_4(self):
        assert _classify_zone(0.85) == 4  # 80-90%

    def test_zone_5(self):
        assert _classify_zone(0.95) == 5  # 90-100%

    def test_boundary_50(self):
        assert _classify_zone(0.50) == 1  # at exactly 50% → zone 1

    def test_at_100_percent(self):
        assert _classify_zone(1.00) == 5  # at exactly 100% → zone 5


class TestScoreStrain:
    def test_empty_input(self):
        result = score_strain([])
        assert result.score == 0.0
        assert result.raw_trimp == 0.0
        assert result.peak_hr == 0.0
        assert all(v == 0.0 for v in result.zone_minutes.values())

    def test_all_zone_1(self):
        # HR at 55% of max (190) = 104.5
        hr = [105.0] * 60  # 60 minutes in zone 1
        result = score_strain(hr, max_hr=190.0)
        assert result.zone_minutes["Zone 1"] == 60.0
        assert result.raw_trimp == 60.0 * ZONE_WEIGHTS[0]
        assert result.score > 0

    def test_all_zone_5(self):
        # HR at 95% of max = 180.5
        hr = [181.0] * 30  # 30 minutes in zone 5
        result = score_strain(hr, max_hr=190.0)
        assert result.zone_minutes["Zone 5"] == 30.0
        assert result.score > result.raw_trimp * 0  # sanity

    def test_below_zone_1_no_strain(self):
        # HR at 40% of max = 76
        hr = [76.0] * 60
        result = score_strain(hr, max_hr=190.0)
        assert result.score == 0.0
        assert result.raw_trimp == 0.0

    def test_score_capped_at_21(self):
        # Extreme activity
        hr = [185.0] * 1000  # 1000 minutes in zone 5
        result = score_strain(hr, max_hr=190.0)
        assert result.score <= STRAIN_MAX

    def test_peak_and_avg(self):
        hr = [100.0, 150.0, 180.0, 120.0]
        result = score_strain(hr, max_hr=190.0)
        assert result.peak_hr == 180.0
        assert result.avg_hr == pytest.approx(137.5, abs=0.1)

    def test_calorie_estimate(self):
        hr = [120.0] * 60  # 60 minutes at 120 bpm
        result = score_strain(hr, max_hr=190.0, resting_hr=60.0)
        assert result.calories_estimate > 0

    def test_mixed_zones(self):
        hr = [105.0] * 20 + [140.0] * 20 + [175.0] * 20
        result = score_strain(hr, max_hr=190.0)
        assert result.zone_minutes["Zone 1"] == 20.0
        assert result.zone_minutes["Zone 3"] > 0 or result.zone_minutes["Zone 4"] > 0

    def test_result_repr(self):
        result = StrainResult(
            score=12.5, raw_trimp=150.0, peak_hr=175.0,
            avg_hr=140.0, zone_minutes={}, calories_estimate=450.0,
        )
        s = repr(result)
        assert "12.5" in s
        assert "21" in s

    def test_zone_labels_present(self):
        hr = [105.0] * 10
        result = score_strain(hr, max_hr=190.0)
        for label in ZONE_LABELS:
            assert label in result.zone_minutes
