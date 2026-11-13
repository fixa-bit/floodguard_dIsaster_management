"""Persistence and calendar climatology use observed training/issue data only."""
import numpy as np
from data import years


class Baselines:
    def __init__(self, store):
        self.store = store
        self.climatology = {}
        for basin, frame in store.frames.items():
            train = frame.loc[frame.index.year.isin(years(store.cfg['splits']['train'])), store.d['target_column']].dropna()
            self.climatology[basin] = (train.groupby(train.index.strftime('%m-%d')).mean().to_dict(), float(train.mean()))

    def predict(self, basin, issue, target):
        known = self.store.frames[basin].loc[:issue, self.store.d['target_column']].dropna()
        persistence = float(known.iloc[-1]) if len(known) else np.nan
        means, default = self.climatology[basin]
        return persistence, means.get(target.strftime('%m-%d'), default)
