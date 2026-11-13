"""Compare both LSTM variants on identical saved observed targets."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data import load_config, resolve
from evaluate import markdown, metrics, save_json, sha256


def compare(cfg):
    old_path = resolve(cfg, cfg['evaluation']['reference_predictions'])
    new_path = resolve(cfg, cfg['evaluation']['output_dir']) / 'predictions.csv'
    old = pd.read_csv(old_path)
    new = pd.read_csv(new_path)
    keys = ['basin_id', 'issue_date', 'target_date', 'lead_day']
    old = old.rename(columns={'LSTM_30d': 'Weather_only_LSTM',
                              'observed_cumecs': 'old_observed',
                              **{f'q{q}': f'weather_q{q}' for q in cfg['model']['quantiles']}})
    new = new.rename(columns={'LSTM_30d_pastQ': 'Past_discharge_LSTM',
                              **{f'q{q}': f'pastQ_q{q}' for q in cfg['model']['quantiles']}})
    old_columns = keys + ['old_observed', 'Weather_only_LSTM'] + [f'weather_q{q}' for q in cfg['model']['quantiles']]
    joined = new.merge(old[old_columns], on=keys, how='inner', validate='one_to_one')
    if len(joined) != len(old) or len(joined) != len(new):
        raise ValueError('Variants have different observed issue/target/lead records')
    np.testing.assert_array_equal(joined.observed_cumecs, joined.old_observed)
    output = resolve(cfg, cfg['evaluation']['comparison_dir'])
    baseline = pd.read_csv(output / 'matched_predictions.csv')[keys + ['Persistence', 'Climatology']]
    joined = joined.merge(baseline, on=keys, how='inner', validate='one_to_one')
    if len(joined) != len(new):
        raise ValueError('Baseline alignment lost a target')
    manifest = json.loads((resolve(cfg, cfg['evaluation']['output_dir']) / 'evaluation_manifest.json').read_text())
    threshold = manifest['flood_threshold_cumecs']
    results, seasons, calibration = [], [], []
    model_names = ['Weather_only_LSTM', 'Past_discharge_LSTM', 'Persistence', 'Climatology']
    for lead, frame in joined.groupby('lead_day'):
        for name in model_names:
            for label, sub in [('all', frame), ('flood', frame.loc[frame.observed_cumecs > threshold]), ('non_flood', frame.loc[frame.observed_cumecs <= threshold])]:
                results.append({'model': name, 'lead_day': lead, 'group': label,
                                **metrics(sub.observed_cumecs, sub[name], threshold)})
            for label, sub in frame.groupby('season'):
                seasons.append({'model': name, 'lead_day': lead, 'season': label,
                                **metrics(sub.observed_cumecs, sub[name], threshold)})
        for name, prefix in [('Weather_only_LSTM', 'weather'), ('Past_discharge_LSTM', 'pastQ')]:
            inside = (frame.observed_cumecs >= frame[f'{prefix}_q0.05']) & (frame.observed_cumecs <= frame[f'{prefix}_q0.95'])
            calibration.append({'model': name, 'lead_day': lead, 'n': len(frame),
                                'coverage_05_95': float(inside.mean()),
                                'interval_width_cumecs': float((frame[f'{prefix}_q0.95'] - frame[f'{prefix}_q0.05']).mean())})
    results, seasons, calibration = map(pd.DataFrame, (results, seasons, calibration))
    joined.drop(columns='old_observed').to_csv(output / 'variant_matched_predictions.csv', index=False)
    results.to_csv(output / 'variant_scores_flood_nonflood_by_lead.csv', index=False)
    seasons.to_csv(output / 'variant_scores_by_season_and_lead.csv', index=False)
    calibration.to_csv(output / 'variant_quantile_calibration.csv', index=False)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for name, frame in results.loc[results.group.eq('all')].groupby('model'):
        axes[0].plot(frame.lead_day, frame.NSE, label=name)
        axes[1].plot(frame.lead_day, frame.RMSE_cumecs)
    for name, frame in calibration.groupby('model'):
        axes[2].plot(frame.lead_day, frame.coverage_05_95, label=name)
    axes[2].axhline(.9, linestyle='--', color='black', linewidth=1)
    axes[0].set(xlabel='Lead day', ylabel='NSE')
    axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[2].set(xlabel='Lead day', ylabel='P05-P95 coverage', ylim=(0, 1))
    axes[0].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(output / 'variant_skill_by_lead.png', dpi=160)
    plt.close(fig)
    final = results.loc[results.lead_day.eq(30) & results.group.eq('all')].set_index('model')
    flood = results.loc[results.lead_day.eq(30) & results.group.eq('flood')].set_index('model')
    nonflood = results.loc[results.lead_day.eq(30) & results.group.eq('non_flood')].set_index('model')
    widths = calibration.loc[calibration.lead_day.eq(30)].set_index('model')
    summary = {'matched_observed_pairs': len(joined),
               'day30_observations': int(final.loc['Past_discharge_LSTM', 'n']),
               'day30_weather_nse': float(final.loc['Weather_only_LSTM', 'NSE']),
               'day30_pastQ_nse': float(final.loc['Past_discharge_LSTM', 'NSE']),
               'day30_nse_change': float(final.loc['Past_discharge_LSTM', 'NSE'] - final.loc['Weather_only_LSTM', 'NSE']),
               'day30_rmse_reduction_pct': float(100 * (1 - final.loc['Past_discharge_LSTM', 'RMSE_cumecs'] / final.loc['Weather_only_LSTM', 'RMSE_cumecs'])),
               'day30_flood_rmse_reduction_pct': float(100 * (1 - flood.loc['Past_discharge_LSTM', 'RMSE_cumecs'] / flood.loc['Weather_only_LSTM', 'RMSE_cumecs'])),
               'day30_nonflood_rmse_reduction_pct': float(100 * (1 - nonflood.loc['Past_discharge_LSTM', 'RMSE_cumecs'] / nonflood.loc['Weather_only_LSTM', 'RMSE_cumecs'])),
               'day30_weather_coverage': float(widths.loc['Weather_only_LSTM', 'coverage_05_95']),
               'day30_pastQ_coverage': float(widths.loc['Past_discharge_LSTM', 'coverage_05_95']),
               'old_prediction_sha256': sha256(old_path), 'new_prediction_sha256': sha256(new_path),
               'only_past_discharge_inputs_changed': True, 'new_real_training_runs': 1,
               'heldout_years_previously_inspected': True}
    save_json(output / 'variant_comparison_summary.json', summary)
    cols = ['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs', 'PBIAS_pct']
    finding = (f'Day-30 NSE changed from **{summary["day30_weather_nse"]:.3f}** to **{summary["day30_pastQ_nse"]:.3f}** '
               f'({summary["day30_nse_change"]:+.3f}). RMSE reduction: **{summary["day30_rmse_reduction_pct"]:+.1f}%** overall, '
               f'**{summary["day30_flood_rmse_reduction_pct"]:+.1f}%** on high-flow days, and '
               f'**{summary["day30_nonflood_rmse_reduction_pct"]:+.1f}%** on other days. Positive reductions indicate improvement.')
    report = ['# Thirty-day LSTM: adding past observed discharge', '', finding, '',
              'One matched input experiment was run. Hidden size, recurrent layers, dropout, optimizer settings, seed, weather features, weather noise and time splits were held fixed. Adding normalized past flow and its missing indicator increases the input dimension from 18 to 20 and adds 512 input weights. Both models were trained from scratch; this run did not load the weather-only weights.', '',
              f'Train 2016-2020; selection 2021; observed benchmark 2022-2024. All **{len(joined)}** issue/target/lead records align exactly, including **{summary["day30_observations"]}** at day 30. Threshold: training observed Q95 = {threshold:.6f} cumecs.', '',
              f'New model: {manifest["training_seconds"]:.1f} seconds, {manifest["epochs"]} epochs, selected epoch {manifest["selected_epoch"]}; {manifest["stopping_reason"]}. One seed, one configuration, no HPO or test-driven retry.', '',
              '## Matched lead scores', '', markdown(results.loc[results.group.eq('all') & results.lead_day.isin(cfg['evaluation']['report_leads']), cols]), '',
              '## High-flow and other days at day 30', '', markdown(results.loc[results.lead_day.eq(30) & results.group.ne('all'), ['model', 'group', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs']]), '',
              '## Day-30 seasons', '', markdown(seasons.loc[seasons.lead_day.eq(30)]), '',
              '## Day-30 uncertainty coverage', '', markdown(calibration.loc[calibration.lead_day.eq(30)]), '',
              'P05-P95 should contain about 90% of observations. Ordering prevents quantile crossing but does not ensure calibration. No interval recalibration or multiple-seed ensemble was applied in this step.', '',
              '## Scope and interpretation', '',
              'Only observed discharge through the issue day is supplied as an input. Missing historical flow is represented inside samples by the training log-flow mean and a missing indicator. The original target series and all its NaNs are retained unchanged; future discharge never enters a predictor.', '',
              'Weather remains noisy realized ERA5-Land; no archived 30-day forecast inputs were available. Historical availability/latency of the daily discharge readings is not established. Operational 30-day flood forecast skill is unverified.', '',
              'These test years were already inspected before this experiment and serve as a comparison benchmark, not a fresh project-wide holdout. A single-seed comparison cannot establish a reliable general improvement. Settings and checkpoint selection used validation data only, and no other model family was trained.', '',
              '![Variant comparison](variant_skill_by_lead.png)', '']
    (output / 'variant_comparison.md').write_text('\n'.join(report), encoding='utf-8')
    readme = Path(cfg['_root']) / 'README.md'
    if readme.exists():
        text = readme.read_text(encoding='utf-8').split('<!-- MATCHED_COMPARISON -->')[0]
        readme.write_text(text + '<!-- MATCHED_COMPARISON -->\n\n## Matched comparison with weather-only LSTM\n\n' + finding + '\n\n'
                          + markdown(results.loc[results.lead_day.eq(30) & results.group.eq('all'), cols]) + '\n\n'
                          + markdown(calibration.loc[calibration.lead_day.eq(30)]) + '\n', encoding='utf-8')
    print(finding, flush=True)
    print(f'Variant report: {output / "variant_comparison.md"}', flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    compare(load_config(parser.parse_args().config))
