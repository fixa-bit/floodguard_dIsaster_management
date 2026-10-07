# Reference coordinates from FFD's public river-state station feed.
STATIONS = [
    ("TARBELA", "Tarbela", "Indus", 34.1059, 72.7338, "Tarbela Dam"),
    ("KALABAGH", "Kalabagh", "Indus", 32.9187, 71.5219, "Kala Bagh"),
    ("CHASHMA", "Chashma", "Indus", 32.4359, 71.3794, "Chashma"),
    ("TAUNSA", "Taunsa", "Indus", 30.518528, 70.836721, "Taunsa"),
    ("GUDDU", "Guddu", "Indus", 28.4201, 69.7114, "Guddu"),
    ("SUKKUR", "Sukkur", "Indus", 27.679, 68.8462, "Sukkur"),
    ("KOTRI", "Kotri", "Indus", 25.4428, 68.3151, "Kotri"),
    ("JASSAR", "Jassar", "Ravi", 32.049654, 74.992018, "Jassar"),
    ("SHAHDARA", "Shahdara", "Ravi", 31.6085, 74.2956, "Shahdara"),
    ("BALLOKI", "Balloki", "Ravi", 31.2222, 73.8596, "Balloki"),
    ("SIDHNAI", "Sidhnai", "Ravi", 30.5723, 72.1582, "Sidhnai"),
    ("MARALA", "Marala", "Chenab", 32.660583, 74.41125, "Marala"),
    ("KHANKI", "Khanki", "Chenab", 32.4088, 73.9685, "Khanki"),
    ("QADIRABAD", "Qadirabad", "Chenab", 32.3209, 73.6851, "Qadirabad"),
    ("TRIMMU", "Trimmu", "Chenab", 31.1448, 72.146, "Trimmu"),
    ("PANJNAD", "Panjnad", "Panjnad", 29.3464, 71.0202, "Panjnad"),
    ("GANDA_SINGH_WALA", "Ganda Singh Wala", "Sutlej", 30.993429, 74.545256, "Ganda Singh Wala"),
    ("SULEMANKI", "Sulemanki", "Sutlej", 30.3777, 73.8663, "Sulemanki"),
    ("ISLAM", "Islam", "Sutlej", 29.8263, 72.5485, "Islam"),
]

RIVER_CHAINS = {
    "Indus": ["TARBELA", "KALABAGH", "CHASHMA", "TAUNSA", "GUDDU", "SUKKUR", "KOTRI"],
    "Ravi": ["JASSAR", "SHAHDARA", "BALLOKI", "SIDHNAI"],
    "Chenab": ["MARALA", "KHANKI", "QADIRABAD", "TRIMMU", "PANJNAD"],
    "Sutlej": ["GANDA_SINGH_WALA", "SULEMANKI", "ISLAM", "PANJNAD"],
}


def upstream_ids(station_id: str) -> list[str]:
    return list(dict.fromkeys(upstream for chain in RIVER_CHAINS.values() if station_id in chain
                              for upstream in chain[:chain.index(station_id)]))
