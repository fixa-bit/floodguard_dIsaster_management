from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.citizen_report import CitizenReportCreate, CitizenReportResponse
from app.services.citizen_report_service import CitizenReportService

router = APIRouter(prefix="/citizen-reports", tags=["Citizen Reports"])


@router.post("", response_model=CitizenReportResponse, status_code=201)
async def create_report(payload: CitizenReportCreate, db: Session = Depends(get_db)):
    return CitizenReportService(db).create(payload)


@router.get("", response_model=list[CitizenReportResponse])
async def list_reports(db: Session = Depends(get_db)):
    return CitizenReportService(db).list()


@router.patch("/{report_id}/important", response_model=CitizenReportResponse)
async def toggle_report_important(report_id: int, db: Session = Depends(get_db)):
    return CitizenReportService(db).toggle_important(report_id)


@router.patch("/{report_id}/close", response_model=CitizenReportResponse)
async def close_report(report_id: int, db: Session = Depends(get_db)):
    return CitizenReportService(db).close(report_id)


@router.get("/{report_id}", response_model=CitizenReportResponse)
async def get_report(report_id: int, db: Session = Depends(get_db)):
    return CitizenReportService(db).get(report_id)
