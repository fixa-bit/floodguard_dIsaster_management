"""Marala 2026-2040 river-flow projections from NEX-GDDP-CMIP6.

Chain per GCM and experiment:
  1. Bias-correct catchment pr/tas to ERA5-Land (reference 1985-2014), per calendar month:
     historical -> quantile mapping; ssp245/ssp585 (2024-2040) -> quantile delta mapping
     (Cannon et al. 2015; multiplicative for precipitation, additive for temperature).
  2. Daily flow: projection-mode TFT (P and T only, no discharge history), mean of 3 seeds,
     180-day windows issued every 30 days and averaged where they overlap; P10/P90 widened
     with the deployment conformal offsets (calibration/reports/conformal_offsets_deployment.csv).
  3. Annual flood-peak probabilities: storm-rainfall peak model (extremes/peak_model.py).
  4. Period statistics for 2026-2030, 2031-2035, 2036-2040 against the same GCM's
     1986-2014 run (delta approach), plus an ERA5-Land-forced 1986-2014 run as a check of step 1.

These are scenario projections of period statistics, not forecasts of particular days.

    ../../.venv/Scripts/python.exe run_projection.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import torch  # noqa: E402
import yaml  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL_DIR = HERE.parent
sys.path.insert(0, str(MODEL_DIR))
sys.path.insert(0, str(MODEL_DIR / "tft"))
sys.path.insert(0, str(MODEL_DIR / "extremes"))
import common  # noqa: E402
from train import Batcher, OBSERVED  # noqa: E402
from tft import TemporalFusionTransformer  # noqa: E402
import peak_model as pm  # noqa: E402

CMIP6 = common.LONG / "dataset" / "nex_gddp_cmip6_marala"
REF_YEARS = (1985, 2014)
REPORT_REF = (1986, 2014)  # first year is TFT spin-up
PERIODS = {"2026-2030": (2026, 2030), "2031-2035": (2031, 2035), "2036-2040": (2036, 2040), "2026-2040": (2026, 2040)}
HIST_BLOCKS = [(1986, 1990), (1991, 1995), (1996, 2000), (2001, 2005), (2006, 2010)]  # 5-year noise floor
SCENARIOS = ["ssp245", "ssp585"]
PROBS = np.linspace(0, 1, 101)
STRIDE = 30


# ------------------------------------------------------------- bias correction
def _monthly(series, years):
    s = series.loc[str(years[0]):str(years[1])]
    return {m: s.loc[s.index.month == m].to_numpy() for m in range(1, 13)}


def _ecdf(values, sample):
    """Empirical CDF with random tie-breaking (fixed seed). Tied values such as runs of dry days are
    spread uniformly over their tie block, so a GCM with more dry days than the reference still maps
    onto the reference's light-rain quantiles instead of collapsing onto one value."""
    sample = np.sort(sample)
    left = np.searchsorted(sample, values, side="left")
    right = np.searchsorted(sample, values, side="right")
    jitter = np.random.default_rng(20261111).random(len(values))
    rank = np.where(right > left, left + jitter * (right - left), left)
    return np.clip(rank / len(sample), 0, 1)


PRECIP_OFFSET_MM = 1.0  # QDM ratio (x + c) / (q_hist + c): near-additive for drizzle, relative for heavy rain


def bias_correct(ref: pd.Series, hist: pd.Series, target: pd.Series, kind: str, mode: str) -> pd.Series:
    """kind: 'precip' (multiplicative) or 'temperature' (additive); mode: 'qm' for historical, 'qdm' for future.

    Precipitation QDM uses an offset ratio and is then rescaled per calendar month so that the change
    in the monthly mean equals the GCM's raw change (target window vs 1985-2014). ERA5-Land has rain
    on ~79 % of days and the GCMs on ~40 %; plain ratio QDM then inflates or even flips the GCM's own
    precipitation change (tested in test_bias_correction.py)."""
    ref_m, hist_m = _monthly(ref, REF_YEARS), _monthly(hist, REF_YEARS)
    out = pd.Series(np.nan, index=target.index)
    for m in range(1, 13):
        sel = target.index.month == m
        x = target.loc[sel].to_numpy()
        if mode == "qm":
            tau = _ecdf(x, hist_m[m])
            out.loc[sel] = np.quantile(ref_m[m], tau)
            continue
        tau = _ecdf(x, x)  # quantile of each value within the future window
        ref_q, hist_q = np.quantile(ref_m[m], tau), np.quantile(hist_m[m], tau)
        if kind == "precip":
            c = PRECIP_OFFSET_MM
            y = np.maximum(ref_q * (x + c) / (hist_q + c), 0)
            # Mean-change preservation: corrected-future / corrected-historical = raw-future / raw-historical.
            hist_corrected_mean = np.quantile(ref_m[m], _ecdf(hist_m[m], hist_m[m])).mean()
            raw_change = x.mean() / hist_m[m].mean() if hist_m[m].mean() > 0 else 1.0
            out.loc[sel] = y * (raw_change * hist_corrected_mean / y.mean()) if y.mean() > 0 else y
        else:
            out.loc[sel] = ref_q + (x - hist_q)
    if kind == "precip":
        out = out.clip(lower=0)
    return out


# ------------------------------------------------------------- TFT inference
class Runner:
    def __init__(self, device):
        cfg = yaml.safe_load((MODEL_DIR / "tft/config.yaml").read_text(encoding="utf-8"))
        self.cfg, self.mcfg, self.device = cfg, cfg["modes"]["projection"], device
        self.norm = json.loads((MODEL_DIR / "tft/runs/normalisation.json").read_text(encoding="utf-8"))
        self.models = []
        for seed in cfg["training"]["seeds"]:
            path = MODEL_DIR / f"tft/runs/projection_seed{seed}_finetuned.pt"
            self.models.append(path)
        self.net = None

    def arrays(self, p: pd.Series, t: pd.Series) -> dict:
        idx = p.index
        f = pd.DataFrame(np.nan, index=idx, columns=common.FORCING)
        f["precip_era5land_mm"], f["temperature_c"] = p.to_numpy(), t.to_numpy()
        for c in self.norm["log1p_vars"]:
            f[c] = np.log1p(f[c].clip(lower=0))
        z = (f - pd.Series(self.norm["forcing_mean"])) / pd.Series(self.norm["forcing_std"])
        doy = idx.day_of_year.to_numpy()
        nan = np.full(len(idx), np.nan, np.float32)
        return {"dates": idx, "forcing": z[common.FORCING].to_numpy(np.float32),
                "doy": np.stack([np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)], 1).astype(np.float32),
                "q": {"observed": nan, "glofas": nan}}

    @torch.no_grad()
    def run(self, p: pd.Series, t: pd.Series) -> pd.DataFrame:
        arr = self.arrays(p, t)
        Te, Td = self.cfg["encoder_days"], self.cfg["horizon_days"]
        n = len(arr["dates"])
        b = Batcher(arr, self.cfg, self.mcfg, "observed", OBSERVED, [str(arr["dates"][0].date()), str(arr["dates"][-1].date())], self.device)
        issues = np.arange(Te - 1, n - Td, STRIDE)
        if issues[-1] != n - Td - 1:
            issues = np.r_[issues, n - Td - 1]  # last window reaches the series end
        z_sum, count = np.zeros((n, 3)), np.zeros(n)
        for path in self.models:
            if self.net is None:
                self.net = TemporalFusionTransformer(b.n_past, b.n_future, 2, quantiles=self.cfg["quantiles"], **self.cfg["model"]).to(self.device)
            self.net.load_state_dict(torch.load(path, map_location=self.device))
            self.net.eval()
            for k in range(0, len(issues), 256):
                chunk = issues[k:k + 256]
                past, fut, static, _, _ = b(chunk)
                pred = self.net(past, fut, static)[0].cpu().numpy()
                for j, i in enumerate(chunk):
                    z_sum[i + 1:i + Td + 1] += np.sort(pred[j], axis=-1)
                    count[i + 1:i + Td + 1] += 1
        z = z_sum / np.maximum(count, 1)[:, None]
        q = np.expm1(z * self.norm["q_log_std"] + self.norm["q_log_mean"])
        q[count == 0] = np.nan
        return pd.DataFrame(q, index=arr["dates"], columns=["p10_m3s", "p50_m3s", "p90_m3s"])


def calibrate(daily: pd.DataFrame) -> pd.DataFrame:
    off = pd.read_csv(MODEL_DIR / "calibration/reports/conformal_offsets_deployment.csv")
    off = off.loc[off["mode"].eq("projection") & off["model"].eq("tft_finetuned")].set_index("stratum")
    season = np.where(daily.index.month.isin([6, 7, 8, 9]), "monsoon_JJAS", "other_months")
    key = pd.Series(season, index=daily.index) + "|lead_31_180"  # windows are averaged over leads; most days are lead > 30
    dl, du = key.map(off["delta_lower"]).to_numpy(), key.map(off["delta_upper"]).to_numpy()
    out = daily.copy()
    out["p10_m3s"] = np.expm1(np.log1p(daily["p10_m3s"]) - dl).clip(lower=0)
    out["p90_m3s"] = np.expm1(np.log1p(daily["p90_m3s"]) + du)
    return out


# ------------------------------------------------------------- statistics
def period_stats(daily, p, t, peaks, years):
    d = daily.loc[str(years[0]):str(years[1])]
    yrs = range(years[0], years[1] + 1)
    q = d["p50_m3s"]
    pk = peaks.loc[peaks.index.isin(yrs)]
    pp = p.loc[str(years[0]):str(years[1])]
    return {
        "mean_flow_m3s": q.mean(),
        "AMJ_snowmelt_mean_m3s": q.loc[q.index.month.isin([4, 5, 6])].mean(),
        "JAS_monsoon_mean_m3s": q.loc[q.index.month.isin([7, 8, 9])].mean(),
        "ONDJFM_low_flow_mean_m3s": q.loc[q.index.month.isin([10, 11, 12, 1, 2, 3])].mean(),
        "annual_max_daily_p50_m3s": q.groupby(q.index.year).max().mean(),
        "annual_max_daily_p90_m3s": d["p90_m3s"].groupby(d.index.year).max().mean(),
        "peak_model_median_event_peak_m3s": pk["median_peak_m3s"].mean(),
        "p_exceed_400k_per_year": pk["p_exceed_very_high_400k_cusecs"].mean(),
        "p_exceed_600k_per_year": pk["p_exceed_exceptional_600k_cusecs"].mean(),
        "storm_p3_mm": pk["p3_mm"].mean(),
        "annual_precip_mm": pp.groupby(pp.index.year).sum().mean(),
        "mean_temperature_c": t.loc[str(years[0]):str(years[1])].mean(),
    }


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    forcing = common.load_forcing()
    era_p, era_t = forcing["precip_era5land_mm"], forcing["temperature_c"]
    runner = Runner(device)

    # Peak model refitted exactly as in extremes/peak_model.py.
    _, train = pm.training_table(common.load_all())
    peak = pm.PeakModel(["log_p3"]).fit(train, train["peak_m3s"].to_numpy(), train["censored"].to_numpy())

    def peaks_for(p, t):
        f = pm.storm_features(p, t)
        mu, _ = peak.predict(f)
        f["median_peak_m3s"] = np.exp(mu)
        for k, thr in pm.THRESHOLDS.items():
            f[f"p_exceed_{k}"] = peak.exceedance(f, thr)
        return f

    receipt = json.loads((CMIP6 / "source_receipt.json").read_text(encoding="utf-8"))
    gcms = sorted({v["model"] for v in receipt["files"].values()})
    gcms = [g for g in gcms if all(f"{g}_{e}.csv" in receipt["files"] for e in ["historical", *SCENARIOS])]
    out_dir = HERE / "outputs"
    out_dir.mkdir(exist_ok=True)

    stats, daily_rows, bc_rows, peak_rows = [], [], [], []
    # ERA5-Land reference run (observed forcing) for the bias-correction check.
    ref_window = slice("1985-01-01", "2014-12-31")
    era_daily = calibrate(runner.run(era_p.loc[ref_window], era_t.loc[ref_window]))
    era_peaks = peaks_for(era_p.loc[ref_window], era_t.loc[ref_window])
    stats.append({"gcm": "ERA5-Land", "experiment": "reference", "period": "1986-2014",
                  **period_stats(era_daily, era_p, era_t, era_peaks, REPORT_REF)})
    daily_rows.append(era_daily.loc["1986":].assign(gcm="ERA5-Land", experiment="reference"))

    for gcm in gcms:
        load = lambda e: pd.read_csv(CMIP6 / f"{gcm}_{e}.csv", parse_dates=["date"]).set_index("date").asfreq("D")  # noqa: E731
        hist = load("historical")
        hp, ht = hist["pr_mm"], hist["tas_c"]
        bc_hp = bias_correct(era_p, hp, hp, "precip", "qm")
        bc_ht = bias_correct(era_t, ht, ht, "temperature", "qm")
        for name, raw, bc, ref in [("pr_mm", hp, bc_hp, era_p), ("tas_c", ht, bc_ht, era_t)]:
            r = ref.loc[ref_window]
            for m in range(1, 13):
                bc_rows.append({"gcm": gcm, "variable": name, "month": m, "era5land_mean": r[r.index.month == m].mean(),
                                "gcm_raw_mean": raw[raw.index.month == m].mean(), "gcm_corrected_mean": bc[bc.index.month == m].mean(),
                                "era5land_p99": r[r.index.month == m].quantile(0.99), "gcm_corrected_p99": bc[bc.index.month == m].quantile(0.99)})
        h_daily = calibrate(runner.run(bc_hp, bc_ht))
        h_peaks = peaks_for(bc_hp, bc_ht)
        stats.append({"gcm": gcm, "experiment": "historical", "period": "1986-2014",
                      **period_stats(h_daily, bc_hp, bc_ht, h_peaks, REPORT_REF)})
        daily_rows.append(h_daily.loc["1986":].assign(gcm=gcm, experiment="historical"))
        peak_rows.append(h_peaks.assign(gcm=gcm, experiment="historical"))
        for scen in SCENARIOS:
            fut = load(scen)
            fp = bias_correct(era_p, hp, fut["pr_mm"], "precip", "qdm")
            ft = bias_correct(era_t, ht, fut["tas_c"], "temperature", "qdm")
            f_daily = calibrate(runner.run(fp, ft))
            f_peaks = peaks_for(fp, ft)
            for period, years in PERIODS.items():
                stats.append({"gcm": gcm, "experiment": scen, "period": period, **period_stats(f_daily, fp, ft, f_peaks, years)})
            daily_rows.append(f_daily.loc["2026":].assign(gcm=gcm, experiment=scen))
            peak_rows.append(f_peaks.loc[2026:].assign(gcm=gcm, experiment=scen))
        print(f"projected {gcm}", flush=True)

    stats = pd.DataFrame(stats)
    stats.to_csv(out_dir / "period_statistics.csv", index=False)
    daily = pd.concat(daily_rows).rename_axis("date").reset_index()
    daily.to_csv(out_dir / "daily_flow_quantiles.csv.gz", index=False, compression="gzip", float_format="%.2f")
    pd.concat(peak_rows).rename_axis("year").reset_index().to_csv(out_dir / "annual_peak_probabilities.csv", index=False, float_format="%.4f")
    pd.DataFrame(bc_rows).to_csv(out_dir / "bias_correction_check.csv", index=False, float_format="%.3f")
    write_report(stats, pd.DataFrame(bc_rows), daily, gcms, out_dir)


def write_report(stats, bc, daily, gcms, out_dir):
    ref = stats.loc[stats["experiment"].eq("historical")].set_index("gcm")
    flow_vars = ["mean_flow_m3s", "AMJ_snowmelt_mean_m3s", "JAS_monsoon_mean_m3s", "ONDJFM_low_flow_mean_m3s",
                 "annual_max_daily_p50_m3s", "peak_model_median_event_peak_m3s", "storm_p3_mm", "annual_precip_mm"]
    rows = []
    for _, r in stats.loc[stats["experiment"].isin(SCENARIOS)].iterrows():
        h = ref.loc[r["gcm"]]
        row = {"gcm": r["gcm"], "experiment": r["experiment"], "period": r["period"]}
        for v in flow_vars:
            row[f"{v}_change_pct"] = 100 * (r[v] / h[v] - 1)
        row["temperature_change_c"] = r["mean_temperature_c"] - h["mean_temperature_c"]
        for v in ["p_exceed_400k_per_year", "p_exceed_600k_per_year"]:
            row[f"{v}_hist"], row[f"{v}_future"] = h[v], r[v]
        rows.append(row)
    change = pd.DataFrame(rows)
    change.to_csv(out_dir / "change_vs_gcm_historical.csv", index=False, float_format="%.3f")

    def ens(df, col, fmt="{:+.1f}"):
        return f"{fmt.format(df[col].median())} [{fmt.format(df[col].min())}, {fmt.format(df[col].max())}]"

    era = stats.loc[stats["gcm"].eq("ERA5-Land")].iloc[0]
    gh = stats.loc[stats["experiment"].eq("historical")]
    lines = ["# Marala river-flow projections, 2026–2040", "",
             f"NEX-GDDP-CMIP6, {len(gcms)} GCMs ({', '.join(gcms)}), SSP2-4.5 and SSP5-8.5. "
             "Values are **ensemble median [min, max] across GCMs** of the change relative to each GCM's own bias-corrected 1986–2014 run. "
             "Flows come from the projection-mode TFT (precipitation and temperature only), and event peaks from the storm-rainfall peak model.", "",
             "**Scenario projections of period statistics. They are not forecasts of particular days or years. Experimental.**", ""]
    for scen in SCENARIOS:
        lines += [f"## {scen.upper()}", "",
                  "| Period | ΔT (°C) | Δ annual P (%) | Δ mean flow (%) | Δ Apr–Jun flow (%) | Δ Jul–Sep flow (%) | Δ Oct–Mar flow (%) | Δ storm 3-day P (%) | Δ median event peak (%) | P(≥400k cusecs) per year: hist → future | P(≥600k) per year: hist → future |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for period in PERIODS:
            c = change.loc[change["experiment"].eq(scen) & change["period"].eq(period)]
            lines.append(f"| {period} | {ens(c, 'temperature_change_c', '{:+.2f}')} | {ens(c, 'annual_precip_mm_change_pct')} | {ens(c, 'mean_flow_m3s_change_pct')} | "
                         f"{ens(c, 'AMJ_snowmelt_mean_m3s_change_pct')} | {ens(c, 'JAS_monsoon_mean_m3s_change_pct')} | {ens(c, 'ONDJFM_low_flow_mean_m3s_change_pct')} | "
                         f"{ens(c, 'storm_p3_mm_change_pct')} | {ens(c, 'peak_model_median_event_peak_m3s_change_pct')} | "
                         f"{c['p_exceed_400k_per_year_hist'].median():.2f} → {ens(c, 'p_exceed_400k_per_year_future', '{:.2f}')} | "
                         f"{c['p_exceed_600k_per_year_hist'].median():.2f} → {ens(c, 'p_exceed_600k_per_year_future', '{:.2f}')} |")
        lines.append("")
    # Noise floor: how much 5-year statistics move between blocks of an unchanged (historical) climate.
    peaks = pd.read_csv(out_dir / "annual_peak_probabilities.csv")
    hp = peaks.loc[peaks["experiment"].eq("historical")]
    blocks = []
    for g, d in hp.groupby("gcm"):
        whole = d.loc[d["year"].between(*REPORT_REF), "p_exceed_very_high_400k_cusecs"].mean()
        for y0, y1 in HIST_BLOCKS:
            b = d.loc[d["year"].between(y0, y1)]
            blocks.append({"p400": b["p_exceed_very_high_400k_cusecs"].mean() - whole,
                           "p3": 100 * (b["p3_mm"].mean() / d.loc[d["year"].between(*REPORT_REF), "p3_mm"].mean() - 1)})
    blocks = pd.DataFrame(blocks)
    dfl = daily.loc[daily["experiment"].eq("historical")].copy()
    dfl["year"] = pd.to_datetime(dfl["date"]).dt.year
    fl = []
    for g, d in dfl.groupby("gcm"):
        whole = d.loc[d["year"].between(*REPORT_REF), "p50_m3s"].mean()
        fl += [100 * (d.loc[d["year"].between(y0, y1), "p50_m3s"].mean() / whole - 1) for y0, y1 in HIST_BLOCKS]
    lines += ["## How large is natural 5-year variability?", "",
              "Spread of 5-year block statistics inside the bias-corrected **historical** runs (1986–2010 blocks against each GCM's 1986–2014 mean, "
              f"{len(blocks)} block × GCM samples). Climate does not change there, so this is the noise floor for one 5-year period of one GCM.", "",
              "| Statistic | 5–95 % range of block departures |", "|---|---|",
              f"| Mean flow | {np.percentile(fl, 5):+.1f} % to {np.percentile(fl, 95):+.1f} % |",
              f"| Storm 3-day precipitation | {blocks['p3'].quantile(.05):+.1f} % to {blocks['p3'].quantile(.95):+.1f} % |",
              f"| P(≥400k cusecs) per year | {blocks['p400'].quantile(.05):+.2f} to {blocks['p400'].quantile(.95):+.2f} |", "",
              "The ensemble median averages 8 GCMs, which narrows this noise, but changes in storm rainfall and flood probability for single 5-year periods "
              "are mostly within it. Use the pooled **2026–2040** row for extremes.", ""]
    lines += ["## Reference period check (1986–2014)", "",
              "The same TFT and peak model forced with ERA5-Land, and with each bias-corrected GCM historical run. "
              "If bias correction works, the GCM-forced statistics should be close to the ERA5-Land-forced ones.", "",
              "| Statistic | ERA5-Land forced | Bias-corrected GCMs: median [min, max] |", "|---|---:|---|"]
    for v in ["mean_flow_m3s", "AMJ_snowmelt_mean_m3s", "JAS_monsoon_mean_m3s", "ONDJFM_low_flow_mean_m3s", "annual_max_daily_p50_m3s",
              "peak_model_median_event_peak_m3s", "p_exceed_400k_per_year", "annual_precip_mm", "mean_temperature_c"]:
        lines.append(f"| {v} | {era[v]:,.2f} | {gh[v].median():,.2f} [{gh[v].min():,.2f}, {gh[v].max():,.2f}] |")
    worst = bc.assign(err=lambda d: (d.gcm_corrected_mean - d.era5land_mean).abs()).groupby("variable")["err"].max()
    lines += ["", f"Largest monthly-mean difference after bias correction (any GCM, 1985–2014): precipitation {worst.get('pr_mm', np.nan):.2f} mm/day, "
              f"temperature {worst.get('tas_c', np.nan):.2f} °C (`bias_correction_check.csv`).", "",
              "## Limits", "",
              "- The TFT was fine-tuned on 2016–2023 observations. Inputs outside that climate (for example warmer springs) are extrapolation.",
              "- Daily TFT flows do not contain flash-flood peaks. Event peaks come only from the peak model, which assumes the PMD list is complete for High-class floods (1980–2016).",
              "- Regulation (Indian run-of-river operations, possible new storage, treaty status) is not modelled. Flows are as-if-unregulated upstream of Marala.",
              "- Glacier retreat is not modelled explicitly. The TFT can only represent melt responses seen in 1980–2023.",
              "- For 2026–2040 the forced climate signal is small compared with internal variability, so read the range across GCMs, not a single number.",
              "- Bias correction keeps each GCM's monthly precipitation change but applies it to the ERA5-Land seasonal cycle. ERA5-Land puts about 33 % of the catchment's "
              "precipitation in January–March, against 20–23 % in the GCMs, so corrected annual changes differ from the raw GCM annual changes "
              "(for example NorESM2-MM, SSP2-4.5: raw −8.9 %, corrected about −1 %)."]
    (out_dir / "PROJECTIONS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Figures: annual mean flow by scenario; mean seasonal cycle by period.
    daily["date"] = pd.to_datetime(daily["date"])
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    ax = axes[0]
    era_mean = daily.loc[daily["gcm"].eq("ERA5-Land")].groupby(daily["date"].dt.year)["p50_m3s"].mean()
    ax.plot(era_mean.index, era_mean.values, color="black", lw=1.2, label="ERA5-Land forced (reference)")
    for scen, colour in (("historical", "grey"), ("ssp245", "tab:blue"), ("ssp585", "tab:red")):
        d = daily.loc[daily["experiment"].eq(scen)]
        ann = d.groupby([d["gcm"], d["date"].dt.year])["p50_m3s"].mean().unstack(0)
        ax.fill_between(ann.index, ann.min(axis=1), ann.max(axis=1), color=colour, alpha=0.2)
        ax.plot(ann.index, ann.median(axis=1), color=colour, lw=1.2, label=f"{scen} (GCM median, range)")
    ax.set_ylabel("annual mean flow P50 (m³/s)")
    ax.set_title("Marala annual mean flow")
    ax.legend(fontsize=8)
    ax = axes[1]
    for (label, sel, colour, ls) in [("GCM historical 1986–2014", daily["experiment"].eq("historical"), "grey", "-"),
                                     ("SSP2-4.5 2036–2040", daily["experiment"].eq("ssp245") & (daily["date"].dt.year >= 2036), "tab:blue", "-"),
                                     ("SSP5-8.5 2036–2040", daily["experiment"].eq("ssp585") & (daily["date"].dt.year >= 2036), "tab:red", "-"),
                                     ("ERA5-Land 1986–2014", daily["gcm"].eq("ERA5-Land"), "black", "--")]:
        d = daily.loc[sel]
        cyc = d.groupby(d["date"].dt.month)[["p10_m3s", "p50_m3s", "p90_m3s"]].mean()
        ax.plot(cyc.index, cyc["p50_m3s"], color=colour, ls=ls, label=label)
        if colour != "black":
            ax.fill_between(cyc.index, cyc["p10_m3s"], cyc["p90_m3s"], color=colour, alpha=0.08)
    ax.set_xticks(range(1, 13))
    ax.set_xlabel("month")
    ax.set_ylabel("mean flow (m³/s)")
    ax.set_title("Mean seasonal cycle (P50, band = mean P10–P90)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "projection_overview.png", dpi=130)
    print(f"wrote {out_dir / 'PROJECTIONS.md'}")


if __name__ == "__main__":
    main()
