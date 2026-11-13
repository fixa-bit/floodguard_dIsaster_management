"""Train an LSTM to correct calibrated physical HBV errors over 30 leads."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from data import load_data, make_samples, save_json
from learning import fit_lstm, predict_lstm
from physical import PARAMETERS


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def masks(samples, frame, cfg):
    dates = samples['valid']
    origins = samples['origins']
    warm = origins >= cfg['warmup_days']
    tr_start = np.datetime64(f"{cfg['first_training_year']}-01-01")
    tr_end = np.datetime64(f"{cfg['last_training_year']}-12-31")
    va_start = np.datetime64(f"{cfg['validation_years'][0]}-01-01")
    va_end = np.datetime64(f"{cfg['validation_years'][1]}-12-31")
    te_start = np.datetime64(f"{cfg['test_years'][0]}-01-01")
    te_end = np.datetime64(f"{cfg['test_years'][1]}-12-31")
    train = warm & (dates[:, 0] >= tr_start) & (dates[:, -1] <= tr_end)
    validation = warm & (dates[:, 0] >= va_start) & (dates[:, -1] <= va_end)
    test = warm & (dates[:, 0] >= te_start) & (dates[:, -1] <= te_end)
    if not train.any() or not validation.any() or not test.any():
        raise ValueError('Chronological train, validation or test samples are empty')
    return train, validation, test


def issue_predictions(samples, indices, frame, bundle):
    residual_quantiles = predict_lstm(bundle, samples['history'][indices], samples['future'][indices])
    physical = samples['hbv'][indices]
    hybrid_quantiles = np.maximum(physical[..., None] + residual_quantiles, 0.)
    if not np.isfinite(hybrid_quantiles).all():
        raise FloatingPointError('Nonfinite hybrid prediction')
    rows, detailed = [], []
    for row_index, sample_index in enumerate(indices):
        origin = int(samples['origins'][sample_index])
        issue = frame.index[origin]
        for lead, date in enumerate(samples['valid'][sample_index]):
            observed = frame.loc[pd.Timestamp(date), 'q_cumecs']
            if not np.isfinite(observed):
                continue
            row = {
                'basin_id': 'marala', 'issue_date': issue.strftime('%Y-%m-%d'),
                'target_date': pd.Timestamp(date).strftime('%Y-%m-%d'), 'lead_day': lead + 1,
                'season': ('Oct-Mar' if pd.Timestamp(date).month in (10, 11, 12, 1, 2, 3)
                           else 'Apr-Jun' if pd.Timestamp(date).month in (4, 5, 6) else 'Jul-Sep'),
                'observed_cumecs': float(observed), 'HBV_LSTM': float(hybrid_quantiles[row_index, lead, 1]),
            }
            rows.append(row)
            detailed.append({**row, 'HBV_physical': float(physical[row_index, lead]),
                             'residual_p10': float(residual_quantiles[row_index, lead, 0]),
                             'residual_p50': float(residual_quantiles[row_index, lead, 1]),
                             'residual_p90': float(residual_quantiles[row_index, lead, 2]),
                             'hybrid_p10': float(hybrid_quantiles[row_index, lead, 0]),
                             'hybrid_p50': float(hybrid_quantiles[row_index, lead, 1]),
                             'hybrid_p90': float(hybrid_quantiles[row_index, lead, 2])})
    return pd.DataFrame(rows), pd.DataFrame(detailed)


def main():
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    run_dir = ROOT / cfg['output_dir']
    if (run_dir / 'lstm' / 'best.pt').exists():
        raise FileExistsError('Existing checkpoint found; change output_dir to preserve earlier runs')
    source_path = (ROOT / cfg['source_daily_file']).resolve()
    source_hash = digest(source_path)
    daily_path = (ROOT / cfg['daily_file']).resolve()
    if digest(daily_path) != source_hash:
        raise ValueError('Bundled observed table differs from its source')
    torch.set_num_threads(cfg['threads'])
    frame, area, archive, input_hashes = load_data(cfg, ROOT)
    if archive is not None:
        raise ValueError('This training configuration expects the saved reanalysis hindcast weather mapping')
    base_cal = json.loads((ROOT / cfg['base_calibration']).read_text(encoding='utf-8'))
    params = np.array([base_cal['parameters'][name] for name in PARAMETERS], dtype=float)
    samples = make_samples(frame, params, area, cfg,
                           f"{cfg['last_training_year']}-12-31", archive=None)
    train, validation, test = masks(samples, frame, cfg)
    print(f"Samples: train={int(train.sum())}, validation={int(validation.sum())}, test={int(test.sum())}", flush=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    lstm_dir = run_dir / 'lstm'
    bundle = fit_lstm(samples['history'], samples['future'], samples['residual'],
                      train, validation, cfg, lstm_dir)
    np.savez_compressed(run_dir / 'sample_split_masks.npz', train=train, validation=validation, test=test,
                        issue_indices=samples['origins'], valid_dates=samples['valid'])
    (run_dir / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
    (run_dir / 'input_manifest.json').write_text(json.dumps(input_hashes, indent=2) + '\n', encoding='utf-8')
    save_json(run_dir / 'feature_manifest.json', {
        'history_features': samples['history_features'], 'future_features': samples['future_features'],
        'normalization': 'fit on training windows only; missing values use training means and indicator channels',
        'training_rows': int(train.sum()), 'validation_rows': int(validation.sum()), 'test_rows': int(test.sum()),
        'training_years': list(range(cfg['first_training_year'], cfg['last_training_year'] + 1)),
        'validation_years': list(range(cfg['validation_years'][0], cfg['validation_years'][1] + 1)),
        'test_years': list(range(cfg['test_years'][0], cfg['test_years'][1] + 1)),
        'physical_base_calibration': str((ROOT / cfg['base_calibration']).relative_to(ROOT)),
        'physical_parameters': dict(zip(PARAMETERS, params.tolist())),
        'physical_area_km2': area, 'weather_mode': 'reanalysis_hindcast',
    })
    for split, mask, output_key in [('validation', validation, 'validation_output_dir'),
                                     ('test', test, 'test_output_dir')]:
        out_dir = ROOT / cfg[output_key]
        out_dir.mkdir(parents=True, exist_ok=True)
        simple, detailed = issue_predictions(samples, np.flatnonzero(mask), frame, bundle)
        simple.to_csv(out_dir / 'predictions.csv', index=False)
        detailed.to_csv(out_dir / 'forecast_detail.csv', index=False)
        print(f"{split}: {len(simple)} observed issue/lead targets", flush=True)
    if digest(source_path) != source_hash:
        raise RuntimeError('Observed source changed during training')
    print(f"Saved residual LSTM checkpoint: {lstm_dir / 'best.pt'}", flush=True)
    from evaluate import main as evaluate_main
    evaluate_main()


if __name__ == '__main__':
    main()
