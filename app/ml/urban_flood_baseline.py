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


URBAN_FLOOD_FEATURE_NAMES = [
    "rainfall_1h_mm",
    "rainfall_3h_mm",
    "rainfall_6h_mm",
    "forecast_rainfall_6h_mm",
    "dem_elevation_m",
    "slope_degrees",
    "drainage_capacity_mm_per_h",
    "impervious_surface_percent",
    "land_use_code",
    "previous_waterlogging_reports_30d",
]

TARGET_COLUMN = "target_urban_flood_class_id"
TARGET_CLASS_COLUMN = "target_urban_flood_class"
SUSCEPTIBILITY_CLASSES = ("Low", "Moderate", "High", "Extremely high")


@dataclass(frozen=True)
class UrbanFloodForecastInput:
    rainfall_1h_mm: float
    rainfall_3h_mm: float
    rainfall_6h_mm: float
    forecast_rainfall_6h_mm: float
    dem_elevation_m: float
    slope_degrees: float
    drainage_capacity_mm_per_h: float
    impervious_surface_percent: float
    land_use_code: float
    previous_waterlogging_reports_30d: float

    def as_model_vector(self) -> list[float]:
        return [
            self.rainfall_1h_mm,
            self.rainfall_3h_mm,
            self.rainfall_6h_mm,
            self.forecast_rainfall_6h_mm,
            self.dem_elevation_m,
            self.slope_degrees,
            self.drainage_capacity_mm_per_h,
            self.impervious_surface_percent,
            self.land_use_code,
            self.previous_waterlogging_reports_30d,
        ]


class LightGBMUrbanFloodBaseline:
    name = "lightgbm_urban_flood_susceptibility_v1"
    model_type = "urban_flood_susceptibility_classifier"

    def __init__(self, model_path: str):
        _require_lightgbm()
        self.model_path = Path(model_path)
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            self._model = lgb.Booster(model_file=str(self.model_path))
        return self._model

    def predict(self, features: UrbanFloodForecastInput) -> dict:
        values = np.asarray([features.as_model_vector()], dtype=np.float32)
        probabilities = np.asarray(self._load().predict(values)[0], dtype=np.float32)
        class_id = int(np.argmax(probabilities))
        return {
            "forecast_horizon_hours": 6,
            "susceptibility_class": SUSCEPTIBILITY_CLASSES[class_id],
            "class_probabilities": {
                label: round(float(probabilities[index]), 4)
                for index, label in enumerate(SUSCEPTIBILITY_CLASSES)
            },
            "model_name": self.name,
            "model_type": self.model_type,
        }


def classify_urban_flood(score: float) -> str:
    if score < 0.28:
        return "Low"
    if score < 0.5:
        return "Moderate"
    if score < 0.72:
        return "High"
    return "Extremely high"


def generate_synthetic_urban_flood_dataset(output_path: str, rows: int = 3600, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [*URBAN_FLOOD_FEATURE_NAMES, "target_urban_flood_score", TARGET_COLUMN, TARGET_CLASS_COLUMN]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for _ in range(rows):
            rainfall_1h = np.clip(rng.gamma(1.5, 8), 0, 120)
            rainfall_3h = np.clip(rainfall_1h * rng.uniform(1.05, 2.8) + rng.normal(0, 5), 0, 220)
            rainfall_6h = np.clip(rainfall_3h * rng.uniform(1.05, 1.8) + rng.normal(0, 8), 0, 320)
            forecast_rainfall = np.clip(rng.gamma(1.7, 12), 0, 190)
            elevation = np.clip(rng.normal(260, 160), 5, 1800)
            slope = np.clip(rng.gamma(1.7, 2.2), 0.05, 28)
            drainage_capacity = np.clip(rng.normal(32, 14), 4, 85)
            impervious = rng.uniform(18, 98)
            land_use = float(rng.choice([1, 2, 3, 4, 5], p=[0.12, 0.22, 0.24, 0.3, 0.12]))
            reports = float(rng.poisson(max(0.2, impervious / 25)))
            low_slope_signal = max(0.0, 1.0 - slope / 10.0)
            drainage_deficit = max(0.0, (rainfall_1h + forecast_rainfall / 6.0 - drainage_capacity) / 70.0)
            dense_land_use = 1 if land_use in {3.0, 4.0, 5.0} else 0
            score = (
                rainfall_1h / 115.0 * 0.16
                + rainfall_3h / 190.0 * 0.13
                + rainfall_6h / 280.0 * 0.1
                + forecast_rainfall / 165.0 * 0.14
                + impervious / 100.0 * 0.18
                + low_slope_signal * 0.1
                + drainage_deficit * 0.13
                + min(reports / 10.0, 1.0) * 0.11
                + dense_land_use * 0.05
                + rng.normal(0, 0.035)
            )
            score = float(np.clip(score, 0, 1))
            flood_class = classify_urban_flood(score)
            writer.writerow(
                {
                    "rainfall_1h_mm": round(float(rainfall_1h), 3),
                    "rainfall_3h_mm": round(float(rainfall_3h), 3),
                    "rainfall_6h_mm": round(float(rainfall_6h), 3),
                    "forecast_rainfall_6h_mm": round(float(forecast_rainfall), 3),
                    "dem_elevation_m": round(float(elevation), 3),
                    "slope_degrees": round(float(slope), 3),
                    "drainage_capacity_mm_per_h": round(float(drainage_capacity), 3),
                    "impervious_surface_percent": round(float(impervious), 3),
                    "land_use_code": land_use,
                    "previous_waterlogging_reports_30d": reports,
                    "target_urban_flood_score": round(score, 4),
                    TARGET_COLUMN: SUSCEPTIBILITY_CLASSES.index(flood_class),
                    TARGET_CLASS_COLUMN: flood_class,
                }
            )
    return destination


def train(
    dataset_path: str,
    output_path: str,
    model_card_path: str,
    rebuild: bool = False,
    rows: int = 3600,
) -> dict:
    _require_lightgbm()
    dataset = Path(dataset_path)
    if rebuild or not dataset.exists():
        generate_synthetic_urban_flood_dataset(str(dataset), rows=rows)
    features, labels = load_urban_flood_dataset(str(dataset))
    train_idx, validation_idx, test_idx = _temporal_like_split(len(labels))
    model, probabilities = _fit_and_predict(features, labels, train_idx, validation_idx, test_idx)
    metrics = _multiclass_metrics(labels[test_idx], probabilities)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(destination))
    card = {
        "model_name": LightGBMUrbanFloodBaseline.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_family": "LightGBM multiclass susceptibility classifier",
        "dataset": str(dataset),
        "dataset_rows": int(len(labels)),
        "dataset_type": "synthetic_bootstrap_until_grid_or_ward_waterlogging_history_is_available",
        "forecast_horizon_hours": 6,
        "features": URBAN_FLOOD_FEATURE_NAMES,
        "targets": [TARGET_COLUMN, TARGET_CLASS_COLUMN],
        "susceptibility_classes": list(SUSCEPTIBILITY_CLASSES),
        "validation_split": {"train_rows": int(len(train_idx)), "validation_rows": int(len(validation_idx)), "test_rows": int(len(test_idx))},
        "test_metrics": metrics,
        "output_format": {
            "forecast_horizon_hours": "integer",
            "susceptibility_class": "Low | Moderate | High | Extremely high",
            "class_probabilities": "object keyed by susceptibility class",
            "model_name": "string",
            "model_type": "string",
        },
        "water_depth_note": "Use HEC-RAS 2D or another hydraulic model for predicted water-depth bands; this ML baseline is susceptibility only.",
        "artifact": str(destination),
    }
    Path(model_card_path).parent.mkdir(parents=True, exist_ok=True)
    Path(model_card_path).write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def load_urban_flood_dataset(dataset_path: str) -> tuple[np.ndarray, np.ndarray]:
    features: list[list[float]] = []
    labels: list[int] = []
    with Path(dataset_path).open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            features.append([float(row[name]) for name in URBAN_FLOOD_FEATURE_NAMES])
            labels.append(int(float(row[TARGET_COLUMN])))
    return np.asarray(features, dtype=np.float32), np.asarray(labels, dtype=np.int32)


def _fit_and_predict(features, labels, train_idx, validation_idx, test_idx):
    train_data = lgb.Dataset(features[train_idx], label=labels[train_idx], feature_name=URBAN_FLOOD_FEATURE_NAMES)
    validation_data = lgb.Dataset(features[validation_idx], label=labels[validation_idx], reference=train_data, feature_name=URBAN_FLOOD_FEATURE_NAMES)
    model = lgb.train(
        {
            "objective": "multiclass",
            "num_class": len(SUSCEPTIBILITY_CLASSES),
            "metric": "multi_logloss",
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


def _multiclass_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    predictions = np.argmax(probabilities, axis=1)
    accuracy = float(np.mean(predictions == labels))
    macro_recall = []
    for class_id in range(len(SUSCEPTIBILITY_CLASSES)):
        mask = labels == class_id
        macro_recall.append(float(np.mean(predictions[mask] == class_id)) if np.any(mask) else 0.0)
    return {
        "accuracy": round(accuracy, 4),
        "macro_recall": round(float(np.mean(macro_recall)), 4),
        "test_rows": int(len(labels)),
    }


def _require_lightgbm() -> None:
    if lgb is None:
        raise RuntimeError("LightGBM is required for the urban-flood baseline. Install requirements.txt first.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the urban-flood susceptibility LightGBM baseline")
    parser.add_argument("--dataset", default="app/ml/data/urban_flood_training.csv")
    parser.add_argument("--output", default="app/ml/artifacts/urban_flood_lightgbm_baseline.txt")
    parser.add_argument("--model-card", default="app/ml/artifacts/urban_flood_lightgbm_baseline.model-card.json")
    parser.add_argument("--rows", type=int, default=3600)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.model_card, args.rebuild, args.rows), indent=2))
