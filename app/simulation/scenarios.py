from app.core.enums import RiverStatus, Scenario


SCENARIO_SEQUENCE = [
    Scenario.NORMAL,
    Scenario.HEAVY_RAIN,
    Scenario.DEVELOPING_FLOOD,
    Scenario.CRITICAL_FLOOD,
    Scenario.CONFIRMED_FLOOD,
]

SCENARIOS = {
    Scenario.NORMAL: {
        "weather": (4, 2, 6, 9, 4, 8, 29, 55, 35),
        "river": (3.0, 2.8, 5.5, 7.0, 0.02, 580, RiverStatus.NORMAL),
    },
    Scenario.HEAVY_RAIN: {
        "weather": (58, 22, 66, 82, 40, 70, 26, 78, 68),
        "river": (4.7, 2.8, 5.5, 7.0, 0.18, 1100, RiverStatus.RISING),
    },
    Scenario.DEVELOPING_FLOOD: {
        "weather": (96, 34, 118, 126, 62, 102, 24, 86, 84),
        "river": (6.3, 2.8, 5.5, 7.0, 0.42, 2100, RiverStatus.WARNING),
    },
    Scenario.CRITICAL_FLOOD: {
        "weather": (125, 48, 152, 210, 78, 130, 23, 92, 95),
        "river": (7.6, 2.8, 5.5, 7.0, 0.7, 3300, RiverStatus.DANGER),
    },
    Scenario.CONFIRMED_FLOOD: {
        "weather": (118, 40, 144, 205, 65, 115, 23, 93, 96),
        "river": (7.8, 2.8, 5.5, 7.0, 0.62, 3450, RiverStatus.DANGER),
    },
    Scenario.FALSE_ALARM: {
        "weather": (22, 8, 34, 58, 12, 22, 27, 70, 52),
        "river": (4.0, 2.8, 5.5, 7.0, 0.01, 760, RiverStatus.NORMAL),
    },
}
