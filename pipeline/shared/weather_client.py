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
