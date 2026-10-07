from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.model_forecast import ModelForecastPoint
from app.simulation.model_forecasts import build_dummy_model_forecasts


class ModelForecastService:
    refresh_after_minutes = 15
    dummy_source_version = "dummy_model_forecast_v3"

    def __init__(self, db: Session):
        self.db = db

    def forecasts(
        self,
        model_case: str | None = None,
        target_id: str | None = None,
        limit: int = 300,
    ) -> list[ModelForecastPoint]:
        self.ensure_current_forecasts()
        query = select(ModelForecastPoint).order_by(
            ModelForecastPoint.model_case,
            ModelForecastPoint.target_id,
            ModelForecastPoint.horizon_hours,
        )
        if model_case:
            query = query.where(ModelForecastPoint.model_case == model_case)
        if target_id:
            query = query.where(ModelForecastPoint.target_id == target_id)
        return list(self.db.scalars(query.limit(limit)))

    def ensure_current_forecasts(self) -> None:
        latest = self.db.scalar(select(ModelForecastPoint.issued_at).order_by(ModelForecastPoint.issued_at.desc()).limit(1))
        latest_metadata = self.db.scalar(select(ModelForecastPoint.point_metadata).order_by(ModelForecastPoint.created_at.desc()).limit(1))
        now = datetime.now(timezone.utc)
        if latest is not None and latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        latest_source = latest_metadata.get("simulation_source") if isinstance(latest_metadata, dict) else None
        if (
            latest is not None
            and latest >= now - timedelta(minutes=self.refresh_after_minutes)
            and latest_source == self.dummy_source_version
        ):
            return
        self.db.execute(delete(ModelForecastPoint))
        self.db.add_all(self._calculate_forecasts(now))
        self.db.commit()

    def _calculate_forecasts(self, issued_at: datetime) -> list[ModelForecastPoint]:
        return build_dummy_model_forecasts(issued_at)
