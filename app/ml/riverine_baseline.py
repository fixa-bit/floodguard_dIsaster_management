import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xgboost as xgb


RIVERINE_FEATURE_NAMES = [
    "station_code",
    "forecast_horizon_hours",
    "q_t_cumecs",
    "q_t_minus_3h_cumecs",
    "q_t_minus_6h_cumecs",
    "q_t_minus_12h_cumecs",
    "q_t_minus_24h_cumecs",
    "rainfall_3h_mm",
    "rainfall_6h_mm",
    "rainfall_24h_mm",
    "upstream_q_cumecs",
    "reservoir_release_cumecs",
    "soil_moisture_percent",
    "forecast_rainfall_mm",
]

TARGET_COLUMN = "target_discharge_cumecs"
STATION_COLUMN = "target_station"
HORIZON_COLUMN = "forecast_horizon_hours"
SUPPORTED_STATIONS = {"Trimmu": 1.0, "Balloki": 2.0}
SUPPORTED_HORIZONS = (24, 48)
LAC_CUSECS_TO_CUMECS = 100000 * 0.028316846592

# FFD flood limits are published in lacs of cusecs for river stations.
# Values below are converted to cumecs so they match the model target unit.
FLOOD_CLASS_THRESHOLDS_CUMECS = {
    "Trimmu": [
        ("Below Low", 1.5 * LAC_CUSECS_TO_CUMECS),
        ("Low", 2.0 * LAC_CUSECS_TO_CUMECS),
        ("Medium", 3.0 * LAC_CUSECS_TO_CUMECS),
        ("High", 4.5 * LAC_CUSECS_TO_CUMECS),
        ("Very High", 6.0 * LAC_CUSECS_TO_CUMECS),
        ("Exceptionally High", float("inf")),
    ],
    "Balloki": [
        ("Below Low", 0.4 * LAC_CUSECS_TO_CUMECS),
        ("Low", 0.65 * LAC_CUSECS_TO_CUMECS),
        ("Medium", 0.9 * LAC_CUSECS_TO_CUMECS),
        ("High", 1.35 * LAC_CUSECS_TO_CUMECS),
        ("Very High", 1.8 * LAC_CUSECS_TO_CUMECS),
        ("Exceptionally High", float("inf")),
    ],
}


@dataclass(frozen=True)
class RiverineForecastInput:
    target_station: str
    forecast_horizon_hours: int
    q_t_cumecs: float
    q_t_minus_3h_cumecs: float
    q_t_minus_6h_cumecs: float
    q_t_minus_12h_cumecs: float
    q_t_minus_24h_cumecs: float
    rainfall_3h_mm: float
    rainfall_6h_mm: float
    rainfall_24h_mm: float
    upstream_q_cumecs: float
    reservoir_release_cumecs: float
    soil_moisture_percent: float
    forecast_rainfall_mm: float

    def as_model_vector(self) -> list[float]:
        return [
            _station_code(self.target_station),
            float(self.forecast_horizon_hours),
            self.q_t_cumecs,
            self.q_t_minus_3h_cumecs,
            self.q_t_minus_6h_cumecs,
            self.q_t_minus_12h_cumecs,
            self.q_t_minus_24h_cumecs,
            self.rainfall_3h_mm,
            self.rainfall_6h_mm,
            self.rainfall_24h_mm,
            self.upstream_q_cumecs,
            self.reservoir_release_cumecs,
            self.soil_moisture_percent,
            self.forecast_rainfall_mm,
        ]


class XGBoostRiverineBaseline:
    name = "xgboost_riverine_baseline_v1"
    model_type = "riverine_discharge_regression"

    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self._model: xgb.Booster | None = None

    def _load(self) -> xgb.Booster:
        if self._model is None:
            model = xgb.Booster()
            model.load_model(self.model_path)
            self._model = model
        return self._model

    def predict(self, features: RiverineForecastInput) -> dict:
        matrix = xgb.DMatrix(
            np.asarray([features.as_model_vector()], dtype=np.float32),
            feature_names=RIVERINE_FEATURE_NAMES,
        )
        discharge = max(float(self._load().predict(matrix)[0]), 0.0)
        return {
            "station": features.target_station,
            "forecast_horizon_hours": features.forecast_horizon_hours,
            "predicted_discharge_cumecs": round(discharge, 2),
            "flood_class": classify_flood(features.target_station, discharge),
            "model_name": self.name,
            "model_type": self.model_type,
        }


def classify_flood(station: str, discharge_cumecs: float) -> str:
    for flood_class, upper_bound in FLOOD_CLASS_THRESHOLDS_CUMECS[station]:
        if discharge_cumecs < upper_bound:
            return flood_class
    return "Exceptionally High"


def generate_synthetic_riverine_dataset(output_path: str, rows: int = 2400, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [STATION_COLUMN, *RIVERINE_FEATURE_NAMES[1:], TARGET_COLUMN, "target_flood_class"]
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for _ in range(rows):
            station = "Trimmu" if rng.random() < 0.5 else "Balloki"
            horizon = int(rng.choice(SUPPORTED_HORIZONS))
            base = 1350 if station == "Trimmu" else 1050
            q_t = np.clip(rng.normal(base, 520), 120, 6200)
            trend = rng.normal(0, 260)
            rain24 = np.clip(rng.gamma(2.2, 18), 0, 260)
            rain6 = np.clip(rain24 * rng.uniform(0.15, 0.55), 0, rain24)
            rain3 = np.clip(rain6 * rng.uniform(0.25, 0.75), 0, rain6)
            upstream = np.clip(q_t * rng.uniform(0.85, 1.35) + trend, 80, 7600)
            release = np.clip(rng.normal(620, 260), 0, 2200)
            soil = rng.uniform(25, 100)
            forecast_rain = np.clip(rng.gamma(2.0, 16), 0, 220)
            horizon_multiplier = 1.0 if horizon == 24 else 1.35
            target = (
                q_t * 0.48
                + upstream * 0.31
                + release * 0.12
                + rain24 * 5.5
                + forecast_rain * 7.0 * horizon_multiplier
                + soil * 5.0
                + trend * 0.22
                + rng.normal(0, 120)
            )
            target = float(np.clip(target, 0, 8000))
            row = {
                STATION_COLUMN: station,
                "forecast_horizon_hours": horizon,
                "q_t_cumecs": round(float(q_t), 3),
                "q_t_minus_3h_cumecs": round(float(np.clip(q_t - trend * 0.35 + rng.normal(0, 80), 0, 8000)), 3),
                "q_t_minus_6h_cumecs": round(float(np.clip(q_t - trend * 0.55 + rng.normal(0, 90), 0, 8000)), 3),
                "q_t_minus_12h_cumecs": round(float(np.clip(q_t - trend * 0.85 + rng.normal(0, 110), 0, 8000)), 3),
                "q_t_minus_24h_cumecs": round(float(np.clip(q_t - trend * 1.2 + rng.normal(0, 140), 0, 8000)), 3),
                "rainfall_3h_mm": round(float(rain3), 3),
                "rainfall_6h_mm": round(float(rain6), 3),
                "rainfall_24h_mm": round(float(rain24), 3),
                "upstream_q_cumecs": round(float(upstream), 3),
                "reservoir_release_cumecs": round(float(release), 3),
                "soil_moisture_percent": round(float(soil), 3),
                "forecast_rainfall_mm": round(float(forecast_rain), 3),
                TARGET_COLUMN: round(target, 3),
                "target_flood_class": classify_flood(station, target),
            }
            writer.writerow(row)
    return destination


def train(
    dataset_path: str,
    output_path: str,
    model_card_path: str,
    rebuild: bool = False,
    rows: int = 2400,
) -> dict:
    dataset = Path(dataset_path)
    if rebuild or not dataset.exists():
        generate_synthetic_riverine_dataset(str(dataset), rows=rows)
    features, targets, stations, horizons = load_riverine_dataset(str(dataset))
    train_idx, validation_idx, test_idx = _temporal_like_split(len(targets))
    model, predictions = _fit_and_predict(features, targets, train_idx, validation_idx, test_idx)
    metrics = _regression_metrics(targets[test_idx], predictions, stations[test_idx])
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(destination)
    card = {
        "model_name": XGBoostRiverineBaseline.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_family": "XGBoost baseline discharge regression",
        "dataset": str(dataset),
        "dataset_rows": int(len(targets)),
        "dataset_type": "synthetic_bootstrap_until_hourly_station_history_is_available",
        "target_stations": sorted(np.unique(stations).tolist()),
        "forecast_horizons_hours": sorted(int(value) for value in np.unique(horizons)),
        "features": RIVERINE_FEATURE_NAMES,
        "targets": [TARGET_COLUMN, "target_flood_class"],
        "flood_class_thresholds_cumecs": _serializable_thresholds(),
        "flood_class_threshold_source": "FFD Flood Limits of Rivers & Nullahs, https://ffd.pmd.gov.pk/flood-limits",
        "validation_split": {"train_rows": int(len(train_idx)), "validation_rows": int(len(validation_idx)), "test_rows": int(len(test_idx))},
        "test_metrics": metrics,
        "output_format": {
            "station": "string",
            "forecast_horizon_hours": "integer",
            "predicted_discharge_cumecs": "float",
            "flood_class": "Below Low | Low | Medium | High | Very High | Exceptionally High",
            "model_name": "string",
            "model_type": "string",
        },
        "next_model_to_compare": "Temporal Fusion Transformer after enough hourly station/NWP history exists",
        "artifact": str(destination),
    }
    Path(model_card_path).parent.mkdir(parents=True, exist_ok=True)
    Path(model_card_path).write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def load_riverine_dataset(dataset_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    targets: list[float] = []
    stations: list[str] = []
    horizons: list[int] = []
    with Path(dataset_path).open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            station = row[STATION_COLUMN]
            values = [_station_code(station)]
            values.extend(float(row[name]) for name in RIVERINE_FEATURE_NAMES[1:])
            rows.append(values)
            targets.append(float(row[TARGET_COLUMN]))
            stations.append(station)
            horizons.append(int(float(row[HORIZON_COLUMN])))
    return (
        np.asarray(rows, dtype=np.float32),
        np.asarray(targets, dtype=np.float32),
        np.asarray(stations),
        np.asarray(horizons, dtype=np.int32),
    )


def _fit_and_predict(features, targets, train_idx, validation_idx, test_idx) -> tuple[xgb.Booster, np.ndarray]:
    train_matrix = xgb.DMatrix(features[train_idx], label=targets[train_idx], feature_names=RIVERINE_FEATURE_NAMES)
    validation_matrix = xgb.DMatrix(features[validation_idx], label=targets[validation_idx], feature_names=RIVERINE_FEATURE_NAMES)
    test_matrix = xgb.DMatrix(features[test_idx], label=targets[test_idx], feature_names=RIVERINE_FEATURE_NAMES)
    model = xgb.train(
        {
            "objective": "reg:squarederror",
            "eval_metric": "rmse",
            "max_depth": 4,
            "eta": 0.05,
            "min_child_weight": 5,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "seed": 42,
            "nthread": 2,
        },
        train_matrix,
        num_boost_round=350,
        evals=[(validation_matrix, "validation")],
        early_stopping_rounds=35,
        verbose_eval=False,
    )
    return model, model.predict(test_matrix)


def _temporal_like_split(row_count: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    indexes = np.arange(row_count)
    train_end = max(round(row_count * 0.7), 1)
    validation_end = max(round(row_count * 0.85), train_end + 1)
    return indexes[:train_end], indexes[train_end:validation_end], indexes[validation_end:]


def _regression_metrics(labels: np.ndarray, predictions: np.ndarray, stations: np.ndarray) -> dict:
    errors = predictions - labels
    class_hits = [
        classify_flood(str(station), float(prediction)) == classify_flood(str(station), float(label))
        for station, prediction, label in zip(stations, predictions, labels, strict=True)
    ]
    return {
        "rmse_cumecs": round(float(np.sqrt(np.mean(errors**2))), 3),
        "mae_cumecs": round(float(np.mean(np.abs(errors))), 3),
        "mean_error_cumecs": round(float(np.mean(errors)), 3),
        "flood_class_accuracy": round(float(np.mean(class_hits)), 4),
        "test_rows": int(len(labels)),
    }


def _station_code(station: str) -> float:
    if station not in SUPPORTED_STATIONS:
        raise ValueError(f"Unsupported riverine station: {station}")
    return SUPPORTED_STATIONS[station]


def _serializable_thresholds() -> dict[str, list[dict[str, float | str]]]:
    thresholds = {}
    for station, bands in FLOOD_CLASS_THRESHOLDS_CUMECS.items():
        thresholds[station] = [
            {
                "flood_class": flood_class,
                "upper_bound_cumecs": "unbounded" if upper_bound == float("inf") else upper_bound,
            }
            for flood_class, upper_bound in bands
        ]
    return thresholds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the riverine XGBoost discharge baseline")
    parser.add_argument("--dataset", default="app/ml/data/riverine_station_training.csv")
    parser.add_argument("--output", default="app/ml/artifacts/riverine_xgboost_baseline.json")
    parser.add_argument("--model-card", default="app/ml/artifacts/riverine_xgboost_baseline.model-card.json")
    parser.add_argument("--rows", type=int, default=2400)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.model_card, args.rebuild, args.rows), indent=2))
