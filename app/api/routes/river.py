from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.river import RiverResponse
from app.schemas.upstream_forecast import UpstreamForecastResponse
from app.services.river_service import RiverService
from app.services.upstream_forecast_cache_service import upstream_forecast_cache
from app.schemas.river_monitoring import RiverMonitoringResponse
from app.services.river_monitoring_service import river_monitoring_cache
from app.models.river_gauge_observation import RiverGaugeObservation
from app.gis.river_stations import STATIONS

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


@router.get("/monitoring/{station_id}/history")
def station_observation_history(station_id: str, db: Session = Depends(get_db)):
    if station_id not in {row[0] for row in STATIONS}:
        raise HTTPException(status_code=404, detail="Unknown monitoring station")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = db.scalars(select(RiverGaugeObservation).where(
        RiverGaugeObservation.station_id == station_id,
        RiverGaugeObservation.recorded_at >= cutoff,
    ).order_by(RiverGaugeObservation.recorded_at.desc()).limit(1000)).all()
    return {"station_id": station_id, "source": "FFD stored observations", "samples": [
        {"time": (row.recorded_at if row.recorded_at.tzinfo else row.recorded_at.replace(tzinfo=timezone.utc)).isoformat(),
         "value": row.discharge_cumecs} for row in reversed(rows)
    ]}
