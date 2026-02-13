"""Daily summary aggregator.

Pulls metrics from all analytics modules into a single DailySummary
that is JSON-serializable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

from poohw.analytics.sleep import SleepResult
from poohw.analytics.recovery import RecoveryResult
from poohw.analytics.strain import StrainResult
from poohw.analytics.spo2 import SpO2Result
from poohw.analytics.respiratory import RespiratoryResult
from poohw.analytics.activity import ActivityResult


@dataclass
class DailySummary:
    """A single day's health metrics report."""

    date: str  # ISO date string, e.g. "2026-02-13"

    # Sleep
    sleep_total_min: float = 0.0
    sleep_efficiency: float = 0.0
    sleep_onset: str | None = None  # ISO timestamp
    wake_time: str | None = None

    # Recovery
    recovery_score: float = 0.0
    hrv_rmssd_ms: float = 0.0
    hrv_score: float = 0.0
    resting_hr: float = 0.0

    # Strain
    strain_score: float = 0.0
    peak_hr: float = 0.0
    avg_hr: float = 0.0
    calories: float = 0.0

    # SpO2
    spo2_median: float = 0.0
    spo2_min: float = 0.0
    spo2_quality: float = 0.0
    spo2_time_below_90: float = 0.0

    # Respiratory
    respiratory_rate: float = 0.0
    respiratory_confidence: float = 0.0

    # Activity
    activity_minutes: dict[str, float] = field(default_factory=dict)

    # Skin temperature (optional)
    skin_temp_c: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict (JSON-friendly)."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def __repr__(self) -> str:
        return (
            f"DailySummary({self.date}: "
            f"sleep={self.sleep_total_min:.0f}min, "
            f"recovery={self.recovery_score:.0f}, "
            f"strain={self.strain_score:.1f}/21, "
            f"spo2={self.spo2_median:.0f}%)"
        )


def build_daily_summary(
    day: date | str,
    sleep: SleepResult | None = None,
    recovery: RecoveryResult | None = None,
    strain: StrainResult | None = None,
    spo2: SpO2Result | None = None,
    respiratory: RespiratoryResult | None = None,
    activity: ActivityResult | None = None,
    skin_temp_c: float | None = None,
) -> DailySummary:
    """Build a daily summary from individual analytics results.

    Args:
        day: The date for this summary.
        sleep: Sleep analysis result.
        recovery: Recovery score result.
        strain: Strain score result.
        spo2: SpO2 analysis result.
        respiratory: Respiratory rate result.
        activity: Activity classification result.
        skin_temp_c: Optional skin temperature reading (Celsius).

    Returns:
        A populated DailySummary.
    """
    date_str = day if isinstance(day, str) else day.isoformat()

    summary = DailySummary(date=date_str, skin_temp_c=skin_temp_c)

    if sleep is not None:
        summary.sleep_total_min = sleep.total_sleep_min
        summary.sleep_efficiency = sleep.sleep_efficiency
        # We store raw timestamps — caller can format if needed
        summary.sleep_onset = str(sleep.sleep_onset) if sleep.sleep_onset else None
        summary.wake_time = str(sleep.wake_time) if sleep.wake_time else None

    if recovery is not None:
        summary.recovery_score = recovery.score
        summary.hrv_rmssd_ms = recovery.hrv_ms
        summary.hrv_score = recovery.hrv_score
        summary.resting_hr = recovery.resting_hr

    if strain is not None:
        summary.strain_score = strain.score
        summary.peak_hr = strain.peak_hr
        summary.avg_hr = strain.avg_hr
        summary.calories = strain.calories_estimate

    if spo2 is not None:
        summary.spo2_median = spo2.median_pct
        summary.spo2_min = spo2.min_pct
        summary.spo2_quality = spo2.quality_score
        summary.spo2_time_below_90 = spo2.time_below_90

    if respiratory is not None:
        summary.respiratory_rate = respiratory.rate_bpm
        summary.respiratory_confidence = respiratory.confidence

    if activity is not None:
        summary.activity_minutes = activity.classification

    return summary
