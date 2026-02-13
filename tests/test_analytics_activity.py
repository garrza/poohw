"""Tests for poohw.analytics.activity -- activity classification."""

import pytest

from poohw.analytics.activity import (
    classify_activity,
    ActivityResult,
    ActivityLevel,
    ActivityEpoch,
    _classify_epoch,
    ACCEL_LOW,
    ACCEL_MED,
    ACCEL_HIGH,
    HR_LIGHT,
    HR_MODERATE,
    HR_VIGOROUS,
    CALORIE_RATES,
)


class TestClassifyEpoch:
    def test_sedentary_no_hr(self):
        assert _classify_epoch(0.01, None) == ActivityLevel.SEDENTARY

    def test_light_no_hr(self):
        assert _classify_epoch(0.10, None) == ActivityLevel.LIGHT

    def test_moderate_no_hr(self):
        assert _classify_epoch(0.30, None) == ActivityLevel.MODERATE

    def test_vigorous_no_hr(self):
        assert _classify_epoch(0.60, None) == ActivityLevel.VIGOROUS

    def test_hr_overrides_accel(self):
        # Low accel (sedentary) but high HR (vigorous) → vigorous
        result = _classify_epoch(0.01, 0.85)  # 85% max HR
        assert result == ActivityLevel.VIGOROUS

    def test_accel_overrides_hr(self):
        # High accel (vigorous) but low HR (sedentary) → vigorous
        result = _classify_epoch(0.60, 0.40)
        assert result == ActivityLevel.VIGOROUS

    def test_moderate_both(self):
        result = _classify_epoch(0.25, 0.65)
        assert result == ActivityLevel.MODERATE


class TestClassifyActivity:
    def test_empty(self):
        result = classify_activity([], [])
        assert result.duration_min == 0.0
        assert result.calories == 0.0
        assert len(result.epochs) == 0

    def test_all_sedentary(self):
        ts = list(range(0, 600, 60))
        stds = [0.01] * 10
        result = classify_activity(ts, stds)
        assert result.classification["sedentary"] == 10.0
        assert result.classification["vigorous"] == 0.0
        assert result.duration_min == 10.0

    def test_mixed_activity(self):
        ts = [0.0, 60.0, 120.0, 180.0]
        stds = [0.01, 0.10, 0.30, 0.60]
        result = classify_activity(ts, stds)
        assert result.classification["sedentary"] == 1.0
        assert result.classification["light"] == 1.0
        assert result.classification["moderate"] == 1.0
        assert result.classification["vigorous"] == 1.0

    def test_with_hr(self):
        ts = [0.0, 60.0]
        stds = [0.01, 0.01]  # both sedentary by accel
        hrs = [50.0, 170.0]  # first sedentary, second vigorous by HR
        result = classify_activity(ts, stds, hr_values=hrs, max_hr=190.0)
        assert result.epochs[0].level == ActivityLevel.SEDENTARY
        assert result.epochs[1].level == ActivityLevel.VIGOROUS

    def test_calories_increase_with_activity(self):
        ts = [0.0] * 60
        stds_sedentary = [0.01] * 60
        stds_vigorous = [0.60] * 60
        r1 = classify_activity(list(range(60)), stds_sedentary)
        r2 = classify_activity(list(range(60)), stds_vigorous)
        assert r2.calories > r1.calories

    def test_result_repr(self):
        result = ActivityResult(
            epochs=[],
            classification={"sedentary": 30.0, "light": 10.0,
                            "moderate": 15.0, "vigorous": 5.0},
            duration_min=60.0,
            calories=350.0,
        )
        s = repr(result)
        assert "sedentary" in s
        assert "60" in s

    def test_all_levels_in_classification(self):
        ts = [0.0]
        stds = [0.01]
        result = classify_activity(ts, stds)
        for level in ActivityLevel:
            assert level.value in result.classification
