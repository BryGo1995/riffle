import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from plugins.ml.score import predict_condition, predict_daily_condition, load_production_model
from plugins.ml.train import CONDITION_CLASSES


def test_predict_condition_returns_valid_label():
    mock_booster = MagicMock()
    # softprob returns one probability per class per row
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][3] = 0.9  # index 3 = "Good"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 150.0, "gauge_height_ft": 1.5, "water_temp_f": 52.0,
        "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 55.0,
        "day_of_year": 90, "hour_of_day": 10, "days_since_precip_event": 5,
        "precip_probability": 0.0, "snowfall_mm": 0.0, "wind_speed_mph": 5.0,
        "weather_code": 0, "cloud_cover_pct": 20.0, "surface_pressure_hpa": 1013.0,
    }
    label, confidence = predict_condition(mock_booster, features)
    assert label == "Good"
    assert confidence == pytest.approx(0.9)


def test_predict_condition_returns_str_and_float():
    mock_booster = MagicMock()
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][0] = 0.95  # "Blown Out"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 1000.0, "gauge_height_ft": 5.0, "water_temp_f": 55.0,
        "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 45.0,
        "day_of_year": 150, "hour_of_day": 8, "days_since_precip_event": 1,
        "precip_probability": 0.1, "snowfall_mm": 0.0, "wind_speed_mph": 10.0,
        "weather_code": 0, "cloud_cover_pct": 50.0, "surface_pressure_hpa": 1010.0,
    }
    label, confidence = predict_condition(mock_booster, features)
    assert isinstance(label, str)
    assert isinstance(confidence, float)
    assert label == "Blown Out"


def test_predict_daily_condition_returns_valid_label():
    mock_booster = MagicMock()
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][4] = 0.85  # "Excellent"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 150.0, "water_temp_f": 50.0,
        "air_temp_f_mean": 55.0, "air_temp_f_min": 40.0, "air_temp_f_max": 70.0,
        "precip_day_mm": 0.0, "precip_3day_mm": 0.0,
        "snowfall_mm": 0.0, "wind_speed_mph_max": 12.0,
        "day_of_year": 90, "days_since_precip_event": 5,
    }
    label, confidence = predict_daily_condition(mock_booster, features)
    assert label == "Excellent"
    assert confidence == pytest.approx(0.85)


# --- daily_forecast ingest task tests ---


@patch("flows.daily_forecast.ingest_weather_daily")
@patch("flows.daily_forecast.ingest_gauge_daily")
@patch("flows.daily_forecast.get_gauge_id")
def test_ingest_daily_task_fetches_yesterday_for_each_active_gauge(
    mock_get_id, mock_ingest_gauge, mock_ingest_weather
):
    from datetime import date, timedelta
    from shared.ingest_daily import IngestResult
    from flows.daily_forecast import ingest_daily_task
    from config.rivers import GAUGES

    yesterday = date.today() - timedelta(days=1)
    mock_get_id.side_effect = lambda usgs_id: hash(usgs_id) % 10000
    mock_ingest_gauge.return_value = IngestResult(rows_written=1, valid_flow_rows=1)
    mock_ingest_weather.return_value = 1

    # Prefect tasks can be called directly like plain functions in tests using .fn
    ingest_daily_task.fn()

    assert mock_ingest_gauge.call_count == len(GAUGES)
    # Every call must use yesterday as both start and end
    for call in mock_ingest_gauge.call_args_list:
        assert call.kwargs["start"] == yesterday
        assert call.kwargs["end"] == yesterday
    # Same check for weather
    assert mock_ingest_weather.call_count == len(GAUGES)
    for call in mock_ingest_weather.call_args_list:
        assert call.kwargs["start"] == yesterday
        assert call.kwargs["end"] == yesterday


@patch("flows.daily_forecast.ingest_weather_daily")
@patch("flows.daily_forecast.ingest_gauge_daily")
@patch("flows.daily_forecast.get_gauge_id")
def test_ingest_daily_task_raises_when_zero_gauges_get_valid_flow(
    mock_get_id, mock_ingest_gauge, mock_ingest_weather
):
    from shared.ingest_daily import IngestResult
    from flows.daily_forecast import ingest_daily_task

    mock_get_id.side_effect = lambda usgs_id: 1
    # Every gauge comes back with zero valid flow rows
    mock_ingest_gauge.return_value = IngestResult(rows_written=1, valid_flow_rows=0)
    mock_ingest_weather.return_value = 1

    with pytest.raises(RuntimeError, match="no gauges received valid flow_cfs"):
        ingest_daily_task.fn()


@patch("flows.daily_forecast.ingest_weather_daily")
@patch("flows.daily_forecast.ingest_gauge_daily")
@patch("flows.daily_forecast.get_gauge_id")
def test_ingest_daily_task_succeeds_when_any_gauge_has_valid_flow(
    mock_get_id, mock_ingest_gauge, mock_ingest_weather
):
    from shared.ingest_daily import IngestResult
    from flows.daily_forecast import ingest_daily_task
    from config.rivers import GAUGES

    mock_get_id.side_effect = lambda usgs_id: 1
    # Alternate: some valid, some not. Task should NOT raise.
    results = [
        IngestResult(rows_written=1, valid_flow_rows=1 if i % 2 == 0 else 0)
        for i in range(len(GAUGES))
    ]
    mock_ingest_gauge.side_effect = results
    mock_ingest_weather.return_value = 1

    # Should not raise
    ingest_daily_task.fn()
