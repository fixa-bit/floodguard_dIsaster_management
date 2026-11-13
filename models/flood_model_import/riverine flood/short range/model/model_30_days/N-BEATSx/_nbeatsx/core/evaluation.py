"""Project evaluation utilities bundled with this model."""
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
from .data import StreamflowDataset, inverse_flow
from .training import check_evaluation_years, device_for
from .lstm_model import HindcastForecastLSTM


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

