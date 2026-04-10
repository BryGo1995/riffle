import sys
sys.path.insert(0, "pipeline")
import pytest
from datetime import datetime, timedelta, timezone
from plugins.features import build_feature_vector, compute_days_since_precip, compute_precip_72h

MT_OFFSET = timezone(timedelta(hours=-7))

def make_hour(dt: datetime, precip_mm: float) -> dict:
    return {
        "observed_at": dt,
        "precip_mm": precip_mm,
        "air_temp_f": 50.0,
        "precip_probability": None,
        "snowfall_mm": 0.0,
        "wind_speed_mph": 5.0,
        "weather_code": 1,
        "cloud_cover_pct": 20,
        "surface_pressure_hpa": 1013.0,
        "is_forecast": False,
    }

TARGET = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)

FEATURE_KEYS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "hour_of_day", "days_since_precip_event",
    "precip_probability", "snowfall_mm", "wind_speed_mph",
    "weather_code", "cloud_cover_pct", "surface_pressure_hpa",
]


def test_build_feature_vector_has_all_keys():
    history = [make_hour(TARGET - timedelta(hours=i), 0.0) for i in range(1, 5)]
    features = build_feature_vector(
        flow_cfs=245.0,
        gauge_height_ft=1.82,
        water_temp_f=54.5,
        air_temp_f=55.0,
        precip_24h_mm=0.0,
        target_datetime=TARGET,
        weather_history=history,
    )
    assert set(features.keys()) == set(FEATURE_KEYS)


def test_build_feature_vector_hour_of_day():
    history = [make_hour(TARGET - timedelta(hours=1), 0.0)]
    features = build_feature_vector(
        flow_cfs=100.0, gauge_height_ft=1.0, water_temp_f=50.0,
        air_temp_f=45.0, precip_24h_mm=0.0,
        target_datetime=TARGET, weather_history=history,
    )
    assert features["hour_of_day"] == TARGET.hour


def test_build_feature_vector_none_precip_probability_defaults_to_zero():
    history = [make_hour(TARGET - timedelta(hours=1), 0.0)]
    features = build_feature_vector(
        flow_cfs=100.0, gauge_height_ft=1.0, water_temp_f=50.0,
        air_temp_f=45.0, precip_24h_mm=0.0,
        target_datetime=TARGET, weather_history=history,
        precip_probability=None,
    )
    assert features["precip_probability"] == 0


def test_compute_precip_72h_sums_hourly_window():
    # 73 hours of 1mm/hr: hours 0 through 72 inclusive = 73 rows all within window
    history = [make_hour(TARGET - timedelta(hours=i), 1.0) for i in range(0, 73)]
    result = compute_precip_72h(history, TARGET)
    assert result == pytest.approx(73.0)


def test_compute_precip_72h_excludes_outside_window():
    history = [
        make_hour(TARGET - timedelta(hours=73), 99.0),  # outside
        make_hour(TARGET - timedelta(hours=1), 2.0),
    ]
    result = compute_precip_72h(history, TARGET)
    assert result == pytest.approx(2.0)


def test_compute_days_since_precip_aggregates_daily():
    # Two hours on same day total >= 5mm — counts as one event 3 days ago
    event_day = TARGET - timedelta(days=3)
    history = [
        make_hour(event_day.replace(hour=10), 3.0),
        make_hour(event_day.replace(hour=11), 3.0),
        make_hour(TARGET - timedelta(hours=1), 0.0),
    ]
    result = compute_days_since_precip(history, TARGET)
    assert result == 3


def test_compute_days_since_precip_returns_sentinel_when_no_event():
    history = [make_hour(TARGET - timedelta(hours=i), 0.1) for i in range(1, 10)]
    result = compute_days_since_precip(history, TARGET, threshold_mm=5.0)
    assert result == 30


# --- Daily feature builder tests ---

from datetime import date as date_type
from plugins.features import (
    build_daily_feature_vector,
    compute_precip_3day_daily,
    compute_days_since_precip_daily,
)

DAILY_FEATURE_KEYS = {
    "flow_cfs", "water_temp_f",
    "air_temp_f_mean", "air_temp_f_min", "air_temp_f_max",
    "precip_day_mm", "precip_3day_mm",
    "snowfall_mm", "wind_speed_mph_max",
    "day_of_year", "days_since_precip_event",
}

TARGET_DATE = date_type(2026, 3, 31)


def make_day(d: date_type, precip: float) -> dict:
    return {"observed_date": d, "precip_mm_sum": precip}


def test_build_daily_feature_vector_has_all_keys():
    history = [make_day(TARGET_DATE - timedelta(days=i), 0.0) for i in range(0, 4)]
    features = build_daily_feature_vector(
        flow_cfs=245.0,
        water_temp_f=54.5,
        air_temp_f_mean=55.0,
        air_temp_f_min=40.0,
        air_temp_f_max=68.0,
        precip_mm_sum=0.0,
        snowfall_mm_sum=0.0,
        wind_speed_mph_max=8.0,
        target_date=TARGET_DATE,
        weather_history_daily=history,
    )
    assert set(features.keys()) == DAILY_FEATURE_KEYS


def test_build_daily_feature_vector_no_hour_of_day():
    features = build_daily_feature_vector(
        flow_cfs=100.0, water_temp_f=50.0,
        air_temp_f_mean=45.0, air_temp_f_min=30.0, air_temp_f_max=60.0,
        precip_mm_sum=0.0, snowfall_mm_sum=0.0, wind_speed_mph_max=5.0,
        target_date=TARGET_DATE, weather_history_daily=[],
    )
    assert "hour_of_day" not in features
    assert "weather_code" not in features
    assert "precip_probability" not in features
    assert "gauge_height_ft" not in features


def test_build_daily_feature_vector_missing_water_temp_defaults():
    features = build_daily_feature_vector(
        flow_cfs=100.0, water_temp_f=None,
        air_temp_f_mean=45.0, air_temp_f_min=30.0, air_temp_f_max=60.0,
        precip_mm_sum=0.0, snowfall_mm_sum=0.0, wind_speed_mph_max=5.0,
        target_date=TARGET_DATE, weather_history_daily=[],
    )
    assert features["water_temp_f"] == 50.0


def test_compute_precip_3day_sums_inclusive_window():
    history = [
        make_day(TARGET_DATE - timedelta(days=3), 99.0),  # outside
        make_day(TARGET_DATE - timedelta(days=2), 5.0),
        make_day(TARGET_DATE - timedelta(days=1), 3.0),
        make_day(TARGET_DATE,                    2.0),
    ]
    assert compute_precip_3day_daily(history, TARGET_DATE) == pytest.approx(10.0)


def test_compute_days_since_precip_daily_finds_recent_event():
    history = [
        make_day(TARGET_DATE - timedelta(days=4), 6.0),
        make_day(TARGET_DATE - timedelta(days=2), 7.0),
        make_day(TARGET_DATE - timedelta(days=1), 0.5),
    ]
    assert compute_days_since_precip_daily(history, TARGET_DATE, threshold_mm=5.0) == 2


def test_compute_days_since_precip_daily_returns_sentinel_when_no_event():
    history = [make_day(TARGET_DATE - timedelta(days=i), 0.5) for i in range(1, 10)]
    assert compute_days_since_precip_daily(history, TARGET_DATE) == 30
