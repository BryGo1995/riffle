"""Backfill historical weather and gauge readings.

Fetches 2 years of hourly data from Open-Meteo archive and USGS IV APIs.
Safe to re-run — all writes are idempotent upserts.

Usage:
  python pipeline/scripts/backfill_weather_gauge.py
  python pipeline/scripts/backfill_weather_gauge.py --start 2023-01-01 --end 2025-12-31
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, "pipeline")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost:5434/riffle")

from config.rivers import GAUGES
from shared.weather_client import fetch_weather_historical
from shared.usgs_client import fetch_gauge_reading_range
from shared.db_client import get_gauge_id, upsert_weather_reading, upsert_gauge_reading


def daterange_chunks(start: date, end: date, days: int):
    """Yield (chunk_start, chunk_end) tuples of at most `days` days."""
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def backfill_weather(gauge_id: int, lat: float, lon: float, start: date, end: date) -> int:
    total = 0
    for chunk_start, chunk_end in daterange_chunks(start, end, 180):
        print(f"    Weather {chunk_start} → {chunk_end}")
        hours = fetch_weather_historical(lat, lon, chunk_start, chunk_end)
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
                is_forecast=False,
            )
        total += len(hours)
        time.sleep(0.5)
    return total


def backfill_gauge(gauge_id: int, usgs_id: str, start: date, end: date) -> int:
    total = 0
    for chunk_start, chunk_end in daterange_chunks(start, end, 30):
        print(f"    Gauge {chunk_start} → {chunk_end}")
        readings = fetch_gauge_reading_range(usgs_id, chunk_start, chunk_end)
        for reading in readings:
            upsert_gauge_reading(
                gauge_id=gauge_id,
                fetched_at=reading.fetched_at,
                flow_cfs=reading.flow_cfs,
                water_temp_f=reading.water_temp_f,
                gauge_height_ft=reading.gauge_height_ft,
            )
        total += len(readings)
        time.sleep(0.5)
    return total


def main():
    parser = argparse.ArgumentParser(description="Backfill historical weather and gauge data")
    two_years_ago = (date.today() - timedelta(days=730)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    parser.add_argument("--start", default=two_years_ago, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=yesterday, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    total_gauges = len(GAUGES)

    print(f"Backfilling {start} → {end} for {total_gauges} gauges")

    for i, gauge_cfg in enumerate(GAUGES, 1):
        name = gauge_cfg["name"]
        usgs_id = gauge_cfg["usgs_gauge_id"]
        print(f"\n[{i}/{total_gauges}] {name} ({usgs_id})")

        gauge_id = get_gauge_id(usgs_id)

        weather_count = backfill_weather(gauge_id, gauge_cfg["lat"], gauge_cfg["lon"], start, end)
        gauge_count = backfill_gauge(gauge_id, usgs_id, start, end)

        print(f"  Done: {weather_count} weather rows, {gauge_count} gauge readings")

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
