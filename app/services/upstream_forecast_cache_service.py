import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.upstream_forecast_snapshot import UpstreamForecastSnapshot
from app.schemas.upstream_forecast import UpstreamForecastResponse
from app.services.upstream_forecast_service import UpstreamForecastService

logger = logging.getLogger(__name__)


def utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


class UpstreamForecastCacheService:
    def __init__(self, session_factory=SessionLocal, forecast_factory=UpstreamForecastService,
                 snapshot_id=1, response_model=UpstreamForecastResponse, refresh_minutes=None):
        self.session_factory = session_factory
        self.forecast_factory = forecast_factory
        self.refresh_minutes = refresh_minutes or get_settings().upstream_forecast_refresh_minutes
        self.snapshot_id = snapshot_id
        self.response_model = response_model
        self.refresh_task: asyncio.Task | None = None
        self.worker_task: asyncio.Task | None = None

    def _read(self) -> UpstreamForecastSnapshot | None:
        with self.session_factory() as db:
            return db.get(UpstreamForecastSnapshot, self.snapshot_id)

    async def get(self, force_refresh: bool = False) -> UpstreamForecastResponse:
        snapshot = await asyncio.to_thread(self._read)
        now = datetime.now(timezone.utc)
        due = snapshot is None or snapshot.next_refresh_at is None or utc(snapshot.next_refresh_at) <= now
        if force_refresh or due:
            # A shared task prevents page visits, timers, and manual refreshes from duplicating requests.
            if self.refresh_task is None or self.refresh_task.done():
                self.refresh_task = asyncio.create_task(self._refresh())
        response = self.response_model.model_validate(snapshot.payload) if snapshot and snapshot.payload else self.response_model(
            generated_at=now.isoformat(), stations=[], notes=[],
        )
        response.cached_at = utc(snapshot.cached_at).isoformat() if snapshot and snapshot.cached_at else None
        response.last_attempt_at = utc(snapshot.last_attempt_at).isoformat() if snapshot and snapshot.last_attempt_at else None
        response.next_refresh_at = utc(snapshot.next_refresh_at).isoformat() if snapshot and snapshot.next_refresh_at else None
        response.refresh_error = snapshot.refresh_error if snapshot else None
        response.refresh_interval_minutes = self.refresh_minutes
        response.refreshing = self.refresh_task is not None and not self.refresh_task.done()
        return response

    def _save(self, payload: UpstreamForecastResponse | None, attempted_at: datetime, error: str | None):
        now = datetime.now(timezone.utc)
        with self.session_factory() as db:
            snapshot = db.get(UpstreamForecastSnapshot, self.snapshot_id)
            if snapshot is None:
                snapshot = UpstreamForecastSnapshot(id=self.snapshot_id)
                db.add(snapshot)
            if payload is not None:
                snapshot.payload = payload.model_dump(mode="json")
                snapshot.cached_at = now
            snapshot.last_attempt_at = attempted_at
            snapshot.next_refresh_at = now + timedelta(minutes=5 if error else self.refresh_minutes)
            snapshot.refresh_error = error
            db.commit()

    async def _refresh(self):
        attempted_at = datetime.now(timezone.utc)
        try:
            payload = await self.forecast_factory().forecasts()
            if not any(point.value is not None for station in payload.stations for provider in station.providers for point in provider.series) and not any(getattr(station, "observed_at", None) for station in payload.stations):
                raise ValueError("Both forecast providers are unavailable. Stored values are retained; retrying in 5 minutes.")
            await asyncio.to_thread(self._save, payload, attempted_at, None)
        except Exception as exc:
            logger.exception("Upstream forecast refresh failed")
            await asyncio.to_thread(self._save, None, attempted_at, str(exc)[:250])

    async def _worker(self):
        while True:
            try:
                await self.get()
            except Exception:
                logger.exception("Upstream forecast cache check failed")
            await asyncio.sleep(60)

    def start(self):
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        tasks = [task for task in (self.worker_task, self.refresh_task) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.worker_task = None
        self.refresh_task = None


upstream_forecast_cache = UpstreamForecastCacheService()
