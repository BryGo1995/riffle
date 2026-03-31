"""ingest_score_dag — Hourly.

Parallel ingest:
  fetch_weather  ──┐
                   ├──> score_conditions
  fetch_gauge    ──┘

score_conditions uses TriggerRule.ALL_DONE so scoring proceeds
even if one ingest fails, using the most recent data in the DB.
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime, timezone
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from config.rivers import GAUGES
from shared.weather_client import fetch_weather_forecast
from shared.usgs_client import fetch_gauge_reading
from shared.db_client import (
    get_gauge_id,
    upsert_weather_reading,
    upsert_gauge_reading,
    get_recent_gauge_readings,
    get_recent_weather_readings,
    get_forecast_weather,
    upsert_prediction,
)
from plugins.features import build_feature_vector
from plugins.ml.score import load_production_model, predict_condition

default_args = {"owner": "riffle", "retries": 2}


def fetch_and_store_weather():
    for gauge_cfg in GAUGES:
        hours = fetch_weather_forecast(lat=gauge_cfg["lat"], lon=gauge_cfg["lon"])
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        for hour in hours:
            upsert_weather_reading(
                gauge_id=gauge_id,
                observed_at=hour.observed_at,
                precip_mm=hour.precip_mm,
                precip_probability=hour.precip_probability,
                air_temp_f=hour.air_temp_f,
                snowfall_mm=hour.snowfall_mm,
                wind_speed_mph=hour.wind_speed_mph,
                weather_code=hour.weather_code,
                cloud_cover_pct=hour.cloud_cover_pct,
                surface_pressure_hpa=hour.surface_pressure_hpa,
                is_forecast=hour.is_forecast,
            )


def fetch_and_store_readings():
    fetched_at = datetime.now(tz=timezone.utc)
    for gauge_cfg in GAUGES:
        usgs_id = gauge_cfg["usgs_gauge_id"]
        reading = fetch_gauge_reading(usgs_id)
        gauge_id = get_gauge_id(usgs_id)
        upsert_gauge_reading(
            gauge_id=gauge_id,
            fetched_at=fetched_at,
            flow_cfs=reading.flow_cfs,
            water_temp_f=reading.water_temp_f,
            gauge_height_ft=reading.gauge_height_ft,
        )


def score_all_gauges():
    booster = load_production_model()
    model_version = "production"

    for gauge_cfg in GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_readings(gauge_id, days=1)
        if not gauge_rows:
            continue

        latest = gauge_rows[0]
        weather_history = get_recent_weather_readings(gauge_id, hours=2160)
        forecast_weather = get_forecast_weather(gauge_id)

        for weather_row in forecast_weather:
            target_datetime = weather_row["observed_at"]
            features = build_feature_vector(
                flow_cfs=latest["flow_cfs"] or 0.0,
                gauge_height_ft=latest["gauge_height_ft"] or 0.0,
                water_temp_f=latest["water_temp_f"],
                air_temp_f=weather_row["air_temp_f"],
                precip_24h_mm=weather_row["precip_mm"],
                target_datetime=target_datetime,
                weather_history=weather_history,
                precip_probability=weather_row["precip_probability"],
                snowfall_mm=weather_row["snowfall_mm"],
                wind_speed_mph=weather_row["wind_speed_mph"],
                weather_code=weather_row["weather_code"],
                cloud_cover_pct=weather_row["cloud_cover_pct"],
                surface_pressure_hpa=weather_row["surface_pressure_hpa"],
            )
            condition, confidence = predict_condition(booster, features)
            upsert_prediction(
                gauge_id=gauge_id,
                target_datetime=target_datetime,
                condition=condition,
                confidence=confidence,
                is_forecast=weather_row["is_forecast"],
                model_version=model_version,
            )


with DAG(
    dag_id="ingest_score",
    default_args=default_args,
    schedule_interval="0 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ingest", "ml"],
) as dag:
    fetch_weather_task = PythonOperator(
        task_id="fetch_weather",
        python_callable=fetch_and_store_weather,
    )
    fetch_gauge_task = PythonOperator(
        task_id="fetch_gauge",
        python_callable=fetch_and_store_readings,
    )
    score_task = PythonOperator(
        task_id="score_conditions",
        python_callable=score_all_gauges,
        trigger_rule=TriggerRule.ALL_DONE,
    )
    [fetch_weather_task, fetch_gauge_task] >> score_task
