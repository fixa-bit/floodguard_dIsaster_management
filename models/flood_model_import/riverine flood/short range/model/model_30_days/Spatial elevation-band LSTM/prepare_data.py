"""Join new real band inputs to the unmodified observed discharge table."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import load_config, resolve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    args = parser.parse_args()
    cfg = load_config(args.config)
    output = resolve(cfg, cfg['data']['daily_file'])
    if output.exists():
        raise FileExistsError('Choose a new daily_file; prepared tables are never overwritten')
    options = cfg['preparation']
    raw = resolve(cfg, options['raw_directory'])
    metadata = json.loads((raw / 'band_metadata.json').read_text())
    receipt = json.loads((raw / 'download_receipt.json').read_text())
    paths = [raw / f'{year}.csv' for year in range(options['start_year'], options['end_year'] + 1)]
    recorded = {int(row['year']): row['sha256'] for row in receipt['files']}
    for year, path in zip(range(options['start_year'], options['end_year'] + 1), paths):
        if hashlib.sha256(path.read_bytes()).hexdigest() != recorded.get(year):
            raise ValueError(f'Raw extraction hash mismatch: {path}')
    weather = pd.concat([pd.read_csv(path, parse_dates=['date']) for path in paths]).set_index('date').sort_index()
    expected = pd.date_range(f'{options["start_year"]}-01-01', f'{options["end_year"]}-12-31')
    if weather.index.has_duplicates or not weather.index.equals(expected):
        raise ValueError('Missing or duplicate extracted dates')
    original_path = resolve(cfg, options['observed_daily_source'])
    original_digest = hashlib.sha256(original_path.read_bytes()).hexdigest()
    original = pd.read_csv(original_path, parse_dates=['date'])
    if original['basin_id'].nunique() != 1:
        raise ValueError('This extraction describes one catchment; provide one matching target basin')
    frame = original.copy(deep=True).set_index('date')
    bands = cfg['spatial']['band_ids']
    variables = cfg['spatial']['history_variables']
    for band in bands:
        for variable in variables:
            name = f'{band}_{variable}'
            frame[name] = weather[name].reindex(frame.index)
    fractions = np.asarray(metadata['area_fractions'])
    for variable in variables:
        values = frame[[f'{band}_{variable}' for band in bands]].to_numpy(float)
        frame[f'mean_{variable}'] = np.sum(values * fractions[None], axis=1)
    pd.testing.assert_series_equal(original['q_cumecs'].reset_index(drop=True), frame.q_cumecs.reset_index(drop=True))
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, na_rep='NaN')
    reread = pd.read_csv(output)
    pd.testing.assert_series_equal(original.q_cumecs, reread.q_cumecs)
    profile = []
    for band, weight in zip(bands, fractions):
        for variable in variables:
            values = weather[f'{band}_{variable}']
            profile.append({'band': band, 'area_fraction': weight, 'variable': variable, 'mean': values.mean(),
                             'minimum': values.min(), 'maximum': values.max(), 'missing_days': int(values.isna().sum())})
    pd.DataFrame(profile).to_csv(output.with_name('band_input_profile.csv'), index=False)
    quality = []
    for variable, reference in options.get('reference_columns', {}).items():
        comparison = frame[[f'mean_{variable}', reference]].dropna()
        error = comparison.iloc[:, 0] - comparison.iloc[:, 1]
        correlation = comparison.iloc[:, 0].corr(comparison.iloc[:, 1])
        relative_rmse = float(np.sqrt(np.mean(error ** 2)) / max(comparison.iloc[:, 1].std(), 1e-6))
        quality.append({'variable': variable, 'overlapping_days': len(comparison),
                         'correlation_with_saved_basin_series': correlation,
                         'rmse_in_variable_units': float(np.sqrt(np.mean(error ** 2))),
                         'rmse_relative_to_reference_std': relative_rmse})
        if len(comparison) < 3000 or not np.isfinite(correlation) or correlation < .99 or relative_rmse > .1:
            raise ValueError(f'Independent aggregation check failed for {variable}')
    pd.DataFrame(quality).to_csv(output.with_name('aggregation_quality_check.csv'), index=False)
    report = {'observed_source': str(original_path), 'observed_source_sha256': original_digest,
              'prepared_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'observed_targets_exactly_preserved': True, 'no_target_filling': True,
              'extracted_first_date': str(weather.index.min().date()), 'extracted_last_date': str(weather.index.max().date()),
              'extracted_daily_rows': len(weather), 'band_count': len(bands),
              'observed_targets': int(reread.q_cumecs.notna().sum()), 'nan_targets': int(reread.q_cumecs.isna().sum()),
              'area_fractions': fractions.tolist()}
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_digest
    output.with_name('preparation_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
