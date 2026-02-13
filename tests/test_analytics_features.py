"""Tests for poohw.analytics.features -- epoch windowing, HR/accel features, HRV."""

import math

import numpy as np
import pytest

from poohw.analytics.features import (
    compute_rmssd,
    lnrmssd_score,
    sdnn,
    pnn50,
    epoch_windows,
    hr_features,
    accel_features,
    HRFeatures,
    AccelFeatures,
)


# ========================== HRV metrics ==========================


class TestComputeRMSSD:
    def test_returns_none_for_empty(self):
        assert compute_rmssd([]) is None

    def test_returns_none_for_single(self):
        assert compute_rmssd([800.0]) is None

    def test_two_intervals(self):
        # diff = 100, RMSSD = 100
        result = compute_rmssd([800.0, 900.0])
        assert result == 100.0

    def test_constant_intervals(self):
        # All diffs = 0 → RMSSD = 0
        result = compute_rmssd([800.0, 800.0, 800.0, 800.0])
        assert result == 0.0

    def test_known_values(self):
        # diffs: 10, -20, 30 → squares: 100, 400, 900 → mean=466.67 → sqrt≈21.6
        result = compute_rmssd([800.0, 810.0, 790.0, 820.0])
        assert result is not None
        assert abs(result - 21.60) < 0.1

    def test_numpy_compatible(self):
        result = compute_rmssd(np.array([800.0, 810.0, 790.0, 820.0]))
        assert result is not None

    def test_negative_diffs(self):
        result = compute_rmssd([900.0, 800.0])
        assert result == 100.0


class TestLnRMSSDScore:
    def test_zero(self):
        assert lnrmssd_score(0.0) == 0.0

    def test_negative(self):
        assert lnrmssd_score(-5.0) == 0.0

    def test_known_value(self):
        # ln(50) / 6.5 * 100 ≈ 60.1
        score = lnrmssd_score(50.0)
        expected = math.log(50.0) / 6.5 * 100.0
        assert abs(score - round(expected, 1)) < 0.1

    def test_high_rmssd(self):
        # ln(100) / 6.5 * 100 ≈ 70.8
        score = lnrmssd_score(100.0)
        assert 70.0 < score < 72.0


class TestSDNN:
    def test_returns_none_for_single(self):
        assert sdnn([800.0]) is None

    def test_returns_none_for_empty(self):
        assert sdnn([]) is None

    def test_constant(self):
        assert sdnn([800.0, 800.0, 800.0]) == 0.0

    def test_known_values(self):
        result = sdnn([800.0, 820.0, 780.0, 810.0])
        assert result is not None
        assert result > 0


class TestPNN50:
    def test_returns_none_for_single(self):
        assert pnn50([800.0]) is None

    def test_all_below_50(self):
        # diffs: 10, 10, 10 → all < 50 → 0%
        result = pnn50([800.0, 810.0, 820.0, 830.0])
        assert result == 0.0

    def test_all_above_50(self):
        # diffs: 100, 100, 100 → all > 50 → 100%
        result = pnn50([800.0, 900.0, 1000.0, 1100.0])
        assert result == 100.0

    def test_mixed(self):
        # diffs: 10, 100 → 1/2 > 50 → 50%
        result = pnn50([800.0, 810.0, 910.0])
        assert result == 50.0


# ========================== Epoch windowing ==========================


class TestEpochWindows:
    def test_empty_input(self):
        assert epoch_windows([], []) == []

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            epoch_windows([1.0, 2.0], [1.0])

    def test_single_epoch(self):
        result = epoch_windows([0.0, 10.0, 20.0], [1, 2, 3], epoch_sec=30.0)
        assert len(result) == 1
        assert result[0][0] == 0.0
        assert result[0][1] == [1, 2, 3]

    def test_two_epochs(self):
        ts = [0.0, 10.0, 20.0, 35.0, 45.0]
        vals = ["a", "b", "c", "d", "e"]
        result = epoch_windows(ts, vals, epoch_sec=30.0)
        assert len(result) == 2
        assert result[0][1] == ["a", "b", "c"]
        assert result[1][1] == ["d", "e"]

    def test_gap_in_timestamps(self):
        ts = [0.0, 10.0, 100.0, 110.0]
        vals = [1, 2, 3, 4]
        result = epoch_windows(ts, vals, epoch_sec=30.0)
        # Should have 2 non-empty epochs (0-30 and 90-120)
        assert len(result) == 2
        assert result[0][1] == [1, 2]
        assert result[1][1] == [3, 4]

    def test_epoch_boundaries(self):
        # Value at exactly epoch boundary goes to the next epoch
        ts = [0.0, 30.0]
        vals = [1, 2]
        result = epoch_windows(ts, vals, epoch_sec=30.0)
        assert len(result) == 2
        assert result[0][1] == [1]
        assert result[1][1] == [2]


# ========================== HR features ==========================


class TestHRFeatures:
    def test_empty(self):
        f = hr_features([])
        assert f.mean_hr == 0.0
        assert f.std_hr == 0.0

    def test_single_value(self):
        f = hr_features([72.0])
        assert f.mean_hr == 72.0
        assert f.min_hr == 72.0
        assert f.max_hr == 72.0
        assert f.std_hr == 0.0

    def test_basic_stats(self):
        f = hr_features([60.0, 70.0, 80.0])
        assert f.mean_hr == 70.0
        assert f.min_hr == 60.0
        assert f.max_hr == 80.0
        assert f.std_hr > 0

    def test_with_rr_intervals(self):
        f = hr_features([70.0, 72.0], rr_intervals=[800.0, 850.0, 900.0])
        assert f.rmssd is not None
        assert f.sdnn_val is not None
        assert f.pnn50_val is not None

    def test_rr_too_short(self):
        f = hr_features([70.0], rr_intervals=[800.0])
        assert f.rmssd is None
        assert f.sdnn_val is None
        assert f.pnn50_val is None


# ========================== Accel features ==========================


class TestAccelFeatures:
    def test_empty(self):
        f = accel_features([])
        assert f.mean_magnitude == 0.0
        assert f.activity_counts == 0.0

    def test_single_sample(self):
        f = accel_features([(0.0, 0.0, 1.0)])
        assert abs(f.mean_magnitude - 1.0) < 0.001
        assert f.std_magnitude == 0.0
        assert f.zero_crossing_rate == 0.0
        assert f.activity_counts == 0.0

    def test_stationary(self):
        # Same sample repeated → no variation
        samples = [(0.0, 0.0, 1.0)] * 10
        f = accel_features(samples)
        assert f.std_magnitude == 0.0
        assert f.activity_counts == 0.0

    def test_movement(self):
        # Alternating between two states → activity
        samples = [(0.0, 0.0, 1.0), (0.5, 0.5, 1.5)] * 5
        f = accel_features(samples)
        assert f.std_magnitude > 0
        assert f.activity_counts > 0
        assert f.zero_crossing_rate > 0

    def test_threshold(self):
        # Very small movements below threshold
        samples = [(0.0, 0.0, 1.0), (0.0, 0.0, 1.001)] * 5
        f = accel_features(samples, threshold=0.01)
        # Activity counts should be 0 (delta < threshold)
        assert f.activity_counts == 0.0


# ========================== Backward compat ==========================


class TestBackwardCompat:
    """Ensure the old import paths still work."""

    def test_historical_compute_rmssd(self):
        from poohw.decoders.historical import compute_rmssd as old_rmssd
        assert old_rmssd([800.0, 900.0]) == 100.0

    def test_historical_lnrmssd_score(self):
        from poohw.decoders.historical import lnrmssd_score as old_score
        assert old_score(50.0) > 0

    def test_historical_estimate_spo2(self):
        from poohw.decoders.historical import estimate_spo2_from_ratio as old_spo2
        assert 90 < old_spo2(0.5) < 100
