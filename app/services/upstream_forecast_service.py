import asyncio
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.upstream_forecast import (
    FloodTypeSignal,
    HydroSeriesPoint,
    ProviderForecast,
    RainfallPoint,
    UpstreamForecastResponse,
    UpstreamStationForecast,
)


UPSTREAM_STATIONS = [
    {
        "id": "UP_INDUS_BESHAM",
        "name": "Besham Upper Indus",
        "river": "Indus",
        "basin": "Upper Indus",
        "latitude": 34.93,
        "longitude": 72.88,
        "geoglows_river_id": 440341343,
        "why_selected": "Northern Indus watch point upstream of Tarbela and before the main Punjab flood corridor.",
        "source_focus": "Himalaya-Karakoram snowmelt, glacial tributaries, and fast upstream routing into Tarbela.",
        "facts": [
            "Useful as an early signal before Indus flow reaches reservoir and downstream barrage operations.",
            "Model discharge here can change quickly after mountain rainfall or warm snowmelt episodes.",
            "Best interpreted as a source-basin forecast point, not an official public warning gauge.",
        ],
    },
    {
        "id": "UP_GILGIT_DANYOR",
        "name": "Danyor Gilgit River",
        "river": "Gilgit",
        "basin": "Upper Indus tributary",
        "latitude": 35.92,
        "longitude": 74.38,
        "geoglows_river_id": 440121137,
        "why_selected": "Far northern tributary station that catches Karakoram/Hindukush source-basin behavior early.",
        "source_focus": "Snowmelt, glacial meltwater, steep tributary response, and localized convective rain bursts.",
        "facts": [
            "Shows upper-basin tributary stress before water combines with the larger Indus system.",
            "Flash response risk is more important here than broad floodplain storage.",
            "Use together with local PMD/NDMA warnings where available before operational action.",
        ],
    },
    {
        "id": "UP_CHENAB_MARALA",
        "name": "Chenab Marala",
        "river": "Chenab",
        "basin": "Upper Chenab",
        "latitude": 32.675,
        "longitude": 74.464,
        "geoglows_river_id": 440400613,
        "why_selected": "Chenab entry watch point near Sialkot, upstream of Khanki and Qadirabad.",
        "source_focus": "Upper Chenab catchment rainfall, snowmelt, and upstream reservoir releases.",
        "facts": [
            "Marala Headworks is an early monitoring point for Chenab flows entering the Punjab flood corridor.",
            "Compare the modeled trend with downstream Khanki and Qadirabad observations to track flood routing.",
            "These are modeled reach forecasts near Marala, not observed headworks inflow or outflow readings.",
        ],
    },
    {
        "id": "UP_RAVI_JASSAR",
        "name": "Ravi Jassar",
        "river": "Ravi",
        "basin": "Upper Ravi",
        "latitude": 32.061389,
        "longitude": 74.839444,
        "geoglows_river_id": 440491452,
        "why_selected": "Ravi border watch point upstream of Shahdara/Lahore and Balloki.",
        "source_focus": "Upper Ravi catchment rainfall and upstream regulated flows entering Pakistan.",
        "facts": [
            "Jassar is a Ravi river observatory used for monitoring upstream flows before the Lahore corridor.",
            "Read its trend alongside Shahdara and Balloki observations to assess downstream river conditions.",
            "These are modeled reach forecasts near Jassar; local rainfall alone cannot explain upstream river inflows.",
        ],
    },
]


class UpstreamForecastService:
    DAILY_FIELDS = (
        "river_discharge,river_discharge_mean,river_discharge_median,"
        "river_discharge_max,river_discharge_min,river_discharge_p25,river_discharge_p75"
    )
    GEOGLOWS_BASE_URL = "https://geoglows.ecmwf.int/api/v2"

    def __init__(self):
        settings = get_settings()
        self.flood_api_base_url = settings.flood_api_base_url
        self.weather_api_base_url = settings.weather_api_base_url
        self.timeout = max(settings.flood_api_timeout_seconds, settings.weather_api_timeout_seconds, 12.0)

    async def forecasts(self) -> UpstreamForecastResponse:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            stations = await asyncio.gather(*(self._station_forecast(client, station) for station in UPSTREAM_STATIONS))
        return UpstreamForecastResponse(
            generated_at=datetime.now(timezone.utc).isoformat(),
            stations=list(stations),
            notes=[
                "GloFAS is read through Open-Meteo's public flood endpoint; direct CEMS EWDS access can be added when an EWDS token is configured.",
                "GEOGloWS provides public streamflow forecast, forecast uncertainty, and retrospective simulation endpoints.",
                "Rainfall is supporting hydrometeorological context, not a standalone official flood warning.",
            ],
        )

    async def _station_forecast(self, client: httpx.AsyncClient, station: dict[str, Any]) -> UpstreamStationForecast:
        glofas, geoglows, rainfall = await asyncio.gather(
            self._glofas(client, station),
            self._geoglows(client, station),
            self._rainfall(client, station),
        )
        flood_types, stats = self._signals(glofas, geoglows, rainfall)
        return UpstreamStationForecast(
            id=station["id"],
            name=station["name"],
            river=station["river"],
            basin=station["basin"],
            latitude=station["latitude"],
            longitude=station["longitude"],
            why_selected=station["why_selected"],
            source_focus=station["source_focus"],
            facts=station["facts"],
            providers=[glofas, geoglows],
            rainfall=rainfall,
            flood_types=flood_types,
            stats=stats,
        )

    async def _glofas(self, client: httpx.AsyncClient, station: dict[str, Any], payload: dict | None = None) -> ProviderForecast:
        try:
            if payload is None:
                response = await client.get(
                    self.flood_api_base_url,
                    params={
                        "latitude": station["latitude"],
                        "longitude": station["longitude"],
                        "daily": self.DAILY_FIELDS,
                        "past_days": 14,
                        "forecast_days": 14,
                        "cell_selection": "nearest",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            daily = payload["daily"]
            times = daily["time"]
            values = self._number_list(daily.get("river_discharge", []))
            lows = self._number_list(daily.get("river_discharge_p25", []))
            highs = self._number_list(daily.get("river_discharge_p75", []))
            today = datetime.now(timezone.utc).date()
            series = [
                HydroSeriesPoint(
                    time=str(item_date),
                    value=value,
                    phase="past" if item_date <= today else "forecast",
                    low=lows[index] if index < len(lows) else None,
                    high=highs[index] if index < len(highs) else None,
                )
                for index, (item_date, value) in enumerate(zip((date.fromisoformat(item) for item in times), values))
            ]
            current = self._latest_past(series)
            forecast_points = [point for point in series if point.phase == "forecast" and point.value is not None]
            peak = max(forecast_points, key=lambda point: point.value or 0, default=None)
            recent = [point.value for point in series if point.phase == "past" and point.value is not None][-7:]
            trend = round(recent[-1] - recent[0], 2) if len(recent) >= 2 else None
            return ProviderForecast(
                provider="GloFAS",
                source="Open-Meteo GloFAS 5 km grid",
                status="available",
                generated_at=datetime.now(timezone.utc).isoformat(),
                current_cumecs=current.value if current else None,
                peak_forecast_cumecs=round(peak.value, 2) if peak and peak.value is not None else None,
                peak_forecast_time=peak.time if peak else None,
                recent_trend_cumecs=trend,
                series=series,
                retrospective=[point for point in series if point.phase == "past"],
                note="Daily modeled discharge with ensemble statistics from the Open-Meteo GloFAS endpoint.",
            )
        except Exception as exc:
            return self._failed_provider("GloFAS", "Open-Meteo GloFAS 5 km grid", str(exc))

    async def _geoglows(self, client: httpx.AsyncClient, station: dict[str, Any]) -> ProviderForecast:
        river_id = station["geoglows_river_id"]
        try:
            forecast_response = await client.get(f"{self.GEOGLOWS_BASE_URL}/forecast/{river_id}", params={"format": "json"})
            forecast_response.raise_for_status()
            forecast = forecast_response.json()
            times = forecast.get("datetime", [])
            medians = self._number_list(forecast.get("flow_median", []))
            lows = self._number_list(forecast.get("flow_uncertainty_lower", []))
            highs = self._number_list(forecast.get("flow_uncertainty_upper", []))
            series = [
                HydroSeriesPoint(
                    time=str(item_time),
                    value=value,
                    phase="forecast",
                    low=lows[index] if index < len(lows) else None,
                    high=highs[index] if index < len(highs) else None,
                )
                for index, (item_time, value) in enumerate(zip(times, medians))
            ]
            retrospective = await self._geoglows_retrospective(client, river_id)
            current = retrospective[-1].value if retrospective else (series[0].value if series else None)
            peak = max((point for point in series if point.value is not None), key=lambda point: point.value or 0, default=None)
            recent = [point.value for point in retrospective if point.value is not None][-7:]
            trend = round(recent[-1] - recent[0], 2) if len(recent) >= 2 else None
            return ProviderForecast(
                provider="GEOGloWS",
                source="GEOGloWS ECMWF Streamflow Service v2",
                status="available",
                river_id=river_id,
                generated_at=forecast.get("metadata", {}).get("gen_date"),
                current_cumecs=round(current, 2) if current is not None else None,
                peak_forecast_cumecs=round(peak.value, 2) if peak and peak.value is not None else None,
                peak_forecast_time=peak.time if peak else None,
                recent_trend_cumecs=trend,
                series=series[::4],
                retrospective=retrospective,
                note="3-hour forecast guidance; chart is thinned to 12-hour points for display.",
            )
        except Exception as exc:
            return self._failed_provider("GEOGloWS", "GEOGloWS ECMWF Streamflow Service v2", str(exc), river_id)

    async def _geoglows_retrospective(self, client: httpx.AsyncClient, river_id: int) -> list[HydroSeriesPoint]:
        end = date.today()
        start = end - timedelta(days=21)
        try:
            response = await client.get(
                f"{self.GEOGLOWS_BASE_URL}/retrospectivedaily/{river_id}",
                params={"format": "json", "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")},
            )
            response.raise_for_status()
            payload = response.json()
            values = self._number_list(payload.get(str(river_id), []))
            return [
                HydroSeriesPoint(time=str(item_time), value=value, phase="past")
                for item_time, value in zip(payload.get("datetime", []), values)
            ]
        except Exception:
            return []

    async def _rainfall(self, client: httpx.AsyncClient, station: dict[str, Any]) -> list[RainfallPoint]:
        try:
            response = await client.get(
                self.weather_api_base_url,
                params={
                    "latitude": station["latitude"],
                    "longitude": station["longitude"],
                    "daily": "precipitation_sum,precipitation_probability_max",
                    "past_days": 3,
                    "forecast_days": 7,
                    "timezone": "UTC",
                },
            )
            response.raise_for_status()
            daily = response.json()["daily"]
            today = date.today()
            return [
                RainfallPoint(
                    date=str(item_date),
                    precipitation_mm=value,
                    probability_percent=probabilities[index] if index < len(probabilities) else None,
                    phase="past" if item_date <= today else "forecast",
                )
                for index, (item_date, value) in enumerate(
                    zip((date.fromisoformat(item) for item in daily.get("time", [])), self._number_list(daily.get("precipitation_sum", [])))
                )
                for probabilities in [self._number_list(daily.get("precipitation_probability_max", []))]
            ]
        except Exception:
            return []

    def _signals(
        self,
        glofas: ProviderForecast,
        geoglows: ProviderForecast,
        rainfall: list[RainfallPoint],
    ) -> tuple[list[FloodTypeSignal], dict[str, float | int | str | None]]:
        provider_peaks = [value for value in [glofas.peak_forecast_cumecs, geoglows.peak_forecast_cumecs] if value is not None]
        current_values = [value for value in [glofas.current_cumecs, geoglows.current_cumecs] if value is not None and value > 0]
        peak = max(provider_peaks, default=None)
        current = mean(current_values) if current_values else None
        peak_ratio = (peak / current) if peak is not None and current else None
        max_rain = max((point.precipitation_mm or 0 for point in rainfall if point.phase == "forecast"), default=0)
        rain_probability = max((point.probability_percent or 0 for point in rainfall if point.phase == "forecast"), default=0)
        max_step_rise = self._max_step_rise(geoglows.series)

        river_probability = self._probability_from_ratio(peak_ratio, 30, 88)
        flash_probability = min(88, int(max_step_rise * 6 + max_rain * 2.5 + rain_probability * 0.25))
        urban_probability = min(76, int(max_rain * 3 + rain_probability * 0.2))

        flood_types = [
            FloodTypeSignal(
                type="Riverine flood",
                severity=self._severity(river_probability),
                probability=river_probability,
                basis="Forecast discharge peak compared with the latest modeled/reanalysis flow.",
                lead_time="1-14 days",
            ),
            FloodTypeSignal(
                type="Flash flood",
                severity=self._severity(flash_probability),
                probability=flash_probability,
                basis="Short-step GEOGloWS rise plus forecast rainfall stress.",
                lead_time="0-72 hours",
            ),
            FloodTypeSignal(
                type="Urban/surface-water flood",
                severity=self._severity(urban_probability),
                probability=urban_probability,
                basis="Daily precipitation forecast and probability near the selected station.",
                lead_time="0-7 days",
            ),
        ]
        return flood_types, {
            "current_mean_cumecs": round(current, 2) if current is not None else None,
            "highest_provider_peak_cumecs": round(peak, 2) if peak is not None else None,
            "peak_to_current_ratio": round(peak_ratio, 2) if peak_ratio is not None else None,
            "glofas_peak_cumecs": glofas.peak_forecast_cumecs,
            "geoglows_peak_cumecs": geoglows.peak_forecast_cumecs,
            "max_forecast_rain_mm": round(max_rain, 1),
            "max_rain_probability_percent": int(rain_probability),
            "geoglows_max_step_rise_cumecs": round(max_step_rise, 2),
        }

    @staticmethod
    def _failed_provider(provider: str, source: str, message: str, river_id: int | None = None) -> ProviderForecast:
        return ProviderForecast(provider=provider, source=source, status="unavailable", river_id=river_id, series=[], retrospective=[], note=message[:180])

    @staticmethod
    def _number_list(values: list[Any]) -> list[float | None]:
        numbers: list[float | None] = []
        for value in values:
            try:
                if value == "" or value is None:
                    numbers.append(None)
                else:
                    numbers.append(round(float(value), 2))
            except (TypeError, ValueError):
                numbers.append(None)
        return numbers

    @staticmethod
    def _latest_past(series: list[HydroSeriesPoint]) -> HydroSeriesPoint | None:
        past = [point for point in series if point.phase == "past" and point.value is not None]
        return past[-1] if past else None

    @staticmethod
    def _max_step_rise(series: list[HydroSeriesPoint]) -> float:
        values = [point.value for point in series if point.value is not None]
        rises = [values[index] - values[index - 1] for index in range(1, len(values))]
        return max(rises, default=0.0)

    @staticmethod
    def _probability_from_ratio(ratio: float | None, floor: int, ceiling: int) -> int:
        if ratio is None:
            return floor
        return max(floor, min(ceiling, int(25 + ratio * 24)))

    @staticmethod
    def _severity(probability: int) -> str:
        if probability >= 75:
            return "CRITICAL"
        if probability >= 55:
            return "HIGH"
        if probability >= 35:
            return "MEDIUM"
        return "LOW"
