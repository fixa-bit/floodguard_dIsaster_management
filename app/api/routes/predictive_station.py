"""API for the Marala measured-gauge forecast (1, 3 and 7 days).

Forecasts are re-run against the latest fresh FFD readings saved by river
monitoring. The sealed hindcast and skill metrics remain read-only artifacts.
"""
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.river_gauge_observation import TypedRiverGaugeObservation
from app.services.marala_forward_forecast import build_forward_forecast, daily_history_from_readings

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


def _recent_marala_readings(now: datetime) -> list[TypedRiverGaugeObservation]:
    with SessionLocal() as db:
        return list(db.scalars(select(TypedRiverGaugeObservation).where(
            TypedRiverGaugeObservation.station_id == "MARALA",
            TypedRiverGaugeObservation.recorded_at >= now - timedelta(days=30),
            TypedRiverGaugeObservation.recorded_at <= now,
            TypedRiverGaugeObservation.gauge.in_(("INFLOW", "OUTFLOW")),
        )).all())


def build_payload() -> dict:
    card = _read_json(ARTIFACTS / "model-card.json")
    latest = _read_json(ARTIFACTS / "latest_predictions.json")
    config = _read_json(MODEL_DIR / "config.json")
    run = _read_json(MODEL_DIR / "LATEST_RUN.json")
    observations = _read_csv(MODEL_DIR / "data/observations.csv")
    holdout = _read_csv(ARTIFACTS / "holdout_predictions_2026.csv")

    now = datetime.now(timezone.utc)
    live_history = daily_history_from_readings(_recent_marala_readings(now))
    live_forecast = build_forward_forecast(live_history, ARTIFACTS, now)
    forecasts: dict[int, dict] = {}
    if live_forecast:
        for item in live_forecast["forecasts"]:
            lead = int(item["horizon_days"])
            forecasts[lead] = {"horizon_days": lead, "target_at": item["target_at"]}
            forecasts[lead]["candidates"] = [{
                "rank": candidate["rank"],
                "candidate": candidate["candidate"],
                "family": candidate["family"],
                "validation_rmse_cumecs": round(candidate["validation_rmse_cumecs"], 2),
                "validation_mae_cumecs": round(candidate["validation_mae_cumecs"], 2),
                "inflow_cumecs": round(candidate["predicted_inflow_cumecs"], 2),
            } for candidate in item["candidates"]]
            for role in ("champion", "best_learned"):
                candidate = item[role]
                forecasts[lead][role] = {"candidate": candidate["candidate"],
                                         "inflow_cumecs": round(candidate["predicted_inflow_cumecs"], 2)}
        origin = live_forecast["origin"]
        computed_at = now.isoformat()
    else:
        for item in latest["predictions"]:
            lead = int(item["horizon_days"])
            entry = forecasts.setdefault(lead, {"horizon_days": lead, "target_at": item["target_at"]})
            entry[item["candidate_role"]] = {"candidate": item["candidate"],
                                             "inflow_cumecs": round(item["predicted_inflow_cumecs"], 2)}
        for entry in forecasts.values():
            candidates = []
            seen = set()
            for role in ("champion", "best_learned"):
                candidate = entry.get(role)
                if candidate and candidate["candidate"] not in seen:
                    seen.add(candidate["candidate"])
                    candidates.append({"rank": len(candidates) + 1, **candidate})
            entry["candidates"] = candidates
        origin = {"observed_at": latest["predictions"][0]["origin_observed_at"],
                  "inflow_cumecs": latest["predictions"][0]["last_measured_inflow_cumecs"],
                  "source_url": latest["origin_source"]}
        computed_at = latest["computed_at"]

    history_by_date = {row["date"]: row for row in observations}
    history_by_date.update({day.isoformat(): row for day, row in live_history.items()})
    history = sorted(history_by_date.values(), key=lambda row: row["observed_at"])

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
        "computed_at": computed_at,
        "forecast_mode": "rolling_live_origin" if live_forecast else "saved_snapshot",
        "run_id": run["run_id"],
        "target": card["target"],
        "station": {"id": config["station_id"], "name": "Marala", "river": "Chenab"},
        "data": {key: card["data"][key] for key in ("measured_days", "years", "first_day", "last_day")},
        "evaluation": {"selection": card["model_selection"], "test": card["evaluation"],
                       "production_refit": card["production_refit"]},
        "thresholds_cumecs": {name: round(value * CUSECS_TO_CUMECS, 1)
                              for name, value in config["thresholds_cusecs"].items()},
        "threshold_source": config["threshold_source"],
        "origin": {"observed_at": origin["observed_at"],
                   "inflow_cumecs": round(origin["inflow_cumecs"], 2),
                   "source_url": origin["source_url"]},
        "history": [{"observed_at": row["observed_at"], "inflow_cumecs": _float(row["inflow_cumecs"]),
                     "source_url": row["source_url"]} for row in history[-HISTORY_DAYS:]],
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
