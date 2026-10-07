from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.river import RiverResponse
from app.schemas.upstream_forecast import UpstreamForecastResponse
from app.services.river_service import RiverService
from app.services.upstream_forecast_cache_service import upstream_forecast_cache
from app.schemas.river_monitoring import RiverMonitoringResponse
from app.services.river_monitoring_service import river_monitoring_cache

router = APIRouter(prefix="/river", tags=["River"])


@router.get("/current", response_model=RiverResponse)
async def current_river(location_id: str, db: Session = Depends(get_db)):
    return await RiverService(db, get_settings().data_mode).current(location_id)


@router.get("/upstream-forecasts", response_model=UpstreamForecastResponse)
async def upstream_forecasts():
    return await upstream_forecast_cache.get()


@router.post("/upstream-forecasts/refresh", response_model=UpstreamForecastResponse)
async def refresh_upstream_forecasts():
    return await upstream_forecast_cache.get(force_refresh=True)


@router.get("/monitoring", response_model=RiverMonitoringResponse)
async def river_monitoring():
    return await river_monitoring_cache.get()


@router.post("/monitoring/refresh", response_model=RiverMonitoringResponse)
async def refresh_river_monitoring():
    return await river_monitoring_cache.get(force_refresh=True)
