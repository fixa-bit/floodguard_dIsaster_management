import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import EventType, HazardType, IncidentStatus, Severity
from app.core.exceptions import AppError
from app.models.incident import Incident
from app.models.monitoring_simulation_run import MonitoringSimulationRun
from app.models.system_event import SystemEvent
from app.schemas.event import EventResponse
from app.schemas.incident import IncidentResponse
from app.schemas.monitoring_simulation import (
    MonitoringSimulationRequest, MonitoringSimulationResponse, SimulationStation,
    SimulationStoredReading, SimulationThreshold,
)
from monitoring.models import Provider, Station, StationValue, Threshold
from monitoring.repository import store_value
from monitoring.simulation import ensure_simulation_provider


def simulation_stations(db: Session) -> list[SimulationStation]:
    thresholds = list(db.scalars(select(Threshold)))
    return [SimulationStation(
        code=station.code, name=station.name, river=station.river,
        thresholds=[SimulationThreshold.model_validate(row, from_attributes=True)
                    for row in thresholds if row.station_id == station.id],
    ) for station in db.scalars(select(Station).order_by(Station.name))]


class MonitoringSimulationService:
    def __init__(self, db: Session, monitoring_db: Session):
        self.db = db
        self.monitoring_db = monitoring_db

    def play(self, payload: MonitoringSimulationRequest) -> MonitoringSimulationResponse:
        run_id = str(payload.run_id)
        fingerprint = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        existing = self.db.get(MonitoringSimulationRun, run_id)
        if existing:
            if existing.fingerprint != fingerprint:
                raise AppError("SIMULATION_RUN_CONFLICT", "This run ID already belongs to different testing data", 409)
            return MonitoringSimulationResponse.model_validate(existing.result)

        station = self.monitoring_db.scalar(select(Station).where(Station.code == payload.station))
        if station is None:
            raise AppError("SIMULATION_STATION_NOT_FOUND", "Select a station from the monitoring database", 404)
        thresholds = self._thresholds(payload, station)
        run = MonitoringSimulationRun(id=run_id, fingerprint=fingerprint, result={})
        self.db.add(run)
        try:
            self.db.flush()
        except IntegrityError as exc:
            self.db.rollback()
            raise AppError("SIMULATION_RUN_CONFLICT", "This simulation run is already being processed; retry with the same data", 409) from exc

        provider_code = f"SIMULATED_FLOW_{payload.run_id.hex.upper()}"
        rows, alerts, incidents = [], [], []
        monitoring_committed = False
        try:
            provider = ensure_simulation_provider(self.monitoring_db, provider_code, f"Simulated flow - {payload.name}")
            # A provider is unique to a run, so retries after interruption reuse its readings.
            for reading in payload.readings:
                row, _ = store_value(
                    self.monitoring_db, station=station.code, provider=provider.code,
                    measurement=payload.measurement, unit=payload.unit, value_type="simulated",
                    value_at=payload.start_at + timedelta(minutes=reading.offset_minutes),
                    value=reading.value, p25=reading.p25, p75=reading.p75,
                    level_reference=payload.level_reference,
                )
                crossed = [(level, limit) for level, limit in thresholds if reading.value >= limit]
                level, limit = crossed[-1] if crossed else ("normal", None)
                rows.append(SimulationStoredReading(id=row.id, value_at=row.value_at, value=row.value, level=level))
                if not crossed:
                    continue
                severity = Severity.CRITICAL if level == "danger" else Severity.HIGH
                message = (f"SIMULATED FLOW - {station.name}: {payload.measurement} "
                           f"{reading.value:g} {payload.unit} reached {level} threshold {limit:g} {payload.unit}")
                incident = Incident(
                    location_id=station.code, type=HazardType.FLOOD.value, severity=severity.value,
                    status=IncidentStatus.OPEN.value, confidence=1.0, description=message,
                    source="SIMULATED_FLOW", created_at=datetime.now(timezone.utc),
                )
                self.db.add(incident)
                self.db.flush()
                metadata = {
                    "source": "SIMULATED_FLOW", "value_type": "simulated", "run_id": run_id,
                    "scenario": payload.name, "station": station.code, "station_name": station.name,
                    "station_value_id": row.id, "measurement": payload.measurement, "value": reading.value,
                    "unit": payload.unit, "value_at": row.value_at.isoformat(), "severity": severity.value,
                    "threshold_level": level, "threshold_value": limit, "threshold_mode": payload.threshold_mode,
                    "level_reference": payload.level_reference, "provider": provider.code, "incident_id": incident.id,
                }
                alert = SystemEvent(event_type=EventType.ALERT_REQUIRED.value, location_id=station.code,
                                    message=message, event_metadata=metadata)
                self.db.add_all([alert, SystemEvent(
                    event_type=EventType.INCIDENT_CREATED.value, location_id=station.code,
                    message=f"SIMULATED FLOW - Incident {incident.id} recorded for {station.name}",
                    event_metadata=metadata,
                )])
                self.db.flush()
                alerts.append(EventResponse.model_validate(alert))
                incidents.append(IncidentResponse.model_validate(incident))

            result = MonitoringSimulationResponse(
                run_id=run_id, name=payload.name, station=station.code, station_name=station.name,
                provider=provider_code, inserted=len(rows), readings=rows, alerts=alerts, incidents=incidents,
            )
            run.result = result.model_dump(mode="json")
            self.db.add(SystemEvent(
                event_type=EventType.SIMULATION_STARTED.value, location_id=station.code,
                message=f"SIMULATED FLOW - {payload.name}: {len(rows)} readings saved, {len(alerts)} alerts",
                event_metadata={"run_id": run_id, "source": "SIMULATED_FLOW", "provider": provider_code},
            ))
            # The stores use separate databases; compensate if the alert/incident commit fails.
            self.monitoring_db.commit()
            monitoring_committed = True
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            self.monitoring_db.rollback()
            if monitoring_committed:
                provider = self.monitoring_db.scalar(select(Provider).where(Provider.code == provider_code))
                if provider:
                    self.monitoring_db.execute(delete(StationValue).where(StationValue.provider_id == provider.id))
                    self.monitoring_db.delete(provider)
                    self.monitoring_db.commit()
            raise

    def _thresholds(self, payload, station):
        if payload.threshold_mode == "custom":
            return [(level, value) for level, value in [
                ("warning", payload.warning_threshold), ("danger", payload.danger_threshold),
            ] if value is not None]
        rows = list(self.monitoring_db.scalars(select(Threshold).where(
            Threshold.station_id == station.id, Threshold.measurement == payload.measurement,
            Threshold.unit == payload.unit, Threshold.level.in_(["warning", "danger"]),
            Threshold.value.is_not(None),
        )))
        if payload.measurement == "water_level":
            rows = [row for row in rows if row.level_reference and row.level_reference == payload.level_reference]
        by_level = {row.level: row.value for row in rows}
        if not by_level:
            raise AppError("SIMULATION_THRESHOLDS_MISSING", "No saved thresholds match this measurement, unit and datum. Enter custom test thresholds.", 400)
        if "warning" in by_level and "danger" in by_level and by_level["danger"] <= by_level["warning"]:
            raise AppError("SIMULATION_THRESHOLDS_INVALID", "Saved danger threshold must exceed warning threshold", 400)
        return [(level, by_level[level]) for level in ["warning", "danger"] if level in by_level]
