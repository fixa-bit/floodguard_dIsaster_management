import json
from pathlib import Path

from sqlalchemy import select

from .models import Provider, Station, Threshold


def seed(session):
    for code, name, kind in [
        ("FFD", "Flood Forecasting Division", "api"), ("IRSA", "IRSA", "api"),
        ("WAPDA", "WAPDA", "api"), ("GLOFAS", "GloFAS via Open-Meteo", "api"),
        ("GEOGLOWS", "GEOGLOWS", "api"), ("MANUAL", "Imported readings", "import"),
    ]:
        if session.scalar(select(Provider).where(Provider.code == code)) is None:
            session.add(Provider(code=code, name=name, kind=kind))
    for hazard in ["Riverine", "Flash flood", "Coastal"]:
        for horizon in ["Short", "Long"]:
            code = f"PLANNED_{hazard.upper().replace(' ', '_')}_{horizon.upper()}"
            if session.scalar(select(Provider).where(Provider.code == code)) is None:
                session.add(Provider(code=code, name=f"{hazard} / {horizon.lower()} range (planned)",
                                     kind="model", model_version=None))
    path = Path(__file__).resolve().parent / "config/stations.json"
    for item in json.loads(path.read_text(encoding="utf-8"))["stations"]:
        if session.scalar(select(Station).where(Station.code == item["station_id"])) is None:
            session.add(Station(code=item["station_id"], name=item["name"], river=item["river"],
                                latitude=item["lat"], longitude=item["lon"]))
    session.flush()
    # These are empty reference slots, not claims of verified official limits.
    for station in session.scalars(select(Station)):
        for measurement, unit in [("discharge_inflow", "cusecs"), ("discharge_outflow", "cusecs"),
                                  ("water_level", "m")]:
            for level in ["warning", "danger"]:
                existing = session.scalar(select(Threshold).where(
                    Threshold.station_id == station.id, Threshold.measurement == measurement,
                    Threshold.unit == unit, Threshold.level == level))
                if existing is None:
                    session.add(Threshold(station_id=station.id, measurement=measurement, unit=unit,
                                          level=level, value=None))
