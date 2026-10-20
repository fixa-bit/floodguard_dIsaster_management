# Jhang ANUGA hydraulic trial

Added 18 October 2026 after the request to try HEC-RAS or an alternative
simulation method. Open **Simulation → Storm replay → 2D hydraulic trial**.
The existing district replay, terrain connected-fill study and monitoring
scenario remain available. The new trial does not create monitoring readings,
alerts, incidents or operational database records.

HEC-RAS was not installed in the workstation's command path or standard program
directories. The trial uses ANUGA 4.0.1, an open-source finite-volume solver for
two-dimensional shallow-water equations. This is an actual dynamic numerical
run, rather than rebranding the existing minimax connected-fill renderer.
ANUGA is a runnable alternative here, not a claim of universal superiority over
HEC-RAS. Official reference: https://anuga.readthedocs.io/en/stable/

## Computation and inputs

The trial uses a 6 km square within the existing Jhang study, centred on UTM
43N coordinates 239960 E, 3466940 N. The existing, attributed Copernicus GLO-30
surface DEM and mapped OSM Chenab geometry are copied into each run. No new
terrain is invented, and channels are not artificially carved or lowered.

A 120 m regular mesh produces 10,000 triangles. The initially dry surface uses
assumed Manning n=0.04, open/transmissive outer edges, no rainfall and no
infiltration. A volumetric inlet over a 240 m radius on the northern mapped
river receives a **hypothetical** 100 → 1,200 → 100 m3/s hydrograph. The total
prescribed volume is 10,080,000 m3 over six hours. This is not a measured
Marala/Jhang boundary, current forecast, historical flood, or calibrated event.

Reported outputs are stored every 15 minutes: triangle depths, depth-averaged
speed for depth ≥0.1 m, water volume, wet area, cumulative source and boundary
fluxes. The six-hour trial reaches about 4.0284 km2 wet area, maximum sampled
depth 3.5791 m, and maximum sampled wet-cell speed 1.8055 m/s. These numbers
describe the assumed trial only. Outer-edge outflow is significant, so local
flood inference requires a larger-domain/boundary-sensitivity study.

The latest native `.sww` and maximum sampled-depth GeoTIFF use UTM 43N. Public
frame images rasterize actual triangle results and use a fixed depth colour
scale saturating at 3 m. Metrics retain values above 3 m. No invented currents
or measured-gauge labels are added to these images. The raster maximum is over
stored reporting frames, not a claim about unsaved between-frame peaks.

## UI and evidence

`SimulationHydraulicPilot.tsx` loads the saved results lazily and provides time
selection, play/pause/reset, computed metrics and a north-up terrain/depth view.
Inputs, hydrograph, limits, mass error and downloads are under **View details**.
Reduced-motion preference disables automatic playback; static inspection still
works. Optional district map imagery is not needed by this local raster view.

`models/jhang_hydraulic_pilot/` holds the independent numerical environment,
configuration, runner, verifier and reproduction documentation. Every run
retains source inputs, licence/provenance, code, package versions, inlet and
hydrograph, benchmarks, native solver output, cell arrays, time series and
preview products. SHA-256 manifests seal each run. `LATEST_RUN.json` identifies
the selected run; earlier runs are preserved. The backend environment is read
without installing packages into it. Serial CPU operation does not use
MPI/PyMetis; the Windows environment's unused PyMetis dependency is documented.

## Verification

- Still lake: maximum stage error approximately 1.1e-15 m, negligible velocity
  and relative volume error.
- Analytical Ritter dry-bed dam break: depth L1 error approximately 0.00973 m
  at 20 s; the separate acceptance threshold is 0.12 m.
- Six-hour trial: maximum relative water-volume balance error approximately
  2.32e-14. Independent hydrograph integration, metrics recomputed from saved
  arrays, all 47 retained file hashes and the output CRS checks passed.
- Browser: load failure/retry, computed frames and metrics, play/pause/reset,
  details/downloads, reduced motion, mobile overflow, restoration of the
  monitoring draft, and absence of operational writes passed.
- Production TypeScript/Vite build passed.

These checks validate the numerical setup and implementation. They do not
establish Jhang flood-prediction accuracy. Required later inputs include channel
and structure surveys, datum-aligned observed boundary hydrographs/stages,
calibrated roughness and verification against actual floods. Finer mesh and
boundary sensitivity are needed. The 120 m mesh cannot resolve building-scale
flow. HEC-RAS or ANUGA routes supplied inflow; neither creates a credible
year-ahead discharge forecast merely by replacing the chart's model name.

Public assets are precomputed in `frontend/public/hydraulic-pilot/`. No backend
route changes or restart are required. Rebuilding the frontend republishes the
viewer and selected assets for production.
