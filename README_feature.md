1. can you make citizen reports section active such that each report stay visible in portal for a minute and it should be  scrollable window and report should get saved in a db 

can we instead make it two way that it can fetch reports from any db and display and also in its interface there can be a place to enter new report that will also be saved in db

there should be option to put location in report too using google map and a location button and lat long display button too, if pic is geo tagged display location of image too, if image geo tagged extract location from it otherwise see if used provided it otherwise leave it empty but still display fields with null value and also give button to close report and mark it close in db too

add one other layer that changes the river colors based on current river level after every 15 minutes(in case of flood after every 3 minutes)


cntal agnt to monitor all models
nstead show these cities values of respective fields in form of table e.g rainfall shows all related fields for these cities along with time it was updated
, it should get  refresehed after every 1 hr , but there should be a refresh button upon pressing should get recent


Rainfall:



h ourly analytics


simulation active


alert 

agent for monitoring(monitors db and predictions too)


early warning report->approval->send to higher ups

implement all models find where they fit


dont you think i there should be a graph too shown for each model that shows prediction of certain intervals and and also selectable station button also maintain the calculated values in db so that graph only fetch calculated values from db,depending upon model it should choose how many predicted values it needs to map


when time reaches the predicted values should turn grey and real values become highlighted , real values should be green and predicted values should be of some other color for distinction

River alignments are schematic unless source geometry is marked official.


# Feature Implementation Tracker

This file tracks one actual product/GIS feature at a time so each change can be reviewed and approved before moving to the next.

## Feature 1 - GIS Boundary/Fill Alignment

Status: In progress, awaiting visual approval.

Goal:
Fix the GIS misalignment between the highlighted Pakistan operational area and visible border lines.

Approach used:
- Use `frontend/src/data/pakistan/pakistan_admin1.geojson` as the single authoritative source for the Pakistan operational fill.
- Use the same `pakistan-operational-base` MapLibre source for the visible province/outer boundary line.
- Remove the separate `international_boundary.geojson` border overlay from rendering to avoid two slightly different Pakistan outlines.
- Keep all custom GeoJSON layers in standard longitude/latitude GeoJSON coordinates, which MapLibre renders as WGS84/EPSG:4326.
- De-emphasize Esri satellite reference borders by reducing the reference-label raster opacity, because that raster contains political border lines that can visually conflict with the custom authoritative geometry.
- Do not manually shift, stretch, rotate, or otherwise alter coordinates.

Files changed:
- `frontend/src/components/NationalRiskMap.tsx`

Approval checklist:
- Pakistan fill and custom Pakistan boundary line visually align.
- No second custom Pakistan border competes with the fill.
- Satellite basemap political borders are subdued enough not to look like the app boundary.
- No manual coordinate transformation or offset is introduced.

Next feature candidates after approval:
- Standardize GIS point symbols and clustering.
- Refine river hierarchy and widths.
- Improve district risk color rules.
