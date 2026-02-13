"""Sleep/wake detection using the Cole-Kripke algorithm.

The Cole-Kripke algorithm (Sleep, 1992) is a validated actigraphy-based
sleep scoring method.  It classifies 1-minute epochs as sleep or wake
based on weighted activity counts from a sliding window of epochs.

After initial scoring, Webster's rescoring rules clean up isolated
wake/sleep bouts that are physiologically unlikely.

An optional HR cross-reference flags epochs where the accelerometer says
"sleep" but heart rate is elevated above the daytime mean, which may
indicate quiet wakefulness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np


class SleepStage(str, Enum):
    """Coarse sleep stage label."""

    WAKE = "wake"
    SLEEP = "sleep"


@dataclass
class SleepEpoch:
    """A single 1-minute epoch with a sleep/wake label."""

    timestamp: float  # epoch start time (seconds)
    stage: SleepStage
    activity_count: float
    hr_bpm: float | None = None
    flagged: bool = False  # True if HR cross-ref suggests misclassification


@dataclass
class SleepResult:
    """Complete sleep analysis result."""

    epochs: list[SleepEpoch]
    sleep_onset: float | None = None  # timestamp of first sustained sleep
    wake_time: float | None = None  # timestamp of final awakening
    total_sleep_min: float = 0.0
    total_wake_min: float = 0.0
    sleep_efficiency: float = 0.0  # total_sleep / time_in_bed (0-1)

    def __repr__(self) -> str:
        return (
            f"SleepResult(sleep={self.total_sleep_min:.0f}min, "
            f"wake={self.total_wake_min:.0f}min, "
            f"eff={self.sleep_efficiency:.0%}, "
            f"epochs={len(self.epochs)})"
        )


# ---------------------------------------------------------------------------
# Cole-Kripke coefficients
# ---------------------------------------------------------------------------

# Weights for epochs [t-4, t-3, t-2, t-1, t, t+1, t+2]
CK_WEIGHTS = [404, 598, 326, 441, 1408, 508, 350]
CK_SCALE = 0.00001
CK_THRESHOLD = 1.0  # D < threshold → sleep


def _cole_kripke_score(activity_counts: np.ndarray) -> np.ndarray:
    """Apply the Cole-Kripke formula to a 1-min activity count series.

    Returns an array of 0 (sleep) / 1 (wake) per epoch.
    """
    n = len(activity_counts)
    stages = np.ones(n, dtype=np.int8)  # default: wake

    for t in range(n):
        # Gather window values, padding with 0 for out-of-bounds
        window_indices = range(t - 4, t + 3)  # t-4 .. t+2  (7 values)
        vals = []
        for idx in window_indices:
            if 0 <= idx < n:
                vals.append(activity_counts[idx])
            else:
                vals.append(0.0)

        d = CK_SCALE * sum(w * v for w, v in zip(CK_WEIGHTS, vals))
        if d < CK_THRESHOLD:
            stages[t] = 0  # sleep

    return stages


# ---------------------------------------------------------------------------
# Webster rescoring rules
# ---------------------------------------------------------------------------


def _webster_rescore(stages: np.ndarray, min_wake_bout: int = 3) -> np.ndarray:
    """Apply Webster's rescoring rules to clean up isolated bouts.

    Rule A: After >= 4 minutes scored as wake, the next 1 min of sleep → wake.
    Rule B: After >= 10 minutes scored as sleep, the next 1–2 min of wake → sleep.
    Rule C: After >= 15 minutes scored as wake, the next 1–3 min of sleep → wake.

    Simplified here: any wake bout of fewer than *min_wake_bout* minutes that is
    surrounded by sleep is rescored as sleep.
    """
    result = stages.copy()
    n = len(result)

    # Rescore short wake bouts surrounded by sleep
    i = 0
    while i < n:
        if result[i] == 1:  # wake
            bout_start = i
            while i < n and result[i] == 1:
                i += 1
            bout_len = i - bout_start
            if bout_len < min_wake_bout:
                # Check if surrounded by sleep
                before_sleep = bout_start == 0 or result[bout_start - 1] == 0
                after_sleep = i >= n or result[i] == 0
                if before_sleep and after_sleep:
                    result[bout_start:i] = 0
        else:
            i += 1

    return result


# ---------------------------------------------------------------------------
# HR cross-reference
# ---------------------------------------------------------------------------


def _hr_flag_epochs(
    epochs: list[SleepEpoch],
    daytime_mean_hr: float | None,
    threshold_factor: float = 0.9,
) -> None:
    """Flag sleep epochs where HR exceeds a threshold (in-place).

    If daytime mean HR is available, epochs scored as sleep but with HR above
    ``threshold_factor * daytime_mean_hr`` are flagged as potentially
    misclassified.
    """
    if daytime_mean_hr is None or daytime_mean_hr <= 0:
        return

    threshold = threshold_factor * daytime_mean_hr
    for ep in epochs:
        if ep.stage == SleepStage.SLEEP and ep.hr_bpm is not None:
            if ep.hr_bpm > threshold:
                ep.flagged = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_sleep(
    timestamps: Sequence[float],
    activity_counts: Sequence[float],
    hr_values: Sequence[float | None] | None = None,
    daytime_mean_hr: float | None = None,
    epoch_sec: float = 60.0,
) -> SleepResult:
    """Score a night of sleep from 1-minute activity counts.

    Args:
        timestamps: Epoch start times in seconds (one per minute-epoch).
        activity_counts: Actigraphy activity counts per epoch.
        hr_values: Optional HR (bpm) per epoch for cross-referencing.
        daytime_mean_hr: Optional mean daytime HR for flag threshold.
        epoch_sec: Epoch duration in seconds (default 60).

    Returns:
        SleepResult with per-epoch stages and summary statistics.
    """
    if len(timestamps) == 0:
        return SleepResult(epochs=[])

    counts = np.asarray(activity_counts, dtype=np.float64)
    n = len(counts)

    # 1) Cole-Kripke scoring
    raw_stages = _cole_kripke_score(counts)

    # 2) Webster rescoring
    stages = _webster_rescore(raw_stages)

    # 3) Build epoch list
    hrs = hr_values if hr_values is not None else [None] * n
    epochs: list[SleepEpoch] = []
    for i in range(n):
        epochs.append(SleepEpoch(
            timestamp=float(timestamps[i]),
            stage=SleepStage.SLEEP if stages[i] == 0 else SleepStage.WAKE,
            activity_count=float(counts[i]),
            hr_bpm=float(hrs[i]) if hrs[i] is not None else None,
        ))

    # 4) HR cross-reference
    _hr_flag_epochs(epochs, daytime_mean_hr)

    # 5) Summary stats
    sleep_epochs = sum(1 for e in epochs if e.stage == SleepStage.SLEEP)
    wake_epochs = sum(1 for e in epochs if e.stage == SleepStage.WAKE)
    total_sleep = sleep_epochs * (epoch_sec / 60.0)
    total_wake = wake_epochs * (epoch_sec / 60.0)

    # Sleep onset: first epoch of a sustained sleep bout (>= 5 min)
    sleep_onset = None
    for i in range(n):
        if stages[i] == 0:
            bout_len = 0
            for j in range(i, n):
                if stages[j] == 0:
                    bout_len += 1
                else:
                    break
            if bout_len >= 5:
                sleep_onset = float(timestamps[i])
                break

    # Wake time: last epoch of a sustained sleep bout
    wake_time = None
    for i in range(n - 1, -1, -1):
        if stages[i] == 0:
            wake_time = float(timestamps[i]) + epoch_sec
            break

    # Sleep efficiency
    time_in_bed = n * (epoch_sec / 60.0)
    efficiency = total_sleep / time_in_bed if time_in_bed > 0 else 0.0

    return SleepResult(
        epochs=epochs,
        sleep_onset=sleep_onset,
        wake_time=wake_time,
        total_sleep_min=round(total_sleep, 1),
        total_wake_min=round(total_wake, 1),
        sleep_efficiency=round(efficiency, 3),
    )
