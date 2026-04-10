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

# flow_thresholds for South Platte Spinney
THRESHOLDS = {"blowout": 500, "optimal_low": 80, "optimal_high": 250}

def test_condition_classes_ordered():
    assert CONDITION_CLASSES == ["Blown Out", "Poor", "Fair", "Good", "Excellent"]

def test_label_blown_out_by_flow():
    assert label_condition(600, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Blown Out"

def test_label_blown_out_by_temp():
    assert label_condition(100, 70.0, seasonal_median=150, thresholds=THRESHOLDS) == "Blown Out"

def test_label_poor_high_flow():
    # 150% of median = 225
    assert label_condition(230, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Poor"

def test_label_poor_warm_temp():
    assert label_condition(100, 66.0, seasonal_median=150, thresholds=THRESHOLDS) == "Poor"

def test_label_fair():
    # 120% of median = 180
    assert label_condition(190, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Fair"

def test_label_good():
    # 80-120% of median = 120-180
    assert label_condition(150, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Good"

def test_label_excellent():
    assert label_condition(150, 50.0, seasonal_median=150, thresholds=THRESHOLDS) == "Excellent"

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
