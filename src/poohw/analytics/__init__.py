"""Analytics engine for computing health metrics from decoded Whoop sensor data.

Modules:
    features   -- Epoch windowing and feature extraction (HR, accel, HRV)
    sleep      -- Cole-Kripke sleep/wake detection
    recovery   -- HRV-based recovery scoring
    strain     -- HR-zone TRIMP strain scoring
    spo2       -- SpO2 from red/IR ratios
    respiratory -- Respiratory rate from RR interval FFT
    activity   -- Activity classification (accel + HR)
    summary    -- Daily summary aggregation
"""

from poohw.analytics.features import (
    epoch_windows,
    hr_features,
    accel_features,
    compute_rmssd,
    lnrmssd_score,
    sdnn,
    pnn50,
)
from poohw.analytics.sleep import score_sleep, SleepResult, SleepEpoch
from poohw.analytics.recovery import score_recovery, RecoveryResult
from poohw.analytics.strain import score_strain, StrainResult
from poohw.analytics.spo2 import (
    estimate_spo2_from_ratio,
    analyze_spo2_session,
    SpO2Result,
)
from poohw.analytics.respiratory import estimate_respiratory_rate, RespiratoryResult
from poohw.analytics.activity import classify_activity, ActivityResult
from poohw.analytics.summary import build_daily_summary, DailySummary

__all__ = [
    # features
    "epoch_windows",
    "hr_features",
    "accel_features",
    "compute_rmssd",
    "lnrmssd_score",
    "sdnn",
    "pnn50",
    # sleep
    "score_sleep",
    "SleepResult",
    "SleepEpoch",
    # recovery
    "score_recovery",
    "RecoveryResult",
    # strain
    "score_strain",
    "StrainResult",
    # spo2
    "estimate_spo2_from_ratio",
    "analyze_spo2_session",
    "SpO2Result",
    # respiratory
    "estimate_respiratory_rate",
    "RespiratoryResult",
    # activity
    "classify_activity",
    "ActivityResult",
    # summary
    "build_daily_summary",
    "DailySummary",
]
