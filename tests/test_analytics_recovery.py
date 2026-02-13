"""Tests for poohw.analytics.recovery -- recovery scoring."""

import pytest
import numpy as np

from poohw.analytics.recovery import (
    score_recovery,
    RecoveryResult,
    _resting_hr,
    W_HRV,
    W_RHR,
    W_SLEEP,
)


class TestRestingHR:
    def test_empty(self):
        assert _resting_hr([]) == 0.0

    def test_short_series(self):
        # Shorter than window → returns mean
        result = _resting_hr([60.0, 62.0, 58.0], window_min=5)
        assert abs(result - 60.0) < 0.1

    def test_rolling_minimum(self):
        # 10 values: 70,70,70,70,70,60,60,60,60,60
        # 5-min rolling avgs: [70, 68, 66, 64, 62, 60]
        # Minimum = 60
        hr = [70.0] * 5 + [60.0] * 5
        result = _resting_hr(hr, window_min=5)
        assert result == 60.0

    def test_constant_hr(self):
        hr = [65.0] * 20
        result = _resting_hr(hr)
        assert result == 65.0


class TestScoreRecovery:
    def test_good_recovery(self):
        # High HRV, low resting HR, good sleep
        rr = [800.0 + i * 5 for i in range(100)]  # moderate variation
        hr = [55.0] * 60  # low resting HR
        result = score_recovery(rr, hr, actual_sleep_min=450.0, sleep_need_min=450.0)
        assert result.score > 50.0  # should be decent
        assert result.resting_hr == 55.0
        assert result.sleep_performance == 1.0

    def test_poor_recovery(self):
        # Low HRV (constant RR), high resting HR, poor sleep
        rr = [800.0, 800.0, 800.0]  # zero variation → RMSSD = 0
        hr = [85.0] * 60
        result = score_recovery(rr, hr, actual_sleep_min=200.0, sleep_need_min=450.0)
        assert result.score < 50.0  # should be low
        assert result.hrv_ms == 0.0

    def test_no_rr_intervals(self):
        result = score_recovery([], [70.0] * 30, actual_sleep_min=400.0)
        assert result.hrv_ms == 0.0
        assert result.hrv_score == 0.0

    def test_score_bounded_0_100(self):
        rr = [800.0 + i * 20 for i in range(200)]
        hr = [45.0] * 100
        result = score_recovery(rr, hr, actual_sleep_min=600.0)
        assert 0.0 <= result.score <= 100.0

    def test_sleep_performance_above_1(self):
        rr = [800.0, 850.0, 900.0, 850.0] * 20
        hr = [60.0] * 60
        result = score_recovery(rr, hr, actual_sleep_min=600.0, sleep_need_min=450.0)
        # Sleep perf > 1, but sleep component capped at 100
        assert result.sleep_performance > 1.0
        assert result.breakdown["sleep_component"] == 100.0

    def test_baseline_hrv_trend(self):
        rr = [800.0, 850.0, 900.0, 850.0] * 20
        hr = [60.0] * 60
        # With a low baseline, current HRV is above → positive trend
        result1 = score_recovery(rr, hr, 450.0, baseline_hrv_score=20.0)
        result2 = score_recovery(rr, hr, 450.0, baseline_hrv_score=None)
        # Trend should boost score slightly
        assert result1.score >= result2.score - 1.0  # within margin

    def test_result_repr(self):
        result = RecoveryResult(
            score=75.0, hrv_ms=50.0, hrv_score=60.1,
            resting_hr=58.0, sleep_performance=0.95,
            breakdown={},
        )
        s = repr(result)
        assert "75" in s
        assert "50.0" in s

    def test_breakdown_keys(self):
        rr = [800.0, 850.0] * 20
        hr = [60.0] * 30
        result = score_recovery(rr, hr, 400.0)
        assert "hrv_component" in result.breakdown
        assert "rhr_component" in result.breakdown
        assert "sleep_component" in result.breakdown
        assert "trend_adjustment" in result.breakdown
