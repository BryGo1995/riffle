import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone
from shared.db_client import (
    upsert_gauge_reading,
    upsert_weather_reading,
    upsert_prediction,
    get_gauge_id,
    get_recent_gauge_readings,
    get_recent_weather_readings,
)

@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session

def test_upsert_gauge_reading_executes_upsert(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_gauge_reading(
            gauge_id=1,
            fetched_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
            flow_cfs=245.0,
            water_temp_f=54.5,
            gauge_height_ft=1.82,
        )
    mock_session.execute.assert_called_once()

def test_upsert_weather_reading_executes_upsert(mock_session):
    from datetime import date
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_weather_reading(
            gauge_id=1,
            date=date(2026, 3, 30),
            precip_mm=2.5,
            air_temp_f=55.0,
            is_forecast=False,
        )
    mock_session.execute.assert_called_once()

def test_upsert_prediction_executes_upsert(mock_session):
    from datetime import date
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_prediction(
            gauge_id=1,
            date=date(2026, 3, 30),
            condition="Good",
            confidence=0.82,
            is_forecast=False,
            model_version="1",
        )
    mock_session.execute.assert_called_once()

def test_get_gauge_id_returns_id(mock_session):
    mock_session.execute.return_value.scalar_one.return_value = 7
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_gauge_id("09035800")
    assert result == 7
