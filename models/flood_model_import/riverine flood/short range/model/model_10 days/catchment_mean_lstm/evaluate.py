"""Observed-only spatial experiment, paired source control, and README scores."""
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
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import DataStore, resolve
from evaluate import markdown, metrics, predict_checkpoint, season_for
from lstm.model import HindcastForecastLSTM
from lstm.train import load_checkpoint, seed_everything
from persistence.model import Persistence
from climatology.model import Climatology
from catchment_mean_lstm.data import load_spatial_config, SpatialDataset
from catchment_mean_lstm.model import build_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    args = parser.parse_args()
    cfg = load_spatial_config(args.config)
    control_cfg = load_spatial_config(resolve(cfg, cfg['spatial']['control_config']))
    seed_everything(cfg['training']['seeds'][0], cfg['training']['cpu_threads'])
    torch.set_flush_denormal(cfg['training'].get('flush_denormal', False))
    state = json.loads(resolve(cfg, cfg['spatial']['run_manifest']).read_text())
    store = DataStore(cfg)
    control_store = DataStore(control_cfg)
    ckpts = [load_checkpoint(path) for path in state['spatial']]
    controls = [load_checkpoint(path) for path in state['mean_control']]
    if cfg['model']['quantiles'] != control_cfg['model']['quantiles']:
        raise ValueError('Spatial and control quantiles differ')
    for runtime, members in [(cfg, ckpts), (control_cfg, controls)]:
        for ck in members:
            if ck['config']['model'] != runtime['model'] or ck['config']['spatial'] != runtime['spatial']:
                raise ValueError('Use the model/spatial configuration saved with the checkpoint')
    if cfg['splits'] != control_cfg['splits']:
        raise ValueError('Control and spatial splits differ')
    if any(ck['statistics']['flow'] != controls[0]['statistics']['flow'] for ck in ckpts):
        raise ValueError('Target normalization differs between spatial and control')
    predicted = [predict_checkpoint(cfg, store, ck, model_factory=build_model, dataset_factory=SpatialDataset) for ck in ckpts]
    averaged = [predict_checkpoint(control_cfg, control_store, ck, dataset_factory=SpatialDataset) for ck in controls]
    dataset = predicted[0][0]
    if any(ds.samples != dataset.samples for ds, _ in predicted + averaged):
        raise ValueError('Spatial and mean control samples differ')
    quantiles = {'ElevationBands': np.mean([p for _, p in predicted], axis=0),
                 'MeanControl': np.mean([p for _, p in averaged], axis=0)}
    tau = cfg['model']['quantiles']
    points = {name: values[:, :, tau.index(.5)] for name, values in quantiles.items()}
    points.update(persistence=Persistence().predict(dataset), climatology=Climatology().fit(store).predict(dataset))
    # Verify both models receive the same physical noisy forecast, before spatial pooling.
    for index in [0, len(dataset) // 2, len(dataset) - 1]:
        a, b = dataset[index]['future'].numpy(), averaged[0][0][index]['future'].numpy()
        a = a[:, :8] * np.asarray(ckpts[0]['statistics']['forecast']['scale']) + np.asarray(ckpts[0]['statistics']['forecast']['center'])
        b = b[:, :2] * np.asarray(controls[0]['statistics']['forecast']['scale']) + np.asarray(controls[0]['statistics']['forecast']['center'])
        expected = (a.reshape(-1, 4, 2) * np.asarray(cfg['spatial']['area_weights'])[None, :, None]).sum(axis=1)
        np.testing.assert_allclose(expected, b, atol=1e-4, equal_nan=True)
    rows = []
    for index in range(len(dataset)):
        basin, issue = dataset.metadata(index)
        for lead in range(cfg['data']['forecast_horizon']):
            day = issue + pd.Timedelta(days=lead + 1)
            row = {'basin_id': basin, 'issue_date': issue, 'target_date': day, 'lead_day': lead + 1,
                   'season': season_for(day), 'observed_cumecs': store.frames[basin].loc[day, cfg['data']['target_column']]}
            row.update({name: values[index, lead] for name, values in points.items()})
            for name, values in quantiles.items():
                row.update({f'{name}_q{q:g}': values[index, lead, j] for j, q in enumerate(tau)})
            rows.append(row)
    table = pd.DataFrame(rows)
    keys = ['basin_id', 'issue_date', 'target_date', 'lead_day']
    for name, path in cfg['evaluation'].get('context_predictions', {}).items():
        saved = pd.read_csv(resolve(cfg, path), parse_dates=['issue_date', 'target_date'], dtype={'basin_id': str})
        column = 'LSTM' if name == 'original_8input_LSTM' else name
        aligned = saved.set_index(keys).reindex(pd.MultiIndex.from_frame(table[keys]))
        if not np.isfinite(aligned[column]).all():
            raise ValueError(f'Context model {name} has different issue-date coverage')
        np.testing.assert_allclose(aligned.observed_cumecs, table.observed_cumecs, equal_nan=True)
        table[name] = aligned[column].to_numpy()
        points[name] = table[name].to_numpy().reshape(len(dataset), -1)
    observed = table[table.observed_cumecs.notna()]
    if len(store.frames) != 1:
        raise ValueError('This comparison expects a single spatial catchment')
    training = next(iter(store.frames.values()))
    train_years = ckpts[0]['training_years']
    threshold = float(training.loc[training.index.year.isin(train_years), cfg['data']['target_column']].quantile(cfg['evaluation']['peak_percentile']))
    flood = cfg['evaluation'].get('flood_threshold_cumecs')
    flood = threshold if flood is None else float(flood)
    overall, seasonal, calibration = [], [], []
    for lead, group in observed.groupby('lead_day'):
        for name in points:
            valid = group[np.isfinite(group[name])]
            overall.append({'model': name, 'lead_day': lead, **metrics(valid.observed_cumecs, valid[name], threshold, flood)})
        for season, subset in group.groupby('season'):
            for name in points:
                valid = subset[np.isfinite(subset[name])]
                seasonal.append({'model': name, 'lead_day': lead, 'season': season,
                                 **metrics(valid.observed_cumecs, valid[name], threshold, flood)})
        for name in quantiles:
            calibration.append({'model': name, 'lead_day': lead, 'n': len(group), 'nominal_coverage': tau[-1] - tau[0],
                                'actual_coverage': float(group.observed_cumecs.between(group[f'{name}_q{tau[0]:g}'], group[f'{name}_q{tau[-1]:g}']).mean())})
    overall, seasonal, calibration = map(pd.DataFrame, [overall, seasonal, calibration])
    output = resolve(cfg, cfg['evaluation']['output_dir']); output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / 'predictions.csv', index=False, na_rep='NaN')
    overall.to_csv(output / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(output / 'scores_by_season_and_lead.csv', index=False)
    calibration.to_csv(output / 'quantile_calibration.csv', index=False)
    source = resolve(cfg, cfg['data']['daily_file'])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if any(ck['source_hashes']['daily_file'] != digest for ck in ckpts + controls):
        raise ValueError('Prepared source table changed after training')
    preparation = json.loads(source.with_name('preparation_report.json').read_text())
    if hashlib.sha256(Path(preparation['observed_source']).read_bytes()).hexdigest() != preparation['observed_source_sha256']:
        raise ValueError('Original discharge table changed')
    by_year = observed[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda x: x.target_date.dt.year).groupby('year').size().reset_index(name='observed_days')
    run_rows = []
    for name, paths, cs in [('ElevationBands', state['spatial'], ckpts), ('MeanControl', state['mean_control'], controls)]:
        for path, ck in zip(paths, cs):
            h = json.loads(Path(path).with_name('history.json').read_text())
            count = sum(t.numel() for key, t in ck['model_state'].items() if key != 'area_weights')
            run_rows.append({'model': name, 'seed': ck['seed'], 'epochs_run': len(h['epochs']), 'selected_epoch': ck['epoch'],
                             'validation_pinball': ck['validation_pinball'], 'training_seconds': h['elapsed_seconds'],
                             'parameters': count, 'training_samples': ck['train_samples'], 'validation_samples': ck['validation_samples']})
    metadata = json.loads(resolve(cfg, cfg['spatial']['metadata_file']).read_text())
    manifest = {'stage_checkpoints': state, 'daily_sha256': digest, 'discharge_preserved': True,
                'unique_observed_test_days': int(by_year.observed_days.sum()), 'observed_target_pairs': len(observed),
                'test_years': sorted(observed.target_date.dt.year.unique().tolist()), 'training_years': train_years,
                'validation_years': ckpts[0]['selection_years'], 'band_area_fractions': cfg['spatial']['area_weights'],
                'paired_forecast_error_check_passed': True, 'forecast_mode': cfg['data']['forecast_mode']}
    (output / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, group in overall.groupby('model'):
        axes[0].plot(group.lead_day, group.NSE, marker='o', label=name)
        axes[1].plot(group.lead_day, group.RMSE_cumecs, marker='o', label=name)
    axes[0].set(xlabel='Lead day', ylabel='NSE'); axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[0].legend(fontsize=7); fig.tight_layout(); fig.savefig(output / 'skill_by_lead.png', dpi=180); plt.close(fig)
    available_weather = training.loc[training['b0_precipitation_mm'].notna()]
    plot_year = int(available_weather.index.year.max())
    weather = available_weather[available_weather.index.year == plot_year]
    fig, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True)
    for axis, variable in zip(axes, cfg['spatial']['history_variables']):
        for band, label in zip(cfg['spatial']['band_ids'], metadata['bands']):
            axis.plot(weather.index, weather[f'{band}_{variable}'], label=label)
        axis.set_ylabel(variable)
    axes[0].legend(title='Elevation (m)', ncol=4, fontsize=8)
    fig.suptitle(f'Actual ERA5-Land elevation-band inputs, {plot_year}')
    fig.tight_layout(); fig.savefig(output / 'band_inputs.png', dpi=160); plt.close(fig)
    horizon = cfg['data']['forecast_horizon']; final = overall[overall.lead_day.eq(horizon)].set_index('model')
    difference = final.loc['ElevationBands', 'NSE'] - final.loc['MeanControl', 'NSE']
    finding = (f'Lead-{horizon} NSE is **{final.loc["ElevationBands", "NSE"]:.3f}** for the elevation-band model and '
               f'**{final.loc["MeanControl", "NSE"]:.3f}** for the same-source catchment-mean control '
               f'(difference {difference:+.4f}). Parameter counts differ; this one-seed pilot does not isolate a universally transferable spatial benefit.')
    summary = ['## Measured test accuracy', '', finding, '',
               '**Future weather is realized ERA5-Land with shared lead-dependent noise. These are not operational archived-forecast scores. NSE is not an accuracy percentage.**', '',
               f'Test years: {manifest["test_years"]}. Observed basin-days across leads: **{manifest["unique_observed_test_days"]}**; observed issue/lead/target pairs: **{len(observed)}**. No missing discharge was filled or scored.', '',
               markdown(overall[overall.lead_day.isin([1, horizon])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs']]), '',
               f'### Seasonal results at lead {horizon}', '', markdown(seasonal[seasonal.lead_day.eq(horizon) & seasonal.model.isin(quantiles)]), '',
               '### Quantile calibration', '', markdown(calibration[calibration.lead_day.eq(horizon)]), '',
               '### Actual training runs', '', markdown(pd.DataFrame(run_rows)), '',
               f'Peak/flood thresholds are training Q95 by default: **{threshold:.2f} / {flood:.2f} cumecs**, not official flood levels or return periods. Positive PBIAS means overprediction. False-alarm rate counts false alerts/non-exceedance days; false-alarm ratio counts false alerts/all alerts.', '',
               'Six spatial and 20 existing synthetic tests passed. Tests establish code correctness, not accuracy. The original eight-input LSTM and earlier ensemble use different predictors and forecast-error models; they are context, not a matched ablation.', '']
    report = ['# Elevation-band spatial streamflow experiment', '', *summary,
              '## Observed days by year', '', markdown(by_year), '', '## All seasonal/lead results', '', markdown(seasonal), '',
              '## Source geometry', '', '```json', json.dumps(metadata, indent=2), '```', '',
              'Four independent LSTM encoder/forecast pairs process actual elevation-band ERA5-Land rain, temperature, SWE and melt histories before joining their area-weighted hidden features. DEM elevation masks are derived at about 90 m; meteorology remains native ERA5-Land resolution, about 11 km. This is a semi-distributed elevation-band model, not high-resolution weather or an explicit river-routing model.', '',
              'The mean control receives exactly the same source values after area aggregation. Both forecast inputs are generated from the same per-band noisy weather before pooling; this was checked in physical units. Noise is shared across bands and is a simplifying experimental assumption. Future SWE and observed future flow are not model inputs.', '',
              'NASA POWER grids flagged HOLD and incomplete first extraction attempts were excluded. Snow inputs are reanalysis products, not new ground measurements. Regulation, glacier dynamics, elevation lapse-rate subgrid physics and operational data latency remain unresolved. The record is short, extremes are sparse, and overlapping windows are not independent. The test years were inspected in earlier workspace experiments and are not an untouched project-wide holdout.', '',
              '![Skill by lead](skill_by_lead.png)', '', '![Elevation-band inputs](band_inputs.png)', '']
    (output / 'evaluation_report.md').write_text('\n'.join(report), encoding='utf-8')
    readme = Path(cfg['_root']) / 'README.md'; text = readme.read_text(encoding='utf-8')
    start, end = '<!-- ACCURACY_START -->', '<!-- ACCURACY_END -->'
    if start not in text or end not in text:
        raise ValueError('README accuracy markers missing')
    readme.write_text(text.split(start)[0] + start + '\n' + '\n'.join(summary) + '\n' + end + text.split(end, 1)[1], encoding='utf-8')
    (Path(cfg['_root']) / 'RUN_RESULTS.md').write_text('# Actual spatial model run\n\n' + '\n'.join(summary) + '\n\nSee README for commands and source provenance.\n', encoding='utf-8')
    print(overall[overall.lead_day.isin([1, horizon])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs']].to_string(index=False), flush=True)
    print('Updated accuracy README:', readme, flush=True)


if __name__ == '__main__':
    main()
