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

### DesInventar district-date research model

The second real-data experiment cleans UNDRR DesInventar Pakistan FLOOD and
FLASH FLOOD records and joins them to historical Open-Meteo rainfall/soil
moisture and GloFAS modeled discharge. It adds 3/7/14/30-day rainfall,
discharge ratios and z-score, elevation, and seasonality, then evaluates
unseen districts, unseen 2-degree geographic blocks, and later years.

```bash
python -m app.ml.train_desinventar_model --rebuild
```

The resulting 10,097-row dataset contains 1,584 positive district-dates across
67 districts. The model is **not deployed**: ROC-AUC was 0.6815 on district
holdout, 0.5704 on geographic holdout, and 0.7029 on temporal holdout. It did
not meet the required 0.75 ROC-AUC plus 0.60 precision and recall on every
holdout. Full provenance is in
`app/ml/artifacts/flood_risk_xgboost_desinventar_v2.model-card.json`.

### Partial-coverage experiment

A separate Lower Indus pilot tests whether a smaller, contiguous coverage area
solves the geographic-transfer problem:

```bash
python -m app.ml.train_pilot_model
```

The declared pilot contains 18 districts in six neighboring 2-degree blocks,
4,597 rows, and 652 positive district-dates. It uses leave-one-block-out
validation so every pilot block is tested while absent from training. The
result is also **not deployed**: block ROC-AUC was 0.5567, district ROC-AUC was
0.5295, and temporal ROC-AUC was 0.4962. This demonstrates that reducing the
coverage area alone does not resolve the mismatch between district impact
reports and point-based hydrometeorological inputs.
