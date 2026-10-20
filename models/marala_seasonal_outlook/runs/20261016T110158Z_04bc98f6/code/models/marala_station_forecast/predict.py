"""Predict future 06:00 Marala inflows from a verified gauge history snapshot."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .core import HERE, feature_row, load_model, load_observations, predict


def forecast(observations=HERE / "data/observations.csv", artifacts=HERE / "artifacts", as_of=None, role="champion"):
    history, _ = load_observations([observations])
    origin = date.fromisoformat(as_of) if as_of else max(history)
    row = feature_row(history, origin)
    predictions = []
    for horizon in (1, 3, 7):
        model = load_model(Path(artifacts) / "models" / f"{horizon}d" / role)
        if datetime.fromisoformat(model["training_last_target"]) > datetime.fromisoformat(row["issued_at"]):
            raise ValueError("This fit includes labels after the requested origin; use the saved evaluation models for historical testing")
        value = float(predict(model, [row])[0])
        predictions.append({"horizon_days": horizon, "candidate": model["spec"]["id"],
                            "target_at": (datetime.fromisoformat(row["issued_at"]) + timedelta(days=horizon)).isoformat(),
                            "predicted_inflow_cumecs": value, "target_kind": "instantaneous_reported_gauge_inflow_at_0600_PKT"})
    return {"station_id": "MARALA", "computed_at": datetime.now(timezone.utc).isoformat(),
            "origin_observed_at": row["issued_at"], "origin_source": row["source_url"],
            "last_measured_inflow_cumecs": row["current_cumecs"], "research_only": True,
            "note": "Measurement time is not guaranteed publication time. These are as-of forecasts, not a live feed or flood probability.",
            "predictions": predictions}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, default=HERE / "data/observations.csv")
    parser.add_argument("--artifacts", type=Path, default=HERE / "artifacts")
    parser.add_argument("--as-of", help="Origin observation date, YYYY-MM-DD; defaults to latest supplied measurement")
    parser.add_argument("--role", choices=["champion", "best_learned"], default="champion")
    args = parser.parse_args()
    print(json.dumps(forecast(args.observations, args.artifacts, args.as_of, args.role), indent=2, allow_nan=False))
