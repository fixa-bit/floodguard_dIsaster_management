# Executed matched input experiment

Working directory: `D:/projects/flood_model/flood_model`.

```powershell
$python = 'riverine flood/short range/experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'riverine flood/short range/evaluation comparison/setup_30day_past_discharge.py'
& $python -m unittest discover -s 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/past_discharge/tests' -v
& $python -u 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/past_discharge/train.py'
& $python 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/past_discharge/verify.py'
```

Before fitting, `verify_inputs()` was also run directly. It checked every one of the 1,067 test issue windows: weather channels, seeded future-weather noise, targets and masks matched the original weather-only model exactly. Training normalization values were identical.

Nine correctness tests passed, including causal issue-day discharge, missing flow indicators, future discharge exclusion, weather-only feature matching, masked loss, input/source retention and synthetic checkpoint continuation. Synthetic fitting in these tests is not real accuracy evidence.

Exactly one new real-data fitting run is performed, with one seed and one frozen configuration. Its selected checkpoint is evaluated automatically, followed by a matched comparison against the saved weather-only model, persistence and training-only climatology. Training settings and validation selection are unchanged from the original experiment; only past discharge and its missing indicator are added to the inputs.

The 2022-2024 benchmark has been inspected before this experiment. There is no HPO sweep or test-driven retry. All other model families remain pending feedback. Real accuracy values and actual fitting measurements are saved in `reports/initial/evaluation_manifest.json` and `RUN_RESULTS.md`.

Actual fitting: 79.954 seconds, 33 epochs; selected epoch 21. Stop: validation patience reached. Verification confirmed 38 original reference files unchanged, exact source observations, and all saved lead metrics.
