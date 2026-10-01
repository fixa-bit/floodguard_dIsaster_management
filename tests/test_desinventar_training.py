import numpy as np

from app.ml.desinventar_data import _canonical_districts, _map_district
from app.ml.train_desinventar_model import _best_threshold, _threshold_metrics
from app.ml.train_pilot_model import PILOT_BLOCKS


def test_historical_district_aliases_are_explicit():
    canonical = _canonical_districts()
    assert _map_district("Batagram", canonical) == "Battagram"
    assert _map_district("Muzaffarabad", canonical) == "Azad Kashmir"
    assert _map_district("Islamabad", canonical) == "Islamabad Capital Territory"
    assert _map_district("Unknown district", canonical) is None


def test_threshold_is_selected_from_validation_predictions():
    labels = np.asarray([0, 0, 0, 1, 1], dtype=np.float32)
    probabilities = np.asarray([0.1, 0.2, 0.4, 0.45, 0.8], dtype=np.float32)
    threshold = _best_threshold(labels, probabilities)
    metrics = _threshold_metrics(labels, probabilities, threshold)
    assert 0.4 <= threshold <= 0.46
    assert metrics["f1"] == 1.0


def test_partial_coverage_is_contiguous_lower_indus_blocks():
    assert PILOT_BLOCKS == {
        "N24_E66", "N24_E68", "N26_E66", "N26_E68", "N28_E66", "N28_E68",
    }
