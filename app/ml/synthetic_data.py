import numpy as np


FEATURE_NAMES = [
    "rainfall_last_1h",
    "rainfall_last_6h",
    "rainfall_last_24h",
    "forecast_rainfall_24h",
    "river_level",
    "river_level_relative_to_warning",
    "river_rise_rate",
    "river_discharge",
    "river_discharge_change",
    "soil_moisture",
]


def generate_synthetic_training_data(rows: int = 6000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate development-only synthetic features and synthetic probability labels."""
    rng = np.random.default_rng(seed)
    rainfall_1h = rng.uniform(0, 60, rows)
    rainfall_6h = np.clip(rainfall_1h * rng.uniform(1, 4, rows) + rng.normal(5, 12, rows), 0, 180)
    rainfall_24h = np.clip(rainfall_6h * rng.uniform(1, 2.2, rows) + rng.normal(8, 20, rows), 0, 300)
    forecast_24h = rng.uniform(0, 160, rows)
    river_level = rng.uniform(2.0, 8.5, rows)
    warning_level = rng.uniform(5.0, 6.5, rows)
    river_ratio = river_level / warning_level
    rise_rate = rng.uniform(-0.12, 0.9, rows)
    discharge = np.clip((river_level / 7) ** 3 * 3200 + rng.normal(0, 180, rows), 0, 6000)
    discharge_change = np.clip(rise_rate * 1200 + rng.normal(0, 120, rows), -1000, 1800)
    soil_moisture = rng.uniform(20, 100, rows)
    features = np.column_stack(
        [
            rainfall_1h,
            rainfall_6h,
            rainfall_24h,
            forecast_24h,
            river_level,
            river_ratio,
            rise_rate,
            discharge,
            discharge_change,
            soil_moisture,
        ]
    )
    probability = (
        np.minimum(rainfall_24h / 220, 1) * 0.24
        + np.minimum(forecast_24h / 140, 1) * 0.16
        + np.minimum(river_ratio, 1.4) / 1.4 * 0.22
        + np.minimum(river_level / 7.0, 1.25) / 1.25 * 0.18
        + np.clip(rise_rate / 0.75, 0, 1) * 0.12
        + np.minimum(soil_moisture / 100, 1) * 0.08
    )
    interaction = np.where((river_ratio >= 1) & (rainfall_24h >= 100), 0.04, 0)
    labels = np.clip(probability + interaction + rng.normal(0, 0.015, rows), 0, 1)
    no_level_rows = rng.random(rows) < 0.35
    features[no_level_rows, 4:7] = np.nan
    return features.astype(np.float32), labels.astype(np.float32)
