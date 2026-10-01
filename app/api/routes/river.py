from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.river import RiverResponse
from app.services.river_service import RiverService

router = APIRouter(prefix="/river", tags=["River"])


@router.get("/current", response_model=RiverResponse)
async def current_river(location_id: str, db: Session = Depends(get_db)):
    return await RiverService(db, get_settings().data_mode).current(location_id)
