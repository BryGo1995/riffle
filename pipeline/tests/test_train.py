import sys
sys.path.insert(0, "pipeline")
import pytest
import pandas as pd
from plugins.ml.train import (
    label_condition,
    generate_labels,
    train_model,
    train_daily_model,
    CONDITION_CLASSES,
    DAILY_FEATURE_COLS,
)

# Seasonal thresholds modeled after a typical gauge
THRESHOLDS = {"blowout": 500, "optimal_low": 80, "optimal_high": 250}

def test_condition_classes_ordered():
    assert CONDITION_CLASSES == ["Blown Out", "Poor", "Fair", "Good", "Excellent"]

def test_label_blown_out_by_flow():
    assert label_condition(600, 55.0, thresholds=THRESHOLDS) == "Blown Out"

def test_label_blown_out_by_temp():
    assert label_condition(100, 70.0, thresholds=THRESHOLDS) == "Blown Out"

def test_label_poor_above_optimal_high():
    assert label_condition(260, 55.0, thresholds=THRESHOLDS) == "Poor"

def test_label_poor_warm_temp():
    assert label_condition(100, 66.0, thresholds=THRESHOLDS) == "Poor"

def test_label_fair_above_blend():
    # blend = 0.85 * 250 + 0.15 * 80 = 224.5; flow 230 > blend
    assert label_condition(230, 55.0, thresholds=THRESHOLDS) == "Fair"

def test_label_fair_below_optimal_low():
    assert label_condition(50, 55.0, thresholds=THRESHOLDS) == "Fair"

def test_label_good():
    assert label_condition(150, 55.0, thresholds=THRESHOLDS) == "Good"

def test_label_excellent():
    assert label_condition(150, 50.0, thresholds=THRESHOLDS) == "Excellent"

def test_label_frozen_gauge_winter():
    assert label_condition(100, 35.0, thresholds=THRESHOLDS, freezes=True, month=1) == "Poor"

def test_label_frozen_gauge_summer_not_forced():
    # Same gauge in summer should NOT be forced to Poor
    result = label_condition(150, 50.0, thresholds=THRESHOLDS, freezes=True, month=6)
    assert result == "Excellent"

def test_label_non_frozen_gauge_winter_uses_thresholds():
    # Non-freezing gauge in winter uses thresholds normally
    result = label_condition(150, 50.0, thresholds=THRESHOLDS, freezes=False, month=1)
    assert result == "Excellent"

def test_train_model_returns_booster_and_version():
    # Synthetic dataset: 50 rows, 15 features
    n = 50
    df = pd.DataFrame({
        "flow_cfs": [150.0] * n,
        "gauge_height_ft": [1.5] * n,
        "water_temp_f": [52.0] * n,
        "precip_24h_mm": [0.0] * n,
        "precip_72h_mm": [0.0] * n,
        "air_temp_f": [55.0] * n,
        "day_of_year": [90] * n,
        "hour_of_day": [8] * n,
        "days_since_precip_event": [5] * n,
        "precip_probability": [0] * n,
        "snowfall_mm": [0.0] * n,
        "wind_speed_mph": [5.0] * n,
        "weather_code": [1] * n,
        "cloud_cover_pct": [20] * n,
        "surface_pressure_hpa": [1013.25] * n,
        "condition": ["Good"] * n,
    })
    import mlflow
    mlflow.set_tracking_uri("sqlite:///test_mlflow.db")
    booster, run_id = train_model(df, experiment_name="test-riffle")
    assert booster is not None
    assert isinstance(run_id, str)


def test_daily_feature_cols_excludes_hourly_only_features():
    # Sanity check that the daily feature schema doesn't accidentally pull in
    # hourly-only features that wouldn't be available at daily granularity.
    excluded = {"hour_of_day", "gauge_height_ft", "weather_code", "precip_probability"}
    assert excluded.isdisjoint(set(DAILY_FEATURE_COLS))


def test_train_daily_model_returns_booster_and_version():
    n = 50
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
        "day_of_year": [90] * n,
        "days_since_precip_event": [5] * n,
        "condition": ["Good"] * n,
    })
    import mlflow
    mlflow.set_tracking_uri("sqlite:///test_mlflow.db")
    booster, run_id = train_daily_model(df, experiment_name="test-riffle-daily")
    assert booster is not None
    assert isinstance(run_id, str)


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
    client = mlflow.tracking.MlflowClient()
    run = client.get_run(run_id)
    assert "eval_accuracy" in run.data.metrics
    assert "eval_weighted_f1" in run.data.metrics
    assert run.data.metrics["eval_holdout_samples"] > 0
