"""Calibrate physical HBV on training observations and make 30-day hindcast trajectories."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from forcing import QuantileMapper
from physical import FLUX_NAMES, PARAMETERS, STATE_NAMES, branches, calibrate, initial_state, simulate


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    def clean(x):
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple, np.ndarray)):
            return [clean(v) for v in x]
        if isinstance(x, (np.integer,)):
            return int(x)
        if isinstance(x, (np.floating, float)):
            return float(x) if np.isfinite(x) else None
        if isinstance(x, (np.bool_,)):
            return bool(x)
        return x
    Path(path).write_text(json.dumps(clean(value), indent=2, allow_nan=False) + '\n', encoding='utf-8')


def season(date):
    if date.month in (10, 11, 12, 1, 2, 3):
        return 'Oct-Mar'
    if date.month in (4, 5, 6):
        return 'Apr-Jun'
    return 'Jul-Sep'


def make_predictions(frame, area, parameters, states, config, split):
    horizon = config['horizon']
    start_year, end_year = config[f'{split}_years']
    target_start = pd.Timestamp(f'{start_year}-01-01')
    target_end = pd.Timestamp(f'{end_year}-12-31')
    train_mask = ((frame.index.year >= config['first_training_year']) &
                  (frame.index.year <= config['last_training_year']))
    mapper = QuantileMapper().fit(frame, train_mask)
    pet_train = frame.loc[train_mask, 'pet_mm']
    pet_climate = pet_train.groupby(pet_train.index.strftime('%m-%d')).mean().to_dict()
    rows = []
    for origin in range(config['history_days'] - 1, len(frame) - horizon):
        issue = frame.index[origin]
        valid = frame.index[origin + 1:origin + 1 + horizon]
        if valid[0] < target_start or valid[-1] > target_end:
            continue
        precipitation = mapper.transform(frame.rain_era5_mm.iloc[origin + 1:origin + 1 + horizon].to_numpy(),
                                         valid.month.to_numpy(), 'rain')
        temperature = mapper.transform(frame.temperature_c.iloc[origin + 1:origin + 1 + horizon].to_numpy(),
                                       valid.month.to_numpy(), 'temperature')
        pet = np.array([pet_climate.get(d.strftime('%m-%d'), pet_climate['02-28']) for d in valid])
        pred_states, pred_fluxes = branches(precipitation[None, :], temperature[None, :], pet[None, :],
                                            parameters, states[origin][None, :])
        prediction = pred_fluxes[0, :, 3] * area / 86.4
        if not np.isfinite(prediction).all() or (prediction < 0).any():
            raise FloatingPointError(f'Invalid physical discharge forecast from {issue.date()}')
        for lead, date in enumerate(valid):
            observed = frame.loc[date, 'q_cumecs']
            if not np.isfinite(observed):
                continue
            rows.append({
                'basin_id': 'marala', 'issue_date': issue.strftime('%Y-%m-%d'),
                'target_date': date.strftime('%Y-%m-%d'), 'lead_day': lead + 1,
                'season': season(date), 'observed_cumecs': float(observed),
                'Calibrated_HBV': float(prediction[lead]),
            })
    return pd.DataFrame(rows)


def main():
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    output = ROOT / cfg['output_dir']
    if (output / 'calibration.json').exists():
        raise FileExistsError('Calibration already exists. Preserve it and use a new output_dir to recalibrate.')
    source = (ROOT / cfg['source_daily_file']).resolve()
    data_path = (ROOT / cfg['daily_file']).resolve()
    if digest(source) != digest(data_path):
        raise ValueError('Local daily table is not byte-identical to the observed source')
    before = digest(source)
    frame = pd.read_csv(data_path, parse_dates=['date']).set_index('date').sort_index()
    frame = frame.loc[cfg['simulation_start']:cfg['simulation_end']].copy()
    expected = pd.date_range(cfg['simulation_start'], cfg['simulation_end'])
    if not frame.index.equals(expected):
        raise ValueError('Forcing table must have one row for every simulation date')
    required = ['rain_chirps_mm', 'rain_era5_mm', 'temperature_c', 'pet_mm', 'q_cumecs']
    if not set(required).issubset(frame.columns):
        raise ValueError(f'Missing required columns: {sorted(set(required) - set(frame.columns))}')
    weather = frame[['rain_chirps_mm', 'rain_era5_mm', 'temperature_c', 'pet_mm']].to_numpy(float)
    if not np.isfinite(weather).all():
        raise ValueError('HBV forcing has missing values in the configured simulation period')
    if (frame[['rain_chirps_mm', 'rain_era5_mm', 'pet_mm']] < 0).any().any():
        raise ValueError('Precipitation and PET must be nonnegative')
    q = frame.q_cumecs.to_numpy(float)
    if np.isinf(q).any() or np.any(q[np.isfinite(q)] < 0):
        raise ValueError('Invalid observed discharge values')

    metadata = json.loads((ROOT / cfg['catchment_metadata']).resolve().read_text(encoding='utf-8'))
    area = float(metadata['catchment_area_km2'])
    dates = frame.index
    calibration_mask = ((dates.year >= cfg['first_training_year']) &
                        (dates.year <= cfg['last_training_year']) &
                        np.isfinite(q) & (np.arange(len(frame)) >= cfg['warmup_days']))
    if int(calibration_mask.sum()) < 365:
        raise ValueError('Insufficient observed training targets after physical warmup')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
    par, result = calibrate(frame.rain_chirps_mm.to_numpy(float), frame.temperature_c.to_numpy(float),
                            frame.pet_mm.to_numpy(float), q, calibration_mask, area, cfg)
    result.update({
        'parameters': dict(zip(PARAMETERS, np.asarray(par).tolist())),
        'calibration_years': list(range(cfg['first_training_year'], cfg['last_training_year'] + 1)),
        'calibration_observed_days': int(calibration_mask.sum()), 'warmup_days': cfg['warmup_days'],
        'area_km2': area, 'objective': 'maximize KGE on observed training days after warmup',
        'source_sha256': before,
    })
    write_json(output / 'calibration.json', result)
    pd.DataFrame(result['generation_history']).to_csv(output / 'calibration_history.csv', index=False)
    states, fluxes = simulate(frame.rain_chirps_mm.to_numpy(float), frame.temperature_c.to_numpy(float),
                              frame.pet_mm.to_numpy(float), par, initial_state(par))
    if not np.isfinite(states).all() or (states < -1e-8).any() or abs(fluxes[:, 5]).max() > 1e-7:
        raise RuntimeError('HBV physical state or water balance check failed')
    daily = pd.DataFrame(states, index=dates, columns=STATE_NAMES)
    daily = daily.join(pd.DataFrame(fluxes, index=dates, columns=FLUX_NAMES))
    daily['observed_q_cumecs'] = q
    daily['hbv_historical_cumecs'] = fluxes[:, 3] * area / 86.4
    daily['is_spinup'] = np.arange(len(frame)) < cfg['warmup_days']
    daily.to_csv(output / 'historical_states_and_fluxes.csv', index_label='date')
    train_mask = ((dates.year >= cfg['first_training_year']) & (dates.year <= cfg['last_training_year']))
    monthly_mapper = QuantileMapper().fit(frame, train_mask)
    write_json(output / 'rainfall_quantile_mapping.json', monthly_mapper.grids)
    write_json(output / 'pet_month_day_climatology.json', frame.loc[train_mask, 'pet_mm'].groupby(
        frame.loc[train_mask].index.strftime('%m-%d')).mean().to_dict())
    manifest = {
        'source_data_sha256_before': before, 'source_data_sha256_after': digest(source),
        'local_data_sha256': digest(data_path), 'local_data_byte_identical': digest(source) == digest(data_path),
        'parameters': dict(zip(PARAMETERS, np.asarray(par).tolist())),
        'calibration_kge': result['calibration_kge'], 'converged': result['converged'],
        'training_years': result['calibration_years'], 'warmup_days': cfg['warmup_days'],
        'validation_years': cfg['validation_years'], 'test_years': cfg['test_years'],
        'discharge_filled_or_modified': False, 'water_balance_max_abs_error_mm': float(np.abs(fluxes[:, 5]).max()),
    }
    write_json(output / 'training_manifest.json', manifest)
    if digest(source) != before:
        raise RuntimeError('Observed source changed during calibration')
    for split, folder_key in [('validation', 'validation_output_dir'), ('test', 'test_output_dir')]:
        pred = make_predictions(frame, area, par, states, cfg, split)
        report_dir = ROOT / cfg[folder_key]
        report_dir.mkdir(parents=True, exist_ok=True)
        pred.to_csv(report_dir / 'predictions.csv', index=False)
        print(f'{split}: {len(pred)} observed issue/lead targets; saved {report_dir / "predictions.csv"}', flush=True)
    from evaluate import main as evaluate_main
    evaluate_main()
    print(json.dumps({k: manifest[k] for k in ['calibration_kge', 'converged', 'training_years', 'water_balance_max_abs_error_mm']}, indent=2))


if __name__ == '__main__':
    main()
