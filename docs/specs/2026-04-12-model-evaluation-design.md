# Model Evaluation System — Design Spec

## Goal

Add repeatable model evaluation to Riffle so that threshold changes,
feature engineering, and hyperparameter tuning can be measured objectively.
Evaluation runs automatically on every retrain and can be compared manually
across any two MLflow runs.

## Context

Riffle uses bootstrapped labels (rule-based thresholds, not human ground
truth) to train an XGBoost multi-class classifier. This means evaluation
measures how well the model generalizes the labeling rules to unseen time
periods — not whether predictions match real fishing conditions. Ground
truth collection is a future enhancement.

## Components

### 1. Evaluation Module (`pipeline/plugins/ml/evaluate.py`)

Shared evaluation logic used by both the training flow and the comparison
script.

**Functions:**

- `evaluate_holdout(booster, X, y, feature_names)` → `dict`
  - Takes trained XGBoost booster, holdout features, holdout labels
  - Returns metrics dict:
    - `accuracy`, `weighted_f1`, `log_loss`
    - Per-class `precision_<class>`, `recall_<class>`, `f1_<class>`
    - `holdout_samples`, `training_samples` (passed in)
    - `confusion_matrix`: list of lists (5x5)
    - `label_distribution`: `{"train": {class: count}, "holdout": {class: count}}`

- `log_evaluation_to_mlflow(metrics)` → `None`
  - Logs scalar metrics via `mlflow.log_metric()`
  - Logs confusion matrix as `confusion_matrix.csv` artifact
  - Logs label distribution as `label_distribution.csv` artifact

- `print_evaluation_summary(metrics)` → `None`
  - Prints a human-readable summary to stdout (captured by Prefect logs)

- `compare_runs(run_id_a, run_id_b)` → `None`
  - Fetches metrics from MLflow for both runs
  - Prints side-by-side comparison table with deltas
  - Prints recommendation based on weighted F1

### 2. Training Flow Integration

Modified in `train_daily.py` (and `train.py` for hourly):

**Rolling 60-day holdout split:**
- Holdout set: observations where `observed_date >= today - 60 days`
- Training set: everything before the holdout cutoff
- If holdout has fewer than 50 samples, skip evaluation and log a warning
- The split happens after feature/label generation, before `xgb.train()`

**What gets logged per retrain:**

MLflow metrics (flat, comparable across runs):
- `eval_accuracy`, `eval_weighted_f1`, `eval_log_loss`
- `eval_f1_blown_out`, `eval_f1_poor`, `eval_f1_fair`, `eval_f1_good`, `eval_f1_excellent`
- `eval_precision_blown_out`, ..., `eval_recall_excellent`
- `holdout_samples`, `training_samples`
- `holdout_days` (number of days in holdout window)

MLflow artifacts:
- `confusion_matrix.csv` — 5×5 matrix, rows=actual, cols=predicted
- `label_distribution.csv` — class counts for train and holdout sets

Prefect log output:
- One-line summary with accuracy, weighted F1, log loss, per-class F1

### 3. Comparison Script (`pipeline/scripts/compare_runs.py`)

Standalone CLI tool for comparing any two MLflow runs:

```
python pipeline/scripts/compare_runs.py <run_id_A> <run_id_B>
```

**Output:** Prints to terminal:
- Side-by-side table: metric name | run A | run B | delta
- Label distribution comparison
- One-line recommendation: "Run B is better (weighted F1 +0.04)"

**No MLflow UI required.** Works from the command line. Reads metrics
via `mlflow.get_run()`.

### 4. Methodology Documentation

`docs/model-evaluation-methodology.md` covering:
- Rolling holdout approach and rationale
- What each metric means in plain language
- How to use the comparison script with examples
- How to interpret results and make threshold/feature decisions
- Known limitations (bootstrapped labels, seasonal coverage)
- When to re-evaluate (after any threshold, feature, or hyperparameter change)

## Files Changed

| File | Action | Purpose |
|------|--------|---------|
| `pipeline/plugins/ml/evaluate.py` | Create | Shared evaluation functions |
| `pipeline/plugins/ml/train.py` | Modify | Add holdout split to `train_model` and `train_daily_model` |
| `pipeline/flows/train_daily.py` | Modify | Pass holdout data through training, call evaluation |
| `pipeline/flows/train.py` | Modify | Same for hourly model |
| `pipeline/scripts/compare_runs.py` | Create | CLI comparison tool |
| `pipeline/tests/test_evaluate.py` | Create | Tests for evaluation module |
| `pipeline/tests/test_train.py` | Modify | Update training tests for holdout split |
| `docs/model-evaluation-methodology.md` | Create | Methodology documentation |

## What This Does NOT Include

- No automated accept/reject gating — human reviews metrics and decides
- No ground truth collection — future enhancement
- No changes to the scoring/prediction pipeline — evaluation only
- No changes to the Prefect schedule — evaluation runs within existing retrain

## Dependencies

- `scikit-learn` for `classification_report`, `confusion_matrix`, `log_loss`
  - Already installed (transitive dependency of mlflow)

## Computed: 2026-04-12
