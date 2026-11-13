# Calibrated HBV + residual correction

This module implements and trains a separate physical/residual pipeline for Marala.
Existing model folders and source observations remain untouched. Models, physical
states, weather corrections, forecasts, metrics and provenance have separate folders.

The actual run is [runs/2026-10-30/REPORT.md](runs/2026-10-30/REPORT.md).
The run manifest records completion status; a report is written only after training
and evaluation finish.

See [IMPROVEMENTS.md](IMPROVEMENTS.md) for measured gains over HBV and prioritized
follow-up experiments. These proposals are separate from the completed training.

## Train and verify

From the parent `model` directory, using the existing experiment environment:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
& $python -m pip install -r hbv_residual/requirements.txt
& $python -m unittest discover -s hbv_residual/tests -v
& $python -u -m hbv_residual.train --config hbv_residual/config.json
& $python -m hbv_residual.verify --run hbv_residual/runs/2026-10-30
```

Set a new `output_dir` for another run. `--resume` reuses completed folds and checks
that configuration and source hashes have not changed. An incomplete fold is fitted
again. Existing complete runs are not overwritten by the default command.

## Physical core

`physical.py` implements daily temperature-index snowfall/melt/refreezing with
liquid retention, HBV soil capacity/nonlinear recharge and moisture-limited PET,
upper/lower response reservoirs with threshold quickflow and percolation, and
a conservative linear routing reservoir. Differential evolution calibrates 14
bounded parameters on KGE (2009). The optimizer budget and convergence status are
saved; hitting the budget is not reported as convergence.

The complete water inventory is snow ice + snow liquid + soil + upper response +
lower response + routing. Snowfall correction is included in effective
precipitation. The daily mass-balance identity is audited to numerical tolerance.
Runoff mm/day converts to m³/s using the saved catchment area divided by 86.4.
The first 730 days from January 2014 are warm-up and never calibration targets.

Historical physics uses CHIRPS precipitation, ERA5-Land temperature and PET. Every
forecast issue/member branches from the causal issue-day state using forecast
rain and temperature and training-only calendar PET climatology. Realized future
PET and snow states do not enter the branch. Daily states, melt and all fluxes are
saved separately from forecast trajectories.

MOD10A1 exports currently available cover 2000-2019; their `snow_cover_pct` field
is actually a basin-mean NDSI index. It must not be interpreted as fractional
snow-covered area. Historical NDSI features require >=50% valid coverage, assume
two days of latency, and carry a valid reading forward for at most seven days.
Snowpack versus clear-day NDSI rank correlations are diagnostics, not independent
SWE or snow-area validation. Actual observed snow fraction is unavailable. The
separate `modeled_snow_fraction` feature uses an assumed 50-mm HBV depletion curve.
The lumped implementation does not resolve elevation bands or glacier ice melt.

## Residual models

Thirty LightGBM models use quantile loss: one model for each of leads 1-10 and
quantiles 0.1, 0.5, 0.9. Each learns observed discharge minus that issue's branched
HBV forecast. Independently fitted quantiles are sorted before adding HBV and
clipping negative final discharge to zero. Saved native text models can be loaded
without retraining. Training writes feature names, gains and best iteration counts.

The alternative PyTorch encoder-decoder LSTM has 60 days of historical features
and a ten-day forecast decoder initialized from encoder hidden/cell states.
It predicts ordered residual quantiles using a center and positive interval widths.
Residual scaling, historical/future feature normalization and missing indicators
are fitted on training samples only. Observed target NaNs stay missing in loss and
verification. No nearby-station regression or simulated discharge becomes a target.

Both models use HBV flow/stores/melt, observed flow and residual lags through issue
day (0,1,2,3,7,14,30), rainfall/temperature history, historical summaries, forecast
weather and cumulative rain, forecast HBV states, cyclic day of year, delayed MODIS
index/coverage, and modeled snow fraction. Minibatch shuffling follows chronological
split assignment. Feature means replace missing model predictors with explicit
missing flags; LightGBM handles missing predictors natively. Persistence uses the
latest observed discharge no more than seven days old, with age in the AI inputs.

## Weather and uncertainty

No archived weather forecasts or genuine meteorological ensemble are available in
the current run. Future ERA5-Land rainfall/temperature are a realized-weather proxy:
the resulting hindcast skill does not establish real operational 10-day skill.
Monthly empirical quantile mapping fits ERA5 rain against CHIRPS on training dates
only. It preserves exact dry zeros and uses additive extrapolation beyond the upper
training tail. Temperature maps to itself because no independent thermometer
reference exists; that identity mapping is explicitly reported.

For an archived forecast experiment set `forecast_file` in the JSON config to a CSV
with these columns (all timestamps use UTC):

```text
issue_date,valid_date,lead_day,member,available_at,precipitation_mm,temperature_c
2020-06-01,2020-06-02,1,member_00,2020-06-01T12:00:00Z,5.0,12.0
```

Supply all ten lead rows for each issue/member. Issue t means end of day t UTC;
target dates are t+1,...,t+10. The loader rejects late publication, inconsistent
valid dates, duplicate rows, invalid weather and incomplete trajectories.
Archived training fits separate maps for each lead/calendar month against CHIRPS
rain and ERA5 temperature, using training target dates only (>=30 pairs required).
No retrospective forecast reconstruction is disguised as an archive.

HBV and AI run separately for every member. Equal-member mixtures use a
piecewise-linear inverse CDF across conditional P10/P50/P90, with constant tails.
Mixture quantiles invert the analytic mixture CDF and exceedance probabilities
evaluate that CDF directly, including probability masses at the tails. The assumed
conditional distribution cannot resolve unmodeled extreme tails. There is no claim of parameter uncertainty or
cross-lead trajectory/event probability. With one reanalysis member, intervals
represent conditional residual uncertainty only. P10/P50/P90 calibration is reported.

## Rolling monsoon evaluation

The expanding folds test June-September 2021, 2022, 2023 and 2024. In each fold:

1. Calibrate physics and weather mapping on 2016 through test_year-2.
2. Fit residual models on those same complete years; select stopping on the following complete year.
3. Evaluate the next monsoon. Every ten-day target window stays inside its own partition/season.

Scores include KGE, NSE, MAE, flood-only scores, event peak magnitude and timing
errors per lead; POD, FAR, CSI and Brier for each threshold. Event clusters are
observed exceedances separated by >7 days, with +/-5-day peak comparison windows.
Prediction dates give timing offsets in days. No-event and no-alarm undefined ratios
remain missing. CSVs preserve event counts and signed errors for interpretation.

Persistence and HBV use the same issues and observations. GloFAS is reported
unavailable; its discharge must never be substituted for observed targets. No
official flood thresholds were supplied: the run uses training Q90/Q95/Q99, and
flood/event errors use training Q95. Configure `thresholds_cumecs` to add named
official thresholds. The report explicitly counts leads where hybrids improve
each baseline. Four seasons with overlapping windows do not establish significance.

After held-out scoring, `final/` refits on all eligible 2016-2024 observations.
LightGBM round counts and LSTM epochs are fixed from the last fold; no held-out
accuracy is claimed for the final refit. Its example is a historical replay.

## Reload and predict a supplied ensemble

Supply a historical daily table with observed CHIRPS rain, temperature, PET and
optional observed discharge through issue day, and a forecast CSV using the schema
above. Include the original warm-up start so model states can be recomputed.

```powershell
& $python -m hbv_residual.predict `
  --run hbv_residual/runs/2026-10-30 `
  --history path/to/daily_history.csv `
  --forecast path/to/issued_ensemble.csv `
  --issue-date 2026-10-30 `
  --output hbv_residual/forecasts/2026-10-30
```

This writes member HBV states, member corrected quantiles, mixture hydrographs,
threshold probabilities and a manifest. Reanalysis-trained models retain an explicit
train/operations mismatch warning; running on real forecasts does not remove it.
Future targets are never required. Historical replay is identified in the manifest.

## References

- [Seibert & Vis (2012), HBV-light routines](https://hess.copernicus.org/articles/16/3315/2012/).
- [NSIDC explanation of NDSI versus fractional snow cover](https://nsidc.org/data/user-resources/help-center/what-ndsi-snow-cover-and-how-does-it-compare-fsc).
- [LightGBM objective and quantile parameters](https://lightgbm.readthedocs.io/en/stable/Parameters.html).
