"""Local observed-only data-window adapter."""
import sys
from pathlib import Path
MODEL_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(MODEL_ROOT))
from _nbeatsx.data import BasisDataset

