# Executed 15-to-30-day encoder-decoder experiment

Working directory: `D:/projects/flood_model/flood_model`.

```powershell
$python = 'riverine flood/short range/experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'riverine flood/short range/evaluation comparison/setup_30day_encoder_decoder.py'
& $python 'riverine flood/short range/evaluation comparison/finish_30day_encoder_sources.py'
& $python -m unittest discover -s 'riverine flood/short range/model/model_30_days/Encoder-decoder LSTM/finetuned_15_to_30/tests' -v
& $python -u 'riverine flood/short range/model/model_30_days/Encoder-decoder LSTM/finetuned_15_to_30/train.py'
& $python 'riverine flood/short range/model/model_30_days/Encoder-decoder LSTM/finetuned_15_to_30/verify.py'
```

Nine implementation tests passed. They checked first-15-lead preservation before fine-tuning, trainable new leads, missing-target masking, future discharge exclusion, training-only statistics, validation blending and retention of previous artifacts. Tests do not establish forecast accuracy.

One predeclared ensemble variant was fitted. Seeds 42, 43 and 44 were trained sequentially for 21, 27 and 38 epochs, selecting epochs 9, 15 and 26. Total fitting time was 176.782 seconds. The initial parent was the saved 15-day CAMELS-US model fine-tuned on Marala; its copied weights and input table remain unchanged.

Configuration was fixed before training. Checkpoints were selected using 2021 MSE across leads 21-30. Validation blend weights and quantile offsets were then fixed and hashed before one benchmark evaluation. No test-driven retry or model-family switch was performed after seeing these results.

Observed benchmark: 2022-2024, 1,084 unique target dates, 31,932 issue/lead pairs, 1,055 observations at lead 30. These benchmark years were inspected in earlier project experiments; they are not a fresh independent holdout.

Verification reproduced validation postprocessing and all thirty lead scores, checked the original climatology score, matched every future-weather sequence to the previous best ensemble, retained inherited donor/local training-year lists, and confirmed 160 original files were unchanged. No later model family was trained.
