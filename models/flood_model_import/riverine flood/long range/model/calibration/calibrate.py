"""Conformal calibration of the TFT P10-P90 interval (conformalized quantile regression, Romano et al. 2019).

Offsets are fitted on the 2022-2023 validation predictions only and checked on the
2024-2026 test. Scores are in log1p space, separately for the lower and upper bound,
per stratum = (season of target date: monsoon Jun-Sep / other) x (lead 1-30 / 31-180):

    s_lo = log1p(P10) - log1p(y)        s_hi = log1p(y) - log1p(P90)
    d_lo = Q_(1-a)(s_lo),  d_hi = Q_(1-a)(s_hi),  a = 0.10, finite-sample level ceil((n+1)(1-a))/n
    P10' = expm1(log1p(P10) - d_lo)     P90' = expm1(log1p(P90) + d_hi)

Negative offsets narrow an interval that was too wide. P50 is not changed.
Daily issues overlap, so validation scores are not exchangeable; the test coverage is
the real check.

    ../../.venv/Scripts/python.exe calibrate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common  # noqa: E402

ALPHA = 0.10
MODELS = ["tft_finetuned", "tft_scratch"]
LEAD_BINS = [(1, 30), (31, 180)]


def stratum(df):
    month = pd.to_datetime(df["target_date"]).dt.month
    season = np.where(month.between(6, 9), "monsoon_JJAS", "other_months")
    lead = np.where(df["lead_days"] <= LEAD_BINS[0][1], "lead_1_30", "lead_31_180")
    return pd.Series(season, index=df.index) + "|" + pd.Series(lead, index=df.index)


def conformal_quantile(scores, alpha=ALPHA):
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


def fit_offsets(val: pd.DataFrame) -> pd.DataFrame:
    v = val.loc[val["obs_m3s"].notna()].copy()
    v["stratum"] = stratum(v)
    ly = np.log1p(v["obs_m3s"])
    v["s_lo"] = np.log1p(v["p10_m3s"]) - ly
    v["s_hi"] = ly - np.log1p(v["p90_m3s"])
    rows = []
    for (mode, model, st), g in v.groupby(["mode", "model", "stratum"]):
        rows.append({"mode": mode, "model": model, "stratum": st, "n_val": len(g),
                     "delta_lower": conformal_quantile(g["s_lo"].to_numpy()),
                     "delta_upper": conformal_quantile(g["s_hi"].to_numpy())})
    return pd.DataFrame(rows)


def apply_offsets(df: pd.DataFrame, offsets: pd.DataFrame) -> pd.DataFrame:
    """Return df with p10_cal_m3s / p90_cal_m3s. Rows without an offset keep NaN."""
    out = df.copy()
    out["stratum"] = stratum(out)
    out = out.merge(offsets[["mode", "model", "stratum", "delta_lower", "delta_upper"]],
                    on=["mode", "model", "stratum"], how="left")
    out["p10_cal_m3s"] = np.expm1(np.log1p(out["p10_m3s"]) - out["delta_lower"]).clip(lower=0)
    out["p90_cal_m3s"] = np.expm1(np.log1p(out["p90_m3s"]) + out["delta_upper"])
    return out.drop(columns=["delta_lower", "delta_upper"])


def expanding_window(val: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    """Operational variant: offsets for issues in month M use validation pairs plus every test
    pair whose target date is before the first day of M (its outcome was already known)."""
    out = []
    test = test.copy()
    month = test["issue_date"].str[:7]
    for m in sorted(month.unique()):
        start = f"{m}-01"
        known = test.loc[test["target_date"] < start, val.columns]
        offsets = fit_offsets(pd.concat([val, known], ignore_index=True))
        out.append(apply_offsets(test.loc[month.eq(m), val.columns], offsets))
    return pd.concat(out, ignore_index=True)


def interval_score(y, lo, hi, alpha=0.2):
    """Winkler interval score for a (1-alpha) interval; lower is better."""
    return np.mean((hi - lo) + (2 / alpha) * (lo - y) * (y < lo) + (2 / alpha) * (y - hi) * (y > hi))


def main():
    files = sorted((HERE.parent / "tft/reports").glob("predictions_*.csv.gz"))
    pred = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    pred = pred.loc[pred["model"].isin(MODELS)]
    offsets = fit_offsets(pred.loc[pred["split"].eq("val")])
    reports = HERE / "reports"
    reports.mkdir(exist_ok=True)
    offsets.to_csv(reports / "conformal_offsets.csv", index=False)

    val = pred.loc[pred["split"].eq("val")]
    test_raw = pred.loc[pred["split"].eq("test") & pred["obs_m3s"].notna()]
    static = apply_offsets(test_raw, offsets).assign(method="static_val_2022_2023")
    rolling = expanding_window(val, test_raw).assign(method="expanding_window")
    # Deployment offsets for projections: every validation and test pair (2022-2026).
    fit_offsets(pd.concat([val, test_raw], ignore_index=True)).to_csv(reports / "conformal_offsets_deployment.csv", index=False)
    test = pd.concat([static, rolling], ignore_index=True)
    rows = []
    for (method, mode, model), g in test.groupby(["method", "mode", "model"]):
        for name, part in [("all", g), *[(s, gs) for s, gs in g.groupby("stratum")],
                           ("2024", g.loc[g["target_date"].str[:4].eq("2024")]),
                           ("2025-2026", g.loc[g["target_date"].str[:4].isin(["2025", "2026"])])]:
            y = part["obs_m3s"].to_numpy()
            raw_lo, raw_hi = part["p10_m3s"].to_numpy(), part["p90_m3s"].to_numpy()
            lo, hi = part["p10_cal_m3s"].to_numpy(), part["p90_cal_m3s"].to_numpy()
            rows.append({"method": method, "mode": mode, "model": model, "subset": name, "n": len(part),
                         "coverage_raw": float(np.mean((y >= raw_lo) & (y <= raw_hi))),
                         "coverage_calibrated": float(np.mean((y >= lo) & (y <= hi))),
                         "below_p10_calibrated": float(np.mean(y < lo)), "above_p90_calibrated": float(np.mean(y > hi)),
                         "median_width_raw_m3s": float(np.median(raw_hi - raw_lo)),
                         "median_width_calibrated_m3s": float(np.median(hi - lo)),
                         "interval_score_raw": float(interval_score(y, raw_lo, raw_hi)),
                         "interval_score_calibrated": float(interval_score(y, lo, hi))})
    summary = pd.DataFrame(rows)
    summary.to_csv(reports / "test_coverage.csv", index=False)

    lines = ["# Conformal calibration of the TFT P10–P90 interval", "",
             "`static_val_2022_2023`: offsets fitted once on 2022–2023 validation predictions (`conformal_offsets.csv`). "
             "`expanding_window`: offsets for each issue month refitted on validation plus all test pairs whose outcome was known before that month. "
             "Scored on the 2024–2026 test. `conformal_offsets_deployment.csv` (fitted on 2022–2026) is used for projections. "
             "Target coverage 0.80 (0.10 below P10, 0.10 above P90). Interval score: Winkler score, lower is better.", "",
             "| Method | Mode | Model | Subset | n | Coverage raw | Coverage calibrated | Below P10 | Above P90 | Median width raw → cal (m³/s) | Interval score raw → cal |",
             "|---|---|---|---|---:|---:|---:|---:|---:|---|---|"]
    for _, r in summary.iterrows():
        lines.append(f"| {r['method']} | {r['mode']} | {r['model']} | {r['subset']} | {r['n']} | {r.coverage_raw:.2f} | {r.coverage_calibrated:.2f} | "
                     f"{r.below_p10_calibrated:.2f} | {r.above_p90_calibrated:.2f} | {r.median_width_raw_m3s:.0f} → {r.median_width_calibrated_m3s:.0f} | "
                     f"{r.interval_score_raw:.0f} → {r.interval_score_calibrated:.0f} |")
    (reports / "CALIBRATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (reports / "run_report.json").write_text(json.dumps({
        "method": "split conformal (CQR), log1p space, asymmetric", "alpha": ALPHA, "fit_split": "val (2022-2023 targets)",
        "strata": "season(JJAS/other) x lead(1-30/31-180)", "inputs": [str(f.relative_to(common.LONG)).replace("\\", "/") for f in files]},
        indent=2) + "\n", encoding="utf-8")
    print(summary.loc[summary["subset"].isin(["all", "2024", "2025-2026"]),
                      ["method", "mode", "model", "subset", "coverage_raw", "coverage_calibrated", "interval_score_raw", "interval_score_calibrated"]].round(2).to_string())


if __name__ == "__main__":
    main()
