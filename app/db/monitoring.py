from functools import lru_cache

from monitoring.database import create_monitoring_engine, session_factory
from monitoring.migrations.runner import upgrade
from monitoring.seed import seed


@lru_cache
def monitoring_sessions():
    engine = create_monitoring_engine()
    upgrade(engine)
    sessions = session_factory(engine)
    with sessions.begin() as db:
        seed(db)
    return sessions


def get_monitoring_db():
    with monitoring_sessions()() as db:
        yield db
