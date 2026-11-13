# Shared N-HiTS / N-BEATSx experiment

`../nhits/` and `../nbeatsx/` hold each model's config, exact data copy, entry points, tests, trained weights and measured results. This directory holds the common data adapter, pinned published computational blocks, masked training runner and comparison evaluator. The matched-input LSTM belongs to `../nhits/controls/lstm/`.

Source: [Nixtla NeuralForecast](https://github.com/Nixtla/neuralforecast), revision in `source_reference/provenance.json`. Original source files and Apache-2.0 license are retained. `blocks.py` extracts the published block/basis classes without their Lightning training framework. Project adaptations supply the existing NaN-masked data windows, training-only normalization, missing indicators, AdamW, smaller widths and sorted quantile projection. The published internal pooling, bases and residual/backcast operations are retained.

Commands actually used, from the parent `model` directory:

```powershell
$py = '../experiments/marala_observed/.venv/Scripts/python.exe'
& $py -m unittest discover -s nhits/tests -v
& $py -m unittest discover -s nbeatsx/tests -v
& $py -u -m time_series_mlp.run_all
& $py -u -m time_series_mlp.evaluate
& $py compare_flood_nonflood.py --output reports/flood_nonflood_2026-11-02_with_nhits_nbeatsx
```

Training runs sequentially on CPU and its stdout/stderr are in `training.log` and `training_errors.log`. `training_status.json` records completion/checkpoint paths. The frozen plan in `experiment_protocol.json` predates training and records source/config hashes, year splits and seed. New output directories are required before retraining.

Both new models and the matched LSTM read 365 historical days, including observed past discharge, and output ten future days. This differs from the earlier weather-only LSTM. Full future weather tensors were checked against the original experiment; target dates and raw discharge also match. Past-only extra ERA5 covariates provide the historical portion of N-HiTS/N-BEATSx future-covariate channels. No future discharge enters the predictors.

All 16 synthetic correctness checks passed. They do not establish forecast accuracy. These are single-seed experiments with no HPO sweep. The actual test results and measured training times are in `reports/initial/comparison_report.md`, each model's README and `RUN_RESULTS.md`. Flood and non-flood rankings remain descriptive results on previously inspected years, not new blind model selection.
