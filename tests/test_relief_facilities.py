import json

from app.services import relief_facilities


def _extract(tmp_path, monkeypatch, facilities):
    path = tmp_path / "facilities.json"
    path.write_text(json.dumps({"source": "OpenStreetMap contributors (ODbL)", "retrieved_at": "2026-11-19T00:00:00+00:00",
                                "note": "Community-mapped.", "counts": {}, "facilities": facilities}), encoding="utf-8")
    monkeypatch.setattr(relief_facilities, "DATA_PATH", path)


def test_nearby_counts_within_radius_and_names_the_nearest_outside(tmp_path, monkeypatch):
    jhang = (31.2681, 72.3187)
    _extract(tmp_path, monkeypatch, [
        {"id": "n1", "category": "hospital", "lat": 31.27, "lon": 72.32, "name": "DHQ Hospital Jhang", "tags": {"beds": "300"}},
        {"id": "n2", "category": "hospital", "lat": 31.40, "lon": 72.32, "name": "Far hospital", "tags": {}},     # ~15 km north
        {"id": "n3", "category": "school", "lat": 31.28, "lon": 72.33, "name": "Govt High School", "tags": {}},
        {"id": "n4", "category": "rescue", "lat": 32.50, "lon": 72.30, "name": "Rescue 1122", "tags": {}},        # ~137 km away
    ])
    reply = relief_facilities.nearby(*jhang, radius_km=10)
    by = {c["category"]: c for c in reply["categories"]}
    assert reply["available"] and reply["total"] == 2
    assert by["hospital"]["count"] == 1 and by["hospital"]["items"][0]["name"] == "DHQ Hospital Jhang"
    assert by["school"]["count"] == 1
    # Nothing within 10 km: the nearest one is still named, so the gap shows.
    assert by["rescue"]["count"] == 0 and by["rescue"]["nearest_outside"]["name"] == "Rescue 1122"
    assert 130 < by["rescue"]["nearest_outside"]["distance_km"] < 145
    assert relief_facilities.nearby(*jhang, radius_km=25)["categories"][0]["count"] == 2


def test_nearby_without_the_extract_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(relief_facilities, "DATA_PATH", tmp_path / "missing.json")
    reply = relief_facilities.nearby(31.0, 72.0, 25)
    assert reply["available"] is False and "fetch_osm_relief_facilities" in reply["note"]
