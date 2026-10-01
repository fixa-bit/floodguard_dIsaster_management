from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.enums import DataMode, Scenario
from app.core.exceptions import AppError
from app.providers.live.live_weather_provider import LiveWeatherProvider
from app.providers.live.live_river_provider import LiveRiverProvider
from app.providers.simulation.simulation_weather_provider import SimulationWeatherProvider
from app.services.river_service import get_river_provider
from app.services.weather_service import get_weather_provider


def weather_payload() -> dict:
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
    times = [(start + timedelta(hours=index)).replace(tzinfo=None).isoformat(timespec="minutes") for index in range(50)]
    return {
        "hourly": {
            "time": times,
            "precipitation": [1.0] * 50,
            "temperature_2m": [27.0] * 50,
            "relative_humidity_2m": [81.0] * 50,
            "soil_moisture_0_to_7cm": [0.42] * 50,
        }
    }


def test_weather_provider_selection():
    assert isinstance(get_weather_provider(DataMode.SIMULATION), SimulationWeatherProvider)
    assert isinstance(get_weather_provider(DataMode.HYBRID), LiveWeatherProvider)
    assert isinstance(get_weather_provider(DataMode.LIVE), LiveWeatherProvider)


@pytest.mark.asyncio
async def test_live_weather_normalizes_to_existing_schema():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=weather_payload()))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await LiveWeatherProvider(client).get_current("JHG_001", Scenario.NORMAL)

    assert result.source == "live"
    assert result.location_id == "JHG_001"
    assert result.rainfall_last_1h_mm == 1.0
    assert result.rainfall_last_6h_mm == 6.0
    assert result.rainfall_last_24h_mm == 24.0
    assert result.forecast_rainfall_next_24h_mm == 24.0
    assert result.soil_moisture_percent == 42.0


@pytest.mark.asyncio
async def test_live_weather_failure_is_clear_provider_error():
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as error:
            await LiveWeatherProvider(client).get_current("JHG_001", Scenario.NORMAL)

    assert error.value.code == "WEATHER_PROVIDER_ERROR"
    assert error.value.status_code == 502


def test_operational_modes_use_live_river_provider():
    assert isinstance(get_river_provider(DataMode.HYBRID), LiveRiverProvider)
    assert isinstance(get_river_provider(DataMode.LIVE), LiveRiverProvider)


def river_payload() -> dict:
    start = datetime.now(timezone.utc).date() - timedelta(days=7)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(14)]
    values = [100.0] * 7 + [200.0, 210.0, 215.0, 220.0, 225.0, 230.0, 235.0]
    return {"daily": {"time": dates, "river_discharge": values}}


@pytest.mark.asyncio
async def test_live_river_uses_discharge_without_inventing_water_level():
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=river_payload()))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)

    assert result.source == "live"
    assert result.discharge_cumecs == 200.0
    assert result.discharge_change_cumecs_per_day == 100.0
    assert result.forecast_discharge_next_24h_cumecs == 210.0
    assert result.river_level_m is None
    assert result.warning_level_m is None
    assert result.status == "RISING"


@pytest.mark.asyncio
async def test_live_river_failure_is_clear_provider_error():
    transport = httpx.MockTransport(lambda _: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(AppError) as error:
            await LiveRiverProvider(client).get_current("JHG_001", Scenario.NORMAL)

    assert error.value.code == "RIVER_PROVIDER_ERROR"
    assert error.value.status_code == 502
