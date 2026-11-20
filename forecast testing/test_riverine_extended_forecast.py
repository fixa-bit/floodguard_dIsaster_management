from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app.services import riverine_extended_forecast


@pytest.mark.asyncio
async def test_live_extended_forecast_returns_thirty_future_days(monkeypatch):
    dates = [(date.today() + timedelta(days=offset)).isoformat() for offset in range(35)]
    payload = {"daily": {"time": dates}}
    for key, base in (
        ("river_discharge_mean", 410),
        ("river_discharge_median", 400),
        ("river_discharge_p25", 350),
        ("river_discharge_p75", 450),
    ):
        payload["daily"][key] = [base + offset for offset in range(len(dates))]

    class FakeResponse:
        url = httpx.URL("https://flood-api.open-meteo.com/v1/flood?forecast_days=210")

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            assert params["forecast_days"] == 210
            assert params["latitude"] == 32.675
            return FakeResponse()

    monkeypatch.setattr(riverine_extended_forecast.httpx, "AsyncClient", FakeClient)
    result = await riverine_extended_forecast._fetch_live()

    assert result["station_id"] == "MARALA"
    assert len(result["daily_forecast"]) == 30
    assert result["daily_forecast"][0]["date"] == dates[0]
    assert result["daily_forecast"][-1]["date"] == dates[29]
    assert result["daily_forecast"][0]["median_cumecs"] == 400
    assert result["annual_projection"]["period"] == "2026–2040"
    assert "not a forecast for the next 365 days" in result["annual_projection"]["note"]
