import sys
sys.path.insert(0, "pipeline")
import pytest
from datetime import date
from plugins.features import build_feature_vector, compute_days_since_precip, compute_precip_72h

FEATURE_KEYS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "days_since_precip_event",
]

def test_build_feature_vector_has_all_keys():
    weather_history = [
        {"date": date(2026, 3, 30), "precip_mm": 0.0},
        {"date": date(2026, 3, 29), "precip_mm": 0.0},
        {"date": date(2026, 3, 28), "precip_mm": 6.0},  # event
        {"date": date(2026, 3, 27), "precip_mm": 0.0},
    ]
    features = build_feature_vector(
        flow_cfs=245.0,
        gauge_height_ft=1.82,
        water_temp_f=54.5,
        air_temp_f=55.0,
        precip_24h_mm=0.0,
        target_date=date(2026, 3, 30),
        weather_history=weather_history,
    )
    assert set(features.keys()) == set(FEATURE_KEYS)

def test_day_of_year_correct():
    weather_history = [{"date": date(2026, 1, 1), "precip_mm": 0.0}]
    features = build_feature_vector(
        flow_cfs=100.0, gauge_height_ft=1.0, water_temp_f=50.0,
        air_temp_f=45.0, precip_24h_mm=0.0,
        target_date=date(2026, 1, 1), weather_history=weather_history,
    )
    assert features["day_of_year"] == 1

def test_compute_precip_72h_sums_three_days():
    history = [
        {"date": date(2026, 3, 30), "precip_mm": 1.0},
        {"date": date(2026, 3, 29), "precip_mm": 2.0},
        {"date": date(2026, 3, 28), "precip_mm": 3.0},
        {"date": date(2026, 3, 27), "precip_mm": 10.0},  # outside 72h window
    ]
    result = compute_precip_72h(history, target_date=date(2026, 3, 30))
    assert result == pytest.approx(6.0)

def test_days_since_precip_event_no_recent_event():
    history = [
        {"date": date(2026, 3, 30), "precip_mm": 0.0},
        {"date": date(2026, 3, 29), "precip_mm": 0.0},
        {"date": date(2026, 3, 28), "precip_mm": 0.0},
    ]
    result = compute_days_since_precip(history, target_date=date(2026, 3, 30), threshold_mm=5.0)
    assert result == 30  # sentinel: no event in window

def test_days_since_precip_event_finds_event():
    history = [
        {"date": date(2026, 3, 30), "precip_mm": 0.0},
        {"date": date(2026, 3, 29), "precip_mm": 0.0},
        {"date": date(2026, 3, 28), "precip_mm": 8.0},  # event: 2 days ago
    ]
    result = compute_days_since_precip(history, target_date=date(2026, 3, 30), threshold_mm=5.0)
    assert result == 2
