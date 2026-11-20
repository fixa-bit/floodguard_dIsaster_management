# Investigation result

## Root cause

`/predictive/marala-station-forecast` previously returned the frozen
`latest_predictions.json` produced by the 16 Oct training run. Its last measured
origin was 15 Oct, so its +1/+3/+7 day target timestamps were already in the
past on 19 Nov. The browser's packaged JSON fallback is frozen in the same way.

Training a new model every day is not required to forecast after training. A
trained regressor can infer from newer observations if its input features are
available. The missing step was rerunning inference from current gauge data.

## Implemented approach

The API now reads paired, typed Marala FFD inflow/outflow observations saved by
the existing 15-minute river-monitoring refresh. It uses a fresh 06:00 PKT
reading and requires the previous day's paired reading. A new issue is accepted
only while all forecast targets remain in the future. If the feed is stale, the
pair is incomplete, or no safe origin exists, the API returns the saved snapshot
with `forecast_mode: saved_snapshot`. The UI labels that fallback as
saved/stale. Existing model and holdout metrics are still served from their
sealed artifacts.

For each lead time, the runtime ranks the frozen validation leaderboard by
2025 validation RMSE (MAE breaks ties), refits its top three candidates in
memory on the frozen training snapshot, and caches those fits until the
snapshot or leaderboard changes. It returns each candidate's forecast and
validation errors. The portal shows all three in its table and chart when a
fresh origin is available. The 2026 holdout is not used to select them.

## Verification

- Offline tests use the copies under this folder: 4 passed.
- Live API payload used the stored 19 Nov FFD origin (209.54 m³/s) and emitted
  target times 20, 22, and 26 Nov 2026 at 06:00 PKT.
- The live payload included three distinct candidates for each lead, ordered by
  validation RMSE. Some lower-ranked delta candidates clipped to 0 m³/s for
  this low-flow origin; those outputs are shown as returned.
- Frontend TypeScript check passed with `tsc --noEmit`.
- Existing training/model folders and the repository's existing `tests/` folder
  were left untouched.

## Model limitation

The model card is `research_only_independent_validation_required` and marks the
model ineligible for deployment. In its held-out 2026 evaluation, the selected
candidate was about 0.04% worse than persistence at 1 day, 42.6% worse at 3 days,
and 9.5% better at 7 days by RMSE. The API now produces rolling future outputs;
that does not make these forecasts operationally validated. The 3-day learned
alternative remains visible alongside the preselected champion to avoid
silently choosing a candidate based on the held-out test.
