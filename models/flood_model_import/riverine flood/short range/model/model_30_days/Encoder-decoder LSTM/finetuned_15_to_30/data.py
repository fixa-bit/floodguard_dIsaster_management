"""Training-only calendar baselines and observed-only 30-day residual targets."""
import numpy as np
import pandas as pd
import torch

from _core_data import (DataStore, StreamflowDataset, fit_statistics as core_statistics,
                        load_config, public_config, resolve, years)


def calendar_curves(series, window):
    if window < 1 or window % 2 != 1:
        raise ValueError('Climatology smoothing window must be positive and odd')
    calendar = pd.date_range('2000-01-01', '2000-12-31').strftime('%m-%d')
    known = series.dropna()
    if known.empty:
        raise ValueError('No observed training targets for climatology')
    grouped = known.groupby(known.index.strftime('%m-%d')).agg(['sum', 'count'])
    sums = grouped['sum'].reindex(calendar, fill_value=0).to_numpy(float)
    counts = grouped['count'].reindex(calendar, fill_value=0).to_numpy(float)
    fallback = float(known.mean())
    exact = np.divide(sums, counts, out=np.full(366, fallback), where=counts > 0)
    half = window // 2
    smooth_sum = sum(np.roll(sums, shift) for shift in range(-half, half + 1))
    smooth_count = sum(np.roll(counts, shift) for shift in range(-half, half + 1))
    smooth = np.divide(smooth_sum, smooth_count, out=np.full(366, fallback), where=smooth_count > 0)
    return {'exact': dict(zip(calendar, exact.tolist())),
            'smooth': dict(zip(calendar, smooth.tolist())), 'fallback': fallback}


def fit_statistics(store):
    stats = core_statistics(store)
    q = []
    stats['climatology'] = {}
    for basin, frame in store.frames.items():
        selected = frame.loc[frame.index.year.isin(years(store.cfg['splits']['train'])), store.d['target_column']]
        q.extend(selected.dropna().tolist())
        curves = calendar_curves(selected, store.cfg['model']['smooth_climatology_window'])
        curves['leave_year_out'] = {
            str(year): calendar_curves(selected.loc[selected.index.year != year], store.cfg['model']['smooth_climatology_window'])
            for year in years(store.cfg['splits']['train'])
        }
        stats['climatology'][basin] = curves
    stats['flow_std_cumecs'] = max(float(np.std(q)), 1.)
    stats['flow_mean_cumecs'] = float(np.mean(q))
    stats['flood_threshold_cumecs'] = float(np.quantile(q, store.cfg['evaluation']['flood_percentile']))
    return stats


class ResidualDataset(StreamflowDataset):
    def __init__(self, store, split, stats, **kwargs):
        super().__init__(store, split, stats, **kwargs)
        self.split = split

    def __getitem__(self, index):
        item = super().__getitem__(index)
        basin, position = self.samples[index]
        frame = self.store.frames[basin]
        dates = frame.index[position + 1:position + 1 + self.d['forecast_horizon']]
        curves = self.stats['climatology'][basin]
        exact, smooth = [], []
        for date in dates:
            # Cross-fit the training anchor; the target year cannot set its own mean.
            selected = curves['leave_year_out'][str(date.year)] if self.split == 'train' else curves
            key = date.strftime('%m-%d')
            exact.append(selected['exact'].get(key, selected['fallback']))
            smooth.append(selected['smooth'].get(key, selected['fallback']))
        item['climatology'] = torch.tensor(exact, dtype=torch.float32)
        item['smooth_climatology'] = torch.tensor(smooth, dtype=torch.float32)
        raw = frame[self.d['target_column']].iloc[position + 1:position + 1 + self.d['forecast_horizon']].to_numpy(np.float32, copy=True)
        item['target_q'] = torch.from_numpy(raw)
        return item
