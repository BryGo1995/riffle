import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from datetime import date
from shared.weather_client import fetch_weather, WeatherDay

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

MOCK_RESPONSE = {
    "daily": {
        "time": ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02"],
        "precipitation_sum": [0.0, 2.5, 0.0, 1.2],
        "temperature_2m_max": [55.0, 48.0, 60.0, 52.0],
    }
}

@rsps.activate
def test_fetch_returns_four_days():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    assert len(results) == 4

@rsps.activate
def test_first_day_is_not_forecast():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    assert results[0].is_forecast is False

@rsps.activate
def test_remaining_days_are_forecast():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    for day in results[1:]:
        assert day.is_forecast is True

@rsps.activate
def test_values_parsed_correctly():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    assert results[0].date == date(2026, 3, 30)
    assert results[0].precip_mm == 0.0
    assert results[0].air_temp_f == 55.0
    assert results[1].precip_mm == 2.5

@rsps.activate
def test_raises_on_http_error():
    rsps.add(rsps.GET, OPEN_METEO_BASE, status=429)
    with pytest.raises(RuntimeError, match="Open-Meteo"):
        fetch_weather(lat=38.9097, lon=-105.5666)
