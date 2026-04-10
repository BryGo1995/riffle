"""Daily scoring flow.

Runs once per day. For each active gauge:
1. Loads daily history for context features (3-day precip rolling sum, etc.)
2. Pulls a 7-day daily weather forecast from Open-Meteo
3. Builds a feature vector for today + each of the next 7 days, holding
   flow_cfs and water_temp_f at their most recently observed values
4. Scores against the daily model and upserts predictions_daily

This is a v1.0 scoring approach: future flow_cfs is held constant from the
latest observation. A future iteration can layer a flow projection on top.
"""

from datetime import date, timedelta

from prefect import flow, task

from config.rivers import ACTIVE_GAUGES
from shared.weather_client import fetch_weather_daily_forecast
from shared.db_client import (
    get_gauge_id,
    get_recent_gauge_daily_readings,
    get_recent_weather_daily_readings,
    upsert_weather_daily_reading,
    upsert_prediction_daily,
)
from plugins.features import build_daily_feature_vector
from plugins.ml.score import load_production_model, predict_daily_condition

DAILY_MODEL_NAME = "riffle-condition-daily"
FORECAST_DAYS = 7


def _score_one_gauge(model, gauge_cfg: dict) -> int:
    """Score today + 7 forecast days for one gauge. Returns rows written."""
    gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
    history = get_recent_gauge_daily_readings(gauge_id, days=730)
    weather_history = get_recent_weather_daily_readings(gauge_id, days=730)

    if not history:
        print(f"  no daily history — skipping")
        return 0

    latest = history[-1]
    latest_flow = latest["flow_cfs"]
    latest_temp = latest["water_temp_f"]
    if latest_flow is None:
        print(f"  no recent flow_cfs — skipping")
        return 0

    forecast_days = fetch_weather_daily_forecast(
        lat=gauge_cfg["lat"],
        lon=gauge_cfg["lon"],
        days=FORECAST_DAYS + 1,  # include today
    )

    # Persist forecast weather rows so the API can re-read them and so the
    # next daily score has more context for the rolling-window features.
    for d in forecast_days:
        upsert_weather_daily_reading(
            gauge_id=gauge_id,
            observed_date=d.observed_date,
            precip_mm_sum=d.precip_mm_sum,
            air_temp_f_mean=d.air_temp_f_mean,
            air_temp_f_min=d.air_temp_f_min,
            air_temp_f_max=d.air_temp_f_max,
            snowfall_mm_sum=d.snowfall_mm_sum,
            wind_speed_mph_max=d.wind_speed_mph_max,
            is_forecast=True,
        )

    model_version = "daily-v1"
    written = 0
    today = date.today()

    # Combine observed history with forecast for the rolling-window context.
    forecast_as_dicts = [
        {
            "observed_date": d.observed_date,
            "precip_mm_sum": d.precip_mm_sum,
            "air_temp_f_mean": d.air_temp_f_mean,
            "air_temp_f_min": d.air_temp_f_min,
            "air_temp_f_max": d.air_temp_f_max,
            "snowfall_mm_sum": d.snowfall_mm_sum,
            "wind_speed_mph_max": d.wind_speed_mph_max,
            "is_forecast": True,
        }
        for d in forecast_days
    ]
    combined_weather = weather_history + forecast_as_dicts

    for d in forecast_days:
        target_date = d.observed_date
        is_forecast = target_date > today

        features = build_daily_feature_vector(
            flow_cfs=latest_flow,
            water_temp_f=latest_temp,
            air_temp_f_mean=d.air_temp_f_mean,
            air_temp_f_min=d.air_temp_f_min,
            air_temp_f_max=d.air_temp_f_max,
            precip_mm_sum=d.precip_mm_sum,
            snowfall_mm_sum=d.snowfall_mm_sum,
            wind_speed_mph_max=d.wind_speed_mph_max,
            target_date=target_date,
            weather_history_daily=combined_weather,
        )

        condition, confidence = predict_daily_condition(model, features)
        upsert_prediction_daily(
            gauge_id=gauge_id,
            target_date=target_date,
            condition=condition,
            confidence=confidence,
            is_forecast=is_forecast,
            model_version=model_version,
        )
        written += 1

    return written


def _score_all():
    model = load_production_model(model_name=DAILY_MODEL_NAME)
    total = 0
    for cfg in ACTIVE_GAUGES:
        print(f"Scoring {cfg['name']} ({cfg['usgs_gauge_id']})")
        total += _score_one_gauge(model, cfg)
    print(f"\nWrote {total} daily predictions across {len(ACTIVE_GAUGES)} gauges")


@task(retries=1, retry_delay_seconds=300)
def score_daily_task():
    _score_all()


@flow(name="score-daily")
def score_daily_flow():
    score_daily_task()
