from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import Scenario, Severity, Trend
from app.models.system_state import SystemState


INTERVALS = {
    Severity.LOW: 60,
    Severity.MEDIUM: 30,
    Severity.HIGH: 15,
    Severity.CRITICAL: 5,
}

INTERVAL_MODES = {value: key for key, value in INTERVALS.items()}


def recommended_interval(severity: Severity, trend: Trend) -> int:
    interval = INTERVALS[severity]
    if trend == Trend.RAPIDLY_RISING:
        return 5
    if trend == Trend.RISING:
        ordered = [60, 30, 15, 5]
        return ordered[min(ordered.index(interval) + 1, len(ordered) - 1)]
    return interval


class StateService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def get_state(self) -> SystemState:
        state = self.db.get(SystemState, 1)
        if state is None:
            state = SystemState(
                id=1,
                active_scenario=Scenario.NORMAL.value,
                active_location_id=self.settings.default_location_id,
                monitoring_mode=Severity.LOW.value,
                monitoring_interval_minutes=self.settings.default_monitoring_interval,
            )
            self.db.add(state)
            self.db.commit()
            self.db.refresh(state)
        return state

    def set_scenario(self, scenario: Scenario, location_id: str) -> SystemState:
        state = self.get_state()
        state.active_scenario = scenario.value
        state.active_location_id = location_id
        state.simulation_time = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(state)
        return state

    def advance_time(self, hours: int = 1) -> SystemState:
        state = self.get_state()
        state.simulation_time = state.simulation_time + timedelta(hours=hours)
        self.db.commit()
        self.db.refresh(state)
        return state

    def update_monitoring(self, severity: Severity, trend: Trend = Trend.STABLE) -> tuple[SystemState, bool, int]:
        state = self.get_state()
        previous = state.monitoring_interval_minutes
        new_interval = recommended_interval(severity, trend)
        now = datetime.now(timezone.utc)
        changed = False

        if new_interval < previous:
            changed = True
        elif new_interval > previous:
            last = state.last_monitoring_change_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            cooldown = timedelta(minutes=self.settings.monitoring_downgrade_cooldown_minutes)
            changed = now - last >= cooldown

        if changed:
            state.monitoring_mode = INTERVAL_MODES[new_interval].value
            state.monitoring_interval_minutes = new_interval
            state.last_monitoring_change_at = now
            self.db.commit()
            self.db.refresh(state)
        return state, changed, previous
