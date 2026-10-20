# Simulation: small Jhang terrain-guided prototype

Implemented 2026-10-15. **Experimental connected-fill sensitivity study, not a calibrated flood forecast or a hydraulic solver.**

## Where it sits and what stays available

Simulation → **Storm replay** → **Jhang terrain prototype**. The default **District storm replay** still provides the previous hypothetical buffer-based event. Monitoring scenario, Flood spread & population, the ten-year outlook, saved readings, alerts and incidents keep their existing behavior. Switching study modes unmounts the previous map/canvas and stops its animation. The monitoring form stays mounted and retains its draft.

The prototype makes no API writes and cannot create operational readings, alerts or incidents. It uses the existing web MapLibre engine and canvas water renderer, with no mobile tooling or additional dependencies.

## Study area and data audit

Fixed bounds: **72.18–72.35°E, 31.23–31.37°N**, approximately **251.445 km²**, around the Chenab near Jhang. This is a local study window, not a Jhang district forecast. All nonzero examples reach this window's edge; the UI explicitly identifies that truncation.

| Dataset | Actual inputs in this version | Gaps |
| --- | --- | --- |
| [Copernicus GLO-30 public COG](https://registry.opendata.aws/copernicus-dem/) | A buffered window of N31E072; bilinear reprojection to EPSG:32643, 30 m cells, 554 × 532 grid; 279,377 valid study cells; elevation approximately 142.74–169.45 m | Surface model includes vegetation/structures; not surveyed bare earth or bathymetry; no station-gauge alignment |
| [OpenStreetMap waterways](https://www.openstreetmap.org/copyright) | Clipped ways: Chenab river `75652156`, canals `73321123` and `275774469`; waterway type, English name where present and mapper verification note | No streams/drains/ditches returned in this window; natural-water area query returned zero ways; one canal has a mapper's visibility/verification note; incomplete coverage is not evidence that drains do not exist |
| [WorldPop Pakistan 2025 constrained 100 m](https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/100m/constrained/pak_pop_2025_CN_100m_R2025A_v1.tif) | Existing local R2025A v1 count raster, window reads only; native pixel counts and NoData; approximate density image at native resolution | Provider's alpha release; modeled population, fixed at 2025; missing raster cells are excluded, never treated as known zero |

Copernicus source tile:

`https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N31_00_E072_00_DEM/Copernicus_DSM_COG_10_N31_00_E072_00_DEM.tif`

The AWS source is the public 2021 COG release; the filename's `10` denotes one arcsecond, not 10 m. Elevations use the provider's EGM2008 reference and are not gauge heights. Downloads read a small window using HTTP byte ranges, rather than a national DEM.

OSM was queried read-only through `https://maps.mail.ru/osm/tools/overpass/api/interpreter` after other public endpoints failed. Snapshot timestamp is recorded in `metadata.json`. The query is `way["waterway"](31.23,72.18,31.37,72.35);out geom;` with JSON output and a 25-second server timeout. Only the clipped, attributed ODbL derivative is distributed; the raw response is cached outside the repo.

## Engineered inputs and projection method

1. Densify the geographic study boundary before projecting to local UTM 43N; rasterize it by cell centers. Read a buffered source crop to avoid artificial NoData barriers at the study edge. Outside-study cells stay NoData.
2. Rasterize the **mapped river centerline only** using all-touched cells as sources. Neither canal is a flood source; canal beds or embankments are not burned into the DEM.
3. Sample a lower local DEM statistic: the **10th percentile within 300 m** around points approximately 60 m apart along the river. Smooth these samples using a 17-sample median and a Gaussian filter with sigma 4 samples. This is an **assumed DEM-derived reference**, not measured water elevation, river bed level or HAND validated against a drainage network.
4. Give each grid cell its nearest smoothed reference sample, then subtract that reference from its elevation. Force the source cells' relative height to zero. No other terrain cells are lowered.
5. Run a multi-source **four-neighbour minimax search**. A cell activates at the smallest possible maximum relative height along any path connecting it to a river source. NoData is impermeable. Diagonal corner shortcuts are excluded. A low but disconnected depression cannot activate until its connecting sill is crossed.
6. Preserve the six rounded examples for reporting, while the map uses a continuous 0-3 m minimax sill surface. Its slider and playback move in 0.01 m steps; impact summaries are calculated every 0.05 m and interpolated between those points. These are exploratory inputs, not probabilities, return periods, warnings, water depths or accuracy claims. Fine control does not imply fine terrain accuracy.
7. The connected extent at rise zero is an **assumed reference extent** (approximately 10.985 km²), not a map of observed river water. Exclude it from the incremental area and population counters at every level. Display it in a separate, muted layer.
8. Save the legacy nested display bands and a new 16-bit sill-threshold raster. The browser compares each cell threshold with the current stage and progressively reveals connected terrain cells. Floodplain spread is a separate optional layer; the mapped Chenab ribbon remains distinct.
9. Derive representative spatial connection paths from the minimax search parent tree. These are inferred terrain connections, not surveyed streams, flow vectors or arrival paths. The animated Chenab is drawn from its mapped centerline using a 90 m illustrative ribbon (not a measured channel width). Mapped canals remain separate context.

No rainfall, historical flood threshold, trained machine-learning model, river forecast, Manning coefficient, flood volume or hydraulic boundary condition is used by this prototype.

## Population and area strategy

Calculate area in the same projected UTM grid used for connectivity, clipping the grid footprints to the study boundary. Read the existing WorldPop raster in a small window; never resample population counts or modify its source file.

For each valid native population pixel, calculate its projected polygon overlap with the selected added footprint. Multiply its native count by the overlap fraction, assuming uniform population within that pixel. Use disjoint raster row-run rectangles and a spatial index to obtain these overlaps without repeatedly intersecting every population pixel with a giant polygon. This optimization preserves the same polygon areas and fractions.

NoData cells contribute no known population and no known coverage. Show the selected footprint's known-raster coverage immediately beside the impact bars, with the remainder explicitly unknown. Whole-window known coverage is approximately 74.3%; selected nonzero footprints have approximately 78.9–81.4% known coverage. Counts represent **people modeled in the example footprint**, not confirmed affected people or real-time occupancy.

Current snapshot, rounded here for readability; the asset contains unrounded underlying estimates:

| Example index | Assumed relative rise | Added connected area | Population in known raster overlap |
| --- | --- | --- | --- |
| 0 | 0 m | 0 km² | 0 |
| 1 | 0.5 m | 66.86 km² | ~29,000 |
| 2 | 1 m | 84.70 km² | ~39,300 |
| 3 | 1.5 m | 105.06 km² | ~64,700 |
| 4 | 2 m | 130.31 km² | ~101,000 |
| 5 | 3 m | 184.36 km² | ~173,000 |

Large changes at low increments reflect the assumed reference and flat terrain's connectivity. These are sensitivity results, not evidence that an observed 0.5 m gauge rise floods this area. The missing hydraulics and historical validation prevent such an interpretation.

## Visualization and performance

- One zoomable MapLibre map: optional satellite imagery, local elevation relief, native-resolution population density, mapped river/canals, assumed reference extent, added footprint and optional connection paths.
- A 0.01 m continuous stage slider, 0-3 m play/pause/reset, lowest/highest controls, optional floodplain-spread layer, and animated area/population summaries. The chart shows precomputed 0.05 m samples with the current stage marker.
- Playback progresses the assumed stage in 0.01 m increments and reveals cells whose connected terrain sill is reached. It has no physical event clock or flood-arrival time. Chenab surface streak direction/speed remain artistic; pausing freezes stage progression and canvas motion.
- Reduced-motion preference, hidden-document state and off-screen scene visibility stop playback. Static slider use remains available. Map/canvas resources are disposed on mode/tab changes.
- Gzipped, hashed study data loads only after choosing the prototype (~1 MB compressed); context images total approximately 333 KB. The full ~659 KB elevation GeoTIFF is a manual download, not loaded as a browser hydraulic grid. The offline solver and full WorldPop raster never run/load in the browser.
- Optional satellite/image errors leave local footprint geometry and saved counters usable. Core data failure disables controls and exposes a retry. Existing monitoring and other simulation modes remain usable.

## Files, reproduction and provenance

`scripts/build_jhang_terrain_prototype.py` fetches/caches input windows, calculates connectivity/population, and writes:

- `frontend/src/data/jhang-terrain-prototype/jhang-pilot.geojson`: six rounded reporting levels, 0.05 m impact samples, a mapped-stream ribbon, legacy display bands, connection paths and geography; compressed by the existing Vite map-asset plugin.
- `frontend/public/jhang-terrain-prototype/`: `terrain.png`, `population.png`, `flood-threshold.png`, `elevation-30m.tif`, attributed `mapped-waterways.geojson`, `metadata.json`, and `NOTICE.txt`.

The manifest records source URLs, OSM query/snapshot, input window/response hashes, output hashes, grid statistics, reference parameters, continuous raster encoding, metric sample interval, stream ribbon width, limits and credits. Runtime core data and optional context layers never need credentials or API keys. Regenerating with newer upstream data requires reviewing the new snapshot and rerunning checks.

```powershell
.venv/Scripts/python.exe scripts/build_jhang_terrain_prototype.py --population-raster D:/Projects/flood_model/exposure_infrastructure/datasets/exposure/raw/worldpop/pak_pop_2025_CN_100m_R2025A_v1.tif
.venv/Scripts/python.exe scripts/check_jhang_terrain_prototype.py
cd frontend
node scripts/validate-jhang-terrain-prototype.mjs
npm run build
```

The generator reuses `%TEMP%/floodguard-jhang-pilot/` windows/responses. It writes no operational databases and makes no edits to the source population raster. Source provenance, not a mutable absolute workstation path, is distributed with the public assets.

## Validation

- Independent saddle, low-gap, NoData-barrier and diagonal-isolation fixtures; randomized minimax results checked against independent binary flood propagation at seven stages; parent adjacency and nondecreasing connection thresholds.
- Native population-pixel overlap checked against direct polygon intersections, including partial study-boundary clipping.
- Published geometry validity, bounds, projected area agreement within half a 30 m cell, tiny display-band slivers below 5% of one source cell, monotonic area/population, zero added reference impact, source/output hashes, grid resolution and complete DEM coverage.
- The earlier six-stage prototype had browser coverage for lazy loading, map layers, counters, playback, reduced motion, no API writes, and preservation of the original replay and monitoring draft. The continuous raster/slider refinement still needs browser verification.
- Existing storm-replay data and water-field checks, original replay browser regression, and production TypeScript/Vite build were checked before the continuous-stage refinement; rerun relevant checks after that change.

These validate the implementation and internal consistency. **They do not establish flood-prediction skill or hydraulic accuracy.**

## Future scope and limitations

Obtain/verify local drains, tributaries, embankments, gates and culverts. Improve bare-earth elevation and channel bathymetry, inspect the river-reference assumptions, align vertical datums, and enlarge/buffer the domain to test boundary sensitivity. Add measured inflow hydrographs, appropriate roughness and an actual mass-conserving solver if hydraulic depths, velocities or timing are required. HEC-RAS 2D is one possible later solver, not used here. Validate against dated observed flood extents and gauges before presenting operational conclusions.

Existing related feature strategies: [branching assessment](simulation-branched-flood-routing-assessment.md), [district storm replay](simulation-storm-replay.md), [natural water material](simulation-natural-water-animation.md), [impact bars](simulation-exposure-impact-bars.md), and [earlier display-only terrain](simulation-jhang-terrain-and-hydraulic-reference.md).

## Data notices

The UI's Inputs & Method and the downloadable notice include the mandatory derivative attribution and liability sentence from the [Copernicus GLO-30 licence](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf). No official endorsement is implied. Waterways: © OpenStreetMap contributors, ODbL 1.0, with the clipped derivative downloadable. Population: WorldPop 2025, CC BY 4.0. Optional aerial imagery retains Esri/provider attribution.
