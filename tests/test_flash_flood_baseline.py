from pathlib import Path

import numpy as np
import pytest

from app.ml.flash_flood_baseline import (
    FLASH_FLOOD_FEATURE_NAMES,
    FlashFloodForecastInput,
    LightGBMFlashFloodBaseline,
    classify_flash_flood,
    generate_synthetic_flash_flood_dataset,
    lgb,
    load_flash_flood_dataset,
    train,
)


def test_flash_flood_feature_vector_matches_feature_names():
    features = FlashFloodForecastInput(
        rainfall_15min_mm=8,
        rainfall_1h_mm=24,
        rainfall_3h_mm=55,
        rainfall_6h_mm=90,
        forecast_rainfall_6h_mm=40,
        soil_moisture_percent=82,
        slope_degrees=14,
        elevation_m=540,
        drainage_density_km_per_km2=2.4,
        land_cover_code=4,
        catchment_area_km2=75,
        distance_to_stream_km=0.4,
    )

    assert len(features.as_model_vector()) == len(FLASH_FLOOD_FEATURE_NAMES)


def test_flash_flood_class_thresholds():
    assert classify_flash_flood(0.01) == "No risk"
    assert classify_flash_flood(0.18) == "Low"
    assert classify_flash_flood(0.35) == "Moderate"
    assert classify_flash_flood(0.6) == "High"
    assert classify_flash_flood(0.85) == "Extreme"


def test_synthetic_flash_flood_dataset_loads(tmp_path: Path):
    dataset = generate_synthetic_flash_flood_dataset(str(tmp_path / "flash.csv"), rows=40)
    features, labels, probabilities = load_flash_flood_dataset(str(dataset))

    assert features.shape == (40, len(FLASH_FLOOD_FEATURE_NAMES))
    assert labels.shape == (40,)
    assert probabilities.shape == (40,)
    assert set(np.unique(labels)).issubset({0, 1})


@pytest.mark.skipif(lgb is None, reason="LightGBM is not installed")
def test_flash_flood_training_writes_model_card_and_predicts(tmp_path: Path):
    artifact = tmp_path / "flash.txt"
    card_path = tmp_path / "flash.model-card.json"
    card = train(str(tmp_path / "flash.csv"), str(artifact), str(card_path), rebuild=True, rows=240)

    assert artifact.exists()
    assert card_path.exists()
    assert card["output_format"]["risk_class"].startswith("No risk")

    model = LightGBMFlashFloodBaseline(str(artifact))
    prediction = model.predict(
        FlashFloodForecastInput(
            rainfall_15min_mm=10,
            rainfall_1h_mm=32,
            rainfall_3h_mm=75,
            rainfall_6h_mm=110,
            forecast_rainfall_6h_mm=42,
            soil_moisture_percent=88,
            slope_degrees=18,
            elevation_m=620,
            drainage_density_km_per_km2=2.8,
            land_cover_code=4,
            catchment_area_km2=55,
            distance_to_stream_km=0.25,
        )
    )

    assert prediction["forecast_horizon_hours"] == 6
    assert 0 <= prediction["flash_flood_probability"] <= 1
    assert prediction["risk_class"] in card["output_format"]["risk_class"]
