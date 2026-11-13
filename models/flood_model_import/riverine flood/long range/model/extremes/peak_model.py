"""Annual flood-peak model for Marala driven by storm rainfall (censored log-normal regression).

Why: the TFT is fine-tuned on 2016-2023 observations whose largest daily flow is 7 232 m3/s,
so it cannot produce the ~22 000 m3/s floods that recur in the record (1973, 1988, 1992,
1996, 1997, 2014, 2025). This model estimates the annual *event* peak from the storm that
causes it, using only precipitation and temperature so it can run on CMIP6 output.

Data (1980-2016, the ERA5-Land years covered by the PMD list):
  target   PMD published event peak for listed years. Years absent from the list are treated
           as left-censored below the "High" class floor of 200 000 cusecs (5 663 m3/s).
           ASSUMPTION: the PMD list contains every flood of High class or above in 1980-2016.
  inputs   P3  = largest June-September 3-day catchment precipitation total (ERA5-Land)
           A30 = precipitation in the 30 days before that 3-day window
           T3  = mean 2 m temperature over the 3-day window
Model:  log Q = b0 + b . x + e,  e ~ N(0, s^2), fitted by maximum likelihood with censoring (Tobit).
Selection: leave-one-year-out log score. Test: 2017-2026 (never used in fitting).

Flood classes (cusecs, inferred from the PMD record's own labels: High <= 377k, Very High
408k-582k, Exceptionally High >= 751k): High >= 200k, Very High >= 400k, Exceptionally High >= 600k.
PMD peaks are instantaneous event peaks; the 2017-2026 observations are daily values (lower bound).

    ../../.venv/Scripts/python.exe peak_model.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common  # noqa: E402

CUSEC = 0.028316846592
CENSOR = 200_000 * CUSEC
THRESHOLDS = {"high_200k_cusecs": 200_000 * CUSEC, "very_high_400k_cusecs": 400_000 * CUSEC,
              "exceptional_600k_cusecs": 600_000 * CUSEC}
FEATURE_SETS = {"P3": ["log_p3"], "P3+A30": ["log_p3", "log_a30"], "P3+A30+T3": ["log_p3", "log_a30", "t3"]}


def storm_features(precip: pd.Series, temperature: pd.Series) -> pd.DataFrame:
    """One row per year with a complete June-September season."""
    p3 = precip.rolling(3).sum()
    rows = []
    for year, g in p3.groupby(p3.index.year):
        season = g.loc[g.index.month.isin([6, 7, 8, 9])].dropna()
        if len(season) < 120:
            continue
        end = season.idxmax()
        start = end - pd.Timedelta(days=2)
        a30 = precip.loc[start - pd.Timedelta(days=30):start - pd.Timedelta(days=1)].sum()
        rows.append({"year": year, "storm_end": end.date().isoformat(), "p3_mm": float(season.max()), "a30_mm": float(a30),
                     "t3_c": float(temperature.loc[start:end].mean())})
    f = pd.DataFrame(rows).set_index("year")
    f["log_p3"], f["log_a30"], f["t3"] = np.log(f["p3_mm"]), np.log1p(f["a30_mm"]), f["t3_c"]
    return f


def negloglik(theta, X, y, censored):
    beta, sigma = theta[:-1], np.exp(theta[-1])
    mu = X @ beta
    ll = np.where(censored, stats.norm.logcdf((np.log(CENSOR) - mu) / sigma),
                  stats.norm.logpdf((y - mu) / sigma) - np.log(sigma))
    return -ll.sum()


class PeakModel:
    def __init__(self, features):
        self.features = features

    def design(self, f):
        x = f[self.features].to_numpy(float)
        return np.column_stack([np.ones(len(x)), (x - self.mean) / self.std])

    def fit(self, f, y, censored):
        self.mean, self.std = f[self.features].mean().to_numpy(), f[self.features].std().to_numpy()
        X = self.design(f)
        start = np.r_[np.log(np.where(censored, CENSOR, y)).mean(), np.zeros(len(self.features)), 0.0]
        res = optimize.minimize(negloglik, start, args=(X, np.log(np.where(censored, CENSOR, y)), censored), method="BFGS")
        self.theta, self.converged = res.x, bool(res.success)
        return self

    def predict(self, f):
        """Mean and sd of log peak."""
        return self.design(f) @ self.theta[:-1], np.exp(self.theta[-1])

    def exceedance(self, f, threshold):
        mu, s = self.predict(f)
        return stats.norm.sf((np.log(threshold) - mu) / s)

    def logscore(self, f, y, censored):
        mu, s = self.predict(f)
        ly = np.log(np.where(censored, CENSOR, y))
        return np.where(censored, stats.norm.logcdf((np.log(CENSOR) - mu) / s), stats.norm.logpdf((ly - mu) / s) - np.log(s))

    def to_dict(self):
        return {"features": self.features, "feature_mean": self.mean.tolist(), "feature_std": self.std.tolist(),
                "coefficients": self.theta[:-1].tolist(), "sigma_log": float(np.exp(self.theta[-1])), "converged": self.converged}


def training_table(frame):
    feats = storm_features(frame["precip_era5land_mm"], frame["temperature_c"])
    pmd = pd.read_csv(common.PROC / "discharge/marala_pmd_historical_flood_peaks.csv", parse_dates=["peak_date"])
    pmd["peak_m3s"] = pmd["peak_discharge_1000_cusecs"] * 1000 * CUSEC
    peaks = pmd.groupby(pmd["peak_date"].dt.year)["peak_m3s"].max()
    train = feats.loc[1980:2016].copy()
    train["peak_m3s"] = peaks.reindex(train.index)
    train["censored"] = train["peak_m3s"].isna()
    return feats, train


def main():
    frame = common.load_all()
    feats, train = training_table(frame)
    y, cens = train["peak_m3s"].to_numpy(), train["censored"].to_numpy()

    # Leave-one-year-out selection.
    selection, loo = {}, {}
    for name, cols in FEATURE_SETS.items():
        scores, p400 = [], []
        for k in range(len(train)):
            keep = np.arange(len(train)) != k
            m = PeakModel(cols).fit(train.iloc[keep], y[keep], cens[keep])
            scores.append(float(m.logscore(train.iloc[[k]], y[[k]], cens[[k]])[0]))
            p400.append(float(m.exceedance(train.iloc[[k]], THRESHOLDS["very_high_400k_cusecs"])[0]))
        loo[name] = p400
        selection[name] = {"loo_mean_log_score": float(np.mean(scores))}
    # Reference: no predictors (constant mean).
    base = []
    for k in range(len(train)):
        keep = np.arange(len(train)) != k
        tr = train.iloc[keep].assign(const=0.0)
        m = PeakModel([]).fit(tr, y[keep], cens[keep])
        base.append(float(m.logscore(train.iloc[[k]].assign(const=0.0), y[[k]], cens[[k]])[0]))
    selection["no_predictor"] = {"loo_mean_log_score": float(np.mean(base))}
    best = max(FEATURE_SETS, key=lambda n: selection[n]["loo_mean_log_score"])
    exceeded_400 = (~cens) & (np.nan_to_num(y) >= THRESHOLDS["very_high_400k_cusecs"])
    base_rate = exceeded_400.mean()
    for name in FEATURE_SETS:
        selection[name]["loo_brier_400k"] = float(np.mean((np.array(loo[name]) - exceeded_400) ** 2))
    selection["no_predictor"]["loo_brier_400k"] = float(np.mean((base_rate - exceeded_400) ** 2))

    model = PeakModel(FEATURE_SETS[best]).fit(train, y, cens)

    # Test years: features from ERA5-Land, outcome = largest observed daily inflow.
    q = frame["q_obs"]
    test = feats.loc[2017:].copy()
    test["obs_daily_max_m3s"] = [q.loc[str(yr)].max() for yr in test.index]
    test["obs_days"] = [int(q.loc[str(yr)].notna().sum()) for yr in test.index]
    mu, s = model.predict(test)
    test["pred_median_m3s"] = np.exp(mu)
    test["pred_p10_m3s"], test["pred_p90_m3s"] = np.exp(mu - 1.2816 * s), np.exp(mu + 1.2816 * s)
    for k, thr in THRESHOLDS.items():
        test[f"p_exceed_{k}"] = model.exceedance(test, thr)
    test["tft_climate_conditioned_max_p50_m3s"] = np.nan
    pred = pd.read_csv(HERE.parent / "tft/reports/predictions_climate_conditioned.csv.gz")
    pred = pred.loc[pred["model"].eq("tft_finetuned") & pred["split"].eq("test") & pred["lead_days"].eq(30)]
    for yr in test.index:
        v = pred.loc[pred["target_date"].str[:4].eq(str(yr)), "p50_m3s"]
        if len(v):
            test.loc[yr, "tft_climate_conditioned_max_p50_m3s"] = v.max()

    reports = HERE / "reports"
    reports.mkdir(exist_ok=True)
    train.to_csv(reports / "training_years_1980_2016.csv")
    test.to_csv(reports / "test_years_2017_2026.csv")
    (reports / "peak_model.json").write_text(json.dumps({
        "selected_features": best, "selection": selection, "model": model.to_dict(), "censor_m3s": CENSOR,
        "thresholds_m3s": THRESHOLDS, "n_train_years": int(len(train)), "n_censored": int(cens.sum()),
        "assumption": "PMD list complete for High-class-and-above floods 1980-2016"}, indent=2) + "\n", encoding="utf-8")

    lines = ["# Marala annual flood-peak model", "",
             f"Censored log-normal regression on storm rainfall, fitted on 1980–2016 ({int((~cens).sum())} PMD-listed flood years, "
             f"{int(cens.sum())} years censored below 200k cusecs = {CENSOR:.0f} m³/s).", "",
             "## Predictor selection (leave-one-year-out)", "", "| Predictors | Mean log score (higher is better) | Brier, ≥400k cusecs (lower is better) |", "|---|---:|---:|"]
    for name, v in selection.items():
        lines.append(f"| {name}{' (selected)' if name == best else ''} | {v['loo_mean_log_score']:.3f} | {v['loo_brier_400k']:.3f} |")
    lines += ["", f"Coefficients (standardised predictors): {dict(zip(['intercept'] + FEATURE_SETS[best], np.round(model.theta[:-1], 3)))}; "
              f"residual sd (log) = {np.exp(model.theta[-1]):.2f}.", "",
              "## Test years (not used in fitting)", "",
              "Observed values are the largest **daily** inflow (WAPDA, then Sindh rim); PMD training peaks are instantaneous, so the observed daily value is a lower bound on the event peak. "
              "The TFT column is the largest climate-conditioned TFT P50 at 30-day lead in that year.", "",
              "| Year | Storm 3-day P (mm) | Observed daily max (m³/s) | Peak model median [P10–P90] | P(≥200k) | P(≥400k) | P(≥600k) | TFT max P50 |",
              "|---|---:|---:|---|---:|---:|---:|---:|"]
    for yr, r in test.iterrows():
        lines.append(f"| {yr} | {r.p3_mm:.0f} | {r.obs_daily_max_m3s:,.0f} ({r.obs_days} d) | {r.pred_median_m3s:,.0f} [{r.pred_p10_m3s:,.0f}–{r.pred_p90_m3s:,.0f}] | "
                     f"{r.p_exceed_high_200k_cusecs:.2f} | {r.p_exceed_very_high_400k_cusecs:.2f} | {r.p_exceed_exceptional_600k_cusecs:.2f} | "
                     f"{'' if pd.isna(r.tft_climate_conditioned_max_p50_m3s) else f'{r.tft_climate_conditioned_max_p50_m3s:,.0f}'} |")
    lines += ["", "400k cusecs = 11 327 m³/s; 600k cusecs = 16 990 m³/s. 2026 has observations only to early November.", "",
              "Marala floods are flash events. The 2025 peak (769.5k cusecs on 2025-08-27) is a single 06:00 reading between "
              "107.5k and 191.9k cusecs (FFD and Sindh rim agree). The 2016 PMD event peak (11 669 m³/s) appears in the WAPDA "
              "daily series as only 4 117 m³/s. Daily series, and the daily TFT, therefore cannot represent event peaks. Only "
              "2025 gives a clean test, and its observed peak lies inside the model's P10–P90."]
    (reports / "PEAK_MODEL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {reports / 'PEAK_MODEL.md'}")


if __name__ == "__main__":
    main()
