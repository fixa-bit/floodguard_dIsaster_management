"""Observed-target scores with a training-only high-flow threshold."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def metrics(y, p, threshold):
    y, p = np.asarray(y, float), np.asarray(p, float)
    valid = np.isfinite(y) & np.isfinite(p)
    y, p = y[valid], p[valid]
    if not len(y):
        return {'n': 0}
    error = p - y
    variance = ((y - y.mean()) ** 2).sum()
    kge = np.nan
    if len(y) > 1 and y.std() > 0 and p.std() > 0 and y.mean() > 0:
        kge = 1 - np.sqrt((np.corrcoef(y, p)[0, 1] - 1) ** 2 + (p.std() / y.std() - 1) ** 2 + (p.mean() / y.mean() - 1) ** 2)
    flood, alerts = y > threshold, p > threshold
    hits, false = int((flood & alerts).sum()), int((~flood & alerts).sum())
    return {'n': len(y), 'NSE': 1 - (error ** 2).sum() / variance if variance > 0 else np.nan,
            'KGE': kge, 'RMSE_cumecs': float(np.sqrt((error ** 2).mean())), 'MAE_cumecs': float(np.abs(error).mean()),
            'PBIAS_pct': 100 * error.sum() / y.sum() if y.sum() else np.nan,
            'peak_n': int(flood.sum()), 'peak_MAPE_pct': 100 * np.abs(error[flood] / y[flood]).mean() if flood.any() else np.nan,
            'flood_hit_rate': hits / flood.sum() if flood.any() else np.nan,
            'false_alarm_rate': false / (~flood).sum() if (~flood).any() else np.nan,
            'false_alarm_ratio': false / alerts.sum() if alerts.any() else np.nan}


def markdown(frame):
    def show(x):
        return 'NA' if pd.isna(x) else f'{x:.3f}' if isinstance(x, (float, np.floating)) else str(x)
    return '\n'.join(['| ' + ' | '.join(frame.columns) + ' |', '| ' + ' | '.join(['---'] * len(frame.columns)) + ' |'] +
                     ['| ' + ' | '.join(show(x) for x in row) + ' |' for row in frame.itertuples(index=False, name=None)])
