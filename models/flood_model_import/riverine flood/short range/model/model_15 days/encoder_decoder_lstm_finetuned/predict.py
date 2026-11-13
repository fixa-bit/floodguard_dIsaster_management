"""Predict all 15 leads in one call using supplied historical and forecast weather."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from data import inverse_flow, normalize
from lstm.train import load_checkpoint
from encoder_decoder_lstm_finetuned.model import HindcastForecastLSTM
from encoder_decoder_lstm_finetuned.train import save_json, sha


def build_inputs(history, future, issue, config, statistics):
    d, flow = config["data"], statistics["flow"]
    issue = pd.Timestamp(issue)
    dates = pd.date_range(issue-pd.Timedelta(days=d["hindcast_length"]-1), issue)
    if not dates.isin(history.index).all():
        raise ValueError("History needs every calendar day in the last 365 days")
    history = history.reindex(dates)
    for col in ["precipitation_mm", "temperature_c", "q_cumecs"]:
        if col not in history:
            if col != "q_cumecs":
                raise ValueError(f"Missing historical feature {col}")
            history[col] = np.nan
    if np.isinf(history[["precipitation_mm", "temperature_c", "q_cumecs"]]).any().any():
        raise ValueError("Infinite historical inputs")
    if (history[["precipitation_mm", "q_cumecs"]] < 0).any().any():
        raise ValueError("Negative rain/discharge in history")
    h = normalize(history[d["dynamic_columns"]].to_numpy(float), statistics["dynamic"])
    if d["past_discharge"]:
        past = history.q_cumecs.to_numpy(float)
        missing = ~np.isfinite(past)
        standardized = (np.log1p(past / flow["scale"])-flow["mean"])/flow["std"]
        fill = (flow["training_log_mean"]-flow["mean"])/flow["std"]
        h = np.column_stack([h, np.where(missing, fill, standardized), missing])
    if d["calendar_features"]:
        angle = 2*np.pi*dates.day_of_year.to_numpy()/365.25
        h = np.column_stack([h, np.sin(angle), np.cos(angle)])
    expected = pd.date_range(issue+pd.Timedelta(days=1), periods=d["forecast_horizon"])
    if not future.index.equals(expected):
        raise ValueError("Forecast dates must be exactly issue+1 through issue+15, sorted and complete")
    if not np.isfinite(future[d["forecast_columns"]]).all().all() or (future.precipitation_mm < 0).any():
        raise ValueError("Forecast precipitation/temperature must be finite, and precipitation nonnegative")
    if "available_at" in future:
        available = pd.to_datetime(future.available_at, utc=True)
        if available.isna().any() or (available > issue.tz_localize("UTC") + pd.Timedelta(days=1)).any():
            raise ValueError("Forecast unavailable at issue cutoff")
    f = normalize(future[d["forecast_columns"]].to_numpy(float), statistics["forecast"])
    return torch.tensor(h[None], dtype=torch.float32), torch.tensor(f[None], dtype=torch.float32), torch.empty(1, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint")
    parser.add_argument("--history", required=True)
    parser.add_argument("--forecast", required=True)
    parser.add_argument("--issue-date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).parent
    checkpoint_path = args.checkpoint or json.loads((root / "runs/selected_model.json").read_text())["checkpoint"]
    checkpoint = load_checkpoint(checkpoint_path)
    cfg = checkpoint["config"]
    torch.set_num_threads(cfg["training"]["cpu_threads"])
    torch.set_flush_denormal(True)
    history = pd.read_csv(args.history, parse_dates=["date"]).set_index("date").sort_index()
    future = pd.read_csv(args.forecast, parse_dates=["date"]).set_index("date").sort_index()
    if history.index.has_duplicates or future.index.has_duplicates:
        raise ValueError("Duplicate history or forecast dates")
    if "precipitation_mm" not in history and "rain_era5_mm" in history:
        history = history.rename(columns={"rain_era5_mm": "precipitation_mm"})
    inputs = build_inputs(history, future, args.issue_date, cfg, checkpoint["statistics"])
    model = HindcastForecastLSTM(cfg, *checkpoint["dimensions"]).eval()
    model.load_state_dict(checkpoint["model_state"])
    with torch.no_grad():
        quantiles = inverse_flow(model(*inputs).numpy()[0], checkpoint["statistics"])
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("Choose a new forecast output file")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame({"issue_date": args.issue_date, "valid_date": future.index, "lead_day": np.arange(1, 16)})
    for j, quantile in enumerate(cfg["model"]["quantiles"]):
        result[f"q{int(quantile*100):02d}_cumecs"] = quantiles[:, j]
    result.to_csv(output, index=False)
    save_json(output.with_suffix(".manifest.json"), {
        "checkpoint": str(checkpoint_path), "checkpoint_sha256": sha(checkpoint_path), "whole_horizon_output_shape": list(quantiles.shape),
        "trained_on_archived_forecasts": cfg["data"]["forecast_mode"] == "archived_forecast",
        "warning": "Trained on realized reanalysis plus artificial noise. Operational forecast skill is unverified.",
        "history_sha256": sha(args.history), "forecast_sha256": sha(args.forecast),
        "availability_provided": "available_at" in future,
        "past_discharge_issue_cutoff": "Only observations through issue day are read; source reading-time assumptions still apply"})
    print(f"Saved all 15 leads to {output}")


if __name__ == "__main__":
    main()
