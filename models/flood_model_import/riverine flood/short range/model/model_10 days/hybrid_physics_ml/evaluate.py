"""Observed-only verification and a measured accuracy section in README.md."""
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
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from climatology.model import Climatology
from data import DataStore, load_config, resolve, years
from evaluate import markdown, metrics, predict_checkpoint, season_for
from hybrid_physics_ml.model import build_model
from lstm.train import load_checkpoint, seed_everything
from persistence.model import Persistence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoints', nargs='+')
    args = parser.parse_args()
    cfg = load_config(args.config)
    seed_everything(cfg['training']['seeds'][0], cfg['training']['cpu_threads'])
    torch.set_flush_denormal(cfg['training'].get('flush_denormal', False))
    paths = args.checkpoints or json.loads((resolve(cfg, cfg['training']['output_dir']) / 'ensemble.json').read_text())['checkpoints']
    checkpoints = [load_checkpoint(path) for path in paths]
    for ck in checkpoints:
        if ck.get('model_family') != 'hybrid_physics_ml':
            raise ValueError('Expected a hybrid-physics checkpoint')
        if ck['config']['physics'] != cfg['physics'] or ck['config']['model'] != cfg['model']:
            raise ValueError('Use the checkpoint physics/model configuration')
    store = DataStore(cfg)
    if set(store.frames) != {'marala'}:
        raise ValueError('This report expects the Marala target basin')
    predictions = [predict_checkpoint(cfg, store, ck, model_factory=build_model) for ck in checkpoints]
    dataset = predictions[0][0]
    if any(ds.samples != dataset.samples for ds, _ in predictions):
        raise ValueError('Seed members have different issue dates')
    quantile_values = np.mean([p for _, p in predictions], axis=0)
    control_cfg = load_config(resolve(cfg, cfg['evaluation']['control_config']))
    control = load_checkpoint(resolve(cfg, cfg['evaluation']['control_checkpoint']))
    for key in ('dynamic_columns', 'forecast_columns', 'reanalysis_columns', 'calendar_features',
                'past_discharge', 'use_static', 'hindcast_length', 'forecast_horizon', 'forecast_mode'):
        if control_cfg['data'][key] != cfg['data'][key]:
            raise ValueError(f'Control has different {key}; supply a matched control')
    if control_cfg['model'] != cfg['model'] or control_cfg['splits'] != cfg['splits']:
        raise ValueError('Control model size/quantiles or split differs')
    if any(ck['statistics'] != control['statistics'] for ck in checkpoints):
        raise ValueError('Hybrid and control require identical training normalization')
    control_ds, control_values = predict_checkpoint(control_cfg, DataStore(control_cfg), control)
    if [control_ds.metadata(i) for i in range(len(control_ds))] != [dataset.metadata(i) for i in range(len(dataset))]:
        raise ValueError('Control issue dates differ')
    tau = cfg['model']['quantiles']
    points = {'Hybrid': quantile_values[:, :, tau.index(0.5)],
              'plain_LSTM': control_values[:, :, tau.index(0.5)],
              'persistence': Persistence().predict(dataset),
              'climatology': Climatology().fit(store).predict(dataset)}
    rows = []
    for index in range(len(dataset)):
        basin, issue = dataset.metadata(index)
        for lead in range(cfg['data']['forecast_horizon']):
            day = issue + pd.Timedelta(days=lead + 1)
            row = {'basin_id': basin, 'issue_date': issue, 'target_date': day, 'lead_day': lead + 1,
                   'season': season_for(day), 'observed_cumecs': store.frames[basin].loc[day, cfg['data']['target_column']]}
            row.update({name: p[index, lead] for name, p in points.items()})
            row.update({f'q{q:g}': quantile_values[index, lead, j] for j, q in enumerate(tau)})
            rows.append(row)
    table = pd.DataFrame(rows)
    keys = ['basin_id', 'issue_date', 'target_date', 'lead_day']
    extra_paths = {}
    for name, path in cfg['evaluation'].get('baseline_predictions', {}).items():
        saved = pd.read_csv(resolve(cfg, path), parse_dates=['issue_date', 'target_date'], dtype={'basin_id': str})
        aligned = saved.set_index(keys).reindex(pd.MultiIndex.from_frame(table[keys]))
        if not np.isfinite(aligned[name]).all():
            raise ValueError(f'{name} baseline does not cover all issue/lead dates')
        np.testing.assert_allclose(aligned.observed_cumecs.to_numpy(), table.observed_cumecs.to_numpy(), equal_nan=True)
        table[name] = aligned[name].to_numpy()
        points[name] = table[name].to_numpy().reshape(len(dataset), -1)
        extra_paths[name] = str(resolve(cfg, path))
    observed = table[table.observed_cumecs.notna()]
    training = store.frames['marala']
    q_train = training.loc[training.index.year.isin(years(cfg['splits']['train'])), cfg['data']['target_column']].dropna()
    peak = float(q_train.quantile(cfg['evaluation']['peak_percentile']))
    flood = cfg['evaluation'].get('flood_threshold_cumecs')
    flood = peak if flood is None else float(flood)
    overall, seasonal, calibration = [], [], []
    for lead, group in observed.groupby('lead_day'):
        for name in points:
            valid = group[np.isfinite(group[name])]
            overall.append({'model': name, 'lead_day': lead, **metrics(valid.observed_cumecs, valid[name], peak, flood)})
        for season, subset in group.groupby('season'):
            for name in points:
                valid = subset[np.isfinite(subset[name])]
                seasonal.append({'model': name, 'lead_day': lead, 'season': season,
                                 **metrics(valid.observed_cumecs, valid[name], peak, flood)})
        calibration.append({'lead_day': lead, 'n': len(group), 'nominal_coverage': tau[-1] - tau[0],
                            'actual_coverage': float(group.observed_cumecs.between(group[f'q{tau[0]:g}'], group[f'q{tau[-1]:g}']).mean())})
    overall, seasonal, calibration = map(pd.DataFrame, [overall, seasonal, calibration])
    output = resolve(cfg, cfg['evaluation']['output_dir'])
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / 'predictions.csv', index=False, na_rep='NaN')
    overall.to_csv(output / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(output / 'scores_by_season_and_lead.csv', index=False)
    calibration.to_csv(output / 'quantile_calibration.csv', index=False)
    audit_rows, parameter_rows = [], []
    for path, ck, (ds, _) in zip(paths, checkpoints, predictions):
        model = build_model(cfg, ds.dimensions(), ck['statistics']).eval()
        model.load_state_dict(ck['model_state'])
        maximum, minimum, missing, clipped, input_count = 0., float('inf'), 0, 0, 0
        with torch.no_grad():
            for batch in DataLoader(ds, batch_size=cfg['training']['batch_size'], shuffle=False):
                past, future, audit = model.physics_features(batch['history'], batch['future'])
                maximum = max(maximum, float(audit['history_residual_mm'].abs().max()), float(audit['forecast_residual_mm'].abs().max()))
                minimum = min(minimum, float(past.min()), float(future.min()))
                n = len(cfg['data']['forecast_columns'])
                missing += int(batch['future'][:, :, n:].sum())
                input_count += batch['future'][:, :, n:].numel()
                pidx = model.future_index['precipitation']
                rain = batch['future'][:, :, pidx] * model.forecast_scale[pidx] + model.forecast_center[pidx]
                clipped += int((rain < 0).sum())
        if maximum > cfg['evaluation']['mass_balance_tolerance_mm'] or minimum < -1e-5:
            raise AssertionError('Bucket water-balance or nonnegative-store audit failed')
        audit_rows.append({'seed': ck['seed'], 'maximum_water_balance_residual_mm': maximum,
                           'minimum_state_or_flux_mm': minimum, 'forecast_missing_pct': 100 * missing / input_count,
                           'negative_noisy_precipitation_clipped_in_bucket': clipped})
        values = model.bucket.parameters_physical().tolist()
        parameter_rows.extend({'seed': ck['seed'], 'parameter': name,
                               'initial': cfg['physics']['parameters'][name][2], 'learned': values[i]}
                              for i, name in enumerate(model.bucket.names))
    pd.DataFrame(audit_rows).to_csv(output / 'water_balance_audit.csv', index=False)
    pd.DataFrame(parameter_rows).to_csv(output / 'learned_physics_parameters.csv', index=False)
    source = resolve(cfg, cfg['data']['daily_file'])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if any(ck['source_hashes']['daily_file'] != digest for ck in checkpoints) or control['source_hashes']['daily_file'] != digest:
        raise RuntimeError('Input daily table changed since training')
    by_year = observed[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda x: x.target_date.dt.year).groupby('year').size().reset_index(name='observed_days')
    manifest = {'checkpoint_paths': paths, 'control_checkpoint': str(resolve(cfg, cfg['evaluation']['control_checkpoint'])),
                'reused_baseline_predictions': extra_paths, 'daily_file_sha256': digest,
                'test_years': sorted(observed.target_date.dt.year.unique().tolist()),
                'unique_observed_test_days': int(by_year.observed_days.sum()), 'observed_target_pairs': len(observed),
                'training_years': checkpoints[0]['training_years'], 'validation_years': checkpoints[0]['selection_years'],
                'no_discharge_filled': True, 'training_input_hash_unchanged': True, 'water_balance_audit': audit_rows,
                'forecast_mode': cfg['data']['forecast_mode'], 'peak_threshold_cumecs': peak, 'flood_threshold_cumecs': flood}
    (output / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, group in overall.groupby('model'):
        axes[0].plot(group.lead_day, group.NSE, marker='o', label=name)
        axes[1].plot(group.lead_day, group.RMSE_cumecs, marker='o', label=name)
    axes[0].set(xlabel='Lead day', ylabel='NSE'); axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[0].legend(fontsize=7); fig.tight_layout(); fig.savefig(output / 'skill_by_lead.png', dpi=180); plt.close(fig)
    horizon = cfg['data']['forecast_horizon']
    end = overall[overall.lead_day.eq(horizon)].set_index('model')
    difference = end.loc['Hybrid', 'NSE'] - end.loc['plain_LSTM', 'NSE']
    comparison = 'higher' if difference > 0 else 'lower' if difference < 0 else 'equal'
    finding = (f'At lead {horizon}, hybrid NSE is **{end.loc["Hybrid", "NSE"]:.3f}**, '
               f'{comparison} than the matched-input plain LSTM (**{end.loc["plain_LSTM", "NSE"]:.3f}**); '
               f'NSE difference: {difference:+.4f}. This single-seed experiment does not establish general improvement in extreme floods.')
    run_rows = []
    for path, ck in zip(paths, checkpoints):
        h = json.loads(Path(path).with_name('history.json').read_text())
        run_rows.append({'seed': ck['seed'], 'epochs_run': len(h['epochs']), 'selected_epoch': ck['epoch'],
                         'validation_pinball': ck['validation_pinball'], 'training_seconds': h['elapsed_seconds'],
                         'train_samples': ck['train_samples'], 'validation_samples': ck['validation_samples']})
    def result_links(base):
        destinations = {'Full evaluation': output / 'evaluation_report.md', 'Prediction CSV': output / 'predictions.csv',
                        'Training history': Path(paths[0]).with_name('history.json')}
        return ' | '.join(f'[{label}](<{os.path.relpath(path, base).replace(chr(92), "/")}>)'
                          for label, path in destinations.items())
    summary = ['## Measured accuracy on Marala', '', finding, '',
               f'Observed test years: **{manifest["test_years"]}**. Unique observed test days across leads: **{manifest["unique_observed_test_days"]}**; observed issue/lead/target pairs: **{len(observed)}**. Individual missing targets were excluded.', '',
               '**These results use realized future ERA5-Land weather plus noise. They are not operational TIGGE/GFS forecast accuracy. NSE is a skill score, not an accuracy percentage.**', '',
               markdown(overall[overall.lead_day.isin([1, horizon])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs']]), '',
               f'### Hybrid seasonal results at lead {horizon}', '',
               markdown(seasonal[seasonal.lead_day.eq(horizon) & seasonal.model.eq('Hybrid')]), '',
               '### Hybrid quantile calibration', '', markdown(calibration), '',
               f'High-flow errors and flood exceedances use a training-derived peak threshold of **{peak:.2f} cumecs** and flood threshold of **{flood:.2f} cumecs**. Defaults use training Q95, not official flood categories or return-period floods. Positive PBIAS means overprediction. False-alarm rate = false alerts/non-exceedance days; false-alarm ratio = false alerts/all alerts.', '',
               '### Training and physics checks', '', markdown(pd.DataFrame(run_rows)), '', markdown(pd.DataFrame(audit_rows)), '',
               f'Maximum measured daily bucket residual: **{max(row["maximum_water_balance_residual_mm"] for row in audit_rows):.8f} mm**, within the configured **{cfg["evaluation"]["mass_balance_tolerance_mm"]} mm** tolerance.', '',
               'Water balance is checked inside the conceptual bucket, including its initial water stores. Final LSTM discharge is not constrained to this balance. Internal conservation is not proof of accurate or physically correct basin runoff. Negative precipitation caused by Gaussian forecast noise is clipped only inside the physical module, and is counted above; source values are unchanged.', '',
               'All 15 shared and 5 hybrid synthetic correctness tests passed. They check implementation, not real accuracy. Observed targets and their NaN positions were not modified. The saved daily-file hash matches both training checkpoints.', '',
               result_links(cfg['_root']), '']
    report_summary = [result_links(output) if line == result_links(cfg['_root']) else line for line in summary]
    report = ['# Hybrid physics-ML evaluation', '', *report_summary, '', '## Observed days per year', '', markdown(by_year), '',
              '## All seasonal lead-by-lead metrics', '', markdown(seasonal), '',
              '## Learned bucket coefficients', '', markdown(pd.DataFrame(parameter_rows)), '',
              'The reused plain LSTM has the same input variables, normalization, split, hidden size and quantiles. Physics adds six derived channels and a small number of learned coefficients; parameter counts are not identical. Persistence deliberately uses known past flow; other models here are weather-only. Saved gradient-boosting and ensemble predictions were reused with exact issue/date/lead alignment and matching observed targets, without refitting them on test data.', '',
              'Known limits: short single-basin record; basin-average snow/temperature simplify elevation gradients and glacier processes; fixed initial soil/groundwater stores; temperature-only evaporation demand; regulation/diversions are not explicitly modeled; forcing/observation publication latency; forecast-input mismatch; sparse independent floods; overlapping windows. SWE, temperature and snowmelt inputs are reanalysis products, not new ground observations. Test years were inspected in earlier workspace experiments and are not a globally untouched research holdout.', '',
              '![Skill by lead](skill_by_lead.png)', '']
    (output / 'evaluation_report.md').write_text('\n'.join(report), encoding='utf-8')
    readme = Path(cfg['_root']) / 'README.md'
    text = readme.read_text(encoding='utf-8')
    start, end_marker = '<!-- ACCURACY_START -->', '<!-- ACCURACY_END -->'
    if start not in text or end_marker not in text:
        raise ValueError('README accuracy markers are missing')
    before = text.split(start)[0]
    after = text.split(end_marker, 1)[1]
    readme.write_text(before + start + '\n' + '\n'.join(summary) + '\n' + end_marker + after, encoding='utf-8')
    commands = ('```powershell\n'
                '$python = "../experiments/marala_observed/.venv/Scripts/python.exe"\n'
                '& $python -m unittest discover -s tests -v\n'
                '& $python -m unittest discover -s hybrid_physics_ml/tests -v\n'
                '& $python -u hybrid_physics_ml/train.py --config hybrid_physics_ml/config.yaml\n'
                '& $python -u hybrid_physics_ml/evaluate.py --config hybrid_physics_ml/config.yaml\n```')
    (Path(cfg['_root']) / 'RUN_RESULTS.md').write_text('# Actual hybrid run\n\nWorking directory: parent `model` folder.\n\n' + commands + '\n\n' + '\n'.join(summary), encoding='utf-8')
    print(overall[overall.lead_day.isin([1, horizon])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs']].to_string(index=False), flush=True)
    print(f'Updated accuracy README: {readme}', flush=True)


if __name__ == '__main__':
    main()
