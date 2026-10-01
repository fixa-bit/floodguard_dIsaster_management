import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb

from app.ml.real_data import EVENT_CATALOG_URL, FLOOD_ARCHIVE_URL, WEATHER_ARCHIVE_URL, build_real_dataset, load_real_dataset
from app.ml.synthetic_data import FEATURE_NAMES


def train(dataset_path: str, output_path: str, model_card_path: str, rebuild: bool = False) -> dict:
    dataset = Path(dataset_path)
    if rebuild or not dataset.exists():
        build_real_dataset(str(dataset))
    features, labels, groups, geographic_blocks = load_real_dataset(str(dataset))
    train_idx, validation_idx, test_idx, split_groups = _group_split(groups)
    model, probabilities = _fit_and_predict(features, labels, train_idx, validation_idx, test_idx)
    metrics = _metrics(labels[test_idx], probabilities)
    geo_train_idx, geo_validation_idx, geo_test_idx, geo_split_groups = _group_split(geographic_blocks)
    _, geographic_probabilities = _fit_and_predict(
        features, labels, geo_train_idx, geo_validation_idx, geo_test_idx
    )
    geographic_metrics = _metrics(labels[geo_test_idx], geographic_probabilities)
    deployment_eligible = all(
        result["roc_auc"] >= 0.75
        and result["precision_at_0_5"] >= 0.6
        and result["recall_at_0_5"] >= 0.6
        for result in (metrics, geographic_metrics)
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(destination)
    card = {
        "model_name": "xgboost_pakistan_gfd_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operational_status": "candidate_requires_external_validation" if deployment_eligible else "rejected_holdout_quality",
        "deployment_eligible": deployment_eligible,
        "acceptance_gate": {"minimum_roc_auc": 0.75, "minimum_precision_at_0_5": 0.6, "minimum_recall_at_0_5": 0.6, "must_pass": ["event_holdout", "geographic_holdout"]},
        "label_definition": "Day falls within a satellite-mapped Global Flood Database event window at the DFO event centroid.",
        "limitations": [
            "Event-centroid daily classification is not district-scale inundation prediction.",
            "The Global Flood Database ends in 2018 and contains 28 Pakistan-associated events.",
            "GloFAS discharge is modeled, not measured gauge height.",
            "Negative examples are matched pre/post-event days and are not proof of no local flooding.",
        ],
        "sources": {
            "labels": EVENT_CATALOG_URL,
            "weather": WEATHER_ARCHIVE_URL,
            "river_discharge": FLOOD_ARCHIVE_URL,
        },
        "features": FEATURE_NAMES,
        "rows": int(len(labels)),
        "positive_rows": int(labels.sum()),
        "events": int(len(np.unique(groups))),
        "geographic_blocks": int(len(np.unique(geographic_blocks))),
        "event_split": {name: sorted(values) for name, values in split_groups.items()},
        "geographic_split": {name: sorted(values) for name, values in geo_split_groups.items()},
        "event_holdout_metrics": metrics,
        "geographic_holdout_metrics": geographic_metrics,
        "best_iteration": int(model.best_iteration),
        "artifact": str(destination),
    }
    card_path = Path(model_card_path)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def _fit_and_predict(
    features: np.ndarray,
    labels: np.ndarray,
    train_idx: np.ndarray,
    validation_idx: np.ndarray,
    test_idx: np.ndarray,
) -> tuple[xgb.Booster, np.ndarray]:
    train_matrix = xgb.DMatrix(features[train_idx], label=labels[train_idx], feature_names=FEATURE_NAMES)
    validation_matrix = xgb.DMatrix(features[validation_idx], label=labels[validation_idx], feature_names=FEATURE_NAMES)
    test_matrix = xgb.DMatrix(features[test_idx], label=labels[test_idx], feature_names=FEATURE_NAMES)
    model = xgb.train(
        {
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "auc"],
            "max_depth": 3,
            "eta": 0.04,
            "min_child_weight": 8,
            "subsample": 0.85,
            "colsample_bytree": 0.9,
            "seed": 42,
            "nthread": 2,
        },
        train_matrix,
        num_boost_round=500,
        evals=[(validation_matrix, "validation")],
        early_stopping_rounds=40,
        verbose_eval=False,
    )
    return model, model.predict(test_matrix)


def _group_split(groups: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, list[str]]]:
    unique = np.unique(groups)
    rng = np.random.default_rng(42)
    rng.shuffle(unique)
    test_groups = set(unique[: max(4, round(len(unique) * 0.2))])
    validation_groups = set(unique[len(test_groups) : len(test_groups) + max(4, round(len(unique) * 0.15))])
    train_groups = set(unique) - test_groups - validation_groups
    indexes = np.arange(len(groups))
    return (
        indexes[np.isin(groups, list(train_groups))],
        indexes[np.isin(groups, list(validation_groups))],
        indexes[np.isin(groups, list(test_groups))],
        {"train_groups": list(train_groups), "validation_groups": list(validation_groups), "test_groups": list(test_groups)},
    )


def _metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    predictions = probabilities >= 0.5
    true_positive = int(np.sum(predictions & (labels == 1)))
    false_positive = int(np.sum(predictions & (labels == 0)))
    false_negative = int(np.sum(~predictions & (labels == 1)))
    true_negative = int(np.sum(~predictions & (labels == 0)))
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    specificity = true_negative / max(true_negative + false_positive, 1)
    return {
        "roc_auc": round(_roc_auc(labels, probabilities), 4),
        "precision_at_0_5": round(precision, 4),
        "recall_at_0_5": round(recall, 4),
        "f1_at_0_5": round(2 * precision * recall / max(precision + recall, 1e-12), 4),
        "accuracy_at_0_5": round((true_positive + true_negative) / max(len(labels), 1), 4),
        "specificity_at_0_5": round(specificity, 4),
        "balanced_accuracy_at_0_5": round((recall + specificity) / 2, 4),
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 4),
        "test_rows": int(len(labels)),
    }


def _roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    positive = scores[labels == 1]
    negative = scores[labels == 0]
    if not len(positive) or not len(negative):
        return 0.5
    return float(np.mean([(positive > value).mean() + 0.5 * (positive == value).mean() for value in negative]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train a research XGBoost model on real Pakistan flood-event data")
    parser.add_argument("--dataset", default="app/ml/data/pakistan_real_flood_training.csv")
    parser.add_argument("--output", default="app/ml/artifacts/flood_risk_xgboost_real.json")
    parser.add_argument("--model-card", default="app/ml/artifacts/flood_risk_xgboost_real.model-card.json")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.model_card, args.rebuild), indent=2))
