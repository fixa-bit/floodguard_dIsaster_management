"""Package the saved Marala monthly dataset for the dashboard's offline fallback."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.api.routes.predictive_monthly import DATASET, get_marala_monthly

PUBLIC_DATA = ROOT / "frontend/public/data"


def main():
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    payload = get_marala_monthly()
    (PUBLIC_DATA / "marala-monthly.json").write_text(
        json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (PUBLIC_DATA / "marala-monthly-dataset.csv").write_bytes(DATASET.read_bytes())
    print(f"Packaged {len(payload['dataset'])} Marala monthly records")


if __name__ == "__main__":
    main()
