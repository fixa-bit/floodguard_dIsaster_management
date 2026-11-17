"""Read-only API for the saved Marala measured-gauge forecast (1, 3 and 7 days).

Serves the sealed outputs of ``models/marala_station_forecast``: the latest
as-of forecast, the 2026 held-out hindcast and its skill against persistence.
Nothing is retrained or re-predicted here.
"""
import csv
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/predictive/marala-station-forecast", tags=["Predictive models"])
ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "models/marala_station_forecast"
ARTIFACTS = MODEL_DIR / "artifacts"
CUSECS_TO_CUMECS = 0.028316846592
HISTORY_DAYS = 45


def _read_json(path: Path):
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Model artifact is missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Model artifact is missing: {path.name}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return round(float(value), 2)


def _metrics(block: dict) -> dict:
    keys = ("rows", "rmse_cumecs", "mae_cumecs", "bias_cumecs", "nse", "flood_events_days", "hits",
            "misses", "false_alarms", "flood_recall", "flood_precision", "peak_actual_cumecs",
            "prediction_at_peak_cumecs", "peak_error_percent", "peak_target_date", "peak_timing_error_days")
    return {key: block.get(key) for key in keys}


def build_payload() -> dict:
    card = _read_json(ARTIFACTS / "model-card.json")
    latest = _read_json(ARTIFACTS / "latest_predictions.json")
    config = _read_json(MODEL_DIR / "config.json")
    run = _read_json(MODEL_DIR / "LATEST_RUN.json")
    observations = _read_csv(MODEL_DIR / "data/observations.csv")
    holdout = _read_csv(ARTIFACTS / "holdout_predictions_2026.csv")

    forecasts: dict[int, dict] = {}
    for item in latest["predictions"]:
        lead = int(item["horizon_days"])
        entry = forecasts.setdefault(lead, {"horizon_days": lead, "target_at": item["target_at"]})
        entry[item["candidate_role"]] = {"candidate": item["candidate"],
                                         "inflow_cumecs": round(item["predicted_inflow_cumecs"], 2)}
    origin = latest["predictions"][0]

    skill = []
    for lead, result in sorted(card["results"].items(), key=lambda pair: int(pair[0])):
        champion = result["selection"]["champion"]["spec"]
        learned = result["selection"]["best_learned"]["spec"]
        skill.append({
            "horizon_days": int(lead),
            "champion": {"candidate": champion["id"], "family": champion["family"]},
            "best_learned": {"candidate": learned["id"], "family": learned["family"]},
            "test": {role: _metrics(result["test"][role]) for role in ("champion", "best_learned", "persistence")
                     if role in result["test"]},
            "rmse_improvement_over_persistence_percent": round(result["test_rmse_improvement_over_persistence_percent"], 2),
            "beats_persistence": bool(result["test_beats_persistence"]),
        })

    return {
        "model_name": card["model_name"],
        "status": card["status"],
        "deployment_eligible": card["deployment_eligible"],
        "trained_at": card["trained_at"],
        "computed_at": latest["computed_at"],
        "run_id": run["run_id"],
        "target": card["target"],
        "station": {"id": config["station_id"], "name": "Marala", "river": "Chenab"},
        "data": {key: card["data"][key] for key in ("measured_days", "years", "first_day", "last_day")},
        "evaluation": {"selection": card["model_selection"], "test": card["evaluation"],
                       "production_refit": card["production_refit"]},
        "thresholds_cumecs": {name: round(value * CUSECS_TO_CUMECS, 1)
                              for name, value in config["thresholds_cusecs"].items()},
        "threshold_source": config["threshold_source"],
        "origin": {"observed_at": origin["origin_observed_at"],
                   "inflow_cumecs": round(origin["last_measured_inflow_cumecs"], 2),
                   "source_url": latest["origin_source"]},
        "history": [{"observed_at": row["observed_at"], "inflow_cumecs": _float(row["inflow_cumecs"]),
                     "source_url": row["source_url"]} for row in observations[-HISTORY_DAYS:]],
        "forecasts": [forecasts[lead] for lead in sorted(forecasts)],
        "skill": skill,
        "holdout": [{"horizon_days": int(row["horizon_days"]), "origin_at": row["origin_observed_at"],
                     "target_at": row["target_at"], "actual": _float(row["actual_cumecs"]),
                     "champion": _float(row["champion_cumecs"]), "best_learned": _float(row["best_learned_cumecs"]),
                     "persistence": _float(row["persistence_cumecs"])} for row in holdout],
        "limitations": card["limitations"],
    }


@router.get("")
def get_marala_station_forecast():
    return build_payload()
