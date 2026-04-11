"""Backfill daily-mean USGS readings and daily aggregated weather.

Replaces backfill_weather_gauge.py for the daily forecasting model. Uses the
USGS /collections/daily/items endpoint and Open-Meteo's daily archive — one
API call per gauge per source, no chunking required.

For 23 active gauges × 2 years, total wall time is well under 5 minutes.

Usage:
  python pipeline/scripts/backfill_daily.py
  python pipeline/scripts/backfill_daily.py --start 2023-01-01 --end 2025-12-31
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, "pipeline")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost:5434/riffle")

from config.rivers import ACTIVE_GAUGES
from shared.db_client import get_gauge_id
from shared.ingest_daily import ingest_gauge_daily, ingest_weather_daily


def main():
    parser = argparse.ArgumentParser(description="Backfill daily weather and gauge data")
    two_years_ago = (date.today() - timedelta(days=730)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    parser.add_argument("--start", default=two_years_ago, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=yesterday, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    total_gauges = len(ACTIVE_GAUGES)
    print(f"Backfilling {total_gauges} active gauges ({start} → {end})")

    for i, cfg in enumerate(ACTIVE_GAUGES, 1):
        name = cfg["name"]
        usgs_id = cfg["usgs_gauge_id"]
        print(f"\n[{i}/{total_gauges}] {name} ({usgs_id})")

        gauge_id = get_gauge_id(usgs_id)

        weather_count = ingest_weather_daily(gauge_id, cfg["lat"], cfg["lon"], start, end)
        print(f"  weather: {weather_count} days")

        gauge_result = ingest_gauge_daily(gauge_id, usgs_id, start, end)
        print(f"  gauge:   {gauge_result.rows_written} days ({gauge_result.valid_flow_rows} with flow)")

        # Small pace between gauges to be polite to USGS — single call so no rate limit pressure
        if i < total_gauges:
            time.sleep(1.0)

    print("\nDaily backfill complete.")


if __name__ == "__main__":
    main()
