"""Observed-only seasonal/lead verification, baseline comparison and calibration."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import argparse
import hashlib
import json
import pickle
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import yaml
from torch.utils.data import DataLoader

from baselines import Baselines
from data import DataStore, StreamflowDataset, inverse_flow, load_config, public_config, resolve, years
from model import HindcastForecastLSTM
from ensemble.model import ConvexEnsemble
from train import check_evaluation_years, device_for, load_checkpoint, seed_everything


def season_for(date):
    return 'Oct-Mar' if date.month in (10, 11, 12, 1, 2, 3) else 'Apr-Jun' if date.month in (4, 5, 6) else 'Jul-Sep'


def metrics(observed, predicted, peak_threshold, flood_threshold):
    observed, predicted = np.asarray(observed), np.asarray(predicted)
    n = len(observed)
    if not n:
        return {'n': 0}
    error = predicted - observed
    variance = np.sum((observed - observed.mean()) ** 2)
    nse = 1 - np.sum(error ** 2) / variance if variance > 0 else np.nan
    if n > 1 and observed.std() > 0 and predicted.std() > 0 and observed.mean() > 0:
        correlation = np.corrcoef(observed, predicted)[0, 1]
        kge = 1 - np.sqrt((correlation - 1) ** 2 + (predicted.std() / observed.std() - 1) ** 2 + (predicted.mean() / observed.mean() - 1) ** 2)
    else:
        kge = np.nan
    peak = (observed > peak_threshold) & (observed > 0)
    actual_flood, predicted_flood = observed > flood_threshold, predicted > flood_threshold
    hits = int((actual_flood & predicted_flood).sum())
    false = int((~actual_flood & predicted_flood).sum())
    return {'n': n, 'NSE': nse, 'KGE': kge, 'PBIAS_pct': 100 * error.sum() / observed.sum() if observed.sum() else np.nan,
            'RMSE_cumecs': np.sqrt(np.mean(error ** 2)), 'MAE_cumecs': np.abs(error).mean(),
            'peak_MAPE_pct': 100 * np.abs(error[peak] / observed[peak]).mean() if peak.any() else np.nan,
            'peak_n': int(peak.sum()), 'flood_hit_rate': hits / actual_flood.sum() if actual_flood.any() else np.nan,
            'false_alarm_rate': false / (~actual_flood).sum() if (~actual_flood).any() else np.nan,
            'false_alarm_ratio': false / predicted_flood.sum() if predicted_flood.any() else np.nan}


def markdown(frame):
    def value(x):
        if pd.isna(x):
            return 'NA'
        return f'{x:.3f}' if isinstance(x, (float, np.floating)) else str(x)
    return '\n'.join(['| ' + ' | '.join(frame.columns) + ' |', '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |']
                     + ['| ' + ' | '.join(value(x) for x in row) + ' |' for row in frame.itertuples(index=False, name=None)])


def predict_checkpoint(cfg, store, checkpoint, split='test', model_factory=None, dataset_factory=None):
    check_evaluation_years(cfg, checkpoint)
    dataset = (dataset_factory or StreamflowDataset)(store, split, checkpoint['statistics'])
    model = model_factory(cfg, dataset.dimensions(), checkpoint['statistics']) if model_factory else HindcastForecastLSTM(cfg, *dataset.dimensions())
    model.load_state_dict(checkpoint['model_state'])
    device = device_for(cfg)
    model.to(device).eval()
    outputs = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=cfg['training']['batch_size'], shuffle=False):
            output = model(*(batch[k].to(device) for k in ('history', 'future', 'static')))
            outputs.append(inverse_flow(output.cpu().numpy(), checkpoint['statistics']))
    prediction = np.concatenate(outputs)
    if not np.isfinite(prediction).all() or (np.diff(prediction, axis=-1) < -1e-8).any():
        raise FloatingPointError('Nonfinite or crossed predictive quantiles')
    return dataset, prediction


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoints', nargs='+')
    args = parser.parse_args()
    cfg = load_config(args.config)
    seed_everything(cfg['training']['seeds'][0], cfg['training']['cpu_threads'])
    paths = args.checkpoints
    if not paths:
        paths = json.loads((resolve(cfg, cfg['training']['output_dir']) / 'ensemble.json').read_text())['checkpoints']
    checkpoints = [load_checkpoint(path) for path in paths]
    for checkpoint in checkpoints:
        if checkpoint['config']['model']['quantiles'] != cfg['model']['quantiles']:
            raise ValueError('Evaluation quantiles differ from checkpoint')
        check_evaluation_years(cfg, checkpoint)
        if years(cfg['splits']['train']) != years(checkpoint['config']['splits']['train']):
            raise ValueError('Keep the checkpoint training range for a fair baseline comparison; fine-tune first to change it')
        if set(years(cfg['splits']['validation'])) & set(checkpoint['training_years']):
            raise ValueError('Ensemble validation years were used for LSTM training')
    store = DataStore(cfg)
    predictions = [predict_checkpoint(cfg, store, ck) for ck in checkpoints]
    dataset = predictions[0][0]
    if any(other.samples != dataset.samples for other, _ in predictions):
        raise ValueError('Ensemble members must predict identical sample dates')
    quantile_predictions = np.mean([p for _, p in predictions], axis=0)
    tau = cfg['model']['quantiles']
    median = quantile_predictions[:, :, tau.index(0.5)]
    out = resolve(cfg, cfg['evaluation']['output_dir'])
    out.mkdir(parents=True, exist_ok=True)
    baseline = Baselines().fit(store, checkpoints[0]['statistics'])
    (out / 'baselines.pkl').write_bytes(pickle.dumps(baseline))
    all_predictions = {'LSTM': median, **baseline.predict(dataset)}
    # Fit the heterogeneous ensemble on validation observations only.
    validation_predictions = [predict_checkpoint(cfg, store, ck, 'validation') for ck in checkpoints]
    validation_dataset = validation_predictions[0][0]
    validation_quantiles = np.mean([p for _, p in validation_predictions], axis=0)
    validation_models = {'LSTM': validation_quantiles[:, :, tau.index(0.5)], **baseline.predict(validation_dataset)}
    validation_targets = np.stack([validation_dataset.store.frames[b][cfg['data']['target_column']].iloc[i + 1:i + 1 + cfg['data']['forecast_horizon']].to_numpy()
                                   for b, i in validation_dataset.samples])
    blend = ConvexEnsemble(cfg['ensemble']).fit(validation_models, validation_targets)
    all_predictions['Ensemble'] = blend.predict(all_predictions)
    ensemble_output = resolve(cfg, cfg['ensemble']['output_dir'])
    ensemble_output.mkdir(parents=True, exist_ok=True)
    (ensemble_output / 'model.pkl').write_bytes(pickle.dumps(blend))
    (ensemble_output / 'config.yaml').write_text(yaml.safe_dump(public_config(cfg), sort_keys=False))
    (ensemble_output / 'weights.json').write_text(json.dumps({'members': blend.members, 'per_lead_weights': blend.weights,
                                                            'fit_years': years(cfg['splits']['validation']),
                                                            'fit_validation_weights': cfg['ensemble']['fit_validation_weights']}, indent=2) + '\n')
    training_years = years(cfg['splits']['train'])
    pooled = np.concatenate([frame.loc[frame.index.year.isin(training_years), cfg['data']['target_column']].dropna().to_numpy() for frame in store.frames.values()])
    thresholds = {}
    for basin, frame in store.frames.items():
        q = frame.loc[frame.index.year.isin(training_years), cfg['data']['target_column']].dropna().to_numpy()
        if not len(q):
            q = pooled
        thresholds[basin] = {'peak': float(np.quantile(q, cfg['evaluation']['peak_percentile'])),
                             'flood': cfg['evaluation']['flood_thresholds_cumecs'].get(basin, float(np.quantile(q, cfg['evaluation']['flood_percentile'])))}
    rows = []
    for index in range(len(dataset)):
        basin, position = dataset.samples[index]
        frame = store.frames[basin]
        issue = frame.index[position]
        for lead in range(cfg['data']['forecast_horizon']):
            day = issue + pd.Timedelta(days=lead + 1)
            row = {'basin_id': basin, 'issue_date': issue, 'target_date': day, 'lead_day': lead + 1,
                   'season': season_for(day), 'observed_cumecs': frame.loc[day, cfg['data']['target_column']]}
            row.update({name: values[index, lead] for name, values in all_predictions.items()})
            row.update({f'q{q:g}': quantile_predictions[index, lead, i] for i, q in enumerate(tau)})
            rows.append(row)
    table = pd.DataFrame(rows)
    table.to_csv(out / 'predictions.csv', index=False, na_rep='NaN')
    observed_table = table[table['observed_cumecs'].notna()]
    scores, calibration = [], []
    for (basin, lead, season), group in observed_table.groupby(['basin_id', 'lead_day', 'season']):
        for name in all_predictions:
            valid = group[np.isfinite(group[name])]
            scores.append({'basin_id': basin, 'lead_day': lead, 'season': season, 'model': name,
                           **metrics(valid['observed_cumecs'], valid[name], thresholds[basin]['peak'], thresholds[basin]['flood'])})
        lower, upper = group[f'q{tau[0]:g}'], group[f'q{tau[-1]:g}']
        calibration.append({'basin_id': basin, 'lead_day': lead, 'season': season, 'n': len(group),
                            'interval_nominal': tau[-1] - tau[0],
                            'interval_coverage': float(group['observed_cumecs'].between(lower, upper).mean()),
                            'mean_interval_width_cumecs': float((upper - lower).mean()),
                            **{f'empirical_q{q:g}': float((group['observed_cumecs'] <= group[f'q{q:g}']).mean()) for q in tau}})
    scores, calibration = pd.DataFrame(scores), pd.DataFrame(calibration)
    scores.to_csv(out / 'scores_by_season_and_lead.csv', index=False)
    calibration.to_csv(out / 'quantile_calibration.csv', index=False)
    overall = []
    for lead, group in observed_table.groupby('lead_day'):
        for name in all_predictions:
            valid = group[np.isfinite(group[name])]
            # Basin-specific thresholds are retained in seasonal tables; pooled overall errors only.
            overall.append({'lead_day': lead, 'model': name, **metrics(valid['observed_cumecs'], valid[name], np.inf, np.inf)})
    overall = pd.DataFrame(overall)
    overall.to_csv(out / 'scores_overall.csv', index=False)
    for name in all_predictions:
        component_output = out if name == 'Ensemble' else resolve(cfg, cfg['evaluation']['model_output_dirs'][name])
        component_output.mkdir(parents=True, exist_ok=True)
        scores[scores['model'].eq(name)].to_csv(component_output / 'model_scores_by_season_and_lead.csv', index=False)
        overall[overall['model'].eq(name)].to_csv(component_output / 'model_scores_overall.csv', index=False)
        columns = ['basin_id', 'issue_date', 'target_date', 'lead_day', 'season', 'observed_cumecs', name]
        if name == 'LSTM':
            columns.extend(f'q{q:g}' for q in tau)
            calibration.to_csv(component_output / 'quantile_calibration.csv', index=False)
        table[columns].to_csv(component_output / 'model_predictions.csv', index=False, na_rep='NaN')
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, group in overall.groupby('model'):
        axes[0].plot(group['lead_day'], group['NSE'], marker='o', label=name)
        axes[1].plot(group['lead_day'], group['RMSE_cumecs'], marker='o', label=name)
    axes[0].set(ylabel='NSE', xlabel='Lead day'); axes[1].set(ylabel='RMSE (m3/s)', xlabel='Lead day')
    axes[0].legend(fontsize=8); fig.tight_layout(); fig.savefig(out / 'skill_by_lead.png', dpi=180); plt.close(fig)
    target_years = sorted(observed_table['target_date'].dt.year.unique().tolist())
    unique_days = len(observed_table[['basin_id', 'target_date']].drop_duplicates())
    by_year = observed_table[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda x: x['target_date'].dt.year).groupby(['basin_id', 'year']).size().rename('observed_days').reset_index()
    availability = {}
    for split in cfg['splits']:
        ds = StreamflowDataset(store, split, checkpoints[0]['statistics'])
        available = [ds[i] for i in range(len(ds))]
        n = len(cfg['data']['forecast_columns'])
        availability[split] = {'samples': len(ds), 'target_values_observed': sum(int(x['mask'].sum()) for x in available),
                               'forecast_input_missing_pct': 100 * float(np.mean([x['future'][:, n:].numpy().mean() for x in available])),
                               'entire_forecast_window_missing_samples': sum(bool(x['future'][:, n:].bool().all()) for x in available)}
    manifest = {'test_years_used': target_years, 'unique_observed_basin_days': unique_days,
                'observed_forecast_target_pairs': len(observed_table), 'availability': availability,
                'checkpoint_paths': paths, 'training_years_ever_used': sorted(set(y for ck in checkpoints for y in ck['training_years'])),
                'selection_years_ever_used': sorted(set(y for ck in checkpoints for y in ck['selection_years'])),
                'forecast_mode': cfg['data']['forecast_mode'], 'thresholds': thresholds,
                'daily_file_sha256': hashlib.sha256(resolve(cfg, cfg['data']['daily_file']).read_bytes()).hexdigest(),
                'ensemble_fit_years': years(cfg['splits']['validation']), 'ensemble_members': blend.members,
                'ensemble_weights': blend.weights,
                'no_discharge_filled': True, 'lstm_seed_members': len(checkpoints)}
    (out / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    limitation = ('**Forecast-input stand-in experiment:** future ERA5-Land realized weather plus lead-dependent Gaussian noise was used. These are real held-out discharge scores conditioned on a stand-in forecast, NOT operational TIGGE/GFS forecast skill.'
                  if cfg['data']['forecast_mode'] == 'reanalysis_with_noise' else 'Archived-forecast mode: inspect the saved issue-time schema, variable coverage and publication latency before operational use.')
    report = ['# Marala hindcast-forecast model evaluation', '', limitation, '',
              f'Observed test years: {target_years}. Unique observed basin-days scored: **{unique_days}**. Observed issue/lead/target pairs: {len(observed_table)}. No missing target was scored or filled.', '',
              f'Training years ever used: {manifest["training_years_ever_used"]}. Validation/selection years ever used: {manifest["selection_years_ever_used"]}. Test years were checked against both lists.', '',
              markdown(by_year), '', '## Models compared', '',
              'LSTM uses median quantiles. Persistence deliberately uses the latest observed discharge available at issue time even when past-Q input is disabled for the LSTM. Climatology uses training month/day means, with training basin/global mean fallback. Gradient boosting uses the same normalized predictor/missingness channels and forecast prefix, summarized over configurable history windows; it is not given future observed discharge.', '',
              f'The heterogeneous Ensemble combines {blend.members} with nonnegative normalized per-lead weights fitted on validation years {years(cfg["splits"]["validation"])} only. No test observation is used for those weights. Saved weights: {cfg["ensemble"]["output_dir"]}/weights.json. It is a point-forecast blend; quantile calibration below is for the LSTM, not a claimed probabilistic ensemble.', '',
              markdown(overall[['lead_day', 'model', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs', 'MAE_cumecs']]), '',
              '## Seasonal lead-by-lead verification', '', markdown(scores), '',
              'Peak MAPE applies to observed days above training-basin Q95 (or configured percentile). Default flood thresholds are training Q95, not official flood categories. Hit rate = hits/observed exceedances. False-alarm rate = false alerts/observed non-exceedances; false-alarm ratio = false alerts/all alerts. NA means an undefined denominator. These count daily exceedances, not independent flood events.', '',
              '## Quantile calibration', '', markdown(calibration), '',
              'With default quantiles, 0.05-0.95 interval nominal coverage is 0.90. Quantile ordering is enforced structurally; calibration is measured, not guaranteed. Multiple seeds use the arithmetic mean of member quantile forecasts, not exact mixture-distribution quantiles.', '',
              '## Data availability', '', markdown(pd.DataFrame(availability).T.reset_index(names='split')), '',
              'Only all-missing target windows are excluded, apart from required history/calendar/split boundaries. Missing inputs remain explicitly flagged and receive transformed training-mean predictor values; a sample can consequently contain entirely unavailable forecast inputs. Future reanalysis availability, source latency and WAPDA reading-time uncertainty remain material limitations.', '',
              '## Known limits', '',
              'Short single-basin record; sparse independent extremes; overlapping target windows; regulation and diversions not modeled. Static climatological attributes may encode post-training years unless reconstructed appropriately. Archived forecasts can differ systematically from noisy reanalysis. No synthetic test result is evidence of real accuracy. No accuracy is guaranteed on a new basin or period.', '',
              'The 2022-2024 period has been inspected in earlier workspace experiments; it is held out from this run, but is not an untouched research holdout across the entire project history.', '',
              '![Skill by lead](skill_by_lead.png)', '', 'Full observed/predicted pairs, seasonal metrics, calibration and thresholds are saved alongside this report.']
    (out / 'evaluation_report.md').write_text('\n'.join(report) + '\n')
    print(overall[['lead_day', 'model', 'n', 'NSE', 'KGE', 'RMSE_cumecs']].to_string(index=False), flush=True)
    print(f'Report: {out / "evaluation_report.md"}', flush=True)


if __name__ == '__main__':
    main()
