"""Nonnegative per-lead blending; weights are learned on validation only."""
import numpy as np
from sklearn.linear_model import LinearRegression


class ConvexEnsemble:
    def __init__(self, options):
        self.options = options
        self.members = options['members']

    def fit(self, predictions, targets):
        stacked = np.stack([predictions[name] for name in self.members], axis=-1)
        self.weights = []
        for lead in range(targets.shape[1]):
            valid = np.isfinite(targets[:, lead]) & np.isfinite(stacked[:, lead]).all(axis=1)
            if self.options['fit_validation_weights']:
                if valid.sum() < 5:
                    raise ValueError('Not enough observed validation targets to fit ensemble weights')
                reg = LinearRegression(positive=True, fit_intercept=False).fit(stacked[valid, lead], targets[valid, lead])
                weights = reg.coef_
            else:
                weights = np.asarray(self.options['fixed_weights'], dtype=float)
            if len(weights) != len(self.members) or (weights < 0).any():
                raise ValueError('Provide one nonnegative ensemble weight per member')
            if weights.sum() == 0:
                weights = np.ones(len(self.members))
            self.weights.append((weights / weights.sum()).tolist())
        return self

    def predict(self, predictions):
        stacked = np.stack([predictions[name] for name in self.members], axis=-1)
        return (stacked * np.asarray(self.weights)[None]).sum(axis=-1)
