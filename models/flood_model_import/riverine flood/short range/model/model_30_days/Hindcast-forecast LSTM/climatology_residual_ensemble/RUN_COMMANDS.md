# Executed residual-ensemble experiment

Working directory: `D:/projects/flood_model/flood_model`.

```powershell
$python = 'riverine flood/short range/experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'riverine flood/short range/evaluation comparison/setup_30day_climatology_residual.py'
& $python -m unittest discover -s 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/climatology_residual_ensemble/tests' -v
& $python -u 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/climatology_residual_ensemble/train.py'
& $python 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/climatology_residual_ensemble/verify.py'
```

Nine implementation tests passed. Their synthetic gradient updates check code behavior and do not establish real accuracy.

One predeclared ensemble variant was fitted: seeds 42, 43 and 44, sequentially. The three fits ran 16, 14 and 22 epochs and selected epochs 4, 2 and 10 respectively. Total fitting time was 150.524 seconds. The model configuration was frozen before training; no test-driven retries were performed.

The objective uses scaled mean-flow MSE plus auxiliary quantile pinball loss and residual regularization. The base calendar curve uses a fixed 31-day window and training-only observations, with training anchors cross-fitted by target year. Parent encoder/decoder weights come from the previously saved past-discharge model.

Checkpoints were selected using 2021 mean scaled MSE over leads 21-30. Three predefined validation-only blend coefficients and empirical quantile offsets were then saved and hashed before the benchmark evaluation. The selected coefficients were 1.0 in all three lead groups; the final point forecast therefore equals the raw uniform ensemble mean.

The initial benchmark evaluation used the same 1,084 unique observed dates and 31,932 issue/lead pairs as the earlier experiments, including 1,055 day-30 targets. These 2022-2024 years had been inspected in prior project experiments and are not a new independent holdout. No benchmark values were used to fit this ensemble or its postprocessing.

Verification reproduced the validation blend/offset choices from the saved checkpoints, independently reproduced all 30 lead scores, checked the unchanged original climatology benchmark, confirmed 80 original reference files were unchanged, and confirmed byte-identical source observations. No other model family was trained.
