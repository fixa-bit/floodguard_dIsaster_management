# 10-Year Outlook: hypothetical flood-spread layer

Implemented 2026-10-14 inside **Predictive Risk Views → 10-Year Outlook → Current versus future**. Other map tabs, forecasts, alerts, and incidents are unchanged.

## Experience

**Flood spread** enables the layer. If the view shows all eight districts, enabling a layer selects Jhang so the footprint is visible. The **Example flood level** slider supports 0–5, keyboard navigation, and bar-chart selection. The existing two synchronized, zoomable maps are reused: the left supplies context with no example flooding; the right shows the selected footprint. This feature adds no WebGL canvas or map service.

Level 0 is empty. Levels 1–5 are progressively wider, nested example corridors, **not water heights, discharge values, official severity categories, or validated inundation predictions**. The selected level is independent of the outlook year, scenario, and flood-type index. The interface states these assumptions beside the control.

## Geometry strategy and actual inputs

- Existing local `app/gis/data/pakistan_osm_waterways.geojson`: approximate, derived OSM reference alignments for Indus, Chenab, Jhelum, Ravi, Sutlej, and Kabul. These are reference lines, not hydraulic centerlines or observed flood extents.
- Existing `frontend/src/data/pakistan/pakistan_districts.geojson`: display district outlines, not catchments or official flood-management zones.
- Transform each selected district and relevant rivers to its local UTM zone. Buffer by arbitrary example distances **250, 500, 1,000, 2,000, and 4,000 m**, then clip to the district. Area calculations and population intersections use equal-area EPSG:6933.
- Store five incremental rings. Filtering `min_level <= selected_level` grows the map footprint without recomputing geometry or uploading full GeoJSON during slider movement. Analysis uses the original footprints; map geometry is simplified at 12 m and topology-snapped to 5-decimal longitude/latitude for a small, valid display asset.
- Seven example districts have an intersecting/nearby reference river: Jhang, Multan, Lahore, Rawalpindi, Charsadda, Sukkur, and Dadu. **Badin has no usable local river alignment**. It shows an explicit unavailable message and disables the slider; no footprint or affected-population value is invented. Its population layer remains usable.

The map source credits OSM contributors. Layer requests load only the selected district after a layer is enabled and use the existing hashed/gzip static-asset cache. A failed request can be retried. Switching districts clears old results immediately. Turning both layers off restores the index legend and district shading.

## Files and regeneration

- `frontend/src/components/TenYearFloodExposure.tsx`: layer controls, sources, slider, context notices, and population summary/chart.
- `frontend/src/components/TenYearComparisonMaps.tsx`: mounts the feature around the existing comparison maps.
- `frontend/src/components/outlookFloodExposureData.ts`: asset URLs, types, rounded display counts.
- `frontend/src/data/outlook-exposure/*.geojson`: precomputed portable district bundles.
- `frontend/src/data/outlook-exposure/metadata.json`: versions, formulas, resolution, source names/hashes, licensing, and coverage.
- `scripts/build_outlook_flood_exposure.py`: reproducible offline builder, using existing Python GIS dependencies. Opens source rasters read-only, streams small row windows, writes only this feature's frontend assets.

```powershell
.venv/Scripts/python.exe scripts/build_outlook_flood_exposure.py --population-raster D:/Projects/flood_model/exposure_infrastructure/datasets/exposure/raw/worldpop/pak_pop_2025_CN_100m_R2025A_v1.tif
.venv/Scripts/python.exe scripts/check_outlook_flood_exposure.py
cd frontend
node scripts/validate-outlook-flood-exposure.mjs
npm run build
```

The external raster is only needed to regenerate assets, not to run the app. No downloads, new packages, backend calculations, database changes, alerts, incidents, or raw-data modifications are required.

## Limitations and future scope

A river buffer cannot establish how water actually propagates. This version ignores terrain, levees, obstructions, reservoirs, drainage, flood duration, and hydraulic connectivity. In particular, Rawalpindi's corridor uses the available Jhelum reference; it is not a simulation of urban/flash flooding in the city. The experiment does not calibrate the user's earlier forecast threshold lines to flood extents.

A future version needs vetted river/drainage networks, elevation and levee data, station height/discharge relationships, sourced historical flood footprints, and hydrodynamic validation. Only then should flood levels be expressed as physical water heights or connected to modeled discharge. Add urban/flash/coastal mechanisms separately with appropriate inputs. Population methodology is documented separately in [ten-year-population-exposure-layer.md](ten-year-population-exposure-layer.md).

## Verification

Offline checks verify source signatures, valid clipped map geometries, nested/nondecreasing extents and exposure, empty level 0, and honest unavailable values. The browser check covers slider endpoints/keyboard input, level-bar selection, seven supported districts plus Badin, retry and stale-result handling, fixed-year semantics, actual cell popups, layer toggles, compact desktop layout, inactive-map cleanup, and no backend writes. Existing preview and motion checks protect the rest of this sub-tab.
