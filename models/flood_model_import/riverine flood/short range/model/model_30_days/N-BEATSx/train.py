"""Train or fine-tune this model using its local implementation."""
import sys
from pathlib import Path
MODEL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_ROOT))
from _nbeatsx.train import main

if __name__ == "__main__":
    main(MODEL_ROOT / "config.yaml")

