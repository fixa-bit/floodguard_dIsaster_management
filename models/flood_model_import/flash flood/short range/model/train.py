"""Train and evaluate the Pakistan flash-flood model: probability of a reported flood onset in each
20 km cell in the next 24 hours (one Pakistan-local day).

Models
    climatology      cell x month onset rate from the training years, with its odds scaled by the national
                     reporting volume of the previous 365 days (news coverage grew about tenfold after 2010)
    rain_trigger     logistic regression on the climatology logit plus the day's rainfall (forecast mode)
    lightgbm         gradient-boosted trees started from the climatology (as an offset), adding rainfall,
                     antecedent wetness, snowmelt, terrain, land cover, population and recent reporting;
                     trained in two modes:
                       forecast  - adds the target day's realised IMERG rain as a perfect-forecast stand-in
                       observed  - only information known before the target day
                     plus an ablation, weather_only: forecast mode without any news-reporting inputs
Splits: train 2010-2019, validation 2020-2021 (early stopping, alarm threshold), test 2022-01-01 to 2026-01-31.

Run from this folder: ../../.venv/Scripts/python.exe train.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

import data

ROOT = Path(__file__).resolve().parent
REPORTS, RUNS = ROOT / "reports", ROOT / "runs"
SPLITS = {"train": ("2010-01-01", "2019-12-31"), "val": ("2020-01-01", "2021-12-31"), "test": ("2022-01-01", "2026-01-31")}
NEGATIVE_RATE = 0.1
SEED = 20261113
CHENAB_MIN_FRACTION = 0.25
PARAMS = {"objective": "binary", "metric": ["average_precision", "binary_logloss"], "first_metric_only": True, "learning_rate": 0.03, "num_leaves": 63, "min_data_in_leaf": 300, "feature_fraction": 0.8,
          "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1, "seed": SEED, "num_threads": 8}


def split_index(grid, name):
    start, end = (np.datetime64(value) for value in SPLITS[name])
    days = np.flatnonzero((grid.dates >= start) & (grid.dates <= end))
    label = grid.label[days]
    day_pos, cell = np.nonzero(label >= 0)
    return days[day_pos], cell, label[day_pos, cell].astype(np.int8)


def subsample(day, cell, y, rate, seed):
    rng = np.random.default_rng(seed)
    keep = (y == 1) | (rng.random(len(y)) < rate)
    weight = np.where(y[keep] == 1, 1.0, 1.0 / rate)
    return day[keep], cell[keep], y[keep], weight


def climatology(grid, train):
    """Smoothed cell x month onset rate from training cell-days, with a reporting-volume factor."""
    day, cell, y = train
    months = np.array([d.astype(object).month for d in grid.dates]) - 1
    m = months[day]
    n_cells = len(grid.cells)
    pos = np.zeros((n_cells, 12)), np.zeros((n_cells, 12))
    np.add.at(pos[0], (cell, m), y)
    np.add.at(pos[1], (cell, m), 1)
    national = pos[0].sum(axis=0) / np.maximum(pos[1].sum(axis=0), 1)            # month rate
    expected = (pos[1] * national[None, :]).sum(axis=1)
    relative = (pos[0].sum(axis=1) + 1.0) / (expected + 1.0)                       # cell relative risk, shrunk
    rate = np.clip(national[None, :] * relative[:, None], 1e-7, 0.5)
    reported = (grid.label == 1).sum(axis=1).astype(np.float32)[:, None]
    volume = data.lagged_sum(reported, 1, 365)[:, 0]
    train_volume = np.nanmean(volume[np.unique(day)])
    factor = np.where(np.isfinite(volume), volume / train_volume, 1.0)

    def predict(d, c, scaled=True):
        p = rate[c, months[d]]
        if not scaled:
            return p
        # Scale the odds, not the probability, so heavily reported cells stay below certainty.
        odds = p / (1 - p) * factor[d]
        return np.clip(odds / (1 + odds), 1e-7, 1 - 1e-7)
    return predict, {"train_reporting_volume_mean": float(train_volume)}


def logit(p):
    p = np.clip(p, 1e-7, 1 - 1e-7)
    return np.log(p / (1 - p))


def scores(y, p, threshold=None, day=None, top_fractions=(0.01, 0.05)):
    y = y.astype(np.float64)
    out = {"n": int(len(y)), "onsets": int(y.sum()), "base_rate": float(y.mean()) if len(y) else None}
    if not len(y) or y.sum() == 0 or y.sum() == len(y):
        return out
    out["brier"] = float(np.mean((p - y) ** 2))
    eps = 1e-7
    out["log_loss"] = float(-np.mean(y * np.log(np.clip(p, eps, 1)) + (1 - y) * np.log(np.clip(1 - p, eps, 1))))
    out["roc_auc"] = float(roc_auc_score(y, p))
    out["pr_auc"] = float(average_precision_score(y, p))
    if threshold is not None:
        warn = p >= threshold
        hits, misses, false = int((warn & (y == 1)).sum()), int((~warn & (y == 1)).sum()), int((warn & (y == 0)).sum())
        out.update(threshold=float(threshold), hits=hits, misses=misses, false_alarms=false,
                   hit_rate=hits / max(hits + misses, 1), false_alarm_ratio=false / max(hits + false, 1), csi=hits / max(hits + misses + false, 1))
    if day is not None:
        order = np.lexsort((-p, day))
        ranked_day, ranked_y = day[order], y[order]
        starts = np.r_[0, np.flatnonzero(np.diff(ranked_day)) + 1]
        rank = np.arange(len(order)) - np.repeat(starts, np.diff(np.r_[starts, len(order)]))
        per_day = np.diff(np.r_[starts, len(order)])
        size = np.repeat(per_day, per_day)
        for fraction in top_fractions:
            caught = ranked_y[rank < np.ceil(fraction * size)].sum()
            out[f"onsets_in_daily_top_{int(fraction * 100)}pct"] = float(caught / y.sum())
    return out


def best_threshold(y, p):
    best = (0.0, 0.5)
    for threshold in np.unique(np.quantile(p, np.linspace(0.95, 0.99995, 200))):
        warn = p >= threshold
        hits = (warn & (y == 1)).sum()
        csi = hits / max(hits + (~warn & (y == 1)).sum() + (warn & (y == 0)).sum(), 1)
        if csi > best[0]:
            best = (float(csi), float(threshold))
    return best[1]


def reliability(y, p, bins=10):
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    which = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    return [{"p_mean": float(p[which == b].mean()), "observed_rate": float(y[which == b].mean()), "n": int((which == b).sum())}
            for b in range(len(edges) - 1) if (which == b).any()]


def main():
    started = time.perf_counter()
    REPORTS.mkdir(exist_ok=True)
    RUNS.mkdir(exist_ok=True)
    grid = data.load()
    n_cells = len(grid.cells)
    chenab = np.array([float(c["chenab_fraction"]) >= CHENAB_MIN_FRACTION for c in grid.cells])
    province = np.array([c["province"] or "AJK / Gilgit-Baltistan" for c in grid.cells])
    print(f"loaded {len(grid.dates)} days x {n_cells} cells; {grid.events_used:,} reports used, dropped {grid.events_dropped}; "
          f"onset cell-days {int((grid.label == 1).sum()):,}; Chenab cells {int(chenab.sum())} ({time.perf_counter() - started:.0f}s)", flush=True)
    split = {name: split_index(grid, name) for name in SPLITS}
    clim_predict, clim_info = climatology(grid, split["train"])
    results = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "label_rule": {"max_duration_days": data.MAX_DURATION_DAYS, "max_area_km2": data.MAX_AREA_KM2,
                              "min_event_share_per_cell": data.MIN_EVENT_SHARE, "onset_gap_days": data.ONSET_GAP_DAYS},
               "splits": SPLITS, "reports_used": grid.events_used, "reports_dropped": grid.events_dropped, "cells": n_cells,
               "chenab_cells": int(chenab.sum()), "climatology": clim_info, "onsets_by_year": {}, "models": {}}
    years = np.array([d.astype(object).year for d in grid.dates])
    for year in range(2010, 2027):
        results["onsets_by_year"][year] = int((grid.label[years == year] == 1).sum())
    predictions = {}
    variants = {"lightgbm_forecast": ("forecast", True), "lightgbm_observed": ("observed", True), "lightgbm_weather_only": ("forecast", False)}
    for variant, (mode, with_reports) in variants.items():
        dynamic, static = data.features(grid, mode)
        names = [name for name in list(dynamic) + list(static) if with_reports or not name.startswith("reports_")]
        # The trees start from the reporting-adjusted climatology (init_score) and learn what weather,
        # terrain and recent reports add to it; the climatology carries the growth in news coverage.
        d, c, y, w = subsample(*split["train"], NEGATIVE_RATE, SEED)
        offset = lambda dd, cc: logit(clim_predict(dd, cc))
        train_set = lgb.Dataset(data.assemble(dynamic, static, d, c, names), label=y, weight=w, init_score=offset(d, c), feature_name=names, free_raw_data=True)
        vd, vc, vy = split["val"]
        val_x = data.assemble(dynamic, static, vd, vc, names)
        val_set = lgb.Dataset(val_x, label=vy, init_score=offset(vd, vc), reference=train_set, feature_name=names)
        booster = lgb.train(PARAMS, train_set, num_boost_round=3000, valid_sets=[val_set], valid_names=["val"],
                            callbacks=[lgb.early_stopping(150, verbose=False), lgb.log_evaluation(0)])
        booster.save_model(str(RUNS / f"{variant}.txt"))
        predict = lambda x, dd, cc: 1 / (1 + np.exp(-(booster.predict(x, num_iteration=booster.best_iteration, raw_score=True) + offset(dd, cc))))
        val_p = predict(val_x, vd, vc)
        threshold = best_threshold(vy, val_p)
        td, tc, ty = split["test"]
        test_p = predict(data.assemble(dynamic, static, td, tc, names), td, tc)
        predictions[variant] = test_p
        gain = booster.feature_importance("gain")
        results["models"][variant] = {
            "best_iteration": int(booster.best_iteration), "threshold_from_validation": threshold,
            "importance": sorted(({"feature": n, "gain_share": float(g / gain.sum())} for n, g in zip(names, gain)), key=lambda x: -x["gain_share"]),
            "val": scores(vy, val_p, threshold, vd)}
        print(f"{variant}: {booster.best_iteration} trees, validation PR-AUC {results['models'][variant]['val'].get('pr_auc', float('nan')):.4f} "
              f"({time.perf_counter() - started:.0f}s)", flush=True)
        if variant == "lightgbm_forecast":
            rain = lambda dd, cc: np.column_stack([logit(clim_predict(dd, cc)), np.log1p(np.nan_to_num(dynamic["rain_max3h_day"][dd, cc])),
                                                    np.log1p(np.nan_to_num(dynamic["rain_day"][dd, cc])), np.log1p(np.nan_to_num(dynamic["rain_prev3"][dd, cc]))])
            trigger = LogisticRegression(C=1.0, max_iter=500).fit(rain(d, c), y, sample_weight=w)
            trigger_val = trigger.predict_proba(rain(vd, vc))[:, 1]
            trigger_threshold = best_threshold(vy, trigger_val)
            predictions["rain_trigger"] = trigger.predict_proba(rain(td, tc))[:, 1]
            results["models"]["rain_trigger"] = {"coefficients": dict(zip(["climatology_logit", "log1p_max3h_rain", "log1p_day_rain", "log1p_prev3_rain"], map(float, trigger.coef_[0]))),
                                                 "intercept": float(trigger.intercept_[0]), "threshold_from_validation": trigger_threshold,
                                                 "val": scores(vy, trigger_val, trigger_threshold, vd)}
        del dynamic, train_set, val_set, val_x
    td, tc, ty = split["test"]
    vd, vc, vy = split["val"]
    clim_val = clim_predict(vd, vc)
    clim_threshold = best_threshold(vy, clim_val)
    predictions["climatology"] = clim_predict(td, tc)
    results["models"]["climatology"] = {"threshold_from_validation": clim_threshold, "val": scores(vy, clim_val, clim_threshold, vd)}
    thresholds = {name: results["models"][name]["threshold_from_validation"] for name in predictions}
    test_years = years[td]
    months = np.array([d.astype(object).month for d in grid.dates])[td]
    regions = {"pakistan": np.ones(len(ty), bool), "chenab_districts": chenab[tc]}
    for prov in sorted(set(province)):
        regions[f"province:{prov}"] = province[tc] == prov
    slices = {"all": np.ones(len(ty), bool), "monsoon_jun_sep": (months >= 6) & (months <= 9), "other_months": (months < 6) | (months > 9)}
    for year in sorted(set(test_years)):
        slices[f"year_{year}"] = test_years == year
    reference = predictions["climatology"]
    test = {}
    for name, p in predictions.items():
        test[name] = {}
        for region, mask in regions.items():
            for slice_name, smask in slices.items():
                keep = mask & smask
                result = scores(ty[keep], p[keep], thresholds[name], td[keep])
                if "brier" in result and name != "climatology":
                    ref = np.mean((reference[keep] - ty[keep]) ** 2)
                    result["brier_skill_vs_climatology"] = float(1 - result["brier"] / ref) if ref > 0 else None
                test[name][f"{region}|{slice_name}"] = result
        test[name]["reliability_pakistan"] = reliability(ty, p)
    results["test"] = test
    (REPORTS / "metrics.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    np.savez_compressed(RUNS / "test_predictions.npz", day=td.astype(np.int32), cell=tc.astype(np.int32), y=ty,
                        dates=grid.dates.astype(str), **{name: p.astype(np.float32) for name, p in predictions.items()})
    print(f"done in {time.perf_counter() - started:.0f}s -> {REPORTS / 'metrics.json'}", flush=True)
    for name in predictions:
        for key in ("pakistan|all", "chenab_districts|all"):
            r = test[name][key]
            print(f"  {name:20s} {key:24s} onsets {r.get('onsets')}  PR-AUC {r.get('pr_auc', float('nan')):.4f}  ROC-AUC {r.get('roc_auc', float('nan')):.3f}"
                  f"  BSS {r.get('brier_skill_vs_climatology', float('nan')) if r.get('brier_skill_vs_climatology') is not None else float('nan'):.3f}"
                  f"  top5% {r.get('onsets_in_daily_top_5pct', float('nan')):.3f}  CSI {r.get('csi', float('nan')):.3f}", flush=True)


if __name__ == "__main__":
    main()
