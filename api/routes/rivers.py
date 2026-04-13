"""FastAPI route handlers for river/gauge endpoints.

GET /api/v1/rivers                         — all gauges with today's condition
GET /api/v1/rivers/{gauge_id}              — current condition + 3-day forecast
GET /api/v1/rivers/{gauge_id}/history      — last 30 days of conditions + key stats
"""

import os
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

router = APIRouter()

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(_get_engine()) as session:
        yield session


def get_today_predictions(session: Session) -> Dict[int, dict]:
    """Return {gauge_id: prediction_row} for today's predictions from the daily model."""
    rows = session.execute(
        text("""
            SELECT gauge_id, condition, confidence, is_forecast, model_version
            FROM predictions_daily
            WHERE target_date = CURRENT_DATE
        """)
    ).mappings().fetchall()
    return {r["gauge_id"]: dict(r) for r in rows if "gauge_id" in r}


def get_gauge_forecast(session: Session, gauge_id_int: int) -> List[dict]:
    """Return today + 7 forecast day predictions for a gauge from the daily model.

    Joins to weather_readings_daily so each day in the response includes the
    forecast precip and temp the prediction was based on.
    """
    rows = session.execute(
        text("""
            SELECT p.target_date, p.condition, p.confidence, p.is_forecast,
                   wd.precip_mm_sum, wd.air_temp_f_mean,
                   wd.air_temp_f_min, wd.air_temp_f_max
            FROM predictions_daily p
            LEFT JOIN weather_readings_daily wd
                ON wd.gauge_id = p.gauge_id
                AND wd.observed_date = p.target_date
            WHERE p.gauge_id = :gid
              AND p.target_date >= CURRENT_DATE
              AND p.target_date <= CURRENT_DATE + 7
            ORDER BY p.target_date
        """),
        {"gid": gauge_id_int},
    ).mappings().fetchall()
    return [dict(r) for r in rows]


def get_gauge_history(session: Session, gauge_id_int: int) -> List[dict]:
    """Return last 30 days of daily predictions joined with daily gauge stats."""
    rows = session.execute(
        text("""
            SELECT p.target_date, p.condition, p.confidence,
                   gd.flow_cfs, gd.water_temp_f
            FROM predictions_daily p
            LEFT JOIN gauge_readings_daily gd
                ON gd.gauge_id = p.gauge_id
                AND gd.observed_date = p.target_date
            WHERE p.gauge_id = :gid
              AND p.target_date >= CURRENT_DATE - 30
              AND p.is_forecast = FALSE
            ORDER BY p.target_date DESC
        """),
        {"gid": gauge_id_int},
    ).mappings().fetchall()
    return [dict(r) for r in rows]


@router.get("/rivers")
def list_rivers() -> List[Dict[str, Any]]:
    """Return all gauges with today's condition label."""
    with get_session() as session:
        gauges = session.execute(
            text("SELECT id, usgs_gauge_id, name, river, lat, lon FROM gauges WHERE visible = TRUE ORDER BY river, name")
        ).mappings().fetchall()
        predictions = get_today_predictions(session)

    result = []
    for g in gauges:
        pred = predictions.get(g["id"], {})
        result.append({
            "gauge_id": g["usgs_gauge_id"],
            "name": g["name"],
            "river": g["river"],
            "lat": g["lat"],
            "lon": g["lon"],
            "condition": pred.get("condition"),
            "confidence": pred.get("confidence"),
        })
    return result


@router.get("/rivers/{gauge_id}")
def get_river(gauge_id: str) -> Dict[str, Any]:
    """Return current snapshot + 7-day daily forecast for a single gauge."""
    with get_session() as session:
        gauge = session.execute(
            text("SELECT id, usgs_gauge_id, name, river, lat, lon FROM gauges WHERE usgs_gauge_id = :gid"),
            {"gid": gauge_id},
        ).mappings().fetchone()

        if not gauge:
            raise HTTPException(status_code=404, detail=f"Gauge {gauge_id} not found")

        latest_reading = session.execute(
            text("""
                SELECT flow_cfs, water_temp_f, observed_date
                FROM gauge_readings_daily
                WHERE gauge_id = :gid
                ORDER BY observed_date DESC
                LIMIT 1
            """),
            {"gid": gauge["id"]},
        ).mappings().fetchone()

        forecast = get_gauge_forecast(session, gauge["id"])

    return {
        "gauge_id": gauge["usgs_gauge_id"],
        "name": gauge["name"],
        "river": gauge["river"],
        "lat": gauge["lat"],
        "lon": gauge["lon"],
        "current": dict(latest_reading) if latest_reading else None,
        "forecast": [
            {
                "date": str(f["target_date"]),
                "condition": f["condition"],
                "confidence": f["confidence"],
                "is_forecast": f["is_forecast"],
                "precip_mm": f.get("precip_mm_sum"),
                "air_temp_f_mean": f.get("air_temp_f_mean"),
                "air_temp_f_min": f.get("air_temp_f_min"),
                "air_temp_f_max": f.get("air_temp_f_max"),
            }
            for f in forecast
        ],
        "usgs_url": f"https://waterdata.usgs.gov/monitoring-location/{gauge_id}/",
    }


@router.get("/rivers/{gauge_id}/history")
def get_river_history(gauge_id: str) -> Dict[str, Any]:
    """Return last 30 days of condition labels + key stats for a gauge."""
    with get_session() as session:
        gauge = session.execute(
            text("SELECT id, name, river FROM gauges WHERE usgs_gauge_id = :gid"),
            {"gid": gauge_id},
        ).mappings().fetchone()

        if not gauge:
            raise HTTPException(status_code=404, detail=f"Gauge {gauge_id} not found")

        history = get_gauge_history(session, gauge["id"])

    return {
        "gauge_id": gauge_id,
        "name": gauge["name"],
        "river": gauge["river"],
        "history": [
            {
                "date": str(h["target_date"]),
                "condition": h["condition"],
                "confidence": h["confidence"],
                "flow_cfs": h.get("flow_cfs"),
                "water_temp_f": h.get("water_temp_f"),
            }
            for h in history
        ],
    }
