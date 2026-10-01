import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.ml.desinventar_data import V2_FEATURE_NAMES, load_desinventar_dataset
from app.ml.train_desinventar_model import _evaluate_split, _group_split, _roc_auc


PILOT_NAME = "Lower Indus pilot"
PILOT_BLOCKS = {
    "N24_E66", "N24_E68", "N26_E66", "N26_E68", "N28_E66", "N28_E68",
}


def train(dataset_path: str, output_path: str, model_card_path: str) -> dict:
    features, labels, districts, blocks, dates = load_desinventar_dataset(dataset_path)
    pilot_mask = np.isin(blocks, sorted(PILOT_BLOCKS))
    features, labels = features[pilot_mask], labels[pilot_mask]
    districts, blocks, dates = districts[pilot_mask], blocks[pilot_mask], dates[pilot_mask]

    district_split = _group_split(districts)
    district_result = _evaluate_split(features, labels, *district_split[:3])
    indexes = np.arange(len(labels))
    temporal_result = _evaluate_split(
        features,
        labels,
        indexes[np.asarray([value.year <= 2010 for value in dates])],
        indexes[np.asarray([value.year in {2011, 2012} for value in dates])],
        indexes[np.asarray([value.year >= 2013 for value in dates])],
    )
    block_result = _leave_one_block_out(features, labels, blocks)

    results = {
        "district_holdout": district_result[1],
        "leave_one_block_out": block_result,
        "temporal_holdout": temporal_result[1],
    }
    deployment_eligible = all(
        value["roc_auc"] >= 0.75 and value["precision"] >= 0.6 and value["recall"] >= 0.6
        for value in results.values()
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporal_result[0].save_model(destination)
    card = {
        "model_name": "xgboost_lower_indus_pilot_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "coverage_status": "partial_declared_coverage",
        "coverage_name": PILOT_NAME,
        "covered_geographic_blocks": sorted(PILOT_BLOCKS),
        "covered_districts": sorted(np.unique(districts).tolist()),
        "rows": int(len(labels)),
        "positive_rows": int(labels.sum()),
        "features": V2_FEATURE_NAMES,
        "validation_results": results,
        "deployment_eligible": deployment_eligible,
        "operational_status": (
            "candidate_requires_feature_parity_and_authority_validation"
            if deployment_eligible else "rejected_holdout_quality"
        ),
        "acceptance_gate": {
            "minimum_roc_auc": 0.75,
            "minimum_precision": 0.6,
            "minimum_recall": 0.6,
            "must_pass": list(results),
        },
        "scope_rule": "Contiguous Lower Indus blocks were selected before evaluation; unsupported districts must not receive this model.",
        "limitations": [
            "This artifact is valid only for the declared pilot coverage and must never be presented as national.",
            "The current live API lacks the 30-day history required for complete V2 feature parity.",
            "DesInventar labels are reported impacts, not continuous gauge-confirmed inundation.",
            "Measured gauge height and official station thresholds remain unavailable.",
        ],
        "artifact": str(destination),
    }
    Path(model_card_path).write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def _leave_one_block_out(features, labels, blocks) -> dict:
    unique_blocks = sorted(np.unique(blocks).tolist())
    all_labels, all_probabilities, all_predictions = [], [], []
    folds = []
    for index, test_block in enumerate(unique_blocks):
        validation_block = unique_blocks[(index + 1) % len(unique_blocks)]
        train_idx = np.flatnonzero(~np.isin(blocks, [test_block, validation_block]))
        validation_idx = np.flatnonzero(blocks == validation_block)
        test_idx = np.flatnonzero(blocks == test_block)
        _, metrics, raw = _evaluate_split(features, labels, train_idx, validation_idx, test_idx)
        all_labels.append(raw["labels"])
        all_probabilities.append(raw["probabilities"])
        all_predictions.append(raw["predictions"])
        folds.append({
            "test_block": test_block,
            "validation_block": validation_block,
            "test_rows": metrics["test_rows"],
            "test_positive_rows": metrics["test_positive_rows"],
            "roc_auc": metrics["roc_auc"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
        })
    combined_labels = np.concatenate(all_labels)
    combined_probabilities = np.concatenate(all_probabilities)
    combined_predictions = np.concatenate(all_predictions)
    tp = int(np.sum(combined_predictions & (combined_labels == 1)))
    fp = int(np.sum(combined_predictions & (combined_labels == 0)))
    fn = int(np.sum(~combined_predictions & (combined_labels == 1)))
    tn = int(np.sum(~combined_predictions & (combined_labels == 0)))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    return {
        "roc_auc": _roc_auc(combined_labels, combined_probabilities),
        "brier_score": round(float(np.mean((combined_probabilities - combined_labels) ** 2)), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / max(precision + recall, 1e-12), 4),
        "accuracy": round((tp + tn) / len(combined_labels), 4),
        "balanced_accuracy": round((recall + specificity) / 2, 4),
        "test_rows": int(len(combined_labels)),
        "test_positive_rows": int(combined_labels.sum()),
        "folds": folds,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the declared Lower Indus partial-coverage model")
    parser.add_argument("--dataset", default="app/ml/data/pakistan_desinventar_training.csv")
    parser.add_argument("--output", default="app/ml/artifacts/flood_risk_xgboost_lower_indus_pilot.json")
    parser.add_argument("--model-card", default="app/ml/artifacts/flood_risk_xgboost_lower_indus_pilot.model-card.json")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.model_card), indent=2))
