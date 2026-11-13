"""Train and evaluate an observed-only seasonal residual Ridge forecast."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent


def cfg_read():
    return yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def feature_row(frame: pd.DataFrame, q_col: str, day: pd.Timestamp, min_coverage: float):
    history = frame.loc[:day]
    if history.empty or history.index[-1] != day:
        return None
    q = pd.to_numeric(history[q_col], errors="coerce")
    row = {}
    for n in (30, 90, 180, 365):
        tail = q.tail(n)
        if len(tail) != n or tail.notna().mean() < min_coverage:
            return None
        row[f"log_q_mean_{n}"] = float(np.log1p(tail.mean()))
    row["q_trend_30_180"] = row["log_q_mean_30"] - row["log_q_mean_180"]
    doy = day.day_of_year
    row["doy_sin"] = float(np.sin(2 * np.pi * doy / 365.25))
    row["doy_cos"] = float(np.cos(2 * np.pi * doy / 365.25))
    for col in ("rain_era5_mm", "temperature_c", "swe_mm", "snowmelt_mm", "snow_depth_m", "pet_mm"):
        if col not in history:
            continue
        values = pd.to_numeric(history[col], errors="coerce")
        for n in (30, 90):
            tail = values.tail(n)
            if len(tail) == n and tail.notna().mean() >= min_coverage:
                row[f"{col}_mean_{n}"] = float(tail.mean())
        if values.iloc[-1:].notna().any():
            row[f"{col}_latest"] = float(values.iloc[-1])
    return row


def build_samples(frame: pd.DataFrame, q_col: str, cfg: dict):
    first, last = cfg["data"]["train_years"]
    years = range(first, max(cfg["data"]["test_years"]) + 1)
    xs, ys = [], {h: [] for h in cfg["forecast"]["horizons_days"]}
    for year in years:
        for month in cfg["forecast"]["issue_months"]:
            issue = pd.Timestamp(year, month, cfg["forecast"]["issue_day"])
            row = feature_row(frame, q_col, issue, cfg["data"]["input_coverage_minimum"])
            if row is None:
                continue
            xs.append((issue, row))
            for horizon in ys:
                future = pd.to_numeric(frame.loc[issue + pd.Timedelta(days=1):issue + pd.Timedelta(days=horizon), q_col], errors="coerce")
                if len(future) == horizon and future.notna().mean() >= cfg["data"]["target_coverage_minimum"]:
                    ys[horizon].append((issue, float(future.mean())))
    all_x = pd.DataFrame([row for _, row in xs], index=[day for day, _ in xs])
    samples = {}
    for horizon, records in ys.items():
        y = pd.Series({day: value for day, value in records}, dtype=float, name="observed_future_mean_q")
        common = all_x.index.intersection(y.index)
        samples[horizon] = (all_x.loc[common], y.loc[common])
    return samples


def monthly_climatology(y: pd.Series, fit_dates: pd.DatetimeIndex, predict_dates: pd.DatetimeIndex):
    train = y.loc[fit_dates]
    means = train.groupby(train.index.month).mean()
    default = float(train.mean())
    return np.array([float(means.get(day.month, default)) for day in predict_dates]), means.to_dict()


def crossfit_climatology(y: pd.Series, dates: pd.DatetimeIndex):
    values = []
    for day in dates:
        other = dates[dates.year != day.year]
        same_month = y.loc[other[other.month == day.month]]
        fallback = y.loc[other]
        if fallback.empty:
            fallback = y.loc[dates]
        values.append(float(same_month.mean()) if len(same_month) else float(fallback.mean()))
    return np.asarray(values)


def make_ridge(alpha: float):
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=float(alpha)))


def metrics(obs, pred, baseline, threshold):
    obs, pred, baseline = map(np.asarray, (obs, pred, baseline))
    error = pred - obs
    rmse = float(np.sqrt(mean_squared_error(obs, pred)))
    clim_rmse = float(np.sqrt(mean_squared_error(obs, baseline)))
    r = float(np.corrcoef(obs, pred)[0, 1]) if len(obs) > 1 and np.std(obs) and np.std(pred) else float("nan")
    vr = float(np.std(pred, ddof=1) / np.std(obs, ddof=1)) if len(obs) > 1 and np.std(obs, ddof=1) else float("nan")
    bias_ratio = float(pred.mean() / obs.mean()) if obs.mean() else float("nan")
    kge = float(1 - np.sqrt((r - 1) ** 2 + (vr - 1) ** 2 + (bias_ratio - 1) ** 2)) if np.isfinite(r + vr + bias_ratio) else float("nan")
    high = obs > threshold
    alert = pred > threshold
    hits = int(np.sum(high & alert))
    false_alarms = int(np.sum(~high & alert))
    return {
        "n": int(len(obs)), "rmse": rmse, "mae": float(mean_absolute_error(obs, pred)),
        "nse": float(1 - np.sum(error ** 2) / np.sum((obs - obs.mean()) ** 2)) if np.sum((obs - obs.mean()) ** 2) else float("nan"),
        "kge": kge, "pbias_pct": float(100 * error.sum() / obs.sum()) if obs.sum() else float("nan"),
        "climatology_rmse": clim_rmse, "rmse_skill_vs_climatology": float(1 - rmse / clim_rmse) if clim_rmse else float("nan"),
        "flood_threshold_q": float(threshold), "observed_high_count": int(high.sum()),
        "flood_hit_rate": float(hits / high.sum()) if high.sum() else float("nan"),
        "flood_false_alarm_rate": float(false_alarms / (~high).sum()) if (~high).sum() else float("nan"),
    }


def rolling_walk_forward(samples, cfg):
    predictions, fold_scores = [], []
    for horizon, (x, y) in samples.items():
        for test_year in range(2020, max(cfg["data"]["test_years"]) + 1):
            train_end = test_year - 3
            val_years = [test_year - 2, test_year - 1]
            train_idx = x.index.year <= train_end
            val_idx = x.index.year.isin(val_years)
            test_idx = x.index.year == test_year
            if not train_idx.any() or not val_idx.any() or not test_idx.any():
                continue
            x_train, y_train = x.loc[train_idx], y.loc[train_idx]
            x_val, y_val = x.loc[val_idx], y.loc[val_idx]
            val_base, _ = monthly_climatology(y, x_train.index, x_val.index)
            residual = np.log1p(y_train.to_numpy()) - np.log1p(crossfit_climatology(y, x_train.index))
            choices = []
            for alpha in cfg["model"]["ridge_alpha_candidates"]:
                candidate = make_ridge(float(alpha)).fit(x_train, residual)
                pv = np.maximum(0, np.expm1(np.log1p(val_base) + candidate.predict(x_val)))
                choices.append((float(np.sqrt(mean_squared_error(y_val, pv))), float(alpha)))
            _, alpha = min(choices, key=lambda item: (item[0], -item[1]))

            prior = x.index.year < test_year
            x_prior, y_prior = x.loc[prior], y.loc[prior]
            prior_residual = np.log1p(y_prior.to_numpy()) - np.log1p(crossfit_climatology(y, x_prior.index))
            model = make_ridge(alpha).fit(x_prior, prior_residual)
            x_test, y_test = x.loc[test_idx], y.loc[test_idx]
            base, _ = monthly_climatology(y, x_prior.index, x_test.index)
            pred = np.maximum(0, np.expm1(np.log1p(base) + model.predict(x_test)))
            threshold = float(y_prior.quantile(cfg["forecast"]["flood_percentile"]))
            score = metrics(y_test.to_numpy(), pred, base, threshold)
            score.update({"horizon_days": horizon, "test_year": test_year, "selected_alpha": alpha})
            fold_scores.append(score)
            predictions.extend({"issue_date": day.date().isoformat(), "test_year": test_year, "horizon_days": horizon,
                                "observed_future_mean_q": float(actual), "ridge_residual_q": float(forecast),
                                "observed_climatology_q": float(climatology), "selected_alpha": alpha}
                               for day, actual, forecast, climatology in zip(x_test.index, y_test, pred, base))
    return pd.DataFrame(predictions), pd.DataFrame(fold_scores)


def main():
    cfg = cfg_read()
    source_path = (HERE / cfg["data"]["merged_daily"]).resolve()
    frame = pd.read_csv(source_path, parse_dates=[cfg["data"]["date_column"]]).set_index(cfg["data"]["date_column"]).sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    q_col, source_col = cfg["data"]["target_column"], cfg["data"]["source_column"]
    # Only the observed source is used as target or flow history.
    frame[q_col] = pd.to_numeric(frame[q_col], errors="coerce").where(frame[source_col].eq(cfg["data"]["observed_source"]))
    samples = build_samples(frame, q_col, cfg)
    report, pred_rows = [], []
    run_dir = HERE / cfg["outputs"]["models"]
    report_dir = HERE / cfg["outputs"]["reports"]
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    for horizon, (x, y) in samples.items():
        train_mask = x.index.year <= cfg["data"]["train_years"][1]
        val_mask = x.index.year.isin(cfg["data"]["validation_years"])
        fit_train = x.loc[train_mask]
        y_train = y.loc[train_mask]
        x_val, y_val = x.loc[val_mask], y.loc[val_mask]
        if fit_train.empty or x_val.empty:
            raise RuntimeError(f"Missing train or validation samples for {horizon}-day horizon")
        train_baseline, _ = monthly_climatology(y, fit_train.index, fit_train.index)
        y_resid = np.log1p(y_train.to_numpy()) - np.log1p(crossfit_climatology(y, fit_train.index))
        val_baseline, _ = monthly_climatology(y, fit_train.index, x_val.index)
        val_rows = []
        for alpha in cfg["model"]["ridge_alpha_candidates"]:
            candidate = make_ridge(float(alpha)).fit(fit_train, y_resid)
            val_pred = np.maximum(0, np.expm1(np.log1p(val_baseline) + candidate.predict(x_val)))
            val_rmse = float(np.sqrt(mean_squared_error(y_val, val_pred)))
            val_rows.append({"alpha": float(alpha), "rmse": val_rmse})
        # Prefer the more regularized model when validation errors tie.
        best = min(val_rows, key=lambda row: (row["rmse"], -row["alpha"]))

        final_train_mask = x.index.year <= cfg["data"]["final_train_last_year"]
        final_x, final_y = x.loc[final_train_mask], y.loc[final_train_mask]
        final_resid = np.log1p(final_y.to_numpy()) - np.log1p(crossfit_climatology(y, final_x.index))
        model = make_ridge(best["alpha"]).fit(final_x, final_resid)
        test_mask = x.index.year.isin(cfg["data"]["test_years"])
        x_test, y_test = x.loc[test_mask], y.loc[test_mask]
        test_baseline, month_means = monthly_climatology(y, final_x.index, x_test.index)
        pred = np.maximum(0, np.expm1(np.log1p(test_baseline) + model.predict(x_test)))
        threshold = float(final_y.quantile(cfg["forecast"]["flood_percentile"]))
        score = metrics(y_test.to_numpy(), pred, test_baseline, threshold)
        score.update({"horizon_days": horizon, "selected_alpha": best["alpha"], "validation_rmse": best["rmse"], "validation_climatology_rmse": float(np.sqrt(mean_squared_error(y_val, val_baseline))), "test_years": cfg["data"]["test_years"]})
        report.append(score)
        for date, actual, forecast, clim in zip(x_test.index, y_test, pred, test_baseline):
            pred_rows.append({"issue_date": date.date().isoformat(), "horizon_days": horizon, "observed_future_mean_q": float(actual), "ridge_residual_q": float(forecast), "observed_climatology_q": float(clim)})
        joblib.dump({"model": model, "feature_columns": list(x.columns), "horizon_days": horizon, "selected_alpha": best["alpha"], "training_years": [int(final_x.index.year.min()), int(final_x.index.year.max())], "monthly_climatology": month_means, "target_transform": "log1p residual around month-of-issue observed climatology"}, run_dir / f"observed_ridge_{horizon}day.joblib")
        print(f"{horizon}-day | test n={score['n']} | RMSE {score['rmse']:.1f} vs climatology {score['climatology_rmse']:.1f} | skill {score['rmse_skill_vs_climatology']:.3f} | NSE {score['nse']:.3f} | hit rate {score['flood_hit_rate']:.3f}")

    rolling_predictions, rolling_scores = rolling_walk_forward(samples, cfg)
    if not rolling_predictions.empty:
        rolling_predictions.to_csv(report_dir / "rolling_oof_predictions.csv", index=False)
        rolling_scores.to_csv(report_dir / "rolling_oof_scores_by_year.csv", index=False)
        summary = []
        for horizon, subset in rolling_predictions.groupby("horizon_days"):
            score = metrics(subset.observed_future_mean_q, subset.ridge_residual_q,
                            subset.observed_climatology_q,
                            float(rolling_scores.loc[rolling_scores.horizon_days.eq(horizon), "flood_threshold_q"].median()))
            score["horizon_days"] = int(horizon)
            score["test_years"] = ",".join(map(str, sorted(subset.test_year.unique())))
            summary.append(score)
        pd.DataFrame(summary).to_csv(report_dir / "rolling_oof_summary.csv", index=False)
        lines = ["# Rolling held-out observed-year check", "", "Each test year is kept out; alpha is chosen using the two preceding validation years, and the model is fit on earlier observed years only.", "", "| Horizon | Test origins | Test years | Model RMSE | Climatology RMSE | Skill vs climatology | NSE |", "|---:|---:|---|---:|---:|---:|---:|"]
        for row in summary:
            lines.append(f"| {row['horizon_days']} days | {row['n']} | {row['test_years']} | {row['rmse']:.1f} | {row['climatology_rmse']:.1f} | {row['rmse_skill_vs_climatology']:.3f} | {row['nse']:.3f} |")
        lines += ["", "Monthly origins overlap in their target windows. These rolling results are a stronger check than a single test year, but they are still a small, single-basin record."]
        (report_dir / "ROLLING_OOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    pd.DataFrame(report).to_csv(report_dir / "heldout_2024_scores.csv", index=False)
    pd.DataFrame(pred_rows).to_csv(report_dir / "heldout_2024_predictions.csv", index=False)
    receipt = {"input_file": str(source_path), "input_sha256": sha256(source_path), "observed_target_source": cfg["data"]["observed_source"], "target_values_modified": False, "target_interpolated": False, "simulation_used_as_target": False}
    (report_dir / "provenance.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    lines = ["# Observed-only seasonal residual Ridge", "", "| Horizon | Test origins | Model RMSE | Climatology RMSE | Skill vs climatology | NSE | KGE | Bias | Flood hit rate |", "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in report:
        lines.append(f"| {r['horizon_days']} days | {r['n']} | {r['rmse']:.1f} | {r['climatology_rmse']:.1f} | {r['rmse_skill_vs_climatology']:.3f} | {r['nse']:.3f} | {r['kge']:.3f} | {r['pbias_pct']:.1f}% | {r['flood_hit_rate']:.3f} |")
    lines += ["", "Validation: observed 2022–2023; alpha selected from the configured Ridge candidates. Final fit: observed WAPDA 2016–2023. Test: observed WAPDA 2024 only. Test origins are monthly and overlap in their future target windows.", "", "The model uses antecedent discharge and antecedent weather/snow indicators only. Target values are never filled. These few test origins make results exploratory; a single held-out year does not establish dependable seasonal skill."]
    (report_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    pred = pd.DataFrame(pred_rows)
    fig, axes = plt.subplots(len(cfg["forecast"]["horizons_days"]), 1, figsize=(10, 6), sharex=True)
    if len(cfg["forecast"]["horizons_days"]) == 1:
        axes = [axes]
    for ax, horizon in zip(axes, cfg["forecast"]["horizons_days"]):
        sub = pred[pred.horizon_days == horizon]
        ax.plot(sub.issue_date, sub.observed_future_mean_q, "o-", label="Observed")
        ax.plot(sub.issue_date, sub.ridge_residual_q, "o-", label="Ridge residual")
        ax.plot(sub.issue_date, sub.observed_climatology_q, "--", label="Climatology")
        ax.set_ylabel(f"{horizon}d mean\n(m³/s)")
        ax.grid(alpha=.25)
    axes[0].legend(ncol=3)
    fig.tight_layout()
    fig.savefig(report_dir / "heldout_2024_forecasts.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
