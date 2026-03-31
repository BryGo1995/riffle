import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from shared.db_client import (
    upsert_gauge_reading,
    upsert_weather_reading,
    upsert_prediction,
    get_gauge_id,
    get_recent_gauge_readings,
    get_recent_weather_readings,
    get_forecast_weather,
    get_weather_for_hour,
)

NOW = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def test_upsert_gauge_reading_executes(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_gauge_reading(
            gauge_id=1,
            fetched_at=NOW,
            flow_cfs=245.0,
            water_temp_f=54.5,
            gauge_height_ft=1.82,
        )
    mock_session.execute.assert_called_once()


def test_upsert_weather_reading_executes(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_weather_reading(
            gauge_id=1,
            observed_at=NOW,
            precip_mm=2.5,
            precip_probability=40,
            air_temp_f=55.0,
            snowfall_mm=0.0,
            wind_speed_mph=5.0,
            weather_code=61,
            cloud_cover_pct=80,
            surface_pressure_hpa=1011.5,
            is_forecast=False,
        )
    mock_session.execute.assert_called_once()


def test_upsert_weather_reading_accepts_none_precip_probability(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_weather_reading(
            gauge_id=1,
            observed_at=NOW,
            precip_mm=0.0,
            precip_probability=None,
            air_temp_f=40.0,
            snowfall_mm=0.0,
            wind_speed_mph=3.0,
            weather_code=1,
            cloud_cover_pct=10,
            surface_pressure_hpa=1015.0,
            is_forecast=False,
        )
    mock_session.execute.assert_called_once()


def test_upsert_prediction_executes(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_prediction(
            gauge_id=1,
            target_datetime=NOW,
            condition="Good",
            confidence=0.82,
            is_forecast=False,
            model_version="production",
        )
    mock_session.execute.assert_called_once()


def test_get_gauge_id_returns_id(mock_session):
    mock_session.execute.return_value.scalar_one.return_value = 7
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_gauge_id("09035800")
    assert result == 7


def test_get_recent_weather_readings_executes(mock_session):
    mock_session.execute.return_value.fetchall.return_value = []
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_recent_weather_readings(gauge_id=1, hours=2160)
    assert result == []
    mock_session.execute.assert_called_once()


def test_get_forecast_weather_executes(mock_session):
    mock_session.execute.return_value.fetchall.return_value = []
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_forecast_weather(gauge_id=1)
    assert result == []
    mock_session.execute.assert_called_once()


def test_get_weather_for_hour_returns_none_when_no_rows(mock_session):
    mock_session.execute.return_value.fetchone.return_value = None
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_weather_for_hour(gauge_id=1, observed_at=NOW)
    assert result is None
