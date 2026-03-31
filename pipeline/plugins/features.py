"""Feature engineering for Riffle ML model.

All features are computed per gauge per target date.
weather_history is a list of dicts with keys: date (datetime.date), precip_mm (float).
Sorted in any order is fine — functions sort internally.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def compute_precip_72h(weather_history: List[Dict], target_date: date) -> float:
    """Sum precipitation over the 3 days ending on target_date (inclusive)."""
    window = {target_date - timedelta(days=i) for i in range(3)}
    return sum(
        row["precip_mm"] for row in weather_history if row["date"] in window
    )


def compute_days_since_precip(
    weather_history: List[Dict],
    target_date: date,
    threshold_mm: float = 5.0,
    sentinel: int = 30,
) -> int:
    """Days since the most recent day with precip >= threshold_mm.

    Returns `sentinel` if no such event is found in weather_history.
    """
    events = [
        row["date"]
        for row in weather_history
        if row["precip_mm"] >= threshold_mm and row["date"] <= target_date
    ]
    if not events:
        return sentinel
    most_recent = max(events)
    return (target_date - most_recent).days


def build_feature_vector(
    flow_cfs: float,
    gauge_height_ft: float,
    water_temp_f: Optional[float],
    air_temp_f: float,
    precip_24h_mm: float,
    target_date: date,
    weather_history: List[Dict],
) -> Dict[str, Any]:
    """Build a single feature dict ready for XGBoost inference or training."""
    return {
        "flow_cfs": flow_cfs,
        "gauge_height_ft": gauge_height_ft,
        "water_temp_f": water_temp_f if water_temp_f is not None else 50.0,
        "precip_24h_mm": precip_24h_mm,
        "precip_72h_mm": compute_precip_72h(weather_history, target_date),
        "air_temp_f": air_temp_f,
        "day_of_year": target_date.timetuple().tm_yday,
        "days_since_precip_event": compute_days_since_precip(weather_history, target_date),
    }
