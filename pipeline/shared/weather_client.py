"""Open-Meteo weather client — forecast and historical.

fetch_weather_forecast: current hour + 72h forecast from Open-Meteo forecast API.
fetch_weather_historical: hourly historical data from Open-Meteo archive API.
"""

from dataclasses import dataclass
from datetime import datetime
from datetime import date as date_type
from typing import List, Optional
from zoneinfo import ZoneInfo
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MT = ZoneInfo("America/Denver")

HOURLY_VARS = (
    "precipitation,precipitation_probability,temperature_2m,"
    "snowfall,wind_speed_10m,weather_code,cloud_cover,surface_pressure"
)
HISTORICAL_VARS = (
    "precipitation,temperature_2m,snowfall,wind_speed_10m,"
    "weather_code,cloud_cover,surface_pressure"
)
DAILY_VARS = (
    "precipitation_sum,temperature_2m_mean,temperature_2m_min,"
    "temperature_2m_max,snowfall_sum,wind_speed_10m_max"
)


@dataclass
class WeatherHour:
    observed_at: datetime
    precip_mm: float
    precip_probability: Optional[int]
    air_temp_f: float
    snowfall_mm: float
    wind_speed_mph: float
    weather_code: int
    cloud_cover_pct: int
    surface_pressure_hpa: float
    is_forecast: bool


@dataclass
class WeatherDay:
    observed_date: date_type
    precip_mm_sum: float
    air_temp_f_mean: float
    air_temp_f_min: float
    air_temp_f_max: float
    snowfall_mm_sum: float
    wind_speed_mph_max: float
    is_forecast: bool


def _parse_hourly(data: dict, has_precip_prob: bool) -> List[WeatherHour]:
    h = data["hourly"]
    times = h["time"]
    hours = []
    for i, t in enumerate(times):
        observed_at = datetime.fromisoformat(t).replace(tzinfo=MT)
        hours.append(WeatherHour(
            observed_at=observed_at,
            precip_mm=h["precipitation"][i] or 0.0,
            precip_probability=h["precipitation_probability"][i] if has_precip_prob else None,
            air_temp_f=h["temperature_2m"][i] if h["temperature_2m"][i] is not None else 0.0,
            snowfall_mm=h["snowfall"][i] or 0.0,
            wind_speed_mph=h["wind_speed_10m"][i] or 0.0,
            weather_code=int(h["weather_code"][i]) if h["weather_code"][i] is not None else 0,
            cloud_cover_pct=int(h["cloud_cover"][i]) if h["cloud_cover"][i] is not None else 0,
            surface_pressure_hpa=h["surface_pressure"][i] or 1013.25,
            is_forecast=(i > 0),
        ))
    return hours


def fetch_weather_forecast(lat: float, lon: float) -> List[WeatherHour]:
    """Fetch current hour + 72h forecast. First row is current (is_forecast=False)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_VARS,
        "forecast_hours": 73,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo forecast API returned {resp.status_code}")
    try:
        return _parse_hourly(resp.json(), has_precip_prob=True)
    except KeyError as e:
        raise RuntimeError(f"Open-Meteo forecast response missing key: {e}")


def fetch_weather_historical(
    lat: float,
    lon: float,
    start_date: date_type,
    end_date: date_type,
) -> List[WeatherHour]:
    """Fetch hourly historical data. precip_probability is None for all rows."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HISTORICAL_VARS,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo archive API returned {resp.status_code}")
    try:
        hours = _parse_hourly(resp.json(), has_precip_prob=False)
        # All historical rows are observed, not forecast
        for h in hours:
            h.is_forecast = False
        return hours
    except KeyError as e:
        raise RuntimeError(f"Open-Meteo archive response missing key: {e}")


def _parse_daily(data: dict, is_forecast: bool) -> List[WeatherDay]:
    d = data["daily"]
    times = d["time"]
    days = []
    for i, t in enumerate(times):
        days.append(WeatherDay(
            observed_date=date_type.fromisoformat(t),
            precip_mm_sum=d["precipitation_sum"][i] or 0.0,
            air_temp_f_mean=d["temperature_2m_mean"][i] if d["temperature_2m_mean"][i] is not None else 0.0,
            air_temp_f_min=d["temperature_2m_min"][i] if d["temperature_2m_min"][i] is not None else 0.0,
            air_temp_f_max=d["temperature_2m_max"][i] if d["temperature_2m_max"][i] is not None else 0.0,
            snowfall_mm_sum=d["snowfall_sum"][i] or 0.0,
            wind_speed_mph_max=d["wind_speed_10m_max"][i] or 0.0,
            is_forecast=is_forecast,
        ))
    return days


def fetch_weather_daily_archive(
    lat: float,
    lon: float,
    start_date: date_type,
    end_date: date_type,
) -> List[WeatherDay]:
    """Fetch daily aggregated historical weather from Open-Meteo's archive API.

    One call covers any reasonable date range — the archive happily returns
    multi-year ranges in a single response. No chunking required.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo daily archive returned {resp.status_code}")
    try:
        return _parse_daily(resp.json(), is_forecast=False)
    except KeyError as e:
        raise RuntimeError(f"Open-Meteo daily archive response missing key: {e}")


def fetch_weather_daily_forecast(lat: float, lon: float, days: int = 7) -> List[WeatherDay]:
    """Fetch a daily-resolution forecast (next N days) from Open-Meteo.

    Used by the daily prediction flow to score 7 days ahead.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "forecast_days": days,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo daily forecast returned {resp.status_code}")
    try:
        return _parse_daily(resp.json(), is_forecast=True)
    except KeyError as e:
        raise RuntimeError(f"Open-Meteo daily forecast response missing key: {e}")
