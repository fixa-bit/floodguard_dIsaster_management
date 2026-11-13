"""Validation-only shrinkage toward climatology and empirical interval correction."""
import numpy as np


def fit_postprocessing(mean, quantiles, baseline, targets, mask, cfg):
    rows = []
    for low, high in cfg['postprocessing']['lead_groups']:
        sl = slice(low - 1, high)
        valid = mask[:, sl] & np.isfinite(targets[:, sl])
        y, c, p = targets[:, sl][valid], baseline[:, sl][valid], mean[:, sl][valid]
        difference = p - c
        denominator = np.dot(difference, difference)
        alpha = float(np.clip(np.dot(y - c, difference) / denominator, 0, 1)) if denominator > 0 else 0.
        if not cfg['postprocessing']['fit_climatology_blend']:
            alpha = 1.
        q = baseline[:, sl, None] + alpha * (quantiles[:, sl] - baseline[:, sl, None])
        offsets = []
        for index, level in enumerate(cfg['model']['quantiles']):
            error = (targets[:, sl] - q[:, :, index])[valid]
            offsets.append(float(np.quantile(error, level)) if cfg['postprocessing']['calibrate_quantiles'] else 0.)
        prediction = c + alpha * difference
        rows.append({'leads': [low, high], 'alpha': alpha, 'quantile_offsets_cumecs': offsets,
                     'validation_pairs': int(valid.sum()),
                     'validation_climatology_mse': float(np.mean((y - c) ** 2)),
                     'validation_blended_mse': float(np.mean((y - prediction) ** 2))})
    return {'fitted_on': '2021 validation only', 'lead_groups': rows,
            'empirical_calibration': True,
            'coverage_guarantee': False,
            'selection_and_calibration_reuse_same_validation_year': True}


def apply_postprocessing(mean, quantiles, baseline, options):
    point = np.empty_like(mean, dtype=np.float64)
    intervals = np.empty_like(quantiles, dtype=np.float64)
    for group in options['lead_groups']:
        low, high = group['leads']
        sl = slice(low - 1, high)
        alpha = group['alpha']
        point[:, sl] = baseline[:, sl] + alpha * (mean[:, sl] - baseline[:, sl])
        intervals[:, sl] = baseline[:, sl, None] + alpha * (quantiles[:, sl] - baseline[:, sl, None])
        intervals[:, sl] += np.asarray(group['quantile_offsets_cumecs'])[None, None]
    return np.maximum(point, 0), np.sort(np.maximum(intervals, 0), axis=-1)
