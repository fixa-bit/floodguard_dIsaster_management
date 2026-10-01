import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/floodguard_test.db"
os.environ["DATA_MODE"] = "simulation"
os.environ["ENABLE_SIMULATION"] = "true"
os.environ["ALLOW_RULE_BASED_FALLBACK"] = "true"
os.environ["ML_MODEL_ENABLED"] = "true"

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import engine
from app.db.session import SessionLocal
from app.main import app
from app.gis.national_risk_service import NationalRiskService


@pytest.fixture(autouse=True)
def reset_db():
    NationalRiskService.clear_cache()
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
