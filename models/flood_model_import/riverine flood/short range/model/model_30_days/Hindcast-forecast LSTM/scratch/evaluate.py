"""Observed-only 30-lead evaluation, quantile calibration, and saved comparisons."""
import argparse
import hashlib
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

from data import DataStore, StreamflowDataset, inverse_flow, load_config, resolve, years
from model import HindcastForecastLSTM
from _training import check_evaluation_years, device_for, load_checkpoint, seed_everything
from baselines import Baselines


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def season(date):
    return 'Oct-Mar' if date.month in (10, 11, 12, 1, 2, 3) else 'Apr-Jun' if date.month in (4, 5, 6) else 'Jul-Sep'


def metrics(observed, predicted, threshold):
    y, p = np.asarray(observed, float), np.asarray(predicted, float)
    valid = np.isfinite(y) & np.isfinite(p)
    y, p = y[valid], p[valid]
    if not len(y):
        return {'n': 0}
    error = p - y
    variance = ((y - y.mean()) ** 2).sum()
    kge = np.nan
    if len(y) > 1 and y.std() > 0 and p.std() > 0 and y.mean() > 0:
        kge = 1 - np.sqrt((np.corrcoef(y, p)[0, 1] - 1) ** 2 + (p.std() / y.std() - 1) ** 2 + (p.mean() / y.mean() - 1) ** 2)
    flood, alerts = y > threshold, p > threshold
    hits, false = int((flood & alerts).sum()), int((~flood & alerts).sum())
    return {'n': len(y), 'NSE': 1 - (error ** 2).sum() / variance if variance > 0 else np.nan,
            'KGE': kge, 'RMSE_cumecs': np.sqrt((error ** 2).mean()), 'MAE_cumecs': np.abs(error).mean(),
            'PBIAS_pct': 100 * error.sum() / y.sum() if y.sum() else np.nan,
            'peak_n': int(flood.sum()), 'peak_MAPE_pct': 100 * np.abs(error[flood] / y[flood]).mean() if flood.any() else np.nan,
            'flood_hit_rate': hits / flood.sum() if flood.any() else np.nan,
            'false_alarm_rate': false / (~flood).sum() if (~flood).any() else np.nan,
            'false_alarm_ratio': false / alerts.sum() if alerts.any() else np.nan}


def markdown(frame):
    def format_value(value):
        if pd.isna(value):
            return 'NA'
        return f'{value:.3f}' if isinstance(value, (float, np.floating)) else str(value)
    return '\n'.join(['| ' + ' | '.join(frame.columns) + ' |', '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |'] +
                     ['| ' + ' | '.join(format_value(x) for x in row) + ' |' for row in frame.itertuples(index=False, name=None)])


def evaluate(cfg):
    options = cfg['training']
    seed_everything(options['seeds'][0], options['cpu_threads'])
    torch.set_flush_denormal(options.get('flush_denormal', False))
    paths = json.loads((resolve(cfg, options['output_dir']) / 'ensemble.json').read_text())['checkpoints']
    if len(paths) != 1:
        raise ValueError('This first experiment evaluates one trained seed only')
    path = Path(paths[0])
    checkpoint = load_checkpoint(path)
    check_evaluation_years(cfg, checkpoint)
    for key in ('data', 'model', 'splits'):
        if cfg[key] != checkpoint['config'][key]:
            raise ValueError(f'{key} differs from the saved checkpoint')
    source = resolve(cfg, cfg['data']['daily_file'])
    if sha256(source) != checkpoint['source_hashes']['daily_file']:
        raise ValueError('The source table changed after fitting')
    store = DataStore(cfg)
    dataset = StreamflowDataset(store, 'test', checkpoint['statistics'])
    model = HindcastForecastLSTM(cfg, *dataset.dimensions())
    model.load_state_dict(checkpoint['model_state'])
    device = device_for(cfg)
    model.to(device).eval()
    started = time.perf_counter()
    predicted = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=options['batch_size'], shuffle=False):
            output = model(*(batch[k].to(device) for k in ('history', 'future', 'static')))
            predicted.append(inverse_flow(output.cpu().numpy(), checkpoint['statistics']))
    quantiles = np.concatenate(predicted)
    if not np.isfinite(quantiles).all() or (np.diff(quantiles, axis=-1) < -1e-8).any():
        raise FloatingPointError('Nonfinite or crossing discharge quantiles')
    training_q = np.concatenate([frame.loc[frame.index.year.isin(years(cfg['splits']['train'])), store.d['target_column']].dropna().to_numpy()
                                 for frame in store.frames.values()])
    threshold = float(np.quantile(training_q, cfg['evaluation']['flood_percentile']))
    baseline = Baselines(store)
    tau = cfg['model']['quantiles']
    rows = []
    for index in range(len(dataset)):
        basin, issue = dataset.metadata(index)
        for lead in range(1, cfg['data']['forecast_horizon'] + 1):
            target = issue + pd.Timedelta(days=lead)
            q = store.frames[basin].loc[target, store.d['target_column']]
            if not np.isfinite(q):
                continue
            persistence, climatology = baseline.predict(basin, issue, target)
            record = {'basin_id': basin, 'issue_date': issue.strftime('%Y-%m-%d'),
                      'target_date': target.strftime('%Y-%m-%d'), 'lead_day': lead, 'season': season(target),
                      'observed_cumecs': float(q), 'LSTM_30d': float(quantiles[index, lead - 1, tau.index(.5)]),
                      'Persistence': persistence, 'Climatology': float(climatology)}
            record.update({f'q{level}': float(quantiles[index, lead - 1, j]) for j, level in enumerate(tau)})
            rows.append(record)
    table = pd.DataFrame(rows)
    output = resolve(cfg, cfg['evaluation']['output_dir'])
    compare = resolve(cfg, cfg['evaluation']['comparison_dir'])
    output.mkdir(parents=True, exist_ok=True)
    compare.mkdir(parents=True, exist_ok=True)
    table.drop(columns=['Persistence', 'Climatology']).to_csv(output / 'predictions.csv', index=False)
    table.to_csv(compare / 'matched_predictions.csv', index=False)
    results, seasonal, grouped, calibration = [], [], [], []
    for lead, frame in table.groupby('lead_day'):
        for name in ('LSTM_30d', 'Persistence', 'Climatology'):
            results.append({'model': name, 'lead_day': lead, **metrics(frame.observed_cumecs, frame[name], threshold)})
            for label, sub in frame.groupby('season'):
                seasonal.append({'model': name, 'lead_day': lead, 'season': label, **metrics(sub.observed_cumecs, sub[name], threshold)})
            for label, sub in [('all', frame), ('flood', frame.loc[frame.observed_cumecs > threshold]), ('non_flood', frame.loc[frame.observed_cumecs <= threshold])]:
                grouped.append({'model': name, 'lead_day': lead, 'group': label, **metrics(sub.observed_cumecs, sub[name], threshold)})
        calibration.append({'lead_day': lead, 'n': len(frame),
                            'coverage_05_95': float(((frame.observed_cumecs >= frame['q0.05']) & (frame.observed_cumecs <= frame['q0.95'])).mean()),
                            'mean_interval_width_cumecs': float((frame['q0.95'] - frame['q0.05']).mean()),
                            **{f'fraction_below_q{q}': float((frame.observed_cumecs <= frame[f'q{q}']).mean()) for q in tau}})
    results, seasonal, grouped, calibration = map(pd.DataFrame, (results, seasonal, grouped, calibration))
    results.to_csv(compare / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(compare / 'scores_by_season_and_lead.csv', index=False)
    grouped.to_csv(compare / 'scores_flood_nonflood_by_lead.csv', index=False)
    results.loc[results.model.eq('LSTM_30d')].to_csv(output / 'scores_by_lead.csv', index=False)
    seasonal.loc[seasonal.model.eq('LSTM_30d')].to_csv(output / 'scores_by_season_and_lead.csv', index=False)
    grouped.loc[grouped.model.eq('LSTM_30d')].to_csv(output / 'scores_flood_nonflood_by_lead.csv', index=False)
    calibration.to_csv(output / 'quantile_calibration.csv', index=False)
    by_year = table[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda f: pd.to_datetime(f.target_date).dt.year).groupby('year').size().rename('observed_days').reset_index()
    by_year.to_csv(output / 'observed_test_days_per_year.csv', index=False)
    history = json.loads((path.parent / 'history.json').read_text())
    manifest = {'forecast_horizon': cfg['data']['forecast_horizon'],
                'training_years': checkpoint['training_years'], 'selection_years': checkpoint['selection_years'],
                'test_years': years(cfg['splits']['test']), 'test_samples': len(dataset),
                'unique_observed_test_days': int(by_year.observed_days.sum()), 'observed_issue_lead_pairs': len(table),
                'day30_observations': int(table.lead_day.eq(30).sum()),
                'training_samples': checkpoint['train_samples'], 'validation_samples': checkpoint['validation_samples'],
                'training_seconds': history['elapsed_seconds'], 'epochs': len(history['epochs']),
                'selected_epoch': checkpoint['epoch'], 'validation_pinball': checkpoint['validation_pinball'],
                'stopping_reason': 'validation patience reached' if len(history['epochs']) < options['epochs'] else 'configured epoch cap reached',
                'seed': checkpoint['seed'], 'parameters': sum(p.numel() for p in model.parameters()),
                'flood_threshold_cumecs': threshold, 'source_sha256': sha256(source), 'checkpoint_sha256': sha256(path),
                'forecast_mode': cfg['data']['forecast_mode'], 'archived_forecasts_available': store.archive is not None,
                'hpo_search_performed': False, 'real_data_training_runs': 1,
                'targets_unchanged': True, 'noncrossing_quantiles_verified': True,
                'inference_and_report_seconds': time.perf_counter() - started}
    save_json(output / 'evaluation_manifest.json', manifest)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, frame in results.groupby('model'):
        axes[0].plot(frame.lead_day, frame.NSE, label=name)
        axes[1].plot(frame.lead_day, frame.RMSE_cumecs)
    axes[0].set(xlabel='Lead day', ylabel='NSE')
    axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(compare / 'skill_by_lead.png', dpi=160)
    plt.close(fig)
    leads = cfg['evaluation']['report_leads']
    cols = ['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs', 'PBIAS_pct']
    report = ['# Thirty-day hindcast-forecast LSTM: first experiment', '',
              'Only the scratch LSTM was trained. All other 30-day model families remain pending feedback.', '',
              f'Train: {checkpoint["training_years"]}; validation selection: {checkpoint["selection_years"]}; observed test years: {manifest["test_years"]}. Training used {checkpoint["train_samples"]} issue windows; validation used {checkpoint["validation_samples"]}.', '',
              f'Actual fitting took **{manifest["training_seconds"]:.1f} seconds**, {manifest["epochs"]} epochs; selected epoch **{checkpoint["epoch"]}**, seed {checkpoint["seed"]}, {manifest["parameters"]:,} parameters. Stop: {manifest["stopping_reason"]}. One fixed configuration, no HPO sweep.', '',
              f'Observed test dates: **{manifest["unique_observed_test_days"]}**; observed issue/lead/target pairs: **{len(table)}**; day-30 observations: **{manifest["day30_observations"]}**. Missing targets were never filled or scored.', '',
              '## Matched observed-day comparison', '', markdown(results.loc[results.lead_day.isin(leads), cols]), '',
              '## Day-30 flood and non-flood results', '',
              markdown(grouped.loc[grouped.lead_day.eq(30) & grouped.group.ne('all'), ['model', 'group', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs']]), '',
              f'Flood proxy is observed discharge strictly above observed-training Q95 = **{threshold:.6f} m3/s**. This is not an official flood warning category or an independent event count. Subset NSE uses that subset\'s mean and variance and can be negative.', '',
              '## Day-30 season scores', '', markdown(seasonal.loc[seasonal.lead_day.eq(30)]), '',
              '## Quantile calibration', '', markdown(calibration.loc[calibration.lead_day.isin(leads)]), '',
              'The nominal P05-P95 coverage is 90%. Quantiles are ordered by construction; this does not guarantee calibration. Quantiles are marginal daily values and do not define joint 30-day flood-event probabilities.', '',
              '## Limits', '',
              'Archived 30-day TIGGE/GFS weather forecasts were not found. Future rain and temperature are realized ERA5-Land plus the existing configurable lead-growing standardized noise (0.05 at lead 1, increasing 0.025 per day to 0.775 at lead 30). The assumed error distribution is not validated against operational weather forecasts. These results therefore establish only retrospective proxy-weather performance, not operational 30-day flood forecast accuracy.', '',
              'Past weather uses the same eight variables as the original weather-only LSTM, including CHIRPS rainfall; future rainfall is ERA5-Land. Product differences, short observed flow history, regulation, sparse extremes and previously inspected test years limit interpretation. Overlapping forecast windows are not independent samples. No observed past or future discharge is supplied to the LSTM.', '',
              'Persistence holds the last observation available at issue time. Climatology uses only training-period month/day means. Both are evaluated on exactly the same observed targets as the LSTM. Flow normalization and input mean filling use training years only; original target NaNs and source bytes are preserved.', '',
              'Synthetic tests establish code behavior only and are not accuracy evidence. Further 30-day architectures will be trained only after feedback on this run.', '',
              '![Lead-day skill](skill_by_lead.png)', '']
    (compare / 'comparison_report.md').write_text('\n'.join(report), encoding='utf-8')
    own = ['# Thirty-day LSTM observed test results', '', markdown(results.loc[results.model.eq('LSTM_30d'), cols]), '',
           markdown(grouped.loc[grouped.lead_day.eq(30) & grouped.model.eq('LSTM_30d')]), '',
           'Full methods, training measurements and limitations: ../../RUN_RESULTS.md. Cross-model comparison is outside model/ under evaluation comparison/model_30_days/.', '']
    (output / 'evaluation_report.md').write_text('\n'.join(own), encoding='utf-8')
    run_report = '\n'.join(report).replace('](skill_by_lead.png)', '](../../../../evaluation%20comparison/model_30_days/hindcast_forecast_lstm_scratch/skill_by_lead.png)')
    (Path(cfg['_root']) / 'RUN_RESULTS.md').write_text(run_report, encoding='utf-8')
    readme = Path(cfg['_root']) / 'README.md'
    if readme.exists():
        body = readme.read_text(encoding='utf-8').split('<!-- ACTUAL_RESULTS -->')[0]
        measured = results.loc[results.model.eq('LSTM_30d') & results.lead_day.isin(leads), cols]
        readme.write_text(body + '<!-- ACTUAL_RESULTS -->\n\n## Actual measured results\n\n' + markdown(measured) +
                          f'\n\nTraining: {manifest["training_seconds"]:.1f} seconds, {manifest["epochs"]} epochs, selected epoch {checkpoint["epoch"]}.\n\n'
                          + markdown(grouped.loc[grouped.model.eq('LSTM_30d') & grouped.lead_day.eq(30)]) + '\n\nSee RUN_RESULTS.md for baseline comparisons, calibration and limitations.\n', encoding='utf-8')
    print(results.loc[results.lead_day.isin(leads), cols].to_string(index=False), flush=True)
    print(f'Report: {compare / "comparison_report.md"}', flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    evaluate(load_config(parser.parse_args().config))
