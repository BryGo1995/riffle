"""Postgres helpers for Riffle.

Uses raw SQL via SQLAlchemy text() for clarity and portability.
Call get_session() as a context manager for each operation.
"""

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Generator, List, Optional, Tuple

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
    date: date,
    precip_mm: float,
    air_temp_f: float,
    is_forecast: bool,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO weather_readings (gauge_id, date, precip_mm, air_temp_f, is_forecast)
                VALUES (:gauge_id, :date, :precip_mm, :air_temp_f, :is_forecast)
                ON CONFLICT (gauge_id, date)
                DO UPDATE SET precip_mm = EXCLUDED.precip_mm,
                              air_temp_f = EXCLUDED.air_temp_f,
                              is_forecast = EXCLUDED.is_forecast
            """),
            {
                "gauge_id": gauge_id,
                "date": date,
                "precip_mm": precip_mm,
                "air_temp_f": air_temp_f,
                "is_forecast": is_forecast,
            },
        )


def upsert_prediction(
    gauge_id: int,
    date: date,
    condition: str,
    confidence: float,
    is_forecast: bool,
    model_version: str,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO predictions (gauge_id, date, condition, confidence, is_forecast, model_version)
                VALUES (:gauge_id, :date, :condition, :confidence, :is_forecast, :model_version)
                ON CONFLICT (gauge_id, date)
                DO UPDATE SET condition = EXCLUDED.condition,
                              confidence = EXCLUDED.confidence,
                              is_forecast = EXCLUDED.is_forecast,
                              model_version = EXCLUDED.model_version,
                              scored_at = NOW()
            """),
            {
                "gauge_id": gauge_id,
                "date": date,
                "condition": condition,
                "confidence": confidence,
                "is_forecast": is_forecast,
                "model_version": model_version,
            },
        )


def get_recent_gauge_readings(gauge_id: int, days: int = 90) -> List[dict]:
    """Returns up to `days` most recent rows, newest first."""
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


def get_recent_weather_readings(gauge_id: int, days: int = 90) -> List[dict]:
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT date, precip_mm, air_temp_f, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND date >= CURRENT_DATE - :days
                ORDER BY date DESC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]
