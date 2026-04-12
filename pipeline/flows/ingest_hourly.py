# pipeline/flows/ingest_hourly.py
"""Hourly data-collection flow — USGS gauge readings + weather forecasts.

Collects raw hourly data for all active gauges and stores it in the
gauge_readings and weather_readings tables.  No scoring or model work.
"""

from datetime import datetime, timezone

from prefect import flow, task

from config.rivers import GAUGES
from shared.usgs_client import fetch_gauge_reading
from shared.weather_client import fetch_weather_forecast
from shared.db_client import get_gauge_id, upsert_gauge_reading, upsert_weather_reading


@task(retries=2, retry_delay_seconds=60)
def fetch_gauge_readings():
    """Fetch latest USGS readings for every gauge."""
    fetched_at = datetime.now(tz=timezone.utc)
    for gauge_cfg in GAUGES:
        usgs_id = gauge_cfg["usgs_gauge_id"]
        reading = fetch_gauge_reading(usgs_id)
        gauge_id = get_gauge_id(usgs_id)
        upsert_gauge_reading(
            gauge_id=gauge_id,
            fetched_at=fetched_at,
            flow_cfs=reading.flow_cfs,
            water_temp_f=reading.water_temp_f,
            gauge_height_ft=reading.gauge_height_ft,
        )


@task(retries=2, retry_delay_seconds=60)
def fetch_weather_readings():
    """Fetch hourly weather forecast for every gauge."""
    for gauge_cfg in GAUGES:
        hours = fetch_weather_forecast(lat=gauge_cfg["lat"], lon=gauge_cfg["lon"])
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        for hour in hours:
            upsert_weather_reading(
                gauge_id=gauge_id,
                observed_at=hour.observed_at,
                precip_mm=hour.precip_mm,
                precip_probability=hour.precip_probability,
                air_temp_f=hour.air_temp_f,
                snowfall_mm=hour.snowfall_mm,
                wind_speed_mph=hour.wind_speed_mph,
                weather_code=hour.weather_code,
                cloud_cover_pct=hour.cloud_cover_pct,
                surface_pressure_hpa=hour.surface_pressure_hpa,
                is_forecast=hour.is_forecast,
            )


@flow(name="ingest-hourly")
def ingest_hourly_flow():
    """Collect USGS gauge + weather data in parallel."""
    gauge = fetch_gauge_readings.submit()
    weather = fetch_weather_readings.submit()
    gauge.result(raise_on_failure=False)
    weather.result(raise_on_failure=False)
