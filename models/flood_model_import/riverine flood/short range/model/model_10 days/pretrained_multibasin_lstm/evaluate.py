"""Observed Marala verification against a matched from-scratch control."""
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
import importlib.metadata
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from climatology.model import Climatology
from data import DataStore, load_config, years
from evaluate import markdown, metrics, predict_checkpoint, season_for
from lstm.train import load_checkpoint, seed_everything
from persistence.model import Persistence
from pretrained_multibasin_lstm.download_data import workflow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('workflow.yaml')))
    args = parser.parse_args()
    w = workflow(args.config)
    root = w['_root']
    state = json.loads((root / w['stages']['manifest']).read_text())
    cfg = load_config(root / w['stages']['finetune_config'])
    seed_everything(cfg['training']['seeds'][0], cfg['training']['cpu_threads'])
    store = DataStore(cfg)
    if set(store.frames) != {'marala'}:
        raise ValueError('This comparison report expects the Marala target basin only')
    checkpoints = {name: load_checkpoint(state[stage]) for name, stage in
                   [('pretrained_only', 'pretrain'), ('finetuned', 'finetune'), ('scratch', 'scratch')]}
    predictions = {name: predict_checkpoint(cfg, store, checkpoint) for name, checkpoint in checkpoints.items()}
    dataset = predictions['finetuned'][0]
    if any(ds.samples != dataset.samples for ds, _ in predictions.values()):
        raise ValueError('All models must score the same issue dates')
    tau = cfg['model']['quantiles']
    quantiles = {name: values for name, (_, values) in predictions.items()}
    if w['evaluation']['include_original_model']:
        original_cfg = load_config(root / w['evaluation']['original_config'])
        original_ck = load_checkpoint(root / w['evaluation']['original_checkpoint'])
        original_ds, original_predictions = predict_checkpoint(original_cfg, DataStore(original_cfg), original_ck)
        if [original_ds.metadata(i) for i in range(len(original_ds))] != [dataset.metadata(i) for i in range(len(dataset))]:
            raise ValueError('Original experiment has different issue dates')
        if original_cfg['model']['quantiles'] != tau:
            raise ValueError('Original model has different quantiles')
        quantiles['original_8input_LSTM'] = original_predictions
    point = {name: values[:, :, tau.index(0.5)] for name, values in quantiles.items()}
    point['persistence'] = Persistence().predict(dataset)
    point['climatology'] = Climatology().fit(store).predict(dataset)
    train = store.frames['marala']
    train = train.loc[train.index.year.isin(years(cfg['splits']['train'])), cfg['data']['target_column']].dropna()
    threshold = float(np.quantile(train, w['evaluation']['high_flow_percentile']))
    flood_threshold = w['evaluation'].get('flood_threshold_cumecs')
    flood_threshold = threshold if flood_threshold is None else float(flood_threshold)
    rows = []
    for index in range(len(dataset)):
        basin, issue = dataset.metadata(index)
        frame = store.frames[basin]
        for lead in range(cfg['data']['forecast_horizon']):
            target_date = issue + pd.Timedelta(days=lead + 1)
            row = {'basin_id': basin, 'issue_date': issue, 'target_date': target_date,
                   'lead_day': lead + 1, 'season': season_for(target_date),
                   'observed_cumecs': frame.loc[target_date, cfg['data']['target_column']]}
            row.update({name: values[index, lead] for name, values in point.items()})
            for name, values in quantiles.items():
                row.update({f'{name}_q{q:g}': values[index, lead, j] for j, q in enumerate(tau)})
            rows.append(row)
    table = pd.DataFrame(rows)
    observed = table[table.observed_cumecs.notna()]
    overall, seasonal, calibration = [], [], []
    for lead, group in observed.groupby('lead_day'):
        for name in point:
            valid = group[np.isfinite(group[name])]
            overall.append({'model': name, 'lead_day': lead,
                            **metrics(valid.observed_cumecs, valid[name], threshold, flood_threshold)})
        for season, subset in group.groupby('season'):
            for name in point:
                valid = subset[np.isfinite(subset[name])]
                seasonal.append({'model': name, 'lead_day': lead, 'season': season,
                                 **metrics(valid.observed_cumecs, valid[name], threshold, flood_threshold)})
        for name in quantiles:
            lower, upper = group[f'{name}_q{tau[0]:g}'], group[f'{name}_q{tau[-1]:g}']
            calibration.append({'model': name, 'lead_day': lead, 'n': len(group),
                                'nominal_coverage': tau[-1] - tau[0],
                                'actual_coverage': float(group.observed_cumecs.between(lower, upper).mean())})
    overall, seasonal, calibration = map(pd.DataFrame, [overall, seasonal, calibration])
    output = root / w['evaluation']['output_dir']
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / 'predictions.csv', index=False, na_rep='NaN')
    overall.to_csv(output / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(output / 'scores_by_season_and_lead.csv', index=False)
    calibration.to_csv(output / 'quantile_calibration.csv', index=False)
    for name in point:
        folder = output / name
        folder.mkdir(parents=True, exist_ok=True)
        columns = ['basin_id', 'issue_date', 'target_date', 'lead_day', 'season', 'observed_cumecs', name]
        if name in quantiles:
            columns += [f'{name}_q{q:g}' for q in tau]
        table[columns].to_csv(folder / 'predictions.csv', index=False, na_rep='NaN')
        overall[overall.model.eq(name)].to_csv(folder / 'scores_by_lead.csv', index=False)
        seasonal[seasonal.model.eq(name)].to_csv(folder / 'scores_by_season_and_lead.csv', index=False)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for name, group in overall.groupby('model'):
        axes[0].plot(group.lead_day, group.NSE, marker='o', label=name)
        axes[1].plot(group.lead_day, group.RMSE_cumecs, marker='o', label=name)
    axes[0].set(xlabel='Lead day', ylabel='NSE')
    axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output / 'skill_by_lead.png', dpi=180)
    plt.close(fig)
    preparation = json.loads((root / w['sources']['pretrain_daily']).with_name('preparation_report.json').read_text())
    receipt = json.loads((root / w['sources']['raw_dir'] / 'download_receipt.json').read_text())
    hashes_ok = all(hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256'] for item in receipt['files'])
    original_ok = hashlib.sha256(Path(preparation['marala_source']).read_bytes()).hexdigest() == preparation['marala_source_sha256']
    if not hashes_ok or not original_ok:
        raise RuntimeError('A source file changed')
    flow_original = pd.read_csv(preparation['marala_source'])['q_cumecs']
    flow_prepared = pd.read_csv(root / w['sources']['marala_daily'])['q_cumecs']
    pd.testing.assert_series_equal(flow_original, flow_prepared)
    counts = observed[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda x: x.target_date.dt.year).groupby('year').size().reset_index(name='observed_days')
    manifest = {'pretraining_basins': checkpoints['finetuned']['pretraining_basins'],
                'pretrain_train_years': years(checkpoints['pretrained_only']['config']['splits']['train']),
                'pretrain_validation_years': years(checkpoints['pretrained_only']['config']['splits']['validation']),
                'marala_train_years': years(cfg['splits']['train']), 'marala_validation_years': years(cfg['splits']['validation']),
                'test_years': sorted(observed.target_date.dt.year.unique().tolist()),
                'unique_observed_days': int(counts.observed_days.sum()), 'observed_target_pairs': len(observed),
                'original_sources_unchanged': hashes_ok and original_ok, 'marala_targets_exactly_preserved': True,
                'stages': state, 'forecast_mode': cfg['data']['forecast_mode'], 'peak_threshold_cumecs': threshold,
                'flood_threshold_cumecs': flood_threshold,
                'training_year_history': checkpoints['finetuned']['training_years'],
                'selection_year_history': checkpoints['finetuned']['selection_years']}
    (output / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    run_rows = []
    for stage, path in state.items():
        checkpoint = load_checkpoint(path)
        history = json.loads(Path(path).with_name('history.json').read_text())
        run_rows.append({'stage': stage, 'epochs_run': len(history['epochs']), 'selected_epoch': checkpoint['epoch'],
                         'validation_pinball': checkpoint['validation_pinball'],
                         'train_samples': checkpoint['train_samples'], 'validation_samples': checkpoint['validation_samples'],
                         'training_seconds': history['elapsed_seconds']})
    day10 = overall[overall.lead_day.eq(10)].set_index('model')
    monsoon10 = seasonal[seasonal.lead_day.eq(10) & seasonal.season.eq('Jul-Sep')].set_index('model')
    gain = day10.loc['finetuned', 'NSE'] - day10.loc['scratch', 'NSE']
    monsoon_gain = monsoon10.loc['finetuned', 'NSE'] - monsoon10.loc['scratch', 'NSE']
    direction = ('a small overall transfer gain' if gain < 0.01 else 'an overall transfer gain') if gain > 0 else 'no overall transfer gain'
    monsoon_direction = 'a monsoon NSE improvement' if monsoon_gain > 0 else 'no monsoon NSE improvement'
    finding = (f'Day-10 overall NSE: fine-tuned **{day10.loc["finetuned", "NSE"]:.3f}**, matched scratch '
               f'**{day10.loc["scratch", "NSE"]:.3f}** (difference '
               f'{gain:+.4f}). '
               f'Day-10 monsoon NSE: fine-tuned **{monsoon10.loc["finetuned", "NSE"]:.3f}**, scratch '
               f'**{monsoon10.loc["scratch", "NSE"]:.3f}**. This pilot shows {direction}, '
               f'with {monsoon_direction}. These results do not establish a robust advantage across seeds, basins or extremes.')
    report = ['# Multi-basin pretraining and Marala fine-tuning', '',
              '**Real observed-data experiment using realized future weather plus noise. This is not measured operational TIGGE/GFS forecast accuracy.**', '',
              finding, '',
              '## Data and method', '',
              f'{len(manifest["pretraining_basins"])} real US CAMELS catchments were selected before scoring, without using Marala test outcomes. Original forcing and observed USGS discharge were downloaded selectively from the publisher archive, not from a tutorial sample or simulated runoff. Missing CAMELS -999 readings become NaN; nonnegative discharge is converted from cusecs to cumecs. Marala targets are identical to the existing observed-only table. No discharge is filled.', '',
              '[CAMELS original dataset](https://doi.org/10.5065/D6MW2F4D) ([download record](https://zenodo.org/records/15529996), CC BY 4.0). [NeuralHydrology fine-tuning method](https://neuralhydrology.readthedocs.io/en/latest/tutorials/finetuning.html). This is this project\'s PyTorch implementation of that pretrain/fine-tune approach, not a downloaded official NeuralHydrology checkpoint.', '',
              markdown(pd.DataFrame(preparation['pretraining_basins'])), '',
              f'Pretraining uses {manifest["pretrain_train_years"][0]}-{manifest["pretrain_train_years"][-1]}, validation {manifest["pretrain_validation_years"]}. Marala training years: {manifest["marala_train_years"]}; validation: {manifest["marala_validation_years"]}; test: {manifest["test_years"]}. The test years are absent from inherited training and validation years. US donor test years were reserved but not scored in this Marala experiment.', '',
              f'The transferred and matched scratch networks use {cfg["data"]["hindcast_length"]} history days, {cfg["data"]["forecast_horizon"]} future days, hidden size {cfg["model"]["hidden_size"]} and {cfg["model"]["num_layers"]} LSTM layer(s). Inputs: {cfg["data"]["dynamic_columns"]}; calendar enabled: {cfg["data"]["calendar_features"]}; static attributes enabled: {cfg["data"]["use_static"]}; past discharge enabled: {cfg["data"]["past_discharge"]}. Source temperature is the midpoint of NLDAS daily Tmax/Tmin; Marala uses ERA5 mean temperature. Forecast mode: {cfg["data"]["forecast_mode"]}. Recompute normalization on Marala training years: {cfg["finetuning"]["recompute_normalization"]}; the coordinate change requires readaptation. Discharge magnitudes and forcing products differ across domains.', '',
              markdown(pd.DataFrame(run_rows)), '',
              'Each model checkpoint was selected by its own validation loss. Fine-tuning uses a smaller learning rate; scratch uses fresh weights. Pinball losses from different normalizations are not directly comparable accuracy scores. No test-driven retry or hyperparameter selection was performed.', '',
              '## Observed Marala test data', '', markdown(counts), '',
              f'Unique observed days: **{manifest["unique_observed_days"]}**; observed issue/lead/target pairs: **{len(observed)}**. Target dates determine seasons. Overlapping windows are not independent flood events.', '',
              '## Comparison', '',
              'The matched control for transfer benefit is `scratch` (same two variables, architecture and split). `pretrained_only` is the donor model without Marala adaptation. `original_8input_LSTM` is context from the earlier, larger model with additional inputs; it is not a matched transfer ablation. Persistence uses the last known flow; climatology uses Marala training month/day means.', '',
              markdown(overall[['model', 'lead_day', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs']]), '',
              '## Seasonal metrics', '', markdown(seasonal), '',
              f'High-flow MAPE uses the configured Marala training quantile, **{threshold:.2f} cumecs**; the flood threshold is **{flood_threshold:.2f} cumecs**. Defaults are training Q95, not official warning categories or return-period floods. Positive bias means overprediction. False-alarm rate = false alerts/non-exceedance days; false-alarm ratio = false alerts/all alerts. NA denotes undefined denominators.', '',
              '## LSTM interval calibration', '', markdown(calibration), '',
              'Non-crossing quantiles are enforced, but interval calibration is not guaranteed. Nominal 5-95% coverage is 90%.', '',
              '## Limits and interpretation', '',
              'This is an eight-basin pilot, not a pretrained model from hundreds of diverse basins. The US donor hydrology, monsoon regime, regulation, catchment sizes and weather products differ from Chenab. Shared global flow scaling and no static embedding limit basin specificity. Transfer is not guaranteed to improve Marala, and conceptual models were not evaluated. The 2022-2024 years have already been inspected in earlier workspace experiments; they are held out of this fitting run but not an untouched project-wide holdout. More representative basins and archived forecasts are needed before operational use.', '',
              'Source hashes match, and Marala target values and NaN positions exactly match the source table. Synthetic tests check code correctness only. Initial source archives and both training stages are retained for retraining.', '',
              '![Skill by lead](skill_by_lead.png)', '']
    (output / 'evaluation_report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    versions = {name: importlib.metadata.version(name) for name in ['torch', 'numpy', 'pandas', 'scikit-learn']}
    commands = ('```powershell\n'
                '$python = "../experiments/marala_observed/.venv/Scripts/python.exe"\n'
                '& $python pretrained_multibasin_lstm/prepare_data.py --config pretrained_multibasin_lstm/config.yaml\n'
                '& $python pretrained_multibasin_lstm/train.py --stage all --config pretrained_multibasin_lstm/config.yaml\n'
                '& $python pretrained_multibasin_lstm/evaluate.py --config pretrained_multibasin_lstm/config.yaml\n'
                '& $python -m unittest discover -s tests -v\n```')
    summary = ['# Actual multi-basin transfer run - 2026-10-30', '',
               'Working directory: `D:/projects/flood_model/flood_model/riverine flood/short range/model`.', '',
               '## Commands executed', '', commands, '',
               'The source-coverage audit initially rejected 1981-1990 because Gallatin had only 2,556 observed days. The final 1985-1994 period has 3,652 observed days for each of eight donors and was selected before any training or test scoring. Data preparation was then completed without interpolation. The three real-data training stages were each run once. Evaluation was rerun to add this summary, with unchanged weights and test scores. Python compilation checks passed for the new scripts. All 15 correctness tests passed; their synthetic fine-tuning checks are not real accuracy results.', '',
               '## Real training results', '', markdown(pd.DataFrame(run_rows)), '',
               'Pretraining used 1985-1994, validation 1995-1996. Fine-tuning and the matched scratch model used Marala 2016-2020, validation 2021. Test years were 2022-2024. Every training/validation year inherited through the parent checkpoint was checked before test scoring. Fine-tuning retained all pretrained model weights and recomputed normalization from Marala training data, using the configured smaller learning rate.', '',
               markdown(counts), '',
               f'Unique observed Marala test days: **{manifest["unique_observed_days"]}**; issue/lead/target pairs: **{len(observed)}**. Day-10 scores use {int(day10.loc["finetuned", "n"])} observed targets.', '',
               '## What the scores show', '', finding, '',
               markdown(overall[overall.lead_day.isin([1, 10])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs']]), '',
               markdown(seasonal[seasonal.lead_day.eq(10) & seasonal.model.isin(['finetuned', 'scratch'])]), '',
               markdown(calibration[calibration.lead_day.eq(10)]), '',
               'The earlier eight-input LSTM remains stronger overall than this two-input transfer pilot. The new model uses fewer inputs and a smaller hidden size, so that comparison does not isolate transfer. The matched scratch model is the relevant control. The donor-only model performs poorly without Marala adaptation. No conceptual model was evaluated.', '',
               'These are stand-in-weather results using future realized weather plus noise. Archived TIGGE/GFS forecasts were not available. Monsoon transfer is weak, the record and donor set are limited, and prediction intervals are not guaranteed to be calibrated. No operational accuracy or robust transfer advantage is established.', '',
               '## Data and artifacts verified', '',
               'Original CAMELS files match their saved SHA256 hashes. Original Marala file SHA256 is unchanged. Prepared Marala observed values and NaN positions exactly match the source table. Missing targets remain NaN, masked from loss and evaluation. All three checkpoints, config snapshots, normalization statistics, training histories and inherited year lists are saved under this model folder.', '',
               markdown(pd.DataFrame(list(versions.items()), columns=['package', 'version'])), '',
               '[Full evaluation](reports/initial/evaluation_report.md) | [Instructions](README.md) | [Stage manifest](runs/stages.json)', '']
    (root / 'RUN_RESULTS.md').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    print(overall[overall.lead_day.isin([1, 10])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs']].to_string(index=False))
    print(f'Report: {output / "evaluation_report.md"}')


if __name__ == '__main__':
    main()
