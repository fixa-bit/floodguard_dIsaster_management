import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import EventType, FloodStatus, Scenario, Severity
from app.core.exceptions import AppError
from app.ml.model import XGBoostRiskModel
from app.locations import get_location
from app.models.prediction import Prediction
from app.risk.features import build_features
from app.risk.rule_based import RuleBasedRiskEngine
from app.risk.trend import calculate_trend
from app.schemas.flood import RiskResponse
from app.schemas.river import RiverResponse
from app.schemas.weather import WeatherResponse
from app.services.event_service import EventService
from app.services.state_service import StateService

logger = logging.getLogger(__name__)


class RiskService:
    def __init__(self, db: Session):
        self.db = db
        self.engine = RuleBasedRiskEngine()
        self.settings = get_settings()
        self.ml_model = XGBoostRiskModel(self.settings.ml_model_path)

    def evaluate(self, weather: WeatherResponse, river: RiverResponse) -> RiskResponse:
        location = get_location(weather.location_id)
        scenario = Scenario(weather.scenario)
        features = build_features(weather, river)
        rule_result = self.engine.evaluate(features, scenario)
        probability, severity, status, confidence, factors, explanation = rule_result
        model_name = "rule_based_v1"
        model_type = "rule_based"
        if self.settings.ml_model_enabled:
            try:
                probability = self.ml_model.predict(features)
                severity, status = self._classify(probability, scenario)
                confidence = 0.86
                model_name = self.ml_model.name
                model_type = self.ml_model.model_type
            except Exception as exc:
                if not self.settings.allow_rule_based_fallback:
                    logger.exception("ML inference failed; fallback is disabled")
                    raise AppError(
                        "ML_INFERENCE_ERROR",
                        "Flood-risk model inference failed and fallback is disabled",
                        503,
                    ) from exc
                logger.exception("ML inference failed; explicitly configured rule-based fallback is active")

        previous_probability = self.db.scalar(
            select(Prediction.probability)
            .where(Prediction.location_id == location.id)
            .order_by(Prediction.created_at.desc(), Prediction.id.desc())
            .limit(1)
        )
        trend, probability_change = calculate_trend(previous_probability, probability)
        top_risk_factors = self._top_risk_factors(features)
        state, changed, previous_interval = StateService(self.db).update_monitoring(severity, trend)
        prediction = Prediction(
            location_id=location.id,
            scenario=scenario.value,
            probability=probability,
            severity=severity.value,
            status=status.value,
            confidence=confidence,
            factors=factors,
            explanation=explanation,
            monitoring_interval_minutes=state.monitoring_interval_minutes,
            trend=trend.value,
            probability_change=probability_change,
            model_name=model_name,
            model_type=model_type,
            top_risk_factors=top_risk_factors,
            weather_source=weather.source,
            river_source=river.source,
        )
        self.db.add(prediction)
        self.db.commit()
        EventService(self.db).record(
            EventType.RISK_UPDATED,
            f"Risk updated for {location.name}: {severity.value} ({probability:.2f})",
            location.id,
            {"probability": probability, "severity": severity.value, "status": status.value},
        )
        if changed:
            EventService(self.db).record(
                EventType.MONITORING_MODE_CHANGED,
                f"Monitoring interval changed from {previous_interval} minutes to {state.monitoring_interval_minutes} minutes",
                location.id,
                {"previous_interval": previous_interval, "new_interval": state.monitoring_interval_minutes},
            )
        if severity == Severity.CRITICAL:
            EventService(self.db).record(EventType.ALERT_REQUIRED, "Critical flood risk requires alert workflow", location.id)
        logger.info("Risk evaluated for %s as %s", location.id, severity.value)
        return RiskResponse(
            location_id=location.id,
            location_name=location.name,
            timestamp=datetime.now(timezone.utc),
            scenario=scenario.value,
            flood_probability=probability,
            severity=severity.value,
            status=status.value,
            confidence=confidence,
            factors=factors,
            explanation=explanation,
            monitoring_mode=state.monitoring_mode,
            monitoring_interval_minutes=state.monitoring_interval_minutes,
            trend=trend.value,
            probability_change=probability_change,
            model=model_name,
            model_type=model_type,
            top_risk_factors=top_risk_factors,
            data_sources={"weather": weather.source, "river": river.source},
        )

    @staticmethod
    def _classify(probability: float, scenario: Scenario) -> tuple[Severity, FloodStatus]:
        if scenario == Scenario.FALSE_ALARM:
            return Severity.LOW, FloodStatus.FALSE_ALARM
        if scenario == Scenario.CONFIRMED_FLOOD:
            return Severity.CRITICAL, FloodStatus.CONFIRMED
        if probability >= 0.78:
            return Severity.CRITICAL, FloodStatus.PREDICTED
        if probability >= 0.58:
            return Severity.HIGH, FloodStatus.PREDICTED
        if probability >= 0.38:
            return Severity.MEDIUM, FloodStatus.UNDER_VERIFICATION
        return Severity.LOW, FloodStatus.NORMAL

    @staticmethod
    def _top_risk_factors(features) -> list[str]:
        ranked = [
            ("24-hour rainfall", features.rainfall_last_24h / 150),
            ("forecast rainfall", features.forecast_rainfall_24h / 100),
            ("river level vs warning level", features.river_level_relative_to_warning or 0),
            ("river rise rate", max(features.river_rise_rate or 0, 0) / 0.5),
            ("modeled river discharge", features.river_discharge / 2500),
            ("modeled discharge increase", max(features.river_discharge_change, 0) / 750),
            ("soil moisture", features.soil_moisture / 90),
            ("6-hour rainfall", features.rainfall_last_6h / 80),
            ("1-hour rainfall", features.rainfall_last_1h / 30),
        ]
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [name for name, score in ranked[:3] if score >= 0.2]

    def predictions(self, location_id: str | None = None, limit: int = 50) -> list[Prediction]:
        query = select(Prediction).order_by(Prediction.created_at.desc()).limit(limit)
        if location_id:
            get_location(location_id)
            query = query.where(Prediction.location_id == location_id)
        return list(self.db.scalars(query))
