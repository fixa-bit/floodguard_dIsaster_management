# Improving on the HBV baseline

The completed 2021-2024 monsoon experiment already improves on HBV alone at all ten
leads for KGE, MAE and flood-day MAE. Means of the ten lead-specific scores:

| Model | KGE | MAE m3/s | Flood-day MAE m3/s |
|---|---:|---:|---:|
| HBV | 0.522 | 507.9 | 936.7 |
| HBV + LightGBM residual | 0.722 | 336.3 | 576.7 |
| HBV + encoder-decoder LSTM residual | 0.764 | 315.7 | 519.7 |

These are reanalysis-driven hindcasts. The gains do not establish operational
forecast skill. LSTM flood-day MAE is about 44.5% lower than HBV; LightGBM is about
38.4% lower. Persistence still wins local event peak magnitude, and interval
coverage is about 62-63% instead of the nominal 80%. Improvements should address
those specific weaknesses, rather than optimize another score on the same tests.

1. **Tune correction strength by lead on validation seasons.** Use
   `Q = max(0, Q_HBV + alpha_lead * residual)` with alpha chosen on validation
   years only; include alpha=0 as the HBV fallback. Select the strength against
   a stated objective such as KGE with a flood-MAE constraint. This can prevent
   unnecessary residual corrections during stable flow. It protects validation
   performance relative to HBV, but cannot guarantee gains on future seasons.

2. **Use the available elevation-band forcing to improve snow physics.** The
   workspace already contains four-band ERA5-Land forcing and area fractions in
   `../spatially_distributed_model/data/raw/era5land_elevation_bands_v2/`.
   Give each band its own snow/soil inventories, area-weight runoff, and share
   selected response parameters to limit overfitting. Recheck the start/warm-up
   period: those band files start in 2015. Glacier ice melt and regulation may
   still need separate treatment. Compare the physical change with a matched
   lumped control using exactly the same train/validation/test issues.

3. **Improve flood peaks using training events.** Increase the influence of
   observed training floods through an auxiliary peak/median-error objective,
   or fit a separate high-flow residual expert with a gate based only on
   issue-time rainfall forecasts, HBV states and recent observed flow.
   Evaluate magnitude and timing together. Keep probabilistic losses and check
   interval calibration: weighting high targets can change predicted quantiles.
   Do not identify the operational flood regime using future observed discharge.

4. **Fit a lead-dependent combination of the two hybrid alternatives.** LightGBM
   is stronger at lead 1 in this run, whereas LSTM is stronger at lead 10.
   Estimate nonnegative blending weights or select the alternative using
   validation seasons only. Test extra LSTM seeds for stability before increasing
   network size; there are only about nine observed years.

5. **Add real archived weather forecasts and honest ensemble uncertainty.**
   Train lead-specific weather corrections and residual models using forecasts
   that were available at each historical issue. Real forecasts may reduce the
   reported scores relative to perfect-weather hindcasts; this gives a credible
   estimate of operational skill. Use genuine ensemble members, not independent
   arbitrary rainfall noise presented as a provider ensemble. The existing
   archive interface and inference command propagate each member separately.

6. **Calibrate uncertainty separately from model selection.** Use a past
   calibration season or chronological cross-fitting to adjust residual interval
   widths by lead. Check P10/P90 coverage and Brier/reliability at the thresholds.
   Do not widen intervals by inspecting the 2021-2024 test errors and then claim
   those same seasons independently validate the change. Temporal dependence
   also limits naive independent-sample coverage guarantees.

Resolve discharge reading times, forecast publication latency and the distinction
between MODIS NDSI and fractional snow-covered area. Obtain official flood
thresholds and archived issued GloFAS forecasts for the requested operational
comparisons. Freeze this run as the existing benchmark and reserve new seasons
or a genuinely uninspected external period for confirmation.

These are proposed follow-up experiments; they have not been trained or claimed
to improve the completed run. See the actual [results](runs/2026-10-30/REPORT.md)
and [verification](runs/2026-10-30/verification/verification.json).
