"""Open-Meteo forecast client.

Fetches today's conditions + 3-day forecast for a lat/lon.
Returns 4 WeatherDay objects: index 0 is today (is_forecast=False),
indices 1-3 are forecast days (is_forecast=True).
"""

from dataclasses import dataclass
from datetime import date
from typing import List
import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class WeatherDay:
    date: date
    precip_mm: float
    air_temp_f: float
    is_forecast: bool


def fetch_weather(lat: float, lon: float) -> List[WeatherDay]:
    """Fetch today + 3-day forecast from Open-Meteo.

    Raises RuntimeError on non-2xx HTTP response.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max",
        "forecast_days": 4,
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo API returned {resp.status_code}")

    try:
        daily = resp.json()["daily"]
        time_data = daily["time"]
        precip_data = daily["precipitation_sum"]
        temp_data = daily["temperature_2m_max"]
    except KeyError as e:
        raise RuntimeError(
            f"Open-Meteo API response missing expected key: {e}. "
            "Ensure API schema includes 'time', 'precipitation_sum', and 'temperature_2m_max'."
        )

    days = []
    for i, (dt_str, precip, temp) in enumerate(
        zip(time_data, precip_data, temp_data)
    ):
        days.append(
            WeatherDay(
                date=date.fromisoformat(dt_str),
                precip_mm=precip or 0.0,
                air_temp_f=temp if temp is not None else 0.0,
                is_forecast=(i > 0),
            )
        )
    return days
