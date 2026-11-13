# Executed first 30-day experiment

Working directory: `D:/projects/flood_model/flood_model`.

```powershell
$python = 'riverine flood/short range/experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'riverine flood/short range/evaluation comparison/setup_30_day_models.py'
& $python -m unittest discover -s 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/scratch/tests' -v
& $python -u 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/scratch/train.py'
& $python 'riverine flood/short range/model/model_30_days/Hindcast-forecast LSTM/scratch/verify.py'
```

The six correctness tests passed. Their tiny synthetic training/fine-tuning steps check code behavior and do not measure real accuracy.

Exactly one real-data model was fitted: the weather-only scratch hindcast-forecast LSTM with 30 output leads. The configuration was frozen before fitting. Seed 42, 34 epochs, selected epoch 22, validation-patience stopping, 80.9046 seconds of training, 42,037 parameters, 1,767 training windows and 336 validation windows. There was no HPO sweep or test-driven retry.

Evaluation ran automatically once after fitting. It used only observed 2022-2024 targets: 1,084 unique observed dates across leads, 31,932 observed issue/lead pairs, and 1,055 observations at lead 30. The remaining model families were not trained. Work stops for feedback.

Verification reproduced all saved lead metrics, checked source byte identity and exact observed targets, loaded the checkpoint, checked all 30 output leads and ordered quantiles, confirmed chronological separation, and checked that other family folders have no trained checkpoint.

Results use noisy realized reanalysis as a forecast proxy. Operational 30-day flood forecast accuracy was not established.
