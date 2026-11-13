"""Create exploratory 7-30 day CRE forecasts using archived future weather."""
from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from train_poc import make_daily_features, read_config


HERE = Path(__file__).resolve().parent


def main() -> None:
    cfg = read_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--daily-csv", help="Merged daily table; defaults to the saved training copy")
    parser.add_argument("--forecast-csv", required=True, help="CSV columns: lead_day, rain_era5_mm, temperature_c for this issue date")
    parser.add_argument("--out", default="poc_forecast.csv")
    args = parser.parse_args()

    daily_path = Path(args.daily_csv) if args.daily_csv else HERE / cfg["data"]["daily_file"]
    daily = pd.read_csv(daily_path, parse_dates=[cfg["data"]["date_column"]]).set_index(cfg["data"]["date_column"]).sort_index()
    daily = daily[~daily.index.duplicated(keep="last")]
    issue = pd.Timestamp(args.issue_date)
    if issue not in daily.index:
        raise ValueError("Issue date is not present in the daily input table")
    features = make_daily_features(daily)
    if features.loc[issue].isna().all():
        raise ValueError("No usable historical input features exist at this issue date")

    fc = pd.read_csv(args.forecast_csv)
    required = {"lead_day", "rain_era5_mm", "temperature_c"}
    if not required.issubset(fc.columns):
        raise ValueError(f"Forecast CSV must include {sorted(required)}")
    fc = fc.set_index("lead_day")
    artifact_path = HERE / cfg["outputs"]["root"] / "final_train_through_2024" / "models.joblib"
    artifact = joblib.load(artifact_path)
    all_leads = artifact["leads"]
    rows = []
    for lead in all_leads:
        if lead not in fc.index:
            raise ValueError(f"Forecast CSV is missing lead_day {lead}")
        target_date = issue + pd.Timedelta(days=int(lead))
        row = features.loc[issue].to_dict()
        row.update({
            "lead_day": lead,
            "lead_scaled": lead / 30.0,
            "lead_sin": np.sin(2 * np.pi * lead / 24),
            "lead_cos": np.cos(2 * np.pi * lead / 24),
            # In training these fields were realized ERA5-Land with synthetic noise.
            # Supplying archived forecast values is an unvalidated domain change.
            "future_rain_at_lead_noisy_era5": float(fc.loc[lead, "rain_era5_mm"]),
            "future_temperature_at_lead_noisy_era5": float(fc.loc[lead, "temperature_c"]),
        })
        climate = artifact["climatology"][target_date.day_of_year]
        x_shared = pd.DataFrame([row])
        for horizon in all_leads:
            x_shared[f"is_lead_{horizon}"] = float(horizon == lead)
        x_shared = x_shared[artifact["shared_feature_columns"]]
        shared_residual = float(np.mean([m.predict(x_shared)[0] for m in artifact["models"]["shared_CRE"]]))
        # The separate estimator was fitted without the lead marker; align to its saved columns.
        separate_models = artifact["models"]["separate_CRE"][lead]
        expected = list(separate_models[0].regressor_.feature_names_in_)
        x_separate = pd.DataFrame([{k: row[k] for k in expected}])
        separate_residual = float(np.mean([m.predict(x_separate)[0] for m in separate_models]))
        rows.append({
            "issue_date": issue.date().isoformat(), "target_date": target_date.date().isoformat(), "lead_day": lead,
            "shared_CRE_q_cumecs": max(0.0, climate + shared_residual),
            "separate_CRE_q_cumecs": max(0.0, climate + separate_residual),
            "training_climatology_q_cumecs": climate,
            "warning": "POC only; trained with noisy realized reanalysis, not archived forecasts",
        })
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"Wrote exploratory {len(rows)} lead forecasts to {out}")


if __name__ == "__main__":
    main()
