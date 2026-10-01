from dataclasses import dataclass

from app.core.exceptions import AppError


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    latitude: float
    longitude: float
    region: str
    elevation_m: float | None
    river_name: str | None
    river_latitude: float | None
    river_longitude: float | None
    river_station_name: str | None


LOCATIONS: dict[str, Location] = {
    "JHG_001": Location(
        "JHG_001", "Jhang", 31.2681, 72.3187, "Punjab", 158, "Chenab", 31.144686, 72.146797, "Trimmu Barrage"
    ),
    "RWP_001": Location(
        "RWP_001", "Rawalpindi", 33.5651, 73.0169, "Punjab", 508, "Soan", 33.657906, 73.305031, "Chirrah"
    ),
    "MUL_001": Location(
        "MUL_001", "Multan", 30.1575, 71.5249, "Punjab", 122, "Chenab", 30.160252, 71.302468, "Sher Shah Reach"
    ),
    "ISB_001": Location(
        "ISB_001",
        "Islamabad",
        33.6844,
        73.0479,
        "Islamabad Capital Territory",
        540,
        "Korang",
        33.693880,
        73.122960,
        "Rawal Lake",
    ),
}


def get_location(location_id: str) -> Location:
    try:
        return LOCATIONS[location_id]
    except KeyError as exc:
        raise AppError("LOCATION_NOT_FOUND", "Unknown location_id", 404) from exc
