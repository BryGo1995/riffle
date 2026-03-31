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
