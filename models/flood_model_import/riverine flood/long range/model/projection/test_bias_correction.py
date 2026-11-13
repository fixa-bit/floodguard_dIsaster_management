"""Bias-correction checks.  Run: ../../.venv/Scripts/python.exe -m pytest test_bias_correction.py"""
import numpy as np
import pandas as pd

from run_projection import bias_correct

DAYS = pd.date_range("1985-01-01", "2014-12-31", freq="D")


def wet_series(seed, scale, dry=0.5):
    rng = np.random.default_rng(seed)
    x = rng.gamma(0.6, scale, len(DAYS))
    x[rng.random(len(DAYS)) < dry] = 0.0  # many tied zeros, as in GCM precipitation
    return pd.Series(x, index=DAYS)


def test_quantile_mapping_matches_reference_mean_with_many_dry_days():
    ref, gcm = wet_series(1, 6.0, dry=0.3), wet_series(2, 3.0, dry=0.6)
    out = bias_correct(ref, gcm, gcm, "precip", "qm")
    assert abs(out.mean() / ref.mean() - 1) < 0.05


def test_dry_days_stay_dry():
    ref, gcm = wet_series(1, 6.0, dry=0.3), wet_series(2, 3.0, dry=0.6)
    out = bias_correct(ref, gcm, gcm, "precip", "qm")
    # GCM dry days (60%) map to the reference's driest 60%, so most must be 0 or very small.
    assert out[gcm.eq(0)].median() < 0.1


def test_qdm_preserves_relative_change():
    ref, hist = wet_series(1, 6.0), wet_series(2, 3.0)
    fut = hist * 1.2
    fut.index = fut.index + pd.DateOffset(years=40)
    out = bias_correct(ref, hist, fut, "precip", "qdm")
    assert abs(out.mean() / ref.mean() - 1.2) < 0.06


def test_qdm_keeps_gcm_mean_change_when_wet_day_frequencies_differ():
    """Reference wet 70 % of days, GCM 40 %, GCM future 10 % drier: the corrected change must stay -10 %."""
    ref, hist = wet_series(1, 6.0, dry=0.3), wet_series(2, 3.0, dry=0.6)
    fut = hist * 0.9
    fut.index = fut.index + pd.DateOffset(years=40)
    out = bias_correct(ref, hist, fut, "precip", "qdm")
    corrected_hist = bias_correct(ref, hist, hist, "precip", "qm")
    assert abs(out.mean() / corrected_hist.mean() - 0.9) < 0.02


def test_temperature_shift_is_additive():
    rng = np.random.default_rng(3)
    ref = pd.Series(rng.normal(5, 3, len(DAYS)), index=DAYS)
    hist = pd.Series(rng.normal(2, 4, len(DAYS)), index=DAYS)
    fut = hist + 1.5
    fut.index = fut.index + pd.DateOffset(years=40)
    out = bias_correct(ref, hist, fut, "temperature", "qdm")
    assert abs((out.mean() - ref.mean()) - 1.5) < 0.1
