"""Walk-forward POC: one shared CRE vs one CRE per lead day (7-30)."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from sklearn.compose import TransformedTargetRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


HERE = Path(__file__).resolve().parent


def read_config() -> dict:
    with (HERE / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_daily_features(data: pd.DataFrame) -> pd.DataFrame:
    """Only use observations dated on or before the forecast issue date."""
    x = data.copy().sort_index()
    q = x["q_cumecs"].where(x["q_source"].eq("WAPDA"))
    out = pd.DataFrame(index=x.index)
    out["q_last"] = q
    for w in (7, 30, 90):
        out[f"q_mean_{w}"] = q.rolling(w, min_periods=1).mean()
    out["q_trend_7_30"] = out["q_mean_7"] - out["q_mean_30"]
    out["q_30_missing_fraction"] = q.isna().astype(float).rolling(30, min_periods=1).mean()

    for name in ("rain_chirps_mm", "snowmelt_mm", "pet_mm"):
        if name in x:
            for w in (30, 90):
                out[f"{name}_sum_{w}"] = x[name].rolling(w, min_periods=max(1, w // 3)).sum()
    for name in ("temperature_c", "swe_mm", "snow_depth_m", "dewpoint_c", "ssrd_wm2"):
        if name in x:
            out[f"{name}_last"] = x[name]
            out[f"{name}_mean_30"] = x[name].rolling(30, min_periods=10).mean()

    issue_doy = x.index.day_of_year.to_numpy(float)
    out["issue_doy_sin"] = np.sin(2 * np.pi * issue_doy / 365.25)
    out["issue_doy_cos"] = np.cos(2 * np.pi * issue_doy / 365.25)
    return out.replace([np.inf, -np.inf], np.nan)


def calendar_climatology(q: pd.Series, years: list[int], window: int) -> dict[int, float]:
    selected = q[q.index.year.isin(years)].dropna()
    doy = selected.index.day_of_year.to_numpy(float)
    values = selected.to_numpy(float)
    result: dict[int, float] = {}
    half = (window - 1) / 2
    for day in range(1, 367):
        distance = np.abs(doy - day)
        distance = np.minimum(distance, 365.25 - distance)
        near = distance <= half
        result[day] = float(np.mean(values[near])) if near.any() else float(np.mean(values))
    return result


def samples_for_years(
    frame: pd.DataFrame,
    features: pd.DataFrame,
    target_years: list[int],
    climatology_by_target_year: dict[int, dict[int, float]],
    leads: list[int],
    future_weather_std: dict[str, float],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, pd.DataFrame]:
    q = frame["q_cumecs"]
    valid = frame["q_source"].eq("WAPDA") & q.notna() & frame.index.year.isin(target_years)
    target_positions = np.flatnonzero(valid.to_numpy())
    rows: list[np.ndarray] = []
    residuals: list[float] = []
    climatologies: list[float] = []
    meta: list[dict] = []
    columns = list(features.columns)
    feature_values = features.to_numpy(float)
    weather_values = frame[["rain_era5_mm", "temperature_c"]].to_numpy(float)
    q_values = q.to_numpy(float)
    for target_pos in target_positions:
        target_date = frame.index[target_pos]
        target_year = int(target_date.year)
        doy = target_date.day_of_year
        clim = climatology_by_target_year[target_year][doy]
        target = float(q_values[target_pos])
        for lead in leads:
            issue_pos = target_pos - lead
            if issue_pos < 0:
                continue
            issue = frame.index[issue_pos]
            future_rain, future_temp = weather_values[target_pos].copy()
            rng_seed = (int(issue.value // 86_400_000_000_000) + lead * 7919 + 42) % (2**32)
            rng = np.random.default_rng(rng_seed)
            noise_std = 0.05 + (lead - 1) * 0.025
            future_rain += rng.normal() * noise_std * future_weather_std["rain_era5_mm"]
            future_temp += rng.normal() * noise_std * future_weather_std["temperature_c"]
            future_rain = max(float(future_rain), 0.0) if np.isfinite(future_rain) else np.nan
            h_features = np.concatenate((feature_values[issue_pos], [lead / 30.0, np.sin(2 * np.pi * lead / 24), np.cos(2 * np.pi * lead / 24), future_rain, future_temp]))
            rows.append(h_features)
            residuals.append(target - clim)
            climatologies.append(clim)
            meta.append({"issue_date": issue, "target_date": target_date, "target_year": target_year, "lead_day": lead, "target": target})
    if not rows:
        return pd.DataFrame(), np.array([]), np.array([]), pd.DataFrame()
    matrix = np.vstack(rows)
    base_names = columns + ["lead_scaled", "lead_sin", "lead_cos", "future_rain_at_lead_noisy_era5", "future_temperature_at_lead_noisy_era5"]
    x = pd.DataFrame(matrix, columns=base_names)
    x.insert(0, "lead_day", [m["lead_day"] for m in meta])
    y = np.asarray(residuals)
    clim_arr = np.asarray(climatologies)
    m = pd.DataFrame(meta)
    return x, y, clim_arr, m


def fit_ensemble(x: pd.DataFrame, y: np.ndarray, alphas: list[float]) -> list:
    models = []
    for alpha in alphas:
        reg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=float(alpha)))
        model = TransformedTargetRegressor(regressor=reg, transformer=StandardScaler())
        model.fit(x, y)
        models.append(model)
    return models


def predict_ensemble(models: list, x: pd.DataFrame) -> np.ndarray:
    return np.mean([model.predict(x) for model in models], axis=0)


def metrics(y: np.ndarray, pred: np.ndarray, baseline: np.ndarray, threshold: float) -> dict:
    mask = np.isfinite(y) & np.isfinite(pred) & np.isfinite(baseline)
    y, pred, baseline = y[mask], pred[mask], baseline[mask]
    if not len(y):
        return {"n": 0}
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
    base_rmse = float(np.sqrt(np.mean((baseline - y) ** 2)))
    denom = float(np.sum((y - y.mean()) ** 2))
    r = float(np.corrcoef(y, pred)[0, 1]) if len(y) > 1 and np.std(pred) > 0 and np.std(y) > 0 else float("nan")
    alpha = float(np.std(pred, ddof=1) / np.std(y, ddof=1)) if len(y) > 1 and np.std(y, ddof=1) else float("nan")
    beta = float(pred.mean() / y.mean()) if y.mean() else float("nan")
    kge = float(1 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)) if np.isfinite(r + alpha + beta) else float("nan")
    obs_flood = y > threshold
    pred_flood = pred > threshold
    tp = int(np.sum(obs_flood & pred_flood))
    return {
        "n": int(len(y)), "rmse": rmse, "mae": float(np.mean(np.abs(pred - y))),
        "nse": float(1 - np.sum((pred - y) ** 2) / denom) if denom > 0 else float("nan"),
        "kge": kge, "pbias_pct": float(100 * np.sum(pred - y) / np.sum(y)) if np.sum(y) else float("nan"),
        "climatology_rmse": base_rmse, "rmse_skill_vs_climatology": float(1 - rmse / base_rmse) if base_rmse else float("nan"),
        "observed_high_flow_days": int(obs_flood.sum()), "high_flow_recall": float(tp / obs_flood.sum()) if obs_flood.sum() else float("nan"),
        "high_flow_precision": float(tp / pred_flood.sum()) if pred_flood.sum() else float("nan"),
    }


def main() -> None:
    cfg = read_config()
    data = pd.read_csv(HERE / cfg["data"]["daily_file"], parse_dates=[cfg["data"]["date_column"]])
    data = data.set_index(cfg["data"]["date_column"]).sort_index()
    data = data[~data.index.duplicated(keep="last")]
    first, last = cfg["data"]["first_target_year"], cfg["data"]["last_target_year"]
    # Isolate the consistent WAPDA segment for the POC; FFD-only 2025-26 rows are not mixed in.
    data.loc[~data["q_source"].eq(cfg["data"]["observed_source"]), "q_cumecs"] = np.nan
    in_target_window = (data.index.year >= first) & (data.index.year <= last)
    q = data["q_cumecs"].where(in_target_window)
    data["q_cumecs"] = q
    features = make_daily_features(data)
    leads = list(range(cfg["forecast"]["first_lead_day"], cfg["forecast"]["last_lead_day"] + 1))
    validation_years = list(range(cfg["validation"]["first_validation_year"], cfg["validation"]["last_validation_year"] + 1))
    alphas = cfg["model"]["ensemble_alphas"]
    window = int(cfg["forecast"]["seasonal_climatology_window_days"])

    all_predictions = []
    folds = []
    for eval_year in validation_years:
        train_years = list(range(first, eval_year))
        if len(train_years) < cfg["validation"]["minimum_training_years"]:
            continue
        clim_train = calendar_climatology(data["q_cumecs"], train_years, window)
        crossfit_clims = {}
        for year in train_years:
            other_years = [y for y in train_years if y != year]
            crossfit_clims[year] = calendar_climatology(data["q_cumecs"], other_years, window)
        weather_train = data.loc[data.index.year.isin(train_years), ["rain_era5_mm", "temperature_c"]]
        weather_std = weather_train.std(ddof=0).replace(0, 1).fillna(1).to_dict()
        x_train, y_train, _, _ = samples_for_years(data, features, train_years, crossfit_clims, leads, weather_std)
        x_eval, _, clim_eval_byrow, m_eval = samples_for_years(data, features, [eval_year], {eval_year: clim_train}, leads, weather_std)
        if x_train.empty or x_eval.empty:
            continue
        fit_source = data.loc[data.index.year.isin(train_years) & data["q_source"].eq("WAPDA"), "q_cumecs"].dropna()
        threshold = float(fit_source.quantile(cfg["forecast"]["flood_percentile"]))
        # Construct target values from the metadata so every model sees the same observed rows.
        y_eval = m_eval["target"].to_numpy(float)
        leads_eval = m_eval["lead_day"].to_numpy(int)
        # Prediction features include a one-hot lead code only for the pooled model.
        x_train_shared = x_train.copy()
        x_eval_shared = x_eval.copy()
        for h in leads:
            x_train_shared[f"is_lead_{h}"] = (x_train_shared["lead_day"] == h).astype(float)
            x_eval_shared[f"is_lead_{h}"] = (x_eval_shared["lead_day"] == h).astype(float)
        # Fit pooled and lead-specific residual ensembles with the same alpha ensemble.
        pooled = fit_ensemble(x_train_shared.drop(columns="lead_day"), y_train, alphas)
        pred_shared_resid = predict_ensemble(pooled, x_eval_shared.drop(columns="lead_day"))
        pred_shared = np.maximum(0, clim_eval_byrow + pred_shared_resid)
        # A fixed seasonal reference is the null CRE with no learned residual.
        base = clim_eval_byrow
        preds_sep = np.full(len(m_eval), np.nan)
        for h in leads:
            train_mask = x_train["lead_day"].eq(h).to_numpy()
            eval_mask = x_eval["lead_day"].eq(h).to_numpy()
            if not train_mask.any() or not eval_mask.any():
                continue
            models = fit_ensemble(x_train.loc[train_mask].drop(columns="lead_day"), y_train[train_mask], alphas)
            residual = predict_ensemble(models, x_eval.loc[eval_mask].drop(columns="lead_day"))
            preds_sep[eval_mask] = np.maximum(0, clim_eval_byrow[eval_mask] + residual)
        for i, row in m_eval.iterrows():
            all_predictions.append({
                "evaluation_year": eval_year, "training_first_year": train_years[0],
                "training_last_year": train_years[-1], "issue_date": row.issue_date.date().isoformat(),
                "target_date": row.target_date.date().isoformat(), "lead_day": int(row.lead_day),
                "observed_q_cumecs": float(row.target), "climatology_q_cumecs": float(base[i]),
                "shared_CRE_q_cumecs": float(pred_shared[i]), "separate_CRE_q_cumecs": float(preds_sep[i]),
                "training_q95_cumecs": threshold,
            })
        folds.append({"evaluation_year": eval_year, "training_years": train_years, "train_samples": len(x_train), "evaluation_pairs": len(m_eval), "q95_cumecs": threshold})
        print(f"fold {eval_year}: train years {train_years[0]}-{train_years[-1]}, samples={len(x_train):,}, eval pairs={len(m_eval):,}")

    out = (HERE / cfg["outputs"]["comparison_root"]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pred = pd.DataFrame(all_predictions)
    if pred.empty:
        raise RuntimeError("No walk-forward validation predictions were generated")
    pred.to_csv(out / "oof_predictions.csv", index=False)
    pd.DataFrame(folds).to_csv(out / "folds.csv", index=False)

    lead_rows = []
    fold_rows = []
    for (year, lead), group in pred.groupby(["evaluation_year", "lead_day"]):
        yv = group["observed_q_cumecs"].to_numpy(float)
        base = group["climatology_q_cumecs"].to_numpy(float)
        threshold = float(group["training_q95_cumecs"].iloc[0])
        for strategy, col in (("shared_CRE", "shared_CRE_q_cumecs"), ("separate_CRE", "separate_CRE_q_cumecs")):
            m = metrics(yv, group[col].to_numpy(float), base, threshold)
            fold_rows.append({"evaluation_year": year, "lead_day": lead, "strategy": strategy, **m})
    by_fold = pd.DataFrame(fold_rows)
    by_fold.to_csv(out / "scores_by_fold.csv", index=False)
    for (strategy, lead), group in pred.melt(
        id_vars=["evaluation_year", "lead_day", "observed_q_cumecs", "climatology_q_cumecs", "training_q95_cumecs"],
        value_vars=["shared_CRE_q_cumecs", "separate_CRE_q_cumecs"], var_name="model", value_name="prediction",
    ).assign(strategy=lambda d: d.model.str.replace("_q_cumecs", "", regex=False)).groupby(["strategy", "lead_day"]):
        threshold_mask = group["training_q95_cumecs"].to_numpy(float)
        # Use each rolling fold's training-only threshold for its rows.
        met = metrics(group.observed_q_cumecs.to_numpy(float), group.prediction.to_numpy(float),
                      group.climatology_q_cumecs.to_numpy(float), float(np.nanmedian(threshold_mask)))
        # Flood scores are recomputed fold by fold below to retain each fold's threshold.
        recalls = []
        precisions = []
        for _, fold_group in group.groupby("evaluation_year"):
            fold_m = metrics(fold_group.observed_q_cumecs.to_numpy(float), fold_group.prediction.to_numpy(float),
                             fold_group.climatology_q_cumecs.to_numpy(float), float(fold_group.training_q95_cumecs.iloc[0]))
            recalls.append(fold_m.get("high_flow_recall", np.nan))
            precisions.append(fold_m.get("high_flow_precision", np.nan))
        met["high_flow_recall_fold_mean"] = float(np.nanmean(recalls))
        met["high_flow_precision_fold_mean"] = float(np.nanmean(precisions))
        lead_rows.append({"strategy": strategy, "lead_day": int(lead), **met})
    scores = pd.DataFrame(lead_rows).sort_values(["lead_day", "strategy"])
    scores.to_csv(out / "scores_by_lead.csv", index=False)

    band_rows = []
    for name, lo, hi in (("7-13 days", 7, 13), ("14-20 days", 14, 20), ("21-30 days", 21, 30)):
        for col, strategy in (("shared_CRE_q_cumecs", "shared_CRE"), ("separate_CRE_q_cumecs", "separate_CRE")):
            g = pred[pred.lead_day.between(lo, hi)]
            # Macro-average lead RMSE is the primary pooled comparison, avoiding a claim that all pairs are independent.
            per_lead = []
            for _, lg in g.groupby("lead_day"):
                per_lead.append(metrics(lg.observed_q_cumecs.to_numpy(float), lg[col].to_numpy(float),
                                        lg.climatology_q_cumecs.to_numpy(float), float(np.nanmedian(lg.training_q95_cumecs))))
            band_rows.append({"horizon_band": name, "strategy": strategy, "lead_days": f"{lo}-{hi}",
                              "macro_mean_lead_rmse_cumecs": float(np.nanmean([m.get("rmse", np.nan) for m in per_lead])),
                              "leads_beating_climatology": int(sum(m.get("rmse", np.inf) < m.get("climatology_rmse", -np.inf) for m in per_lead))})
    bands = pd.DataFrame(band_rows)
    bands.to_csv(out / "scores_by_horizon_band.csv", index=False)

    # Final deployable POC artifacts: train through 2024 after the walk-forward comparison.
    all_train_years = list(range(first, last + 1))
    full_clim = calendar_climatology(data["q_cumecs"], all_train_years, window)
    crossfit_full = {year: calendar_climatology(data["q_cumecs"], [y for y in all_train_years if y != year], window) for year in all_train_years}
    weather_full = data.loc[data.index.year.isin(all_train_years), ["rain_era5_mm", "temperature_c"]]
    weather_std_full = weather_full.std(ddof=0).replace(0, 1).fillna(1).to_dict()
    x_full, y_full, _, _ = samples_for_years(data, features, all_train_years, crossfit_full, leads, weather_std_full)
    shared_full = x_full.copy()
    for h in leads:
        shared_full[f"is_lead_{h}"] = (shared_full.lead_day == h).astype(float)
    final_models = {"shared_CRE": fit_ensemble(shared_full.drop(columns="lead_day"), y_full, alphas), "separate_CRE": {}}
    for h in leads:
        mask = x_full.lead_day.eq(h).to_numpy()
        final_models["separate_CRE"][h] = fit_ensemble(x_full.loc[mask].drop(columns="lead_day"), y_full[mask], alphas)
    final_dir = HERE / cfg["outputs"]["root"] / "final_train_through_2024"
    final_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": final_models, "feature_columns": list(x_full.columns), "shared_feature_columns": list(shared_full.drop(columns="lead_day").columns), "climatology": full_clim, "training_years": all_train_years, "alphas": alphas, "leads": leads}, final_dir / "models.joblib")

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for strategy, color in (("shared_CRE", "#0d8a78"), ("separate_CRE", "#d58c27")):
        s = scores[scores.strategy.eq(strategy)]
        ax.plot(s.lead_day, s.rmse, marker="o", markersize=3, linewidth=2, label=strategy.replace("_", " "), color=color)
    clim_points = []
    for lead, lead_group in pred.groupby("lead_day"):
        yearly_rmse = []
        for _, fold_group in lead_group.groupby("evaluation_year"):
            yearly_rmse.append(metrics(fold_group.observed_q_cumecs.to_numpy(float), fold_group.climatology_q_cumecs.to_numpy(float),
                                       fold_group.climatology_q_cumecs.to_numpy(float), float(fold_group.training_q95_cumecs.iloc[0]))["rmse"])
        clim_points.append((int(lead), float(np.mean(yearly_rmse))))
    ax.plot([x[0] for x in clim_points], [x[1] for x in clim_points], linestyle="--", color="#586a64", label="seasonal climatology")
    ax.set(xlabel="Forecast lead (days)", ylabel="RMSE (m³/s)", title="Walk-forward comparison: shared vs one model per lead")
    ax.grid(alpha=.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out / "shared_vs_separate_rmse.png", dpi=170)
    plt.close(fig)

    overall = scores.groupby("strategy").agg(macro_mean_lead_rmse=("rmse", "mean"), macro_mean_lead_skill=("rmse_skill_vs_climatology", "mean"), mean_nse=("nse", "mean"), leads_beating_climatology=("rmse_skill_vs_climatology", lambda x: int((x > 0).sum()))).reset_index()
    shared_score = float(overall.loc[overall.strategy.eq("shared_CRE"), "macro_mean_lead_rmse"].iloc[0])
    sep_score = float(overall.loc[overall.strategy.eq("separate_CRE"), "macro_mean_lead_rmse"].iloc[0])
    win_leads = int((scores.pivot(index="lead_day", columns="strategy", values="rmse").shared_CRE < scores.pivot(index="lead_day", columns="strategy", values="rmse").separate_CRE).sum())
    summary = {
        "validation_method": "Expanding-window, target-year walk-forward; training only precedes each evaluation year.",
        "validation_years": validation_years,
        "data": {"selected_target_source": "WAPDA only", "training_and_validation_target_years": f"{first}-{last}", "q_days_by_year": data.loc[data.q_source.eq("WAPDA")].groupby(data.loc[data.q_source.eq("WAPDA")].index.year).q_cumecs.count().dropna().astype(int).to_dict()},
        "leads": leads,
        "shared_macro_mean_lead_rmse_cumecs": shared_score,
        "separate_macro_mean_lead_rmse_cumecs": sep_score,
        "shared_wins_at_lead_count": win_leads,
        "lead_count": len(leads),
        "folds": folds,
        "long_range_training_status": "Not trained: nine observed WAPDA target years are inadequate for reliable 1-6 month seasonal validation; requires archived seasonal ensemble reforecasts and additional independent years/basins.",
        "note": "Development POC only. Historical years have been used in prior project model comparisons and are not a fresh independent test set. Future weather covariates are realized ERA5-Land at each target date with lead-growing synthetic noise, not archived issue-time forecasts; operational skill is not established.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    with (out / "REPORT.md").open("w", encoding="utf-8") as f:
        f.write("# Multi-horizon CRE proof of concept\n\n")
        f.write("## Question\n\nCan one horizon-aware climatology-residual model share learning across forecast days 7–30, or do separate models for each lead work better? The POC compares both on the same dates, features, baseline and rolling-year folds.\n\n")
        f.write("## Walk-forward results\n\n")
        f.write(overall.to_markdown(index=False, floatfmt=".3f"))
        f.write(f"\n\nThe shared model had lower macro-average RMSE on **{win_leads} of {len(leads)} leads**. Shared macro-RMSE: **{shared_score:.1f} m³/s**; separate-model macro-RMSE: **{sep_score:.1f} m³/s**. See the lead-by-lead CSV and plot; do not interpret the aggregate alone.\n\n")
        f.write("## Horizon groups\n\n" + bands.to_markdown(index=False, floatfmt=".3f"))
        f.write("\n\n## Interpretation and limits\n\nThis answers only the 7–30-day daily-flow POC. It is not evidence of skill at 1–6 months. Future weather covariates use realized ERA5-Land at each target date with lead-growing synthetic noise, matching the project's earlier retrospective proxy setup; these are not archived forecasts available at issue time. The expanding-year checks use 2019–2024 target years; these years have already been examined elsewhere in the project, so the results are developmental, not a fresh independent test. The validation data contain only WAPDA-labelled targets (2016–2024); FFD-only 2025–2026 rows are excluded from this prototype pending source-period consistency review.\n\nThe model fit at long lead can be compared only with climatology/persistence, and flood recall varies sharply with the number of high-flow dates. Do not call the POC operationally validated.\n")
    print(f"Wrote POC artifacts under {out}")
    print(overall.to_string(index=False))
    print(f"Shared lower RMSE on {win_leads}/{len(leads)} leads")


if __name__ == "__main__":
    main()
