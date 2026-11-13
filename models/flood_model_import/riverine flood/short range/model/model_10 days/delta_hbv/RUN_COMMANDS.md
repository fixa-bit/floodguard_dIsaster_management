# Executed run, 2026-11-02 (Asia/Karachi)

Working directory: `D:/projects/flood_model/flood_model`.

```powershell
$python = 'riverine flood/short range/experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'riverine flood/short range/model/delta_hbv/setup_sources.py'
& $python 'riverine flood/short range/model/delta_hbv/prepare.py'
& $python -m unittest discover -s 'riverine flood/short range/model/delta_hbv/tests' -v
& $python -u 'riverine flood/short range/model/delta_hbv/train.py'
& $python 'riverine flood/short range/model/delta_hbv/verify.py'
& $python 'riverine flood/short range/evaluation comparison/compare_flood_nonflood.py' --output 'riverine flood/short range/evaluation comparison/flood_nonflood_with_delta_hbv'
```

The final correctness-test run passed all five tests. The alignment test was corrected during development to preserve target availability when perturbing observed values; changing availability changes which issue windows exist and therefore the inherited index-seeded weather noise.

Exactly one real-data fitting run was executed: seed 42, 40 epochs, 88.464 seconds. It used 589 training issues per epoch from 1,767 eligible issues, and 356 validation issues. The selected checkpoint was epoch 40. Training reached the fixed epoch cap with validation loss still improving; convergence was not established. No further fitting or tuning was done after test results were inspected.

Training automatically ran evaluation once. All 1,084 unique observed 2022-2024 target dates were represented, with 10,795 observed issue/lead pairs. Lead 10 used 1,075 observations: 51 above training Q95 and 1,024 at or below it.

The saved-result verification independently reproduced the metrics, checked checkpoint predictions, matched forecast weather against the existing LSTM, checked unmodified upstream physics sources, and confirmed the source data SHA256 stayed unchanged.

Implementation tests and checkpoint verification do not establish real-world forecast accuracy. Scores in `RUN_RESULTS.md` come from observed test targets.
