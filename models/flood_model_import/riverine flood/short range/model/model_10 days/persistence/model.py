"""Hold the latest observed flow known at issue time; never fill the target table."""
import numpy as np


class Persistence:
    def predict(self, dataset):
        horizon = dataset.d['forecast_horizon']
        prediction = np.full((len(dataset), horizon), np.nan)
        for index, (basin, position) in enumerate(dataset.samples):
            q = dataset.store.frames[basin][dataset.d['target_column']].iloc[:position + 1].dropna()
            if len(q):
                prediction[index] = q.iloc[-1]
        return prediction
