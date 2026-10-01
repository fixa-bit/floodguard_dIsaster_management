from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.enums import DataMode, Scenario
from app.locations import LOCATIONS


Feature = dict[str, Any]
WATERWAYS_PATH = Path(__file__).resolve().parent / "data" / "pakistan_osm_waterways.geojson"


def _load_river_features() -> list[Feature]:
    if not WATERWAYS_PATH.exists():
        return []
    with WATERWAYS_PATH.open(encoding="utf-8") as file:
        collection = json.load(file)
    return collection.get("features", [])


WATER_BODY_FEATURES: list[Feature] = [
    ("Tarbela Reservoir", "dam_reservoir", 72.698, 34.088, "Indus", "WAPDA project; operational reservoir, not a live reading in this layer."),
    ("Mangla Reservoir", "dam_reservoir", 73.645, 33.142, "Jhelum", "WAPDA project; operational reservoir, not a live reading in this layer."),
    ("Warsak Dam", "dam", 71.37, 34.16, "Kabul", "Dam and reservoir reference point."),
    ("Chashma Barrage", "barrage", 71.381, 32.431, "Indus", "Barrage reference point and known flow-control structure."),
    ("Kalabagh Barrage", "barrage", 71.55, 32.96, "Indus", "Barrage reference point and known flow-control structure."),
    ("Taunsa Barrage", "barrage", 70.848, 30.704, "Indus", "Barrage reference point and known flow-control structure."),
    ("Guddu Barrage", "barrage", 69.706, 28.421, "Indus", "Barrage reference point and known flow-control structure."),
    ("Sukkur Barrage", "barrage", 68.859, 27.692, "Indus", "Barrage reference point and known flow-control structure."),
    ("Kotri Barrage", "barrage", 68.307, 25.366, "Indus", "Barrage reference point and known flow-control structure."),
    ("Rawal Lake", "reservoir", 73.12, 33.70, "Korang", "Reservoir reference point near Islamabad."),
]


OBSERVED_STATIONS: list[tuple[str, str, str, float, float, str, str]] = [
    ("Indus at Tarbela", "Indus", "dam_gauge", 34.088, 72.698, "FFD/WAPDA operational network", "Public summaries report Tarbela dam level/flows; current station readings require official feed access."),
    ("Indus at Kalabagh", "Indus", "barrage_gauge", 32.96, 71.55, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Indus at Chashma", "Indus", "barrage_gauge", 32.431, 71.381, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Indus at Taunsa", "Indus", "barrage_gauge", 30.704, 70.848, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Indus at Guddu", "Indus", "barrage_gauge", 28.421, 69.706, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Indus at Sukkur", "Indus", "barrage_gauge", 27.692, 68.859, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Indus at Kotri", "Indus", "barrage_gauge", 25.366, 68.307, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Kabul at Nowshera", "Kabul", "river_gauge", 34.015, 71.975, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Jhelum at Mangla", "Jhelum", "dam_gauge", 33.142, 73.645, "FFD/WAPDA operational network", "Public summaries report Mangla dam level/flows; current station readings require official feed access."),
    ("Jhelum at Rasul", "Jhelum", "headworks_gauge", 32.683, 73.517, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Chenab at Marala", "Chenab", "headworks_gauge", 32.675, 74.464, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Chenab at Khanki", "Chenab", "headworks_gauge", 32.404, 73.974, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Chenab at Qadirabad", "Chenab", "barrage_gauge", 32.319, 73.589, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Chenab at Trimmu", "Chenab", "barrage_gauge", 31.145, 72.147, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Ravi at Balloki", "Ravi", "headworks_gauge", 31.225, 73.861, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Sutlej at Sulemanki", "Sutlej", "headworks_gauge", 30.379, 73.885, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
    ("Panjnad Headworks", "Panjnad", "headworks_gauge", 29.347, 71.034, "FFD/WAPDA/provincial irrigation", "Flood Forecasting Division river-state monitoring station."),
]


def _point_feature(feature_id: str, longitude: float, latitude: float, properties: dict[str, Any]) -> Feature:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": properties,
    }


def _with_feature_type(raw: Feature) -> Feature:
    feature = deepcopy(raw)
    feature["type"] = "Feature"
    return feature


def _geometry_intersects_bbox(geometry: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox

    def point_in_bbox(coordinate: list[float]) -> bool:
        lon, lat = coordinate[:2]
        return west <= lon <= east and south <= lat <= north

    def line_in_bbox(line: list[list[float]]) -> bool:
        return any(point_in_bbox(coordinate) for coordinate in line)

    if geometry["type"] == "Point":
        return point_in_bbox(geometry["coordinates"])
    if geometry["type"] == "LineString":
        return line_in_bbox(geometry["coordinates"])
    if geometry["type"] == "MultiLineString":
        return any(line_in_bbox(line) for line in geometry["coordinates"])
    return True


class WaterIntelligenceService:
    def feature_collection(
        self,
        data_mode: DataMode,
        scenario: Scenario,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        features = self._features(data_mode, scenario)
        filtered = [feature for feature in features if bbox is None or _geometry_intersects_bbox(feature["geometry"], bbox)]
        station_count = sum(1 for feature in features if feature["properties"]["data_class"] == "observed_station")
        forecast_count = sum(1 for feature in features if feature["properties"]["data_class"] == "model_forecast")
        water_feature_count = sum(1 for feature in features if feature["properties"]["data_class"] == "gis_feature")
        return {
            "type": "FeatureCollection",
            "metadata": {
                "coverage": "Pakistan river corridors, major barrages, dams, reservoirs, and monitoring points",
                "feature_count": len(features),
                "returned_feature_count": len(filtered),
                "water_feature_count": water_feature_count,
                "observed_station_count": station_count,
                "model_forecast_count": forecast_count,
                "generated_at": generated_at,
                "data_mode": data_mode.value,
                "scenario": scenario.value,
                "methodology": "GIS reference features are separated from observed stations and model forecast points; observed station features do not include fabricated readings.",
                "source_summary": "WaterwayMap/OpenStreetMap river geometry; FFD Lahore public river-state pages; WAPDA/provincial irrigation station network summaries; Open-Meteo GloFAS for modeled discharge hooks.",
                "map_notice": "River alignments are schematic unless source geometry is marked official.",
                "public_live_reading_note": "Official FFD public pages expose river-state summaries, but this app does not currently ingest an authenticated/current observed gauge API.",
                "forecast_provider": get_settings().flood_api_base_url,
            },
            "features": filtered,
        }

    def _features(self, data_mode: DataMode, scenario: Scenario) -> list[Feature]:
        features: list[Feature] = [_with_feature_type(feature) for feature in _load_river_features()]
        features.extend(
            _point_feature(
                f"water_body_{name.lower().replace(' ', '_')}",
                longitude,
                latitude,
                {
                    "name": name,
                    "water_system": river,
                    "feature_kind": kind,
                    "data_class": "gis_feature",
                    "data_status": "GIS reference feature",
                    "telemetry_status": "not_station",
                    "coordinate_quality": "approximate",
                    "geometry_source": "curated reference point",
                    "geometry_quality": "approximate",
                    "description": description,
                },
            )
            for name, kind, longitude, latitude, river, description in WATER_BODY_FEATURES
        )
        features.extend(
            _point_feature(
                f"observed_station_{name.lower().replace(' ', '_').replace('/', '_')}",
                longitude,
                latitude,
                {
                    "name": name,
                    "water_system": river,
                    "feature_kind": station_type,
                    "data_class": "observed_station",
                    "data_status": "Observed monitoring station metadata",
                    "telemetry_status": "station_known_current_reading_not_ingested",
                    "coordinate_quality": "approximate",
                    "observed_level_m": None,
                    "observed_discharge_cumecs": None,
                    "forecast_discharge_cumecs": None,
                    "source": source,
                    "description": description,
                },
            )
            for name, river, station_type, latitude, longitude, source, description in OBSERVED_STATIONS
        )
        features.extend(self._model_forecast_points(data_mode, scenario))
        return features

    def _model_forecast_points(self, data_mode: DataMode, scenario: Scenario) -> list[Feature]:
        source = "simulation scenario" if data_mode == DataMode.SIMULATION else "Open-Meteo GloFAS public Flood API"
        return [
            _point_feature(
                f"model_forecast_{location.id.lower()}",
                location.river_longitude or location.longitude,
                location.river_latitude or location.latitude,
                {
                    "name": f"{location.river_station_name or location.name} model point",
                    "location_id": location.id,
                    "water_system": location.river_name or "Nearest modeled river",
                    "feature_kind": "model_grid_point",
                    "data_class": "model_forecast",
                    "data_status": "Forecast/model generated value",
                    "telemetry_status": "not_observed_gauge",
                    "coordinate_quality": "derived",
                    "observed_level_m": None,
                    "observed_discharge_cumecs": None,
                    "forecast_discharge_cumecs": None,
                    "source": source,
                    "scenario": scenario.value,
                    "details_endpoint": f"/api/v1/river/current?location_id={location.id}",
                    "description": "Model or simulation point used by the portal river-risk component. Treat separately from observed gauge telemetry.",
                },
            )
            for location in LOCATIONS.values()
        ]
