"""Strain / training load scoring (HR-zone TRIMP variant).

Classifies each minute into heart rate zones and accumulates strain
using exponential zone weights, then maps the raw TRIMP value onto
Whoop's 0-21 scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# HR zones (% of max HR)
# ---------------------------------------------------------------------------

ZONE_BOUNDARIES = [0.50, 0.60, 0.70, 0.80, 0.90, 1.01]
ZONE_WEIGHTS = [0.5, 1.0, 2.0, 4.0, 8.0]  # zone 1-5
ZONE_LABELS = ["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"]

# Max raw TRIMP that maps to strain 21 (empirical; a very hard day
# might accumulate ~400 TRIMP-minutes worth)
TRIMP_MAX = 400.0

# Whoop strain ceiling
STRAIN_MAX = 21.0

# Calorie estimation constant: kcal ≈ gender_factor * (time_hr * HR_mean)
# Simplified — uses a unisex constant; real Whoop factors in weight/age/sex.
CALORIE_FACTOR = 0.05  # rough kcal per minute per bpm above rest


@dataclass
class StrainResult:
    """Strain score and breakdown."""

    score: float  # 0-21 Whoop-style
    raw_trimp: float  # raw TRIMP accumulation
    peak_hr: float
    avg_hr: float
    zone_minutes: dict[str, float]  # label → minutes in zone
    calories_estimate: float

    def __repr__(self) -> str:
        return (
            f"StrainResult(score={self.score:.1f}/21, "
            f"peak={self.peak_hr:.0f}bpm, "
            f"avg={self.avg_hr:.0f}bpm, "
            f"cal≈{self.calories_estimate:.0f})"
        )


def _classify_zone(hr_pct: float) -> int:
    """Return 0-based zone index (0 = below zone 1, 1..5 = zone 1..5)."""
    for i, upper in enumerate(ZONE_BOUNDARIES):
        if hr_pct < upper:
            return i
    return len(ZONE_BOUNDARIES) - 1


def score_strain(
    hr_values: Sequence[float],
    max_hr: float = 190.0,
    resting_hr: float = 60.0,
    epoch_min: float = 1.0,
) -> StrainResult:
    """Compute a strain score from a heart rate time series.

    Args:
        hr_values: Per-epoch HR values (bpm), typically 1-minute epochs.
        max_hr: User's estimated max HR (default 190, ~220-30 for age 30).
        resting_hr: Resting heart rate for calorie estimation.
        epoch_min: Duration of each epoch in minutes.

    Returns:
        StrainResult with the 0-21 score and zone breakdown.
    """
    if len(hr_values) == 0:
        return StrainResult(
            score=0.0,
            raw_trimp=0.0,
            peak_hr=0.0,
            avg_hr=0.0,
            zone_minutes={label: 0.0 for label in ZONE_LABELS},
            calories_estimate=0.0,
        )

    arr = np.asarray(hr_values, dtype=np.float64)
    peak = float(np.max(arr))
    avg = float(np.mean(arr))

    zone_mins = {label: 0.0 for label in ZONE_LABELS}
    trimp = 0.0

    for hr in arr:
        pct = hr / max_hr if max_hr > 0 else 0.0
        zone_idx = _classify_zone(pct)
        if 1 <= zone_idx <= 5:
            label = ZONE_LABELS[zone_idx - 1]
            zone_mins[label] += epoch_min
            trimp += epoch_min * ZONE_WEIGHTS[zone_idx - 1]
        # Below zone 1 contributes 0 strain

    # Map TRIMP to 0-21 using a log curve (diminishing returns at high strain)
    if trimp > 0:
        score = STRAIN_MAX * (1.0 - np.exp(-trimp / (TRIMP_MAX / 3.0)))
        score = min(STRAIN_MAX, float(score))
    else:
        score = 0.0

    # Calorie estimate
    duration_min = len(arr) * epoch_min
    cal = CALORIE_FACTOR * duration_min * max(avg - resting_hr, 0.0)

    return StrainResult(
        score=round(score, 1),
        raw_trimp=round(trimp, 2),
        peak_hr=round(peak, 1),
        avg_hr=round(avg, 1),
        zone_minutes={k: round(v, 1) for k, v in zone_mins.items()},
        calories_estimate=round(cal, 0),
    )
