"""Recovery score computation (HRV-driven).

Recovery is primarily determined by heart rate variability during sleep,
with adjustments for resting heart rate and sleep performance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from poohw.analytics.features import compute_rmssd, lnrmssd_score


@dataclass
class RecoveryResult:
    """Recovery score and its components."""

    score: float  # 0-100 composite recovery score
    hrv_ms: float  # RMSSD in ms
    hrv_score: float  # ln(RMSSD) / 6.5 * 100
    resting_hr: float  # lowest 5-min rolling avg during sleep
    sleep_performance: float  # actual_sleep / sleep_need (0-1+)
    breakdown: dict  # individual component scores

    def __repr__(self) -> str:
        return (
            f"RecoveryResult(score={self.score:.0f}, "
            f"hrv={self.hrv_ms:.1f}ms, "
            f"rhr={self.resting_hr:.0f}bpm, "
            f"sleep_perf={self.sleep_performance:.0%})"
        )


# ---------------------------------------------------------------------------
# Resting HR estimation
# ---------------------------------------------------------------------------


def _resting_hr(
    hr_values: list[float],
    window_min: int = 5,
) -> float:
    """Compute resting HR as the lowest N-minute rolling average.

    Args:
        hr_values: Per-minute HR samples during sleep.
        window_min: Rolling window in minutes.

    Returns:
        Lowest rolling average, or the overall mean if series is too short.
    """
    if len(hr_values) == 0:
        return 0.0
    arr = np.asarray(hr_values, dtype=np.float64)
    if len(arr) < window_min:
        return round(float(np.mean(arr)), 1)

    # Simple rolling mean
    cumsum = np.cumsum(arr)
    cumsum = np.insert(cumsum, 0, 0)
    rolling = (cumsum[window_min:] - cumsum[:-window_min]) / window_min
    return round(float(np.min(rolling)), 1)


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

# Weights for the composite recovery score
W_HRV = 0.50
W_RHR = 0.25
W_SLEEP = 0.25

# Reference ranges for normalization
HRV_SCORE_MAX = 100.0
RHR_IDEAL = 50.0  # bpm — lower is better
RHR_WORST = 90.0  # bpm


def score_recovery(
    rr_intervals_sleep: list[float],
    hr_during_sleep: list[float],
    actual_sleep_min: float,
    sleep_need_min: float = 450.0,
    baseline_hrv_score: float | None = None,
) -> RecoveryResult:
    """Compute a Whoop-style recovery score.

    Args:
        rr_intervals_sleep: All RR intervals (ms) collected during sleep.
        hr_during_sleep: Per-minute HR values during sleep.
        actual_sleep_min: Total minutes of detected sleep.
        sleep_need_min: Target sleep in minutes (default 7.5 h).
        baseline_hrv_score: 14-day baseline HRV score (optional; used for
            trend adjustment).

    Returns:
        RecoveryResult with the composite score and components.
    """
    # --- HRV ---
    rmssd = compute_rmssd(rr_intervals_sleep) or 0.0
    hrv_s = lnrmssd_score(rmssd) if rmssd > 0 else 0.0

    # Normalize HRV component to 0-100
    hrv_component = min(hrv_s / HRV_SCORE_MAX * 100.0, 100.0)

    # --- Resting HR ---
    rhr = _resting_hr(hr_during_sleep)
    # Lower RHR = better; map [RHR_IDEAL, RHR_WORST] → [100, 0]
    if rhr > 0:
        rhr_component = max(
            0.0,
            min(100.0, (RHR_WORST - rhr) / (RHR_WORST - RHR_IDEAL) * 100.0),
        )
    else:
        rhr_component = 50.0  # neutral if no data

    # --- Sleep performance ---
    sleep_perf = actual_sleep_min / sleep_need_min if sleep_need_min > 0 else 0.0
    sleep_component = min(sleep_perf * 100.0, 100.0)

    # --- Trend adjustment ---
    trend_adj = 0.0
    if baseline_hrv_score is not None and baseline_hrv_score > 0:
        delta = hrv_s - baseline_hrv_score
        trend_adj = max(-10.0, min(10.0, delta * 0.2))

    # --- Composite ---
    raw_score = (
        W_HRV * hrv_component
        + W_RHR * rhr_component
        + W_SLEEP * sleep_component
        + trend_adj
    )
    composite = max(0.0, min(100.0, raw_score))

    return RecoveryResult(
        score=round(composite, 1),
        hrv_ms=rmssd,
        hrv_score=hrv_s,
        resting_hr=rhr,
        sleep_performance=round(sleep_perf, 3),
        breakdown={
            "hrv_component": round(hrv_component, 1),
            "rhr_component": round(rhr_component, 1),
            "sleep_component": round(sleep_component, 1),
            "trend_adjustment": round(trend_adj, 1),
        },
    )
