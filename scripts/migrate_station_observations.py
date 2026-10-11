"""Add the observation table without altering existing station data."""
from app.db.session import engine
from app.models.station_observation import StationObservation


def main():
    StationObservation.__table__.create(bind=engine, checkfirst=True)
    print("station_observations migration complete (existing tables unchanged).")


if __name__ == "__main__":
    main()
