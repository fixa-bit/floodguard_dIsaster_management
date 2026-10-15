# Simulation: assessment of tributaries and branched flood spreading

Reviewed 2026-10-15 following the user's question about the missing small branches in Storm replay. **Status: assessment and proposed next stage; branch-aware inundation has not been implemented.** Existing animation and exposure totals remain based on their documented hypothetical river buffers.

## Verified cause in this repository

`app/gis/data/pakistan_osm_waterways.geojson` contains six named major-river features: Indus, Sutlej, Chenab, Jhelum, Ravi, and Kabul. It does not provide a comprehensive local stream, canal, ditch, or drain network. The Jhang asset lists Chenab, Jhelum, and Ravi as relevant major-river references; clipped geometry may be empty where a reference only passes near the boundary.

`scripts/build_outlook_flood_exposure.py` creates each example by buffering the selected river lines by 250, 500, 1,000, 2,000, or 4,000 m and clipping the result to the district. It does not use elevation, terrain connectivity, hydraulic gradients, levees, culverts, channel capacities, or mass-conserving water routing. Adding more particles can improve the surface appearance but cannot produce data-supported new flood pathways outside those saved footprints.

The downloaded Jhang terrain is approximately 262 m spacing and is used as an optional hillshade only. It does not currently determine inundation. Narrow channels and many road/levee-scale flow controls cannot be resolved at that display resolution.

## Separate the two requested capabilities

1. **Mapped tributaries and local waterways:** obtain a fuller observed/mapped network, preserving its provenance and distinguishing natural streams from canals, ditches, and drains. Rendering a mapped waterway does not establish that it is flooded in the selected example.
2. **Floodwater splitting into additional paths:** calculate connected inundation over suitable terrain, accounting for inflows and relevant barriers. A watershed flow-direction raster alone does not simulate backwater, overtopping, culverts, or changing floodplain flow.

## Candidate data and models

- [OpenStreetMap waterway data](https://wiki.openstreetmap.org/wiki/Key:waterway) distinguishes rivers, streams, canals, ditches, drains, and water-control structures. Local coverage and connectivity require inspection before use.
- [HydroRIVERS](https://www.hydrosheds.org/products/hydrorivers) adds a connected larger river network. Its inclusion threshold is catchment area of at least 10 km² or long-term average discharge of at least 0.1 m³/s, so it cannot be assumed to contain every small field drain.
- [Copernicus GLO-30](https://registry.opendata.aws/copernicus-dem/) offers a possible nominal 30 m starting grid where public tiles are available. It is a surface model including vegetation and structures. Actual Jhang tile access, elevations/datum, drainage conditioning, and suitability still need checking; it should not be described as a surveyed bare-earth channel model.
- A limited, terrain-connected what-if method could provide a more geographically plausible demonstration, with explicit assumptions. A validated dynamic flood simulation requires a suitable solver, channel geometry/bathymetry, boundary hydrographs, roughness, barriers, datum alignment, and historical validation. [HEC-RAS terrain guidance](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/latest/developing-a-terrain-model-and-geospatial-layers) and [2D mesh/breakline guidance](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/latest/geometry-data/2d-flow-areas) describe relevant terrain and flow-control requirements.

## Suggested implementation sequence

Start with a small Jhang study area to limit download, computation, and memory. Audit the detailed channel network and finer DEM before selecting a routing method. Add mapped waterways as geographic context; then develop a separately labeled terrain-guided example with connected inundation and clearly stated inputs/assumptions. Recompute flooded area and population intersections from every resulting footprint so the existing bar cards and inspection line remain consistent with the displayed water.

Keep the current example available as a baseline. Precompute model/terrain products outside the browser and load compact frames or tiles in the web portal. Do not imply all mapped canals become flooded, and do not label illustrative depths, velocities, timing, or return periods as calibrated outputs. Record the chosen data, features, routing method, uncertainty, and validation in a separate implementation feature document when this work is undertaken.
