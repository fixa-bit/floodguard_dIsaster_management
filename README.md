Terminal 1 
cd D:\Projects\disaster_management
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

terminal 2

cd D:\Projects\disaster_management\frontend
npm run dev -- --host 127.0.0.1 --port 3000


-------------------------------------------------

.venv\Scripts\activate
uvicorn app.main:app --reload

Access backend/API docs here:
http://127.0.0.1:8000/docs

Terminal 2:
cd frontend
npm run dev

http://localhost:3000

The frontend is configured to call the backend at:
http://127.0.0.1:8000/api/v1

Static glacier and district map assets are built as content-hashed `.geojson.gz`
files. The browser decompresses them without changing coordinates and stores them
in Cache Storage for reuse across reloads. Changed content gets a new URL.
Vite dev/preview serves these files with `Cache-Control: public, max-age=31536000,
immutable`; use the same header for `/assets/*.geojson.gz` on a production static
host. The loader also accepts files already decoded by HTTP `Content-Encoding`.

# FloodGuard AI Backend

FastAPI backend foundation for flood monitoring, national GIS screening, risk scoring, incidents, citizen reports, automation context, dashboard summaries, and authority-supplied emergency resources.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

## Technical documentation

- Maintained source: `docs/FloodGuard_Backend_Technical_Overview.html`
- Generated PDF: `docs/FloodGuard_Backend_Technical_Overview.pdf`

Regenerate the PDF after backend feature or model changes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\generate_backend_pdf.ps1
```

## Test

```bash
pytest
```

## Database

Local development uses SQLite by default: `sqlite:///./floodguard.db`.
Switch later to PostgreSQL by changing `DATABASE_URL`.

## Weather modes

- `DATA_MODE=live`: live Open-Meteo weather plus live GloFAS modeled river discharge.
- `DATA_MODE=hybrid`: backward-compatible alias using the same free live providers.
- `DATA_MODE=simulation`: deterministic development/test scenarios; it never represents external data.

Production defaults are strict: `ENABLE_SIMULATION=false` and
`ALLOW_RULE_BASED_FALLBACK=false`. Live provider or ML failures are returned as
errors instead of being replaced with mock values. Simulation can be enabled
only for a deliberately isolated development/test deployment.

`ML_MODEL_ENABLED=false` is also the production default because the bundled
XGBoost artifact uses synthetic development training data. The rule engine uses
the live normalized inputs directly and is the primary operational model until
a validated historical model artifact replaces the development artifact.

The public flood source provides modeled discharge, not measured water level. Live river responses therefore leave legacy level fields as `null` instead of inventing measurements.

Emergency-resource endpoints return empty lists until approved authority data is
configured; the backend does not ship placeholder facilities.

## National GIS

`GET /api/v1/gis/national-risk` returns a gzip-compressed GeoJSON layer for 126
Pakistan ADM2 districts. Live mode batches Open-Meteo weather requests and
caches the national layer for `GIS_CACHE_TTL_SECONDS`. Use the optional
`bbox=west,south,east,north` query for viewport filtering.

This layer is explicitly a weather-based prioritization screen. Detailed
river-aware XGBoost predictions remain available through `/flood/risk` for
configured monitoring locations.

The overview and GIS maps start with only the Pakistan boundary enabled and do
not wait for dashboard feeds. After the boundary's first paint, hidden layers
warm in the background, including the rainfall raster. Enabling a prepared layer
reuses its sources instead of downloading its geometry again. The dedicated
rainfall view still opens with rainfall enabled.

District and glacier geometry use content-hashed gzip files and browser Cache
Storage, with immutable HTTP caching. Deployments should preserve the asset
filenames and serve `.geojson.gz` as `application/gzip` with
`Cache-Control: public, max-age=31536000, immutable`. The loading wheel appears
when an enabled district or glacier layer is still loading, not while hidden
geometry warms. Live feeds keep their refresh intervals and depend on provider
availability; an early toggle may still need to wait for its initial data.

District names and borders use their own static source, independent of risk
coverage. The display includes 10 AJ&K districts from the existing Pakistan
adapter and 22 wider Kashmir context districts from geoBoundaries
`IND-ADM2-76128533` (2021, ODbL 1.0), clipped to the displayed Kashmir outline.
Regenerate the context subset with
`.venv/Scripts/python.exe scripts/fetch_kashmir_districts.py`. Display geography
does not assign sovereignty or create district risk estimates.

## Development ML model

The included training generator is synthetic and intended only for development. It is not historical flood data.

```bash
python -m app.ml.train_model
```

## Real-data research model

The real-data trainer joins Pakistan-associated Global Flood Database event
windows to historical Open-Meteo weather and GloFAS modeled discharge. It uses
event-grouped train/validation/test splits and writes a model card with a hard
deployment gate:

```bash
python -m app.ml.train_real_model --rebuild
```

The current `xgboost_pakistan_gfd_v1` run is **not deployed**. Its held-out
event ROC-AUC is 0.5936 and spatially blocked ROC-AUC is 0.3836, below the
0.75 gate. Full metrics and split membership are recorded in
`app/ml/artifacts/flood_risk_xgboost_real.model-card.json`; production remains
on `rule_based_v1` with real inputs.
