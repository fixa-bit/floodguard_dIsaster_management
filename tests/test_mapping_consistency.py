import ast
import re
from pathlib import Path

from app.core.enums import Scenario
from app.locations import LOCATIONS


FRONTEND_CONFIG = Path(__file__).parents[1] / "frontend" / "src" / "config" / "index.ts"


def _frontend_locations() -> list[dict]:
    source = FRONTEND_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"export const LOCATIONS = \[(.*?)\] as const;", source, re.S)
    assert match is not None
    entries = []
    for raw_entry in re.findall(r"\{(.*?)\}", match.group(1), re.S):
        normalized = re.sub(r"(\w+):", r'"\1":', raw_entry)
        entries.append(ast.literal_eval("{" + normalized + "}"))
    return entries


def _frontend_scenarios() -> list[str]:
    source = FRONTEND_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"export const SCENARIOS = \[(.*?)\] as const;", source, re.S)
    assert match is not None
    return ast.literal_eval("[" + match.group(1) + "]")


def test_frontend_location_mapping_matches_backend_catalog():
    expected = [
        {
            "id": location.id,
            "name": location.name,
            "region": location.region,
            "river": location.river_name,
            "latitude": location.latitude,
            "longitude": location.longitude,
        }
        for location in LOCATIONS.values()
    ]
    assert _frontend_locations() == expected


def test_frontend_scenarios_match_backend_enum_values():
    assert _frontend_scenarios() == [scenario.value for scenario in Scenario]
