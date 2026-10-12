# GIS flood exposure engine

The engine reads prepared datasets from the separate exposure workspace and integrates with the existing FastAPI router under `/api/v1/exposure`. The active pilot is Trimmu Headworks within the official Jhang district administrative study area. It is not an upstream catchment model. No frontend files are changed.

Set `EXPOSURE_DATASET_ROOT` to a folder containing `processed/<region>/` and its preparation manifest. The default local layout is `../flood_model/exposure_infrastructure/datasets/exposure`. `EXPOSURE_OUTPUT_ROOT` optionally overrides output storage; otherwise analyses are written to `analysis/<region>/<analysis UUID>/` below the dataset root. Inputs are read-only. Balloki and Trimmu outputs stay separate. Install the updated backend `requirements.txt` before starting FastAPI.

## API

| Method | Endpoint | Output |
|---|---|---|
| GET | `/api/v1/exposure/regions` | Available prepared regions and historical reference availability |
| GET | `/api/v1/exposure/regions/{region}/audit` | Coverage, CRS, geometry, duplicates, missing data and reference alignment |
| POST | `/api/v1/exposure/analyses` | Exposure summary and artifact URLs |
| GET | `/api/v1/exposure/analyses/{region}/{analysis_id}` | Saved JSON summary |
| GET | `/api/v1/exposure/analyses/{region}/{analysis_id}/layers/{layer}` | Saved GeoJSON map layer |

Historical reference request:

```json
{
  "region": "trimmu_jhang",
  "flood_source": "historical_reference",
  "population_method": "fractional_area",
  "include_reference_buildings": true
}
```

The prepared UNOSAT 4197 reference is satellite-detected water from 26 August–7 September 2025 at 375 m resolution. It is preliminary, not field validated, and not a live forecast or this portal's model output. Source metadata and explicit geometry repairs remain in the preparation report. The service never silently substitutes a sample if the historical reference is missing.

To use a georeferenced user polygon, set `flood_source` to `provided`, include a Polygon, MultiPolygon, Feature or FeatureCollection in `flood_extent`, and declare `flood_crs` (default EPSG:4326). The result is labelled `user_provided_unverified`; a source label alone does not establish observed accuracy. Empty FeatureCollections are allowed and produce zero geometric exposure. Invalid or nonpolygon geometries are rejected with HTTP 422.

To explicitly test without an actual extent:

```json
{"region":"trimmu_jhang","flood_source":"sample","include_reference_buildings":false}
```

This creates a deterministic rectangle around the configured station. Summary and every GeoJSON layer carry `is_sample: true` and `flood_kind: synthetic_sample`. It is never presented as measured or forecast flooding.

## Calculations and interpretation

- All flood polygons are transformed with longitude/latitude axis order, unioned to remove overlapping water counts, and clipped to the configured study polygon. Holes are retained. Boundary-only contact produces no polygon or road exposure.
- WorldPop counts are read on their native grid without resampling or reprojection of values. The default weights each cell by the fraction of its area intersecting water, measured in EPSG:6933. This conserves each cell's total and assumes uniform within-cell population. `cell_center` is an explicit coarser alternative. Nodata is unknown, not zero; no valid population coverage returns a null exposed-population estimate. Estimates cover known cells and include a coverage fraction.
- Buildings require positive overlap area. Road length is the WGS84 geodesic length of flood-intersected line geometry, in kilometres; split segment count and unique OSM-way count are separate. Roads retain directionality and source tags. Geometric overlap does not prove a road is closed.
- Hospitals, schools and settlements retain source attributes and IDs. Covered points, including points on the flood boundary, are counted. Polygonal facilities require positive overlap. Settlement overlap is exposure, not proof of isolation.
- Repeated feature IDs are suppressed. Exact building footprints are deduplicated within each inventory; exact retraced road segments are suppressed within the same OSM way. Co-located distinct facilities and separate carriageways are retained. OSM buildings and Microsoft's image-derived detections are returned in separate layers and totals and **must not be summed**. Detection confidence/imagery age and OSM completeness remain source limitations.
- The analysis fails with a clear HTTP 503 when required files, CRS or valid geometries are missing. An empty mapped inventory carries a review warning. The API does not invent facilities or silently convert missing files to zero counts.

Outputs include `summary.json`, `audit.json`, a completion marker, `flood_extent.geojson` and affected roads/buildings/hospitals/schools/settlements, plus optional `reference_buildings.geojson`. GeoJSON is EPSG:4326; infrastructure geometries show the inundated part. Completed artifacts alone are exposed by download routes. GeoJSON is streamed to disk; responses contain URLs rather than embedding large vector collections.

GIS analyses run synchronously in FastAPI's worker thread pool. One analysis per process is allowed; a concurrent request receives HTTP 409. Audits are cached by dataset size/mtime and source verification metadata. Use `refresh=true` to force a repeat. For large province/national runs, use the CLI to avoid HTTP client timeouts; use a background job queue before deploying long multi-worker production workloads.

```powershell
.venv/Scripts/python scripts/run_exposure_analysis.py --region trimmu_jhang --source historical_reference
.venv/Scripts/python scripts/run_exposure_analysis.py --region trimmu_jhang --source sample --without-reference-buildings
```

Other Pakistan regions use the same code: first prepare a uniquely named bbox, polygon, district, province or national selection using the acquisition module, then pass that name as `region`. Geodesic road measurements and the equal-area population calculation avoid assuming all regions share one UTM zone.

Tests use small synthetic fixtures for exact counts, partial cells, holes, overlapping/empty extents, CRS transforms, nodata, duplicate features, point/polygon boundary rules, geodesic lengths, missing files and API artifact access. Synthetic fixtures are never written into the prepared Trimmu dataset.

## Completed Trimmu verification

Historical analysis `6f445015-b93c-475f-b796-9276681f647a` is saved under `analysis/trimmu_jhang/` in the exposure dataset root. Its analyzed historical water extent covers 975.05 km². The partial population estimate is 313,436.40 people; cells with known population values cover only 57.44% of that water area, so this is not a complete affected-person count. Intersections include 405.60 km of mapped roads (3,240 segments, 539 OSM ways), 16 mapped settlements and 56,686 independent image-derived building detections. No OSM buildings, hospitals or schools intersect this extent; sparse OSM coverage prevents interpreting those zeros as absence. Reference detections remain separate from OSM counts and are not field-verified buildings.

Dataset preparation passed technical checks while retaining review flags for source completeness and model-output alignment. The historical reference aligns spatially with Jhang; no portal model flood output was available for comparison. All nine baseline Balloki data files retained their SHA-256 hashes. The backend/API/GIS test suite passed 24 tests; the latest six exposure tests and the subsequent focused CRS/extent test also passed. Live HTTP requests returned 201 for a labelled sample calculation and 200 for saved historical summary/layer downloads.

The reusable artifact validator independently checks saved feature counts, geometry validity, duplicate IDs, sample/source labels, containment within flood and study polygons, and geodesic road totals. The historical run passed all checks, including all 56,686 reference detections. A numerical tolerance of `1e-9` degrees is recorded in its report.

```powershell
.venv/Scripts/python scripts/validate_exposure_artifacts.py --region trimmu_jhang --analysis-id 6f445015-b93c-475f-b796-9276681f647a
```

This writes `artifact_validation.json` beside the saved analysis; it does not modify inputs or repeat exposure calculations.

Source and method references: [WorldPop](https://hub.worldpop.org/), [UNOSAT 4197](https://unosat.org/products/4197), [OSM attribution](https://www.openstreetmap.org/copyright), [Microsoft reference footprints](https://github.com/microsoft/GlobalMLBuildingFootprints), [Rasterio masking](https://rasterio.readthedocs.io/en/stable/topics/masking-by-shapefile.html), [pyproj geodesic calculations](https://pyproj4.github.io/pyproj/stable/api/geod.html).
