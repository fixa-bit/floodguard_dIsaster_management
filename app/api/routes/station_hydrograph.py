from datetime import datetime, timedelta, timezone
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.gis.hydrograph_config import station_configs
from app.models.station_observation import StationObservation
from app.providers.open_meteo_hydrograph import open_meteo_hydrograph

router = APIRouter(prefix="/stations", tags=["Experimental hydrograph"])


@router.get("/{station_id}/hydrograph")
async def hydrograph(station_id: str, days: Literal["5", "30"] = "5", db: Session = Depends(get_db)):
    config = station_configs().get(station_id)
    if config is None:
        raise HTTPException(404, "Unknown station")
    model = await open_meteo_hydrograph.get(config, int(days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    rows = db.scalars(select(StationObservation).where(StationObservation.station_id == station_id,
        StationObservation.observed_at >= cutoff, StationObservation.observed_at <= datetime.now(timezone.utc))
        .order_by(StationObservation.observed_at).limit(1000)).all()
    rows = [row for row in rows if math.isfinite(row.discharge_cusecs) and row.discharge_cusecs >= 0]
    if not rows and not model["forecast"]:
        raise HTTPException(503, "Hydrograph data is temporarily unavailable. Please retry.")
    observed = [{"t": (row.observed_at if row.observed_at.tzinfo else row.observed_at.replace(tzinfo=timezone.utc)).isoformat(),
                 "v": row.discharge_cusecs, "source": row.source} for row in rows]
    return {"station": {**config.model_dump(), "observationBasis": "inflow", "modelCell": model["modelCell"], "cellVerified": False},
            "unit": "cusecs", "observed": observed, "forecast": model["forecast"],
            "thresholds": config.thresholds.model_dump(), "highestRecorded": config.highestRecorded.model_dump(),
            "generatedAt": model["generatedAt"], "stale": model["stale"], "forecastUnavailable": model.get("forecastUnavailable", False),
            "sources": {"observed": sorted({row.source for row in rows}),
                        "forecast": "Open-Meteo Flood API / GloFAS v4 (simulated, experimental)",
                        "forecastUrl": "https://open-meteo.com/en/docs/flood-api"}}
