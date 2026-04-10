import sys
sys.path.insert(0, "pipeline")

from datetime import date
from unittest.mock import patch, MagicMock

from shared.ingest_daily import (
    IngestResult,
    ingest_gauge_daily,
    ingest_weather_daily,
)
from shared.usgs_client import USGSDailyReading
from shared.weather_client import WeatherDay


def _fake_usgs_row(observed_date: date, flow: float | None) -> USGSDailyReading:
    return USGSDailyReading(
        gauge_id="09085000",
        observed_date=observed_date,
        flow_cfs=flow,
        water_temp_f=48.0,
    )


def _fake_weather_day(observed_date: date) -> WeatherDay:
    return WeatherDay(
        observed_date=observed_date,
        precip_mm_sum=1.0,
        air_temp_f_mean=50.0,
        air_temp_f_min=40.0,
        air_temp_f_max=60.0,
        snowfall_mm_sum=0.0,
        wind_speed_mph_max=5.0,
        is_forecast=False,
    )


@patch("shared.ingest_daily.upsert_gauge_daily_reading")
@patch("shared.ingest_daily.fetch_gauge_daily_range")
def test_ingest_gauge_daily_returns_counts_for_valid_rows(
    mock_fetch, mock_upsert
):
    mock_fetch.return_value = [
        _fake_usgs_row(date(2026, 4, 9), flow=150.0),
        _fake_usgs_row(date(2026, 4, 10), flow=160.0),
    ]

    result = ingest_gauge_daily(
        gauge_id=1,
        usgs_id="09085000",
        start=date(2026, 4, 9),
        end=date(2026, 4, 10),
    )

    assert isinstance(result, IngestResult)
    assert result.rows_written == 2
    assert result.valid_flow_rows == 2
    mock_fetch.assert_called_once_with("09085000", date(2026, 4, 9), date(2026, 4, 10))
    assert mock_upsert.call_count == 2


@patch("shared.ingest_daily.upsert_gauge_daily_reading")
@patch("shared.ingest_daily.fetch_gauge_daily_range")
def test_ingest_gauge_daily_counts_null_flow_as_invalid(
    mock_fetch, mock_upsert
):
    mock_fetch.return_value = [
        _fake_usgs_row(date(2026, 4, 9), flow=None),
        _fake_usgs_row(date(2026, 4, 10), flow=150.0),
    ]

    result = ingest_gauge_daily(
        gauge_id=1,
        usgs_id="09085000",
        start=date(2026, 4, 9),
        end=date(2026, 4, 10),
    )

    assert result.rows_written == 2
    assert result.valid_flow_rows == 1


@patch("shared.ingest_daily.upsert_gauge_daily_reading")
@patch("shared.ingest_daily.fetch_gauge_daily_range")
def test_ingest_gauge_daily_handles_empty_response(mock_fetch, mock_upsert):
    mock_fetch.return_value = []

    result = ingest_gauge_daily(
        gauge_id=1,
        usgs_id="09085000",
        start=date(2026, 4, 10),
        end=date(2026, 4, 10),
    )

    assert result.rows_written == 0
    assert result.valid_flow_rows == 0
    mock_upsert.assert_not_called()


@patch("shared.ingest_daily.upsert_weather_daily_reading")
@patch("shared.ingest_daily.fetch_weather_daily_archive")
def test_ingest_weather_daily_upserts_each_day(mock_fetch, mock_upsert):
    mock_fetch.return_value = [
        _fake_weather_day(date(2026, 4, 9)),
        _fake_weather_day(date(2026, 4, 10)),
    ]

    count = ingest_weather_daily(
        gauge_id=1,
        lat=39.5,
        lon=-106.0,
        start=date(2026, 4, 9),
        end=date(2026, 4, 10),
    )

    assert count == 2
    mock_fetch.assert_called_once_with(39.5, -106.0, date(2026, 4, 9), date(2026, 4, 10))
    assert mock_upsert.call_count == 2
    # Confirm is_forecast=False is passed (historical archive)
    for call in mock_upsert.call_args_list:
        assert call.kwargs["is_forecast"] is False
