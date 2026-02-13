"""SpO2 estimation from red/IR ratios with signal quality filtering.

Uses the standard Beer-Lambert calibration curve and adds quality
filtering to discard unreliable readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Core estimation
# ---------------------------------------------------------------------------


def estimate_spo2_from_ratio(r: float) -> float:
    """Estimate SpO2% from the red/IR AC-DC ratio.

    Uses the standard empirical calibration curve:
        SpO2 = 110 - 25 * R

    where R = (AC_red / DC_red) / (AC_ir / DC_ir).

    The result is clamped to [0, 100].
    """
    spo2 = 110.0 - 25.0 * r
    return round(max(0.0, min(100.0, spo2)), 1)


# ---------------------------------------------------------------------------
# Signal quality filtering
# ---------------------------------------------------------------------------


# Plausible range for the R ratio in a healthy human
R_MIN = 0.3
R_MAX = 1.2

# Minimum DC value (arbitrary units) to trust the reading — low DC means
# poor skin contact or the LED didn't reach the photodiode
DC_MIN = 50


def is_quality_reading(
    r: float,
    dc_red: float | None = None,
    dc_ir: float | None = None,
) -> bool:
    """Return True if the R ratio / DC levels indicate a trustworthy reading."""
    if not (R_MIN <= r <= R_MAX):
        return False
    if dc_red is not None and dc_red < DC_MIN:
        return False
    if dc_ir is not None and dc_ir < DC_MIN:
        return False
    return True


# ---------------------------------------------------------------------------
# Nightly / session aggregation
# ---------------------------------------------------------------------------


@dataclass
class SpO2Result:
    """Aggregated SpO2 statistics for a sleep session or time window."""

    median_pct: float
    min_pct: float
    readings: list[float]  # individual SpO2 percentages that passed QC
    quality_score: float  # fraction of input readings that passed QC
    time_below_90: float = 0.0  # fraction of readings below 90%

    def __repr__(self) -> str:
        return (
            f"SpO2Result(median={self.median_pct:.1f}%, "
            f"min={self.min_pct:.1f}%, "
            f"n={len(self.readings)}, "
            f"quality={self.quality_score:.0%})"
        )


def analyze_spo2_session(
    ratios: list[float],
    dc_red_values: list[float | None] | None = None,
    dc_ir_values: list[float | None] | None = None,
) -> SpO2Result:
    """Analyze a batch of red/IR ratio readings.

    Args:
        ratios: Raw R values from the SpO2 sensor.
        dc_red_values: Optional per-reading red DC levels for QC.
        dc_ir_values: Optional per-reading IR DC levels for QC.

    Returns:
        SpO2Result with aggregated statistics.
    """
    if not ratios:
        return SpO2Result(
            median_pct=0.0,
            min_pct=0.0,
            readings=[],
            quality_score=0.0,
        )

    n_total = len(ratios)
    dc_reds = dc_red_values or [None] * n_total
    dc_irs = dc_ir_values or [None] * n_total

    good_spo2: list[float] = []
    for r, dc_r, dc_i in zip(ratios, dc_reds, dc_irs):
        if is_quality_reading(r, dc_r, dc_i):
            good_spo2.append(estimate_spo2_from_ratio(r))

    if not good_spo2:
        return SpO2Result(
            median_pct=0.0,
            min_pct=0.0,
            readings=[],
            quality_score=0.0,
        )

    arr = np.asarray(good_spo2, dtype=np.float64)
    below_90 = float(np.sum(arr < 90.0) / len(arr))

    return SpO2Result(
        median_pct=round(float(np.median(arr)), 1),
        min_pct=round(float(np.min(arr)), 1),
        readings=good_spo2,
        quality_score=round(len(good_spo2) / n_total, 3),
        time_below_90=round(below_90, 3),
    )
