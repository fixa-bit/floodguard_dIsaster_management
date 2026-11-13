"""Reload saved models and forecast every supplied, dated meteorological member.

History must contain actual inputs only through the issue date. No future
discharge, snow, PET or historical weather is required. Future PET is the saved
training climatology. Reanalysis-trained models retain a prominent mismatch flag.
"""
import argparse
import json
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
import torch
from .data import make_samples, save_json, digest
from .forcing import QuantileMapper, validate_archive
from .learning import load_lstm, predict_lstm, predict_boosters
from .physical import PARAMETERS
from .train import forecast_table, save_trajectories


def predict(run, history_file, forecast_file, issue_date, output):
    root, output = Path(run).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Forecast output already exists: {output}")
    config = json.loads((root / "config.json").read_text())
    torch.set_num_threads(config["threads"])
    final = root / "final"
    if not (final / "complete.json").exists():
        raise ValueError("Final model refit is not complete")
    history = pd.read_csv(history_file, parse_dates=["date"]).set_index("date").sort_index()
    if history.index.duplicated().any():
        raise ValueError("Duplicate historical dates")
    issue = pd.Timestamp(issue_date)
    history = history.loc[config["simulation_start"]:issue].copy()
    if not history.index.equals(pd.date_range(config["simulation_start"], issue)):
        raise ValueError("Historical forcing must cover the original spin-up start through issue day")
    required = ["rain_chirps_mm", "temperature_c", "pet_mm"]
    if not np.isfinite(history[required]).all().all():
        raise ValueError("Missing observed historical forcing")
    if (history[["rain_chirps_mm", "pet_mm"]] < 0).any().any():
        raise ValueError("Negative precipitation/PET in history")
    if "q_cumecs" not in history:
        history["q_cumecs"] = np.nan
    if np.isinf(history.q_cumecs).any() or (history.q_cumecs.dropna() < 0).any():
        raise ValueError("Invalid historical discharge")
    if "snow_cover_pct" not in history:
        history["snow_cover_pct"], history["valid_frac"] = np.nan, np.nan
    archive = validate_archive(pd.read_csv(forecast_file), config["horizon"])
    archive = archive[archive.issue_date.dt.tz_localize(None) == issue]
    if archive.empty:
        raise ValueError("No complete meteorological members for requested issue date")
    # Padding only makes room for target calendar slots. It is never part of the
    # selected issue's historical states, observed inputs or residual targets.
    padding = pd.DataFrame(index=pd.date_range(issue + pd.Timedelta(days=1), periods=config["horizon"]), columns=history.columns, dtype=float)
    padding[required] = 0.
    history = pd.concat([history, padding])
    history.index.name = "date"
    calibration = json.loads((final / "physical/calibration.json").read_text())
    par = np.array([calibration["parameters"][name] for name in PARAMETERS])
    mapper = QuantileMapper(json.loads((final / "forcing/quantile_mapping.json").read_text()))
    climate = json.loads((final / "forcing/pet_climatology.json").read_text())
    samples = make_samples(history, par, calibration["area_km2"], config,
                           calibration["calibration_cutoff"], archive, mapper=mapper, pet_climate=climate)
    names = json.loads((final / "models/features.json").read_text())
    if samples["tabular_features"] != names["tabular_features"]:
        raise ValueError("Feature schema differs from trained models")
    boosters = [[lgb.Booster(model_file=str(final / f"models/lightgbm/lead_{lead:02d}_q{int(q*100):02d}.txt"))
                 for q in config["quantiles"]] for lead in range(1, config["horizon"] + 1)]
    lstm = load_lstm(final / "models/lstm/best.pt")
    selected = history.index[samples["origins"]] == issue
    corrections = {"HBV": None, "persistence": None,
                   "HBV_LightGBM": predict_boosters(boosters, samples["tabular"][selected]),
                   "HBV_LSTM": predict_lstm(lstm, samples["history"][selected], samples["future"][selected])}
    threshold = json.loads((final / "thresholds.json").read_text())
    table, members = forecast_table(history, samples, selected, corrections,
                                    threshold["values_cumecs"], threshold["event_threshold_cumecs"],
                                    "issued_forecast", "issued_ensemble")
    output.mkdir(parents=True)
    table.drop(columns=["observed", "fold_year"]).to_csv(output / "hydrographs.csv", index=False)
    members.to_csv(output / "member_hydrographs.csv", index=False)
    save_trajectories(history, samples, selected, output / "hbv_trajectories.csv")
    run_manifest = json.loads((root / "run_manifest.json").read_text())
    mismatch = not bool(config.get("forecast_file"))
    save_json(output / "forecast_manifest.json", {
        "issue_date": str(issue.date()), "forecast_members": int(archive.member.nunique()),
        "model_run": str(root), "trained_on_reanalysis": mismatch,
        "warning": "TRAIN/OPERATIONS MISMATCH: residual models and weather mappings were trained on reanalysis, "
                   "not this forecast provider. Operational skill is unverified." if mismatch else None,
        "model_calibration_cutoff": calibration["calibration_cutoff"],
        "historical_replay": issue <= pd.Timestamp(calibration["calibration_cutoff"]),
        "inputs": {str(Path(p).resolve()): digest(p) for p in [history_file, forecast_file]},
        "limitations": run_manifest["limitations"]})
    print(f"Saved {archive.member.nunique()} weather members and their mixture forecasts to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--forecast", required=True)
    parser.add_argument("--issue-date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    predict(args.run, args.history, args.forecast, args.issue_date, args.output)
