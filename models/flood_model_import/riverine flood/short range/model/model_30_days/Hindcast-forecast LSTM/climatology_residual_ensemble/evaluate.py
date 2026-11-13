"""One observed benchmark evaluation after validation choices are frozen."""
import argparse
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from data import DataStore, ResidualDataset, load_config, resolve, years
from metrics import markdown, metrics, save_json, sha
from model import ResidualLSTM
from postprocess import apply_postprocessing
from train import predict, seed_everything


def season(date):
    return 'Oct-Mar' if date.month in (10, 11, 12, 1, 2, 3) else 'Apr-Jun' if date.month in (4, 5, 6) else 'Jul-Sep'


def evaluate(cfg):
    seed_everything(42, cfg['training']['cpu_threads'])
    run = resolve(cfg, cfg['training']['output_dir'])
    selection = json.loads((run / 'selection_complete.json').read_text())
    if not selection['selection_complete_before_test'] or selection['postprocessing_sha256'] != sha(run / 'validation_postprocessing.json'):
        raise ValueError('Validation selection must be fixed before test evaluation')
    if selection['config_sha256'] != sha(Path(cfg['_root']) / 'config.yaml'):
        raise ValueError('Configuration changed after selection')
    post = json.loads((run / 'validation_postprocessing.json').read_text())
    paths = json.loads((run / 'ensemble.json').read_text())['checkpoints']
    store = DataStore(cfg)
    predictions = []
    checkpoints = []
    for path in paths:
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
        if set(checkpoint['training_years'] + checkpoint['selection_years']) & set(years(cfg['splits']['test'])):
            raise ValueError('Benchmark year used in model fitting or selection')
        if checkpoint['source_sha256'] != sha(resolve(cfg, cfg['data']['daily_file'])):
            raise ValueError('Input table changed')
        dataset = ResidualDataset(store, 'test', checkpoint['statistics'])
        model = ResidualLSTM(cfg, dataset.dimensions(), checkpoint['statistics'])
        model.load_state_dict(checkpoint['model_state'])
        model.to(cfg['training']['device'])
        predictions.append(predict(model, dataset, cfg))
        checkpoints.append(checkpoint)
    mean = np.mean([p['mean'] for p in predictions], axis=0)
    quantiles = np.mean([p['quantiles'] for p in predictions], axis=0)
    point, intervals = apply_postprocessing(mean, quantiles, predictions[0]['baseline'], post)
    if not np.isfinite(point).all() or not np.isfinite(intervals).all() or (np.diff(intervals, axis=-1) < 0).any():
        raise FloatingPointError('Invalid predictions')
    stats = checkpoints[0]['statistics']
    threshold = stats['flood_threshold_cumecs']
    records = []
    for index in range(len(dataset)):
        basin, issue = dataset.metadata(index)
        frame = store.frames[basin]
        known = frame.loc[:issue, 'q_cumecs'].dropna()
        persistence = float(known.iloc[-1]) if len(known) else np.nan
        curves = stats['climatology'][basin]
        for lead in range(1, 31):
            date = issue + pd.Timedelta(days=lead)
            observed = frame.loc[date, 'q_cumecs']
            if not np.isfinite(observed):
                continue
            row = {'basin_id': basin, 'issue_date': issue.strftime('%Y-%m-%d'),
                   'target_date': date.strftime('%Y-%m-%d'), 'lead_day': lead, 'season': season(date),
                   'observed_cumecs': float(observed), 'Residual_ensemble': float(point[index, lead - 1]),
                   'Raw_residual_ensemble': float(mean[index, lead - 1]),
                   'Climatology': curves['exact'].get(date.strftime('%m-%d'), curves['fallback']),
                   'Smooth_climatology': curves['smooth'].get(date.strftime('%m-%d'), curves['fallback']),
                   'Persistence': persistence}
            for j, q in enumerate(cfg['model']['quantiles']):
                row[f'q{q}'] = float(intervals[index, lead - 1, j])
                row[f'raw_q{q}'] = float(quantiles[index, lead - 1, j])
            records.append(row)
    table = pd.DataFrame(records)
    keys = ['basin_id', 'issue_date', 'target_date', 'lead_day']
    for setting, column, name in [('weather_only_predictions', 'LSTM_30d', 'Weather_only_LSTM'),
                                   ('past_discharge_predictions', 'LSTM_30d_pastQ', 'Past_discharge_LSTM')]:
        old = pd.read_csv(resolve(cfg, cfg['evaluation'][setting]))[keys + ['observed_cumecs', column]]
        old = old.rename(columns={'observed_cumecs': 'reference_observed', column: name})
        size = len(table)
        table = table.merge(old, on=keys, how='inner', validate='one_to_one')
        if len(table) != size or not np.array_equal(table.observed_cumecs, table.reference_observed):
            raise ValueError('Reference observed dates differ')
        table = table.drop(columns='reference_observed')
    output = resolve(cfg, cfg['evaluation']['output_dir'])
    compare = resolve(cfg, cfg['evaluation']['comparison_dir'])
    output.mkdir(parents=True, exist_ok=True)
    compare.mkdir(parents=True, exist_ok=True)
    own_columns = keys + ['season', 'observed_cumecs', 'Residual_ensemble'] + [f'q{q}' for q in cfg['model']['quantiles']]
    table[own_columns].to_csv(output / 'predictions.csv', index=False)
    table.to_csv(compare / 'matched_predictions.csv', index=False)
    names = ['Residual_ensemble', 'Raw_residual_ensemble', 'Climatology', 'Smooth_climatology',
             'Weather_only_LSTM', 'Past_discharge_LSTM', 'Persistence']
    all_scores, seasonal, coverage = [], [], []
    for lead, frame in table.groupby('lead_day'):
        for name in names:
            for label, sub in [('all', frame), ('flood', frame.loc[frame.observed_cumecs > threshold]), ('non_flood', frame.loc[frame.observed_cumecs <= threshold])]:
                all_scores.append({'model': name, 'lead_day': lead, 'group': label,
                                   **metrics(sub.observed_cumecs, sub[name], threshold)})
            for label, sub in frame.groupby('season'):
                seasonal.append({'model': name, 'lead_day': lead, 'season': label,
                                 **metrics(sub.observed_cumecs, sub[name], threshold)})
        for name, prefix in [('raw', 'raw_'), ('validation_adjusted', '')]:
            coverage.append({'lead_day': lead, 'version': name, 'n': len(frame),
                             'coverage_05_95': float(((frame.observed_cumecs >= frame[f'{prefix}q0.05']) & (frame.observed_cumecs <= frame[f'{prefix}q0.95'])).mean()),
                             'interval_width_cumecs': float((frame[f'{prefix}q0.95'] - frame[f'{prefix}q0.05']).mean())})
    scores, seasonal, coverage = map(pd.DataFrame, (all_scores, seasonal, coverage))
    scores.to_csv(compare / 'scores_flood_nonflood_by_lead.csv', index=False)
    seasonal.to_csv(compare / 'scores_by_season_and_lead.csv', index=False)
    coverage.to_csv(output / 'quantile_calibration.csv', index=False)
    scores.loc[scores.model.eq('Residual_ensemble')].to_csv(output / 'scores_flood_nonflood_by_lead.csv', index=False)
    scores.loc[scores.model.eq('Residual_ensemble') & scores.group.eq('all')].drop(columns='group').to_csv(output / 'scores_by_lead.csv', index=False)
    seasonal.loc[seasonal.model.eq('Residual_ensemble')].to_csv(output / 'scores_by_season_and_lead.csv', index=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name in ('Residual_ensemble', 'Climatology', 'Smooth_climatology', 'Past_discharge_LSTM', 'Persistence'):
        selected = scores.loc[scores.model.eq(name) & scores.group.eq('all')]
        axes[0].plot(selected.lead_day, selected.NSE, label=name)
        axes[1].plot(selected.lead_day, selected.RMSE_cumecs)
    axes[0].set(xlabel='Lead day', ylabel='NSE')
    axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[0].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(compare / 'skill_by_lead.png', dpi=160)
    plt.close(fig)
    final = scores.loc[scores.lead_day.eq(30) & scores.group.eq('all')].set_index('model')
    manifest = {'training_years': years(cfg['splits']['train']), 'selection_years': years(cfg['splits']['validation']),
                'test_years': years(cfg['splits']['test']), 'selected_epochs': [c['epoch'] for c in checkpoints],
                'training_seconds': sum(x['seconds'] for x in selection['training_summaries']),
                'new_seed_models': len(paths), 'parameters_per_member': selection['training_summaries'][0]['parameters'],
                'unique_observed_test_days': len(table[['basin_id', 'target_date']].drop_duplicates()),
                'observed_issue_lead_pairs': len(table), 'day30_observations': int(final.loc['Residual_ensemble', 'n']),
                'day30_nse': float(final.loc['Residual_ensemble', 'NSE']),
                'climatology_day30_nse': float(final.loc['Climatology', 'NSE']),
                'smooth_climatology_day30_nse': float(final.loc['Smooth_climatology', 'NSE']),
                'beats_original_climatology_day30': bool(final.loc['Residual_ensemble', 'NSE'] > final.loc['Climatology', 'NSE']),
                'beats_smooth_climatology_day30': bool(final.loc['Residual_ensemble', 'NSE'] > final.loc['Smooth_climatology', 'NSE']),
                'source_sha256': sha(resolve(cfg, cfg['data']['daily_file'])),
                'postprocessing_sha256': sha(run / 'validation_postprocessing.json'),
                'test_evaluations_before_this_report': 0,
                'all_choices_fixed_using_training_and_validation_only': True,
                'test_years_inspected_in_prior_project_experiments': True,
                'operational_forecast_skill_established': False,
                'flood_threshold_cumecs': threshold}
    save_json(output / 'evaluation_manifest.json', manifest)
    cols = ['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs', 'PBIAS_pct']
    finding = (f'Day-30 mean-flow NSE is **{manifest["day30_nse"]:.3f}**, versus exact climatology '
               f'**{manifest["climatology_day30_nse"]:.3f}** and smoothed climatology **{manifest["smooth_climatology_day30_nse"]:.3f}**. '
               f'Beats the original climatology: **{manifest["beats_original_climatology_day30"]}**; '
               f'beats the smoothed control: **{manifest["beats_smooth_climatology_day30"]}**.')
    report = ['# Thirty-day climatology-residual LSTM ensemble', '', finding, '',
              f'Three seeds were trained sequentially: {cfg["training"]["seeds"]}. Selected epochs: {manifest["selected_epochs"]}; total fitting time {manifest["training_seconds"]:.1f} seconds. All choices, blend strengths and empirical quantile offsets were fixed using 2021 before this benchmark evaluation.', '',
              f'Observed benchmark: 2022-2024, {manifest["unique_observed_test_days"]} unique target dates, {len(table)} issue/lead/target pairs, and {manifest["day30_observations"]} day-30 observations. Original targets and NaNs were never changed.', '',
              '## Day-30 observed scores', '', markdown(scores.loc[scores.lead_day.eq(30) & scores.group.eq('all'), cols]), '',
              '## Selected leads', '', markdown(scores.loc[scores.lead_day.isin([1, 10, 20, 30]) & scores.group.eq('all') & scores.model.isin(['Residual_ensemble', 'Climatology', 'Smooth_climatology']), cols]), '',
              '## High-flow and other days at day 30', '', markdown(scores.loc[scores.lead_day.eq(30) & scores.group.ne('all') & scores.model.isin(['Residual_ensemble', 'Climatology', 'Smooth_climatology', 'Past_discharge_LSTM']), ['model', 'group', 'n', 'NSE', 'RMSE_cumecs', 'MAE_cumecs', 'flood_hit_rate', 'false_alarm_ratio']]), '',
              f'High-flow proxy: observed discharge above training-only Q95 = {threshold:.6f} cumecs. This is not an official flood category or an independent event count.', '',
              '## Day-30 seasons', '', markdown(seasonal.loc[seasonal.lead_day.eq(30) & seasonal.model.isin(['Residual_ensemble', 'Climatology', 'Smooth_climatology'])]), '',
              '## Day-30 interval coverage', '', markdown(coverage.loc[coverage.lead_day.eq(30)]), '',
              'Nominal P05-P95 coverage is 90%. The separate quantile head is trained with pinball loss. Empirical offsets use validation residual quantiles in three predefined lead groups; ordering is projected after correction. The same validation year was used for checkpoint selection and correction fitting, so there is no independent conformal coverage guarantee. Quantiles remain daily marginal values, not joint event probabilities.', '',
              '## Model and objective', '',
              'The mean-flow head predicts a correction to a 31-day circular, count-weighted climatology fitted only on observed 2016-2020 discharge. Training anchors are cross-fitted by excluding the target year. Validation and benchmark use full training climatology. A separate exact month/day climatology is retained as the original benchmark.', '',
              'The encoder and decoder start from the saved past-discharge LSTM; the extra climatology input column is zero-initialized. Mean and quantile heads are new. Training uses linear-flow MSE scaled by training flow standard deviation, auxiliary ordered-quantile pinball loss, and a residual penalty. Leads 21-30 receive double training weight. Selection uses validation mean scaled MSE across leads 21-30, with the initial smooth-climatology prediction retained as an epoch-zero fallback.', '',
              'The three selected mean/quantile outputs are averaged. A validation-fitted coefficient in each predefined group (1-10, 11-20, 21-30) shrinks them toward exact climatology. Mean and median are separate outputs; NSE is scored on the mean forecast, unlike the earlier median-based LSTMs.', '',
              '## Limits and interpretation', '',
              'Weather is still noisy future reanalysis, not archived operational forecasts. Only past observed flow through issue time is an input. Source publication latency is unverified. These previously inspected 2022-2024 years are a comparison benchmark, not a fresh project-wide holdout. One three-seed ensemble does not establish general performance across future periods. There was no test-driven retry after this evaluation.', '',
              'Both the original and smoothed climatology controls are reported so a benefit from calendar smoothing is not attributed automatically to the neural network. Epoch-zero selections, if any, appear in the training summaries. No other model family was trained in this step.', '',
              '![Lead-day comparison](skill_by_lead.png)', '']
    (compare / 'comparison_report.md').write_text('\n'.join(report), encoding='utf-8')
    run_report = '\n'.join(report).replace('](skill_by_lead.png)', '](../../../../evaluation%20comparison/model_30_days/climatology_residual_ensemble/skill_by_lead.png)')
    (Path(cfg['_root']) / 'RUN_RESULTS.md').write_text(run_report, encoding='utf-8')
    readme = Path(cfg['_root']) / 'README.md'
    if readme.exists():
        text = readme.read_text(encoding='utf-8').split('<!-- RESULTS -->')[0]
        readme.write_text(text + '<!-- RESULTS -->\n\n## Measured results\n\n' + finding + '\n\n'
                          + markdown(scores.loc[scores.lead_day.eq(30) & scores.group.eq('all'), cols]) + '\n', encoding='utf-8')
    print(finding, flush=True)
    print(scores.loc[scores.lead_day.eq(30) & scores.group.eq('all'), cols].to_string(index=False), flush=True)
    print(f'Report: {compare / "comparison_report.md"}', flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    evaluate(load_config(parser.parse_args().config))
