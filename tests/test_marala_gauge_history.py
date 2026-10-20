import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.collect_marala_gauge_history import monthly_gauge_averages, parse_current_bulletin


def reading(day, value):
    return {"station_id": "MARALA", "date": day, "measurement_kind": "FFD_reported_observation",
            "inflow_cumecs": value, "source_url": "https://ffd.pmd.gov.pk/" + day}


def test_monthly_average_uses_only_measured_readings_and_preserves_gaps():
    rows = monthly_gauge_averages([reading("2025-01-01", 100), reading("2025-01-03", 300), reading("2025-01-03", 300)], date(2025, 1, 1), date(2025, 2, 28))
    assert rows[0]["flow_mean_cumecs"] == 200
    assert rows[0]["days"] == 2
    assert rows[0]["coverage"] == "partial"
    assert rows[1]["flow_mean_cumecs"] is None
    assert rows[1]["coverage"] == "missing"


def test_conflicting_daily_observations_are_rejected():
    with pytest.raises(ValueError, match="Conflicting"):
        monthly_gauge_averages([reading("2025-01-01", 100), reading("2025-01-01", 200)], date(2025, 1, 1), date(2025, 1, 31))


def test_chart_monthly_averages_match_saved_ffd_observations():
    artifacts = Path(__file__).resolve().parents[1] / "app/ml/marala_pilot/artifacts/seasonal"
    observed = json.loads((artifacts / "gauge_history_observations.json").read_text(encoding="utf-8"))
    saved = json.loads((artifacts / "observed_monthly_history.json").read_text(encoding="utf-8"))
    assert monthly_gauge_averages(observed, date.fromisoformat(saved["period_start"]), date.fromisoformat(saved["period_end"])) == saved["monthly"]
    assert saved["station_observation"] is True
    assert len(saved["monthly"]) == saved["monthly_slots"]
    provider = json.loads((artifacts / "current_provider_outlook.json").read_text(encoding="utf-8"))
    issue = date.fromisoformat(provider["forecast_issue_start"])
    assert date.fromisoformat(saved["period_start"]) == issue.replace(year=issue.year - 2)
    assert date.fromisoformat(saved["period_end"]) == issue - timedelta(days=1)
    assert all(saved["period_start"] <= row["date"] <= saved["period_end"] for row in saved["daily"])
    assert saved["daily_records"] == len(saved["daily"])
    assert all(row["observed_at"] == row["date"] + "T06:00:00+05:00" for row in saved["daily"])


def test_current_bulletin_uses_measured_cells_not_forecast():
    html = '''Dated: 21st September-2026
    IN THOUSANDS OF CUSECS Actual Observations at 0600 PST
    <table><tr><td data-ffd="station">Marala</td><td data-ffd="inflow">24.2</td>
    <td data-ffd="outflow">7.0</td><td data-ffd="forecast">999</td></tr></table>'''
    row = parse_current_bulletin(html, date(2026, 9, 21))
    assert row["inflow_cusecs"] == 24200
    assert row["outflow_cusecs"] == 7000
    assert row["observed_at"] == "2026-09-21T06:00:00+05:00"
    with pytest.raises(ValueError, match="date mismatch"):
        parse_current_bulletin(html, date(2026, 9, 22))


def test_legacy_table_in_current_publication_can_be_extracted():
    html = '''Dated: 20th June-2026 IN THOUSANDS OF CUSECS
    Actual Observations at 0600 PST QUANTITATIVE FLOOD FORECAST
    <tr><td>Marala</td><td>1100</td><td>40.0</td><td>20.0</td><td>999</td></tr>'''
    row = parse_current_bulletin(html, date(2026, 6, 20))
    assert row["inflow_cusecs"] == 40000
    assert row["outflow_cusecs"] == 20000
