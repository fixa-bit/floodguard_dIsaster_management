"""Evaluate the saved local model on observed targets."""
import sys
from pathlib import Path
MODEL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_ROOT))
from _nhits.evaluate import main

if __name__ == "__main__":
    main()
