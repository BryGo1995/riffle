# Model Evaluation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add repeatable model evaluation with rolling 60-day holdout, automatic MLflow logging on every retrain, and a CLI comparison script for A/B testing.

**Architecture:** A shared `evaluate.py` module provides holdout evaluation and MLflow logging. The training functions in `train.py` accept an optional holdout DataFrame — when provided, they evaluate after training and log metrics. The training flows split data by date before calling train. A standalone `compare_runs.py` script reads metrics from MLflow for any two runs.

**Tech Stack:** XGBoost, MLflow, scikit-learn (classification_report, confusion_matrix, log_loss), pandas

---

### Task 1: Create evaluation module with tests

**Files:**
- Create: `pipeline/plugins/ml/evaluate.py`
- Create: `pipeline/tests/test_evaluate.py`

- [ ] **Step 1: Write the test file**

```python
# pipeline/tests/test_evaluate.py
import sys
sys.path.insert(0, "pipeline")
import numpy as np
import pytest
from plugins.ml.evaluate import evaluate_holdout, format_summary

# 5-class problem: 20 samples, perfect predictions
CLASSES = ["Blown Out", "Poor", "Fair", "Good", "Excellent"]
LABEL_TO_INT = {c: i for i, c in enumerate(CLASSES)}


def _make_perfect_probas(y_true, n_classes=5):
    """One-hot probability matrix where the model is 100% correct."""
    probas = np.zeros((len(y_true), n_classes))
    for i, label in enumerate(y_true):
        probas[i, label] = 1.0
    return probas


def test_evaluate_holdout_returns_expected_keys():
    y = np.array([0, 1, 2, 3, 4] * 4)
    probas = _make_perfect_probas(y)
    metrics = evaluate_holdout(y, probas, CLASSES, training_samples=100)
    assert "accuracy" in metrics
    assert "weighted_f1" in metrics
    assert "log_loss" in metrics
    assert "holdout_samples" in metrics
    assert "training_samples" in metrics
    assert "confusion_matrix" in metrics
    assert "label_distribution" in metrics


def test_evaluate_holdout_perfect_predictions():
    y = np.array([0, 1, 2, 3, 4] * 4)
    probas = _make_perfect_probas(y)
    metrics = evaluate_holdout(y, probas, CLASSES, training_samples=100)
    assert metrics["accuracy"] == 1.0
    assert metrics["weighted_f1"] == 1.0
    assert metrics["holdout_samples"] == 20


def test_evaluate_holdout_per_class_f1():
    y = np.array([0, 1, 2, 3, 4] * 4)
    probas = _make_perfect_probas(y)
    metrics = evaluate_holdout(y, probas, CLASSES, training_samples=100)
    for cls in CLASSES:
        safe = cls.lower().replace(" ", "_")
        assert metrics[f"f1_{safe}"] == 1.0
        assert metrics[f"precision_{safe}"] == 1.0
        assert metrics[f"recall_{safe}"] == 1.0


def test_evaluate_holdout_confusion_matrix_shape():
    y = np.array([0, 1, 2, 3, 4] * 4)
    probas = _make_perfect_probas(y)
    metrics = evaluate_holdout(y, probas, CLASSES, training_samples=100)
    cm = metrics["confusion_matrix"]
    assert len(cm) == 5
    assert all(len(row) == 5 for row in cm)


def test_evaluate_holdout_label_distribution():
    y = np.array([0, 0, 1, 1, 2])
    probas = _make_perfect_probas(y)
    metrics = evaluate_holdout(y, probas, CLASSES, training_samples=50)
    dist = metrics["label_distribution"]["holdout"]
    assert dist["Blown Out"] == 2
    assert dist["Poor"] == 2
    assert dist["Fair"] == 1


def test_format_summary_returns_string():
    y = np.array([0, 1, 2, 3, 4] * 4)
    probas = _make_perfect_probas(y)
    metrics = evaluate_holdout(y, probas, CLASSES, training_samples=100)
    summary = format_summary(metrics, CLASSES)
    assert isinstance(summary, str)
    assert "accuracy" in summary.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest pipeline/tests/test_evaluate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins.ml.evaluate'`

- [ ] **Step 3: Implement evaluate.py**

```python
# pipeline/plugins/ml/evaluate.py
"""Model evaluation utilities for Riffle.

Provides holdout evaluation, MLflow metric logging, and run comparison.
Used by the training flows (automatic) and compare_runs.py (manual).
"""

import csv
import io
import tempfile
from collections import Counter
from typing import Dict, List

import mlflow
import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
)


def evaluate_holdout(
    y_true: np.ndarray,
    y_probas: np.ndarray,
    class_names: List[str],
    training_samples: int,
) -> Dict:
    """Evaluate model on holdout set.

    Args:
        y_true: integer labels (0-4) for holdout samples.
        y_probas: predicted probability matrix (n_samples x n_classes).
        class_names: ordered list of class names matching label indices.
        training_samples: number of samples used for training (logged as context).

    Returns:
        Dict with all evaluation metrics, confusion matrix, and label distribution.
    """
    y_pred = np.argmax(y_probas, axis=1)

    report = classification_report(
        y_true, y_pred, target_names=class_names, output_dict=True, zero_division=0,
    )

    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "weighted_f1": f1_score(y_true, y_pred, average="weighted", zero_division=0),
        "log_loss": log_loss(y_true, y_probas, labels=list(range(len(class_names)))),
        "holdout_samples": len(y_true),
        "training_samples": training_samples,
    }

    # Per-class precision, recall, F1
    for cls in class_names:
        safe = cls.lower().replace(" ", "_")
        cls_metrics = report.get(cls, {})
        metrics[f"precision_{safe}"] = cls_metrics.get("precision", 0.0)
        metrics[f"recall_{safe}"] = cls_metrics.get("recall", 0.0)
        metrics[f"f1_{safe}"] = cls_metrics.get("f1-score", 0.0)

    # Confusion matrix as list of lists
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(class_names))))
    metrics["confusion_matrix"] = cm.tolist()

    # Label distribution
    holdout_counts = Counter(int(v) for v in y_true)
    metrics["label_distribution"] = {
        "holdout": {class_names[i]: holdout_counts.get(i, 0) for i in range(len(class_names))},
    }

    return metrics


def log_evaluation_to_mlflow(metrics: Dict, class_names: List[str]) -> None:
    """Log evaluation metrics and artifacts to the active MLflow run."""
    # Scalar metrics
    for key in ["accuracy", "weighted_f1", "log_loss", "holdout_samples", "training_samples"]:
        mlflow.log_metric(f"eval_{key}", metrics[key])

    for cls in class_names:
        safe = cls.lower().replace(" ", "_")
        for metric_type in ["precision", "recall", "f1"]:
            key = f"{metric_type}_{safe}"
            mlflow.log_metric(f"eval_{key}", metrics[key])

    # Confusion matrix CSV artifact
    cm = metrics["confusion_matrix"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["actual \\ predicted"] + class_names)
    for i, row in enumerate(cm):
        writer.writerow([class_names[i]] + row)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(buf.getvalue())
        mlflow.log_artifact(f.name, artifact_path="evaluation")

    # Label distribution CSV artifact
    dist = metrics["label_distribution"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["class", "holdout_count"])
    for cls in class_names:
        writer.writerow([cls, dist["holdout"].get(cls, 0)])

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(buf.getvalue())
        mlflow.log_artifact(f.name, artifact_path="evaluation")


def format_summary(metrics: Dict, class_names: List[str]) -> str:
    """Format a human-readable evaluation summary for log output."""
    lines = [
        f"Holdout evaluation ({metrics['holdout_samples']} samples, "
        f"{metrics['training_samples']} training):",
        f"  accuracy={metrics['accuracy']:.3f}  "
        f"weighted_f1={metrics['weighted_f1']:.3f}  "
        f"log_loss={metrics['log_loss']:.3f}",
    ]
    parts = []
    for cls in class_names:
        safe = cls.lower().replace(" ", "_")
        parts.append(f"{cls}: f1={metrics[f'f1_{safe}']:.2f}")
    lines.append("  " + "  ".join(parts))
    return "\n".join(lines)


def compare_runs(run_id_a: str, run_id_b: str) -> str:
    """Fetch metrics from MLflow for two runs and return a comparison report."""
    client = mlflow.tracking.MlflowClient()
    run_a = client.get_run(run_id_a)
    run_b = client.get_run(run_id_b)

    metrics_a = run_a.data.metrics
    metrics_b = run_b.data.metrics

    # Collect all eval_ metrics
    eval_keys = sorted(k for k in metrics_a if k.startswith("eval_"))
    if not eval_keys:
        return f"Run A ({run_id_a[:8]}) has no evaluation metrics. Was it trained with holdout?"

    lines = [
        f"Comparison: Run A ({run_id_a[:8]}) vs Run B ({run_id_b[:8]})",
        "",
        f"{'Metric':<30} {'Run A':>10} {'Run B':>10} {'Delta':>10}",
        "-" * 62,
    ]

    for key in eval_keys:
        val_a = metrics_a.get(key, 0.0)
        val_b = metrics_b.get(key, 0.0)
        delta = val_b - val_a
        sign = "+" if delta >= 0 else ""
        lines.append(f"{key:<30} {val_a:>10.4f} {val_b:>10.4f} {sign}{delta:>9.4f}")

    # Recommendation based on weighted F1
    f1_a = metrics_a.get("eval_weighted_f1", 0.0)
    f1_b = metrics_b.get("eval_weighted_f1", 0.0)
    delta = f1_b - f1_a
    lines.append("")
    if abs(delta) < 0.005:
        lines.append(f"Recommendation: Runs are equivalent (weighted F1 delta {delta:+.4f})")
    elif delta > 0:
        lines.append(f"Recommendation: Run B is better (weighted F1 {delta:+.4f})")
    else:
        lines.append(f"Recommendation: Run A is better (weighted F1 {delta:+.4f})")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest pipeline/tests/test_evaluate.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/plugins/ml/evaluate.py pipeline/tests/test_evaluate.py
git commit -m "feat: add model evaluation module with holdout metrics and run comparison"
```

---

### Task 2: Add holdout split to training functions

**Files:**
- Modify: `pipeline/plugins/ml/train.py:100-165` (train_model, train_daily_model)
- Modify: `pipeline/tests/test_train.py`

- [ ] **Step 1: Update test for holdout evaluation in train_daily_model**

Add to `pipeline/tests/test_train.py`:

```python
def test_train_daily_model_with_holdout_logs_evaluation():
    from datetime import date, timedelta
    n = 100
    today = date.today()
    dates = [today - timedelta(days=n - i) for i in range(n)]
    df = pd.DataFrame({
        "flow_cfs": [150.0] * n,
        "water_temp_f": [52.0] * n,
        "air_temp_f_mean": [55.0] * n,
        "air_temp_f_min": [40.0] * n,
        "air_temp_f_max": [70.0] * n,
        "precip_day_mm": [0.0] * n,
        "precip_3day_mm": [0.0] * n,
        "snowfall_mm": [0.0] * n,
        "wind_speed_mph_max": [12.0] * n,
        "day_of_year": [d.timetuple().tm_yday for d in dates],
        "days_since_precip_event": [5] * n,
        "condition": ["Good"] * n,
        "observed_date": dates,
    })
    import mlflow
    mlflow.set_tracking_uri("sqlite:///test_mlflow.db")
    booster, run_id = train_daily_model(df, experiment_name="test-holdout", holdout_days=60)
    assert booster is not None
    # Verify evaluation metrics were logged
    client = mlflow.tracking.MlflowClient()
    run = client.get_run(run_id)
    assert "eval_accuracy" in run.data.metrics
    assert "eval_weighted_f1" in run.data.metrics
    assert run.data.metrics["eval_holdout_samples"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest pipeline/tests/test_train.py::test_train_daily_model_with_holdout_logs_evaluation -v`
Expected: FAIL — `train_daily_model() got an unexpected keyword argument 'holdout_days'`

- [ ] **Step 3: Update train_model and train_daily_model to accept holdout**

Replace both functions in `pipeline/plugins/ml/train.py`:

```python
MIN_HOLDOUT_SAMPLES = 50


def train_model(
    df: pd.DataFrame,
    experiment_name: str = "riffle-conditions",
    holdout_days: int = 0,
    date_column: str = "observed_at",
) -> Tuple[xgb.Booster, str]:
    """Train XGBoost classifier on labeled data, log to MLflow.

    df must have columns: FEATURE_COLS + 'condition'.
    If holdout_days > 0 and date_column exists, splits data for evaluation.
    Returns: (trained booster, MLflow run_id).
    """
    # Holdout split
    holdout_df = None
    train_df = df
    if holdout_days > 0 and date_column in df.columns:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=holdout_days)
        train_df = df[df[date_column] < cutoff]
        holdout_df = df[df[date_column] >= cutoff]
        if len(holdout_df) < MIN_HOLDOUT_SAMPLES:
            print(f"  Warning: only {len(holdout_df)} holdout samples (need {MIN_HOLDOUT_SAMPLES}), skipping evaluation")
            holdout_df = None
            train_df = df

    X = train_df[FEATURE_COLS].values
    y = train_df["condition"].map(LABEL_TO_INT).values

    dtrain = xgb.DMatrix(X, label=y, feature_names=FEATURE_COLS)

    params = {
        "objective": "multi:softprob",
        "num_class": len(CONDITION_CLASSES),
        "max_depth": 4,
        "eta": 0.1,
        "subsample": 0.8,
        "eval_metric": "mlogloss",
        "seed": 42,
    }

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params(params)
        if holdout_days > 0:
            mlflow.log_param("holdout_days", holdout_days)
        booster = xgb.train(params, dtrain, num_boost_round=50)
        mlflow.xgboost.log_model(booster, artifact_path="model")

        if holdout_df is not None:
            from plugins.ml.evaluate import evaluate_holdout, log_evaluation_to_mlflow, format_summary
            X_hold = holdout_df[FEATURE_COLS].values
            y_hold = holdout_df["condition"].map(LABEL_TO_INT).values
            dhold = xgb.DMatrix(X_hold, feature_names=FEATURE_COLS)
            probas = booster.predict(dhold)
            metrics = evaluate_holdout(y_hold, probas, CONDITION_CLASSES, training_samples=len(train_df))
            log_evaluation_to_mlflow(metrics, CONDITION_CLASSES)
            print(format_summary(metrics, CONDITION_CLASSES))

        run_id = run.info.run_id

    return booster, run_id


def train_daily_model(
    df: pd.DataFrame,
    experiment_name: str = "riffle-conditions-daily",
    holdout_days: int = 0,
    date_column: str = "observed_date",
) -> Tuple[xgb.Booster, str]:
    """Train XGBoost classifier on daily-granularity data, log to MLflow.

    df must have columns: DAILY_FEATURE_COLS + 'condition'.
    If holdout_days > 0 and date_column exists, splits data for evaluation.
    Returns: (trained booster, MLflow run_id).
    """
    # Holdout split
    holdout_df = None
    train_df = df
    if holdout_days > 0 and date_column in df.columns:
        cutoff = (pd.Timestamp.now() - pd.Timedelta(days=holdout_days)).date()
        train_df = df[df[date_column] < cutoff]
        holdout_df = df[df[date_column] >= cutoff]
        if len(holdout_df) < MIN_HOLDOUT_SAMPLES:
            print(f"  Warning: only {len(holdout_df)} holdout samples (need {MIN_HOLDOUT_SAMPLES}), skipping evaluation")
            holdout_df = None
            train_df = df

    X = train_df[DAILY_FEATURE_COLS].values
    y = train_df["condition"].map(LABEL_TO_INT).values

    dtrain = xgb.DMatrix(X, label=y, feature_names=DAILY_FEATURE_COLS)

    params = {
        "objective": "multi:softprob",
        "num_class": len(CONDITION_CLASSES),
        "max_depth": 4,
        "eta": 0.1,
        "subsample": 0.8,
        "eval_metric": "mlogloss",
        "seed": 42,
    }

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params(params)
        if holdout_days > 0:
            mlflow.log_param("holdout_days", holdout_days)
        booster = xgb.train(params, dtrain, num_boost_round=50)
        mlflow.xgboost.log_model(booster, artifact_path="model")

        if holdout_df is not None:
            from plugins.ml.evaluate import evaluate_holdout, log_evaluation_to_mlflow, format_summary
            X_hold = holdout_df[DAILY_FEATURE_COLS].values
            y_hold = holdout_df["condition"].map(LABEL_TO_INT).values
            dhold = xgb.DMatrix(X_hold, feature_names=DAILY_FEATURE_COLS)
            probas = booster.predict(dhold)
            metrics = evaluate_holdout(y_hold, probas, CONDITION_CLASSES, training_samples=len(train_df))
            log_evaluation_to_mlflow(metrics, CONDITION_CLASSES)
            print(format_summary(metrics, CONDITION_CLASSES))

        run_id = run.info.run_id

    return booster, run_id
```

- [ ] **Step 4: Run all train tests**

Run: `python -m pytest pipeline/tests/test_train.py -v`
Expected: All tests PASS (existing tests still work because holdout_days defaults to 0)

- [ ] **Step 5: Commit**

```bash
git add pipeline/plugins/ml/train.py pipeline/tests/test_train.py
git commit -m "feat: add rolling holdout evaluation to training functions"
```

---

### Task 3: Wire holdout into training flows

**Files:**
- Modify: `pipeline/flows/train_daily.py:25-71`
- Modify: `pipeline/flows/train.py:11-63`

- [ ] **Step 1: Update train_daily.py to pass observed_date and holdout_days**

In `pipeline/flows/train_daily.py`, the `_train_and_promote_daily` function builds a `records` list that becomes a DataFrame. Add `observed_date` to each record and pass `holdout_days=60` to `train_daily_model`:

Replace line 63-64:
```python
            features["condition"] = condition
            records.append(features)
```
with:
```python
            features["condition"] = condition
            features["observed_date"] = target_date
            records.append(features)
```

Replace line 70:
```python
    _, run_id = train_daily_model(df)
```
with:
```python
    _, run_id = train_daily_model(df, holdout_days=60)
```

- [ ] **Step 2: Update train.py to pass observed_at and holdout_days**

In `pipeline/flows/train.py`, add `observed_at` to each record. Replace line 55:
```python
            features["condition"] = condition
            records.append(features)
```
with:
```python
            features["condition"] = condition
            features["observed_at"] = target_datetime
            records.append(features)
```

Replace line 62:
```python
    _, run_id = train_model(df)
```
with:
```python
    _, run_id = train_model(df, holdout_days=60)
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest pipeline/tests/ api/tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add pipeline/flows/train_daily.py pipeline/flows/train.py
git commit -m "feat: wire 60-day rolling holdout into training flows"
```

---

### Task 4: Create comparison script

**Files:**
- Create: `pipeline/scripts/compare_runs.py`

- [ ] **Step 1: Create the comparison script**

```python
# pipeline/scripts/compare_runs.py
"""Compare evaluation metrics between two MLflow training runs.

Usage:
  python pipeline/scripts/compare_runs.py <run_id_A> <run_id_B>

Prints a side-by-side metrics table with deltas and a recommendation.
Works with any two runs that have eval_ metrics logged (i.e., runs
trained with holdout_days > 0).
"""

import argparse
import os
import sys

sys.path.insert(0, "pipeline")
os.environ.setdefault("MLFLOW_TRACKING_URI", "http://localhost:5000")

from plugins.ml.evaluate import compare_runs


def main():
    parser = argparse.ArgumentParser(
        description="Compare evaluation metrics between two MLflow runs"
    )
    parser.add_argument("run_id_a", help="MLflow run ID for the baseline (Run A)")
    parser.add_argument("run_id_b", help="MLflow run ID for the candidate (Run B)")
    args = parser.parse_args()

    print(compare_runs(args.run_id_a, args.run_id_b))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/scripts/compare_runs.py
git commit -m "feat: add CLI script for comparing MLflow training runs"
```

---

### Task 5: Write methodology documentation

**Files:**
- Create: `docs/model-evaluation-methodology.md`

- [ ] **Step 1: Write the methodology doc**

```markdown
# Model Evaluation Methodology

## Overview

Riffle evaluates its XGBoost condition-prediction model using a rolling
time-based holdout. Evaluation runs automatically on every weekly retrain
and metrics are logged to MLflow. A standalone comparison script enables
A/B testing when thresholds, features, or hyperparameters change.

## Rolling 60-Day Holdout

### Why Time-Based, Not Random

Random train/test splits leak temporal information. A flow reading from
June 14 is highly correlated with June 13 and June 15 — if June 13 and
June 15 are in the training set, predicting June 14 is trivially easy
and overstates model quality.

Time-based splits simulate real deployment: the model trains on
historical data and predicts future conditions it hasn't seen.

### How It Works

On each retrain (Sundays at 03:00 MT):

1. All labeled data is collected (23 gauges × ~730 days = ~15,000+ records)
2. Records with `observed_date >= today - 60` are held out for evaluation
3. Everything before the cutoff is used for training
4. After training, the model scores the holdout set
5. Metrics are computed and logged to MLflow

The 60-day window means:
- ~1,380 holdout samples (23 gauges × 60 days)
- Covers at least one full seasonal transition
- Over a year, every season gets evaluated as the window rolls forward

### Minimum Sample Gate

If the holdout set has fewer than 50 samples (e.g., a brand-new deployment
with limited history), evaluation is skipped and a warning is logged. Training
proceeds normally — the model still gets built, just without metrics.

## Metrics

### Accuracy
Percentage of holdout predictions that match the bootstrapped label.
Easy to understand but misleading when classes are imbalanced (e.g., if
80% of labels are "Good", a model that always predicts "Good" scores 80%).

### Weighted F1
Harmonic mean of precision and recall, weighted by class frequency.
**This is the primary metric for comparing runs.** It accounts for
class imbalance and penalizes models that ignore rare classes.

### Log Loss
Measures confidence calibration — does the model's 0.85 confidence
actually mean it's right 85% of the time? Lower is better. Useful for
detecting overconfident models that get the right answer but with
misleadingly high confidence.

### Per-Class Precision, Recall, F1
- **Precision**: Of all predictions for "Blown Out", how many were correct?
- **Recall**: Of all actual "Blown Out" days, how many did we catch?
- **F1**: Balance of precision and recall

Low recall for a class means the model misses it. Low precision means
the model over-predicts it. Both matter — missing a Blown Out day is
dangerous, but crying wolf erodes trust.

## Using the Comparison Script

After making a change (thresholds, features, hyperparameters):

1. Note the current model's MLflow run ID (visible in MLflow UI or Prefect logs)
2. Make your change
3. Retrain (trigger manually or wait for Sunday)
4. Compare the two runs:

```bash
python pipeline/scripts/compare_runs.py <old_run_id> <new_run_id>
```

Example output:

```
Comparison: Run A (a1b2c3d4) vs Run B (e5f6g7h8)

Metric                             Run A      Run B      Delta
--------------------------------------------------------------
eval_accuracy                     0.7200     0.7850    +0.0650
eval_weighted_f1                  0.7100     0.7720    +0.0620
eval_log_loss                     0.8900     0.7200    -0.1700
eval_f1_blown_out                 0.8500     0.8800    +0.0300
eval_f1_poor                      0.7400     0.7900    +0.0500
eval_f1_fair                      0.5800     0.6500    +0.0700
eval_f1_good                      0.6900     0.7400    +0.0500
eval_f1_excellent                 0.7700     0.8100    +0.0400

Recommendation: Run B is better (weighted F1 +0.0620)
```

### Interpreting Results

- **weighted_f1 delta > +0.02**: Meaningful improvement, adopt the change
- **weighted_f1 delta ±0.005**: Equivalent, prefer simplicity
- **weighted_f1 delta < -0.02**: Regression, investigate before adopting
- **log_loss decrease**: Better-calibrated confidence scores
- **Per-class F1 changes**: Check that no class collapsed (e.g., Fair F1 dropped to 0)

## Limitations

### Bootstrapped Labels ≠ Ground Truth

The model is evaluated against labels generated by rule-based thresholds,
not against human assessments of actual fishing conditions. A "perfect"
evaluation score means the model learned the rules well — not that the
rules themselves are correct.

### Seasonal Coverage

A 60-day window captures ~2 months of one season. If you change thresholds
in April, the first evaluation only covers spring runoff. Wait for the
window to roll through all three seasons before drawing conclusions about
year-round performance.

### Small Class Sizes

Rare conditions (Blown Out) may have very few holdout samples in any
given 60-day window. Per-class metrics for rare classes can swing
dramatically between retrains — look at trends over multiple retrains
rather than a single evaluation.

## Future: Ground Truth Collection

The most impactful improvement to evaluation would be collecting
human-labeled ground truth:

- In-app feedback ("Was this prediction accurate?")
- Fishing guide reports
- Personal fishing log entries

Even 50-100 labeled days across a handful of gauges would enable
evaluating whether the model's predictions match reality, not just
whether they match the bootstrapping rules.

## Computed: 2026-04-12
```

- [ ] **Step 2: Commit**

```bash
git add docs/model-evaluation-methodology.md
git commit -m "docs: add model evaluation methodology"
```

---

### Task 6: Rebuild, retrain, and verify end-to-end

**Files:** No code changes — verification only.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest pipeline/tests/ api/tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Rebuild prefect-serve**

Run: `docker compose up -d --build prefect-serve`
Expected: Container starts, all 5 deployments registered

- [ ] **Step 3: Trigger a retrain to verify evaluation runs**

Run: `docker exec riffle-prefect-serve-1 prefect deployment run "train-daily/train-daily"`

Watch logs: `docker compose logs prefect-serve --follow`

Expected: Logs show holdout evaluation summary with accuracy, weighted_f1, and per-class F1. MLflow at localhost:5000 shows the new run with eval_ metrics.

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A
git commit -m "chore: verify model evaluation end-to-end"
```
