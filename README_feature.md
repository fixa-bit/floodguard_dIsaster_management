# Feature Implementation Tracker

This file tracks one actual product/GIS feature at a time so each change can be reviewed and approved before moving to the next.

## Feature 1 - GIS Boundary/Fill Alignment

Status: In progress, awaiting visual approval.

Goal:
Fix the GIS misalignment between the highlighted Pakistan operational area and visible border lines.

Approach used:
- Use `frontend/src/data/pakistan/pakistan_admin1.geojson` as the single authoritative source for the Pakistan operational fill.
- Use the same `pakistan-operational-base` MapLibre source for the visible province/outer boundary line.
- Remove the separate `international_boundary.geojson` border overlay from rendering to avoid two slightly different Pakistan outlines.
- Keep all custom GeoJSON layers in standard longitude/latitude GeoJSON coordinates, which MapLibre renders as WGS84/EPSG:4326.
- De-emphasize Esri satellite reference borders by reducing the reference-label raster opacity, because that raster contains political border lines that can visually conflict with the custom authoritative geometry.
- Do not manually shift, stretch, rotate, or otherwise alter coordinates.

Files changed:
- `frontend/src/components/NationalRiskMap.tsx`

Approval checklist:
- Pakistan fill and custom Pakistan boundary line visually align.
- No second custom Pakistan border competes with the fill.
- Satellite basemap political borders are subdued enough not to look like the app boundary.
- No manual coordinate transformation or offset is introduced.

Next feature candidates after approval:
- Standardize GIS point symbols and clustering.
- Refine river hierarchy and widths.
- Improve district risk color rules.

## Feature 2 - Two-Way Citizen Reports

Status: In progress, ready for portal review.

Goal:
Make Citizen Reports an active two-way operational feature: fetch reports from the configured database, show active reports in the portal, allow operators/citizens to enter a new report, preserve media references, and prepare important reports for future n8n notification.

Approach used:
- Keep the frontend database-agnostic: it reads from and writes to the backend `/api/v1/citizen-reports` API.
- Keep the backend database source configurable through `DATABASE_URL`; changing that value lets the same API fetch/save reports from another SQL database supported by SQLAlchemy.
- Extend `citizen_reports` with `video_url`, `is_important`, and `important_marked_at`.
- Preserve existing development databases with a lightweight startup migration in `app/db/init_db.py`.
- Seed dummy citizen reports into the local SQLite `floodguard.db` during development startup so the portal displays DB-backed examples immediately.
- Add a `Create report` button on the Citizen Reports page; clicking it reveals fields for location, coordinates, description, depth, image URL, video URL, and source.
- Add report-location tools: browser GPS, Google Maps link parsing, a Google Maps launch button, and a lat/long show-hide button.
- Extract GPS coordinates from a selected local geotagged image when EXIF GPS metadata exists; save `image_latitude` and `image_longitude`, otherwise save/display them as `null`.
- Save new reports through the backend API so they are written into the database and then reloaded into the visible feed.
- Show each report as a prominent boxed card inside a scrollable window and mark newly received reports as active for 60 seconds based on their timestamp.
- Add a Close Report action that sets `report_status` to `CLOSED` and stores `closed_at` in the database.
- Allow importance to be toggled on open reports only; closed reports keep and display their final important/not-important state without edit controls.
- Add an Important action that records a `CITIZEN_REPORT_MARKED_IMPORTANT` system event with `n8n_pending: true`, so a later n8n integration can poll or receive those events.

Files changed:
- `app/models/citizen_report.py`
- `app/schemas/citizen_report.py`
- `app/services/citizen_report_service.py`
- `app/api/routes/citizen_reports.py`
- `app/db/init_db.py`
- `app/core/enums.py`
- `frontend/src/components/CitizenReportsPanel.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/types/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/styles.css`

Approval checklist:
- Existing reports load from the configured backend database.
- Dummy reports are visible from `floodguard.db` before real citizen integrations exist.
- The report entry fields are hidden until `Create report` is clicked.
- A new report can be entered in the Citizen Reports page and saved to the database.
- Image and video references are retained and shown as media chips.
- Report location can be entered from location presets, browser GPS, manual lat/long, or parsed Google Maps links.
- Image geotag coordinates are displayed as real values when available and `null` when absent.
- Newly created reports appear as active for about one minute.
- The report list remains scrollable as records grow.
- Important reports create a system event ready for n8n integration.
- Closed reports stay visible but are marked closed and persisted in the database.
- Closed reports no longer show Mark/Unmark/Close actions; only the final status badges remain.

Next feature candidates after approval:
- Actual image/video file upload with local/S3-compatible storage.
- n8n webhook delivery for important reports.
- Report verification workflow with approved/rejected/duplicate actions.

## Feature 3 - Overview Multi-City Command Tables

Status: In progress, ready for visual/functional review.

Goal:
Make the Overview screen controls work as national dashboard controls instead of implying that the whole screen represents one selected city.

Approach used:
- Keep the operational-area selector on location-specific pages, but hide it on the Overview screen.
- Keep the Overview map national/global while the top command deck exposes city-level values through its tabs.
- Fetch weather and river telemetry for every configured `LOCATIONS` city in `useDashboardData`.
- Preserve the existing selected-location fetches for pages that still need a focused location.
- Convert the Rainfall tab into an all-city table with current rain, 1h, 6h, 24h, forecast 6h, forecast 24h, temperature, humidity, soil moisture, and updated time.
- Convert the Rivers tab into an all-city table with river/station, updated time, level, discharge, 24h forecast discharge, rise rate, and status.
- Update the Rivers tab to use river/reach rows instead of city rows, with real FFD Lahore observed station discharge/status when available and Open-Meteo GloFAS public flood fields as fallback/forecast context.
- Read the official FFD river-state page token and call its `/river-state/data` JSON feed with the same XMLHttpRequest headers used by the FFD page.
- Cache the FFD station feed briefly in the backend to avoid fetching the official token/data once per visible row.
- Show official observed level only where FFD publishes a level value. In the current public feed this appears for dam/reservoir stations such as Tarbela/Mangla, while most barrage/headworks stations publish observed discharge and flood status but no height.
- Add a live river-status map overlay layer above the base water lines. It colors matching river lines by current live river status: normal, rising, warning, or danger/flood.
- Refresh dashboard river data every 15 minutes in normal conditions and every 3 minutes when any monitored river reports a flood-like status.
- Add an hourly analytics ticker on the Overview command screen. It generates right-to-left operational briefing text from current risk, live rainfall, live river discharge, incidents, and citizen reports.
- Keep the ticker generator replaceable: current implementation is deterministic model-style analysis in the frontend, designed so a later LLM or trained predictive model can feed the same ticker surface.
- Add a four-view flood-risk panel on the Overview map: Riverine Short-Term, Flash Flood, Seasonal Basin Risk, and Upstream / Transboundary anomaly. Each view has a separate score, model-family label, and compact mini-map visual.
- River map colors now use live river condition derived from current GloFAS discharge, forecast discharge, daily change, and percentile/statistical fields when true gauge level is unavailable.
- Make Overview snapshot numbers use max all-city river discharge and max all-city rainfall forecast so they read as national dashboard summaries.

Files changed:
- `app/providers/live/live_river_provider.py`
- `app/providers/simulation/simulation_river_provider.py`
- `app/schemas/river.py`
- `frontend/src/hooks/useDashboardData.ts`
- `frontend/src/components/CommandStatsDeck.tsx`
- `frontend/src/components/EnvironmentalPanel.tsx`
- `frontend/src/components/NationalRiskMap.tsx`
- `frontend/src/components/NationalRiskMapLoader.tsx`
- `frontend/src/pages/OverviewPage.tsx`
- `frontend/src/pages/GISPage.tsx`
- `frontend/src/types/api.ts`
- `frontend/src/styles.css`

Approval checklist:
- The Overview header no longer shows a top-right city selector.
- Refresh remains available on the Overview header.
- Opening Rainfall shows rows for all monitored cities with updated timestamps.
- Opening Rivers shows rows for all monitored rivers/reaches with official FFD source labels and updated timestamps.
- Observed level appears where the official FFD feed provides a level value; otherwise the field shows empty/unavailable rather than a fake inferred level.
- Other pages still retain the operational-area selector.

## Feature 4 - Adaptive River Layer and Flood Risk Multi-View

Status: In progress, ready for visual review.

Goal:
Add an operational river-status layer that changes river colors from live conditions, refreshes more often during flood-like conditions, and adds a four-view flood-risk display for NDMA-style briefing.

Approach used:
- Keep the base river geometry separate from live telemetry so the map can redraw status colors without changing GIS coordinates.
- Use live Open-Meteo GloFAS river discharge, forecast discharge, daily change, and percentile/statistical fields for current river condition where observed gauge height is unavailable.
- Classify river line colors as normal, rising, warning, or danger/flood from the live river response.
- Refresh river/dashboard data every 15 minutes in normal mode.
- Switch refresh to every 3 minutes when any monitored river reports a flood-like condition.
- Add a right-side four-view panel on the Overview map with separate operational risk views:
  Riverine short-term, Flash flood, Seasonal basin risk, and Upstream / transboundary anomaly.
- Use simple deterministic scoring now, but label each view with the intended model family so trained models can replace the current logic later.
- Keep the hourly analytics briefing ticker at the bottom of the map and generate its text from the same live dashboard data.

Files changed:
- `frontend/src/components/FloodRiskMultiView.tsx`
- `frontend/src/components/HourlyAnalyticsTicker.tsx`
- `frontend/src/components/NationalRiskMap.tsx`
- `frontend/src/hooks/useDashboardData.ts`
- `frontend/src/pages/OverviewPage.tsx`
- `frontend/src/styles.css`
- `README_feature.md`

Approval checklist:
- River legend includes live normal/rising/flood colors.
- River overlay updates from live river data without moving or stretching map geometry.
- Normal refresh interval is 15 minutes.
- Flood-like river status changes the interval to 3 minutes.
- Overview map shows a compact four-view flood-risk panel.
- The four views cover riverine, flash flood, seasonal, and upstream/transboundary risk.
- The bottom hourly analytics ticker remains visible and readable over the map.
