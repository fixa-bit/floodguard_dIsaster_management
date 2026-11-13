"""Lead-specific flow, event-peak, binary and probabilistic verification."""
from pathlib import Path
import numpy as np
import pandas as pd
from .physical import kge
from .data import save_json


def flow_metrics(obs, pred):
    good = np.isfinite(obs) & np.isfinite(pred)
    o, p = np.asarray(obs)[good], np.asarray(pred)[good]
    if not len(o):
        return {"n": 0, "kge": np.nan, "nse": np.nan, "mae_cumecs": np.nan}
    denom = np.sum((o - o.mean())**2)
    return {"n": len(o), "kge": kge(o, p),
            "nse": 1 - np.sum((o-p)**2) / denom if denom > 0 else np.nan,
            "mae_cumecs": float(np.abs(o-p).mean())}


def threshold_metrics(obs, probability, threshold):
    good = np.isfinite(obs) & np.isfinite(probability) & np.isfinite(threshold)
    o, probability, threshold = np.asarray(obs)[good], np.asarray(probability)[good], np.asarray(threshold)[good]
    yes, forecast = o >= threshold, probability >= 0.5
    tp, fp, fn = int((yes & forecast).sum()), int((~yes & forecast).sum()), int((yes & ~forecast).sum())
    return {"n": len(o), "observed_exceedances": int(yes.sum()), "tp": tp, "fp": fp, "fn": fn,
            "pod": tp / (tp+fn) if tp+fn else np.nan,
            "far": fp / (tp+fp) if tp+fp else np.nan,
            "csi": tp / (tp+fp+fn) if tp+fp+fn else np.nan,
            "brier_score": float(np.mean((probability - yes)**2)) if len(o) else np.nan}


def peak_events(group, threshold):
    """Observed exceedance clusters separated by >7 days; evaluate +/-5-day windows.

    These are local event diagnostics: a false peak elsewhere is captured by FAR/CSI,
    not counted as a successfully matched event. Actual time offsets use dates.
    """
    group = group.sort_values("valid_date").dropna(subset=["observed", "p50"])
    dates = pd.to_datetime(group.valid_date)
    high = group.loc[group.observed >= threshold]
    if high.empty:
        return []
    clusters = (pd.to_datetime(high.valid_date).diff().dt.days.fillna(99) > 7).cumsum()
    result = []
    for _, event in high.groupby(clusters):
        start, end = pd.to_datetime(event.valid_date).min(), pd.to_datetime(event.valid_date).max()
        window = group[(dates >= start - pd.Timedelta(days=5)) & (dates <= end + pd.Timedelta(days=5))]
        oi, pi = window.observed.idxmax(), window.p50.idxmax()
        observed, predicted = window.loc[oi], window.loc[pi]
        result.append({"event_start": start.strftime("%Y-%m-%d"), "event_end": end.strftime("%Y-%m-%d"),
                       "observed_peak_date": str(observed.valid_date), "predicted_peak_date": str(predicted.valid_date),
                       "observed_peak_cumecs": float(observed.observed), "predicted_peak_cumecs": float(predicted.p50),
                       "peak_magnitude_error_cumecs": float(predicted.p50 - observed.observed),
                       "peak_magnitude_error_pct": float(100 * (predicted.p50 / observed.observed - 1)),
                       "peak_timing_error_days": int((pd.Timestamp(predicted.valid_date) - pd.Timestamp(observed.valid_date)).days)})
    return result


def evaluate(predictions, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    scores, threshold_scores, events, calibration = [], [], [], []
    threshold_names = sorted({c[len("probability_"):] for c in predictions if c.startswith("probability_")})
    for keys, group in predictions.groupby(["fold_year", "model", "lead_day"]):
        year, model, lead = keys
        meta = {"fold_year": year, "model": model, "lead_day": lead}
        event_threshold = float(group.event_threshold_cumecs.iloc[0])
        found_events = peak_events(group, event_threshold)
        events.extend([{**meta, **e} for e in found_events])
        score = {**meta, **flow_metrics(group.observed.to_numpy(), group.p50.to_numpy())}
        high = group.observed >= event_threshold
        score.update({"flood_" + k: v for k, v in flow_metrics(group.observed[high].to_numpy(), group.p50[high].to_numpy()).items()})
        score.update({"n_peak_events": len(found_events),
                      "peak_magnitude_mae_cumecs": np.mean([abs(e["peak_magnitude_error_cumecs"]) for e in found_events]) if found_events else np.nan,
                      "peak_timing_mae_days": np.mean([abs(e["peak_timing_error_days"]) for e in found_events]) if found_events else np.nan})
        scores.append(score)
        good = group.observed.notna() & group.p50.notna()
        g = group[good]
        calibration.append({**meta, "n": len(g),
                            "coverage_80": ((g.observed >= g.p10) & (g.observed <= g.p90)).mean(),
                            "mean_width_cumecs": (g.p90-g.p10).mean(),
                            **{f"pinball_{q}": np.maximum(q*(g.observed-g[col]), (q-1)*(g.observed-g[col])).mean()
                               for q, col in [(0.1, "p10"), (0.5, "p50"), (0.9, "p90")]}})
        for name in threshold_names:
            thresholds = group[f"threshold_{name}_cumecs"].to_numpy()
            threshold_scores.append({**meta, "threshold": name, "threshold_cumecs": thresholds[0],
                                     **threshold_metrics(group.observed.to_numpy(), group[f"probability_{name}"].to_numpy(), thresholds)})
    pd.DataFrame(scores).to_csv(out / "scores_by_season_and_lead.csv", index=False)
    pd.DataFrame(threshold_scores).to_csv(out / "threshold_scores_by_season_and_lead.csv", index=False)
    event_frame = pd.DataFrame(events)
    event_frame.to_csv(out / "peak_events.csv", index=False)
    pd.DataFrame(calibration).to_csv(out / "quantile_calibration.csv", index=False)
    pooled, pooled_thresholds = [], []
    for (model, lead), g in predictions.groupby(["model", "lead_day"]):
        high = g.observed >= g.event_threshold_cumecs
        found = event_frame[(event_frame.model == model) & (event_frame.lead_day == lead)] if not event_frame.empty else pd.DataFrame()
        pooled.append({"model": model, "lead_day": lead, **flow_metrics(g.observed.to_numpy(), g.p50.to_numpy()),
                       **{"flood_" + k: v for k, v in flow_metrics(g.observed[high].to_numpy(), g.p50[high].to_numpy()).items()},
                       "n_peak_events": len(found),
                       "peak_magnitude_mae_cumecs": found.peak_magnitude_error_cumecs.abs().mean() if len(found) else np.nan,
                       "peak_timing_mae_days": found.peak_timing_error_days.abs().mean() if len(found) else np.nan})
        for name in threshold_names:
            pooled_thresholds.append({"model": model, "lead_day": lead, "threshold": name,
                                      **threshold_metrics(g.observed.to_numpy(), g[f"probability_{name}"].to_numpy(), g[f"threshold_{name}_cumecs"].to_numpy())})
    pooled = pd.DataFrame(pooled)
    pooled_thresholds = pd.DataFrame(pooled_thresholds)
    pooled.to_csv(out / "scores_by_lead.csv", index=False)
    pooled_thresholds.to_csv(out / "threshold_scores_by_lead.csv", index=False)
    comparisons = []
    for hybrid in ["HBV_LightGBM", "HBV_LSTM"]:
        for baseline in [m for m in ["persistence", "HBV", "GloFAS"] if m in pooled.model.unique()]:
            h, b = pooled[pooled.model == hybrid].set_index("lead_day"), pooled[pooled.model == baseline].set_index("lead_day")
            for lead in h.index.intersection(b.index):
                comparisons.append({"hybrid": hybrid, "baseline": baseline, "lead_day": lead,
                                    "kge_improvement": h.loc[lead, "kge"]-b.loc[lead, "kge"],
                                    "mae_reduction_cumecs": b.loc[lead, "mae_cumecs"]-h.loc[lead, "mae_cumecs"],
                                    "flood_mae_reduction_cumecs": b.loc[lead, "flood_mae_cumecs"]-h.loc[lead, "flood_mae_cumecs"],
                                    "peak_magnitude_mae_reduction_cumecs": b.loc[lead, "peak_magnitude_mae_cumecs"]-h.loc[lead, "peak_magnitude_mae_cumecs"],
                                    "peak_timing_mae_reduction_days": b.loc[lead, "peak_timing_mae_days"]-h.loc[lead, "peak_timing_mae_days"]})
    pd.DataFrame(comparisons).to_csv(out / "baseline_comparison.csv", index=False)
    return pooled, pooled_thresholds


def plots(predictions, scores, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = Path(out)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for model, group in scores.groupby("model"):
        for ax, metric in zip(axes, ["kge", "mae_cumecs", "flood_mae_cumecs"]):
            ax.plot(group.lead_day, group[metric], marker="o", label=model)
            ax.set(xlabel="Lead day", ylabel=metric)
            ax.grid(alpha=.2)
    axes[0].legend(fontsize=8)
    fig.suptitle("Rolling monsoon hindcasts; reanalysis weather is not an operational forecast")
    fig.tight_layout()
    fig.savefig(out / "skill_by_lead.png", dpi=160)
    plt.close(fig)
    for year in sorted(predictions.fold_year.unique()):
        subset = predictions[(predictions.fold_year == year) & (predictions.lead_day == 5)]
        fig, ax = plt.subplots(figsize=(12, 4))
        for model in ["HBV", "HBV_LightGBM", "HBV_LSTM", "persistence"]:
            g = subset[subset.model == model].sort_values("valid_date")
            dates = pd.to_datetime(g.valid_date)
            ax.plot(dates, g.p50, label=model, alpha=.8)
            if model == "HBV_LightGBM":
                ax.fill_between(dates, g.p10, g.p90, alpha=.2)
        observed = subset[subset.model == "HBV"].sort_values("valid_date")
        ax.plot(pd.to_datetime(observed.valid_date), observed.observed, "k", linewidth=1.4, label="Observed")
        ax.set(title=f"{year} monsoon, lead 5; LightGBM P10-P90 band", ylabel="Discharge (m³/s)")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(out / f"hydrograph_{year}_lead05.png", dpi=160)
        plt.close(fig)
