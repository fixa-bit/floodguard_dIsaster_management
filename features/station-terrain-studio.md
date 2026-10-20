# Station terrain studio

The national operations map now offers a Terrain studio card in GIS Operations and other views that embed NationalRiskMap. It adds true elevation relief and a 58-degree bird's-eye camera while preserving existing monitoring layers and readings. Presets focus Tarbela, Mangla, Marala and Taunsa using the existing station reference coordinates. Once terrain is enabled, choosing another mapped monitoring station focuses its location as well.

`StationTerrainStudio.tsx` uses a MapLibre raster-dem source with Terrarium decoding, hillshade, perspective terrain and a subtle sky/horizon. Presets adjust zoom and bearing to suit reservoir and river reaches. Controls provide relief on/off, bird's-eye/flat perspective, compass north, 1–2× display exaggeration and a flat reset. The four preset elevation readouts use decoded native pixels from the cached source tiles, independent of visual exaggeration; other locations use rendered DEM samples with exaggeration divided out. These are approximate terrain samples, not station gauge readings. Flat river plains remain relatively flat rather than acquiring invented mountains.

The compact card uses translucent dark green surfaces, station buttons, an outlined station beacon and a responsive layout. It begins collapsed and loads no elevation tiles until requested. Entering a station view collapses the long map-layer panel and enables river/lake context. Reduced motion uses immediate camera changes. Zooming back out to the national overview disables terrain, avoiding costly terrain rendering across the country. The national map permits zoom 15 and pitch 70, with a compass/pitch control. Initial overview timers and resize handlers respect an active terrain viewpoint, so they cannot unexpectedly reset the station camera.

`scripts/fetch_station_terrain.py` downloaded **268 unchanged 256-pixel Terrarium tiles** across zooms 0–13 near the four station viewpoints, totaling approximately 15.2 MB. Coarse parent tiles cover the horizon in the tilted view. They are served from `frontend/public/station-terrain/`; `manifest.json` retains file hashes, actual decoded elevation ranges, station coordinates and source attribution. A custom MapLibre protocol uses local indexed tiles first and the original AWS Terrain Tiles endpoint outside those windows. NoData/network failures leave the ordinary flat map available and show a retry message. Satellite imagery remains the existing Esri imagery layer and requires connectivity. Terrain tiles and camera controls do not alter hydraulic model inputs or operational station values.

When a detailed tile beyond the cached window cannot be fetched, the protocol can crop a nearby cached parent up to three levels coarser. It uses nearest sampling of encoded RGB to preserve original elevation values. This is coarser real terrain rather than invented zero-height land. Loaded DEM content is tracked independently of global map idle, since unavailable imagery can keep idle pending. Missing all suitable elevation sources yields the ordinary flat map with a retry message.

To refresh cached elevation data:

```powershell
.venv/Scripts/python.exe scripts/fetch_station_terrain.py
```

From `frontend`, validate with `node scripts/check-station-terrain.mjs` and `npm run build`. The browser check exercises actual local DEM requests, a tilted camera, station presets, relief intensity, north and flat resets, reduced motion and a narrow viewport while operational APIs and remote imagery are unavailable.

Primary references: [MapLibre terrain example](https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/), [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/). Source elevation credits and details remain available through map attribution and the local manifest.
