from datetime import date, timedelta

import httpx
import pytest

from app.schemas.upstream_forecast import HydroSeriesPoint, ProviderForecast
from app.services.upstream_forecast_service import UPSTREAM_STATIONS, UpstreamForecastService


@pytest.mark.asyncio
async def test_marala_uses_main_chenab_model_points():
    station = next(item for item in UPSTREAM_STATIONS if item["id"] == "UP_CHENAB_MARALA")
    seen = []
    today = date.today()

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/flood":
            return httpx.Response(200, json={
                "latitude": 32.675003, "longitude": 74.425,
                "daily": {"time": [today.isoformat(), (today + timedelta(days=1)).isoformat()],
                          "river_discharge": [393, 380]},
            })
        if request.url.path == "/api/v2/forecast/440499683":
            return httpx.Response(200, json={
                "datetime": [f"{today.isoformat()}T00:00:00+00:00"],
                "flow_median": [822], "metadata": {"gen_date": f"{today.isoformat()}T00:00:00+00:00"},
            })
        if request.url.path == "/api/v2/retrospectivedaily/440499683":
            return httpx.Response(200, json={"datetime": [today.isoformat()], "440499683": [800]})
        return httpx.Response(200, json={"daily": {"time": [], "precipitation_sum": [], "precipitation_probability_max": []}})

    service = UpstreamForecastService()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await service._station_forecast(client, station)

    flood_request = next(request for request in seen if request.url.path == "/v1/flood")
    assert flood_request.url.params["latitude"] == "32.675"
    assert flood_request.url.params["longitude"] == "74.425"
    assert {provider.status for provider in result.providers} == {"available"}
    assert result.providers[0].current_cumecs == 393
    assert result.providers[1].river_id == 440499683
    assert result.providers[1].current_cumecs == 800
    assert "32.675, 74.425" in result.providers[0].note
    assert result.stats["current_mean_cumecs"] == 596.5
    assert result.stats["peak_to_current_ratio"] == 1.03


def test_conflicting_zero_forecast_is_excluded_from_comparison_stats():
    service = UpstreamForecastService()
    glofas = ProviderForecast(
        provider="GloFAS", source="test", status="available", current_cumecs=40,
        peak_forecast_cumecs=50, series=[HydroSeriesPoint(time="2026-10-14", value=50, phase="forecast")], retrospective=[],
    )
    geoglows = ProviderForecast(
        provider="GEOGloWS", source="test", status="available", current_cumecs=0,
        peak_forecast_cumecs=0, series=[HydroSeriesPoint(time="2026-10-14", value=0, phase="forecast")], retrospective=[],
    )

    service._flag_conflicting_zero_flow(glofas, geoglows)
    signals, stats = service._signals(glofas, geoglows, [])

    assert glofas.status == "available"
    assert geoglows.status == "suspect"
    assert stats["current_mean_cumecs"] == 40
    assert stats["geoglows_peak_cumecs"] is None
    assert stats["peak_to_current_ratio"] == 1.25
    assert "needs review" in signals[1].basis
