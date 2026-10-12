# Flood-affected population module

The GIS Operations page now includes a population panel and layers in the existing MapLibre map. The initial region is `trimmu_jhang`, using the prepared WorldPop 2025 counts and official Jhang district exposure boundary. This administrative study area is not a Trimmu upstream catchment. Balloki inputs and previous exposure analyses remain separate and unchanged.

## Run and view

Install backend `requirements.txt`, start the existing FastAPI server, and run `npm run dev` in `frontend`. Open GIS Operations. The panel loads the latest completed population analysis; Calculate population starts a background job and polls its status. Cards show exposed people, percentage of known population, population coverage of mapped water, and mapped settlements. District/tehsil charts, population density bands and clickable administrative polygons display the same persisted statistics. Layer checkboxes control flood extent, population density, administrative exposure and affected settlements. Every result retains its source label; synthetic scenarios display an explicit test banner and `is_sample: true` in all map layers.

## API

| Method | Route under `/api/v1` | Behavior |
|---|---|---|
| POST | `/population/analyses` | Returns 202 with durable analysis ID and status URL |
| GET | `/population/analyses/{region}/{id}/status` | QUEUED, RUNNING, COMPLETED or FAILED with error details |
| GET | `/population/analyses/{region}/{id}` | Completed summary JSON |
| GET | `/population/analyses/{region}/{id}/layers/{layer}` | Completed GeoJSON |
| GET | `/population/regions/{region}/latest` | Most recently completed result, or null |

```json
{"region":"trimmu_jhang","flood_source":"historical_reference","grid_km":2}
```

Other flood sources are `provided` (GeoJSON in `flood_extent`, with declared `flood_crs`), `sample` (a deterministic station rectangle), and `segmentation`. No segmentation output was found in the existing project. The dashboard can upload polygon GeoJSON in EPSG:4326. The API also supports projected polygon coordinates with their declared CRS. Overlapping flood features are unioned before calculations; holes and empty extents are preserved. Invalid polygons are rejected explicitly.

To use a trusted segmentation raster, add this configuration to the region's prepared `metadata/manifest.json` under `configuration`:

```json
{
  "population_analysis": {
    "segmentation": {
      "path": "processed/trimmu_jhang/flood_extent/model_mask.tif",
      "flood_values": [1],
      "label": "Model segmentation: specify model/version/observation date"
    }
  }
}
```

The path is relative to the exposure dataset root. The raster must contain one classified band and a CRS. Nodata and nonfinite cells are excluded; only the configured flood classes are polygonized. Probability rasters require explicit classification beforehand. No arbitrary filesystem path is accepted through the public API. Satellite/model provenance and performance are separate from spatial alignment checks.

## Population and aggregation rules

The engine reads native count pixels with Rasterio and NumPy and uses GeoPandas to read/reproject administrative polygons. For each native raster cell, it multiplies the population count by the intersection area divided by the complete cell area, measured in EPSG:6933. Both flooded cells and cells split by study/district/tehsil boundaries use fractional areas. This assumes uniform population inside each cell; no population values are resampled or overwritten. Nodata is unknown, never zero. A flooded area with no known population coverage returns a null estimate.

Percentage exposed is the estimated exposed population divided by known population within the study polygon. This denominator is also fractionally clipped at the study boundary. It can differ slightly from the previous exposure engine's whole-cell-centre total. District/tehsil geometries are clipped to the study area. Repeated IDs are dissolved; different administrative units with overlapping area are rejected. Statistics for ADM2 and ADM3 are separate partitions and must not be added together. Each partition reports allocated and unassigned exposure and checks its sum does not exceed the regional total. Tehsil boundaries are currently unavailable for Trimmu, so no tehsil totals are fabricated.

The display grid aggregates native cell contributions by their centre coordinates in an equal-area grid. It preserves the population sums but is a cartographic approximation at grid boundaries; exact administrative statistics use polygon fractions. Density bands summarize exposed population by the underlying raster cell's people/km². A maximum approximate 20,000-cell display grid prevents unbounded map payloads; use `grid_km: 10` or `25` for large regions. Other Pakistan regions use uniquely named prepared region directories and the same API/CLI.

## Saved outputs and validation

Outputs live under `analysis/population/<region>/<UUID>/` in persistent exposure storage: summary JSON, status JSON, flood extent, administrative exposure, population grid and affected settlements GeoJSON. Only completed analyses can be downloaded. Missing population data, invalid geometry, overlapping boundaries and missing segmentation produce explicit job errors. One population job runs per backend process; additional concurrent requests return 409. Jobs use a process-local thread executor with persisted state; interrupted jobs are not automatically resumed after a server restart. Use a durable external queue before scaling long jobs across production workers.

The historical Trimmu calculation uses the existing [UNOSAT 4197 reference](https://unosat.org/products/4197), observed 26 August–7 September 2025. It is preliminary satellite-detected water at 375 m resolution, not a live flood forecast or portal segmentation output. Results: approximately 313,436 exposed people, 9.66% of known study-area population, with known population cells covering 57.44% of the mapped water. Jhang's district exposure equals the regional total. The coverage gap prevents treating this as a complete affected-person count.

```powershell
.venv/Scripts/python scripts/run_population_analysis.py --region trimmu_jhang --source historical_reference
.venv/Scripts/python scripts/validate_population_analysis.py --region trimmu_jhang --analysis-id ab793c55-8a46-426c-b31f-588f0159741d
.venv/Scripts/python -m pytest -q tests/test_population.py tests/test_exposure.py tests/test_api.py tests/test_gis.py
cd frontend
npm run build
node scripts/validate-population.mjs
```

Tests check partial cells crossing administrative boundaries, unioned floods, missing/empty extents, nodata, binary segmentation classes, CRS, duplicated boundary IDs, overlapping administrative areas, unassigned population, distribution totals, read-only raster preservation, background jobs and API artifacts. The browser check verifies cards, map rendering, clickable population regions, layer toggles, unavailable tehsil messaging and mobile layout. Raster operations follow [Rasterio's geometry masking API](https://rasterio.readthedocs.io/en/stable/api/rasterio.features.html); administrative reads use [GeoPandas](https://geopandas.org/en/stable/docs/reference/api/geopandas.read_file.html).
