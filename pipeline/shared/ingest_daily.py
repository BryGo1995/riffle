"""Shared daily ingest core used by both the scheduled daily flow and the
one-shot backfill script.

Keeps "fetch + upsert N days for one gauge" logic in exactly one place so the
scheduled 04:00 run and a manual re-backfill produce identical rows.
"""

from dataclasses import dataclass
from datetime import date

from shared.usgs_client import fetch_gauge_daily_range
from shared.weather_client import fetch_weather_daily_archive
from shared.db_client import (
    upsert_gauge_daily_reading,
    upsert_weather_daily_reading,
)


@dataclass
class IngestResult:
    rows_written: int
    valid_flow_rows: int  # subset of rows_written where flow_cfs is not None


def ingest_gauge_daily(
    gauge_id: int,
    usgs_id: str,
    start: date,
    end: date,
) -> IngestResult:
    """Fetch USGS daily-mean flow/temp for [start, end] and upsert each row.

    Returns an IngestResult so callers can distinguish "rows arrived but USGS
    hasn't finalized yesterday's flow yet" from "rows arrived with valid flow".
    """
    readings = fetch_gauge_daily_range(usgs_id, start, end)
    valid = 0
    for r in readings:
        upsert_gauge_daily_reading(
            gauge_id=gauge_id,
            observed_date=r.observed_date,
            flow_cfs=r.flow_cfs,
            water_temp_f=r.water_temp_f,
        )
        if r.flow_cfs is not None:
            valid += 1
    return IngestResult(rows_written=len(readings), valid_flow_rows=valid)


def ingest_weather_daily(
    gauge_id: int,
    lat: float,
    lon: float,
    start: date,
    end: date,
) -> int:
    """Fetch Open-Meteo daily archive for [start, end] and upsert each day.

    Returns the number of days written. Weather archive is reliable enough
    that we don't track a separate "valid" count — if the fetch succeeds at
    all, the rows are usable.
    """
    days = fetch_weather_daily_archive(lat, lon, start, end)
    for d in days:
        upsert_weather_daily_reading(
            gauge_id=gauge_id,
            observed_date=d.observed_date,
            precip_mm_sum=d.precip_mm_sum,
            air_temp_f_mean=d.air_temp_f_mean,
            air_temp_f_min=d.air_temp_f_min,
            air_temp_f_max=d.air_temp_f_max,
            snowfall_mm_sum=d.snowfall_mm_sum,
            wind_speed_mph_max=d.wind_speed_mph_max,
            is_forecast=False,
        )
    return len(days)
