"""Build the Marala riverine outlook snapshot served by the Riverine Forecast tab.

Runs the trained flood_model riverine models forward from the latest data and
summarises their saved projection outputs into one JSON file:

* 180-day TFT outlook (forecast mode, fine-tuned 3-seed ensemble, conformally
  calibrated P10-P90) issued from the last day with complete ERA5-Land forcing.
  The same issue one year earlier is replayed as a track-record check.
* 90- and 180-day mean-flow outlook from the observed residual Ridge models.
* Day-of-year normal range of observed Marala inflow.
* 2026-2040 climate projections (8 CMIP6 GCMs x SSP2-4.5 / SSP5-8.5) from the
  projection-mode TFT and the storm-rainfall flood-peak model.
* Research leaderboard of the 10-day models (day-10 flood-day detection).

Model weights come from this app's copy in ``models/flood_model_import``.
Input data and saved projection outputs are read from the flood_model project
at build time only; the app serves the resulting JSON and never reads
flood_model at runtime. Nothing is filled: missing observations stay missing.

    .venv\\Scripts\\python.exe models\\riverine_outlook\\build_marala_outlook.py
    .venv\\Scripts\\python.exe models\\riverine_outlook\\build_marala_outlook.py --source D:\\projects\\flood_model\\flood_model
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
IMPORT = ROOT / "models" / "flood_model_import" / "riverine flood"
LONG_COPY = IMPORT / "long range" / "model"
RIDGE_COPY = IMPORT / "short range" / "seasonal" / "Observed_residual_Ridge" / "runs"
DEFAULT_SOURCE = Path(r"D:\projects\flood_model\flood_model")
OUT = HERE / "artifacts" / "marala_outlook.json"

CUSECS_TO_CUMECS = 0.028316846592
FLOOD_CLASSES_CUSECS = {"Low": 100_000, "Medium": 150_000, "High": 200_000, "Very High": 400_000, "Exceptional": 600_000}
HORIZON = 180
SEEDS = (11, 22, 33)
NORMAL_YEARS = list(range(2016, 2026))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _r(value, digits=1):
    if value is None:
        return None
    value = float(value)
    return None if not np.isfinite(value) else round(value, digits)


# ------------------------------------------------------------------ TFT 180-day outlook
class TftRunner:
    def __init__(self, source_long_model: Path):
        import torch
        import yaml

        self.torch = torch
        sys.path.insert(0, str(source_long_model))  # data loaders resolve paths inside flood_model
        self.common = _load_module("common", source_long_model / "common.py")
        sys.path.insert(0, str(LONG_COPY / "tft"))
        self.tft = _load_module("tft", LONG_COPY / "tft" / "tft.py")
        self.train = _load_module("tft_train", LONG_COPY / "tft" / "train.py")
        self.cfg = yaml.safe_load((LONG_COPY / "tft" / "config.yaml").read_text(encoding="utf-8"))
        self.mode_cfg = self.cfg["modes"]["forecast"]
        self.frame = self.common.load_all()
        self.forcing_end = self.frame[self.common.FORCING].dropna().index.max()
        calendar = pd.date_range(self.frame.index[0], self.forcing_end + pd.Timedelta(days=HORIZON + 1), freq="D")
        self.frame_ext = self.frame.reindex(calendar)  # future rows carry calendar only (forecast mode)
        self.arr = self.train.prepare(self.frame_ext, self.cfg)
        saved = json.loads((LONG_COPY / "tft" / "runs" / "normalisation.json").read_text(encoding="utf-8"))
        if abs(saved["q_log_mean"] - self.arr["norm"]["q_log_mean"]) > 1e-6:
            raise RuntimeError("Normalisation differs from the trained run; data changed before 2014")
        self.offsets = pd.read_csv(LONG_COPY / "calibration" / "reports" / "conformal_offsets_deployment.csv")
        self.offsets = self.offsets.loc[self.offsets["mode"].eq("forecast") & self.offsets["model"].eq("tft_finetuned")]
        device = torch.device("cpu")
        self.batcher = self.train.Batcher(self.arr, self.cfg, self.mode_cfg, "observed", self.train.OBSERVED,
                                          ["1980-01-01", "2100-01-01"], device)
        self.models = []
        for seed in SEEDS:
            model = self.tft.TemporalFusionTransformer(self.batcher.n_past, self.batcher.n_future, 2,
                                                       quantiles=self.cfg["quantiles"], **self.cfg["model"])
            state = torch.load(LONG_COPY / "tft" / "runs" / f"forecast_seed{seed}_finetuned.pt", map_location=device)
            model.load_state_dict(state)
            model.eval()
            self.models.append(model)

    def issue_ok(self, i: int) -> tuple[bool, str]:
        Te = self.cfg["encoder_days"]
        past = self.arr["forcing"][i - Te + 1:i + 1][:, self.train.past_cols(self.mode_cfg)]
        if not np.isfinite(past).all():
            return False, "incomplete ERA5-Land forcing in the 365-day encoder window"
        cover = np.isfinite(self.arr["q"]["observed"][i - 89:i + 1]).mean()
        if cover < self.cfg["min_past_obs_coverage_90d"]:
            return False, f"observed inflow covers {cover:.0%} of the last 90 days (needs 80%)"
        return True, ""

    def run(self, issue: pd.Timestamp) -> pd.DataFrame:
        torch = self.torch
        i = int(self.arr["dates"].get_loc(issue))
        ok, reason = self.issue_ok(i)
        if not ok:
            raise RuntimeError(f"Cannot issue the TFT outlook on {issue.date()}: {reason}")
        past, fut, static, _, _ = self.batcher(np.array([i]))
        with torch.no_grad():
            z = np.mean([m(past, fut, static)[0].numpy() for m in self.models], axis=0)[0]
        z = np.sort(z, axis=-1)
        mu, sd = self.arr["norm"]["q_log_mean"], self.arr["norm"]["q_log_std"]
        q = np.expm1(z * sd + mu)
        dates = self.arr["dates"][i + 1:i + 1 + HORIZON]
        out = pd.DataFrame({"date": dates, "lead_days": np.arange(1, HORIZON + 1),
                            "p10": q[:, 0], "p50": q[:, 1], "p90": q[:, 2]})
        season = np.where(out["date"].dt.month.between(6, 9), "monsoon_JJAS", "other_months")
        lead = np.where(out["lead_days"] <= 30, "lead_1_30", "lead_31_180")
        out["stratum"] = pd.Series(season) + "|" + pd.Series(lead)
        out = out.merge(self.offsets[["stratum", "delta_lower", "delta_upper"]], on="stratum", how="left")
        out["p10_cal"] = np.expm1(np.log1p(out["p10"]) - out["delta_lower"]).clip(lower=0)
        out["p90_cal"] = np.expm1(np.log1p(out["p90"]) + out["delta_upper"])
        out["observed"] = self.frame_ext["q_obs"].reindex(dates).to_numpy()
        return out


def normal_range(observed: pd.Series, dates: pd.DatetimeIndex, window: int = 15) -> pd.DataFrame:
    """P10/P50/P90 of observed inflow on the same calendar days (+-window) in NORMAL_YEARS."""
    obs = observed.loc[observed.index.year.isin(NORMAL_YEARS)].dropna()
    doy = obs.index.day_of_year.to_numpy()
    values = obs.to_numpy()
    rows = []
    for day in dates:
        d = day.day_of_year
        dist = np.minimum(np.abs(doy - d), 366 - np.abs(doy - d))
        sample = values[dist <= window]
        rows.append({"date": day, "normal_p10": np.quantile(sample, 0.1), "normal_p50": np.quantile(sample, 0.5),
                     "normal_p90": np.quantile(sample, 0.9), "normal_n_years": len(set(obs.index.year[dist <= window]))})
    return pd.DataFrame(rows)


def tft_block(runner: TftRunner) -> dict:
    issue = runner.forcing_end
    observed = runner.frame["q_obs"]
    forward = runner.run(issue)
    normals = normal_range(observed, pd.DatetimeIndex(forward["date"]))
    forward = forward.merge(normals, on="date")

    # Track record: same model, same calendar issue one year earlier, compared with what happened.
    back_issue = issue - pd.DateOffset(years=1)
    back = runner.run(back_issue)
    back = back.merge(normal_range(observed, pd.DatetimeIndex(back["date"])), on="date")
    seen = back.dropna(subset=["observed"])
    inside = ((seen["observed"] >= seen["p10_cal"]) & (seen["observed"] <= seen["p90_cal"])).mean()
    inside_normal = ((seen["observed"] >= seen["normal_p10"]) & (seen["observed"] <= seen["normal_p90"])).mean()

    def monthly(df):
        rows = []
        for month, g in df.groupby(df["date"].dt.to_period("M")):
            rows.append({"month": str(month), "days": int(len(g)), "partial": bool(len(g) < month.days_in_month),
                         "p10": _r(g["p10_cal"].mean()), "p50": _r(g["p50"].mean()), "p90": _r(g["p90_cal"].mean()),
                         "normal_p50": _r(g["normal_p50"].mean()),
                         "change_vs_normal_pct": _r((g["p50"].mean() / g["normal_p50"].mean() - 1) * 100)})
        return rows

    history = observed.loc[issue - pd.Timedelta(days=365):issue]
    hist_dates = pd.date_range(issue - pd.Timedelta(days=365), issue, freq="D")
    hist_normal = normal_range(observed, hist_dates)
    return {
        "issue_date": issue.date().isoformat(),
        "issue_basis": "Last day with complete ERA5-Land catchment forcing; flow history = observed Marala inflow",
        "model": "Temporal Fusion Transformer · forecast mode · GloFAS-pretrained, fine-tuned on observed inflow · 3-seed ensemble",
        "interval": "P10–P90, conformally calibrated (deployment offsets fitted on 2022–2026)",
        "daily": [{"date": r.date.date().isoformat(), "p10": _r(r.p10_cal), "p50": _r(r.p50), "p90": _r(r.p90_cal),
                   "normal_p10": _r(r.normal_p10), "normal_p50": _r(r.normal_p50), "normal_p90": _r(r.normal_p90)}
                  for r in forward.itertuples()],
        "monthly": monthly(forward),
        "observed_last_365": [{"date": d.date().isoformat(), "observed": _r(history.get(d)),
                               "normal_p10": _r(n.normal_p10), "normal_p50": _r(n.normal_p50), "normal_p90": _r(n.normal_p90)}
                              for d, n in zip(hist_dates, hist_normal.itertuples())],
        "peak": {"date": forward.loc[forward["p50"].idxmax(), "date"].date().isoformat(),
                 "p50": _r(forward["p50"].max()), "p90": _r(forward["p90_cal"].max())},
        "mean_p50": _r(forward["p50"].mean()), "mean_normal_p50": _r(forward["normal_p50"].mean()),
        "track_record": {
            "issue_date": back_issue.date().isoformat(),
            "daily": [{"date": r.date.date().isoformat(), "p10": _r(r.p10_cal), "p50": _r(r.p50), "p90": _r(r.p90_cal),
                       "observed": _r(r.observed), "normal_p50": _r(r.normal_p50)} for r in back.itertuples()],
            "observed_days": int(len(seen)),
            "share_inside_band": _r(inside, 3),
            "share_inside_normal_range": _r(inside_normal, 3),
            "mae_p50": _r((seen["observed"] - seen["p50"]).abs().mean()),
            "mae_normal": _r((seen["observed"] - seen["normal_p50"]).abs().mean()),
        },
    }


# ------------------------------------------------------------------ Ridge seasonal means
def ridge_block(runner: TftRunner, ridge_source: Path) -> dict:
    import joblib

    ridge_mod = _load_module("ridge_train", ridge_source / "train_evaluate.py")
    f = runner.frame
    frame = pd.DataFrame({
        "q": f["q_obs"], "rain_era5_mm": f["precip_era5land_mm"], "temperature_c": f["temperature_c"],
        "swe_mm": f["swe_mm"], "snowmelt_mm": f["snowmelt_mm"], "snow_depth_m": f["snow_depth_m"], "pet_mm": f["pet_mm"],
    })
    issue = pd.Timestamp(runner.forcing_end.year, runner.forcing_end.month, 1)
    row = ridge_mod.feature_row(frame, "q", issue, 0.8)
    out = {"issue_date": issue.date().isoformat(),
           "model": "Observed residual Ridge (90- and 180-day mean flow, correction to month-of-issue climatology)",
           "flow_history": "Observed Marala inflow (Sindh rim-station after WAPDA ends in Dec 2024)",
           "horizons": []}
    if row is None:
        out["unavailable_reason"] = "Flow or weather history before the issue date is below 80% coverage"
        return out
    for horizon in (90, 180):
        bundle = joblib.load(RIDGE_COPY / f"observed_ridge_{horizon}day.joblib")
        x = pd.DataFrame([row]).reindex(columns=bundle["feature_columns"])
        clim = float(bundle["monthly_climatology"].get(issue.month))
        pred = max(0.0, float(np.expm1(np.log1p(clim) + bundle["model"].predict(x)[0])))
        start, end = issue + pd.Timedelta(days=1), issue + pd.Timedelta(days=horizon)
        out["horizons"].append({
            "horizon_days": horizon, "window_start": start.date().isoformat(), "window_end": end.date().isoformat(),
            "mean_flow": _r(pred), "normal_mean_flow": _r(clim), "change_vs_normal_pct": _r((pred / clim - 1) * 100),
            "missing_features": int(x.isna().sum().sum()),
        })
    return out


# ------------------------------------------------------------------ climate projections
def projection_block(proj_dir: Path) -> dict:
    change = pd.read_csv(proj_dir / "change_vs_gcm_historical.csv")
    peaks = pd.read_csv(proj_dir / "annual_peak_probabilities.csv")
    stats = pd.read_csv(proj_dir / "period_statistics.csv")
    daily = pd.read_csv(proj_dir / "daily_flow_quantiles.csv.gz", parse_dates=["date"])
    metrics = {
        "mean_flow_pct": "mean_flow_m3s_change_pct", "snowmelt_season_pct": "AMJ_snowmelt_mean_m3s_change_pct",
        "monsoon_pct": "JAS_monsoon_mean_m3s_change_pct", "low_flow_season_pct": "ONDJFM_low_flow_mean_m3s_change_pct",
        "annual_max_daily_pct": "annual_max_daily_p50_m3s_change_pct", "precip_pct": "annual_precip_mm_change_pct",
        "temperature_c": "temperature_change_c",
    }
    ref = stats.loc[stats["gcm"].eq("ERA5-Land")].iloc[0]
    scenarios = []
    for exp, label, desc in (("ssp245", "SSP2-4.5", "Middle-of-the-road emissions"),
                             ("ssp585", "SSP5-8.5", "Very high emissions")):
        periods = []
        for period in ("2026-2030", "2031-2035", "2036-2040", "2026-2040"):
            g = change.loc[change["experiment"].eq(exp) & change["period"].eq(period)]
            block = {"period": period.replace("-", "–"), "gcms": int(len(g))}
            for key, col in metrics.items():
                block[key] = {"median": _r(g[col].median(), 2), "low": _r(g[col].min(), 2), "high": _r(g[col].max(), 2)}
            for k, hist, fut in (("p400k", "p_exceed_400k_per_year_hist", "p_exceed_400k_per_year_future"),
                                 ("p600k", "p_exceed_600k_per_year_hist", "p_exceed_600k_per_year_future")):
                block[k] = {"baseline": _r(g[hist].median(), 3), "median": _r(g[fut].median(), 3),
                            "low": _r(g[fut].min(), 3), "high": _r(g[fut].max(), 3)}
            periods.append(block)

        p = peaks.loc[peaks["experiment"].eq(exp) & peaks["year"].between(2026, 2040)]
        yearly = []
        for year, g in p.groupby("year"):
            yearly.append({"year": int(year),
                           "p200k": _r(g["p_exceed_high_200k_cusecs"].median(), 3),
                           "p400k": _r(g["p_exceed_very_high_400k_cusecs"].median(), 3),
                           "p400k_low": _r(g["p_exceed_very_high_400k_cusecs"].min(), 3),
                           "p400k_high": _r(g["p_exceed_very_high_400k_cusecs"].max(), 3),
                           "p600k": _r(g["p_exceed_exceptional_600k_cusecs"].median(), 3)})
        pooled = {k: _r(p[c].mean(), 3) for k, c in (("p200k", "p_exceed_high_200k_cusecs"),
                                                      ("p400k", "p_exceed_very_high_400k_cusecs"),
                                                      ("p600k", "p_exceed_exceptional_600k_cusecs"))}
        scenarios.append({"id": exp, "label": label, "description": desc, "periods": periods,
                          "yearly_flood_odds": yearly, "pooled_flood_odds": pooled})

    hist = peaks.loc[peaks["experiment"].eq("historical") & peaks["year"].between(1986, 2014)]
    baseline_odds = {k: _r(hist[c].mean(), 3) for k, c in (("p200k", "p_exceed_high_200k_cusecs"),
                                                          ("p400k", "p_exceed_very_high_400k_cusecs"),
                                                          ("p600k", "p_exceed_exceptional_600k_cusecs"))}

    # Typical-year hydrograph: day-of-year median of daily P50, per GCM, then median across GCMs.
    daily["doy"] = daily["date"].dt.day_of_year.clip(upper=365)

    def typical(sub: pd.DataFrame) -> np.ndarray:
        per_gcm = sub.groupby(["gcm", "doy"])["p50_m3s"].mean().unstack(0)
        curve = per_gcm.median(axis=1).reindex(range(1, 366))
        return curve.rolling(15, center=True, min_periods=1).mean().to_numpy()

    base = typical(daily.loc[daily["experiment"].eq("historical") & daily["date"].dt.year.between(1986, 2014)])
    hydro = {"baseline": [_r(v, 0) for v in base]}
    for exp in ("ssp245", "ssp585"):
        hydro[exp] = [_r(v, 0) for v in typical(daily.loc[daily["experiment"].eq(exp) & daily["date"].dt.year.between(2026, 2040)])]

    return {
        "period": "2026–2040", "baseline_period": "1986–2014",
        "chain": "8 NEX-GDDP-CMIP6 GCMs → bias correction to ERA5-Land → projection-mode TFT (calibrated P10/P50/P90) + storm-rainfall flood-peak model",
        "gcms": sorted(change["gcm"].unique().tolist()),
        "reference_era5land": {"mean_flow": _r(ref["mean_flow_m3s"]), "monsoon_mean": _r(ref["JAS_monsoon_mean_m3s"]),
                               "p400k": _r(ref["p_exceed_400k_per_year"], 3), "p600k": _r(ref["p_exceed_600k_per_year"], 3)},
        "baseline_flood_odds": baseline_odds,
        "scenarios": scenarios,
        "typical_year_hydrograph": hydro,
    }


# ------------------------------------------------------------------ evidence
def peak_block(extremes_dir: Path) -> dict:
    model = json.loads((extremes_dir / "peak_model.json").read_text(encoding="utf-8"))
    tests = pd.read_csv(extremes_dir / "test_years_2017_2026.csv")
    t2025 = tests.loc[tests["year"].eq(2025)].iloc[0]
    return {
        "model": "Censored log-normal regression on the largest Jun–Sep 3-day catchment rainfall",
        "brier_400k_loo": _r(model["selection"]["P3"]["loo_brier_400k"], 3),
        "brier_400k_no_predictor": _r(model["selection"]["no_predictor"]["loo_brier_400k"], 3),
        "test_2025": {"observed_peak": _r(t2025["obs_daily_max_m3s"], 0), "median": _r(t2025["pred_median_m3s"], 0),
                      "p10": _r(t2025["pred_p10_m3s"], 0), "p90": _r(t2025["pred_p90_m3s"], 0),
                      "p400k": _r(t2025["p_exceed_very_high_400k_cusecs"], 2)},
    }


def evidence_block(long_model: Path, ridge_reports: Path) -> dict:
    """Held-out test scores (2024-2026 issues) for the long-range models, read from their saved reports."""
    scores = pd.read_csv(long_model / "reports" / "scores_by_lead.csv")
    scores = scores.loc[scores["leads"].eq("1-180") & scores["target_period"].eq("all")]
    cover = pd.read_csv(long_model / "calibration" / "reports" / "test_coverage.csv")
    cover = cover.loc[cover["method"].eq("static_val_2022_2023") & cover["model"].eq("tft_finetuned") & cover["subset"].eq("all")]

    def tft(mode):
        s = scores.loc[scores["mode"].eq(mode) & scores["model"].eq("tft_finetuned")].iloc[0]
        c = cover.loc[cover["mode"].eq(mode)]
        return {"nse": _r(s["nse"], 2), "kge": _r(s["kge"], 2), "skill_vs_normal": _r(s["rmse_skill_vs_climatology"], 3),
                "pbias_pct": _r(s["pbias_pct"], 1),
                "band_coverage": _r(c["coverage_calibrated"].iloc[0], 3) if len(c) else None, "target_coverage": 0.8}

    clim = scores.loc[scores["mode"].eq("forecast") & scores["model"].eq("climatology")].iloc[0]
    glofas = scores.loc[scores["mode"].eq("climate_conditioned") & scores["model"].eq("glofas_raw")].iloc[0]
    ridge = pd.read_csv(ridge_reports / "rolling_oof_summary.csv")
    return {
        "test_period": "Issues from 2024-01-01 to 2026, leads 1–180 days (held out from training)",
        "tft_forecast": tft("forecast"), "tft_projection": tft("projection"),
        "normal_season_nse": _r(clim["nse"], 2),
        "glofas_pbias_pct": _r(glofas["pbias_pct"], 1), "glofas_nse": _r(glofas["nse"], 2),
        "ridge": [{"horizon_days": int(r.horizon_days), "skill_vs_normal": _r(r.rmse_skill_vs_climatology, 3),
                   "high_flow_hit_rate": _r(r.flood_hit_rate, 2), "false_alarm_rate": _r(r.flood_false_alarm_rate, 2),
                   "test_years": str(r.test_years)} for r in ridge.itertuples()],
    }


TRANSFER_DIAGNOSTICS ={"Global LSTM zero-shot (reference)", "8-basin donor LSTM without adaptation"}
BASELINES = {"Persistence", "Climatology"}


def ten_day_block(eval_dir: Path) -> dict:
    """Main 2022-2024 cohort: flood-day hit rate by lead and day-10 accuracy for each trained model."""
    det = pd.read_csv(eval_dir / "flood_detection_by_lead.csv")
    det = det.loc[det["cohort"].eq("main_2022_2024") & det["lead_day"].between(1, 10)]
    scores = pd.read_csv(eval_dir / "main_day10_scores.csv")
    scores = scores.loc[scores["cohort"].eq("main_2022_2024") & scores["lead_day"].eq(10)]
    models = []
    for name, g in det.groupby("model"):
        if name in TRANSFER_DIAGNOSTICS:
            continue
        g = g.sort_values("lead_day")
        s = scores.loc[scores["model"].eq(name)].set_index("group")
        d10 = g.loc[g["lead_day"].eq(10)].iloc[0]
        models.append({
            "model": name, "baseline": name in BASELINES,
            "hit_rate_by_lead": [_r(v, 3) for v in g["POD"]],
            "hit_rate_day10": _r(d10["POD"], 3), "false_alarm_ratio_day10": _r(d10["false_alarm_ratio"], 3),
            "csi_day10": _r(d10["CSI"], 3),
            "nse_day10": _r(s.loc["all", "NSE"], 3) if "all" in s.index else None,
            "rmse_day10": _r(s.loc["all", "RMSE_cumecs"], 0) if "all" in s.index else None,
            "flood_rmse_day10": _r(s.loc["flood", "RMSE_cumecs"], 0) if "flood" in s.index else None,
        })
    models.sort(key=lambda m: (-(m["csi_day10"] or 0), m["model"]))
    return {"cohort": "Observed target days 2022–2024, identical issue/target pairs for every model",
            "flood_day_definition": "Observed flow above the 2016–2020 Q95 (2,495 m³/s)",
            "forcing_caveat": "Future ERA5-Land reanalysis stood in for forecast weather, so these are upper-bound research scores, not operational accuracy",
            "flood_days": int(det["TP"].iloc[0] + det["FN"].iloc[0]) if len(det) else 0,
            "models": models}


# ------------------------------------------------------------------ short-range model replay
# Every trained short-range model's saved test predictions (issues 2022-2024). Families drive the UI colour.
SHORT_MODELS = [
    # id, label, family, folder (under short range/model), file, prediction column
    ("persistence", "Persistence (no change)", "baseline", "model_10 days/persistence/reports/initial/model_predictions.csv", "persistence"),
    ("climatology", "Climatology (normal year)", "baseline", "model_10 days/climatology/reports/initial/model_predictions.csv", "climatology"),
    ("gradient_boosting", "Gradient boosting", "statistical", "model_10 days/gradient_boosting/reports/initial/model_predictions.csv", "gradient_boosting"),
    ("lstm", "Original LSTM", "ai", "model_10 days/lstm/reports/initial/model_predictions.csv", "LSTM"),
    ("lstm_two_input", "Two-input LSTM", "ai", "model_10 days/lstm_two_input_scratch/reports/initial/predictions.csv", "scratch"),
    ("lstm_past_flow", "Past-flow + weather LSTM", "ai", "model_10 days/lstm_past_discharge_weather/reports/initial/predictions.csv", "Matched_LSTM"),
    ("lstm_boost_ensemble", "LSTM + boosting ensemble", "ai", "model_10 days/ensemble/reports/initial/model_predictions.csv", "Ensemble"),
    ("multibasin_lstm", "8-basin pretrained LSTM", "ai", "model_10 days/pretrained_multibasin_lstm_finetuned/reports/initial/predictions.csv", "finetuned"),
    ("global_lstm", "Global pretrained LSTM", "ai", "model_10 days/fine_tuned_global_pretrained_lstm/reports/initial/predictions.csv", "Global_finetuned"),
    ("seq2seq_15", "Seq2seq LSTM (15-day)", "ai", "model_15 days/encoder_decoder_lstm/reports/initial/predictions.csv.gz", "scratch"),
    ("seq2seq_15_ft", "Seq2seq LSTM fine-tuned (15-day)", "ai", "model_15 days/encoder_decoder_lstm_finetuned/reports/initial/predictions.csv.gz", "finetuned"),
    ("seq2seq_30", "Seq2seq LSTM ensemble (30-day)", "ai", "model_30_days/Encoder-decoder LSTM/finetuned_15_to_30/reports/initial/predictions.csv", "Seq2seq_30d_ensemble"),
    ("hf_lstm_30", "Weather-only LSTM (30-day)", "ai", "model_30_days/Hindcast-forecast LSTM/scratch/reports/initial/predictions.csv", "LSTM_30d"),
    ("hf_lstm_pastq_30", "Past-flow LSTM (30-day)", "ai", "model_30_days/Hindcast-forecast LSTM/past_discharge/reports/initial/predictions.csv", "LSTM_30d_pastQ"),
    ("clim_residual_30", "Climatology-residual LSTM ensemble", "ai", "model_30_days/Hindcast-forecast LSTM/climatology_residual_ensemble/reports/initial/predictions.csv", "Residual_ensemble"),
    ("catchment_lstm_30", "Catchment-mean LSTM", "ai", "model_30_days/Spatial elevation-band LSTM/reports/initial/control_predictions.csv", "CatchmentMean_Control"),
    ("elevation_lstm_30", "Elevation-band LSTM", "ai", "model_30_days/Spatial elevation-band LSTM/reports/initial/predictions.csv", "Spatial_ElevationBand"),
    ("nhits_30", "N-HiTS", "ai", "model_30_days/N-HiTS/reports/initial/predictions.csv", "NHiTS"),
    ("nbeatsx_30", "N-BEATSx", "ai", "model_30_days/N-BEATSx/reports/initial/predictions.csv", "NBEATSx"),
    ("hbv", "Calibrated HBV", "physics", "model_30_days/HBV hybrids/calibrated-physical-HBV/reports/initial/predictions.csv", "Calibrated_HBV"),
    ("delta_hbv", "Differentiable HBV (δHBV)", "hybrid", "model_30_days/HBV hybrids/delta-HBV/reports/initial/predictions.csv", "delta_HBV"),
    ("hbv_lstm", "HBV + LSTM correction", "hybrid", "model_30_days/HBV hybrids/HBV-LSTM-residual/reports/initial/predictions.csv", "HBV_LSTM"),
    ("hbv_lightgbm", "HBV + LightGBM correction", "hybrid", "model_30_days/HBV hybrids/HBV-LightGBM-residual/reports/initial/predictions.csv", "HBV_LightGBM"),
    ("snow_bucket_lstm", "Snow-bucket + LSTM", "hybrid", "model_10 days/hybrid_physics_ml/reports/initial/predictions.csv", "Hybrid"),
]
REPLAY_LEADS = (1, 3, 5, 7, 10, 15, 20, 30)
HIGH_FLOW_Q95 = 2494.714185  # observed 2016-2020 Q95, the threshold every short-range comparison uses


def replay_block(short_model_dir: Path) -> dict:
    frames, models = [], []
    for model_id, label, family, rel, col in SHORT_MODELS:
        df = pd.read_csv(short_model_dir / rel, usecols=["issue_date", "target_date", "lead_day", "observed_cumecs", col])
        df = df.rename(columns={col: "pred"}).assign(model=model_id)
        frames.append(df)
        models.append({"id": model_id, "label": label, "family": family, "max_lead": int(df["lead_day"].max()),
                       "source": rel.split("/reports/")[0]})
    allp = pd.concat(frames, ignore_index=True)
    allp["target_date"] = pd.to_datetime(allp["target_date"])
    obs = allp.dropna(subset=["observed_cumecs"]).drop_duplicates("target_date").set_index("target_date")["observed_cumecs"].sort_index()

    events = []
    for year in sorted(obs.index.year.unique()):
        s = obs[obs.index.year == year]
        if s.max() < HIGH_FLOW_Q95:
            continue
        peak = s.idxmax()
        start, end = peak - pd.Timedelta(days=35), peak + pd.Timedelta(days=25)
        events.append({"id": str(year), "label": f"{peak.strftime('%B %Y')} high flow", "peak_date": peak.date().isoformat(),
                       "peak": _r(s.max(), 0), "start": start.date().isoformat(), "end": end.date().isoformat(),
                       "high_flow_days": int((s.loc[start:end] > HIGH_FLOW_Q95).sum()),
                       "observed": [{"date": d.date().isoformat(), "v": _r(obs.get(d))} for d in pd.date_range(start, end)]})

    def skill(sub: pd.DataFrame) -> dict:
        o, p = sub["observed_cumecs"].to_numpy(), sub["pred"].to_numpy()
        hit = ((o > HIGH_FLOW_Q95) & (p > HIGH_FLOW_Q95)).sum()
        miss = ((o > HIGH_FLOW_Q95) & (p <= HIGH_FLOW_Q95)).sum()
        false = ((o <= HIGH_FLOW_Q95) & (p > HIGH_FLOW_Q95)).sum()
        return {"n": int(len(o)), "rmse": _r(np.sqrt(np.mean((p - o) ** 2)), 0),
                "nse": _r(1 - np.sum((p - o) ** 2) / np.sum((o - o.mean()) ** 2), 3),
                "hit_rate": _r(hit / (hit + miss), 3) if hit + miss else None,
                "false_alarm_ratio": _r(false / (hit + false), 3) if hit + false else None,
                "csi": _r(hit / (hit + miss + false), 3) if hit + miss + false else None}

    scores, series = {}, {}
    for lead in REPLAY_LEADS:
        at = allp.loc[allp["lead_day"].eq(lead)].dropna(subset=["observed_cumecs", "pred"])
        if at.empty:
            continue
        # Score every model on the same (issue, target) pairs: those all models with this lead share.
        keys = at.groupby("model")["target_date"].apply(set)
        common = set.intersection(*keys.tolist())
        matched = at.loc[at["target_date"].isin(common)]
        scores[str(lead)] = {"pairs": len(common), "models": {m: skill(g) for m, g in matched.groupby("model")}}
        for ev in events:
            window = at.loc[at["target_date"].between(ev["start"], ev["end"])]
            for m, g in window.groupby("model"):
                g = g.set_index("target_date")["pred"]
                peak_pred = g.max()
                series.setdefault(ev["id"], {}).setdefault(str(lead), {})[m] = {
                    "values": [_r(g.get(d)) for d in pd.date_range(ev["start"], ev["end"])],
                    "peak": _r(peak_pred, 0), "peak_error_pct": _r((peak_pred / ev["peak"] - 1) * 100),
                    "peak_date": g.idxmax().date().isoformat(),
                    "days_above": int((g > HIGH_FLOW_Q95).sum()),
                }
    return {
        "threshold": HIGH_FLOW_Q95,
        "threshold_label": "High-flow level (top 5% of 2016–2020 flows)",
        "test_period": "Forecasts issued 31 Dec 2021 – 2024, never seen in training",
        "weather_caveat": "These replays fed the models the weather that actually happened (reanalysis) in place of a weather forecast, so they show the best these models can do, not live accuracy.",
        "leads": [int(k) for k in scores],
        "models": models, "events": events, "scores": scores, "series": series,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="flood_model project root")
    args = parser.parse_args()
    riv = args.source / "riverine flood"
    long_model = riv / "long range" / "model"

    runner = TftRunner(long_model)
    payload = {
        "station": {"id": "MARALA", "name": "Marala", "river": "Chenab", "latitude": 32.675, "longitude": 74.425},
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "flood_classes_cumecs": {k: round(v * CUSECS_TO_CUMECS, 1) for k, v in FLOOD_CLASSES_CUSECS.items()},
        "flood_classes_cusecs": FLOOD_CLASSES_CUSECS,
        "flood_class_source": "https://ffd.pmd.gov.pk/flood-limits",
        "seasonal": tft_block(runner),
        "seasonal_means": ridge_block(runner, riv / "short range" / "seasonal" / "Observed_residual_Ridge"),
        "climate": projection_block(long_model / "projection" / "outputs"),
        "peak_model": peak_block(long_model / "extremes" / "reports"),
        "evidence": evidence_block(long_model, riv / "short range" / "seasonal" / "Observed_residual_Ridge" / "reports"),
        "replay": replay_block(riv / "short range" / "model"),
        "ten_day_research": ten_day_block(riv / "short range" / "evaluation comparison" / "flood_nonflood_2026-11-02_with_nhits_nbeatsx"),
        "weights_sha256": {p.name: _sha(p)[:16] for p in sorted((LONG_COPY / "tft" / "runs").glob("forecast_seed*_finetuned.pt"))},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":"), default=str) + "\n", encoding="utf-8")
    s = payload["seasonal"]
    print(f"TFT issue {s['issue_date']}: mean P50 {s['mean_p50']} vs normal {s['mean_normal_p50']} m3/s; "
          f"track record {s['track_record']['share_inside_band']} inside band")
    for h in payload["seasonal_means"]["horizons"]:
        print(f"Ridge {h['horizon_days']}d mean {h['mean_flow']} vs normal {h['normal_mean_flow']} ({h['change_vs_normal_pct']}%)")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
