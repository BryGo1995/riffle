"""Postgres helpers for Riffle.

Uses raw SQL via SQLAlchemy text() for clarity and portability.
"""

import os
from contextlib import contextmanager
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Generator, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        url = os.environ["DATABASE_URL"]
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(_get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_gauge_id(usgs_gauge_id: str) -> int:
    with get_session() as session:
        return session.execute(
            text("SELECT id FROM gauges WHERE usgs_gauge_id = :gid"),
            {"gid": usgs_gauge_id},
        ).scalar_one()


def upsert_gauge_reading(
    gauge_id: int,
    fetched_at: datetime,
    flow_cfs: Optional[float],
    water_temp_f: Optional[float],
    gauge_height_ft: Optional[float],
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO gauge_readings (gauge_id, fetched_at, flow_cfs, water_temp_f, gauge_height_ft)
                VALUES (:gauge_id, :fetched_at, :flow_cfs, :water_temp_f, :gauge_height_ft)
                ON CONFLICT (gauge_id, fetched_at) DO NOTHING
            """),
            {
                "gauge_id": gauge_id,
                "fetched_at": fetched_at,
                "flow_cfs": flow_cfs,
                "water_temp_f": water_temp_f,
                "gauge_height_ft": gauge_height_ft,
            },
        )


def upsert_weather_reading(
    gauge_id: int,
    observed_at: datetime,
    precip_mm: float,
    precip_probability: Optional[int],
    air_temp_f: float,
    snowfall_mm: float,
    wind_speed_mph: float,
    weather_code: int,
    cloud_cover_pct: int,
    surface_pressure_hpa: float,
    is_forecast: bool,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO weather_readings (
                    gauge_id, observed_at, precip_mm, precip_probability,
                    air_temp_f, snowfall_mm, wind_speed_mph, weather_code,
                    cloud_cover_pct, surface_pressure_hpa, is_forecast
                )
                VALUES (
                    :gauge_id, :observed_at, :precip_mm, :precip_probability,
                    :air_temp_f, :snowfall_mm, :wind_speed_mph, :weather_code,
                    :cloud_cover_pct, :surface_pressure_hpa, :is_forecast
                )
                ON CONFLICT (gauge_id, observed_at)
                DO UPDATE SET
                    precip_mm = EXCLUDED.precip_mm,
                    precip_probability = EXCLUDED.precip_probability,
                    air_temp_f = EXCLUDED.air_temp_f,
                    snowfall_mm = EXCLUDED.snowfall_mm,
                    wind_speed_mph = EXCLUDED.wind_speed_mph,
                    weather_code = EXCLUDED.weather_code,
                    cloud_cover_pct = EXCLUDED.cloud_cover_pct,
                    surface_pressure_hpa = EXCLUDED.surface_pressure_hpa,
                    is_forecast = EXCLUDED.is_forecast
            """),
            {
                "gauge_id": gauge_id,
                "observed_at": observed_at,
                "precip_mm": precip_mm,
                "precip_probability": precip_probability,
                "air_temp_f": air_temp_f,
                "snowfall_mm": snowfall_mm,
                "wind_speed_mph": wind_speed_mph,
                "weather_code": weather_code,
                "cloud_cover_pct": cloud_cover_pct,
                "surface_pressure_hpa": surface_pressure_hpa,
                "is_forecast": is_forecast,
            },
        )


def upsert_prediction(
    gauge_id: int,
    target_datetime: datetime,
    condition: str,
    confidence: float,
    is_forecast: bool,
    model_version: str,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO predictions (gauge_id, target_datetime, condition, confidence, is_forecast, model_version)
                VALUES (:gauge_id, :target_datetime, :condition, :confidence, :is_forecast, :model_version)
                ON CONFLICT (gauge_id, target_datetime)
                DO UPDATE SET
                    condition = EXCLUDED.condition,
                    confidence = EXCLUDED.confidence,
                    is_forecast = EXCLUDED.is_forecast,
                    model_version = EXCLUDED.model_version,
                    scored_at = NOW()
            """),
            {
                "gauge_id": gauge_id,
                "target_datetime": target_datetime,
                "condition": condition,
                "confidence": confidence,
                "is_forecast": is_forecast,
                "model_version": model_version,
            },
        )


def get_recent_gauge_readings(gauge_id: int, days: int = 90) -> List[dict]:
    """Returns rows for the last `days` days, newest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT fetched_at, flow_cfs, water_temp_f, gauge_height_ft
                FROM gauge_readings
                WHERE gauge_id = :gauge_id
                  AND fetched_at >= NOW() - (:days * INTERVAL '1 day')
                ORDER BY fetched_at DESC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_recent_weather_readings(gauge_id: int, hours: int = 2160) -> List[dict]:
    """Returns observed-only (is_forecast=FALSE) hourly rows for the last `hours` hours, newest first.

    Use get_forecast_weather() to retrieve upcoming forecast rows.
    Default 2160 hours = 90 days.
    """
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_at, precip_mm, precip_probability, air_temp_f,
                       snowfall_mm, wind_speed_mph, weather_code,
                       cloud_cover_pct, surface_pressure_hpa, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND observed_at >= NOW() - (:hours * INTERVAL '1 hour')
                  AND is_forecast = FALSE
                ORDER BY observed_at DESC
            """),
            {"gauge_id": gauge_id, "hours": hours},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_forecast_weather(gauge_id: int) -> List[dict]:
    """Returns current hour + all is_forecast=True rows in the next 72 hours, oldest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_at, precip_mm, precip_probability, air_temp_f,
                       snowfall_mm, wind_speed_mph, weather_code,
                       cloud_cover_pct, surface_pressure_hpa, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND observed_at >= DATE_TRUNC('hour', NOW())
                  AND observed_at <= NOW() + INTERVAL '72 hours'
                ORDER BY observed_at ASC
            """),
            {"gauge_id": gauge_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def upsert_gauge_daily_reading(
    gauge_id: int,
    observed_date: date_type,
    flow_cfs: Optional[float],
    water_temp_f: Optional[float],
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO gauge_readings_daily (gauge_id, observed_date, flow_cfs, water_temp_f)
                VALUES (:gauge_id, :observed_date, :flow_cfs, :water_temp_f)
                ON CONFLICT (gauge_id, observed_date)
                DO UPDATE SET
                    flow_cfs = EXCLUDED.flow_cfs,
                    water_temp_f = EXCLUDED.water_temp_f
            """),
            {
                "gauge_id": gauge_id,
                "observed_date": observed_date,
                "flow_cfs": flow_cfs,
                "water_temp_f": water_temp_f,
            },
        )


def upsert_weather_daily_reading(
    gauge_id: int,
    observed_date: date_type,
    precip_mm_sum: float,
    air_temp_f_mean: float,
    air_temp_f_min: float,
    air_temp_f_max: float,
    snowfall_mm_sum: float,
    wind_speed_mph_max: float,
    is_forecast: bool,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO weather_readings_daily (
                    gauge_id, observed_date, precip_mm_sum,
                    air_temp_f_mean, air_temp_f_min, air_temp_f_max,
                    snowfall_mm_sum, wind_speed_mph_max, is_forecast
                )
                VALUES (
                    :gauge_id, :observed_date, :precip_mm_sum,
                    :air_temp_f_mean, :air_temp_f_min, :air_temp_f_max,
                    :snowfall_mm_sum, :wind_speed_mph_max, :is_forecast
                )
                ON CONFLICT (gauge_id, observed_date)
                DO UPDATE SET
                    precip_mm_sum = EXCLUDED.precip_mm_sum,
                    air_temp_f_mean = EXCLUDED.air_temp_f_mean,
                    air_temp_f_min = EXCLUDED.air_temp_f_min,
                    air_temp_f_max = EXCLUDED.air_temp_f_max,
                    snowfall_mm_sum = EXCLUDED.snowfall_mm_sum,
                    wind_speed_mph_max = EXCLUDED.wind_speed_mph_max,
                    is_forecast = EXCLUDED.is_forecast
            """),
            {
                "gauge_id": gauge_id,
                "observed_date": observed_date,
                "precip_mm_sum": precip_mm_sum,
                "air_temp_f_mean": air_temp_f_mean,
                "air_temp_f_min": air_temp_f_min,
                "air_temp_f_max": air_temp_f_max,
                "snowfall_mm_sum": snowfall_mm_sum,
                "wind_speed_mph_max": wind_speed_mph_max,
                "is_forecast": is_forecast,
            },
        )


def upsert_prediction_daily(
    gauge_id: int,
    target_date: date_type,
    condition: str,
    confidence: float,
    is_forecast: bool,
    model_version: str,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO predictions_daily (gauge_id, target_date, condition, confidence, is_forecast, model_version)
                VALUES (:gauge_id, :target_date, :condition, :confidence, :is_forecast, :model_version)
                ON CONFLICT (gauge_id, target_date)
                DO UPDATE SET
                    condition = EXCLUDED.condition,
                    confidence = EXCLUDED.confidence,
                    is_forecast = EXCLUDED.is_forecast,
                    model_version = EXCLUDED.model_version,
                    scored_at = NOW()
            """),
            {
                "gauge_id": gauge_id,
                "target_date": target_date,
                "condition": condition,
                "confidence": confidence,
                "is_forecast": is_forecast,
                "model_version": model_version,
            },
        )


def get_recent_gauge_daily_readings(gauge_id: int, days: int = 730) -> List[dict]:
    """Returns daily rows for the last `days` days, oldest first.

    Oldest-first order makes downstream rolling computations (3-day precip
    sum, days-since-precip-event) cheaper.
    """
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_date, flow_cfs, water_temp_f
                FROM gauge_readings_daily
                WHERE gauge_id = :gauge_id
                  AND observed_date >= CURRENT_DATE - (:days * INTERVAL '1 day')
                ORDER BY observed_date ASC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_recent_weather_daily_readings(gauge_id: int, days: int = 730) -> List[dict]:
    """Returns observed-only daily weather rows for the last `days` days, oldest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_date, precip_mm_sum, air_temp_f_mean,
                       air_temp_f_min, air_temp_f_max, snowfall_mm_sum,
                       wind_speed_mph_max, is_forecast
                FROM weather_readings_daily
                WHERE gauge_id = :gauge_id
                  AND observed_date >= CURRENT_DATE - (:days * INTERVAL '1 day')
                  AND is_forecast = FALSE
                ORDER BY observed_date ASC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_forecast_weather_daily(gauge_id: int) -> List[dict]:
    """Returns is_forecast=True daily rows for today and the next 7 days, oldest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_date, precip_mm_sum, air_temp_f_mean,
                       air_temp_f_min, air_temp_f_max, snowfall_mm_sum,
                       wind_speed_mph_max, is_forecast
                FROM weather_readings_daily
                WHERE gauge_id = :gauge_id
                  AND observed_date >= CURRENT_DATE
                  AND observed_date <= CURRENT_DATE + INTERVAL '7 days'
                  AND is_forecast = TRUE
                ORDER BY observed_date ASC
            """),
            {"gauge_id": gauge_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_weather_for_hour(gauge_id: int, observed_at: datetime) -> Optional[dict]:
    """Returns the weather row closest to the given hour, within ±2 hours."""
    hour = observed_at.replace(minute=0, second=0, microsecond=0)
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT observed_at, precip_mm, precip_probability, air_temp_f,
                       snowfall_mm, wind_speed_mph, weather_code,
                       cloud_cover_pct, surface_pressure_hpa, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND observed_at BETWEEN :low AND :high
                ORDER BY ABS(EXTRACT(EPOCH FROM (observed_at - :target))) ASC
                LIMIT 1
            """),
            {
                "gauge_id": gauge_id,
                "low": hour - timedelta(hours=2),
                "high": hour + timedelta(hours=2),
                "target": hour,
            },
        ).fetchone()
    return dict(row._mapping) if row else None
