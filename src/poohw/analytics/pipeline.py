"""Analytics pipeline: wire decoded BLE records into the analytics engine.

This module consumes the list of decoded records produced by
:func:`poohw.replay.replay_file` (or similar) and runs the full
analytics pipeline, producing a :class:`DailySummary`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np

from poohw.decoders.historical import (
    ComprehensiveRecord,
    HistoricalAccelBatch,
    HistoricalHRRecord,
    HistoricalTempRecord,
    HistoricalSpO2RawRecord,
)
from poohw.analytics.features import accel_features, epoch_windows
from poohw.analytics.sleep import score_sleep
from poohw.analytics.recovery import score_recovery
from poohw.analytics.strain import score_strain
from poohw.analytics.spo2 import analyze_spo2_session
from poohw.analytics.respiratory import estimate_respiratory_rate
from poohw.analytics.activity import classify_activity
from poohw.analytics.summary import build_daily_summary, DailySummary


def _extract_data(records: list[dict]) -> dict[str, list]:
    """Walk the decoded record list and bin data by type.

    Each record dict has ``{"type": ..., "data": ...}``. The "data" value
    is either a dataclass instance or a dict.  We pull out the fields we
    need for the analytics pipeline.
    """
    hr_records: list[HistoricalHRRecord] = []
    accel_batches: list[HistoricalAccelBatch] = []
    temps: list[HistoricalTempRecord] = []
    spo2_raws: list[HistoricalSpO2RawRecord] = []

    for rec in records:
        decoded_list = rec.get("decoded", [])
        for d in decoded_list:
            # d is {"type": name, "data": str_repr} from replay_file,
            # but if called from pipeline directly it might be the object.
            obj = d.get("data")
            if obj is None:
                continue

            # If obj is a string representation, we can't do much.
            # The pipeline works best when called with actual objects.
            if isinstance(obj, HistoricalHRRecord):
                hr_records.append(obj)
            elif isinstance(obj, ComprehensiveRecord):
                if obj.hr:
                    hr_records.append(obj.hr)
                if obj.temperature:
                    temps.append(obj.temperature)
                if obj.spo2_raw:
                    spo2_raws.append(obj.spo2_raw)
            elif isinstance(obj, HistoricalAccelBatch):
                accel_batches.append(obj)
            elif isinstance(obj, HistoricalTempRecord):
                temps.append(obj)
            elif isinstance(obj, HistoricalSpO2RawRecord):
                spo2_raws.append(obj)

    return {
        "hr": hr_records,
        "accel": accel_batches,
        "temps": temps,
        "spo2": spo2_raws,
    }


def run_pipeline(
    records: list[dict],
    max_hr: float = 190.0,
    resting_hr: float = 60.0,
    sleep_need_min: float = 450.0,
    day_override: date | str | None = None,
) -> DailySummary:
    """Run the full analytics pipeline on decoded records.

    Args:
        records: List of record dicts from :func:`poohw.replay.replay_file`.
        max_hr: User's estimated max heart rate.
        resting_hr: User's resting heart rate (for strain calorie est.).
        sleep_need_min: Target sleep minutes for recovery scoring.
        day_override: Override the date (default: today).

    Returns:
        A populated DailySummary.
    """
    data = _extract_data(records)
    hr_records = data["hr"]
    accel_batches = data["accel"]
    temps = data["temps"]
    spo2_raws = data["spo2"]

    # --- Determine the day ---
    if day_override:
        day = day_override
    elif hr_records:
        day = datetime.utcfromtimestamp(hr_records[0].timestamp).date()
    else:
        day = date.today()

    # --- Collect time series ---
    # Sort HR records by timestamp
    hr_records.sort(key=lambda r: r.timestamp)
    hr_timestamps = [float(r.timestamp) for r in hr_records]
    hr_values = [float(r.hr_bpm) for r in hr_records]
    all_rr: list[float] = []
    for r in hr_records:
        all_rr.extend(r.rr_intervals_ms)

    # Collect accel data into 1-minute epochs
    accel_batches.sort(key=lambda b: b.timestamp)
    accel_timestamps: list[float] = []
    accel_stds: list[float] = []
    accel_counts: list[float] = []  # activity counts for sleep scoring

    for batch in accel_batches:
        if batch.samples:
            feat = accel_features(batch.samples)
            accel_timestamps.append(float(batch.timestamp))
            accel_stds.append(feat.std_magnitude)
            accel_counts.append(feat.activity_counts)

    # --- Sleep ---
    sleep_result = None
    if accel_counts:
        # Use accel timestamps for sleep scoring
        sleep_hr = None
        if hr_values and len(hr_values) >= len(accel_timestamps):
            # Try to align HR with accel epochs (nearest neighbor)
            sleep_hr = hr_values[:len(accel_timestamps)]

        daytime_mean = float(np.mean(hr_values)) if hr_values else None
        sleep_result = score_sleep(
            accel_timestamps,
            accel_counts,
            hr_values=sleep_hr,
            daytime_mean_hr=daytime_mean,
        )

    # --- Recovery ---
    recovery_result = None
    if all_rr and hr_values:
        actual_sleep = sleep_result.total_sleep_min if sleep_result else 0.0
        recovery_result = score_recovery(
            rr_intervals_sleep=all_rr,
            hr_during_sleep=hr_values,
            actual_sleep_min=actual_sleep,
            sleep_need_min=sleep_need_min,
        )

    # --- Strain ---
    strain_result = None
    if hr_values:
        strain_result = score_strain(
            hr_values,
            max_hr=max_hr,
            resting_hr=resting_hr,
        )

    # --- SpO2 ---
    spo2_result = None
    if spo2_raws:
        ratios = [
            r.red_ir_ratio for r in spo2_raws
            if r.red_ir_ratio is not None
        ]
        if ratios:
            spo2_result = analyze_spo2_session(ratios)

    # --- Respiratory rate ---
    resp_result = None
    if len(all_rr) >= 10:
        resp_result = estimate_respiratory_rate(all_rr)

    # --- Activity ---
    activity_result = None
    if accel_stds:
        activity_hr = hr_values[:len(accel_stds)] if hr_values else None
        activity_result = classify_activity(
            accel_timestamps,
            accel_stds,
            hr_values=activity_hr,
            max_hr=max_hr,
        )

    # --- Temperature ---
    skin_temp = None
    if temps:
        skin_temp = float(np.median([t.skin_temp_c for t in temps]))

    return build_daily_summary(
        day=day,
        sleep=sleep_result,
        recovery=recovery_result,
        strain=strain_result,
        spo2=spo2_result,
        respiratory=resp_result,
        activity=activity_result,
        skin_temp_c=skin_temp,
    )
