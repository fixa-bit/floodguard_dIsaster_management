# Experimental Station Hydrograph

The third station tab is independent of Station details and Discharge forecast.
It lazily calls `GET /api/stations/{id}/hydrograph?days=5|30`. No map state or
hover requests are added. Both modal and native SVG chart are separate chunks.

## Data and honesty

Open-Meteo's default flood model is GloFAS v4. Daily model values and ensemble
percentiles arrive in m3/s and are converted using 35.3147 cusecs per m3/s.
Requests use GMT to retain the original daily boundaries. PKT tooltip times are
converted from these instants, not relabeled local-day averages. The returned
river cell is shown and remains unverified until checked against the river.
No past modeled values become observed readings.

IRSA's public site could not be verified during implementation. The replaceable
adapter `app/providers/irsa_report_parser.py` currently parses the verified FFD
bulletin's explicitly marked INFLOW cells in thousands of cusecs. Its records
are labeled FFD, not IRSA. Replace this adapter after verifying a public IRSA
report format, or import official IRSA inflow readings by CSV. Never mix inflow
and outflow in this table. Retain the observation time, not the publication time.

Model requests have a six-second timeout and three attempts with backoff.
The in-memory model cache is keyed by station, horizon and configured coordinates
for four hours. On failure, a previously successful entry is served with `stale`
and its original generatedAt. Cache does not survive a server restart. Missing
model data leaves observations available; no available data returns a generic
retryable 503. Internal exception messages are not returned.

The default red line is raw simulated discharge, separate from blue observations.
Its dashed connector to the final observed point is not an additional reading.
Daily forecast points at or before the latest observation are omitted from the
display to avoid a backward connector. Alignment is off by default; enabling it
adds one constant display-only offset and an explicit note. Negative shifted
values are omitted, never fabricated. CSV marks shifted exports and their offset.

## Migration and Ingestion

Run from the repository root, with the application's DATABASE_URL configured:

```powershell
.venv\Scripts\python.exe -m scripts.migrate_station_observations
.venv\Scripts\python.exe -m scripts.ingest_station_observations
.venv\Scripts\python.exe -m scripts.ingest_station_observations --csv C:\data\official-inflows.csv
```

The migration adds only `station_observations`, with a unique station/time
constraint. App startup also creates this table. Failed parsing/imports roll back
the batch and retain existing data. Reruns update the same reading without creating
duplicates. Source URLs and all import errors are logged only server-side.

CSV headers: `station_id,observed_at,discharge_cusecs,source`.
Times require a timezone, e.g. `2026-10-11T06:00:00+05:00`.
Only nonnegative finite official inflow values are accepted.

Example daily Linux cron (set DATABASE_URL in the job environment):

```cron
CRON_TZ=Asia/Karachi
0 13 * * * cd /opt/floodguard && .venv/bin/python -m scripts.ingest_station_observations >> /var/log/floodguard-ingestion.log 2>&1
```

`scripts/station_observations.cron` contains this template; adjust paths and check
whether your cron implementation supports CRON_TZ. Schedule after the daily bulletin.
On Windows schedule the same module command daily at 13:00 PKT with Task Scheduler. Configure
the repository as its working directory and use the full virtualenv Python path.
The job is not automatically enabled by opening the chart.

## Stations and References

Edit `app/gis/hydrograph_stations.json`. Eight requested stations are seeded;
other existing monitoring stations have null reference values and fallback
coordinates. Add an entry to customize any station or add a station for the API:

```json
{"station_id":"NEW_STATION","name":"Station","river":"River","lat":31,"lon":72,
 "glofas_lat":31,"glofas_lon":72,
 "thresholds":{"low":null,"medium":null,"high":null,"veryHigh":null,"exceptional":null},
 "highestRecorded":{"value":null,"date":null}}
```

TODO: Verify each GloFAS river cell; coordinate changes of about 0.1 degrees can
select another river and must not be tuned solely to resemble observed readings.
TODO: Fill references using official FFD/WAPDA values in cusecs and ISO dates.
Null references are not drawn. Newly configured stations need map integration
separately if they are not already in the monitored network.

## Test Data and Checks

`tests/fixtures/hydrograph_mock.json` and `station_observations_mock.csv` contain
synthetic data, never automatically loaded in the application. Synthetic threshold
numbers are test values only, not station-config defaults. Use a test DATABASE_URL
before importing the mock CSV; do not import it into an operational database.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_experimental_hydrograph.py -q
cd frontend
node scripts/check-experimental-hydrograph.mjs
node scripts/check-station-hover-browser.mjs
npm run build
```

In the third tab test 5/30 Days, both units, hiding thresholds, series visibility,
alignment, PNG/CSV, no-observation and stale states, retry and mobile scrolling.

Source: https://open-meteo.com/en/docs/flood-api
Observation adapter: https://ffd.pmd.gov.pk/bulletin
Check Open-Meteo's usage licence before operational deployment; the free endpoint
does not require a key, but free access is not an unrestricted commercial licence.
