"""Daily forecasting pipeline: ingest yesterday's data, then score today + 7
forecast days for each active gauge.

Structure: one flow, two tasks as a DAG. If ingest fails after all retries,
score is skipped automatically by Prefect's task dependency mechanism — we
never score stale data.

The ingest task retries on a 5m / 15m / 30m backoff so the 04:00 MT run has
roughly 45 minutes of slack for USGS to finalize yesterday's daily-mean row.
"""

from datetime import date, timedelta

from prefect import flow, task

from config.rivers import ACTIVE_GAUGES
from shared.db_client import (
    get_gauge_id,
    get_recent_gauge_daily_readings,
    get_recent_weather_daily_readings,
    upsert_weather_daily_reading,
    upsert_prediction_daily,
)
from shared.ingest_daily import ingest_gauge_daily, ingest_weather_daily
from shared.weather_client import fetch_weather_daily_forecast
from plugins.features import build_daily_feature_vector
from plugins.ml.score import load_production_model, predict_daily_condition


DAILY_MODEL_NAME = "riffle-condition-daily"
FORECAST_DAYS = 7


@task(
    name="ingest-daily",
    retries=3,
    retry_delay_seconds=[300, 900, 1800],  # 5m, 15m, 30m
)
def ingest_daily_task():
    """Fetch yesterday's daily gauge + weather data for every active gauge.

    Raises RuntimeError if zero gauges received a valid flow_cfs row — that
    indicates a real USGS outage worth retrying. Per-gauge missing-flow cases
    are logged and then handled gracefully by score_daily_task's existing
    "no recent flow_cfs — skipping" path.
    """
    yesterday = date.today() - timedelta(days=1)
    print(f"Ingesting daily data for {yesterday}")

    total_valid = 0
    total_gauges = 0
    for cfg in ACTIVE_GAUGES:
        name = cfg["name"]
        usgs_id = cfg["usgs_gauge_id"]
        gauge_id = get_gauge_id(usgs_id)

        ingest_weather_daily(
            gauge_id=gauge_id,
            lat=cfg["lat"],
            lon=cfg["lon"],
            start=yesterday,
            end=yesterday,
        )
        result = ingest_gauge_daily(
            gauge_id=gauge_id,
            usgs_id=usgs_id,
            start=yesterday,
            end=yesterday,
        )
        total_gauges += 1
        if result.valid_flow_rows > 0:
            total_valid += 1
            print(f"  {name} ({usgs_id}): {result.valid_flow_rows} valid flow rows")
        else:
            print(f"  {name} ({usgs_id}): no valid flow yet")

    print(f"\nIngest complete: {total_valid}/{total_gauges} gauges have valid flow_cfs for {yesterday}")

    if total_valid == 0:
        raise RuntimeError(
            f"no gauges received valid flow_cfs for {yesterday} — USGS may not have "
            "finalized yesterday's mean yet, triggering retry"
        )


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


@task(name="score-daily", retries=1, retry_delay_seconds=300)
def score_daily_task():
    _score_all()


@flow(name="daily-forecast")
def daily_forecast_flow():
    # Synchronous calls — if ingest_daily_task raises after all retries,
    # the exception propagates and score_daily_task never runs. No need
    # for explicit wait_for.
    ingest_daily_task()
    score_daily_task()
