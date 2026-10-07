from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.flood import PredictionResponse, RiskResponse
from app.schemas.model_forecast import ModelForecastPointResponse
from app.services.model_forecast_service import ModelForecastService
from app.services.risk_service import RiskService
from app.services.river_service import RiverService
from app.services.weather_service import WeatherService

router = APIRouter(prefix="/flood", tags=["Flood Risk"])


@router.get("/risk", response_model=RiskResponse)
async def flood_risk(location_id: str, db: Session = Depends(get_db)):
    settings = get_settings()
    weather = await WeatherService(db, settings.data_mode).current(location_id)
    river = await RiverService(db, settings.data_mode).current(location_id)
    return RiskService(db).evaluate(weather, river)


@router.get("/predictions", response_model=list[PredictionResponse])
async def predictions(location_id: str | None = None, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return RiskService(db).predictions(location_id, limit)


@router.get("/model-forecasts", response_model=list[ModelForecastPointResponse])
async def model_forecasts(
    model_case: str | None = None,
    target_id: str | None = None,
    limit: int = Query(300, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return ModelForecastService(db).forecasts(model_case=model_case, target_id=target_id, limit=limit)
