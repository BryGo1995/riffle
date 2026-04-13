"""XGBoost training + MLflow integration for Riffle.

Bootstraps condition labels from domain-knowledge thresholds,
trains a multi-class classifier, logs to MLflow, and returns
the trained booster and MLflow run ID.
"""

from datetime import date as date_type
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd
import xgboost as xgb
import mlflow
import mlflow.xgboost

from config.rivers import get_season, get_thresholds

CONDITION_CLASSES = ["Blown Out", "Poor", "Fair", "Good", "Excellent"]
LABEL_TO_INT = {c: i for i, c in enumerate(CONDITION_CLASSES)}
FEATURE_COLS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "hour_of_day", "days_since_precip_event",
    "precip_probability", "snowfall_mm", "wind_speed_mph",
    "weather_code", "cloud_cover_pct", "surface_pressure_hpa",
]
DAILY_FEATURE_COLS = [
    "flow_cfs", "water_temp_f",
    "air_temp_f_mean", "air_temp_f_min", "air_temp_f_max",
    "precip_day_mm", "precip_3day_mm",
    "snowfall_mm", "wind_speed_mph_max",
    "day_of_year", "days_since_precip_event",
]

MIN_HOLDOUT_SAMPLES = 50


def label_condition(
    flow_cfs: float,
    water_temp_f: float,
    thresholds: Dict,
    freezes: bool = False,
    month: int = 6,
) -> str:
    """Apply seasonal flow thresholds to assign a condition label.

    Args:
        flow_cfs: observed daily mean flow in cubic feet per second.
        water_temp_f: water temperature in Fahrenheit (may be a default).
        thresholds: seasonal dict with blowout, optimal_low, optimal_high.
        freezes: whether this gauge typically ices over in winter.
        month: month of the observation (1-12), used for winter detection.

    Priority order: Blown Out > Poor > Fair > Good > Excellent.
    """
    # Frozen gauges in winter are auto-labeled Poor.
    if freezes and get_season(month) == "winter":
        return "Poor"

    blowout = thresholds["blowout"]
    optimal_low = thresholds["optimal_low"]
    optimal_high = thresholds["optimal_high"]

    if flow_cfs > blowout or water_temp_f > 68:
        return "Blown Out"
    if flow_cfs > optimal_high or water_temp_f >= 65:
        return "Poor"
    if flow_cfs > (optimal_high * 0.85 + optimal_low * 0.15) or water_temp_f >= 60:
        return "Fair"
    if optimal_low <= flow_cfs <= optimal_high and water_temp_f <= 60:
        if water_temp_f <= 50:
            return "Excellent"
        return "Good"
    if flow_cfs < optimal_low:
        return "Fair"
    return "Good"


def generate_labels(
    df: pd.DataFrame,
    default_thresholds: Optional[Dict] = None,
) -> pd.Series:
    """Generate bootstrapped labels for a DataFrame of gauge readings.

    df must have columns: flow_cfs, water_temp_f.
    default_thresholds: used as a flat fallback when per-gauge seasonal
    thresholds are unavailable.
    """
    if default_thresholds is None:
        default_thresholds = {"blowout": 2000, "optimal_low": 100, "optimal_high": 500}

    return df.apply(
        lambda row: label_condition(
            flow_cfs=row["flow_cfs"],
            water_temp_f=row["water_temp_f"],
            thresholds=default_thresholds,
        ),
        axis=1,
    )


def train_model(
    df: pd.DataFrame,
    experiment_name: str = "riffle-conditions",
    holdout_days: int = 0,
    date_column: str = "observed_at",
) -> Tuple[xgb.Booster, str]:
    """Train XGBoost classifier on labeled data, log to MLflow.

    df must have columns: FEATURE_COLS + 'condition'.
    Returns: (trained booster, MLflow run_id).
    """
    holdout_df = None
    train_df = df
    if holdout_days > 0 and date_column in df.columns:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=holdout_days)
        train_df = df[df[date_column] < cutoff]
        holdout_df = df[df[date_column] >= cutoff]
        if len(holdout_df) < MIN_HOLDOUT_SAMPLES:
            print(
                f"Warning: only {len(holdout_df)} holdout samples "
                f"(need {MIN_HOLDOUT_SAMPLES}). Using full dataset."
            )
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
        booster = xgb.train(params, dtrain, num_boost_round=50)
        mlflow.xgboost.log_model(booster, artifact_path="model")

        if holdout_days > 0:
            mlflow.log_param("holdout_days", holdout_days)
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
    Returns: (trained booster, MLflow run_id).
    """
    holdout_df = None
    train_df = df
    if holdout_days > 0 and date_column in df.columns:
        cutoff = (pd.Timestamp.now() - pd.Timedelta(days=holdout_days)).date()
        train_df = df[df[date_column] < cutoff]
        holdout_df = df[df[date_column] >= cutoff]
        if len(holdout_df) < MIN_HOLDOUT_SAMPLES:
            print(
                f"Warning: only {len(holdout_df)} holdout samples "
                f"(need {MIN_HOLDOUT_SAMPLES}). Using full dataset."
            )
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
        booster = xgb.train(params, dtrain, num_boost_round=50)
        mlflow.xgboost.log_model(booster, artifact_path="model")

        if holdout_days > 0:
            mlflow.log_param("holdout_days", holdout_days)
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
