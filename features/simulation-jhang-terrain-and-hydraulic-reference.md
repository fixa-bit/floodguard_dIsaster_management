# Simulation: Jhang terrain acquisition and hydraulic reference

Added 2026-10-15 following the user's request to obtain real terrain and hydraulic data for the current study location. Available in **Simulation → Storm replay → Jhang** with a **Terrain** layer toggle, source credits, and downloads in **Inputs & Method**. Other districts retain their existing data and do not claim this terrain coverage.

## Data obtained

**Real terrain:** 25 public Terrarium elevation tiles from the [AWS Terrain Tiles catalog](https://registry.opendata.aws/terrain-tiles/), maintained by Mapzen/Tilezen. The catalog requires no AWS account. The [official format documentation](https://github.com/tilezen/joerd/blob/master/docs/formats.md) specifies the RGB elevation decode `R × 256 + G + B / 256 − 32768`, in metres. [Attribution and source licensing](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) identify the mixed global sources, including USGS SRTM/GMTED2010. This is an archived mixed-source elevation product, not a new high-resolution survey of buildings, levees, or river beds.

The acquisition uses zoom-10 tiles covering the Jhang study rectangle, crops to integer source pixel bounds, and area-averages the elevation to a 427 × 507 EPSG:3857 grid. Effective sampling is approximately **262 m** near the study center. Actual values in the downloaded rectangular window range from **120.5 to 183.8 m**. These figures describe the window and product; they are not station water levels or flood-trigger thresholds. Provider vertical reference is not aligned to a local station gauge datum.

**Historical hydraulic reference:** the [Federal Flood Commission Jhang/Bhakkar floodplain map, Sheet 8](https://ffc.gov.pk/wp-content/uploads/2019/02/Sheet8_flood.pdf). The PDF was downloaded, its `%PDF` signature checked, and its byte length and SHA-256 recorded in the metadata. It supplies a relevant official historical reference to review. Its archived project model and map cannot be treated as a current boundary hydrograph, a time-varying inundation grid, surveyed channel bathymetry, or a calibrated model for this portal. No numerical threshold, return period, or predicted depth was extracted into the replay from it.

The existing portal also has FFD station observations and GloFAS/GEOGloWS modeled discharge services. Their units, reach/station matching, timing, uncertainty, and gauge datum must be reconciled before using them as hydraulic boundary conditions. They have not been silently connected to the hypothetical replay timeline.

## Generated assets

Under `frontend/public/simulation-terrain/`:

- `jhang-dem.tif`: real cropped/aggregated elevation GeoTIFF, 176,593 bytes.
- `jhang-hillshade.png`: derived 427 × 507 hillshade, 102,218 bytes.
- `jhang-metadata.json`: source URLs and hashes for every tile, output hashes, extent, resolution, elevation range, access date, processing method, vertical-reference caveat, and FFC reference retrieval/hash.

Source tile and PDF downloads are cached outside the repository in the OS temporary directory under `floodguard-jhang-terrain`. The PDF is linked to its official source in the UI, rather than republished as a portal asset. The small DEM can be downloaded from Inputs & Method for future work.

Hillshade uses finite-difference gradients, a northwest light, and **6× lighting exaggeration** to make subtle plain relief visible. This affects lighting only. The elevation values remain unexaggerated in the GeoTIFF. `useReplayTerrain.ts` overlays the hillshade as a local image source, credits the terrain provider visibly, and prevents an unavailable optional terrain layer from disabling the replay.

The terrain is **context only**. It does not clip, reroute, or replace the existing flood extents or alter population estimates. There is no inferred water surface, no terrain-derived hydraulic depth, and no fake measured velocity. The [natural-water renderer](simulation-natural-water-animation.md) remains a separately documented artistic presentation.

## Reproduction and validation

From the repository root, using the existing environment without installing packages:

```powershell
.venv/Scripts/python.exe scripts/fetch_simulation_jhang_terrain.py
.venv/Scripts/python.exe scripts/check_simulation_jhang_terrain.py
```

The download script uses four bounded concurrent tile requests and caches them. It processes a small local window instead of loading a global DEM. The validation verifies all source/output records and hashes, GeoTIFF CRS/extent/dimensions/resolution and actual finite elevation range, alignment of the hillshade, and the explicit non-hydraulic status of terrain and the FFC reference. The browser water-material check verifies successful local asset access and honest Jhang-only coverage.

Acquisition and the Python terrain validation passed on 2026-10-15. The natural-water browser check passed with both blocked optional imagery and live satellite imagery, including local DEM access, terrain layer toggles, and missing terrain coverage outside Jhang. The original replay, 2D Simulation, and Cinematic 3D checks passed with no browser errors or operational writes, and the production build passed.

## Remaining work for a credible hydraulic simulation

Obtain finer elevation and drainage data, surveyed channels and structures, vertical datum transformations, time-aligned inflow and water-level boundary conditions, and friction/roughness assumptions. Run an appropriate 2D hydraulic model and validate extent, arrival time, depth, and flow against historical floods and observations. Publish its uncertainty and resolution limits. These are prerequisites for the reference video's building-scale flow-routing and water-depth/velocity claims; adding terrain shading alone does not provide them.
