"""Prepare the author's feature schema without changing discharge observations."""
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
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


def duration(mask):
    locations = np.flatnonzero(mask)
    if not len(locations):
        return 0.
    return float(np.mean([len(run) for run in np.split(locations, np.flatnonzero(np.diff(locations) > 1) + 1)]))


def climate_attributes(frame):
    p, pet, temp = frame['rain_era5_mm'], frame['pet_mm'], frame['temperature_c']
    if frame[[p.name, pet.name, temp.name]].isna().any().any():
        raise ValueError('Climate period contains missing inputs')
    mean_p, mean_pet = p.mean(), pet.mean()
    monthly_p, monthly_pet = p.groupby(frame.index.month).mean(), pet.groupby(frame.index.month).mean()
    monthly_t = temp.groupby(frame.index.month).mean()
    moisture = np.where(monthly_p > monthly_pet, 1 - monthly_pet / monthly_p,
                        np.where(monthly_p < monthly_pet, monthly_p / monthly_pet - 1, 0))
    return {'p_mean': float(mean_p), 'pet_mean': float(mean_pet), 'aridity': float(mean_pet / mean_p),
            'frac_snow': float(monthly_p[monthly_t < 0].sum() / monthly_p.sum()),
            'high_prec_freq': float((p >= 5 * mean_p).mean()), 'high_prec_dur': duration(p >= 5 * mean_p),
            'low_prec_freq': float((p < 1).mean()), 'low_prec_dur': duration(p < 1),
            'moisture_index': float(np.mean(moisture)), 'seasonality': float(np.max(moisture) - np.min(moisture))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    args = parser.parse_args()
    root = Path(args.config).resolve().parent
    cfg = yaml.safe_load(Path(args.config).read_text())
    output, static_output = root / cfg['data']['daily_file'], root / cfg['data']['static_file']
    if output.exists() or static_output.exists():
        raise FileExistsError('Use new preparation output paths; existing tables are never overwritten')
    source = (root / cfg['preparation']['observed_daily_source']).resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    original = pd.read_csv(source, parse_dates=['date'])
    frame = original.copy(deep=True).set_index('date')
    raw = root / cfg['preparation']['raw_directory']
    receipt = json.loads((raw / 'download_receipt.json').read_text())
    verified = {row['year']: row for row in receipt['files']}
    paths = [raw / 'era5land_daily' / f'{year}.csv' for year in range(cfg['preparation']['start_year'], cfg['preparation']['end_year'] + 1)]
    for path in paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() != verified[int(path.stem)]['sha256']:
            raise ValueError('Raw weather differs from its saved receipt')
    weather = pd.concat([pd.read_csv(path, parse_dates=['date']) for path in paths]).set_index('date').sort_index()
    expected = pd.date_range(f'{cfg["preparation"]["start_year"]}-01-01', f'{cfg["preparation"]["end_year"]}-12-31')
    if weather.index.has_duplicates or not weather.index.equals(expected):
        raise ValueError('Incomplete weather calendar')
    base = yaml.safe_load((root / cfg['pretrained']['config']).read_text())
    for name in base['dynamic_inputs']:
        frame[name] = weather[name].reindex(frame.index)
    provenance = {name: 'fresh_ERA5_LAND_DAILY_AGGR_UTC' for name in base['dynamic_inputs']}
    for name, column in cfg['preparation']['existing_feature_map'].items():
        # These definitions match; missing values stay NaN in the prepared data.
        frame[name] = original[column].to_numpy()
        provenance[name] = f'existing_daily_table:{column}'
    for name in ['total_precipitation_sum', 'snow_depth_water_equivalent_mean']:
        # Caravan's documented numerical-artifact handling; target values are untouched.
        frame[name] = frame[name].clip(lower=0)
    atlas = json.loads((raw / 'hydroatlas_intersections.json').read_text())
    first, last = cfg['preparation']['climate_years']
    climate = climate_attributes(frame[frame.index.year.isin(range(first, last + 1))])
    values, sources, coverage = dict(climate), {name: f'ERA5_climate_{first}_{last}' for name in climate}, {}
    values['area'], sources['area'] = atlas['area_km2'], 'catchment_geometry_Earth_Engine_area_km2'
    total = sum(item['intersection_km2'] for item in atlas['records'])
    for name in atlas['requested']:
        valid = [(item['intersection_km2'], item.get(name)) for item in atlas['records']
                 if item.get(name) is not None and np.isfinite(item[name]) and item[name] > -900]
        present = sum(weight for weight, value in valid)
        coverage[name] = present / total if total else 0
        values[name] = sum(weight * value for weight, value in valid) / present if present and coverage[name] >= .99 else np.nan
        sources[name] = 'HydroATLAS_area_weighted' if np.isfinite(values[name]) else 'missing_global_training_mean_imputation_in_model'
    statics = {'basin_id': cfg['data']['basin_id'], **{name: values.get(name, np.nan) for name in sorted(base['static_attributes'])}}
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, na_rep='NaN')
    pd.DataFrame([statics]).to_csv(static_output, index=False, na_rep='NaN')
    reread = pd.read_csv(output)
    pd.testing.assert_series_equal(original['q_cumecs'], reread['q_cumecs'])
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    pd.DataFrame([{'attribute': name, 'value': statics[name], 'source': sources.get(name, 'missing'),
                   'coverage_fraction': coverage.get(name, 1.)} for name in sorted(base['static_attributes'])]).to_csv(output.with_name('static_attribute_provenance.csv'), index=False)
    report = {'observed_source': str(source), 'observed_source_sha256': before,
              'prepared_daily_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
              'static_sha256': hashlib.sha256(static_output.read_bytes()).hexdigest(),
              'observed_targets_exactly_preserved': True, 'observed_targets': int(reread.q_cumecs.notna().sum()),
              'nan_targets': int(reread.q_cumecs.isna().sum()), 'weather_days_downloaded': len(weather),
              'dynamic_feature_order': base['dynamic_inputs'], 'static_feature_order': sorted(base['static_attributes']),
              'static_missing_count': sum(not np.isfinite(statics[name]) for name in base['static_attributes']),
              'climate_period': [first, last], 'area_km2': values['area'], 'dynamic_provenance': provenance,
              'timezone_note': 'UTC daily aggregates; parent Caravan used local-day aggregates. This is a documented domain mismatch.'}
    output.with_name('preparation_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
