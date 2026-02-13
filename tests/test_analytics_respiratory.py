"""Tests for poohw.analytics.respiratory -- respiratory rate from RR intervals."""

import math

import numpy as np
import pytest

from poohw.analytics.respiratory import (
    estimate_respiratory_rate,
    RespiratoryResult,
    _interpolate_rr,
    _bandpass_filter,
    RESP_LO,
    RESP_HI,
    INTERP_FS,
)


class TestInterpolateRR:
    def test_basic(self):
        rr = [800.0, 800.0, 800.0, 800.0, 800.0]
        t, vals = _interpolate_rr(rr)
        assert len(t) == len(vals)
        assert len(t) > 0

    def test_uniform_output(self):
        rr = [1000.0] * 10  # 1 sec each → 10 sec total
        t, vals = _interpolate_rr(rr, fs=4.0)
        # Should have ~40 samples over 10 seconds
        assert len(t) >= 35


class TestBandpassFilter:
    def test_passes_in_band(self):
        # Create a signal at 0.25 Hz (15 breaths/min) — should pass
        fs = 4.0
        t = np.arange(0, 30, 1 / fs)
        signal = np.sin(2 * math.pi * 0.25 * t)
        filtered = _bandpass_filter(signal, fs)
        # Power should be preserved (mostly)
        assert np.std(filtered) > 0.3 * np.std(signal)

    def test_rejects_out_of_band(self):
        # Create a signal at 1.0 Hz — well above respiratory band
        fs = 4.0
        t = np.arange(0, 30, 1 / fs)
        signal = np.sin(2 * math.pi * 1.0 * t)
        filtered = _bandpass_filter(signal, fs)
        # Should be attenuated significantly
        assert np.std(filtered) < 0.3 * np.std(signal)


class TestEstimateRespiratoryRate:
    def test_too_few_intervals(self):
        result = estimate_respiratory_rate([800.0] * 5)
        assert result.rate_bpm == 0.0
        assert result.confidence == 0.0

    def test_known_respiratory_rate(self):
        """Simulate RR intervals with a known respiratory modulation.

        Breathing at 15 breaths/min = 0.25 Hz.
        Base RR = 800 ms, modulated ±30 ms.
        """
        base_rr = 800.0  # ms
        resp_freq = 0.25  # Hz
        n_beats = 200

        # Build a time axis from the cumulative RR
        rr_list = []
        cumulative_t = 0.0
        for i in range(n_beats):
            modulation = 30.0 * math.sin(2 * math.pi * resp_freq * cumulative_t / 1000.0)
            rr = base_rr + modulation
            rr_list.append(rr)
            cumulative_t += rr

        result = estimate_respiratory_rate(rr_list)
        # Should detect ~15 breaths/min ± 3
        assert 12.0 <= result.rate_bpm <= 18.0
        assert result.confidence > 0.1

    def test_constant_rr_low_confidence(self):
        # No respiratory modulation → no clear peak
        rr = [800.0] * 100
        result = estimate_respiratory_rate(rr)
        # rate might be anything but confidence should be low or zero
        # (constant signal → no variation after bandpass)
        assert result.confidence <= 0.5 or result.rate_bpm == 0.0

    def test_result_repr(self):
        result = RespiratoryResult(rate_bpm=15.5, confidence=0.85)
        s = repr(result)
        assert "15.5" in s
        assert "0.85" in s
