"""Feature engineering for Riffle ML model.

All features computed per gauge per target datetime (hourly).
weather_history is a list of dicts with key: observed_at (datetime), precip_mm (float).
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


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
        daily_totals[row["observed_at"].date()] += row["precip_mm"]

    target_date = target_datetime.date()
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
