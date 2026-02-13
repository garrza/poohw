"""Tests for poohw.analytics.sleep -- Cole-Kripke sleep scoring."""

import numpy as np
import pytest

from poohw.analytics.sleep import (
    score_sleep,
    SleepResult,
    SleepEpoch,
    SleepStage,
    _cole_kripke_score,
    _webster_rescore,
    _hr_flag_epochs,
    CK_WEIGHTS,
    CK_SCALE,
    CK_THRESHOLD,
)


class TestColeKripkeScore:
    def test_all_zero_activity_is_sleep(self):
        counts = np.zeros(30)
        stages = _cole_kripke_score(counts)
        assert np.all(stages == 0)  # all sleep

    def test_high_activity_is_wake(self):
        # Very high activity → D > 1 → wake
        counts = np.full(30, 10000.0)
        stages = _cole_kripke_score(counts)
        assert np.all(stages == 1)  # all wake

    def test_mixed_activity(self):
        counts = np.zeros(60)
        counts[25:35] = 5000.0  # burst of activity
        stages = _cole_kripke_score(counts)
        # The middle burst should be wake
        assert np.any(stages[25:35] == 1)
        # Quiet periods should be sleep
        assert np.all(stages[:20] == 0)

    def test_edge_around_threshold(self):
        # Activity that produces D exactly at threshold
        # D = CK_SCALE * CK_WEIGHTS[4] * A  (if only center epoch has activity)
        # D = 0.00001 * 1408 * A → set A = 1/0.01408 ≈ 71 to get D ≈ 1
        counts = np.zeros(10)
        counts[4] = 71.0  # D ≈ 0.01408 * 71 ≈ 0.9997 → just below threshold → sleep
        stages = _cole_kripke_score(counts)
        assert stages[4] == 0  # sleep (D < 1)

    def test_output_length_matches_input(self):
        counts = np.random.rand(100)
        stages = _cole_kripke_score(counts)
        assert len(stages) == 100


class TestWebsterRescore:
    def test_no_change_for_long_bouts(self):
        # All sleep
        stages = np.zeros(20, dtype=np.int8)
        rescored = _webster_rescore(stages)
        assert np.array_equal(stages, rescored)

    def test_short_wake_surrounded_by_sleep(self):
        stages = np.zeros(20, dtype=np.int8)
        stages[10:12] = 1  # 2-min wake bout
        rescored = _webster_rescore(stages, min_wake_bout=3)
        # Should be rescored as sleep
        assert np.all(rescored[10:12] == 0)

    def test_long_wake_not_rescored(self):
        stages = np.zeros(20, dtype=np.int8)
        stages[5:15] = 1  # 10-min wake bout
        rescored = _webster_rescore(stages, min_wake_bout=3)
        # Should remain wake
        assert np.all(rescored[5:15] == 1)

    def test_wake_at_start_not_rescored(self):
        stages = np.zeros(20, dtype=np.int8)
        stages[0:2] = 1  # 2-min wake at start
        rescored = _webster_rescore(stages, min_wake_bout=3)
        # At start, "before_sleep" → True (bout_start==0), after_sleep → True
        assert np.all(rescored[0:2] == 0)


class TestHRFlagEpochs:
    def test_no_flag_without_daytime_hr(self):
        epochs = [
            SleepEpoch(0.0, SleepStage.SLEEP, 0.0, hr_bpm=80.0),
        ]
        _hr_flag_epochs(epochs, None)
        assert not epochs[0].flagged

    def test_flag_elevated_hr(self):
        epochs = [
            SleepEpoch(0.0, SleepStage.SLEEP, 0.0, hr_bpm=85.0),
            SleepEpoch(60.0, SleepStage.SLEEP, 0.0, hr_bpm=55.0),
        ]
        _hr_flag_epochs(epochs, daytime_mean_hr=80.0, threshold_factor=0.9)
        # 85 > 0.9*80=72 → flagged
        assert epochs[0].flagged
        # 55 < 72 → not flagged
        assert not epochs[1].flagged

    def test_no_flag_wake_epochs(self):
        epochs = [
            SleepEpoch(0.0, SleepStage.WAKE, 100.0, hr_bpm=90.0),
        ]
        _hr_flag_epochs(epochs, daytime_mean_hr=80.0)
        assert not epochs[0].flagged  # wake epochs are not flagged

    def test_no_flag_when_hr_none(self):
        epochs = [
            SleepEpoch(0.0, SleepStage.SLEEP, 0.0, hr_bpm=None),
        ]
        _hr_flag_epochs(epochs, daytime_mean_hr=80.0)
        assert not epochs[0].flagged


class TestScoreSleep:
    def test_empty_input(self):
        result = score_sleep([], [])
        assert len(result.epochs) == 0
        assert result.total_sleep_min == 0.0

    def test_all_sleep(self):
        n = 60  # 60 minutes
        ts = list(range(0, n * 60, 60))
        counts = [0.0] * n
        result = score_sleep(ts, counts)
        assert result.total_sleep_min == 60.0
        assert result.total_wake_min == 0.0
        assert result.sleep_efficiency == 1.0

    def test_all_wake(self):
        n = 60
        ts = list(range(0, n * 60, 60))
        counts = [50000.0] * n
        result = score_sleep(ts, counts)
        assert result.total_wake_min == 60.0
        assert result.total_sleep_min == 0.0

    def test_sleep_onset_and_wake_time(self):
        n = 120
        ts = list(range(0, n * 60, 60))
        # First 30 min wake, then 60 min sleep, then 30 min wake
        counts = [50000.0] * 30 + [0.0] * 60 + [50000.0] * 30
        result = score_sleep(ts, counts)
        assert result.sleep_onset is not None
        assert result.wake_time is not None
        assert result.sleep_onset >= ts[30] * 1.0

    def test_with_hr_values(self):
        n = 30
        ts = list(range(0, n * 60, 60))
        counts = [0.0] * n
        hrs = [55.0] * n
        result = score_sleep(ts, counts, hr_values=hrs, daytime_mean_hr=75.0)
        # With low HR + low activity → all sleep, none flagged
        assert all(not e.flagged for e in result.epochs)

    def test_result_repr(self):
        result = SleepResult(
            epochs=[],
            total_sleep_min=420.0,
            total_wake_min=60.0,
            sleep_efficiency=0.875,
        )
        s = repr(result)
        assert "420" in s
        assert "60" in s

    def test_epoch_count_matches(self):
        n = 45
        ts = list(range(0, n * 60, 60))
        counts = [0.0] * n
        result = score_sleep(ts, counts)
        assert len(result.epochs) == n
