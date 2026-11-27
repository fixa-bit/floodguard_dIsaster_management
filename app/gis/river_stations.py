# Each station sits on its gauging structure as mapped in OpenStreetMap (checked 2026-11-25): where the
# barrage, headworks or gauge bridge spans the river, or the middle of the main dam (Tarbela, Mangla).
# Coordinates that already lay on the structure (within 50 m) are FFD's own river-state feed values,
# kept unchanged; Ganda Singh Wala has no structure to check against and keeps FFD's point.
STATIONS = [
    ("TARBELA", "Tarbela", "Indus", 34.08772, 72.700691, "Tarbela Dam"),  # Main Embankment Dam, OSM way 218764755
    ("KALABAGH", "Kalabagh", "Indus", 32.9187, 71.5219, "Kala Bagh"),
    ("CHASHMA", "Chashma", "Indus", 32.4359, 71.3794, "Chashma"),
    ("TAUNSA", "Taunsa", "Indus", 30.513031, 70.849405, "Taunsa"),  # Taunsa Barrage, way 27721368
    ("GUDDU", "Guddu", "Indus", 28.4201, 69.7114, "Guddu"),
    ("SUKKUR", "Sukkur", "Indus", 27.679, 68.8462, "Sukkur"),
    ("KOTRI", "Kotri", "Indus", 25.4428, 68.3151, "Kotri"),
    ("NOWSHERA", "Nowshera", "Kabul", 34.008815, 71.985649, "Nowshera"),  # Kabul River bridge nearest FFD's point, way 849036638
    ("MANGLA", "Mangla", "Jhelum", 33.141206, 73.641977, "Mangla"),  # Mangla Dam, way 245066466
    ("RASUL", "Rasul", "Jhelum", 32.68169, 73.519375, "Rasul"),  # Rasul Barrage, way 863371614
    ("JASSAR", "Jassar", "Ravi", 32.049654, 74.992018, "Jassar"),
    ("SHAHDARA", "Shahdara", "Ravi", 31.6085, 74.2956, "Shahdara"),
    ("BALLOKI", "Balloki", "Ravi", 31.2222, 73.8596, "Balloki"),
    ("SIDHNAI", "Sidhnai", "Ravi", 30.5723, 72.1582, "Sidhnai"),
    ("MARALA", "Marala", "Chenab", 32.668632, 74.467518, "Marala"),  # Marala Headworks, way 641342082
    ("KHANKI", "Khanki", "Chenab", 32.40627, 73.966999, "Khanki"),  # Khanki Headworks, way 863084179
    ("QADIRABAD", "Qadirabad", "Chenab", 32.321669, 73.685414, "Qadirabad"),  # Qadirabad Headworks, way 863088577
    ("TRIMMU", "Trimmu", "Chenab", 31.1448, 72.146, "Trimmu"),
    ("PANJNAD", "Panjnad", "Panjnad", 29.3464, 71.0202, "Panjnad"),
    ("GANDA_SINGH_WALA", "Ganda Singh Wala", "Sutlej", 30.993429, 74.545256, "Ganda Singh Wala"),
    ("SULEMANKI", "Sulemanki", "Sutlej", 30.3777, 73.8663, "Sulemanki"),
    ("ISLAM", "Islam", "Sutlej", 29.825603, 72.549093, "Islam"),  # Islam Headworks, way 695667968
]

# GloFAS forecasts keep using the 5 km grid cell they always read: moving a station onto its structure
# must not switch it to a neighbouring cell. These are the previous (FFD feed) coordinates.
GLOFAS_POINTS = {
    "TARBELA": (34.1059, 72.7338), "TAUNSA": (30.518528, 70.836721), "NOWSHERA": (34.015, 71.975),
    "MANGLA": (33.142, 73.645), "RASUL": (32.683, 73.517), "MARALA": (32.660583, 74.41125),
    "KHANKI": (32.4088, 73.9685), "QADIRABAD": (32.3209, 73.6851), "ISLAM": (29.8263, 72.5485),
}


def glofas_point(station_id: str, latitude: float, longitude: float) -> tuple[float, float]:
    return GLOFAS_POINTS.get(station_id, (latitude, longitude))


RIVER_CHAINS = {
    "Indus": ["TARBELA", "KALABAGH", "CHASHMA", "TAUNSA", "GUDDU", "SUKKUR", "KOTRI"],
    "Kabul": ["NOWSHERA"],
    "Jhelum": ["MANGLA", "RASUL"],
    "Ravi": ["JASSAR", "SHAHDARA", "BALLOKI", "SIDHNAI"],
    "Chenab": ["MARALA", "KHANKI", "QADIRABAD", "TRIMMU", "PANJNAD"],
    "Sutlej": ["GANDA_SINGH_WALA", "SULEMANKI", "ISLAM", "PANJNAD"],
}


def upstream_ids(station_id: str) -> list[str]:
    return list(dict.fromkeys(upstream for chain in RIVER_CHAINS.values() if station_id in chain
                              for upstream in chain[:chain.index(station_id)]))
