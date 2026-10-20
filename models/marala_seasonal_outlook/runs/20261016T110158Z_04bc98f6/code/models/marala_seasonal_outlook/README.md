# Marala 365-day daily mean research outlook

This separate experiment outputs **one modeled-reach daily mean per day** for
365 days and averages those same values by calendar month. Partial first and
last months are flagged. It does not output 06:00 gauge readings, subdaily
values, or calibrated flood probabilities.

The measured-gauge experiment is in `../marala_station_forecast`. Its 322
measurements cannot validate a full annual cycle. This longer-range experiment
instead uses the archived GloFAS modeled river reach at 32.675, 74.425. The
provider's daily values are simulations, **not real measured Marala inflow**.
See https://open-meteo.com/en/docs/flood-api for source semantics and resolution.

From the project root:

```powershell
.venv\Scripts\python.exe -m models.marala_seasonal_outlook.experiment train
.venv\Scripts\python.exe -m models.marala_seasonal_outlook.experiment validate
.venv\Scripts\python.exe -m models.marala_seasonal_outlook.experiment predict
```

Training fits through 2013, selects candidates on 2014-2017, persists selection,
then evaluates frozen candidates on 2018-2021. Validation and test require both
origin and target in their own partition; boundary samples are purged. Month-end
origins generate exact daily leads 1-365. No future target contributes features.
All candidate choices are declared in code. Final models refit on all available
modeled data after evaluation, without a new independent test for that refit.

Baselines are persistence, previous-year seasonal discharge and smooth seasonal
climatology. Learned candidates are ridge and XGBoost corrections to the
previous-year value. The best learned candidate is retained separately if a
baseline wins validation. More jagged output is not a selection criterion.

Each training run preserves the exact raw response, download URL, retrieval
time, response hash, missing-data ledger, every feature/target/split row, source
code, package versions, candidates, selections, held-out predictions and models.
`LATEST_RUN.json` points to an immutable `runs/<id>/RUN_MANIFEST.json` with every
file's SHA-256. `validate` verifies those hashes and replays predictions offline.
For exact historical code, run the copied package from that run's `code` folder
in an environment with the recorded requirements. Keep sealed folders unchanged.

The initial raw download also remains in `data/`; its null 1984-1996 rows are
retained and excluded, never filled. Missing dates cannot become training labels.
An updated source response must be saved under a new filename and its manifest
updated explicitly before training; it must not silently replace a sealed run.

Read `artifacts/REPORT.md` and `model-card.json` for measured test errors and
limitations. Correlated daily targets and retrospective modeled inputs do not
prove real-time gauge or rare-flood skill. Without future rainfall/release
inputs, a year-ahead output is a statistical seasonal outlook. The existing
dashboard feed is not changed by this experiment.
