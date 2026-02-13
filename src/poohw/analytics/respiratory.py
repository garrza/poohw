"""Respiratory rate estimation from RR intervals.

Respiratory sinus arrhythmia (RSA) causes the RR interval to modulate
at the breathing frequency (typically 0.15–0.4 Hz, i.e. 9–24 breaths/min).

Algorithm:
1. Interpolate the (irregularly sampled) RR interval series to a uniform
   sample rate.
2. Apply a bandpass filter to isolate the respiratory band.
3. Find the dominant frequency via FFT peak detection.
4. Convert Hz → breaths per minute.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sig


# Respiratory frequency band (Hz)
RESP_LO = 0.15  # 9 breaths/min
RESP_HI = 0.40  # 24 breaths/min

# Interpolation target sample rate
INTERP_FS = 4.0  # Hz


@dataclass
class RespiratoryResult:
    """Estimated respiratory rate and confidence."""

    rate_bpm: float  # breaths per minute
    confidence: float  # 0-1 quality indicator

    def __repr__(self) -> str:
        return (
            f"RespiratoryResult(rate={self.rate_bpm:.1f} breaths/min, "
            f"conf={self.confidence:.2f})"
        )


def _interpolate_rr(
    rr_intervals_ms: list[float],
    fs: float = INTERP_FS,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate RR intervals to a uniform sample rate.

    Args:
        rr_intervals_ms: Successive RR intervals in milliseconds.
        fs: Target sample rate in Hz.

    Returns:
        (time_uniform, rr_uniform) arrays.
    """
    # Build cumulative time axis from the RR intervals themselves
    rr_sec = np.asarray(rr_intervals_ms, dtype=np.float64) / 1000.0
    t_rr = np.cumsum(rr_sec)
    t_rr = np.insert(t_rr, 0, 0.0)  # start at t=0
    # The RR value at each timestamp is the *next* interval
    rr_vals = rr_sec  # length n
    t_vals = t_rr[:-1]  # also length n

    # Uniform time grid
    t_end = t_vals[-1]
    t_uniform = np.arange(0, t_end, 1.0 / fs)
    if len(t_uniform) < 4:
        return t_uniform, np.interp(t_uniform, t_vals, rr_vals)

    rr_uniform = np.interp(t_uniform, t_vals, rr_vals)
    return t_uniform, rr_uniform


def _bandpass_filter(
    data: np.ndarray,
    fs: float,
    lo: float = RESP_LO,
    hi: float = RESP_HI,
    order: int = 4,
) -> np.ndarray:
    """Apply a Butterworth bandpass filter."""
    nyq = fs / 2.0
    # Clamp to avoid invalid Wn values
    lo_n = max(lo / nyq, 0.001)
    hi_n = min(hi / nyq, 0.999)
    if lo_n >= hi_n:
        return data
    sos = sig.butter(order, [lo_n, hi_n], btype="band", output="sos")
    return sig.sosfiltfilt(sos, data)


def estimate_respiratory_rate(
    rr_intervals_ms: list[float],
) -> RespiratoryResult:
    """Estimate respiratory rate from RR intervals.

    Args:
        rr_intervals_ms: Successive RR intervals in milliseconds.

    Returns:
        RespiratoryResult with rate in breaths/min and a confidence score.
    """
    if len(rr_intervals_ms) < 10:
        return RespiratoryResult(rate_bpm=0.0, confidence=0.0)

    # 1) Interpolate
    t_uniform, rr_uniform = _interpolate_rr(rr_intervals_ms, INTERP_FS)
    if len(rr_uniform) < 16:
        return RespiratoryResult(rate_bpm=0.0, confidence=0.0)

    # 2) Remove DC / detrend
    rr_uniform = rr_uniform - np.mean(rr_uniform)

    # 3) Bandpass filter
    filtered = _bandpass_filter(rr_uniform, INTERP_FS)

    # 4) FFT
    n = len(filtered)
    freqs = np.fft.rfftfreq(n, d=1.0 / INTERP_FS)
    fft_mag = np.abs(np.fft.rfft(filtered))

    # 5) Find peak in the respiratory band
    mask = (freqs >= RESP_LO) & (freqs <= RESP_HI)
    if not np.any(mask):
        return RespiratoryResult(rate_bpm=0.0, confidence=0.0)

    band_freqs = freqs[mask]
    band_mag = fft_mag[mask]
    peak_idx = int(np.argmax(band_mag))
    peak_freq = band_freqs[peak_idx]
    peak_power = band_mag[peak_idx]

    # 6) Confidence: ratio of peak power to total power in the band
    total_power = float(np.sum(band_mag))
    confidence = float(peak_power / total_power) if total_power > 0 else 0.0

    # 7) Convert Hz → breaths per minute
    rate_bpm = peak_freq * 60.0

    return RespiratoryResult(
        rate_bpm=round(rate_bpm, 1),
        confidence=round(min(confidence, 1.0), 2),
    )
