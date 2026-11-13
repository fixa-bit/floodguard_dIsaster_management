"""Score the TFT variants and baselines on identical (issue, target) pairs and write reports/COMPARISON.md.

    ../.venv/Scripts/python.exe compare.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import common  # noqa: E402

HERE = Path(__file__).resolve().parent
RIDGE = common.LONG.parent / "short range/seasonal/Observed_residual_Ridge/reports/heldout_2024_predictions.csv"
BUCKETS = [(1, 30), (31, 90), (91, 180), (1, 180)]
ORDER = ["climatology", "damped_persistence", "tft_scratch", "tft_pretrained_only", "tft_finetuned", "glofas_raw"]


def load():
    tft = pd.concat([pd.read_csv(f) for f in sorted((HERE / "tft/reports").glob("predictions_*.csv.gz"))])
    base = pd.read_csv(HERE / "baselines/reports/predictions.csv.gz")
    tft = tft.loc[tft["split"].eq("test")]
    frames = []
    for mode in tft["mode"].unique():
        models = ["climatology", "damped_persistence"] + (["glofas_raw"] if mode != "forecast" else [])
        frames.append(pd.concat([tft.loc[tft["mode"].eq(mode)], base.loc[base["model"].isin(models)].assign(mode=mode)]))
    df = pd.concat(frames, ignore_index=True)
    df = df.loc[df["obs_m3s"].notna()]
    # Keep only pairs every model in the mode has, so all scores use the same sample.
    key = ["mode", "issue_date", "target_date"]
    n_models = df.groupby("mode")["model"].nunique()
    counts = df.groupby(key)["model"].nunique().rename("k").reset_index()
    counts = counts.loc[counts["k"].eq(counts["mode"].map(n_models))]
    df = df.merge(counts[key], on=key)
    clim = df.loc[df["model"].eq("climatology"), key + ["p50_m3s"]].rename(columns={"p50_m3s": "clim_m3s"})
    return df.merge(clim, on=key)


def score_table(df):
    rows = []
    for (mode, model), g in df.groupby(["mode", "model"]):
        for lo, hi in BUCKETS:
            b = g.loc[g["lead_days"].between(lo, hi)]
            for period, p in [("all", b), ("2024", b.loc[b["target_date"].str[:4].eq("2024")]),
                              ("2025-2026", b.loc[b["target_date"].str[:4].isin(["2025", "2026"])])]:
                if len(p) < 10:
                    continue
                s = common.scores(p["obs_m3s"], p["p50_m3s"], p["clim_m3s"], p["p10_m3s"], p["p90_m3s"])
                rows.append({"mode": mode, "model": model, "leads": f"{lo}-{hi}", "target_period": period,
                             "issues": p["issue_date"].nunique(), **s})
    return pd.DataFrame(rows)


def seasonal_means(df):
    """Mean flow over the next 90/180 days for 1st-of-month issues (as in the seasonal Ridge study)."""
    rows = []
    first = df.loc[df["issue_date"].str[8:].eq("01")]
    for (mode, model, issue), g in first.groupby(["mode", "model", "issue_date"]):
        for h in (90, 180):
            w = g.loc[g["lead_days"] <= h]
            if len(w) >= 0.9 * h:
                rows.append({"mode": mode, "model": model, "issue_date": issue, "horizon_days": h,
                             "obs_mean": w["obs_m3s"].mean(), "pred_mean": w["p50_m3s"].mean(), "clim_mean": w["clim_m3s"].mean()})
    out = pd.DataFrame(rows)
    if RIDGE.exists():
        r = pd.read_csv(RIDGE)
        for mode in out["mode"].unique():
            out = pd.concat([out, pd.DataFrame({"mode": mode, "model": "seasonal_ridge (short range)", "issue_date": r["issue_date"],
                                                "horizon_days": r["horizon_days"], "obs_mean": r["observed_future_mean_q"],
                                                "pred_mean": r["ridge_residual_q"], "clim_mean": r["observed_climatology_q"]})])
    return out


def fmt(x, nd=2):
    return "" if pd.isna(x) else f"{x:.{nd}f}"


def main():
    df = load()
    reports = HERE / "reports"
    reports.mkdir(exist_ok=True)
    scores = score_table(df)
    scores.to_csv(reports / "scores_by_lead.csv", index=False)
    seas = seasonal_means(df)
    seas.to_csv(reports / "seasonal_mean_predictions.csv", index=False)

    lines = ["# Marala long-range comparison (held-out test, issues from 2024-01-01)", "",
             "All models in a mode are scored on the same (issue date, target date) pairs. "
             "Skill = 1 − RMSE / RMSE of observed day-of-year climatology (2016–2023). "
             "Point forecast = P50. Coverage = share of observations inside P10–P90 (ideal 0.80). "
             "Issues overlap (one per day), so pairs are not independent.", ""]
    for mode in scores["mode"].unique():
        s = scores.loc[scores["mode"].eq(mode) & scores["target_period"].eq("all")]
        lines += [f"## Mode: {mode}", "", "| Model | Leads (days) | Issues | NSE | KGE | RMSE m³/s | Skill vs clim | PBIAS % | P10–P90 coverage |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for model in [m for m in ORDER if m in s["model"].unique()]:
            for _, r in s.loc[s["model"].eq(model)].iterrows():
                lines.append(f"| {model} | {r['leads']} | {r['issues']} | {fmt(r['nse'])} | {fmt(r['kge'])} | {fmt(r['rmse'], 0)} | "
                             f"{fmt(r['rmse_skill_vs_climatology'])} | {fmt(r['pbias_pct'], 1)} | {fmt(r.get('p10_p90_coverage'))} |")
        lines += ["", "By target period, leads 1–180:", "", "| Model | Period | NSE | KGE | Skill vs clim |", "|---|---|---:|---:|---:|"]
        sp = scores.loc[scores["mode"].eq(mode) & scores["leads"].eq("1-180") & ~scores["target_period"].eq("all")]
        for model in [m for m in ORDER if m in sp["model"].unique()]:
            for _, r in sp.loc[sp["model"].eq(model)].iterrows():
                lines.append(f"| {model} | {r['target_period']} | {fmt(r['nse'])} | {fmt(r['kge'])} | {fmt(r['rmse_skill_vs_climatology'])} |")
        lines.append("")

    lines += ["## 90- and 180-day mean flow on the seasonal Ridge test dates", "",
              "Only the (issue date, horizon) pairs in the short-range seasonal Ridge 2024 test. Ridge values are read "
              "from its saved predictions and use its own month-of-issue climatology; the others use the day-of-year "
              "climatology. Compare skill, not RMSE, across those two groups. 9 and 7 issues only.", "",
              "| Mode | Model | Horizon | Issues | RMSE m³/s | Climatology RMSE | Skill |", "|---|---|---:|---:|---:|---:|---:|"]
    ridge_pairs = set(zip(seas.loc[seas["model"].str.startswith("seasonal_ridge"), "issue_date"],
                          seas.loc[seas["model"].str.startswith("seasonal_ridge"), "horizon_days"]))
    s24 = seas.loc[[p in ridge_pairs for p in zip(seas["issue_date"], seas["horizon_days"])]]
    for (mode, model, h), g in s24.groupby(["mode", "model", "horizon_days"]):
        rmse = np.sqrt(np.mean((g.pred_mean - g.obs_mean) ** 2))
        crmse = np.sqrt(np.mean((g.clim_mean - g.obs_mean) ** 2))
        lines.append(f"| {mode} | {model} | {h} | {len(g)} | {rmse:.0f} | {crmse:.0f} | {1 - rmse / crmse:+.2f} |")
    lines += ["", "## Flood peaks", "",
              "Largest observed daily inflow in each target year against the same model's P50 and P90 for that date, "
              "at fixed leads (one issue date per row).", "",
              "| Mode | Model | Year | Observed peak m³/s | Date | Lead | P50 | P90 |", "|---|---|---|---:|---|---:|---:|---:|"]
    for (mode, model), g in df.loc[df["model"].isin(["climatology", "tft_finetuned", "tft_scratch", "glofas_raw"])].groupby(["mode", "model"]):
        for year in ("2024", "2025"):
            y = g.loc[g["target_date"].str[:4].eq(year)]
            if y.empty:
                continue
            peak_day = y.loc[y["obs_m3s"].idxmax(), "target_date"]
            for lead in (30, 90, 180):
                r = y.loc[y["target_date"].eq(peak_day) & y["lead_days"].eq(lead)]
                if len(r):
                    r = r.iloc[0]
                    lines.append(f"| {mode} | {model} | {year} | {r.obs_m3s:.0f} | {peak_day} | {lead} | {r.p50_m3s:.0f} | {fmt(r.p90_m3s, 0)} |")
    (reports / "COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Figure: skill by lead (30-day bins) per mode.
    fig, axes = plt.subplots(1, df["mode"].nunique(), figsize=(12, 4), sharey=True, squeeze=False)
    for ax, mode in zip(axes[0], sorted(df["mode"].unique())):
        g = df.loc[df["mode"].eq(mode)].assign(bin=lambda d: (d["lead_days"] - 1) // 30)
        for model in [m for m in ORDER if m in g["model"].unique() and m != "climatology"]:
            sk = g.loc[g["model"].eq(model)].groupby("bin").apply(
                lambda b: 1 - np.sqrt(np.mean((b.p50_m3s - b.obs_m3s) ** 2)) / np.sqrt(np.mean((b.clim_m3s - b.obs_m3s) ** 2)),
                include_groups=False)
            ax.plot(sk.index * 30 + 15, sk.values, marker="o", label=model)
        ax.axhline(0, color="grey", lw=0.8)
        ax.set_title(mode)
        ax.set_xlabel("lead (days)")
    axes[0][0].set_ylabel("RMSE skill vs climatology")
    axes[0][-1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(reports / "skill_by_lead.png", dpi=130)

    # Figure: finetuned TFT P10-P90 at fixed leads along the test period.
    fig, axes = plt.subplots(df["mode"].nunique(), 1, figsize=(12, 7), squeeze=False)
    for ax, mode in zip(axes[:, 0], sorted(df["mode"].unique())):
        g = df.loc[df["mode"].eq(mode) & df["model"].eq("tft_finetuned")]
        obs = g.drop_duplicates("target_date").set_index("target_date")["obs_m3s"].sort_index()
        ax.plot(pd.to_datetime(obs.index), obs.values, color="black", lw=1, label="observed")
        for lead, colour in ((30, "tab:blue"), (90, "tab:orange"), (180, "tab:red")):
            l = g.loc[g["lead_days"].eq(lead)].sort_values("target_date")
            t = pd.to_datetime(l["target_date"])
            ax.plot(t, l["p50_m3s"], color=colour, lw=1, label=f"P50, lead {lead} d")
            ax.fill_between(t, l["p10_m3s"], l["p90_m3s"], color=colour, alpha=0.12)
        ax.set_title(f"TFT fine-tuned ({mode}) - held-out test")
        ax.set_ylabel("Marala inflow (m³/s)")
        ax.legend(fontsize=8, ncol=4)
    fig.tight_layout()
    fig.savefig(reports / "test_forecasts_by_lead.png", dpi=130)
    print(f"wrote {reports / 'COMPARISON.md'}")


if __name__ == "__main__":
    main()
