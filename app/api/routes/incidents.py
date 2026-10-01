from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.incident import IncidentCreate, IncidentResponse, IncidentUpdate
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.get("", response_model=list[IncidentResponse])
async def list_incidents(db: Session = Depends(get_db)):
    return IncidentService(db).list()


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: int, db: Session = Depends(get_db)):
    return IncidentService(db).get(incident_id)


@router.post("", response_model=IncidentResponse, status_code=201)
async def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    return IncidentService(db).create(payload)


@router.patch("/{incident_id}", response_model=IncidentResponse)
async def update_incident(incident_id: int, payload: IncidentUpdate, db: Session = Depends(get_db)):
    return IncidentService(db).update(incident_id, payload)
