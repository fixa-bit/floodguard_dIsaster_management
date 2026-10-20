# Monthly Marala loading

Monthly Marala belongs to Predictive Risk Views → Near-Term Screening → Riverine
Short-Term. Its tab stays inside that card; it does not span the dashboard grid.

The frontend requests `${VITE_API_BASE_URL}/predictive/marala-monthly`, defaulting
to `http://127.0.0.1:8000/api/v1/predictive/marala-monthly`. On failure it requests
`${BASE_URL}data/marala-monthly.json` from the frontend origin. The Download CSV
link uses `${BASE_URL}data/marala-monthly-dataset.csv`, independently of the API.
The API also provides `/api/v1/predictive/marala-monthly/dataset.csv`.

On investigation, the running backend returned 404 for both API endpoints and
listed neither in `/openapi.json`, although current `app/api/router.py` registered
the router. Uvicorn was running without `--reload` and still had the older route
table in memory. Restarting the backend loaded both endpoints; each returned 200
and 264 records. No additional route registration was needed.

The current frontend already successfully served and used its packaged fallback
before that restart. The reported bare “Not Found” error did not reproduce with
the current frontend files. If it persists in an open browser, refresh the page
or rebuild/redeploy its frontend assets. Fallback failures now report their own
error separately from the backend error rather than hiding behind its 404.

`npm run build` checks the packaged JSON and CSV exist and agree on all 264 months
(2000-01 through 2021-12). Regenerate both from saved backend artifacts with
`.venv\Scripts\python.exe scripts/export_marala_dashboard_assets.py` from the repo
root when the dataset changes.

Run `node scripts/check-marala-monthly.mjs` in `frontend` for browser checks of
both the live API and a forced 404 fallback, the CSV download, all 264 table rows,
card width and mobile overflow. Set `DASHBOARD_URL` for another frontend origin.
For a preview origin outside backend CORS settings, set `MARALA_FALLBACK_ONLY=1`
to verify static production assets independently.

Backend code changes require a restart when using `uvicorn app.main:app` without
reload. For development, use `.venv\Scripts\python.exe -m uvicorn app.main:app
--host 127.0.0.1 --port 8000 --reload`. Packaged assets remain available during
backend downtime.

The chart's historical series uses individual FFD-reported Marala inflow readings
at 06:00 PKT on their actual dates over the two years preceding the forecast issue
date (currently 16 October 2024–15 October 2026).
Run `.venv\Scripts\python.exe scripts/collect_marala_gauge_history.py`, then the
asset exporter. The collector checks both the older year-wise PDF archive and
the current-season publication pages, including 2026 HTML bulletins. The old
archive alone does not list the current season. Measured readings appear as blue
points; hover, focus or tap for the actual date, time and inflow. These are daily
snapshots, not daily averages. Every missing day breaks the blue line. No missing
value is filled with a model value or interpolation. Available monthly averages
remain in View details.

Measured inflow history and the dashed, shaded nearby-reach GloFAS monthly-mean
forecast are separate products. Monthly forecast means are positioned at the
middle of each month; daily forecasts are not inferred from them. Both series
share a real date axis, and no line joins observations to predictions. The
264-row modeled training dataset and its CSV remain separate too.
Raw extracted FFD observations, bulletin URLs, SHA-256 hashes and rejected-source
records are retained alongside `observed_monthly_history.json`. The earlier
modeled-history artifacts are retained for provenance but are not used for the
chart's past values.

The light hydrograph uses blue open-circle observations, red diamond forecasts,
a date cursor and a value tooltip. There are exactly two options, Daily and
Monthly averages. Both always include all available readings in the full two-year
window; no additional range controls truncate history or forecasts. Gaps and the
measurement units remain the same in each view. The green line is the highest
measured value in the loaded window, not an all-time record or official danger
threshold. No danger line is drawn without a verified station threshold.

Daily and Monthly averages subtabs now control both historical and forecast
resolution. Daily uses the actual measured 06:00 PKT snapshots and every available
daily forecast within the maximum requested provider horizon, with missing days
breaking both lines. The current request spans 210 days (~7 months), with 201
usable daily values through 4 May 2027; the trailing missing forecast days remain
blank. Monthly averages shows all six complete forecast months, November
2026–April 2027, and excludes the partial future months.
The provider has fixed daily resolution: its means are UTC calendar-day values,
not exact 06:00 predictions. The caption and tooltips retain that distinction.
Monthly averages uses measured available-reading monthly means with coverage
counts, and complete-month averages of the same saved daily provider forecasts.
No daily predictions are synthesized from monthly values. Seasonal collection
retains the provider daily response in `current_provider_outlook.daily-source.json`
and exports both resolutions through the API and packaged fallback.
