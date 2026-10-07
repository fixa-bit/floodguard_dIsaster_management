from pathlib import Path

import numpy as np
import pytest

from app.ml.urban_flood_baseline import (
    SUSCEPTIBILITY_CLASSES,
    URBAN_FLOOD_FEATURE_NAMES,
    LightGBMUrbanFloodBaseline,
    UrbanFloodForecastInput,
    classify_urban_flood,
    generate_synthetic_urban_flood_dataset,
    lgb,
    load_urban_flood_dataset,
    train,
)


def test_urban_flood_feature_vector_matches_feature_names():
    features = UrbanFloodForecastInput(
        rainfall_1h_mm=28,
        rainfall_3h_mm=72,
        rainfall_6h_mm=110,
        forecast_rainfall_6h_mm=45,
        dem_elevation_m=220,
        slope_degrees=1.5,
        drainage_capacity_mm_per_h=22,
        impervious_surface_percent=82,
        land_use_code=4,
        previous_waterlogging_reports_30d=6,
    )

    assert len(features.as_model_vector()) == len(URBAN_FLOOD_FEATURE_NAMES)


def test_urban_flood_class_thresholds():
    assert classify_urban_flood(0.1) == "Low"
    assert classify_urban_flood(0.4) == "Moderate"
    assert classify_urban_flood(0.6) == "High"
    assert classify_urban_flood(0.9) == "Extremely high"


def test_synthetic_urban_flood_dataset_loads(tmp_path: Path):
    dataset = generate_synthetic_urban_flood_dataset(str(tmp_path / "urban.csv"), rows=48)
    features, labels = load_urban_flood_dataset(str(dataset))

    assert features.shape == (48, len(URBAN_FLOOD_FEATURE_NAMES))
    assert labels.shape == (48,)
    assert set(np.unique(labels)).issubset(set(range(len(SUSCEPTIBILITY_CLASSES))))


@pytest.mark.skipif(lgb is None, reason="LightGBM is not installed")
def test_urban_flood_training_writes_model_card_and_predicts(tmp_path: Path):
    artifact = tmp_path / "urban.txt"
    card_path = tmp_path / "urban.model-card.json"
    card = train(str(tmp_path / "urban.csv"), str(artifact), str(card_path), rebuild=True, rows=260)

    assert artifact.exists()
    assert card_path.exists()
    assert card["output_format"]["susceptibility_class"].startswith("Low")

    model = LightGBMUrbanFloodBaseline(str(artifact))
    prediction = model.predict(
        UrbanFloodForecastInput(
            rainfall_1h_mm=34,
            rainfall_3h_mm=80,
            rainfall_6h_mm=126,
            forecast_rainfall_6h_mm=55,
            dem_elevation_m=215,
            slope_degrees=1.1,
            drainage_capacity_mm_per_h=18,
            impervious_surface_percent=88,
            land_use_code=4,
            previous_waterlogging_reports_30d=8,
        )
    )

    assert prediction["forecast_horizon_hours"] == 6
    assert prediction["susceptibility_class"] in SUSCEPTIBILITY_CLASSES
    assert set(prediction["class_probabilities"]) == set(SUSCEPTIBILITY_CLASSES)
