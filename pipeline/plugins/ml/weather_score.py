"""Rule-based weather-only condition scorer for inactive gauges.

Used when a gauge has active=False in config, meaning no USGS gauge
readings are available. Derives a fishing condition label from weather
data only. Returns lower confidence than the ML model (capped at 0.75)
to signal this is a weather-only estimate.

Condition priority: Blown Out > Poor > Fair > Good > Excellent
"""

from typing import Tuple


def score_weather_only(
    air_temp_f: float,
    precip_mm: float,
    precip_probability: int,
    snowfall_mm: float,
    wind_speed_mph: float,
) -> Tuple[str, float]:
    """Return (condition, confidence) derived from weather data only.

    Confidence is capped at 0.75 — lower than ML predictions — to make
    clear this is a weather-only estimate with no gauge flow data.
    """
    # Blown Out: extreme precipitation
    if precip_mm > 20 or (precip_probability >= 80 and precip_mm > 10):
        return "Blown Out", 0.75

    # Poor: heavy precip, freezing temps, or significant snowfall
    if (
        precip_probability > 60
        or precip_mm > 8
        or snowfall_mm > 3
        or air_temp_f < 34
        or air_temp_f > 88
    ):
        return "Poor", 0.65

    # Fair: moderate precip or marginal temperatures
    if precip_probability > 35 or precip_mm > 3 or air_temp_f < 42 or air_temp_f > 80:
        return "Fair", 0.60

    # Excellent: ideal temps, clear skies
    if 48 <= air_temp_f <= 68 and precip_probability <= 15 and snowfall_mm == 0:
        return "Excellent", 0.55

    # Good: decent conditions that don't meet the excellent threshold
    return "Good", 0.55
