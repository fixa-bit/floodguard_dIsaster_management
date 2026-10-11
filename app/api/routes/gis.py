from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import DataMode, Scenario
from app.core.exceptions import AppError
from app.db.session import get_db
from app.gis.national_risk_service import NationalRiskService
from app.gis.rainfall_service import RainfallService
from app.gis.water_intelligence_service import WaterIntelligenceService
from app.services.state_service import StateService
from app.services.google_flood_service import google_flood_service


router = APIRouter(prefix="/gis", tags=["National GIS"])


@router.get("/google-flood-hub")
async def google_flood_hub():
    return await google_flood_service.feature_collection()


@router.get("/rainfall")
async def rainfall():
    return await RainfallService().feature_collection()


def parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        bbox = tuple(float(item) for item in value.split(","))
    except ValueError as exc:
        raise AppError("INVALID_BBOX", "bbox must contain west,south,east,north", 422) from exc
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise AppError("INVALID_BBOX", "bbox must contain west,south,east,north", 422)
    return bbox


@router.get("/national-risk")
async def national_risk(bbox: str | None = None, db: Session = Depends(get_db)):
    settings = get_settings()
    state = StateService(db).get_state()
    scenario = Scenario(state.active_scenario) if settings.data_mode == DataMode.SIMULATION else Scenario.NORMAL
    return await NationalRiskService().feature_collection(settings.data_mode, scenario, parse_bbox(bbox))


@router.get("/water-intelligence")
async def water_intelligence(bbox: str | None = None, db: Session = Depends(get_db)):
    settings = get_settings()
    state = StateService(db).get_state()
    scenario = Scenario(state.active_scenario) if settings.data_mode == DataMode.SIMULATION else Scenario.NORMAL
    return WaterIntelligenceService().feature_collection(settings.data_mode, scenario, parse_bbox(bbox))

