"""Local correctness tests; synthetic tests do not establish accuracy."""
import sys
from pathlib import Path
MODEL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODEL_ROOT))
import _nhits.testing as local_tests


class ModelTests(local_tests.BasisTests):
    family = 'nhits'
