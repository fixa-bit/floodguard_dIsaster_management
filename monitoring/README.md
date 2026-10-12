# Station Data Store

This subsystem only stores values collected from APIs or produced by forecasting
models. Actual monitoring, comparisons, threshold checks and alerts belong in
FloodGuard. No polling rules, health status, training jobs or alert records live here.

## Four Tables

| Table | Fields |
| --- | --- |
| stations | id, code, name, river, latitude, longitude |
| providers | id, code, name, kind (api/model/import), model_version |
| station_values | id, station_id, provider_id, measurement, value, unit, value_type, value_at, forecast_issued_at, stored_at, p25, p75, level_reference |
| thresholds | id, station_id, measurement, unit, level, value, provider_id, source_reference, level_reference |

A provider is either an API or a particular version of your own model. Use a distinct
provider code per model version. Every value links to exactly one station/provider.
Do not create a table or column for each model or timestamp: add rows instead.

- measurement: e.g. river_discharge, discharge_inflow, discharge_outflow, rainfall_1h.
- value_at: when an observation was measured, or the time a predicted value applies to.
- forecast_issued_at: actual forecast issue time if supplied, otherwise NULL.
- stored_at: when this store received the value; never a replacement for value_at.
- value_type: observed, simulated, or forecast. GloFAS past values are simulated, not observed.
- unit: supplied unit, unchanged. No automatic unit conversion takes place here.
- p25/p75: optional uncertainty percentiles in the same unit as value; absent is NULL.
- level_reference: gauge datum/mMSL reference for water-level values, otherwise NULL.

No risk classifications, model execution statuses, training parameters,
health flags, polling intervals, forecasts runs or geometry objects remain in the
active schema. Unknown metadata stays NULL. No fake measurements or model outputs
are inserted. Checks only validate incoming data; they do not perform monitoring.

## Run

From the repository root:

```powershell
.venv\Scripts\python.exe -m monitoring.cli init
.venv\Scripts\python.exe -m monitoring.cli status
.venv\Scripts\python.exe -m monitoring.viewer --port 8010
```

Read-only viewer: http://localhost:8010. Records, Raw Table and Schema Diagram show
only these four tables. The SQLite file is monitoring/data/monitoring.db and is
ignored by Git. A separate PostgreSQL URL can be configured through
MONITORING_DATABASE_URL; the local viewer is SQLite-only.

Initialization registers 24 station/dam/headworks locations from FloodGuard's
priority station set, six API/import identities and six planned model entries. This is metadata, not a promise
that every station has a working API. Confluence planning reference points are
excluded. River-cell coordinates for a future GloFAS adapter stay in config/stations.json;
station coordinates must not be silently replaced by the model's nearest river cell.

## Planned Models and Thresholds

Providers includes riverine, flash-flood and coastal planning slots, each with short-
and long-range entries. Names say `(planned)` and model_version is NULL: these are
not trained models and cannot accept output through store_value. Register a distinct
versioned provider when a real trained model is ready; add other hazards the same way.

Thresholds are reference data, not providers or monitoring rules. Each station gets
empty warning/danger slots for discharge_inflow and discharge_outflow in cusecs,
and water_level in metres. These labels are planning placeholders, not assertions
that official thresholds exist for every station. Unknown values, source providers,
source references and gauge datums stay NULL. NULL is never treated as zero.
Additional official flow categories or measurements can be added as rows.

Before filling a limit, verify its station, measurement, unit and official source;
record provider_id and source_reference (document/page/date). Water levels also
need level_reference: metres alone cannot distinguish gauge datum from mMSL.
Do not apply an inflow limit to outflow or to a model's river-cell discharge.
Initialization only fills missing slots and never replaces entered limits.
The read-only viewer shows these references in Records, Raw Table and Schema Diagram;
actual threshold comparisons and alerts remain in FloodGuard.

## Supply API or Model Output

Register your model version:

```powershell
.venv\Scripts\python.exe -m monitoring.cli add-provider RIVER_V1 "River model" --kind model --version v1
```

Write a JSON array of actual fetched/generated values, then import it:

```powershell
.venv\Scripts\python.exe -m monitoring.cli import-json path\to\values.json
```

Required keys: station (station code), provider (provider code), measurement, value,
unit, value_type and value_at. Optional keys: forecast_issued_at, p25, p75,
level_reference. Timestamps must include Z or a timezone offset such as +05:00.
Use repository.store_value directly from an API adapter or model worker if desired.

Importing identical data again adds no duplicate. A changed value for the same
station/provider/time appends a new capture instead of erasing history. Different
forecast issue times, model versions, measurements and units stay separate.
Serialize collectors for a stream to avoid racing duplicate imports. Batch imports
are atomic: a bad record rolls back the entire batch and leaves prior data intact.
The consumer can select the latest capture by stored_at/id when corrections exist.

No API fetching scheduler or model execution is started by this schema change.
Collection workers will call this storage contract; FloodGuard will read the rows
and perform the actual monitoring. Never claim a feed is live just because its
provider identity has been registered.

## Simulated Flow Scenarios

The `monitoring/simulation` package creates flood-test data without changing the
monitoring schema. Scenario files can describe richer testing inputs such as
baseline flow, peak flow, recovery flow, rise/hold/recession steps, interval,
explicit step values and uncertainty bands. The writer converts those inputs into
normal `station_values` rows with `value_type = simulated`, `forecast_issued_at =
NULL`, and an import provider whose code starts with `SIMULATED_FLOW`.

Run the example scenario after initialization:

```powershell
.venv\Scripts\python.exe -m monitoring.cli simulate-flow monitoring\simulation\examples\taunsa-danger-surge.json
```

Example fields:

```json
{
  "name": "taunsa-danger-surge",
  "start_at": "2026-10-12T00:00:00Z",
  "interval_minutes": 60,
  "uncertainty_ratio": 0.08,
  "series": [
    {
      "station": "TAUNSA",
      "measurement": "discharge_inflow",
      "unit": "cusecs",
      "baseline_value": 120000,
      "peak_value": 650000,
      "recovery_value": 180000,
      "rise_steps": 5,
      "hold_steps": 2,
      "recession_steps": 5
    }
  ]
}
```

Use `step_values` instead of baseline/peak/recovery fields when you need a custom
hydrograph shape. Water-level simulations must include `level_reference`, matching
the normal storage rule for level measurements.

## Backup and Migration

The migration from the previous seven-table design makes a complete SQLite backup,
converts station/API/model values into rows here, validates counts/foreign keys,
and replaces the active file only after validation. Stop collectors/viewer first.
Backups: monitoring/data/monitoring.previous-design-<UTC timestamp>.db.

Old configuration/training/health fields stay in the backup, not the active store.
Existing numeric readings/forecast values and timestamps are preserved. Legacy
ensemble members get distinguishable model provider identities. Removed legacy
uncertainty fields beyond p25/p75, quality metadata and run status remain in the
backup; they are not claimed to be part of this minimal data contract.
SQLite schema version is 5 (PRAGMA user_version), with no extra version table.
Upgrading the three-table store adds only thresholds; all existing values stay intact.
Legacy PostgreSQL conversion is refused until an explicit backup/export is arranged.

```powershell
.venv\Scripts\python.exe -m pytest monitoring/tests -q
```
