from app.api.routes.predictive_station import build_payload


def test_station_forecast_payload_comes_from_saved_model_outputs():
    payload = build_payload()
    assert payload["model_name"] == "marala_station_gauge_forecast_v1"
    assert payload["deployment_eligible"] is False
    assert [item["horizon_days"] for item in payload["forecasts"]] == [1, 3, 7]
    assert [item["horizon_days"] for item in payload["skill"]] == [1, 3, 7]
    assert all(item["champion"]["inflow_cumecs"] > 0 for item in payload["forecasts"])
    assert payload["holdout"] and {row["horizon_days"] for row in payload["holdout"]} == {1, 3, 7}
    assert round(payload["thresholds_cumecs"]["Low"]) == 2832
    assert payload["history"][-1]["observed_at"] == payload["origin"]["observed_at"]
