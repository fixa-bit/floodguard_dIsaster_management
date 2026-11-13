"""Daily alignment, training-only statistics and masked multi-basin samples."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset
import yaml


def load_config(path):
    path = Path(path).resolve()
    with path.open() as f:
        cfg = yaml.safe_load(f)
    cfg['_root'] = str(path.parent)
    cfg['_config_path'] = str(path)
    ranges = {key: set(years(value)) for key, value in cfg['splits'].items()}
    for a, b in [('train', 'validation'), ('train', 'test'), ('validation', 'test')]:
        if ranges[a] & ranges[b] or max(ranges[a]) >= min(ranges[b]):
            raise ValueError('Use disjoint chronological train, validation and test year ranges')
    return cfg


def years(bounds):
    return list(range(int(bounds[0]), int(bounds[1]) + 1))


def resolve(cfg, path):
    return (Path(cfg['_root']) / path).resolve()


def public_config(cfg):
    return {k: v for k, v in cfg.items() if not k.startswith('_')}


def read_daily(path, date_col='date', dtype=None):
    frame = pd.read_csv(path, parse_dates=[date_col], dtype=dtype).rename(columns={date_col: 'date'})
    if frame['date'].isna().any() or not frame['date'].equals(frame['date'].dt.normalize()):
        raise ValueError(f'Invalid or non-daily date labels in {path}')
    return frame


def prepare(cfg):
    """Create a separate source-traceable table; targets remain observed or NaN."""
    p, d = cfg['preparation'], cfg['data']
    targets, source_names, provenance = [], [], []
    def read(spec):
        path = resolve(cfg, spec['path'])
        provenance.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        return read_daily(path).set_index('date')
    for spec in p['target_sources']:
        frame = read(spec)
        q = pd.to_numeric(frame[spec['column']], errors='raise') * spec['factor_to_cumecs']
        keep = np.isfinite(q)
        if spec.get('exclude_nonpositive'):
            keep &= q.gt(0)
        for column, expected in spec.get('require', {}).items():
            keep &= frame[column].eq(expected)
        candidates = q[keep]
        unambiguous = candidates.groupby(level=0).nunique().eq(1)
        candidates = candidates[candidates.index.isin(unambiguous[unambiguous].index)]
        targets.append(candidates.groupby(level=0).first())
        source_names.append(spec['source'])
    target = pd.Series(dtype=float)
    source = pd.Series(dtype=object)
    for q, name in zip(targets, source_names):
        new = q.index.difference(target.dropna().index)
        source = source.combine_first(pd.Series(name, index=new))
        target = target.combine_first(q)
    inputs = []
    for spec in p['dynamic_sources']:
        frame = read(spec)
        if frame.index.has_duplicates:
            raise ValueError('Duplicate dynamic-source dates')
        inputs.append(frame[list(spec['columns'])].rename(columns=spec['columns']))
    merged = pd.concat(inputs, axis=1, sort=True).sort_index()
    calendar = pd.date_range(merged.index.min(), max(merged.index.max(), target.index.max()))
    merged = merged.reindex(calendar)
    merged[d['target_column']] = target.reindex(calendar)
    merged['q_source'] = source.reindex(calendar)
    merged[d['basin_column']] = p['basin_id']
    merged.index.name = d['date_column']
    output = resolve(cfg, d['daily_file'])
    if output.exists():
        raise FileExistsError('Prepared output already exists. Choose a new daily_file in config; existing datasets are never overwritten.')
    if any(str(output) == r['path'] for r in provenance):
        raise ValueError('Output must not overwrite a source')
    output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output, na_rep='NaN')
    for item in provenance:
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Source changed during preparation')
    report = {'output': str(output), 'observed_target_days': int(target.notna().sum()),
              'target_nan_days': int(merged[d['target_column']].isna().sum()),
              'no_discharge_filling': True, 'sources': provenance}
    output.with_suffix('.provenance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'sources'}, indent=2))


class DataStore:
    def __init__(self, cfg):
        self.cfg, self.d = cfg, cfg['data']
        basin = self.d['basin_column']
        frame = read_daily(resolve(cfg, self.d['daily_file']), self.d['date_column'], dtype={basin: str})
        if basin not in frame:
            frame[basin] = self.d['default_basin_id']
        if frame[basin].isna().any() or frame.duplicated([basin, 'date']).any():
            raise ValueError('Missing basin ID or duplicate basin/date')
        frame[basin] = frame[basin].astype(str)
        columns = set(self.d['dynamic_columns'] + [self.d['target_column']])
        if self.d['forecast_mode'] == 'reanalysis_with_noise':
            columns.update(self.d['reanalysis_columns'])
        for column in columns:
            frame[column] = pd.to_numeric(frame[column], errors='raise')
            if np.isinf(frame[column]).any():
                raise ValueError(f'Infinite values in {column}; preserve source and review it')
        if frame[self.d['target_column']].dropna().lt(0).any():
            raise ValueError('Observed discharge must be nonnegative or NaN')
        self.frames = {}
        for name, group in frame.groupby(basin):
            group = group.set_index('date').sort_index()
            calendar = pd.date_range(group.index.min(), group.index.max())
            self.frames[name] = group.reindex(calendar)
        self.static = None
        if self.d['use_static']:
            if not self.d['static_file'] or not self.d['static_columns']:
                raise ValueError('Static mode needs static_file and static_columns')
            self.static = pd.read_csv(resolve(cfg, self.d['static_file']), dtype={basin: str})
            if basin not in self.static:
                if len(self.frames) != 1 or len(self.static) != 1:
                    raise ValueError('Multi-basin static file requires basin_id')
                self.static[basin] = next(iter(self.frames))
            self.static[basin] = self.static[basin].astype(str)
            if self.static[basin].duplicated().any():
                raise ValueError('Duplicate static basin ID')
            self.static = self.static.set_index(basin)
        self.archive = None
        if self.d['forecast_mode'] == 'archived_forecast':
            if not self.d['forecast_file']:
                raise ValueError('archived_forecast needs a forecast_file')
            archive = read_daily(resolve(cfg, self.d['forecast_file']), self.d['forecast_date_column'], dtype={basin: str})
            if basin not in archive:
                archive[basin] = self.d['default_basin_id']
            archive[basin] = archive[basin].astype(str)
            lead = self.d['forecast_lead_column']
            archive[lead] = pd.to_numeric(archive[lead], errors='raise')
            if archive[lead].isna().any() or not archive[lead].eq(archive[lead].astype(int)).all() or archive[lead].lt(1).any():
                raise ValueError('Forecast lead_day must contain positive integers')
            if archive.duplicated([basin, 'date', lead]).any():
                raise ValueError('Use one forecast run/ensemble summary per basin/issue/lead')
            available = self.d.get('forecast_available_at_column')
            if available:
                published = pd.to_datetime(archive[available], utc=True, errors='raise')
                issued = archive['date'].dt.tz_localize('UTC') + pd.Timedelta(hours=self.d['issue_hour_utc'])
                if published.isna().any() or published.gt(issued).any():
                    raise ValueError('A forecast record was published after its issue time')
            for column in self.d['forecast_columns']:
                archive[column] = pd.to_numeric(archive[column], errors='raise')
                if np.isinf(archive[column]).any():
                    raise ValueError('Infinite forecast value')
            self.archive = archive.set_index([basin, 'date', lead]).sort_index()
        elif self.d['forecast_mode'] != 'reanalysis_with_noise':
            raise ValueError('Unknown forecast_mode')
        if len(self.d['forecast_columns']) != len(self.d['reanalysis_columns']):
            raise ValueError('Forecast and reanalysis feature mappings must have equal lengths')

    def static_values(self, basin):
        if self.static is None:
            return np.empty(0)
        if basin not in self.static.index:
            return np.full(len(self.d['static_columns']), np.nan)
        return self.static.loc[basin, self.d['static_columns']].to_numpy(dtype=float)


def stats_for(array, mode):
    a = np.asarray(array, dtype=float)
    if a.ndim == 1:
        a = a[:, None]
    count = np.isfinite(a).sum(axis=0)
    if not count.all():
        raise ValueError('An input has no finite training observations; remove it or supply training data')
    mean, std = np.nanmean(a, axis=0), np.nanstd(a, axis=0)
    if mode not in ('standard', 'center', 'none'):
        raise ValueError('Normalization must be standard, center or none')
    return {'mean': mean.tolist(), 'center': (mean if mode != 'none' else np.zeros_like(mean)).tolist(),
            'scale': (np.maximum(std, 1e-6) if mode == 'standard' else np.ones_like(mean)).tolist(), 'count': count.tolist()}


def normalize(array, stats):
    a = np.array(array, dtype=np.float32, copy=True)
    missing = ~np.isfinite(a)
    center, scale, mean = (np.asarray(stats[k], dtype=np.float32) for k in ('center', 'scale', 'mean'))
    normalized = (a - center) / scale
    # Fill predictor channels only, after transformation. Targets never use this.
    normalized = np.where(missing, (mean - center) / scale, normalized)
    return np.concatenate([normalized, missing.astype(np.float32)], axis=-1)


def fit_statistics(store):
    cfg, d = store.cfg, store.d
    training_years = years(cfg['splits']['train'])
    dynamic, flow, forecast = [], [], []
    basins = []
    for basin, frame in store.frames.items():
        train = frame[frame.index.year.isin(training_years)]
        if train.empty:
            continue
        basins.append(basin)
        dynamic.append(train[d['dynamic_columns']].to_numpy(float))
        flow.append(train[d['target_column']].to_numpy(float))
        if store.archive is None:
            forecast.append(train[d['reanalysis_columns']].to_numpy(float))
    q = np.concatenate(flow) if flow else np.array([])
    q = q[np.isfinite(q)]
    if not len(q):
        raise ValueError('No observed training flow')
    if store.archive is not None:
        archive = store.archive.reset_index()
        valid_year = (archive['date'] + pd.to_timedelta(archive[d['forecast_lead_column']], unit='D')).dt.year
        archive = archive[archive['date'].dt.year.isin(training_years) & valid_year.isin(training_years)]
        forecast = [archive[d['forecast_columns']].to_numpy(float)]
    logarithm = np.log1p(q / cfg['normalization']['flow_scale_cumecs'])
    standard = cfg['normalization']['standardize_log_flow']
    result = {'dynamic': stats_for(np.concatenate(dynamic), cfg['normalization']['inputs']),
              'forecast': stats_for(np.concatenate(forecast), cfg['normalization']['inputs']),
              'flow': {'mean': float(logarithm.mean()) if standard else 0.0,
                       'std': max(float(logarithm.std()), 1e-6) if standard else 1.0,
                       'training_log_mean': float(logarithm.mean()),
                       'scale': cfg['normalization']['flow_scale_cumecs']},
              'static': stats_for(np.stack([store.static_values(b) for b in basins]), cfg['normalization']['static']) if d['use_static'] else None,
              'training_years': training_years,
              'schema': {k: d[k] for k in ('dynamic_columns', 'forecast_columns', 'static_columns', 'use_static', 'past_discharge', 'calendar_features')}}
    return result


def inverse_flow(values, stats):
    f = stats['flow']
    return np.maximum(0, np.expm1(np.asarray(values, dtype=float) * f['std'] + f['mean']) * f['scale'])


class StreamflowDataset(Dataset):
    def __init__(self, store, split, stats, training_noise=False, seed=42):
        self.store, self.cfg, self.d, self.stats = store, store.cfg, store.d, stats
        self.training_noise, self.seed, self.epoch = training_noise, seed, 0
        schema = {k: self.d[k] for k in stats['schema']}
        if schema != stats['schema']:
            raise ValueError('Checkpoint feature schema differs; preserve column meaning and order')
        self.samples = []
        allowed = years(self.cfg['splits'][split])
        h, horizon = self.d['hindcast_length'], self.d['forecast_horizon']
        self.arrays = {}
        for basin, frame in store.frames.items():
            self.arrays[basin] = {'x': frame[self.d['dynamic_columns']].to_numpy(np.float32),
                                  'q': frame[self.d['target_column']].to_numpy(np.float32)}
            for i in range(h - 1, len(frame) - horizon):
                target_dates = frame.index[i + 1:i + 1 + horizon]
                if not target_dates.year.isin(allowed).all():
                    continue
                if np.isfinite(self.arrays[basin]['q'][i + 1:i + 1 + horizon]).any():
                    self.samples.append((basin, i))
        if not self.samples:
            raise ValueError(f'No {split} samples after calendar/context/split alignment')

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        basin, i = self.samples[index]
        frame, a = self.store.frames[basin], self.arrays[basin]
        h, horizon = self.d['hindcast_length'], self.d['forecast_horizon']
        history = normalize(a['x'][i - h + 1:i + 1], self.stats['dynamic'])
        flow_stats = self.stats['flow']
        if self.d['past_discharge']:
            past_q = a['q'][i - h + 1:i + 1]
            missing = ~np.isfinite(past_q)
            log_q = (np.log1p(past_q / flow_stats['scale']) - flow_stats['mean']) / flow_stats['std']
            fill = (flow_stats['training_log_mean'] - flow_stats['mean']) / flow_stats['std']
            history = np.column_stack([history, np.where(missing, fill, log_q), missing])
        if self.d['calendar_features']:
            angle = 2 * np.pi * frame.index[i - h + 1:i + 1].day_of_year.to_numpy() / 365.25
            history = np.column_stack([history, np.sin(angle), np.cos(angle)])
        if self.store.archive is None:
            raw_future = frame[self.d['reanalysis_columns']].iloc[i + 1:i + 1 + horizon].to_numpy(float)
        else:
            keys = pd.MultiIndex.from_tuples([(basin, frame.index[i], lead) for lead in range(1, horizon + 1)], names=self.store.archive.index.names)
            raw_future = self.store.archive.reindex(keys)[self.d['forecast_columns']].to_numpy(float)
        future = normalize(raw_future, self.stats['forecast'])
        if self.store.archive is None:
            noise_cfg = self.d['noise']
            parts = [self.seed, self.epoch, index] if self.training_noise else [noise_cfg['evaluation_seed'], index]
            rng = np.random.default_rng(np.random.SeedSequence(parts))
            std = noise_cfg['std_at_lead_1'] + np.arange(horizon) * noise_cfg['std_growth_per_lead']
            n = len(self.d['forecast_columns'])
            noisy = future[:, :n] + rng.normal(size=(horizon, n)) * std[:, None]
            future[:, :n] = np.where(future[:, n:] == 0, noisy, future[:, :n])
        raw_target = a['q'][i + 1:i + 1 + horizon].copy()
        target = (np.log1p(raw_target / flow_stats['scale']) - flow_stats['mean']) / flow_stats['std']
        static = normalize(self.store.static_values(basin), self.stats['static']) if self.d['use_static'] else np.empty(0, np.float32)
        return {'history': torch.tensor(history, dtype=torch.float32), 'future': torch.tensor(future, dtype=torch.float32),
                'static': torch.tensor(static, dtype=torch.float32), 'target': torch.tensor(target, dtype=torch.float32),
                'mask': torch.tensor(np.isfinite(raw_target)), 'index': index}

    def dimensions(self):
        item = self[0]
        return item['history'].shape[-1], item['future'].shape[-1], item['static'].shape[-1]

    def metadata(self, index):
        basin, i = self.samples[index]
        return basin, self.store.frames[basin].index[i]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--prepare', action='store_true')
    arguments = parser.parse_args()
    configuration = load_config(arguments.config)
    if arguments.prepare:
        prepare(configuration)
    else:
        storage = DataStore(configuration)
        statistics = fit_statistics(storage)
        print({s: len(StreamflowDataset(storage, s, statistics)) for s in configuration['splits']})
