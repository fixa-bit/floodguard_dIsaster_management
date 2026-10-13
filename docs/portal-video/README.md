# FloodGuard portal walkthrough

Deliverable: `FloodGuard_Portal_Walkthrough.mp4` — 1920 × 1080, 30 fps, 05:45, English on-screen captions, silent.
The video is a real browser recording of the existing React portal, with pointer movement, clicks, scrolling, form entry, and chart interaction. It is not a slideshow or an AI-generated video.
Loading and action periods are retimed per chapter to fit the requested 4–6 minute runtime; every section retains its final three seconds at normal speed for readability.
The edit joins browser-recorded clips from several capture passes, with long processing stalls omitted. The glacier section uses a separate close view of the Pakistan river contributors. Screenshots are used only to locate and verify recorded frames; the video itself contains browser footage.

## Demo assumptions and data

The requested assumption is that the displayed models have been trained on small datasets. This project does not train additional models or claim validated accuracy. The existing forecast cards use the portal's bundled dummy forecast series. The visible operational risk engine remains the configured rule-based engine.

- Backend weather, city river values, national screening, and water geometry use the isolated backend's simulation mode.
- River geometry is generalized to 0.001 degrees in the browser-only demo feed to keep catchment clipping responsive; the portal's static district and boundary assets and station coordinates are unchanged.
- River monitoring/provider series, rainfall heatmap samples, Google integration markers, and the satellite water mask are explicitly illustrative browser fixtures. The satellite segment demonstrates the existing U-Net control using an illustrative mask; it does not execute the Sentinel-1 inference pipeline.
- Reports, priority flags, closure actions, monitoring simulation, saved alerts, linked incidents, and events run against a separate `demo.db`, using the portal's real backend endpoints.
- Population exposure displays the existing stored historical-reference analysis with its coverage limitations. The video inspects its controls and overlays without recomputing or replacing that analysis.
- This video does not assert access to an official Google Flood API, operational thresholds, successful training of planned models, or measured model accuracy.

## Chapters

- 00:00 — Operational overview
- 00:07 — Command statistics
- 00:15 — Command statistics
- 00:26 — Command statistics
- 00:37 — Command statistics
- 00:49 — National GIS layers
- 01:00 — Reference outlines and Flood Hub integration
- 01:11 — Coordinate lookup
- 01:22 — Catchment study mode
- 01:33 — Station hover cards
- 01:44 — Station discharge forecast
- 01:55 — Glaciers and headwaters
- 02:06 — Satellite water extent
- 02:17 — Rainfall heatmap
- 02:28 — Population exposure analysis
- 02:40 — Exposure controls and map overlays
- 02:51 — Predictive model views
- 03:02 — Riverine short-term model
- 03:09 — Flash-flood model
- 03:17 — Urban flooding model
- 03:28 — Seasonal basin model
- 03:35 — Upstream anomaly model
- 03:42 — Upstream source flood watch
- 03:54 — Source forecast context
- 04:01 — River monitoring table
- 04:12 — Station network and chart
- 04:19 — Citizen reports
- 04:31 — Submit a geolocated report
- 04:42 — Prioritize and close reports
- 04:52 — Monitoring simulation
- 05:03 — Threshold crossing and saved results
- 05:10 — Alert review
- 05:18 — Incident management
- 05:26 — System activity
- 05:33 — Command overview

## Reproduction

1. Start the backend with `DATA_MODE=simulation`, `ENABLE_SIMULATION=true`, `ALLOW_RULE_BASED_FALLBACK=true`, `DATABASE_URL=sqlite:///D:/Projects/disaster_management/docs/portal-video/demo.db`, and `CORS_ORIGINS=http://127.0.0.1:3025`, on port 8025.
2. Start Vite on port 3025 with `VITE_API_BASE_URL=http://127.0.0.1:8025/api/v1`.
3. Existing `feed-*.json` files retain the recording session's base GIS geometry. From `frontend`, run `node scripts/record-portal-video.mjs`. Set `VIDEO_PREFLIGHT=1` for an abbreviated interaction check.
4. For the included multipart capture, run `.venv/Scripts/python.exe scripts/package_portal_recordings.py`. Its retained frame matches identify completed views in the raw footage. `frontend/scripts/record-glacier-detail.mjs` and `scripts/replace_glacier_video_clip.py` provide the closer glacier section.
5. From the repository root, run `.venv/Scripts/python.exe scripts/render_portal_video.py`, then `.venv/Scripts/python.exe scripts/verify_portal_video.py`.

`recording-manifest.json` contains capture timing, chapter spans, downloads, and browser-error results. `demo-feed-provenance.json` describes demo feed sources. A separate SRT file is included for editable captions; the MP4 includes burned-in captions and embedded chapter markers.
