import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb

from app.ml.desinventar_data import (
    DESINVENTAR_URL,
    FLOOD_ARCHIVE_URL,
    V2_FEATURE_NAMES,
    WEATHER_ARCHIVE_URL,
    build_desinventar_dataset,
    load_desinventar_dataset,
)
from app.ml.train_real_model import _group_split, _metrics, _roc_auc


def train(dataset_path: str, output_path: str, model_card_path: str, rebuild: bool = False) -> dict:
    dataset = Path(dataset_path)
    cleaned = dataset.with_name("pakistan_desinventar_cleaned_events.csv")
    quality = dataset.with_name("pakistan_desinventar_quality_report.json")
    if rebuild or not dataset.exists():
        build_desinventar_dataset(str(dataset), str(cleaned), str(quality))
    features, labels, districts, blocks, dates = load_desinventar_dataset(str(dataset))

    district_split = _group_split(districts)
    district_result = _evaluate_split(features, labels, *district_split[:3])
    geographic_split = _group_split(blocks)
    geographic_result = _evaluate_split(features, labels, *geographic_split[:3])
    indexes = np.arange(len(labels))
    temporal_train = indexes[np.asarray([value.year <= 2010 for value in dates])]
    temporal_validation = indexes[np.asarray([value.year in {2011, 2012} for value in dates])]
    temporal_test = indexes[np.asarray([value.year >= 2013 for value in dates])]
    temporal_result = _evaluate_split(features, labels, temporal_train, temporal_validation, temporal_test)

    results = {
        "district_holdout": district_result[1],
        "geographic_holdout": geographic_result[1],
        "temporal_holdout": temporal_result[1],
    }
    deployment_eligible = all(
        metrics["roc_auc"] >= 0.75 and metrics["precision"] >= 0.6 and metrics["recall"] >= 0.6
        for metrics in results.values()
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    geographic_result[0].save_model(destination)
    quality_summary = json.loads(quality.read_text(encoding="utf-8"))
    gain = geographic_result[0].get_score(importance_type="gain")
    card = {
        "model_name": "xgboost_pakistan_desinventar_v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operational_status": "candidate_requires_authority_validation" if deployment_eligible else "rejected_holdout_quality",
        "deployment_eligible": deployment_eligible,
        "acceptance_gate": {
            "minimum_roc_auc": 0.75, "minimum_precision": 0.6, "minimum_recall": 0.6,
            "must_pass": list(results),
        },
        "label_definition": "District-date is a UNDRR DesInventar FLOOD or FLASH FLOOD record; controls are matched seasonal dates for the same district.",
        "sources": {"labels": DESINVENTAR_URL, "weather": WEATHER_ARCHIVE_URL, "river_discharge": FLOOD_ARCHIVE_URL},
        "features": V2_FEATURE_NAMES,
        "rows": int(len(labels)), "positive_rows": int(labels.sum()),
        "districts": int(len(np.unique(districts))), "geographic_blocks": int(len(np.unique(blocks))),
        "data_quality_report": str(quality),
        "data_quality_summary": quality_summary,
        "feature_importance_gain": {
            name: round(float(gain.get(name, 0.0)), 6) for name in V2_FEATURE_NAMES
        },
        "operational_feature_parity": {
            "ready": False,
            "missing_live_history": [
                "rainfall_3d", "rainfall_7d", "rainfall_14d", "rainfall_30d",
                "discharge_ratio_30d", "discharge_zscore_30d",
            ],
            "reason": "The current detailed live providers fetch 24 weather hours and seven discharge days; V2 requires up to 30 days.",
        },
        "validation_results": results,
        "split_membership": {
            "district": district_split[3],
            "geographic": geographic_split[3],
            "temporal": {"train": "2000-2010", "validation": "2011-2012", "test": "2013-2014"},
        },
        "limitations": [
            "DesInventar records impacts and reports, not continuous sensor-confirmed inundation.",
            "Reporting density varies strongly by district and year.",
            "Historical district aliases and boundary changes introduce spatial uncertainty.",
            "Weather and GloFAS values use district representative points, not catchment averages.",
            "Measured gauge height and official station thresholds are unavailable.",
            "The 2007 covariate year was excluded because the free provider quota ended before complete national coverage.",
        ],
        "artifact": str(destination),
    }
    card_path = Path(model_card_path)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def _evaluate_split(features, labels, train_idx, validation_idx, test_idx):
    best_model, best_auc, best_validation, best_params = None, -1.0, None, None
    positive = max(float(labels[train_idx].sum()), 1.0)
    class_weight = float((len(train_idx) - positive) / positive)
    for depth in (2, 3, 4):
        for eta in (0.03, 0.06):
            for min_child_weight in (5, 15):
                train_matrix = xgb.DMatrix(features[train_idx], label=labels[train_idx], feature_names=V2_FEATURE_NAMES)
                validation_matrix = xgb.DMatrix(features[validation_idx], label=labels[validation_idx], feature_names=V2_FEATURE_NAMES)
                model = xgb.train(
                    {
                        "objective": "binary:logistic", "eval_metric": ["logloss", "auc"],
                        "max_depth": depth, "eta": eta, "min_child_weight": min_child_weight,
                        "subsample": 0.85, "colsample_bytree": 0.9, "scale_pos_weight": class_weight,
                        "seed": 42, "nthread": 2,
                    },
                    train_matrix, num_boost_round=500, evals=[(validation_matrix, "validation")],
                    early_stopping_rounds=40, verbose_eval=False,
                )
                validation_probabilities = model.predict(validation_matrix)
                auc = _roc_auc(labels[validation_idx], validation_probabilities)
                if auc > best_auc:
                    best_model, best_auc, best_validation = model, auc, validation_probabilities
                    best_params = {
                        "max_depth": depth, "eta": eta,
                        "min_child_weight": min_child_weight,
                        "best_iteration": int(model.best_iteration),
                    }
    threshold = _best_threshold(labels[validation_idx], best_validation)
    test_matrix = xgb.DMatrix(features[test_idx], label=labels[test_idx], feature_names=V2_FEATURE_NAMES)
    test_probabilities = best_model.predict(test_matrix)
    fixed = _metrics(labels[test_idx], test_probabilities)
    selected = _threshold_metrics(labels[test_idx], test_probabilities, threshold)
    result = {
        "roc_auc": fixed["roc_auc"], "brier_score": fixed["brier_score"],
        "selected_threshold": threshold, **selected,
        "selected_hyperparameters": best_params,
        "metrics_at_0_5": fixed, "test_rows": int(len(test_idx)),
        "test_positive_rows": int(labels[test_idx].sum()),
    }
    return best_model, result, {
        "labels": labels[test_idx],
        "probabilities": test_probabilities,
        "predictions": test_probabilities >= threshold,
    }


def _best_threshold(labels, probabilities) -> float:
    candidates = np.arange(0.1, 0.91, 0.02)
    scored = [(_threshold_metrics(labels, probabilities, float(value))["f1"], float(value)) for value in candidates]
    return round(max(scored)[1], 2)


def _threshold_metrics(labels, probabilities, threshold) -> dict[str, float]:
    predictions = probabilities >= threshold
    tp = int(np.sum(predictions & (labels == 1)))
    fp = int(np.sum(predictions & (labels == 0)))
    fn = int(np.sum(~predictions & (labels == 1)))
    tn = int(np.sum(~predictions & (labels == 0)))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    return {
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / max(precision + recall, 1e-12), 4),
        "accuracy": round((tp + tn) / max(len(labels), 1), 4),
        "balanced_accuracy": round((recall + specificity) / 2, 4),
        "true_positives": tp, "false_positives": fp,
        "false_negatives": fn, "true_negatives": tn,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the district-date real-data Pakistan flood model")
    parser.add_argument("--dataset", default="app/ml/data/pakistan_desinventar_training.csv")
    parser.add_argument("--output", default="app/ml/artifacts/flood_risk_xgboost_desinventar_v2.json")
    parser.add_argument("--model-card", default="app/ml/artifacts/flood_risk_xgboost_desinventar_v2.model-card.json")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.model_card, args.rebuild), indent=2))
