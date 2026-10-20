"""Read-only API for the saved Marala monthly research dataset and artifacts."""
import csv
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/predictive/marala-monthly", tags=["Predictive models"])
ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "app/ml/marala_pilot/data"
ARTIFACT_DIR = ROOT / "app/ml/marala_pilot/artifacts/seasonal"
DATASET = DATA_DIR / "seasonal_monthly.csv"


def _read_json(path: Path):
    if not path.is_file():
        raise HTTPException(status_code=503, detail=f"Model artifact is missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("")
def get_marala_monthly():
    if not DATASET.is_file():
        raise HTTPException(status_code=503, detail="Monthly Marala dataset is not available")
    with DATASET.open(newline="", encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    numeric = ("flow_mean_cumecs", "flow_max_daily_mean_cumecs", "rainfall_mm",
               "temperature_c", "snowfall_cm")
    for row in records:
        for field in numeric:
            row[field] = float(row[field])
    card = _read_json(ARTIFACT_DIR / "model-card.json")
    hindcast = _read_json(ARTIFACT_DIR / "example_outlook.json")
    provider = _read_json(ARTIFACT_DIR / "current_provider_outlook.json")
    sources = _read_json(DATA_DIR / "seasonal-sources.json")
    leads = {}
    for horizon, result in card["models"].items():
        model = result["model"]
        leads[horizon] = {
            "selected_candidate": result["validation_selected_candidate"],
            "model_type": model["model_type"],
            "test": result["metrics"]["test"]["selected_model"],
            "ridge_vs_xgboost_test": result["metrics"]["test"].get("candidate_comparison", {}),
        }
    return {
        "station_id": card["station_id"], "river": card["river"],
        "target": card["target"], "input_period": card["input_period"],
        "monthly_records": card["monthly_records"], "features": card["features"],
        "trained_at": card["trained_at"], "status": card["status"],
        "sources": {"documentation": sources["documentation"],
                    "attribution": sources["attribution"],
                    "weather_definition": sources["weather_definition"]},
        "leads": leads, "dataset": records,
        "historical_model_hindcast": hindcast,
        "current_provider_outlook": provider,
        "recent_history": _read_json(ARTIFACT_DIR / "observed_monthly_history.json"),
    }


@router.get("/dataset.csv", include_in_schema=True)
def download_marala_dataset():
    if not DATASET.is_file():
        raise HTTPException(status_code=503, detail="Monthly Marala dataset is not available")
    return FileResponse(DATASET, media_type="text/csv", filename="marala-monthly-dataset.csv")
