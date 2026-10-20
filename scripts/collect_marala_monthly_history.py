"""Save 24 complete historical flow months preceding the saved forecast issue."""
import calendar
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "app/ml/marala_pilot/artifacts/seasonal"


def aggregate_months(payload, start, end):
    days = payload["daily"]["time"]
    values = payload["daily"]["river_discharge"]
    if len(days) != len(values) or len(set(days)) != len(days):
        raise ValueError("Historical dates and values must match without duplicates")
    expected = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    if days != expected:
        raise ValueError("Historical response does not cover the requested daily period")
    grouped = defaultdict(list)
    for day, value in zip(days, values, strict=True):
        if value is None or not math.isfinite(value) or value < 0:
            raise ValueError(f"Missing or invalid daily discharge: {day}")
        grouped[day[:7]].append(value)
    rows = []
    for month, values in sorted(grouped.items()):
        year, number = map(int, month.split("-"))
        if len(values) != calendar.monthrange(year, number)[1]:
            raise ValueError(f"Incomplete month: {month}")
        rows.append({"month": month, "days": len(values), "flow_mean_cumecs": sum(values) / len(values)})
    if len(rows) != 24:
        raise ValueError("Expected exactly 24 complete historical months")
    return rows


def main():
    forecast = json.loads((ARTIFACTS / "current_provider_outlook.json").read_text(encoding="utf-8"))
    issue = date.fromisoformat(forecast["forecast_issue_start"])
    end = issue.replace(day=1) - timedelta(days=1)
    first_index = end.year * 12 + end.month - 1 - 23
    start = date(first_index // 12, first_index % 12 + 1, 1)
    response = httpx.get("https://flood-api.open-meteo.com/v1/flood", params={
        "latitude": 32.675, "longitude": 74.425,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "river_discharge", "cell_selection": "nearest", "timezone": "GMT",
    }, timeout=90, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    grid = forecast["source_grid"]
    if abs(payload["latitude"] - grid["latitude"]) > 0.0001 or abs(payload["longitude"] - grid["longitude"]) > 0.0001:
        raise ValueError("Historical and forecast grid cells differ")
    if payload["daily_units"]["river_discharge"] != "m³/s":
        raise ValueError("Unexpected historical discharge units")
    rows = aggregate_months(payload, start, end)
    artifact = {
        "station_id": "MARALA", "river": "Chenab", "station_observation": False,
        "kind": "historical_modeled_discharge", "source": "Open-Meteo Flood API / GloFAS seamless",
        "documentation": "https://open-meteo.com/en/docs/flood-api",
        "source_url": str(response.url), "response_sha256": hashlib.sha256(response.content).hexdigest(),
        "source_grid": {"latitude": payload["latitude"], "longitude": payload["longitude"]},
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "aggregation": "Arithmetic mean of all daily river_discharge values per complete UTC calendar month",
        "limitations": "Provider historical modeled river flow, not measured Marala gauge observations. Seamless data may combine historical model products.",
        "monthly_records": len(rows), "monthly": rows,
    }
    (ARTIFACTS / "recent_history_daily.json").write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    (ARTIFACTS / "recent_monthly_history.json").write_text(json.dumps(artifact, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved {len(rows)} historical modeled-flow months: {rows[0]['month']} to {rows[-1]['month']}")


if __name__ == "__main__":
    main()
