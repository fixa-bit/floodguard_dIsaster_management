"""Replaceable daily-report adapter. Current verified HTML adapter is FFD, not IRSA."""
from datetime import datetime, timezone
import math
import re

from app.gis.hydrograph_config import station_configs
from app.services.ffd_bulletin_service import BulletinParser, parse_bulletin


def parse_report(html: str, source_url: str) -> list[dict]:
    validated = parse_bulletin(html)
    parser = BulletinParser()
    parser.feed(html)
    names = {station.name: station.station_id for station in station_configs().values()}
    names.update({"Punjnad": "PANJNAD", "G.S. Wala": "GANDA_SINGH_WALA"})
    readings = []
    for row in parser.rows:
        station_id = names.get(row["station"])
        sample = validated[row["station"]]["samples"].get("INFLOW")
        raw = row.get("inflow", "").strip()
        if not station_id or not sample or not re.fullmatch(r"\d+(?:\.\d+)?", raw):
            continue
        value = float(raw) * 1000
        if not math.isfinite(value):
            continue
        readings.append({"station_id": station_id, "observed_at": datetime.fromisoformat(sample["time"]).astimezone(timezone.utc),
                         "discharge_cusecs": value, "source": f"FFD bulletin inflow | {sample.get('source') or source_url}"})
    if not readings:
        raise ValueError("No recognized daily inflow observations")
    return readings
