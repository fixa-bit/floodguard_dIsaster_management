"""Month/day flow means fitted only on training years."""
import numpy as np
import pandas as pd

from data import years


class Climatology:
    def fit(self, store):
        records = []
        for basin, frame in store.frames.items():
            train = frame[frame.index.year.isin(years(store.cfg['splits']['train']))]
            records.extend((basin, day.strftime('%m-%d'), q) for day, q in train[store.d['target_column']].dropna().items())
        frame = pd.DataFrame(records, columns=['basin', 'month_day', 'q'])
        self.daily = frame.groupby(['basin', 'month_day'])['q'].mean().to_dict()
        self.basin_mean = frame.groupby('basin')['q'].mean().to_dict()
        self.global_mean = frame['q'].mean()
        return self

    def predict(self, dataset):
        horizon = dataset.d['forecast_horizon']
        result = np.empty((len(dataset), horizon))
        for index in range(len(dataset)):
            basin, issue = dataset.metadata(index)
            for lead in range(horizon):
                key = basin, (issue + pd.Timedelta(days=lead + 1)).strftime('%m-%d')
                result[index, lead] = self.daily.get(key, self.basin_mean.get(basin, self.global_mean))
        return result
