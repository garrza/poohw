"""Activity classification from accelerometer + heart rate data.

Classifies each epoch into one of four activity levels based on
accelerometer magnitude variation and heart rate zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np


class ActivityLevel(str, Enum):
    """Coarse activity classification."""

    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    VIGOROUS = "vigorous"


# Calorie estimates (kcal per minute) per activity level
# These are rough averages for a ~70 kg person
CALORIE_RATES = {
    ActivityLevel.SEDENTARY: 1.2,
    ActivityLevel.LIGHT: 3.0,
    ActivityLevel.MODERATE: 6.0,
    ActivityLevel.VIGOROUS: 10.0,
}


@dataclass
class ActivityEpoch:
    """A single epoch with activity classification."""

    timestamp: float
    level: ActivityLevel
    accel_std: float  # accelerometer magnitude std dev
    hr_pct: float | None  # HR as % of max, if available


@dataclass
class ActivityResult:
    """Activity analysis for a time window."""

    epochs: list[ActivityEpoch]
    classification: dict[str, float]  # level → total minutes
    duration_min: float
    calories: float

    def __repr__(self) -> str:
        dominant = max(self.classification, key=self.classification.get) if self.classification else "none"
        return (
            f"ActivityResult({dominant}, "
            f"dur={self.duration_min:.0f}min, "
            f"cal≈{self.calories:.0f})"
        )


# ---------------------------------------------------------------------------
# Thresholds (in g for accel std, fraction for HR % of max)
# ---------------------------------------------------------------------------

ACCEL_LOW = 0.05  # below this → sedentary accel
ACCEL_MED = 0.20  # below this → light accel
ACCEL_HIGH = 0.50  # below this → moderate accel; above = vigorous

HR_LIGHT = 0.50
HR_MODERATE = 0.60
HR_VIGOROUS = 0.80


def _classify_epoch(
    accel_std: float,
    hr_pct: float | None,
) -> ActivityLevel:
    """Classify a single epoch using combined accel + HR heuristics."""
    # Start with accel-based guess
    if accel_std < ACCEL_LOW:
        accel_level = ActivityLevel.SEDENTARY
    elif accel_std < ACCEL_MED:
        accel_level = ActivityLevel.LIGHT
    elif accel_std < ACCEL_HIGH:
        accel_level = ActivityLevel.MODERATE
    else:
        accel_level = ActivityLevel.VIGOROUS

    if hr_pct is None:
        return accel_level

    # HR-based guess
    if hr_pct < HR_LIGHT:
        hr_level = ActivityLevel.SEDENTARY
    elif hr_pct < HR_MODERATE:
        hr_level = ActivityLevel.LIGHT
    elif hr_pct < HR_VIGOROUS:
        hr_level = ActivityLevel.MODERATE
    else:
        hr_level = ActivityLevel.VIGOROUS

    # Take the higher of the two
    order = [ActivityLevel.SEDENTARY, ActivityLevel.LIGHT,
             ActivityLevel.MODERATE, ActivityLevel.VIGOROUS]
    return max(accel_level, hr_level, key=lambda x: order.index(x))


def classify_activity(
    timestamps: Sequence[float],
    accel_stds: Sequence[float],
    hr_values: Sequence[float | None] | None = None,
    max_hr: float = 190.0,
    epoch_min: float = 1.0,
) -> ActivityResult:
    """Classify activity for a series of epochs.

    Args:
        timestamps: Epoch start times (seconds).
        accel_stds: Accelerometer magnitude standard deviation per epoch.
        hr_values: Optional HR (bpm) per epoch.
        max_hr: Max heart rate for zone calculation.
        epoch_min: Epoch duration in minutes.

    Returns:
        ActivityResult with per-epoch classifications and summary.
    """
    n = len(timestamps)
    if n == 0:
        return ActivityResult(
            epochs=[],
            classification={level.value: 0.0 for level in ActivityLevel},
            duration_min=0.0,
            calories=0.0,
        )

    hrs = hr_values if hr_values is not None else [None] * n

    epochs: list[ActivityEpoch] = []
    classification = {level.value: 0.0 for level in ActivityLevel}
    total_cal = 0.0

    for i in range(n):
        hr_pct = float(hrs[i]) / max_hr if hrs[i] is not None and max_hr > 0 else None
        level = _classify_epoch(float(accel_stds[i]), hr_pct)

        epochs.append(ActivityEpoch(
            timestamp=float(timestamps[i]),
            level=level,
            accel_std=float(accel_stds[i]),
            hr_pct=hr_pct,
        ))

        classification[level.value] += epoch_min
        total_cal += CALORIE_RATES[level] * epoch_min

    return ActivityResult(
        epochs=epochs,
        classification={k: round(v, 1) for k, v in classification.items()},
        duration_min=round(n * epoch_min, 1),
        calories=round(total_cal, 0),
    )
