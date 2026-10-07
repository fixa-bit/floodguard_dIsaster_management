import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover - exercised only in environments without optional ML deps.
    lgb = None


FLASH_FLOOD_FEATURE_NAMES = [
    "rainfall_15min_mm",
    "rainfall_1h_mm",
    "rainfall_3h_mm",
    "rainfall_6h_mm",
    "forecast_rainfall_6h_mm",
    "soil_moisture_percent",
    "slope_degrees",
    "elevation_m",
    "drainage_density_km_per_km2",
    "land_cover_code",
    "catchment_area_km2",
    "distance_to_stream_km",
]

TARGET_COLUMN = "target_flash_flood_next_6h"
TARGET_PROBABILITY_COLUMN = "target_flash_flood_probability"
TARGET_CLASS_COLUMN = "target_flash_flood_class"
RISK_CLASSES = ("No risk", "Low", "Moderate", "High", "Extreme")


@dataclass(frozen=True)
class FlashFloodForecastInput:
    rainfall_15min_mm: float
    rainfall_1h_mm: float
    rainfall_3h_mm: float
    rainfall_6h_mm: float
    forecast_rainfall_6h_mm: float
    soil_moisture_percent: float
    slope_degrees: float
    elevation_m: float
    drainage_density_km_per_km2: float
    land_cover_code: float
    catchment_area_km2: float
    distance_to_stream_km: float

    def as_model_vector(self) -> list[float]:
        return [
            self.rainfall_15min_mm,
            self.rainfall_1h_mm,
            self.rainfall_3h_mm,
            self.rainfall_6h_mm,
            self.forecast_rainfall_6h_mm,
            self.soil_moisture_percent,
            self.slope_degrees,
            self.elevation_m,
            self.drainage_density_km_per_km2,
            self.land_cover_code,
            self.catchment_area_km2,
            self.distance_to_stream_km,
        ]


class LightGBMFlashFloodBaseline:
    name = "lightgbm_flash_flood_baseline_v1"
    model_type = "flash_flood_probability_classifier"

    def __init__(self, model_path: str):
        _require_lightgbm()
        self.model_path = Path(model_path)
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            self._model = lgb.Booster(model_file=str(self.model_path))
        return self._model

    def predict(self, features: FlashFloodForecastInput) -> dict:
        values = np.asarray([features.as_model_vector()], dtype=np.float32)
        probability = float(self._load().predict(values)[0])
        probability = min(max(probability, 0.0), 1.0)
        return {
            "forecast_horizon_hours": 6,
            "flash_flood_probability": round(probability, 4),
            "risk_class": classify_flash_flood(probability),
            "model_name": self.name,
            "model_type": self.model_type,
        }


def classify_flash_flood(probability: float) -> str:
    if probability < 0.05:
        return "No risk"
    if probability < 0.2:
        return "Low"
    if probability < 0.45:
        return "Moderate"
    if probability < 0.7:
        return "High"
    return "Extreme"


def generate_synthetic_flash_flood_dataset(output_path: str, rows: int = 3200, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [*FLASH_FLOOD_FEATURE_NAMES, TARGET_PROBABILITY_COLUMN, TARGET_COLUMN, TARGET_CLASS_COLUMN]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for _ in range(rows):
            rainfall_15min = np.clip(rng.gamma(1.3, 3.1), 0, 55)
            rainfall_1h = np.clip(rainfall_15min * rng.uniform(1.2, 3.4) + rng.normal(1, 3), 0, 120)
            rainfall_3h = np.clip(rainfall_1h * rng.uniform(1.15, 2.5) + rng.normal(2, 7), 0, 220)
            rainfall_6h = np.clip(rainfall_3h * rng.uniform(1.05, 1.9) + rng.normal(4, 10), 0, 340)
            forecast_rainfall = np.clip(rng.gamma(1.8, 13), 0, 210)
            soil_moisture = rng.uniform(18, 100)
            slope = np.clip(rng.gamma(2.2, 4.2), 0.2, 42)
            elevation = np.clip(rng.normal(520, 430), 20, 4200)
            drainage_density = rng.uniform(0.15, 4.8)
            land_cover = float(rng.choice([1, 2, 3, 4, 5], p=[0.12, 0.3, 0.25, 0.18, 0.15]))
            catchment_area = np.clip(rng.lognormal(3.6, 0.8), 4, 1200)
            distance_to_stream = np.clip(rng.exponential(1.6), 0.02, 15)
            impervious_or_bare = 1 if land_cover in {4.0, 5.0} else 0
            small_steep_catchment = 1 if catchment_area < 90 and slope > 10 else 0
            stream_proximity = max(0.0, 1.0 - distance_to_stream / 6.0)
            logit = (
                -4.25
                + rainfall_15min / 10.0
                + rainfall_1h / 33.0
                + rainfall_3h / 80.0
                + rainfall_6h / 150.0
                + forecast_rainfall / 95.0
                + soil_moisture / 95.0
                + slope / 18.0
                + drainage_density / 2.6
                + stream_proximity * 1.0
                + impervious_or_bare * 0.45
                + small_steep_catchment * 0.65
                + rng.normal(0, 0.3)
            )
            probability = float(1 / (1 + np.exp(-logit)))
            label = int(rng.random() < probability)
            writer.writerow(
                {
                    "rainfall_15min_mm": round(float(rainfall_15min), 3),
                    "rainfall_1h_mm": round(float(rainfall_1h), 3),
                    "rainfall_3h_mm": round(float(rainfall_3h), 3),
                    "rainfall_6h_mm": round(float(rainfall_6h), 3),
                    "forecast_rainfall_6h_mm": round(float(forecast_rainfall), 3),
                    "soil_moisture_percent": round(float(soil_moisture), 3),
                    "slope_degrees": round(float(slope), 3),
                    "elevation_m": round(float(elevation), 3),
                    "drainage_density_km_per_km2": round(float(drainage_density), 3),
                    "land_cover_code": land_cover,
                    "catchment_area_km2": round(float(catchment_area), 3),
                    "distance_to_stream_km": round(float(distance_to_stream), 3),
                    TARGET_PROBABILITY_COLUMN: round(probability, 4),
                    TARGET_COLUMN: label,
                    TARGET_CLASS_COLUMN: classify_flash_flood(probability),
                }
            )
    return destination


def train(
    dataset_path: str,
    output_path: str,
    model_card_path: str,
    rebuild: bool = False,
    rows: int = 3200,
) -> dict:
    _require_lightgbm()
    dataset = Path(dataset_path)
    if rebuild or not dataset.exists():
        generate_synthetic_flash_flood_dataset(str(dataset), rows=rows)
    features, labels, target_probabilities = load_flash_flood_dataset(str(dataset))
    train_idx, validation_idx, test_idx = _temporal_like_split(len(labels))
    model, probabilities = _fit_and_predict(features, labels, train_idx, validation_idx, test_idx)
    metrics = _classification_metrics(labels[test_idx], probabilities)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(destination))
    card = {
        "model_name": LightGBMFlashFloodBaseline.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_family": "LightGBM binary classifier",
        "dataset": str(dataset),
        "dataset_rows": int(len(labels)),
        "dataset_type": "synthetic_bootstrap_until_rain_gauge_gis_event_history_is_available",
        "forecast_horizon_hours": 6,
        "features": FLASH_FLOOD_FEATURE_NAMES,
        "targets": [TARGET_COLUMN, TARGET_CLASS_COLUMN],
        "risk_classes": list(RISK_CLASSES),
        "validation_split": {"train_rows": int(len(train_idx)), "validation_rows": int(len(validation_idx)), "test_rows": int(len(test_idx))},
        "test_metrics": metrics,
        "output_format": {
            "forecast_horizon_hours": "integer",
            "flash_flood_probability": "float_0_to_1",
            "risk_class": "No risk | Low | Moderate | High | Extreme",
            "model_name": "string",
            "model_type": "string",
        },
        "artifact": str(destination),
    }
    Path(model_card_path).parent.mkdir(parents=True, exist_ok=True)
    Path(model_card_path).write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def load_flash_flood_dataset(dataset_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features: list[list[float]] = []
    labels: list[int] = []
    target_probabilities: list[float] = []
    with Path(dataset_path).open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            features.append([float(row[name]) for name in FLASH_FLOOD_FEATURE_NAMES])
            labels.append(int(float(row[TARGET_COLUMN])))
            target_probabilities.append(float(row[TARGET_PROBABILITY_COLUMN]))
    return (
        np.asarray(features, dtype=np.float32),
        np.asarray(labels, dtype=np.int32),
        np.asarray(target_probabilities, dtype=np.float32),
    )


def _fit_and_predict(features, labels, train_idx, validation_idx, test_idx):
    train_data = lgb.Dataset(features[train_idx], label=labels[train_idx], feature_name=FLASH_FLOOD_FEATURE_NAMES)
    validation_data = lgb.Dataset(features[validation_idx], label=labels[validation_idx], reference=train_data, feature_name=FLASH_FLOOD_FEATURE_NAMES)
    model = lgb.train(
        {
            "objective": "binary",
            "metric": ["binary_logloss", "auc"],
            "learning_rate": 0.04,
            "num_leaves": 31,
            "min_data_in_leaf": 35,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "seed": 42,
            "num_threads": 2,
            "verbosity": -1,
        },
        train_data,
        num_boost_round=400,
        valid_sets=[validation_data],
        callbacks=[lgb.early_stopping(35, verbose=False)],
    )
    return model, model.predict(features[test_idx])


def _temporal_like_split(row_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    indexes = np.arange(row_count)
    train_end = max(round(row_count * 0.7), 1)
    validation_end = max(round(row_count * 0.85), train_end + 1)
    return indexes[:train_end], indexes[train_end:validation_end], indexes[validation_end:]


def _classification_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    predictions = probabilities >= 0.45
    true_positive = int(np.sum(predictions & (labels == 1)))
    false_positive = int(np.sum(predictions & (labels == 0)))
    false_negative = int(np.sum(~predictions & (labels == 1)))
    true_negative = int(np.sum(~predictions & (labels == 0)))
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    specificity = true_negative / max(true_negative + false_positive, 1)
    return {
        "roc_auc": round(_roc_auc(labels, probabilities), 4),
        "brier_score": round(float(np.mean((probabilities - labels) ** 2)), 4),
        "precision_at_0_45": round(precision, 4),
        "recall_at_0_45": round(recall, 4),
        "f1_at_0_45": round(2 * precision * recall / max(precision + recall, 1e-12), 4),
        "accuracy_at_0_45": round((true_positive + true_negative) / max(len(labels), 1), 4),
        "balanced_accuracy_at_0_45": round((recall + specificity) / 2, 4),
        "test_rows": int(len(labels)),
    }


def _roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    positive = scores[labels == 1]
    negative = scores[labels == 0]
    if not len(positive) or not len(negative):
        return 0.5
    return float(np.mean([(positive > value).mean() + 0.5 * (positive == value).mean() for value in negative]))


def _require_lightgbm() -> None:
    if lgb is None:
        raise RuntimeError("LightGBM is required for the flash-flood baseline. Install requirements.txt first.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the flash-flood LightGBM baseline")
    parser.add_argument("--dataset", default="app/ml/data/flash_flood_training.csv")
    parser.add_argument("--output", default="app/ml/artifacts/flash_flood_lightgbm_baseline.txt")
    parser.add_argument("--model-card", default="app/ml/artifacts/flash_flood_lightgbm_baseline.model-card.json")
    parser.add_argument("--rows", type=int, default=3200)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.model_card, args.rebuild, args.rows), indent=2))
