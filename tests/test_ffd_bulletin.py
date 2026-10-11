from datetime import datetime, timedelta, timezone

import pytest

from app.services.ffd_bulletin_service import forecast_range, parse_bulletin


def bulletin(forecast="40 - 50", inflow="50.0", outflow="0.0"):
    yesterday = datetime.now(timezone(timedelta(hours=5))) - timedelta(days=1)
    return f'''<a href="https://ffd.pmd.gov.pk/b/example">Permalink</a>
    BULLETIN No: 120/26 Dated: {yesterday.day}th {yesterday:%B-%Y} Time: 11:30 hours (PST)
    QUANTITATIVE FLOOD FORECAST OF GAUGING STATIONS (IN THOUSANDS OF CUSECS)
    Actual Observations at 0600 PST Quantitative Forecast for Next 24-hrs (Inflow)
    <table><tr><td data-ffd="station">Trimmu</td><td data-ffd="inflow">{inflow}</td>
    <td data-ffd="outflow">{outflow}</td><td data-ffd="forecast">{forecast}</td></tr></table>'''


def test_bulletin_gauge_units_timestamps_and_range():
    station = parse_bulletin(bulletin())["Trimmu"]
    assert station["samples"]["INFLOW"]["value"] == 1415.84
    assert station["samples"]["OUTFLOW"]["value"] == 0
    assert station["samples"]["INFLOW"]["time"].endswith("06:00:00+05:00")
    forecast = station["forecast"]
    assert forecast["gauge"] == "INFLOW"
    assert (forecast["low"], forecast["high"]) == (1132.67, 1415.84)
    assert forecast["horizon_hours"] == 24
    assert forecast["issued_at"].endswith("11:30:00+05:00")
    assert forecast["source"] == "https://ffd.pmd.gov.pk/b/example"
    assert forecast["valid_from"] is None and forecast["valid_until"] is None


@pytest.mark.parametrize("text", ["No sig. change", "50 - 40", "NaN", "inf", "-1", "40 to 50 tomorrow", "40 - 50 cusecs", ""])
def test_no_manufactured_forecasts(text):
    assert forecast_range(text) == (None, None)
    forecast = parse_bulletin(bulletin(text))["Trimmu"]["forecast"]
    assert forecast["text"] == text
    assert forecast["low"] is None and forecast["high"] is None


def test_bulletin_rejects_changed_units_or_gauge_basis():
    for old, new in [("IN THOUSANDS OF CUSECS", "IN CUSECS"), ("(Inflow)", "(Outflow)"), ("Time: 11:30", "Time: unavailable")]:
        with pytest.raises(ValueError):
            parse_bulletin(bulletin().replace(old, new))
    assert forecast_range("0.1 - 0.2") == (2.83, 5.66)
