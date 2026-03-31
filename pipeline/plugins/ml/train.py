"""XGBoost training + MLflow integration for Riffle.

Bootstraps condition labels from domain-knowledge thresholds,
trains a multi-class classifier, logs to MLflow, and returns
the trained booster and MLflow run ID.
"""

from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd
import xgboost as xgb
import mlflow
import mlflow.xgboost

CONDITION_CLASSES = ["Blown Out", "Poor", "Fair", "Good", "Excellent"]
LABEL_TO_INT = {c: i for i, c in enumerate(CONDITION_CLASSES)}
FEATURE_COLS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "days_since_precip_event",
]


def label_condition(
    flow_cfs: float,
    water_temp_f: float,
    seasonal_median: float,
    thresholds: Dict,
) -> str:
    """Apply domain-knowledge thresholds to assign a condition label.

    Priority order: Blown Out > Poor > Fair > Good > Excellent.
    """
    if flow_cfs > thresholds["blowout"] or water_temp_f > 68:
        return "Blown Out"
    if flow_cfs > seasonal_median * 1.5 or water_temp_f >= 65:
        return "Poor"
    if flow_cfs > seasonal_median * 1.2 or water_temp_f >= 60:
        return "Fair"
    if seasonal_median * 0.8 <= flow_cfs <= seasonal_median * 1.2 and water_temp_f <= 60:
        if water_temp_f <= 50:
            return "Excellent"
        return "Good"
    return "Excellent"


def generate_labels(
    df: pd.DataFrame,
    seasonal_medians: Optional[Dict[str, float]] = None,
    default_thresholds: Optional[Dict] = None,
) -> pd.Series:
    """Generate bootstrapped labels for a DataFrame of gauge readings.

    df must have columns: flow_cfs, water_temp_f, gauge_id (optional).
    seasonal_medians: {gauge_id: median_flow_cfs}. Falls back to df median.
    default_thresholds: used when per-gauge thresholds are unavailable.
    """
    if default_thresholds is None:
        default_thresholds = {"blowout": 2000, "optimal_low": 100, "optimal_high": 500}

    median = (
        seasonal_medians.get(str(df.get("gauge_id", "").iloc[0]), df["flow_cfs"].median())
        if seasonal_medians and "gauge_id" in df.columns
        else df["flow_cfs"].median()
    )

    return df.apply(
        lambda row: label_condition(
            flow_cfs=row["flow_cfs"],
            water_temp_f=row["water_temp_f"],
            seasonal_median=median,
            thresholds=default_thresholds,
        ),
        axis=1,
    )


def train_model(
    df: pd.DataFrame,
    experiment_name: str = "riffle-conditions",
) -> Tuple[xgb.Booster, str]:
    """Train XGBoost classifier on labeled data, log to MLflow.

    df must have columns: FEATURE_COLS + 'condition'.
    Returns: (trained booster, MLflow run_id).
    """
    X = df[FEATURE_COLS].values
    y = df["condition"].map(LABEL_TO_INT).values

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
        booster = xgb.train(params, dtrain, num_boost_round=50)
        mlflow.xgboost.log_model(booster, artifact_path="model")
        run_id = run.info.run_id

    return booster, run_id
