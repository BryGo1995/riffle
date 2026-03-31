import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from datetime import datetime
from zoneinfo import ZoneInfo
from shared.weather_client import fetch_weather_forecast, WeatherHour

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MT = ZoneInfo("America/Denver")

MOCK_FORECAST = {
    "hourly": {
        "time": [
            "2026-03-31T07:00", "2026-03-31T08:00", "2026-03-31T09:00"
        ],
        "precipitation": [0.0, 1.2, 0.0],
        "precipitation_probability": [10, 40, 5],
        "temperature_2m": [45.0, 43.0, 48.0],
        "snowfall": [0.0, 0.0, 0.0],
        "wind_speed_10m": [5.0, 7.2, 4.1],
        "weather_code": [1, 61, 2],
        "cloud_cover": [20, 80, 30],
        "surface_pressure": [1013.0, 1011.5, 1012.0],
    }
}


@rsps.activate
def test_fetch_forecast_returns_weather_hours():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    assert len(results) == 3
    assert all(isinstance(r, WeatherHour) for r in results)


@rsps.activate
def test_fetch_forecast_first_hour_not_forecast():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    assert results[0].is_forecast is False


@rsps.activate
def test_fetch_forecast_remaining_hours_are_forecast():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    for r in results[1:]:
        assert r.is_forecast is True


@rsps.activate
def test_fetch_forecast_values_parsed_correctly():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    first = results[0]
    assert first.precip_mm == 0.0
    assert first.precip_probability == 10
    assert first.air_temp_f == 45.0
    assert first.snowfall_mm == 0.0
    assert first.wind_speed_mph == 5.0
    assert first.weather_code == 1
    assert first.cloud_cover_pct == 20
    assert first.surface_pressure_hpa == 1013.0


@rsps.activate
def test_fetch_forecast_observed_at_is_timezone_aware():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    assert results[0].observed_at.tzinfo is not None


@rsps.activate
def test_fetch_forecast_raises_on_http_error():
    rsps.add(rsps.GET, FORECAST_URL, status=429)
    with pytest.raises(RuntimeError, match="Open-Meteo"):
        fetch_weather_forecast(lat=38.9097, lon=-105.5666)


from datetime import date
from shared.weather_client import fetch_weather_historical

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

MOCK_ARCHIVE = {
    "hourly": {
        "time": ["2024-03-31T00:00", "2024-03-31T01:00"],
        "precipitation": [0.5, 0.0],
        "temperature_2m": [38.0, 37.5],
        "snowfall": [0.0, 0.0],
        "wind_speed_10m": [3.0, 2.5],
        "weather_code": [2, 1],
        "cloud_cover": [40, 20],
        "surface_pressure": [1015.0, 1015.2],
    }
}


@rsps.activate
def test_fetch_historical_returns_weather_hours():
    rsps.add(rsps.GET, ARCHIVE_URL, json=MOCK_ARCHIVE, status=200)
    results = fetch_weather_historical(
        lat=38.9097, lon=-105.5666,
        start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
    )
    assert len(results) == 2
    assert all(isinstance(r, WeatherHour) for r in results)


@rsps.activate
def test_fetch_historical_precip_probability_is_none():
    rsps.add(rsps.GET, ARCHIVE_URL, json=MOCK_ARCHIVE, status=200)
    results = fetch_weather_historical(
        lat=38.9097, lon=-105.5666,
        start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
    )
    assert all(r.precip_probability is None for r in results)


@rsps.activate
def test_fetch_historical_all_rows_not_forecast():
    rsps.add(rsps.GET, ARCHIVE_URL, json=MOCK_ARCHIVE, status=200)
    results = fetch_weather_historical(
        lat=38.9097, lon=-105.5666,
        start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
    )
    assert all(r.is_forecast is False for r in results)


@rsps.activate
def test_fetch_historical_raises_on_http_error():
    rsps.add(rsps.GET, ARCHIVE_URL, status=500)
    with pytest.raises(RuntimeError, match="Open-Meteo"):
        fetch_weather_historical(
            lat=38.9097, lon=-105.5666,
            start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
        )
