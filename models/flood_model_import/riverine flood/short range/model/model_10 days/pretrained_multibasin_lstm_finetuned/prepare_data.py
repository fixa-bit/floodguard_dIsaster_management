"""Unit conversion and weather alignment; no target imputation or interpolation."""
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
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import load_config, years
from pretrained_multibasin_lstm_finetuned.download_data import download, workflow


def prepare(cfg):
    root, options = cfg['_root'], cfg['sources']
    output = root / options['pretrain_daily']
    marala_output = root / options['marala_daily']
    if output.exists() or marala_output.exists():
        raise FileExistsError('Choose new prepared output paths; existing daily tables are never overwritten')
    receipt = download(cfg)
    train_cfg = load_config(root / cfg['stages']['pretrain_config'])
    records, coverage = [], []
    for basin in options['basins']:
        folder = root / options['raw_dir'] / basin
        forcing = pd.read_csv(folder / f'{basin}_lump_{options["forcing"]}_forcing_leap.txt', sep=r'\s+', skiprows=3)
        forcing.columns = forcing.columns.str.lower()
        forcing['date'] = pd.to_datetime(dict(year=forcing['year'], month=forcing['mnth'], day=forcing['day']))
        flow = pd.read_csv(folder / f'{basin}_streamflow_qc.txt', sep=r'\s+', header=None,
                           names=['gauge_id', 'year', 'month', 'day', 'q_cusecs', 'quality'], dtype={'gauge_id': str})
        flow['date'] = pd.to_datetime(flow[['year', 'month', 'day']])
        if forcing['date'].duplicated().any() or flow['date'].duplicated().any():
            raise ValueError('Duplicate original dates')
        # CAMELS -999 denotes missing discharge, never a physical negative flow.
        q = flow.set_index('date')['q_cusecs'].where(flow.set_index('date')['q_cusecs'] >= 0) * 0.028316846592
        weather = forcing.set_index('date')
        weather = weather.where(weather > -900)
        frame = pd.DataFrame({'precipitation_mm': weather['prcp(mm/day)'],
                              'temperature_c': (weather['tmax(c)'] + weather['tmin(c)']) / 2})
        frame = frame.where(frame > -900)
        frame['q_cumecs'] = q.reindex(frame.index)
        frame['basin_id'] = basin
        frame['q_source'] = np.where(frame.q_cumecs.notna(), 'CAMELS_US_USGS', None)
        observed_train = int(frame.loc[frame.index.year.isin(years(train_cfg['splits']['train'])), 'q_cumecs'].notna().sum())
        if observed_train < options['minimum_training_observed_days_per_basin']:
            raise ValueError(f'{basin}: only {observed_train} observed training days')
        coverage.append({'basin_id': basin, 'observed_training_days': observed_train,
                         'first_date': str(frame.index.min().date()), 'last_date': str(frame.index.max().date())})
        records.append(frame.reset_index())
    merged = pd.concat(records, ignore_index=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output, index=False, na_rep='NaN')
    source = root / options['marala_source']
    marala_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    original = pd.read_csv(source)
    marala = original[['date', 'basin_id', 'q_cumecs', 'q_source']].copy()
    marala['precipitation_mm'] = original[options['marala_precipitation_column']]
    marala['temperature_c'] = original[options['marala_temperature_column']]
    pd.testing.assert_series_equal(marala['q_cumecs'], original['q_cumecs'])
    marala_output.parent.mkdir(parents=True, exist_ok=True)
    marala.to_csv(marala_output, index=False, na_rep='NaN')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == marala_digest
    for item in receipt['files']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == item['sha256']
    (output.parent / 'preparation_report.json').write_text(json.dumps({
        'pretraining_basins': coverage, 'observed_targets_not_filled': True,
        'marala_source': str(source.resolve()), 'marala_source_sha256': marala_digest,
        'prepared_pretrain_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'prepared_marala_sha256': hashlib.sha256(marala_output.read_bytes()).hexdigest(),
        'source_file_hashes_unchanged': True}, indent=2) + '\n')
    print(pd.DataFrame(coverage).to_string(index=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('workflow.yaml')))
    args = parser.parse_args()
    prepare(workflow(args.config))
