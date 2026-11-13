"""Score the spatial model and its mean-input control on observed test targets."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from data import DataStore, load_config, resolve, inverse_flow
from lstm.model import HindcastForecastLSTM
from spatial_data import SpatialDataset, load_spatial_config
from spatial_model import build_model

ROOT = Path(__file__).resolve().parent


def scores(observed, predicted, threshold):
    observed, predicted = np.asarray(observed), np.asarray(predicted)
    err = predicted - observed
    variance = np.sum((observed - observed.mean()) ** 2)
    r = np.corrcoef(observed, predicted)[0, 1] if len(observed) > 1 else np.nan
    alpha = predicted.std() / observed.std() if observed.std() else np.nan
    beta = predicted.mean() / observed.mean() if observed.mean() else np.nan
    flood = observed >= threshold
    alert = predicted >= threshold
    hits = int((flood & alert).sum())
    return {
        'n': len(observed),
        'NSE': 1 - np.sum(err ** 2) / variance if variance else np.nan,
        'KGE': 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2),
        'PBIAS_pct': 100 * err.sum() / observed.sum() if observed.sum() else np.nan,
        'RMSE_cumecs': float(np.sqrt(np.mean(err ** 2))),
        'MAE_cumecs': float(np.mean(np.abs(err))),
        'flood_precision': hits / int(alert.sum()) if alert.any() else 0.0,
        'flood_recall': hits / int(flood.sum()) if flood.any() else np.nan,
        'flood_days': int(flood.sum()),
    }


def load_member(cfg, checkpoint_path, spatial):
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
    store = DataStore(cfg)
    dataset = SpatialDataset(store, 'test', checkpoint['statistics'])
    model = (build_model(cfg, dataset.dimensions(), checkpoint['statistics']) if spatial
             else HindcastForecastLSTM(cfg, *dataset.dimensions()))
    model.load_state_dict(checkpoint['model_state'])
    model.eval()
    outputs = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=cfg['training']['batch_size'], shuffle=False):
            outputs.append(model(*(batch[key] for key in ('history', 'future', 'static'))).numpy())
    return dataset, inverse_flow(np.concatenate(outputs), checkpoint['statistics']), checkpoint


def main():
    cfg = load_spatial_config(ROOT / 'config.yaml')
    manifest = json.loads(resolve(cfg, cfg['spatial']['run_manifest']).read_text(encoding='utf-8'))
    spatial_ds, spatial_q, spatial_ck = load_member(cfg, manifest['spatial'], True)
    control_cfg = deepcopy(cfg)
    control_cfg['data']['dynamic_columns'] = cfg['control']['dynamic_columns']
    control_cfg['data']['forecast_columns'] = cfg['control']['forecast_columns']
    control_cfg['data']['reanalysis_columns'] = cfg['control']['forecast_columns']
    control_cfg['spatial']['mode'] = 'catchment_mean'
    control_cfg['model']['hidden_size'] = 64
    control_ds, control_q, control_ck = load_member(control_cfg, manifest['control'], False)
    if spatial_ds.samples != control_ds.samples:
        raise ValueError('The spatial model and mean control have different test samples')

    # Confirm that area-aggregating the very same noisy band forecasts yields the control inputs.
    sample_ids = sorted(set([0, len(spatial_ds) // 2, len(spatial_ds) - 1]))
    weights = np.asarray(cfg['spatial']['area_weights'])
    for index in sample_ids:
        a = spatial_ds[index]['future'].numpy()
        b = control_ds[index]['future'].numpy()
        ns = len(cfg['data']['forecast_columns'])
        a = a[:, :ns] * np.asarray(spatial_ck['statistics']['forecast']['scale']) + np.asarray(spatial_ck['statistics']['forecast']['center'])
        b = b[:, :2] * np.asarray(control_ck['statistics']['forecast']['scale']) + np.asarray(control_ck['statistics']['forecast']['center'])
        expected = np.sum(a.reshape(-1, 4, 2) * weights[None, :, None], axis=1)
        np.testing.assert_allclose(expected, b, atol=1e-4, equal_nan=True)

    store = spatial_ds.store
    frame = next(iter(store.frames.values()))
    threshold = float(cfg['evaluation']['flood_threshold_cumecs'])
    qidx = cfg['model']['quantiles'].index(0.5)
    preds = {'Spatial_ElevationBand': spatial_q[:, :, qidx], 'CatchmentMean_Control': control_q[:, :, qidx]}
    rows = []
    seasonal_rows = []
    calibration = []
    for model_name, forecasts in preds.items():
        for i, (basin, origin) in enumerate(spatial_ds.samples):
            issue_date = frame.index[origin]
            for lead in range(cfg['data']['forecast_horizon']):
                target_date = issue_date + pd.Timedelta(days=lead + 1)
                observed = frame.loc[target_date, 'q_cumecs']
                qvalues = spatial_q[i, lead] if model_name == 'Spatial_ElevationBand' else control_q[i, lead]
                rows.append({'basin_id': basin, 'issue_date': issue_date, 'target_date': target_date,
                             'lead_day': lead + 1, 'season': ('Oct-Mar' if target_date.month in (10, 11, 12, 1, 2, 3)
                             else 'Apr-Jun' if target_date.month in (4, 5, 6) else 'Jul-Sep'),
                             'observed_cumecs': observed, model_name: forecasts[i, lead]})
                if model_name == 'Spatial_ElevationBand' and np.isfinite(observed):
                    calibration.append({'lead_day': lead + 1, 'observed': observed,
                                         'lower': spatial_q[i, lead, 0], 'upper': spatial_q[i, lead, -1]})

    out = resolve(cfg, cfg['evaluation']['output_dir'])
    out.mkdir(parents=True, exist_ok=True)
    full = pd.DataFrame(rows)
    # Keep a simple one-prediction-column file for the shared evaluation skill.
    for name, column, filename in [('Spatial_ElevationBand', 'Spatial_ElevationBand', 'predictions.csv'),
                                    ('CatchmentMean_Control', 'CatchmentMean_Control', 'control_predictions.csv')]:
        cols = ['basin_id', 'issue_date', 'target_date', 'lead_day', 'season', 'observed_cumecs']
        one = full[cols + [column]].dropna(subset=['observed_cumecs', column]).copy()
        one.to_csv(out / filename, index=False, na_rep='NaN')

    long_scores = []
    # The prediction CSVs contain one model column each for direct comparison.
    for name, forecast in preds.items():
        group_source = full.dropna(subset=['observed_cumecs'])
        for lead, group in group_source.groupby('lead_day'):
            vals = group[group[name].notna()]
            long_scores.append({'model': name, 'lead_day': lead, **scores(vals.observed_cumecs, vals[name], threshold)})
            for season, sg in vals.groupby('season'):
                seasonal_rows.append({'model': name, 'lead_day': lead, 'season': season,
                                      **scores(sg.observed_cumecs, sg[name], threshold)})
    score_frame = pd.DataFrame(long_scores)
    seasonal_frame = pd.DataFrame(seasonal_rows)
    score_frame.to_csv(out / 'scores_by_lead.csv', index=False)
    seasonal_frame.to_csv(out / 'scores_by_season_and_lead.csv', index=False)
    cal_rows = []
    calibration_frame = pd.DataFrame(calibration)
    for lead, group in calibration_frame.groupby('lead_day'):
        cal_rows.append({'lead_day': lead, 'n': len(group),
                         'coverage_90': group.observed.between(group.lower, group.upper).mean()})
    cal = pd.DataFrame(cal_rows)
    cal.to_csv(out / 'quantile_calibration.csv', index=False)

    source = Path(cfg['preparation']['observed_daily_source'])
    source = (ROOT / source).resolve()
    original = pd.read_csv(source, parse_dates=['date'])
    original = original.set_index('date').q_cumecs.reindex(frame.index)
    pd.testing.assert_series_equal(frame.q_cumecs, original, check_names=False, check_dtype=False)
    verification = {'source_target_values_unchanged': True, 'missing_targets_left_nan': True,
                    'test_years': [2022, 2023, 2024],
                    'spatial_and_control_share_test_origins': True, 'same_noisy_forecast_after_area_aggregation': True,
                    'flood_threshold_cumecs': threshold, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'daily_sha256': hashlib.sha256(resolve(cfg, cfg['data']['daily_file']).read_bytes()).hexdigest()}
    (out / 'verification.json').write_text(json.dumps(verification, indent=2) + '\n', encoding='utf-8')

    final = score_frame[score_frame.lead_day.eq(30)]
    summary = ['# Spatial elevation-band LSTM: 30-day evaluation', '',
               'Observed discharge targets were retained as recorded; missing targets were excluded from loss and scoring. Future reanalysis with lead-dependent noise is a stand-in, not archived forecast data.', '',
               f'Test years: 2022–2024. Flood threshold: {threshold:.3f} m³/s (training Q95). Observed target pairs: {int(full.observed_cumecs.notna().sum() / 2)}.', '',
               '## Lead 30 overall', '', final.to_markdown(index=False, floatfmt='.3f'), '',
               '## Lead 30 by season', '', seasonal_frame[seasonal_frame.lead_day.eq(30)].to_markdown(index=False, floatfmt='.3f'), '',
               '## Quantile coverage', '', cal[cal.lead_day.eq(30)].to_markdown(index=False, floatfmt='.3f'), '',
               '## Architecture and inputs', '', 'Each of four elevation bands has its own 365-day encoder and 30-day decoder. Area-weighted decoder features feed a shared monotonic quantile head. Rain, temperature, SWE and snowmelt are inputs to the history encoders; per-band rain and temperature reanalysis with lead-growing noise are decoder inputs. A same-source catchment-mean LSTM was trained as the spatial ablation control.', '',
               'Weather bands cover 2015–2024. Training uses 2016–2020, validation 2021, and held-out test targets 2022–2024. The 2022–2024 period was inspected in prior workspace experiments and is not an untouched project-wide holdout.', '',
               'NSE is not a percentage accuracy. These retrospective test scores do not establish operational forecast skill because realized reanalysis is used as a noisy future-weather proxy. Sparse flood observations also limit flood-case conclusions.', '']
    (out / 'evaluation_report.md').write_text('\n'.join(summary), encoding='utf-8')
    readme = ROOT / 'README.md'
    (ROOT / 'RUN_RESULTS.md').write_text('\n'.join(summary), encoding='utf-8')
    print(final.to_string(index=False), flush=True)
    print('Report:', out / 'evaluation_report.md', flush=True)


if __name__ == '__main__':
    main()
