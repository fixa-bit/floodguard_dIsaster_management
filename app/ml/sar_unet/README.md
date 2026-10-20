# Bundled satellite water-extent model

This directory is the self-contained inference bundle used by
`app.services.sar_water_service`. Ship this entire directory with the backend.
No NDMA_tasks checkout, training dataset, or network weight download is needed
to load the model. Runtime dependencies are in the backend requirements.txt.

- `network.py`: architecture snapshot from the selected training run.
- `runs/20261012T035709Z_6f1bb1/best.pt`: validation-selected epoch 7 weights.
- `runs/20261012T035709Z_6f1bb1/dataset_scalers.json`: fitted normalization.
- `runs/20261012T035709Z_6f1bb1/results.json`: recorded evaluation metrics.

Training, raw/prepared data, optimizer checkpoints, and training logs remain in
the separate NDMA_tasks project. This bundle deliberately contains none of them.
`SAR_UNET_MODEL_DIR` optionally overrides this bundle with another directory
using the same layout. `release.json` pins the selected run when present;
directories without it fall back to the newest `runs/*/best.pt`. A selected
run can supply `inference.json` with a validation-selected global threshold.

The existing `/api/v1/flood/water-extent` endpoint accepts during-event VV/VH,
pre-event VV/VH, elevation, slope, and binary permanent water GeoTIFFs, aligns
and normalizes them, and returns a georeferenced PNG water overlay. The
`/location` endpoint additionally depends on external imagery providers.

The model predicts all water. The default API overlay now subtracts the aligned
binary permanent-water reference and is labeled potential flooding. It is not
confirmed new flooding: seasonal water and reference gaps can remain, and a
verified pre-event water map is still needed to establish new inundation.
Unknown input/reference pixels remain excluded. `water_pixels` / `water_percent`
retain total-water statistics; `potential_flood_pixels` / `potential_flood_percent`
describe the displayed filtered overlay. `excluded_permanent_water_pixels`
reports the removed predictions; `all_water_image_data_url` retains the original
all-water overlay. This filtering does not retrain or alter model weights.

Response version 2 also reports approximate areas in km² using pixel corners
transformed to an equal-area CRS, usable-image coverage, and a detection status.
The map outlines the analysed footprint even when the flood overlay is empty.
The frontend rejects older responses instead of rendering missing measurements.

The map defaults to a suggested historical example: Pakistan, 28 June 2017,
Sen1Floods11 test chip `Pakistan_849790`. Click **View flood example** to load
`frontend/public/examples/sar-pakistan.json` and frame its footprint. This is a
recorded prediction from the bundled model, chosen to illustrate a visible
overlay, not a benchmark or current flood report. The JSON includes checkpoint
and input hashes. Raw GeoTIFFs and training data remain in NDMA_tasks; only
derived display images and evaluation summaries are packaged with the example.
Regenerate it from NDMA_tasks using `export_flood_example.py --app-directory
<disaster_management-directory>` with the app's Python environment. Select
**Recent imagery · choose on map** for the existing live imagery workflow.

Historical results provide **Compare imagery, labels & accuracy**, with aligned
event VV radar, all-water prediction, hand-labeled reference water, a confusion
overlay (cyan correct water, pink missed water, orange false detections, gray
excluded pixels), and a separately labeled blue permanent-water reference.
All panels share the same event radar and grid; no contemporary basemap enters
the comparison. The map also offers these display layers and defaults to the
event-date radar background inside the analysed box.

The second example, `Pakistan_70625`, includes nonzero permanent-water reference.
Generate it using `--sample-id Pakistan_70625 --output-name
sar-pakistan-permanent.json`. The original example has an empty permanent-water
reference, explicitly reported as incomplete evidence rather than proof that
the river is temporary. Reference labels include permanent water; the separate
outside-permanent metrics describe a proxy and cannot establish newly flooded
ground truth. Baseline/current metrics use identical supervised pixels.

Recorded metrics measure all-water prediction before this filtering. Test IoU
is 65.36% and Dice 79.05%; Pakistan test IoU is 13.47%. Event-sharing splits do
not establish performance on unseen events. Permanent-water source timing also
needs verification before operational use. Packaging does not improve accuracy.

On 16 October 2026, two accuracy experiments were completed in NDMA_tasks.
Event-balanced fine-tuning improved validation IoU to 63.75% but Pakistan test
IoU remained 13.44%; the radar-change ensemble reached 66.09% pooled test IoU
but only 9.82% on Pakistan. Both were rejected by the regional release check.
`release.json` therefore pins the original checkpoint, and its model card
records both rejected experiments. No accuracy gain in Pakistan is claimed.
The validation dialog shows these scores alongside the active baseline.
