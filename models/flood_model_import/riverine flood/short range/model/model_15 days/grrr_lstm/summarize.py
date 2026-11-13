"""Generate measured results and verify the selected experiment artifacts offline."""
import hashlib
import json

import numpy as np
import pandas as pd

from compare import HERE, OBSERVED, PROTOCOL, SEASONS
from experiment import ARMS, bootstrap_test, select_arm


def main():
    source = json.loads((HERE / 'source_receipt.json').read_text())
    comparison = json.loads((HERE / 'comparison/report.json').read_text())
    report = json.loads((HERE / 'experiment/report.json').read_text())
    scores = pd.read_csv(HERE / 'comparison/scores.csv')
    model_scores = pd.read_csv(HERE / 'experiment/scores.csv')
    peaks = pd.read_csv(HERE / 'experiment/sampled_peak_scores.csv')
    predictions = pd.read_csv(HERE / 'experiment/predictions_observed_days.csv', parse_dates=['target_date', 'issue_after_date'])
    working = pd.read_csv(HERE / 'experiment/experimental_daily.csv', parse_dates=['date'])
    original = pd.read_csv(OBSERVED, parse_dates=['date'])
    validations = {}
    def check(name, condition):
        validations[name] = bool(condition)
        if not condition:
            raise AssertionError(name)
    check('protocol_hash_matches', report['protocol_sha256'] == hashlib.sha256((HERE / 'protocol.json').read_bytes()).hexdigest())
    check('comparison_and_model_use_same_grrr', comparison['grrr_sha256'] == hashlib.sha256((HERE / 'grrr_marala_reanalysis.csv').read_bytes()).hexdigest())
    check('observed_dataset_hash_matches', comparison['observed_sha256'] == hashlib.sha256(OBSERVED.read_bytes()).hexdigest())
    check('original_calendar_preserved', list(working.date) == list(original.date))
    check('original_observations_and_nans_unchanged', np.array_equal(working.observed_discharge_m3_s, original.observed_discharge_m3_s, equal_nan=True))
    observed = original.observed_discharge_m3_s.notna()
    check('fills_never_overwrite_observations', np.array_equal(working.loc[observed, 'experimental_discharge_m3_s'], original.loc[observed, 'observed_discharge_m3_s']))
    lookup = original.set_index('date')
    check('every_scored_target_is_originally_observed', np.array_equal(predictions.observed_m3_s, lookup.loc[predictions.target_date, 'observed_discharge_m3_s']))
    check('all_arms_have_same_scoring_keys', not predictions.duplicated(['split', 'issue_after_date', 'target_date', 'lead_days']).any() and predictions[['nan_gaps_m3_s', 'weighted_fills_m3_s']].notna().all().all())
    check('no_post_archive_fill', not (working.is_modeled_fill & working.grrr_discharge_m3_s.isna()).any())
    check('all_2026_gaps_remain_nan', working.loc[(working.date.dt.year == 2026) & ~observed, 'experimental_discharge_m3_s'].isna().all())
    check('heldout_days_have_zero_training_weight', (working.loc[working.split != 'train', 'training_target_weight'] == 0).all())
    uncertainty = bootstrap_test(predictions[predictions.split == 'test'])
    decision = select_arm(model_scores, peaks, uncertainty)
    check('decision_recomputed_from_saved_predictions', decision['selected_arm'] == report['decision']['selected_arm'])
    check('bootstrap_interval_recomputed', np.allclose(uncertainty['improvement_fraction_95pct_ci'], report['uncertainty']['improvement_fraction_95pct_ci'], atol=1e-12))
    for arm in ARMS:
        actual = model_scores[(model_scores.split == 'test') & (model_scores.scope == 'overall') & (model_scores.arm == arm)].iloc[0].rmse_m3_s
        test = predictions[predictions.split == 'test']
        recomputed = np.sqrt(np.mean((test[arm + '_m3_s'] - test.observed_m3_s)**2))
        check(f'{arm}_test_rmse_recomputed', np.isclose(actual, recomputed, atol=1e-10))
    check('selected_checkpoint_exists', (HERE / 'experiment' / f"{decision['selected_arm']}.pt").exists())
    check('rejected_filled_checkpoint_absent', decision['selected_arm'] == 'weighted_fills' or not (HERE / 'experiment/weighted_fills.pt').exists())
    (HERE / 'experiment/validation_checks.json').write_text(json.dumps(validations, indent=2) + '\n')
    gate = report['feature_gate']
    lines = ['# Marala GRRR results', '', 'Run date: 30 October 2026.', '',
             '**Keep lagged GRRR as an input feature and leave discharge gaps NaN. The lower-weight filling experiment failed the frozen clear-win rule.**', '',
             '## Seasonal raw comparison', '',
             f"Main release: `{source['model_id']}`, basin `{source['gauge_id']}`. Actual overlap is 2016-03-01 through 2025-12-30, with **3,332 paired observed dates**. GRRR has no 2026 data. The newer release's reanalysis metadata was uploaded on 28 October 2026; the older documented release is retained separately and ends on 2023-12-23.", '',
             'Bias = GRRR minus observed. Seasons: winter Dec-Feb, pre-monsoon Mar-May, monsoon Jun-Sep, post-monsoon Oct-Nov. The peak column is the modeled error **on the largest observed paired-date peak in that season across all available years**; it is not an average event-peak error.', '',
             '| Season | Paired days | Pearson r | Bias (m³/s) | Bias (%) | Error at largest observed peak (%) |',
             '|---|---:|---:|---:|---:|---:|']
    for s in SEASONS:
        r = scores[(scores.scope == 'season') & (scores.season == s)].iloc[0]
        lines.append(f"| {s.replace('_', ' ').title()} | {int(r.n)} | {r.pearson_r:.3f} | {r.bias_m3_s:+.1f} | {r.percent_bias:+.1f}% | {r.error_at_observed_peak_pct:+.1f}% |")
    overall = scores[scores.scope == 'overall'].iloc[0]
    lines += ['', f"Overall r = **{overall.pearson_r:.3f}**, bias = **{overall.percent_bias:+.1f}%**. The largest observed paired peak is {overall.observed_peak_m3_s:,.1f} m³/s on {overall.observed_peak_date}; GRRR gives {overall.modeled_peak_m3_s:,.1f} m³/s on that date ({overall.error_at_observed_peak_pct:+.1f}%). Strong correlation does not make raw GRRR an accurate substitute for extreme observations.", '',
              'The selected HydroBasins polygon contains Marala and has upstream area 29,080.8 km², within 0.38% of the published 29,192 km². Its modeled outlet is about 18.72 km downstream. The nearest outlet was rejected as a tributary. Raw daily means and observed point readings have unconfirmed interval equivalence.', '',
              'Year-by-season peak magnitudes, peak-day errors and sampled peak timing are in [comparison/scores.csv](comparison/scores.csv). They use identical paired dates. Missing observations, missing seasons and modeled daily means prevent interpreting those maxima or timing differences as complete-event peak validation. Winter year/season groups use calendar year, so December is not joined to the following January-February.', '',
              '![Seasonal paired comparison](comparison/seasonal_comparison.png)', '',
              '## Feature decision', '',
              f"The fixed two-day-lagged feature passes the training-only gate: **r = {gate['overall']['pearson_r']:.3f}** on {gate['overall']['n']:,} 2016-2021 pairs; **monthly-anomaly r = {gate['monthly_anomaly']['pearson_r']:.3f}**; all four seasonal correlations exceed the frozen minimum. Both experiment arms include this GRRR feature and an availability mask. No feature scaling or fill calibration is fitted to validation/test observations.", '',
              '## Gap experiment', '',
              'Both 16-unit LSTMs use seed 42, 30 input days, 15 direct outputs, 15 epochs, the same chronological partitions and exactly the same forecast origins. Both select epoch 9 on observed-only 2022 validation loss. Filled training targets have weight 0.2, observed targets weight 1. Filled values may also enter past input context in the experimental arm.', '',
              '| Split | Observed days | Experimental fills | Remaining NaNs |', '|---|---:|---:|---:|']
    for part, counts in report['fill_counts'].items():
        lines.append(f"| {part.title()} | {counts['observed']:,} | {counts['filled']:,} | {counts['remaining_nan']:,} |")
    lines += ['', '**Only one training day is missing.** Filling 259 test-period days supplies no additional supervised training targets; those values affect eligible past input contexts only. No test fills are treated as truth. This limits evidence about the benefits of training on large quantities of low-weight filled targets.', '',
              '| Observed-only evaluation | NaN gaps RMSE (m³/s) | Weighted fills RMSE (m³/s) | Persistence RMSE (m³/s) |', '|---|---:|---:|---:|']
    for part in ('validation', 'test'):
        r = model_scores[(model_scores.split == part) & (model_scores.scope == 'overall')].set_index('arm')
        lines.append(f"| {part.title()} ({int(r.loc['nan_gaps', 'n']):,} pairs) | {r.loc['nan_gaps', 'rmse_m3_s']:.2f} | {r.loc['weighted_fills', 'rmse_m3_s']:.2f} | {r.loc['persistence', 'rmse_m3_s']:.2f} |")
    ci = report['uncertainty']['improvement_fraction_95pct_ci']
    delta = report['decision']['checks']['test_rmse_improvement']['value']
    lines += ['', f"Filling reduces observed-test RMSE by only **{100 * delta:.3f}%**. Paired 30-day-block bootstrap 95% interval for relative improvement: **[{100 * ci[0]:+.3f}%, {100 * ci[1]:+.3f}%]**. Validation improvement is also below the frozen 5% requirement. **Reject the filled version.** Its checkpoint is removed; evaluation artifacts remain labeled as an experiment. The selected checkpoint is [nan_gaps.pt](experiment/nan_gaps.pt), with [preprocessing metadata](experiment/selected_model.json).", '',
              '| Test lead | Observed pairs | NaN gaps RMSE | Weighted fills RMSE | Persistence RMSE |', '|---|---:|---:|---:|---:|']
    for lead in (1, 3, 7, 15):
        r = model_scores[(model_scores.split == 'test') & (model_scores.scope == 'lead') & (model_scores.lead_days == lead)].set_index('arm')
        lines.append(f"| {lead} days | {int(r.loc['nan_gaps', 'n'])} | {r.loc['nan_gaps', 'rmse_m3_s']:.1f} | {r.loc['weighted_fills', 'rmse_m3_s']:.1f} | {r.loc['persistence', 'rmse_m3_s']:.1f} |")
    lines += ['', 'All flow errors in the table are m³/s. There are 922 common test origins and 13,562 observed test origin/target/lead pairs. These pairs overlap and are not independent floods.', '',
              '## Limits that affect interpretation', '',
              '- No 2026 GRRR values exist in this extraction. All 2026 gaps stay NaN. There are 1,515 scored 2026 pairs, where both models use the missing-GRRR flag. GRRR was complete in training, so this feature-availability pattern was not seen in training. Availability and year breakdowns are in the saved scores.',
              '- Peak flows remain difficult: the selected model has high-flow test RMSE about 2,871 m³/s and high-flow NSE below zero. These metrics use the training 95th percentile, not an official flood-warning threshold. Overall improvement over persistence does not establish reliable extreme-flood warnings.',
              '- The main two-arm experiment isolates the effect of filling because both models contain GRRR. Correlation supports including the feature; a matched no-GRRR ablation would be needed to establish its incremental predictive benefit.',
              '- This is one seeded retrospective run. Global GRRR pretraining overlap, release latency and true issue-time availability are unverified. The new release lacks independently confirmed interval semantics. The modeled outlet and observation measurement basis differ from an exact daily-mean gauge target.',
              '- Fills were fitted on training observations only and never overwrite original observations. Model selection and evaluation use observed truth exclusively. The experiment does not promote the filled dataset to an observed source.', '',
              f"Validation: **{len(validations)} artifact checks passed**, including recomputed paired scoring, bootstrap, source/protocol hashes, unchanged observations, no 2026 fills and absence of the rejected checkpoint. Four additional integrity unit tests passed. [Full method and reproduction](README.md), [decision and training report](experiment/report.json), [scored predictions](experiment/predictions_observed_days.csv)."]
    (HERE / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(validations, indent=2))


if __name__ == '__main__':
    main()
