"""Local model architecture and factory."""
import sys
from pathlib import Path
MODEL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_ROOT))
from _nhits.model import BasisForecaster, build_model
