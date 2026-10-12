import asyncio
import math
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.gis.river_stations import RIVER_CHAINS, STATIONS, upstream_ids
from app.models.river_gauge_observation import RiverGaugeObservation, TypedRiverGaugeObservation
from app.providers.live.live_river_provider import LiveRiverProvider
from app.schemas.river_monitoring import RiverMonitoringResponse, RiverMonitoringStation
from app.schemas.upstream_forecast import RainfallPoint
from app.services.upstream_forecast_cache_service import UpstreamForecastCacheService
from app.services.upstream_forecast_service import UpstreamForecastService


class RiverMonitoringService(UpstreamForecastService):
    async def _models(self, client, definitions):
        try:
            response = await client.get(self.flood_api_base_url, params={
                "latitude": ",".join(str(station["latitude"]) for station in definitions),
                "longitude": ",".join(str(station["longitude"]) for station in definitions),
                "daily": self.DAILY_FIELDS, "past_days": 14, "forecast_days": 14, "cell_selection": "nearest",
            })
            response.raise_for_status()
            payloads = response.json()
            if not isinstance(payloads, list) or len(payloads) != len(definitions):
                raise ValueError("Flood API returned an incomplete station batch")
            return [await self._glofas(client, station, payload) for station, payload in zip(definitions, payloads)]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return [self._failed_provider("GloFAS", "Open-Meteo GloFAS 5 km grid", str(exc)) for _ in definitions]

    async def _observations(self):
        try:
            return await LiveRiverProvider()._get_ffd_stations()
        except (httpx.HTTPError, ValueError, KeyError):
            return []

    async def _rainfall_contexts(self, client, definitions) -> list[list[RainfallPoint]]:
        try:
            response = await client.get(self.weather_api_base_url, params={
                "latitude": ",".join(str(station["latitude"]) for station in definitions),
                "longitude": ",".join(str(station["longitude"]) for station in definitions),
                "daily": "precipitation_sum,precipitation_probability_max",
                "past_days": 3, "forecast_days": 7, "timezone": "UTC",
            })
            response.raise_for_status()
            payloads = response.json()
            if isinstance(payloads, dict):
                payloads = [payloads]
            if not isinstance(payloads, list) or len(payloads) != len(definitions):
                raise ValueError("Weather API returned an incomplete station rainfall batch")
            return [self._rainfall_points(payload) for payload in payloads]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return [[] for _ in definitions]

    @staticmethod
    def _rainfall_points(payload: dict) -> list[RainfallPoint]:
        daily = payload["daily"]
        today = datetime.now(timezone.utc).date()
        probabilities = UpstreamForecastService._number_list(daily.get("precipitation_probability_max", []))
        return [
            RainfallPoint(
                date=str(item_date),
                precipitation_mm=value,
                probability_percent=probabilities[index] if index < len(probabilities) else None,
                phase="past" if item_date <= today else "forecast",
            )
            for index, (item_date, value) in enumerate(
                zip((datetime.fromisoformat(item).date() for item in daily.get("time", [])),
                    UpstreamForecastService._number_list(daily.get("precipitation_sum", [])))
            )
        ]

    async def forecasts(self) -> RiverMonitoringResponse:
        definitions = [dict(id=station_id, name=name, river=river, latitude=lat, longitude=lon, ffd_name=ffd)
                       for station_id, name, river, lat, lon, ffd in STATIONS]
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            observations, models, rainfall_contexts = await asyncio.gather(
                self._observations(), self._models(client, definitions), self._rainfall_contexts(client, definitions),
            )
        ffd = {row["name"]: row for row in observations}
        stations = [self._station(definition, model, self._observation_for(definition["ffd_name"], ffd), rainfall)
                    for definition, model, rainfall in zip(definitions, models, rainfall_contexts)]
        await asyncio.to_thread(self._store_observations, stations)
        return RiverMonitoringResponse(
            generated_at=datetime.now(timezone.utc).isoformat(), stations=stations, chains=RIVER_CHAINS,
            notes=["Current readings and flood categories: FFD Lahore. Hydrographs and expected peaks: GloFAS modeled discharge.",
                   "24h change uses matching FFD observations where stored; otherwise the modeled day-over-day change is labeled separately.",
                   "Rainfall context: Open-Meteo daily precipitation near each monitoring station.",
                   "Peak time is the modeled maximum within the available forecast window, not a confirmed flood arrival time."],
        )

    @staticmethod
    def _observation_for(name, observations):
        aliases = {"Mangla": "Mangla Dam", "Rasul": "New Rasul"}
        return observations.get(name) or observations.get(aliases.get(name))

    def _station(self, definition, model, observed, rainfall: list[RainfallPoint] | None = None) -> RiverMonitoringStation:
        parser = LiveRiverProvider()
        rainfall = rainfall or []
        flood_types, stats = self._signals(model, self._failed_provider("GEOGloWS", "Not used for river monitoring", ""), rainfall)
        observed_value = parser._parse_cusecs_to_cumecs(observed.get("discharge")) if observed else None
        observed_time = parser._parse_ffd_recording_time(observed.get("recording_time")) if observed and observed_value is not None else None
        level = parser._parse_number(observed.get("level")) if observed else None
        level_time = parser._parse_ffd_recording_time(observed.get("recording_time")) if observed and level is not None and math.isfinite(level) else None
        past = [point for point in model.series if point.phase == "past" and point.value is not None]
        future = [point for point in model.series if point.phase == "forecast" and point.value is not None]
        change = round(past[-1].value - past[-2].value, 2) if len(past) > 1 else None
        gauge_time = parser._parse_ffd_recording_time(observed.get("recording_time")) if observed else None
        readings = {}
        for gauge in (observed or {}).get("gauges", []) or []:
            kind = str(gauge.get("type", "")).upper()
            value = parser._parse_cusecs_to_cumecs(gauge.get("discharge"))
            if kind in {"INFLOW", "OUTFLOW"} and value is not None and math.isfinite(value) and value >= 0 and gauge_time:
                readings[kind] = dict(gauge=kind, value=value, time=gauge_time.isoformat())
        return RiverMonitoringStation(
            gauge_readings=list(readings.values()),
            **{key: value for key, value in definition.items() if key != "ffd_name"},
            basin=definition["river"], why_selected="River monitoring network", source_focus="FFD observations and GloFAS forecast context",
            facts=[], rainfall=rainfall, flood_types=flood_types, stats=stats, providers=[model],
            current_discharge_cumecs=observed_value if observed_time else model.current_cumecs,
            current_source="FFD observed" if observed_time else "GloFAS modeled",
            observed_at=observed_time.isoformat() if observed_time else None,
            observed_level_value=level if level_time else None,
            observed_level_unit="ft" if level_time else None,
            level_source="FFD Lahore observed" if level_time else None,
            level_observed_at=level_time.isoformat() if level_time else None,
            forecast_discharge_cumecs=future[0].value if future else None,
            forecast_valid_at=future[0].time if future else None,
            change_24h_cumecs=change, change_source="GloFAS modeled 24h change",
            flood_category=self._category(observed.get("status")) if observed_time else "Unavailable",
            official_forecast_text=str(observed.get("forecast_quant") or "") or None if observed else None,
            expected_peak_at=model.peak_forecast_time, expected_peak_cumecs=model.peak_forecast_cumecs,
            upstream_station_ids=upstream_ids(definition["id"]),
        )

    @staticmethod
    def _category(status):
        return {"NORMAL": "Below low", "LOW": "Low flood", "MEDIUM": "Medium flood", "HIGH": "High flood",
                "VERY_HIGH": "Very high flood", "EX_HIGH": "Exceptionally high flood"}.get(str(status).upper(), "Unavailable")

    @staticmethod
    def _store_observations(stations):
        with SessionLocal() as db:
            for station in stations:
                for reading in station.gauge_readings:
                    key = (station.id, reading.gauge, datetime.fromisoformat(reading.time).astimezone(timezone.utc))
                    row = db.get(TypedRiverGaugeObservation, key)
                    if row is None:
                        db.add(TypedRiverGaugeObservation(station_id=key[0], gauge=key[1], recorded_at=key[2],
                                                         discharge_cumecs=reading.value, source=reading.source))
                    else:
                        row.discharge_cumecs = reading.value
                        row.source = reading.source
                if not station.observed_at:
                    continue
                recorded_at = datetime.fromisoformat(station.observed_at)
                previous = db.get(RiverGaugeObservation, (station.id, recorded_at - timedelta(hours=24)))
                if previous is not None:
                    station.change_24h_cumecs = round(station.current_discharge_cumecs - previous.discharge_cumecs, 2)
                    station.change_source = "FFD observed 24h change"
                if db.get(RiverGaugeObservation, (station.id, recorded_at)) is None:
                    db.add(RiverGaugeObservation(station_id=station.id, recorded_at=recorded_at, discharge_cumecs=station.current_discharge_cumecs))
            db.execute(delete(RiverGaugeObservation).where(RiverGaugeObservation.recorded_at < datetime.now(timezone.utc) - timedelta(days=30)).execution_options(synchronize_session=False))
            db.execute(delete(TypedRiverGaugeObservation).where(TypedRiverGaugeObservation.recorded_at < datetime.now(timezone.utc) - timedelta(days=30)).execution_options(synchronize_session=False))
            db.commit()


river_monitoring_cache = UpstreamForecastCacheService(
    forecast_factory=RiverMonitoringService, snapshot_id=3, response_model=RiverMonitoringResponse,
    refresh_minutes=get_settings().river_monitoring_refresh_minutes,
)
