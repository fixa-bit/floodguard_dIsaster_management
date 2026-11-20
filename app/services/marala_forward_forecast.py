"""Create current-as-of Marala forecasts from the application's stored FFD readings."""

import csv
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from models.marala_station_forecast.core import (
    build_rows,
    candidate_specs,
    feature_row,
    fit,
    load_observations,
    predict,
)

PKT = timezone(timedelta(hours=5))
MAX_ORIGIN_AGE = timedelta(hours=24)
HORIZONS_DAYS = (1, 3, 7)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def daily_history_from_readings(readings: Iterable[object]) -> dict[date, dict]:
    """Group paired typed gauge records into the model's daily FFD input format."""
    paired: dict[date, dict[str, tuple[datetime, float, str]]] = {}
    for reading in readings:
        if getattr(reading, "station_id", None) != "MARALA":
            continue
        gauge = getattr(reading, "gauge", None)
        if gauge not in {"INFLOW", "OUTFLOW"}:
            continue
        recorded_at = _utc(reading.recorded_at).astimezone(PKT)
        if recorded_at.timetz().replace(tzinfo=None) != time(6, 0):
            continue
        value = float(reading.discharge_cumecs)
        if value < 0:
            continue
        day = recorded_at.date()
        source = str(getattr(reading, "source", "") or "")
        current = paired.setdefault(day, {}).get(gauge)
        if current is None or recorded_at > current[0]:
            paired[day][gauge] = (recorded_at, value, source)

    history = {}
    for day, gauges in sorted(paired.items()):
        if "INFLOW" not in gauges or "OUTFLOW" not in gauges:
            continue
        observed_at, inflow, source = gauges["INFLOW"]
        if observed_at != gauges["OUTFLOW"][0] or urlparse(source).hostname != "ffd.pmd.gov.pk":
            continue
        history[day] = {
            "station_id": "MARALA",
            "date": day.isoformat(),
            "observed_at": observed_at.isoformat(),
            "inflow_cumecs": inflow,
            "outflow_cumecs": gauges["OUTFLOW"][1],
            "measurement_kind": "FFD_reported_observation",
            "source_url": source,
        }
    return history


@lru_cache(maxsize=3)
def _fit_top_validation_models(artifacts_path: str, observations_mtime: int, leaderboard_mtime: int) -> dict[int, list[dict]]:
    """Refit the five validation leaders on all available training history, once per artifact revision."""
    artifacts = Path(artifacts_path)
    model_dir = artifacts.parent
    history_path = model_dir / "data" / "observations.csv"
    leaderboard_path = artifacts / "validation_leaderboard.csv"
    history, _ = load_observations([history_path])
    spec_by_id = {spec["id"]: spec for spec in candidate_specs()}
    ranked: dict[int, list[dict]] = {horizon: [] for horizon in HORIZONS_DAYS}
    with leaderboard_path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            if raw["status"] != "valid":
                continue
            horizon = int(raw["horizon_days"])
            if horizon not in ranked:
                continue
            ranked[horizon].append({
                "spec": spec_by_id[raw["candidate"]],
                "validation_rmse_cumecs": float(raw["validation_rmse_cumecs"]),
                "validation_mae_cumecs": float(raw["validation_mae_cumecs"]),
            })

    models: dict[int, list[dict]] = {}
    for horizon, candidates in ranked.items():
        candidates.sort(key=lambda item: (
            item["validation_rmse_cumecs"], item["validation_mae_cumecs"], item["spec"]["id"]
        ))
        rows, _ = build_rows(history, horizon)
        selected = []
        for rank, candidate in enumerate(candidates[:5], start=1):
            model = fit(candidate["spec"], rows, horizon)
            model.update(
                validation_rank=rank,
                validation_rmse_cumecs=candidate["validation_rmse_cumecs"],
                validation_mae_cumecs=candidate["validation_mae_cumecs"],
            )
            selected.append(model)
        if len(selected) != 5:
            raise ValueError(f"Expected five valid validation candidates for the {horizon}-day forecast")
        models[horizon] = selected
    return models


def _top_validation_models(artifacts: Path) -> dict[int, list[dict]]:
    model_dir = artifacts.parent
    observations = model_dir / "data" / "observations.csv"
    leaderboard = artifacts / "validation_leaderboard.csv"
    return _fit_top_validation_models(
        str(artifacts.resolve()),
        observations.stat().st_mtime_ns,
        leaderboard.stat().st_mtime_ns,
    )


def build_forward_forecast(history: dict[date, dict], artifacts: Path, now: datetime | None = None) -> dict | None:
    """Forecast +1/+3/+7 days only from a fresh 06:00 FFD origin with yesterday's gauge pair."""
    if not history:
        return None
    now_utc = _utc(now or datetime.now(timezone.utc))
    issue_day = max(history)
    previous_day = issue_day - timedelta(days=1)
    if previous_day not in history:
        return None
    row = feature_row(history, issue_day)
    issued_at = datetime.fromisoformat(row["issued_at"])
    age = now_utc - _utc(issued_at)
    if age < timedelta(0) or age >= MAX_ORIGIN_AGE:
        return None

    candidate_models = _top_validation_models(Path(artifacts))
    forecasts = []
    for horizon in HORIZONS_DAYS:
        candidates = []
        for model in candidate_models[horizon]:
            training_last_target = datetime.fromisoformat(model["training_last_target"])
            if _utc(training_last_target) > _utc(issued_at):
                return None
            value = float(predict(model, [row])[0])
            candidates.append({
                "rank": model["validation_rank"],
                "candidate": model["spec"]["id"],
                "family": model["spec"]["family"],
                "validation_rmse_cumecs": model["validation_rmse_cumecs"],
                "validation_mae_cumecs": model["validation_mae_cumecs"],
                "predicted_inflow_cumecs": value,
            })
        best_learned = next((candidate for candidate in candidates if candidate["family"] in {"ridge", "xgboost"}), candidates[0])
        forecasts.append({
            "horizon_days": horizon,
            "target_at": (issued_at + timedelta(days=horizon)).isoformat(),
            "origin_observed_at": issued_at.isoformat(),
            "last_measured_inflow_cumecs": float(row["current_cumecs"]),
            "candidates": candidates,
            "champion": candidates[0],
            "best_learned": best_learned,
        })

    return {
        "origin": {
            "observed_at": issued_at.isoformat(),
            "inflow_cumecs": float(row["current_cumecs"]),
            "source_url": row["source_url"],
        },
        "forecasts": forecasts,
    }
