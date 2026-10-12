# Monitoring simulation

Open the **Simulation** tab, select a monitoring station and measurement, and
enter readings with minute offsets from the selected start time. Select saved
thresholds or enter custom warning/danger test limits, then press **Play**.
The profile selector can fill below-threshold, warning, danger, or surge and
recovery readings. Optional p25/p75 bands are stored with the readings.

Play saves the full reading queue immediately. Offsets specify the readings'
timestamps; they are not wall-clock playback delays. Each reading at or above
a limit produces one alert and one linked open incident. A reading at or above
both limits uses the danger level: warning maps to HIGH severity, danger to
CRITICAL. Uncertainty bands do not independently trigger alerts.

## Storage and provenance

Readings use the existing `monitoring.station_values` schema, with
`value_type="simulated"` and an import provider named
`SIMULATED_FLOW_<run UUID>`. Live observed rows are preserved. The monitoring
database keeps its original four tables. Its connection honors
`MONITORING_DATABASE_URL`, defaulting to `monitoring/data/monitoring.db`.

Alerts are persisted as `ALERT_REQUIRED` events in the application's existing
`system_events` table and exposed in the **Alerts** tab. Their metadata records
the run, provider, station value, measurement, unit, timestamp, threshold level,
threshold value and source, and linked incident ID. Incidents use the existing
`incidents` table with `source="SIMULATED_FLOW"`. The alert banner and both
sections label these records **Simulated flow**. They also appear in System
Activity and incident totals.

The application's `monitoring_simulation_runs` table stores each request
fingerprint and result. Retrying a run UUID returns its existing result;
changing its payload returns HTTP 409. **New run** creates a fresh run UUID.
Handled failures roll back application records and compensate monitoring
writes if needed. The two databases do not support a shared atomic transaction;
an abrupt process interruption between commits can leave monitoring-only rows.
Retrying the same UUID reuses those readings and completes the application run.

## Threshold selection

Saved limits must match station, measurement and unit exactly. Water-level
limits must also have the same nonempty gauge datum/reference as the readings.
Units are not silently converted. Empty saved threshold slots cannot trigger
alerts; use custom test limits until the saved values are configured.

Custom limits apply only to the submitted run and are retained in alert
metadata. They do not overwrite the monitoring database's saved limits.
These monitoring test endpoints are available alongside live feeds. The
existing `ENABLE_SIMULATION` setting continues to govern the older global
scenario endpoints (`start`, `advance`, `reset`).

## API

- `GET /api/v1/simulation/monitoring/stations`: stations and saved thresholds.
- `POST /api/v1/simulation/monitoring/play`: validated test queue and limits.
- `GET /api/v1/alerts`: latest 500 saved alert events.
- `GET /api/v1/incidents`: persisted incidents, including simulated incidents.

## Verification

Run `.venv/Scripts/python.exe -m pytest tests/test_monitoring_simulation.py -q`
for isolated database/API checks. From `frontend`, `npm run build` checks the
frontend and `node scripts/check-monitoring-simulation.mjs` checks the browser
workflow. The browser check writes sample scenarios: point it at an isolated
backend with empty threshold slots using `BACKEND_URL` and a frontend using
that backend via `FRONTEND_URL`. Its default backend is port 8001 and frontend
is port 3000. Screenshots are written under `.pytest_cache`.

## Request Example

Example play request:

```json
{
  "run_id": "2f30df0e-72a3-4528-89e8-1f2f719fe30f",
  "name": "Taunsa danger test",
  "station": "TAUNSA",
  "measurement": "discharge_inflow",
  "unit": "cusecs",
  "start_at": "2026-10-12T10:00:00+05:00",
  "threshold_mode": "custom",
  "warning_threshold": 300000,
  "danger_threshold": 600000,
  "readings": [
    {"offset_minutes": 0, "value": 120000},
    {"offset_minutes": 60, "value": 300000},
    {"offset_minutes": 120, "value": 650000}
  ]
}
```
