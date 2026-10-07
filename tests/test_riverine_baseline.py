from pathlib import Path

import numpy as np

from app.ml.riverine_baseline import (
    RIVERINE_FEATURE_NAMES,
    RiverineForecastInput,
    XGBoostRiverineBaseline,
    classify_flood,
    generate_synthetic_riverine_dataset,
    load_riverine_dataset,
    train,
)


def test_riverine_feature_vector_matches_feature_names():
    features = RiverineForecastInput(
        target_station="Trimmu",
        forecast_horizon_hours=24,
        q_t_cumecs=1200,
        q_t_minus_3h_cumecs=1150,
        q_t_minus_6h_cumecs=1100,
        q_t_minus_12h_cumecs=1000,
        q_t_minus_24h_cumecs=900,
        rainfall_3h_mm=12,
        rainfall_6h_mm=20,
        rainfall_24h_mm=42,
        upstream_q_cumecs=1500,
        reservoir_release_cumecs=500,
        soil_moisture_percent=76,
        forecast_rainfall_mm=30,
    )

    assert len(features.as_model_vector()) == len(RIVERINE_FEATURE_NAMES)
    assert features.as_model_vector()[0] == 1.0


def test_flood_class_uses_station_thresholds():
    assert classify_flood("Trimmu", 500) == "Below Low"
    assert classify_flood("Trimmu", 5000) == "Low"
    assert classify_flood("Trimmu", 18000) == "Exceptionally High"
    assert classify_flood("Balloki", 2500) == "Medium"
    assert classify_flood("Balloki", 3000) == "High"


def test_synthetic_riverine_dataset_loads(tmp_path: Path):
    dataset = generate_synthetic_riverine_dataset(str(tmp_path / "riverine.csv"), rows=32)
    features, targets, stations, horizons = load_riverine_dataset(str(dataset))

    assert features.shape == (32, len(RIVERINE_FEATURE_NAMES))
    assert targets.shape == (32,)
    assert set(np.unique(stations)).issubset({"Trimmu", "Balloki"})
    assert set(np.unique(horizons)).issubset({24, 48})


def test_riverine_training_writes_model_card_and_predicts(tmp_path: Path):
    artifact = tmp_path / "riverine.json"
    card_path = tmp_path / "riverine.model-card.json"
    card = train(str(tmp_path / "riverine.csv"), str(artifact), str(card_path), rebuild=True, rows=180)

    assert artifact.exists()
    assert card_path.exists()
    assert card["output_format"]["flood_class"].startswith("Below Low")

    model = XGBoostRiverineBaseline(str(artifact))
    prediction = model.predict(
        RiverineForecastInput(
            target_station="Balloki",
            forecast_horizon_hours=48,
            q_t_cumecs=1300,
            q_t_minus_3h_cumecs=1250,
            q_t_minus_6h_cumecs=1200,
            q_t_minus_12h_cumecs=1100,
            q_t_minus_24h_cumecs=1000,
            rainfall_3h_mm=10,
            rainfall_6h_mm=18,
            rainfall_24h_mm=35,
            upstream_q_cumecs=1500,
            reservoir_release_cumecs=550,
            soil_moisture_percent=70,
            forecast_rainfall_mm=28,
        )
    )

    assert prediction["station"] == "Balloki"
    assert prediction["forecast_horizon_hours"] == 48
    assert prediction["predicted_discharge_cumecs"] >= 0
    assert prediction["flood_class"] in card["output_format"]["flood_class"]
