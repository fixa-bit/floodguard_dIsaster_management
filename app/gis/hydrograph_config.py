import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.gis.river_stations import STATIONS


class Thresholds(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    low: float | None = Field(default=None, ge=0)
    medium: float | None = Field(default=None, ge=0)
    high: float | None = Field(default=None, ge=0)
    veryHigh: float | None = Field(default=None, ge=0)
    exceptional: float | None = Field(default=None, ge=0)


class HighestRecorded(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    value: float | None = Field(default=None, ge=0)
    date: str | None = None


class HydrographStation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    station_id: str
    name: str
    river: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    glofas_lat: float = Field(ge=-90, le=90)
    glofas_lon: float = Field(ge=-180, le=180)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    highestRecorded: HighestRecorded = Field(default_factory=HighestRecorded)


def station_configs():
    # Existing monitored stations remain selectable, with explicitly unverified cells.
    configs = {row[0]: HydrographStation(station_id=row[0], name=row[1], river=row[2], lat=row[3], lon=row[4],
                                       glofas_lat=row[3], glofas_lon=row[4]) for row in STATIONS}
    payload = json.loads(Path(__file__).with_name("hydrograph_stations.json").read_text(encoding="utf-8"))
    for item in payload["stations"]:
        config = HydrographStation.model_validate(item)
        configs[config.station_id] = config
    return configs
