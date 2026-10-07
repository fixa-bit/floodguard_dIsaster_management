from datetime import datetime, timedelta

from app.models.model_forecast import ModelForecastPoint


def build_dummy_model_forecasts(issued_at: datetime) -> list[ModelForecastPoint]:
    """DB-ready simulation forecasts used until trained model outputs are available."""
    return [
        *_riverine(issued_at),
        *_flash(issued_at),
        *_urban(issued_at),
        *_seasonal(issued_at),
        *_upstream(issued_at),
    ]


def _riverine(issued_at: datetime) -> list[ModelForecastPoint]:
    return [
        *_series(
            "riverine",
            "trimmu",
            "Trimmu",
            issued_at,
            "cumecs",
            "xgboost_riverine_baseline_v1",
            [
                (0, 1680, 0.32, "Low"),
                (3, 1705, 0.33, "Low"),
                (6, 1765, 0.34, "Low"),
                (9, 1930, 0.38, "Medium"),
                (12, 2180, 0.42, "Medium"),
                (18, 2520, 0.49, "Medium"),
                (24, 2860, 0.55, "High"),
            ],
            {
                "simulation_source": "dummy_model_forecast_v3",
                "target_output": "predicted_discharge_cumecs",
                "feature_snapshot": {
                    "q_t_cumecs": 1680,
                    "q_t_minus_3h_cumecs": 1595,
                    "q_t_minus_6h_cumecs": 1510,
                    "q_t_minus_12h_cumecs": 1425,
                    "q_t_minus_24h_cumecs": 1320,
                    "rainfall_3h_mm": 18,
                    "rainfall_6h_mm": 34,
                    "rainfall_24h_mm": 72,
                    "upstream_q_cumecs": 2120,
                    "reservoir_release_cumecs": 640,
                    "soil_moisture_percent": 78,
                    "forecast_rainfall_mm": 42,
                },
            },
        ),
        *_series(
            "riverine",
            "balloki",
            "Balloki",
            issued_at,
            "cumecs",
            "xgboost_riverine_baseline_v1",
            [
                (0, 940, 0.22, "Low"),
                (6, 970, 0.23, "Low"),
                (12, 1045, 0.25, "Low"),
                (18, 1190, 0.28, "Low"),
                (24, 1360, 0.32, "Medium"),
                (30, 1585, 0.38, "Medium"),
                (36, 1810, 0.43, "Medium"),
                (42, 1995, 0.47, "Medium"),
                (48, 2160, 0.51, "High"),
            ],
            {
                "simulation_source": "dummy_model_forecast_v3",
                "target_output": "predicted_discharge_cumecs",
                "feature_snapshot": {
                    "q_t_cumecs": 940,
                    "q_t_minus_3h_cumecs": 900,
                    "q_t_minus_6h_cumecs": 865,
                    "q_t_minus_12h_cumecs": 810,
                    "q_t_minus_24h_cumecs": 760,
                    "rainfall_3h_mm": 12,
                    "rainfall_6h_mm": 28,
                    "rainfall_24h_mm": 61,
                    "upstream_q_cumecs": 1380,
                    "reservoir_release_cumecs": 520,
                    "soil_moisture_percent": 72,
                    "forecast_rainfall_mm": 38,
                },
            },
        ),
    ]


def _flash(issued_at: datetime) -> list[ModelForecastPoint]:
    targets = [
        ("rwp_streams", "Rawalpindi streams", [(0, 18, 0.18, "Low"), (1, 46, 0.46, "High"), (2, 64, 0.64, "High"), (3, 72, 0.72, "Extreme"), (4, 70, 0.70, "Extreme"), (5, 64, 0.64, "High"), (6, 58, 0.58, "High")]),
        ("isb_streams", "Islamabad streams", [(0, 12, 0.12, "Low"), (1, 20, 0.20, "Moderate"), (2, 34, 0.34, "Moderate"), (3, 49, 0.49, "High"), (4, 52, 0.52, "High"), (5, 47, 0.47, "High"), (6, 41, 0.41, "Moderate")]),
        ("hill_torrents", "Hill torrents", [(0, 26, 0.26, "Moderate"), (1, 69, 0.69, "High"), (2, 83, 0.83, "Extreme"), (3, 88, 0.88, "Extreme"), (4, 82, 0.82, "Extreme"), (5, 73, 0.73, "Extreme"), (6, 63, 0.63, "High")]),
    ]
    return [
        point
        for target_id, target_name, values in targets
        for point in _series(
            "flash",
            target_id,
            target_name,
            issued_at,
            "probability_percent",
            "lightgbm_flash_flood_baseline_v1",
            values,
            {
                "simulation_source": "dummy_model_forecast_v3",
                "target_output": "flash_flood_probability",
                "feature_snapshot": {
                    "rainfall_15min_mm": 9,
                    "rainfall_1h_mm": 28,
                    "rainfall_3h_mm": 64,
                    "rainfall_6h_mm": 98,
                    "forecast_rainfall_6h_mm": 44,
                    "soil_moisture_percent": 82,
                    "slope_degrees": 16,
                    "elevation_m": 610,
                    "drainage_density_km_per_km2": 2.7,
                    "land_cover_code": 4,
                    "catchment_area_km2": 72,
                    "distance_to_stream_km": 0.35,
                },
            },
        )
    ]


def _urban(issued_at: datetime) -> list[ModelForecastPoint]:
    targets = [
        ("isb_grid", "Islamabad grid cells", [(0, 21, 0.21, "Low"), (1, 29, 0.29, "Moderate"), (2, 37, 0.37, "Moderate"), (3, 44, 0.44, "Moderate"), (4, 50, 0.50, "High"), (5, 54, 0.54, "High"), (6, 57, 0.57, "High")]),
        ("rwp_grid", "Rawalpindi grid cells", [(0, 28, 0.28, "Moderate"), (1, 52, 0.52, "High"), (2, 67, 0.67, "High"), (3, 75, 0.75, "Extremely high"), (4, 79, 0.79, "Extremely high"), (5, 80, 0.80, "Extremely high"), (6, 78, 0.78, "Extremely high")]),
        ("lahore_grid", "Lahore grid cells", [(0, 19, 0.19, "Low"), (1, 27, 0.27, "Low"), (2, 39, 0.39, "Moderate"), (3, 51, 0.51, "High"), (4, 59, 0.59, "High"), (5, 64, 0.64, "High"), (6, 66, 0.66, "High")]),
    ]
    return [
        point
        for target_id, target_name, values in targets
        for point in _series(
            "urban",
            target_id,
            target_name,
            issued_at,
            "susceptibility_percent",
            "lightgbm_urban_flood_susceptibility_v1",
            values,
            {
                "simulation_source": "dummy_model_forecast_v3",
                "target_output": "urban_flood_susceptibility",
                "feature_snapshot": {
                    "rainfall_1h_mm": 31,
                    "rainfall_3h_mm": 76,
                    "rainfall_6h_mm": 118,
                    "forecast_rainfall_6h_mm": 52,
                    "dem_elevation_m": 225,
                    "slope_degrees": 1.8,
                    "drainage_capacity_mm_per_h": 24,
                    "impervious_surface_percent": 84,
                    "land_use_code": 4,
                    "previous_waterlogging_reports_30d": 7,
                    "hydraulic_depth_model_required": True,
                },
            },
        )
    ]


def _seasonal(issued_at: datetime) -> list[ModelForecastPoint]:
    return _series(
        "seasonal",
        "national_basin",
        "National basin",
        issued_at,
        "risk_percent",
        "seasonal_basin_baseline_v1",
        [(168, 24, 0.24, "Low"), (336, 27, 0.27, "Low"), (504, 31, 0.31, "Moderate"), (720, 36, 0.36, "Moderate"), (1008, 43, 0.43, "Moderate"), (1440, 49, 0.49, "Moderate"), (1800, 54, 0.54, "High"), (2160, 58, 0.58, "High")],
        {
            "simulation_source": "dummy_model_forecast_v3",
            "target_output": "basin_risk_probability",
            "feature_snapshot": {
                "basin_saturation_index": 0.54,
                "seasonal_rainfall_anomaly": 0.18,
                "snowmelt_proxy": 0.11,
                "current_national_risk_baseline": 0.34,
            },
        },
    )


def _upstream(issued_at: datetime) -> list[ModelForecastPoint]:
    return _series(
        "upstream",
        "downstream_reaches",
        "Downstream reaches",
        issued_at,
        "anomaly_percent",
        "upstream_anomaly_baseline_v1",
        [(0, 14, 0.14, "Normal"), (3, 14, 0.14, "Normal"), (6, 16, 0.16, "Normal"), (9, 22, 0.22, "Watch"), (12, 31, 0.31, "Watch"), (18, 48, 0.48, "Watch"), (24, 64, 0.64, "High"), (36, 70, 0.70, "High"), (48, 73, 0.73, "High")],
        {
            "simulation_source": "dummy_model_forecast_v3",
            "target_output": "upstream_flow_anomaly",
            "feature_snapshot": {
                "local_rain_signal": "low",
                "positive_discharge_anomaly_cumecs_per_day": 420,
                "upstream_q_ratio": 1.28,
                "transboundary_watch_flag": True,
            },
        },
    )


def _series(
    model_case: str,
    target_id: str,
    target_name: str,
    issued_at: datetime,
    value_unit: str,
    model_name: str,
    values: list[tuple[int, float, float, str]],
    metadata: dict,
) -> list[ModelForecastPoint]:
    return [
        ModelForecastPoint(
            model_case=model_case,
            target_id=target_id,
            target_name=target_name,
            issued_at=issued_at,
            valid_at=issued_at + timedelta(hours=horizon),
            horizon_hours=horizon,
            value=value,
            value_unit=value_unit,
            probability=probability,
            risk_class=risk_class,
            model_name=model_name,
            point_metadata={**metadata, "model_status": "dummy_until_trained_model_ready"},
        )
        for horizon, value, probability, risk_class in values
    ]
