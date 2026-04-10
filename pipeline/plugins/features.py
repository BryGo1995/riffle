"""Feature engineering for Riffle ML model.

Two feature builders:
- build_feature_vector: hourly features for the v1.1 hourly diurnal model.
- build_daily_feature_vector: daily features for the v1.0 forecasting model.

weather_history (hourly) is a list of dicts with key: observed_at (datetime), precip_mm (float).
weather_history_daily is a list of dicts with key: observed_date (date), precip_mm_sum (float).
"""

from collections import defaultdict
from datetime import date as date_type, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


def compute_precip_72h(weather_history: List[Dict], target_datetime: datetime) -> float:
    """Sum precipitation over the 72 hours ending at target_datetime (inclusive)."""
    cutoff = target_datetime - timedelta(hours=72)
    return sum(
        row["precip_mm"] for row in weather_history
        if cutoff <= row["observed_at"] <= target_datetime
    )


def compute_days_since_precip(
    weather_history: List[Dict],
    target_datetime: datetime,
    threshold_mm: float = 5.0,
    sentinel: int = 30,
) -> int:
    """Days since last day whose cumulative hourly precip >= threshold_mm."""
    daily_totals: Dict = defaultdict(float)
    for row in weather_history:
        daily_totals[row["observed_at"].astimezone(ZoneInfo("America/Denver")).date()] += row["precip_mm"]

    target_date = target_datetime.astimezone(ZoneInfo("America/Denver")).date()
    events = [d for d, total in daily_totals.items() if total >= threshold_mm and d <= target_date]
    if not events:
        return sentinel
    return (target_date - max(events)).days


def build_feature_vector(
    flow_cfs: float,
    gauge_height_ft: float,
    water_temp_f: Optional[float],
    air_temp_f: float,
    precip_24h_mm: float,
    target_datetime: datetime,
    weather_history: List[Dict],
    precip_probability: Optional[int] = None,
    snowfall_mm: float = 0.0,
    wind_speed_mph: float = 0.0,
    weather_code: int = 0,
    cloud_cover_pct: int = 0,
    surface_pressure_hpa: float = 1013.25,
) -> Dict[str, Any]:
    """Build a single feature dict for XGBoost inference or training."""
    return {
        "flow_cfs": flow_cfs,
        "gauge_height_ft": gauge_height_ft,
        "water_temp_f": water_temp_f if water_temp_f is not None else 50.0,
        "precip_24h_mm": precip_24h_mm,
        "precip_72h_mm": compute_precip_72h(weather_history, target_datetime),
        "air_temp_f": air_temp_f,
        "day_of_year": target_datetime.timetuple().tm_yday,
        "hour_of_day": target_datetime.hour,
        "days_since_precip_event": compute_days_since_precip(weather_history, target_datetime),
        "precip_probability": precip_probability if precip_probability is not None else 0,
        "snowfall_mm": snowfall_mm,
        "wind_speed_mph": wind_speed_mph,
        "weather_code": weather_code,
        "cloud_cover_pct": cloud_cover_pct,
        "surface_pressure_hpa": surface_pressure_hpa,
    }


def compute_precip_3day_daily(
    weather_history_daily: List[Dict],
    target_date: date_type,
) -> float:
    """Sum daily precipitation totals over the 3 days ending at target_date (inclusive)."""
    cutoff = target_date - timedelta(days=2)
    return sum(
        row["precip_mm_sum"] for row in weather_history_daily
        if cutoff <= row["observed_date"] <= target_date
    )


def compute_days_since_precip_daily(
    weather_history_daily: List[Dict],
    target_date: date_type,
    threshold_mm: float = 5.0,
    sentinel: int = 30,
) -> int:
    """Days since the most recent day whose precip_mm_sum >= threshold_mm."""
    events = [
        row["observed_date"] for row in weather_history_daily
        if row["precip_mm_sum"] >= threshold_mm and row["observed_date"] <= target_date
    ]
    if not events:
        return sentinel
    return (target_date - max(events)).days


def build_daily_feature_vector(
    flow_cfs: float,
    water_temp_f: Optional[float],
    air_temp_f_mean: float,
    air_temp_f_min: float,
    air_temp_f_max: float,
    precip_mm_sum: float,
    snowfall_mm_sum: float,
    wind_speed_mph_max: float,
    target_date: date_type,
    weather_history_daily: List[Dict],
) -> Dict[str, Any]:
    """Build a single daily feature dict for the daily forecasting model."""
    return {
        "flow_cfs": flow_cfs,
        "water_temp_f": water_temp_f if water_temp_f is not None else 50.0,
        "air_temp_f_mean": air_temp_f_mean,
        "air_temp_f_min": air_temp_f_min,
        "air_temp_f_max": air_temp_f_max,
        "precip_day_mm": precip_mm_sum,
        "precip_3day_mm": compute_precip_3day_daily(weather_history_daily, target_date),
        "snowfall_mm": snowfall_mm_sum,
        "wind_speed_mph_max": wind_speed_mph_max,
        "day_of_year": target_date.timetuple().tm_yday,
        "days_since_precip_event": compute_days_since_precip_daily(weather_history_daily, target_date),
    }
