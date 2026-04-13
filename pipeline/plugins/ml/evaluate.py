"""Holdout evaluation, MLflow logging, and run comparison for Riffle."""

import csv
import os
import tempfile
from typing import List

import numpy as np
import mlflow
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix as sk_confusion_matrix,
    f1_score,
    log_loss,
)


def evaluate_holdout(
    y_true: np.ndarray,
    y_probas: np.ndarray,
    class_names: List[str],
    training_samples: int,
) -> dict:
    """Compute holdout metrics for a multi-class classifier.

    Args:
        y_true: Array of integer labels (0-4).
        y_probas: Array of shape (n_samples, n_classes) with predicted probabilities.
        class_names: List of human-readable class names.
        training_samples: Number of training samples used.

    Returns:
        Dict with scalar metrics, confusion matrix, label distribution, and
        per-class precision/recall/f1.

    Raises:
        ValueError: If y_probas is not 2-D or its column count does not match
            len(class_names).
    """
    if y_probas.ndim != 2 or y_probas.shape[1] != len(class_names):
        raise ValueError(
            f"y_probas must be 2-D with {len(class_names)} columns, "
            f"got shape {y_probas.shape}"
        )

    y_pred = np.argmax(y_probas, axis=1)

    acc = float(accuracy_score(y_true, y_pred))
    wf1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
    ll = float(log_loss(y_true, y_probas, labels=np.arange(len(class_names))))

    cm = sk_confusion_matrix(y_true, y_pred, labels=np.arange(len(class_names)))

    report = classification_report(
        y_true, y_pred,
        labels=np.arange(len(class_names)),
        target_names=class_names,
        output_dict=True,
        zero_division=0,
    )

    metrics: dict = {
        "accuracy": acc,
        "weighted_f1": wf1,
        "log_loss": ll,
        "holdout_samples": len(y_true),
        "training_samples": training_samples,
        "confusion_matrix": cm.tolist(),
    }

    # Per-class metrics
    for name in class_names:
        slug = name.lower().replace(" ", "_")
        entry = report[name]
        metrics[f"precision_{slug}"] = float(entry["precision"])
        metrics[f"recall_{slug}"] = float(entry["recall"])
        metrics[f"f1_{slug}"] = float(entry["f1-score"])

    # Label distribution
    holdout_dist = {}
    unique, counts = np.unique(y_true, return_counts=True)
    count_map = dict(zip(unique, counts))
    for i, name in enumerate(class_names):
        holdout_dist[name] = int(count_map.get(i, 0))
    metrics["label_distribution"] = {"holdout": holdout_dist}

    return metrics


def log_evaluation_to_mlflow(metrics: dict, class_names: List[str]) -> None:
    """Log evaluation metrics and artifacts to the active MLflow run.

    Scalar metrics are logged with an ``eval_`` prefix. The confusion matrix
    and label distribution are written as CSV artifacts under the
    ``evaluation`` artifact path.

    Args:
        metrics: Dict returned by :func:`evaluate_holdout`.
        class_names: List of human-readable class names.
    """
    skip_keys = {"confusion_matrix", "label_distribution"}
    for key, value in metrics.items():
        if key in skip_keys:
            continue
        mlflow.log_metric(f"eval_{key}", value)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Confusion matrix CSV
        cm_path = os.path.join(tmpdir, "confusion_matrix.csv")
        with open(cm_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([""] + class_names)
            for name, row in zip(class_names, metrics["confusion_matrix"]):
                writer.writerow([name] + row)
        mlflow.log_artifact(cm_path, artifact_path="evaluation")

        # Label distribution CSV
        dist_path = os.path.join(tmpdir, "label_distribution.csv")
        with open(dist_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["class", "holdout"])
            holdout = metrics["label_distribution"]["holdout"]
            for name in class_names:
                writer.writerow([name, holdout.get(name, 0)])
        mlflow.log_artifact(dist_path, artifact_path="evaluation")


def format_summary(metrics: dict, class_names: List[str]) -> str:
    """Return a human-readable summary of evaluation metrics.

    Args:
        metrics: Dict returned by :func:`evaluate_holdout`.
        class_names: List of human-readable class names.

    Returns:
        Multi-line string with scalar metrics and per-class F1.
    """
    lines = [
        f"Evaluation Summary  (holdout={metrics['holdout_samples']}, training={metrics['training_samples']})",
        "==================",
        f"  accuracy:    {metrics['accuracy']:.4f}",
        f"  weighted_f1: {metrics['weighted_f1']:.4f}",
        f"  log_loss:    {metrics['log_loss']:.4f}",
        "",
        "Per-class F1:",
    ]
    for name in class_names:
        slug = name.lower().replace(" ", "_")
        lines.append(f"  {name:12s}  {metrics[f'f1_{slug}']:.4f}")
    return "\n".join(lines)


def compare_runs(run_id_a: str, run_id_b: str) -> str:
    """Compare eval metrics between two MLflow runs.

    Args:
        run_id_a: MLflow run ID for the baseline run.
        run_id_b: MLflow run ID for the candidate run.

    Returns:
        Formatted comparison table with deltas and a recommendation
        based on weighted F1.
    """
    client = mlflow.tracking.MlflowClient()
    run_a = client.get_run(run_id_a)
    run_b = client.get_run(run_id_b)

    metrics_a = {k: v for k, v in run_a.data.metrics.items() if k.startswith("eval_")}
    metrics_b = {k: v for k, v in run_b.data.metrics.items() if k.startswith("eval_")}

    if not metrics_a:
        return f"Run A ({run_id_a[:8]}) has no evaluation metrics."
    if not metrics_b:
        return f"Run B ({run_id_b[:8]}) has no evaluation metrics."

    all_keys = sorted(set(metrics_a.keys()) | set(metrics_b.keys()))

    lines = [
        f"{'Metric':<30s} {'Run A':>10s} {'Run B':>10s} {'Delta':>10s}",
        "-" * 62,
    ]
    for key in all_keys:
        val_a = metrics_a.get(key, float("nan"))
        val_b = metrics_b.get(key, float("nan"))
        delta = val_b - val_a
        lines.append(f"{key:<30s} {val_a:10.4f} {val_b:10.4f} {delta:+10.4f}")

    wf1_a = metrics_a.get("eval_weighted_f1", float("nan"))
    wf1_b = metrics_b.get("eval_weighted_f1", float("nan"))
    if np.isnan(wf1_a) or np.isnan(wf1_b):
        rec = "Cannot compare: eval_weighted_f1 missing from one or both runs."
    elif wf1_b > wf1_a:
        rec = "Run B is better (higher weighted F1)."
    elif wf1_a > wf1_b:
        rec = "Run A is better (higher weighted F1)."
    else:
        rec = "Both runs have equal weighted F1."

    lines.append("")
    lines.append(f"Recommendation: {rec}")
    return "\n".join(lines)
