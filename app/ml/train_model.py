import argparse
from pathlib import Path

import xgboost as xgb

from app.ml.synthetic_data import generate_synthetic_training_data


def train(output_path: str, rows: int = 6000) -> Path:
    features, labels = generate_synthetic_training_data(rows=rows)
    training_data = xgb.DMatrix(features, label=labels)
    model = xgb.train(
        {
            "objective": "reg:squarederror",
            "max_depth": 4,
            "eta": 0.05,
            "subsample": 0.9,
            "colsample_bytree": 0.9,
            "seed": 42,
            "nthread": 2,
        },
        training_data,
        num_boost_round=180,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the development-only synthetic flood-risk model")
    parser.add_argument("--output", default="app/ml/artifacts/flood_risk_xgboost.json")
    parser.add_argument("--rows", type=int, default=6000)
    args = parser.parse_args()
    print(train(args.output, args.rows))
