import csv
import math
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.gis.hydrograph_config import station_configs
from app.models.station_observation import StationObservation
from app.providers.irsa_report_parser import parse_report


def store_readings(db, readings):
    known = station_configs()
    # Validate the entire batch before writing; a broken file cannot partly replace data.
    checked = []
    for row in readings:
        timestamp = row["observed_at"]
        value = float(row["discharge_cusecs"])
        source = str(row["source"]).strip()
        if row["station_id"] not in known or not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("Unknown station or missing observation timezone")
        if not math.isfinite(value) or value < 0 or not source or len(source) > 500 or timestamp > datetime.now(timezone.utc) + timedelta(minutes=15):
            raise ValueError("Invalid observation value, source or date")
        checked.append({**row, "observed_at": timestamp.astimezone(timezone.utc), "discharge_cusecs": value, "source": source})
    try:
        for item in checked:
            existing = db.scalar(select(StationObservation).where(StationObservation.station_id == item["station_id"],
                                                                 StationObservation.observed_at == item["observed_at"]))
            if existing is None:
                db.add(StationObservation(**item))
                db.flush()
            else:
                existing.discharge_cusecs = item["discharge_cusecs"]
                existing.source = item["source"]
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(checked)


async def ingest_report(db, url):
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    return store_readings(db, parse_report(response.text, str(response.url)))


def import_csv(db, stream):
    rows = []
    reader = csv.DictReader(stream)
    required = {"station_id", "observed_at", "discharge_cusecs", "source"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("CSV requires station_id, observed_at, discharge_cusecs, source")
    for row in reader:
        rows.append({"station_id": row["station_id"].strip().upper(),
                     "observed_at": datetime.fromisoformat(row["observed_at"].strip().replace("Z", "+00:00")),
                     "discharge_cusecs": row["discharge_cusecs"], "source": row["source"]})
    return store_readings(db, rows)
