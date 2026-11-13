"""Shared data loading and scoring for the Marala long-range models.

Every source is read from its own file (short-range data is read-only) and
joined by date in memory. Observed, simulated (GloFAS) and reanalysis series
stay in separate columns; nothing combined is written back to disk, and no
missing value is filled.
"""
from __future__ import annotations

import glob
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

LONG = Path(__file__).resolve().parents[1]
SHORT = LONG.parent / "short range" / "dataset" / "chenab_marala"
RAW = SHORT / "raw" / "marala"
PROC = SHORT / "processed" / "marala"
EXTENSION_DIR = LONG / "dataset" / "era5land_marala_extension"

FORCING = ["precip_era5land_mm", "temperature_c", "dewpoint_c", "pet_mm",
           "snowmelt_mm", "snow_depth_m", "swe_mm", "ssrd_wm2"]
SOURCES: dict[str, Path] = {}


def _register(name: str, path: Path) -> Path:
    SOURCES[name] = path
    return path


def _yearly(folder: str, column: str) -> pd.Series:
    files = sorted(glob.glob(str(RAW / folder / "[0-9][0-9][0-9][0-9].csv")))
    _register(folder, RAW / folder)
    frame = pd.concat([pd.read_csv(f, parse_dates=["date"]) for f in files])
    return frame.set_index("date")[column]


def load_forcing() -> pd.DataFrame:
    """ERA5-Land catchment means, 1980-2024 from short range, 2025+ from the extension."""
    p = pd.read_csv(_register("precip", RAW / "rainfall/google_earth_engine/marala_daily_precipitation_1980_2024.csv"),
                    parse_dates=["date"]).set_index("date")["era5land_mm"]
    t = pd.read_csv(_register("temperature", RAW / "temperature/google_earth_engine/marala_daily_temperature_1980_2024.csv"),
                    parse_dates=["date"]).set_index("date")["era5land_temperature_2m_c"]
    pet = pd.read_csv(_register("pet", RAW / "potential_evaporation_sum/marala_daily_pet_1980_2024.csv"),
                      parse_dates=["date"]).set_index("date")["pet_mm"]
    base = pd.DataFrame({
        "precip_era5land_mm": p, "temperature_c": t, "pet_mm": pet,
        "dewpoint_c": _yearly("dewpoint_temperature", "dewpoint_c"),
        "snowmelt_mm": _yearly("snowmelt_sum", "snowmelt_mm"),
        "snow_depth_m": _yearly("snow_depth", "snow_depth_m"),
        "swe_mm": _yearly("snow_depth_water_equivalent", "swe_mm"),
        "ssrd_wm2": _yearly("surface_solar_radiation_downwards_sum", "ssrd_wm2"),
    })[FORCING]
    base["forcing_source"] = "short_range_era5land"
    ext_files = sorted(EXTENSION_DIR.glob("marala_era5land_daily_*.csv"))
    if ext_files:
        ext = pd.read_csv(_register("era5land_extension", ext_files[-1]), parse_dates=["date"]).set_index("date")[FORCING]
        ext = ext.loc[ext.index > base.index.max()]  # 2024 in the extension is verification only.
        ext["forcing_source"] = "long_range_era5land_extension"
        base = pd.concat([base, ext])
    return base.sort_index().asfreq("D")


def load_observed() -> pd.DataFrame:
    """Observed Marala inflow (m3/s). WAPDA first; Sindh rim-station only on days WAPDA lacks."""
    w = pd.read_csv(_register("wapda", PROC / "discharge/marala_daily_inflow_clean.csv"), parse_dates=["date"])
    w = w.loc[w["eligible_daily_training"].eq(1)].set_index("date")["inflow_m3_s"]
    s = pd.read_csv(_register("sindh_rim", PROC / "discharge/marala_sindh_rimstation_discharge.csv"), parse_dates=["date"])
    s = s.loc[~s["inflow_check_vs_wapda_ffd"].astype(str).str.startswith("conflict")].set_index("date")["inflow_m3_s"]
    out = pd.DataFrame({"q_obs": w, "q_obs_source": "WAPDA"})
    extra = s.loc[~s.index.isin(out.index)]
    out = pd.concat([out, pd.DataFrame({"q_obs": extra, "q_obs_source": "Sindh_rim"})]).sort_index()
    return out


def load_glofas() -> pd.Series:
    g = pd.read_csv(_register("glofas_v5", PROC / "discharge/simulated/marala_glofas_historical_daily.csv"),
                    parse_dates=["date_utc_day_averaged"])
    return g.set_index("date_utc_day_averaged")["glofas_v5_0_m3_s"].rename("q_glofas")


def load_all() -> pd.DataFrame:
    """Daily frame on the forcing calendar. q_obs and q_glofas are separate columns."""
    frame = load_forcing()
    frame = frame.join(load_observed(), how="left").join(load_glofas(), how="left")
    return frame


def provenance() -> dict:
    out = {}
    for name, path in SOURCES.items():
        rel = str(path.relative_to(LONG.parent)).replace("\\", "/")
        out[name] = {"path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
    return out


# ---------------------------------------------------------------- scoring
def doy_climatology(q: pd.Series, years: list[int], window: int = 31) -> pd.Series:
    """Day-of-year mean of log1p(Q) over the given years, circularly smoothed; returned in m3/s."""
    sel = q.loc[q.index.year.isin(years)].dropna()
    doy = sel.index.day_of_year.where(sel.index.day_of_year <= 365, 365)
    means = np.log1p(sel).groupby(doy).mean().reindex(range(1, 366))
    padded = pd.concat([means.iloc[-window:], means, means.iloc[:window]])
    smooth = padded.rolling(window, center=True, min_periods=1).mean().iloc[window:-window]
    return np.expm1(smooth)


def clim_for_dates(clim: pd.Series, dates: pd.DatetimeIndex) -> np.ndarray:
    doy = np.minimum(dates.day_of_year, 365)
    return clim.loc[doy].to_numpy()


def scores(obs, pred, clim=None, lo=None, hi=None) -> dict:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    ok = np.isfinite(obs) & np.isfinite(pred)
    obs, pred = obs[ok], pred[ok]
    if len(obs) < 2:
        return {"n": int(len(obs))}
    err = pred - obs
    rmse = float(np.sqrt(np.mean(err ** 2)))
    r = float(np.corrcoef(obs, pred)[0, 1])
    alpha = float(pred.std() / obs.std())
    beta = float(pred.mean() / obs.mean())
    out = {"n": int(len(obs)), "rmse": rmse, "mae": float(np.mean(np.abs(err))),
           "nse": float(1 - np.sum(err ** 2) / np.sum((obs - obs.mean()) ** 2)),
           "kge": float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)),
           "pbias_pct": float(100 * err.sum() / obs.sum()), "r": r}
    if clim is not None:
        c = np.asarray(clim, float)[ok]
        crmse = float(np.sqrt(np.mean((c - obs) ** 2)))
        out["climatology_rmse"] = crmse
        out["rmse_skill_vs_climatology"] = float(1 - rmse / crmse) if crmse else float("nan")
    if lo is not None and hi is not None:
        lo_, hi_ = np.asarray(lo, float)[ok], np.asarray(hi, float)[ok]
        out["p10_p90_coverage"] = float(np.mean((obs >= lo_) & (obs <= hi_)))
    return out
