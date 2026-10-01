import numpy as np

from app.ml.train_real_model import _group_split, _metrics


def test_real_model_split_keeps_events_out_of_multiple_sets():
    groups = np.asarray([f"event_{index // 3}" for index in range(84)])
    train, validation, test, _ = _group_split(groups)
    train_groups = set(groups[train])
    validation_groups = set(groups[validation])
    test_groups = set(groups[test])
    assert train_groups.isdisjoint(validation_groups)
    assert train_groups.isdisjoint(test_groups)
    assert validation_groups.isdisjoint(test_groups)


def test_real_model_metrics_reward_correct_ranking():
    labels = np.asarray([0, 0, 1, 1], dtype=np.float32)
    probabilities = np.asarray([0.1, 0.2, 0.8, 0.9], dtype=np.float32)
    metrics = _metrics(labels, probabilities)
    assert metrics["roc_auc"] == 1.0
    assert metrics["f1_at_0_5"] == 1.0
