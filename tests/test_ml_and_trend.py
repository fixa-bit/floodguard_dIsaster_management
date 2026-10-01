from app.core.enums import Scenario, Severity, Trend
from app.ml.model import XGBoostRiskModel
from app.models.prediction import Prediction
from app.providers.simulation.simulation_river_provider import SimulationRiverProvider
from app.providers.simulation.simulation_weather_provider import SimulationWeatherProvider
from app.risk.features import build_features
from app.risk.trend import calculate_trend
from app.services.state_service import recommended_interval


def test_xgboost_model_inference():
    import asyncio

    weather = asyncio.run(SimulationWeatherProvider().get_current("JHG_001", Scenario.DEVELOPING_FLOOD))
    river = asyncio.run(SimulationRiverProvider().get_current("JHG_001", Scenario.DEVELOPING_FLOOD))
    probability = XGBoostRiskModel("app/ml/artifacts/flood_risk_xgboost.json").predict(build_features(weather, river))
    assert 0.58 <= probability < 0.78


def test_rule_engine_fallback_when_ml_fails(client, monkeypatch):
    def fail_inference(*_):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.services.risk_service.XGBoostRiskModel.predict", fail_inference)
    client.post("/api/v1/simulation/start", json={"scenario": "HEAVY_RAIN", "location_id": "JHG_001"})
    result = client.get("/api/v1/flood/risk?location_id=JHG_001")
    assert result.status_code == 200
    assert result.json()["model"] == "rule_based_v1"
    assert result.json()["model_type"] == "rule_based"


def test_prediction_persists_model_source_and_trend(client, db_session):
    response = client.get("/api/v1/flood/risk?location_id=JHG_001")
    assert response.status_code == 200
    persisted = db_session.query(Prediction).one()
    assert persisted.model_name == "xgboost_v1"
    assert persisted.weather_source == "simulation"
    assert persisted.river_source == "simulation"
    assert persisted.trend == "STABLE"
    assert persisted.probability_change == 0


def test_trend_calculation_thresholds():
    assert calculate_trend(None, 0.2) == (Trend.STABLE, 0.0)
    assert calculate_trend(0.2, 0.27) == (Trend.RISING, 0.07)
    assert calculate_trend(0.2, 0.36) == (Trend.RAPIDLY_RISING, 0.16)
    assert calculate_trend(0.5, 0.4) == (Trend.FALLING, -0.1)


def test_rising_trend_shortens_monitoring_recommendation():
    assert recommended_interval(Severity.LOW, Trend.STABLE) == 60
    assert recommended_interval(Severity.LOW, Trend.RISING) == 30
    assert recommended_interval(Severity.LOW, Trend.RAPIDLY_RISING) == 5


def test_endpoint_calculates_trend_from_prediction_history(client, monkeypatch):
    predictions = iter([0.2, 0.36])
    monkeypatch.setattr("app.services.risk_service.XGBoostRiskModel.predict", lambda *_: next(predictions))
    first = client.get("/api/v1/flood/risk?location_id=JHG_001").json()
    second = client.get("/api/v1/flood/risk?location_id=JHG_001").json()
    assert first["trend"] == "STABLE"
    assert second["trend"] == "RAPIDLY_RISING"
    assert second["probability_change"] == 0.16
    assert second["monitoring_interval_minutes"] == 5
