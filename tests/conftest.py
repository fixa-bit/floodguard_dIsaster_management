import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/floodguard_test.db"
os.environ["DATA_MODE"] = "simulation"
os.environ["ENABLE_SIMULATION"] = "true"
os.environ["ALLOW_RULE_BASED_FALLBACK"] = "true"
os.environ["ML_MODEL_ENABLED"] = "true"
os.environ["WEATHER_CACHE_DIR"] = ""
os.environ["LAST_GOOD_CACHE_DIR"] = ""
os.environ["WEATHER_API_FALLBACK_BASE_URL"] = ""

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import engine
from app.db.session import SessionLocal
from app.main import app
from app.gis.national_risk_service import NationalRiskService
from app.providers import open_meteo_weather_cache


@pytest.fixture(autouse=True)
def reset_db():
    NationalRiskService.clear_cache()
    open_meteo_weather_cache.reset_state()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
