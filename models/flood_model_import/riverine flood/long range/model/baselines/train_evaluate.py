"""Reference baselines for the Marala long-range TFT (same issue rules, horizon and test period).

* climatology          - smoothed day-of-year mean of log1p(Q_obs), fitted on 2016-2023.
                         P10/P90 from monthly spread of log anomalies.
* damped_persistence   - climatology plus the issue-day log anomaly (7-day mean) decayed by a
                         per-lead coefficient fitted on 2016-2023 issues.
* glofas_raw           - simulated GloFAS v5 on the target date. It is driven by the actual
                         weather, so it is a reference for the climate-conditioned mode only.

    ../../.venv/Scripts/python.exe train_evaluate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common  # noqa: E402

Z90 = 1.2815515655446004


def main():
    cfg = yaml.safe_load((HERE.parent / "tft" / "config.yaml").read_text(encoding="utf-8"))
    Td, fit_years = cfg["horizon_days"], list(range(2016, 2024))
    frame = common.load_all()
    q = frame["q_obs"]
    dates = frame.index
    clim = common.doy_climatology(q, fit_years)
    log_clim = np.log1p(common.clim_for_dates(clim, dates))
    anomaly = pd.Series(np.log1p(q.to_numpy()) - log_clim, index=dates)
    anom7 = anomaly.rolling(7, min_periods=4).mean()

    # Spread of daily log anomalies by calendar month (fit years only) -> climatology P10/P90.
    fit = anomaly.loc[anomaly.index.year.isin(fit_years)].dropna()
    month_sd = fit.groupby(fit.index.month).std()

    def eligible(i, t0, t1):
        if i < 89 or np.isfinite(q.iloc[i - 89:i + 1]).mean() < cfg["min_past_obs_coverage_90d"]:
            return None
        fut = np.arange(i + 1, min(i + Td + 1, len(dates)))
        keep = (dates[fut] >= t0) & (dates[fut] <= t1) & q.iloc[fut].notna().to_numpy()
        return fut if keep.sum() >= cfg["min_valid_targets"] else None

    # Fit per-lead decay phi(h) and residual sd on 2016-2023 issues (regression through origin).
    a0s, futs = [], []
    t0, t1 = pd.Timestamp("2016-03-01"), pd.Timestamp("2023-12-31")
    for i in range(dates.searchsorted(t0), dates.searchsorted(t1)):
        fut = eligible(i, t0, t1)
        if fut is None or not np.isfinite(anom7.iloc[i]):
            continue
        a0s.append(anom7.iloc[i])
        futs.append(np.pad(anomaly.iloc[fut].to_numpy(), (0, Td - len(fut)), constant_values=np.nan))
    A0, FUT = np.asarray(a0s), np.vstack(futs)
    phi, resid_sd = np.zeros(Td), np.zeros(Td)
    for h in range(Td):
        ok = np.isfinite(FUT[:, h])
        phi[h] = np.sum(A0[ok] * FUT[ok, h]) / np.sum(A0[ok] ** 2)
        resid_sd[h] = np.std(FUT[ok, h] - phi[h] * A0[ok])

    rows = []
    split = cfg["finetune"]["test"]
    t0, t1 = (pd.Timestamp(d) for d in split["targets"])
    i_start = dates.searchsorted(pd.Timestamp(split["issues"][0]))
    for i in range(i_start, len(dates) - 1):
        fut = eligible(i, t0, t1)
        if fut is None:
            continue
        fut = fut[(dates[fut] >= t0) & (dates[fut] <= t1)]
        lead = fut - i
        base = {"split": "test", "issue_date": dates[i].date().isoformat(),
                "target_date": dates[fut].strftime("%Y-%m-%d"), "lead_days": lead,
                "obs_m3s": q.iloc[fut].to_numpy(), "obs_source": frame["q_obs_source"].iloc[fut].to_numpy()}
        lc = log_clim[fut]
        sd = month_sd.reindex(dates[fut].month).to_numpy()
        rows.append(pd.DataFrame({**base, "model": "climatology", "p50_m3s": np.expm1(lc),
                                  "p10_m3s": np.expm1(lc - Z90 * sd), "p90_m3s": np.expm1(lc + Z90 * sd)}))
        if np.isfinite(anom7.iloc[i]):
            mid = lc + phi[lead - 1] * anom7.iloc[i]
            s = resid_sd[lead - 1]
            rows.append(pd.DataFrame({**base, "model": "damped_persistence", "p50_m3s": np.expm1(mid),
                                      "p10_m3s": np.expm1(mid - Z90 * s), "p90_m3s": np.expm1(mid + Z90 * s)}))
        g = frame["q_glofas"].iloc[fut].to_numpy()
        rows.append(pd.DataFrame({**base, "model": "glofas_raw", "p50_m3s": g, "p10_m3s": np.nan, "p90_m3s": np.nan}))

    reports = HERE / "reports"
    reports.mkdir(exist_ok=True)
    pd.concat(rows, ignore_index=True).to_csv(reports / "predictions.csv.gz", index=False, compression="gzip")
    pd.DataFrame({"day_of_year": clim.index, "climatology_m3s": clim.to_numpy()}).to_csv(reports / "climatology_2016_2023.csv", index=False)
    pd.DataFrame({"lead_days": np.arange(1, Td + 1), "phi": phi, "residual_log_sd": resid_sd}).to_csv(
        reports / "damped_persistence_coefficients.csv", index=False)
    (reports / "run_report.json").write_text(json.dumps({
        "fit_years": fit_years, "persistence_fit_issues": int(len(A0)),
        "test_split": split, "data_provenance": common.provenance()}, indent=2) + "\n", encoding="utf-8")
    print(f"baseline predictions written; persistence fitted on {len(A0)} issues; phi(30)={phi[29]:.2f} phi(90)={phi[89]:.2f} phi(180)={phi[179]:.2f}")


if __name__ == "__main__":
    main()
