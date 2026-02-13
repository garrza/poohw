"""Epoch windowing and feature extraction for Whoop sensor data.

This is the shared foundation for all analytics modules.  It provides:
  - Time-series windowing into fixed-duration epochs
  - Heart rate feature extraction (mean, std, min, max)
  - Accelerometer feature extraction (magnitude, activity counts)
  - HRV metrics (RMSSD, SDNN, pNN50, ln-RMSSD score)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# HRV metrics
# ---------------------------------------------------------------------------


def compute_rmssd(rr_intervals: Sequence[float]) -> float | None:
    """Root mean square of successive RR-interval differences (ms).

    Returns None if fewer than 2 intervals are provided.
    """
    if len(rr_intervals) < 2:
        return None
    arr = np.asarray(rr_intervals, dtype=np.float64)
    diffs = np.diff(arr)
    return round(float(np.sqrt(np.mean(diffs ** 2))), 2)


def lnrmssd_score(rmssd_ms: float) -> float:
    """HRV score: ln(RMSSD) / 6.5 * 100.

    Maps the natural log of RMSSD into a 0-100-ish scale used by consumer
    wearables (Whoop, Oura, etc.).
    """
    if rmssd_ms <= 0:
        return 0.0
    return round(math.log(rmssd_ms) / 6.5 * 100.0, 1)


def sdnn(rr_intervals: Sequence[float]) -> float | None:
    """Standard deviation of NN (RR) intervals (ms).

    Returns None if fewer than 2 intervals.
    """
    if len(rr_intervals) < 2:
        return None
    arr = np.asarray(rr_intervals, dtype=np.float64)
    return round(float(np.std(arr, ddof=1)), 2)


def pnn50(rr_intervals: Sequence[float]) -> float | None:
    """Percentage of successive RR differences > 50 ms.

    Returns None if fewer than 2 intervals.
    """
    if len(rr_intervals) < 2:
        return None
    arr = np.asarray(rr_intervals, dtype=np.float64)
    diffs = np.abs(np.diff(arr))
    return round(float(np.sum(diffs > 50.0) / len(diffs) * 100.0), 1)


# ---------------------------------------------------------------------------
# Epoch windowing
# ---------------------------------------------------------------------------


def epoch_windows(
    timestamps: Sequence[float],
    values: Sequence,
    epoch_sec: float = 30.0,
) -> list[tuple[float, list]]:
    """Slice a time-series into fixed-width epochs.

    Args:
        timestamps: Monotonically increasing timestamps (seconds).
        values: Corresponding values (same length as *timestamps*).
        epoch_sec: Duration of each epoch window in seconds.

    Returns:
        List of ``(epoch_start_time, [values_in_epoch])`` tuples.
        Epochs with no values are omitted.
    """
    if len(timestamps) == 0:
        return []
    if len(timestamps) != len(values):
        raise ValueError("timestamps and values must have the same length")

    ts = np.asarray(timestamps, dtype=np.float64)
    t_start = ts[0]
    t_end = ts[-1]

    epochs: list[tuple[float, list]] = []
    window_start = t_start

    while window_start <= t_end:
        window_end = window_start + epoch_sec
        mask = (ts >= window_start) & (ts < window_end)
        indices = np.where(mask)[0]
        if len(indices) > 0:
            epoch_values = [values[int(i)] for i in indices]
            epochs.append((float(window_start), epoch_values))
        window_start = window_end

    return epochs


# ---------------------------------------------------------------------------
# Heart rate features (per-epoch)
# ---------------------------------------------------------------------------


@dataclass
class HRFeatures:
    """Aggregated heart rate features for an epoch."""

    mean_hr: float
    std_hr: float
    min_hr: float
    max_hr: float
    rmssd: float | None = None
    sdnn_val: float | None = None
    pnn50_val: float | None = None


def hr_features(
    hr_values: Sequence[float],
    rr_intervals: Sequence[float] | None = None,
) -> HRFeatures:
    """Compute HR features for a single epoch.

    Args:
        hr_values: Heart rate samples (bpm).
        rr_intervals: Optional RR intervals (ms) for HRV metrics.
    """
    arr = np.asarray(hr_values, dtype=np.float64)
    if len(arr) == 0:
        return HRFeatures(mean_hr=0.0, std_hr=0.0, min_hr=0.0, max_hr=0.0)

    result = HRFeatures(
        mean_hr=round(float(np.mean(arr)), 1),
        std_hr=round(float(np.std(arr, ddof=0)), 1) if len(arr) > 1 else 0.0,
        min_hr=float(np.min(arr)),
        max_hr=float(np.max(arr)),
    )

    if rr_intervals is not None and len(rr_intervals) >= 2:
        result.rmssd = compute_rmssd(rr_intervals)
        result.sdnn_val = sdnn(rr_intervals)
        result.pnn50_val = pnn50(rr_intervals)

    return result


# ---------------------------------------------------------------------------
# Accelerometer features (per-epoch)
# ---------------------------------------------------------------------------


@dataclass
class AccelFeatures:
    """Aggregated accelerometer features for an epoch."""

    mean_magnitude: float
    std_magnitude: float
    zero_crossing_rate: float  # fraction of samples that cross the mean
    activity_counts: float  # sum of |delta-magnitude| above threshold


def accel_features(
    samples: Sequence[tuple[float, float, float]],
    threshold: float = 0.05,
) -> AccelFeatures:
    """Compute accelerometer features for a single epoch.

    Args:
        samples: List of (x, y, z) tuples in g.
        threshold: Minimum |delta-magnitude| to count as activity.
    """
    if len(samples) == 0:
        return AccelFeatures(
            mean_magnitude=0.0,
            std_magnitude=0.0,
            zero_crossing_rate=0.0,
            activity_counts=0.0,
        )

    arr = np.asarray(samples, dtype=np.float64)  # shape (N, 3)
    magnitudes = np.sqrt(np.sum(arr ** 2, axis=1))

    mean_mag = float(np.mean(magnitudes))
    std_mag = float(np.std(magnitudes, ddof=0)) if len(magnitudes) > 1 else 0.0

    # Zero-crossing rate: how often magnitude crosses the mean
    centered = magnitudes - mean_mag
    if len(centered) > 1:
        sign_changes = np.sum(np.diff(np.sign(centered)) != 0)
        zcr = float(sign_changes) / (len(centered) - 1)
    else:
        zcr = 0.0

    # Activity counts: sum of |delta-magnitude| above threshold
    if len(magnitudes) > 1:
        delta_mag = np.abs(np.diff(magnitudes))
        counts = float(np.sum(delta_mag[delta_mag > threshold]))
    else:
        counts = 0.0

    return AccelFeatures(
        mean_magnitude=round(mean_mag, 4),
        std_magnitude=round(std_mag, 4),
        zero_crossing_rate=round(zcr, 4),
        activity_counts=round(counts, 4),
    )
