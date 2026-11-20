# Marala forward-forecast investigation

This isolated folder contains copied model artifacts, the frozen training
observation snapshot, its validation leaderboard, and a read-only export of
recent typed Marala gauge readings. The original model/data directories and
existing `tests/` folder are not used as test output locations.

Run the offline forward-origin checks from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest "forecast testing/test_forward_forecast.py"
```

The tests verify that a fresh FFD origin after model training produces future
1-, 3-, and 7-day target timestamps, with five distinct candidates ranked by
the frozen validation RMSE; stale origins and missing previous-day
measurements are rejected. The five candidates are refit in memory from the
copied observations and cached until the dataset or leaderboard changes. They
do not claim forecast skill. The trained model remains research-only, and
measured forecast accuracy must continue to be assessed with the sealed 2026
holdout or later independent observations.

`test_riverine_extended_forecast.py` checks the live GloFAS response adapter
with a mocked provider payload. The portal uses its daily median and P25–P75
range for a 30-day graph. The yearly view displays the repository's existing
2026–2040 CMIP6 scenario summary, clearly labeled as a climate projection, not
a forecast for the next 365 days.
