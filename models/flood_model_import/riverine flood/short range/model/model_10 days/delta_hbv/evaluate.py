"""Score the selected checkpoint on observed test targets only."""
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
from torch.utils.data import DataLoader

from data import DataStore, DeltaDataset, load_config, resolve, save_json, sha256, years
from model import DeltaHBV


def season(date):
    return 'Oct-Mar' if date.month in (10, 11, 12, 1, 2, 3) else 'Apr-Jun' if date.month in (4, 5, 6) else 'Jul-Sep'


def metrics(y, p, threshold):
    y, p = np.asarray(y, float), np.asarray(p, float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    if not len(y):
        return {'n': 0}
    error = p - y
    variance = ((y - y.mean()) ** 2).sum()
    kge = np.nan
    if len(y) > 1 and y.std() > 0 and p.std() > 0 and y.mean() > 0:
        kge = 1 - np.sqrt((np.corrcoef(y, p)[0, 1] - 1) ** 2 + (p.std() / y.std() - 1) ** 2 + (p.mean() / y.mean() - 1) ** 2)
    flood = y > threshold
    alerts = p > threshold
    tp, fp = int((flood & alerts).sum()), int((~flood & alerts).sum())
    return {'n': len(y), 'NSE': 1 - (error ** 2).sum() / variance if variance > 0 else np.nan,
            'KGE': kge, 'RMSE_cumecs': np.sqrt((error ** 2).mean()), 'MAE_cumecs': np.abs(error).mean(),
            'PBIAS_pct': 100 * error.sum() / y.sum() if y.sum() else np.nan,
            'peak_n': int(flood.sum()), 'peak_MAPE_pct': 100 * np.abs(error[flood] / y[flood]).mean() if flood.any() else np.nan,
            'flood_hit_rate': tp / flood.sum() if flood.any() else np.nan,
            'false_alarm_rate': fp / (~flood).sum() if (~flood).any() else np.nan,
            'false_alarm_ratio': fp / alerts.sum() if alerts.any() else np.nan}


def markdown(frame):
    def value(x):
        if pd.isna(x):
            return 'NA'
        return f'{x:.3f}' if isinstance(x, (float, np.floating)) else str(x)
    return '\n'.join(['| ' + ' | '.join(frame.columns) + ' |', '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |'] +
                     ['| ' + ' | '.join(value(x) for x in row) + ' |' for row in frame.itertuples(index=False, name=None)])


def evaluate(cfg):
    torch.set_num_threads(cfg['training']['cpu_threads'])
    torch.manual_seed(cfg['training']['seed'])
    checkpoint_path = resolve(cfg, cfg['training']['output_dir']) / 'best.pt'
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=False)
    test_years = set(years(cfg['splits']['test']))
    used_years = set(checkpoint['training_years']) | set(checkpoint['selection_years'])
    if test_years & used_years:
        raise ValueError('A test year was used for training or validation selection')
    for key in ('data', 'model'):
        ignored_paths = {'daily_file', 'static_file', 'forecast_file', 'area_metadata'}
        current_schema = {k: v for k, v in cfg[key].items() if k not in ignored_paths}
        saved_schema = {k: v for k, v in checkpoint['config'][key].items() if k not in ignored_paths}
        if current_schema != saved_schema:
            raise ValueError(f'{key} configuration differs from selected checkpoint')
    source = resolve(cfg, cfg['data']['daily_file'])
    if sha256(source) != checkpoint['source_sha256']:
        raise ValueError('Evaluation data changed after training')
    store = DataStore(cfg)
    dataset = DeltaDataset(store, 'test', checkpoint['statistics'])
    model = DeltaHBV(cfg)
    model.load_state_dict(checkpoint['model_state'])
    model.eval()
    device = torch.device(cfg['training']['device'])
    model.to(device)
    started = time.perf_counter()
    predictions = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=cfg['training']['batch_size'], shuffle=False):
            prediction = model(batch['neural'].to(device), batch['forcing'].to(device)).cpu().numpy()
            if not np.isfinite(prediction).all() or (prediction < 0).any():
                raise FloatingPointError('Invalid physical discharge')
            predictions.extend(prediction)
    rows = []
    horizon = cfg['data']['forecast_horizon']
    climo = {}
    for basin, frame in store.frames.items():
        training = frame.loc[frame.index.year.isin(years(cfg['splits']['train']))]
        observed = training.q_cumecs.dropna()
        climo[basin] = (observed.groupby(observed.index.strftime('%m-%d')).mean().to_dict(), observed.mean())
    for index, prediction in enumerate(predictions):
        basin, issue = dataset.metadata(index)
        frame = store.frames[basin]
        latest = frame.loc[:issue, 'q_cumecs'].dropna()
        persistence = latest.iloc[-1] if len(latest) else np.nan
        for lead in range(1, horizon + 1):
            date = issue + pd.Timedelta(days=lead)
            q = frame.loc[date, 'q_cumecs']
            if not np.isfinite(q):
                continue
            means, default = climo[basin]
            rows.append({'basin_id': basin, 'issue_date': issue.strftime('%Y-%m-%d'),
                         'target_date': date.strftime('%Y-%m-%d'), 'lead_day': lead, 'season': season(date),
                         'observed_cumecs': float(q), 'delta_HBV': float(prediction[lead - 1]),
                         'Persistence': float(persistence), 'Climatology': float(means.get(date.strftime('%m-%d'), default))})
    table = pd.DataFrame(rows)
    threshold = checkpoint['statistics']['flood_threshold_cumecs']
    output = resolve(cfg, cfg['evaluation']['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    own_columns = ['basin_id', 'issue_date', 'target_date', 'lead_day', 'season', 'observed_cumecs', 'delta_HBV']
    table[own_columns].to_csv(output / 'predictions.csv', index=False)
    own_scores, seasonal, own_groups = [], [], []
    for lead, group in table.groupby('lead_day'):
        own_scores.append({'model': 'delta_HBV', 'lead_day': lead, **metrics(group.observed_cumecs, group.delta_HBV, threshold)})
        for name, sub in group.groupby('season'):
            seasonal.append({'model': 'delta_HBV', 'lead_day': lead, 'season': name, **metrics(sub.observed_cumecs, sub.delta_HBV, threshold)})
        for name, sub in [('all', group), ('flood', group.loc[group.observed_cumecs > threshold]), ('non_flood', group.loc[group.observed_cumecs <= threshold])]:
            own_groups.append({'model': 'delta_HBV', 'lead_day': lead, 'group': name, **metrics(sub.observed_cumecs, sub.delta_HBV, threshold)})
    scores = pd.DataFrame(own_scores)
    seasonal = pd.DataFrame(seasonal)
    groups = pd.DataFrame(own_groups)
    scores.to_csv(output / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(output / 'scores_by_season_and_lead.csv', index=False)
    groups.to_csv(output / 'scores_flood_nonflood_by_lead.csv', index=False)
    # Original model is scored on exactly the same issue/target/lead records.
    reference_path = resolve(cfg, cfg['evaluation']['reference_predictions'])
    reference = pd.read_csv(reference_path)
    keys = ['basin_id', 'issue_date', 'target_date', 'lead_day']
    reference = reference[keys + ['observed_cumecs', 'LSTM']].rename(columns={'observed_cumecs': 'reference_observed'})
    compared = table.merge(reference, on=keys, how='inner', validate='one_to_one')
    if len(compared) != len(table) or not np.allclose(compared.observed_cumecs, compared.reference_observed, rtol=0, atol=1e-8):
        raise ValueError('Original LSTM does not match all observed targets')
    all_scores = []
    for lead, group in compared.groupby('lead_day'):
        for model_name in ('delta_HBV', 'LSTM', 'Persistence', 'Climatology'):
            for group_name, sub in [('all', group), ('flood', group.loc[group.observed_cumecs > threshold]), ('non_flood', group.loc[group.observed_cumecs <= threshold])]:
                all_scores.append({'model': model_name, 'lead_day': lead, 'group': group_name,
                                   **metrics(sub.observed_cumecs, sub[model_name], threshold)})
    all_scores = pd.DataFrame(all_scores)
    comparison = resolve(cfg, cfg['evaluation']['comparison_dir'])
    comparison.mkdir(parents=True, exist_ok=True)
    compared.to_csv(comparison / 'matched_predictions.csv', index=False)
    all_scores.to_csv(comparison / 'scores_flood_nonflood_by_lead.csv', index=False)
    # Append the new row to a new comparison file; older reports remain historical.
    previous = resolve(cfg, cfg['evaluation']['existing_comparison'])
    if previous.exists():
        old = pd.read_csv(previous)
        appended = groups.assign(cohort='main_2022_2024').drop(columns=['peak_n', 'peak_MAPE_pct', 'flood_hit_rate', 'false_alarm_rate', 'false_alarm_ratio'])
        pd.concat([old, appended], ignore_index=True).to_csv(comparison / 'all_models_flood_nonflood_by_lead.csv', index=False)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for name, frame in all_scores.loc[all_scores.group.eq('all')].groupby('model'):
        axes[0].plot(frame.lead_day, frame.NSE, marker='o', markersize=3, label=name)
        axes[1].plot(frame.lead_day, frame.RMSE_cumecs)
    axes[0].set(ylabel='NSE', xlabel='Lead day')
    axes[1].set(ylabel='RMSE (m3/s)', xlabel='Lead day')
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(comparison / 'skill_by_lead.png', dpi=160)
    plt.close(fig)
    dates = pd.to_datetime(table.target_date)
    counts = table[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda x: pd.to_datetime(x.target_date).dt.year).groupby('year').size().rename('observed_days').reset_index()
    counts.to_csv(output / 'observed_test_days_per_year.csv', index=False)
    summary = json.loads((checkpoint_path.parent / 'training_summary.json').read_text())
    summary.update({'selected_epoch': checkpoint['epoch'], 'test_years': sorted(test_years),
                    'unique_observed_test_days': len(table[['basin_id', 'target_date']].drop_duplicates()),
                    'observed_issue_lead_pairs': len(table), 'test_samples': len(dataset),
                    'flood_threshold_cumecs': threshold, 'inference_seconds': time.perf_counter() - started,
                    'checkpoint_sha256': sha256(checkpoint_path), 'input_sha256': sha256(source),
                    'source_targets_unchanged': True, 'forecast_type': 'noisy reanalysis, not operational forecasts'})
    save_json(output / 'evaluation_manifest.json', summary)
    cols = ['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs', 'PBIAS_pct']
    report = ['# Marala differentiable HBV: actual results', '',
              'The authors\' HBV 1.0 equations are coupled to a new causal LSTM parameter network and trained end to end on Marala. This is a single-basin adaptation of delta-HBV, not downloaded pretrained delta-HBV weights or delta-HBV 2.0.', '',
              f'Train: {checkpoint["training_years"]}; validation/checkpoint selection: {checkpoint["selection_years"]}; test: {sorted(test_years)}. Observed test days: **{summary["unique_observed_test_days"]}**; observed issue/lead pairs: **{len(table)}**. Missing targets were never filled or scored.', '',
              f'Actual training: **{summary["seconds"]:.1f} seconds**, {summary["epochs"]} epochs, selected epoch {checkpoint["epoch"]}, seed {summary["seed"]}, {summary["parameters"]:,} trainable parameters. One fixed configuration; no HPO sweep.', '',
              '## Scores on identical observed records', '',
              markdown(all_scores.loc[all_scores.group.eq('all') & all_scores.lead_day.isin([1, 5, horizon]), cols]), '',
              f'## Flood and other days at lead {horizon}', '',
              markdown(all_scores.loc[all_scores.lead_day.eq(horizon) & all_scores.group.ne('all'), ['model', 'group', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs']]), '',
              f'Flood proxy: observed Q above training Q95 = **{threshold:.6f} m3/s**; other days are at or below it. This is not an official flood category. NSE is not an accuracy percentage.', '',
              '## Seasonal scores', '', markdown(seasonal.loc[seasonal.lead_day.eq(horizon)]), '',
              '## Interpretation and limits', '',
              'Future precipitation/temperature are realized ERA5-Land plus the same seeded standardized noise used in the earlier LSTM experiment. Future PET is a training-only monthly climatology. Real archived weather forecasts are unavailable; operational skill is unverified.', '',
              'The weather inputs differ from the eight-input original LSTM: this model uses ERA5-Land precipitation, temperature and PET, with no observed flow as a predictor. Architecture differences cannot be isolated from these input differences. The record is short, regulated, and these test years were inspected in earlier experiments; they are not a fresh project-wide holdout.', '',
              'Three HBV components are averaged. The LSTM learns time-varying BETA, CFMAX and K1; other HBV and gamma-routing parameters are learned as basin constants. Outputs are routed physical runoff converted using a delineated area of 28,780.646 km2. No residual ML discharge head is present. The deterministic model does not provide calibrated forecast intervals.', '',
              'Every third eligible training issue is used per epoch to control CPU cost; validation and test use every eligible issue. Each sample contains 365 history days and 10 forecast days; the first 305 physical days are upstream no-gradient warmup, leaving 60 history days plus 10 forecast days for parameter gradients. Missing predictor values use training means and indicators; actual 2015-2024 required forcing coverage is complete.', '',
              '## Provenance and license', '',
              '[MHPI hydrodl2](https://github.com/mhpi/hydrodl2), pinned commit b163a3c0125c5188f730f379643437d83b4e5d35; unmodified upstream sources and their SHA256 values are in source_reference/. Upstream code is licensed for non-commercial use; commercial use requires permission from PSU. See source_reference/LICENSE.', '',
              'Synthetic tests check gradients, masking, alignment and loading only; they do not establish forecast accuracy.', '',
              '![Lead-day skill](skill_by_lead.png)', '']
    (comparison / 'comparison_report.md').write_text('\n'.join(report), encoding='utf-8')
    own_report = ['# delta-HBV observed test performance', '', markdown(scores[cols]), '', markdown(groups.loc[groups.lead_day.eq(horizon)]), '',
                  f'Observed test days: {summary["unique_observed_test_days"]}; test years: {sorted(test_years)}.', '',
                  'The full methods and limitations are in README.md and the separate evaluation comparison/delta_hbv/comparison_report.md.', '']
    (output / 'evaluation_report.md').write_text('\n'.join(own_report), encoding='utf-8')
    (Path(cfg['_root']) / 'RUN_RESULTS.md').write_text('\n'.join(report).replace('](skill_by_lead.png)', '](../../../evaluation%20comparison/delta_hbv/skill_by_lead.png)'), encoding='utf-8')
    print(scores.loc[scores.lead_day.isin([1, 5, horizon]), cols].to_string(index=False), flush=True)
    print(f'Report: {comparison / "comparison_report.md"}', flush=True)
    return scores, groups


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    evaluate(load_config(parser.parse_args().config))
