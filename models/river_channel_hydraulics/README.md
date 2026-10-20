# White River hydraulic animation

This replaces the arbitrary dry-field point-source experiment in the fifth replay tab. The user selected the complete USACE White River model instead of a Chenab model with assumed bathymetry. The other replay tabs and their models are preserved.

The inputs are the original official **Muncie 2025** HEC-RAS example, Indiana, USA. The model includes channel terrain, a 7,257-cell hydraulic mesh, roughness/property tables, initially wet channel cells, an upstream flow hydrograph, downstream normal depth (slope 0.001) and a stage boundary. Original upstream flow rises from 1,000 to 20,000 cfs. No point source, channel buffer widening or newly carved channel is introduced.

The official installed HEC-RAS 2025 Beta CPU implicit diffusion-wave solver was actually run for this feature. Visual review of the original sample start revealed incomplete channel wetting, so `prepare.py` first runs a 24-hour, 1,000 cfs baseflow scenario using the original starting downstream stage. Its final native cell depths and face velocities initialize a second 24-hour run with the original flood boundary series. This establishes 970 wet cells throughout the channel before the rise; final-hour baseflow volume drift is approximately 6.2e-8. Retained active output: `white-river-initialized.h5`; `initialization.json` records every changed input and result hash. The earlier `white-river-computed.h5` remains as an archived initial attempt. Original geometry, roughness and terrain remain unchanged under `tools/hec_ras/runs/muncie_trial/`, with provenance in `models/hec_ras_2d/muncie-inputs.json`. This example is not a Pakistan flood simulation or validation against observations.

From the project root:

```powershell
.venv/Scripts/python.exe -m models.river_channel_hydraulics.prepare
.venv/Scripts/python.exe -m models.river_channel_hydraulics.export
.venv/Scripts/python.exe -m pytest tests/test_river_channel_hydraulics.py -q
```

Use a fresh result filename/directory for later model experiments; keep retained completed runs unchanged. `export.py` reads this result, verifies model input checksums and native successful completion, and invokes **native `ras result map`** for all 25 hourly depth profiles using the original terrain. The source terrain includes a channel terrain overlay. Native mapping is at 10 US survey feet, then reprojected to a web display grid. Fine mapping pixels do not refine the hydraulic mesh. The browser displays actual hourly profiles without generating intermediate hydraulic results.

For animation, the exporter reconstructs a cell vector by solving a length-weighted least-squares fit to the native signed face-normal velocities. It verifies that face orientation points from left to right cell, rotates native coordinate vectors to geographic east/south, converts native feet/s to metres/s, and assigns each vector to its original hydraulic polygon. Dry pixels suppress vectors. Bilinear interpolation is limited to wet display pixels. The animation therefore derives from hydraulic output, not an artistic river-line field. This is a visualization reconstruction, not a claim of independently simulated subcell velocities.

`frontend/public/river-channel-flow/frames.bin.gz` decompresses into 25 row-major frames. Each frame has three little-endian int16 planes: mapped depth, east velocity and south velocity, all with a scale of 0.001 in m and m/s. The manifest includes exact raster dimensions, 0.1 m display wet threshold, map/terrain scales, initial wet count, native result hash, payload hash, boundary geometry and source references. Terrain gaps remain explicitly marked as NoData; the inspector never presents them as real zero elevations. Particle travel displays at 60× for legibility, independently of timeline playback compression.

Browser controls retain play/pause, reset, seek, playback speed, imagery fallback, flow trails, close-up, study area and inspection. The timeline starts with an existing wet river. Additional wet area is relative to the initial modeled wet footprint; it is not a damage estimate. The archived old NDMA exporter, assets and numerical tests remain for provenance but are no longer selected by the tab.

Tests verify a manufactured known vector against signed face-normal reconstruction, completed native solve status, initially wet cells and boundary types, source and payload hashes, depth quantization, nonnegative depths and growth beyond the starting river. Browser checks cover actual changing water pixels, pause, seeking, an initially wet reset, inspection, layers, restart, reduced motion, mobile width, the original district replay and download failure/retry.

Primary references: [USACE 2D output documentation](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.4/viewing-2d-or-1d-2d-output-using-hec-ras-mapper/2d-output-file-hdf5-binary-file), [official Muncie sample manifest](https://s3.hecdev.net/ras-public-examples/Muncie%202025-2024-Sep-30%2010-37-23.json).
