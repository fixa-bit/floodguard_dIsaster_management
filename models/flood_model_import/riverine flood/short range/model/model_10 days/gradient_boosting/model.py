"""Direct lead-specific sklearn models on summaries of the same input channels."""
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from data import StreamflowDataset, inverse_flow


def feature_vector(item, lead, windows):
    history, future, static = (item[k].numpy() for k in ('history', 'future', 'static'))
    parts = []
    for window in windows:
        segment = history[-min(window, len(history)):]
        parts.extend([segment.mean(axis=0), segment.std(axis=0)])
    parts.extend([future[:lead + 1].ravel(), static, np.array([(lead + 1) / len(future)])])
    return np.concatenate(parts)


class GradientBoosting:
    def fit(self, store, stats):
        self.cfg, self.stats = store.cfg, stats
        options = self.cfg['baselines']
        train = StreamflowDataset(store, 'train', stats)
        items = [train[i] for i in range(len(train))]
        self.models = []
        for lead in range(store.d['forecast_horizon']):
            features = np.stack([feature_vector(item, lead, options['history_summary_windows']) for item in items])
            target = np.array([float(item['target'][lead]) for item in items])
            valid = np.isfinite(target)
            if valid.sum() < 2:
                self.models.append(None)
                continue
            model = HistGradientBoostingRegressor(max_iter=options['boosting_iterations'],
                learning_rate=options['boosting_learning_rate'], max_leaf_nodes=options['boosting_max_leaf_nodes'],
                l2_regularization=options['boosting_l2'], early_stopping=False,
                random_state=self.cfg['training']['seeds'][0])
            model.fit(features[valid], target[valid])
            self.models.append(model)
            print(f'Boosting lead {lead + 1}: {valid.sum()} observed training targets', flush=True)
        return self

    def predict(self, dataset):
        result = np.full((len(dataset), dataset.d['forecast_horizon']), np.nan)
        items = [dataset[i] for i in range(len(dataset))]
        for lead, model in enumerate(self.models):
            if model is not None:
                features = np.stack([feature_vector(item, lead, self.cfg['baselines']['history_summary_windows']) for item in items])
                result[:, lead] = inverse_flow(model.predict(features), self.stats)
        return result
