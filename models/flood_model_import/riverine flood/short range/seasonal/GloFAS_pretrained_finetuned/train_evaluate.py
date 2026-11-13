"""GloFAS pretraining, observed Marala fine-tuning, and held-out evaluation."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

HERE = Path(__file__).resolve().parent


def load_config():
    return yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))


def feature_row(frame: pd.DataFrame, q_col: str, date: pd.Timestamp) -> dict | None:
    hist = frame.loc[:date]
    if hist.empty or hist.index[-1] != date:
        return None
    q = pd.to_numeric(hist[q_col], errors="coerce")
    row: dict[str, float] = {}
    for days in (30, 90, 180, 365):
        tail = q.tail(days)
        if len(tail) < days or tail.notna().mean() < 0.8:
            return None
        row[f"log_q_mean_{days}"] = float(np.log1p(tail.mean()))
    row["q_trend_30_180"] = row["log_q_mean_30"] - row["log_q_mean_180"]
    doy = date.day_of_year
    row["doy_sin"] = float(np.sin(2 * np.pi * doy / 365.25))
    row["doy_cos"] = float(np.cos(2 * np.pi * doy / 365.25))
    for col in ("rain_era5_mm", "temperature_c", "swe_mm", "snowmelt_mm", "snow_depth_m"):
        if col not in hist.columns:
            continue
        vals = pd.to_numeric(hist[col], errors="coerce")
        for days in (30, 90):
            tail = vals.tail(days)
            if len(tail) == days and tail.notna().mean() >= 0.8:
                row[f"{col}_mean_{days}"] = float(tail.mean())
        if vals.iloc[-1:].notna().any():
            row[f"{col}_latest"] = float(vals.iloc[-1])
    return row


def make_samples(frame: pd.DataFrame, q_col: str, years: list[int], cfg: dict):
    horizons = cfg["forecast"]["horizons_days"]
    min_target = cfg["data"]["target_coverage_minimum"]
    features, targets, metadata = [], {h: [] for h in horizons}, {h: [] for h in horizons}
    for year in years:
        for month in cfg["forecast"]["issue_months"]:
            try:
                issue = pd.Timestamp(year, month, cfg["forecast"]["issue_day"])
            except ValueError:
                continue
            x = feature_row(frame, q_col, issue)
            if x is None:
                continue
            features.append((issue, x))
            for h in horizons:
                future = frame.loc[issue + pd.Timedelta(days=1):issue + pd.Timedelta(days=h), q_col]
                future = pd.to_numeric(future, errors="coerce")
                if len(future) < h or future.notna().mean() < min_target:
                    continue
                targets[h].append(float(future.mean()))
                metadata[h].append(issue)
    xdf = pd.DataFrame([r for _, r in features], index=[d for d, _ in features])
    out = {}
    for h in horizons:
        ydf = pd.Series(targets[h], index=metadata[h], name="target_mean_q")
        common = xdf.index.intersection(ydf.index)
        out[h] = (xdf.loc[common], ydf.loc[common])
    return out


def new_model(cfg: dict):
    return MLPRegressor(
        hidden_layer_sizes=tuple(cfg["model"]["hidden_layer_sizes"]),
        activation="relu", solver="adam", alpha=float(cfg["model"]["alpha"]),
        learning_rate_init=float(cfg["model"]["learning_rate_init"]),
        max_iter=1, warm_start=True, shuffle=False,
        random_state=int(cfg["model"]["seed"]),
    )


def train_epochs(model, x: np.ndarray, y: np.ndarray, epochs: int):
    for _ in range(epochs):
        model.partial_fit(x, y)
    return model


def fit_pretrained(x_pre, y_pre, x_obs, y_obs, cfg, epochs):
    xs = StandardScaler().fit(x_pre)
    ys = StandardScaler().fit(y_pre.reshape(-1, 1))
    model = new_model(cfg)
    train_epochs(model, xs.transform(x_pre), ys.transform(y_pre.reshape(-1, 1)).ravel(), cfg["model"]["pretrain_epochs"])
    train_epochs(model, xs.transform(x_obs), ys.transform(y_obs.reshape(-1, 1)).ravel(), epochs)
    return model, xs, ys


def predict(model, xs, ys, x):
    z = model.predict(xs.transform(x))
    return np.maximum(0.0, np.expm1(ys.inverse_transform(z.reshape(-1, 1)).ravel()))


def scores(obs, pred, clim, threshold):
    obs, pred, clim = map(np.asarray, (obs, pred, clim))
    rmse = float(np.sqrt(mean_squared_error(obs, pred)))
    clim_rmse = float(np.sqrt(mean_squared_error(obs, clim)))
    flood = obs > threshold
    alert = pred > threshold
    tp = int(np.sum(flood & alert))
    return {
        "n": len(obs), "rmse": rmse, "mae": float(mean_absolute_error(obs, pred)),
        "nse": float(1 - np.sum((obs - pred) ** 2) / np.sum((obs - obs.mean()) ** 2)) if len(obs) > 1 and np.sum((obs - obs.mean()) ** 2) else float("nan"),
        "pbias_pct": float(100 * np.sum(pred - obs) / np.sum(obs)) if np.sum(obs) else float("nan"),
        "climatology_rmse": clim_rmse,
        "rmse_skill_vs_climatology": float(1 - rmse / clim_rmse) if clim_rmse else float("nan"),
        "flood_threshold_q": float(threshold), "observed_flood_count": int(flood.sum()),
        "flood_hit_rate": float(tp / flood.sum()) if flood.sum() else float("nan"),
        "flood_false_alarm_rate": float(np.sum(alert & ~flood) / np.sum(~flood)) if np.sum(~flood) else float("nan"),
    }


def main():
    cfg = load_config()
    merged = pd.read_csv((HERE / cfg["data"]["merged_daily"]).resolve(), parse_dates=[cfg["data"]["date_column"]])
    merged = merged.set_index(cfg["data"]["date_column"]).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    qobs = cfg["data"]["observed_target"]
    source = cfg["data"]["observed_source"]
    merged[qobs] = pd.to_numeric(merged[qobs], errors="coerce").where(merged["q_source"].eq(source))
    glofas = pd.read_csv((HERE / cfg["data"]["glofas_daily"]).resolve(), parse_dates=["date_utc_day_averaged"])
    glofas = glofas.set_index("date_utc_day_averaged").sort_index()
    glofas = glofas.rename(columns={cfg["data"]["simulated_target"]: "q_sim"})
    sim = merged.join(glofas[["q_sim"]], how="inner")
    sim = sim.loc[f"{cfg['data']['simulated_first_year']}-01-01":f"{cfg['data']['simulated_last_year']}-12-31"]
    obs = merged.loc[f"{cfg['data']['observed_train_first_year']}-01-01":f"{cfg['data']['observed_test_years'][-1]}-12-31"]
    sim_samples = make_samples(sim, "q_sim", list(range(cfg["data"]["simulated_first_year"], cfg["data"]["simulated_last_year"] + 1)), cfg)
    obs_samples = make_samples(obs, qobs, list(range(cfg["data"]["observed_train_first_year"], cfg["data"]["observed_test_years"][-1] + 1)), cfg)
    report = {"source_separation": {"pretraining": "GloFAS simulated discharge only, 1980-2015", "fine_tuning": "WAPDA observed Marala discharge only", "held_out_test": cfg["data"]["observed_test_years"]}, "results": []}
    all_predictions = []
    model_dir = HERE / cfg["outputs"]["model_directory"]
    model_dir.mkdir(parents=True, exist_ok=True)
    for h in cfg["forecast"]["horizons_days"]:
        xpre, ypre = sim_samples[h]
        xobs, yobs = obs_samples[h]
        val_mask = xobs.index.year.isin(cfg["data"]["observed_validation_years"])
        train_mask = (xobs.index.year >= cfg["data"]["observed_train_first_year"]) & (xobs.index.year < min(cfg["data"]["observed_validation_years"]))
        test_mask = xobs.index.year.isin(cfg["data"]["observed_test_years"])
        xtr, ytr = xobs.loc[train_mask], yobs.loc[train_mask]
        xv, yv = xobs.loc[val_mask], yobs.loc[val_mask]
        xt, yt = xobs.loc[test_mask], yobs.loc[test_mask]
        if not len(xt) or not len(xpre) or not len(xtr) or not len(xv):
            raise RuntimeError(f"Insufficient samples for {h}-day horizon: GloFAS={len(xpre)}, train={len(xtr)}, validation={len(xv)}, test={len(xt)}")
        best_epoch, best_rmse = None, float("inf")
        for epochs in cfg["model"]["finetune_epochs_to_check"]:
            mdl, xscale, yscale = fit_pretrained(xpre.to_numpy(), np.log1p(ypre.to_numpy()), xtr.to_numpy(), np.log1p(ytr.to_numpy()), cfg, int(epochs))
            pval = predict(mdl, xscale, yscale, xv.to_numpy())
            rmse = float(np.sqrt(mean_squared_error(yv, pval)))
            if rmse < best_rmse:
                best_epoch, best_rmse = int(epochs), rmse
        # Final fit uses all observed years through 2023. 2024 remains held out.
        final_train = xobs.index.year <= cfg["data"]["observed_final_train_last_year"]
        final_model, final_xs, final_ys = fit_pretrained(xpre.to_numpy(), np.log1p(ypre.to_numpy()), xobs.loc[final_train].to_numpy(), np.log1p(yobs.loc[final_train].to_numpy()), cfg, best_epoch)
        pred = predict(final_model, final_xs, final_ys, xt.to_numpy())
        # Seasonal-month climatology uses observed training targets only.
        train_frame = pd.DataFrame({"y": yobs.loc[final_train]})
        clim = np.array([train_frame.loc[train_frame.index.month == d.month, "y"].mean() for d in xt.index])
        q95 = float(yobs.loc[final_train].quantile(cfg["forecast"]["flood_percentile"]))
        score = scores(yt.to_numpy(), pred, clim, q95)
        score.update({"horizon_days": h, "best_finetune_epochs": best_epoch, "validation_rmse": best_rmse, "test_years": cfg["data"]["observed_test_years"], "interpretation": "exploratory; few independent held-out seasonal origins"})
        report["results"].append(score)
        all_predictions.extend({"issue_date": d.date().isoformat(), "horizon_days": h, "observed_future_mean_q": float(o), "glofas_pretrained_finetuned_q": float(p), "observed_climatology_q": float(c)} for d, o, p, c in zip(xt.index, yt, pred, clim))
        joblib.dump({"model": final_model, "x_scaler": final_xs, "y_scaler": final_ys, "horizon_days": h, "features": list(xobs.columns), "pretrain_years": [cfg["data"]["simulated_first_year"], cfg["data"]["simulated_last_year"]], "fine_tune_through_year": cfg["data"]["observed_final_train_last_year"]}, model_dir / f"glofas_pretrained_{h}day.joblib")
        print(f"{h}-day: test n={score['n']} | RMSE={score['rmse']:.1f} | NSE={score['nse']:.3f} | skill vs climatology={score['rmse_skill_vs_climatology']:.3f} | flood hit={score['flood_hit_rate']:.3f}")
    report_dir = HERE / cfg["outputs"]["directory"]
    report_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_predictions).to_csv(report_dir / "heldout_2024_predictions.csv", index=False)
    pd.DataFrame(report["results"]).to_csv(report_dir / "heldout_2024_scores.csv", index=False)
    (report_dir / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Seasonal GloFAS pretraining experiment", "", "| Horizon | Test origins | RMSE | MAE | NSE | Bias | RMSE skill vs observed climatology | Flood hit rate |", "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in report["results"]:
        lines.append(f"| {r['horizon_days']} days | {r['n']} | {r['rmse']:.1f} | {r['mae']:.1f} | {r['nse']:.3f} | {r['pbias_pct']:.1f}% | {r['rmse_skill_vs_climatology']:.3f} | {r['flood_hit_rate']:.3f} |")
    lines += ["", "Test set: observed WAPDA Marala targets in 2024 only; model fitting used GloFAS 1980–2015, observed fine-tuning 2016–2023, and validation 2022–2023 for epoch selection.", "", "**Caution:** GloFAS is simulated, not measured flow. This is a small exploratory test with few independent seasonal forecast origins; scores do not establish operational long-range forecast skill. The forecast features use antecedent conditions only. No target values were filled or altered."]
    (report_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
