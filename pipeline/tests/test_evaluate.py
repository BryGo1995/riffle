import sys
sys.path.insert(0, "pipeline")
import numpy as np
import pytest
from plugins.ml.evaluate import evaluate_holdout, format_summary

CLASS_NAMES = ["Blown Out", "Poor", "Fair", "Good", "Excellent"]


def _perfect_inputs(n_per_class=10):
    """Return y_true and y_probas for perfect predictions."""
    n_classes = len(CLASS_NAMES)
    y_true = np.repeat(np.arange(n_classes), n_per_class)
    y_probas = np.zeros((len(y_true), n_classes))
    for i, label in enumerate(y_true):
        y_probas[i, label] = 1.0
    return y_true, y_probas


def test_evaluate_holdout_returns_expected_keys():
    y_true, y_probas = _perfect_inputs()
    metrics = evaluate_holdout(y_true, y_probas, CLASS_NAMES, training_samples=200)

    expected_scalar_keys = {
        "accuracy", "weighted_f1", "log_loss",
        "holdout_samples", "training_samples",
    }
    expected_matrix_keys = {"confusion_matrix", "label_distribution"}
    per_class_keys = set()
    for name in CLASS_NAMES:
        slug = name.lower().replace(" ", "_")
        per_class_keys |= {
            f"precision_{slug}", f"recall_{slug}", f"f1_{slug}",
        }

    all_expected = expected_scalar_keys | expected_matrix_keys | per_class_keys
    assert all_expected.issubset(metrics.keys())


def test_evaluate_holdout_perfect_predictions():
    y_true, y_probas = _perfect_inputs()
    metrics = evaluate_holdout(y_true, y_probas, CLASS_NAMES, training_samples=200)

    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["weighted_f1"] == pytest.approx(1.0)


def test_evaluate_holdout_per_class_f1():
    y_true, y_probas = _perfect_inputs()
    metrics = evaluate_holdout(y_true, y_probas, CLASS_NAMES, training_samples=200)

    for name in CLASS_NAMES:
        slug = name.lower().replace(" ", "_")
        assert metrics[f"f1_{slug}"] == pytest.approx(1.0), f"f1_{slug} should be 1.0"


def test_evaluate_holdout_confusion_matrix_shape():
    y_true, y_probas = _perfect_inputs()
    metrics = evaluate_holdout(y_true, y_probas, CLASS_NAMES, training_samples=200)

    cm = metrics["confusion_matrix"]
    assert len(cm) == 5
    assert all(len(row) == 5 for row in cm)


def test_evaluate_holdout_label_distribution():
    n_per_class = 10
    y_true, y_probas = _perfect_inputs(n_per_class=n_per_class)
    metrics = evaluate_holdout(y_true, y_probas, CLASS_NAMES, training_samples=200)

    dist = metrics["label_distribution"]
    assert "holdout" in dist
    for name in CLASS_NAMES:
        assert dist["holdout"][name] == n_per_class


def test_format_summary_returns_string():
    y_true, y_probas = _perfect_inputs()
    metrics = evaluate_holdout(y_true, y_probas, CLASS_NAMES, training_samples=200)
    summary = format_summary(metrics, CLASS_NAMES)

    assert isinstance(summary, str)
    assert "accuracy" in summary.lower()
    assert "weighted_f1" in summary.lower() or "weighted f1" in summary.lower()
