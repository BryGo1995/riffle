"""condition_score_dag — Daily at 7:30am MT (13:30 UTC).

Waits for gauge_ingest + weather_ingest to complete, then:
  1. Load production XGBoost model from MLflow
  2. Build feature vectors for today + 3 forecast days per gauge
  3. Run classification → write predictions to Postgres
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import date, datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.external_task import ExternalTaskSensor

from config.rivers import GAUGES
from shared.db_client import (
    get_gauge_id,
    get_recent_gauge_readings,
    get_recent_weather_readings,
    upsert_prediction,
)
from plugins.features import build_feature_vector
from plugins.ml.score import load_production_model, predict_condition

default_args = {"owner": "riffle", "retries": 1}


def score_all_gauges():
    booster = load_production_model()
    model_version = "production"
    today = date.today()

    for gauge_cfg in GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_readings(gauge_id, days=1)
        if not gauge_rows:
            continue

        latest = gauge_rows[0]
        weather_history = get_recent_weather_readings(gauge_id, days=90)

        # Score today + 3 forecast days
        forecast_weather = get_recent_weather_readings(gauge_id, days=4)
        for i, weather_row in enumerate(sorted(forecast_weather, key=lambda r: r["date"])):
            target_date = weather_row["date"]
            is_forecast = (target_date != today)
            features = build_feature_vector(
                flow_cfs=latest["flow_cfs"] or 0.0,
                gauge_height_ft=latest["gauge_height_ft"] or 0.0,
                water_temp_f=latest["water_temp_f"],
                air_temp_f=weather_row["air_temp_f"],
                precip_24h_mm=weather_row["precip_mm"],
                target_date=target_date,
                weather_history=weather_history,
            )
            condition, confidence = predict_condition(booster, features)
            upsert_prediction(
                gauge_id=gauge_id,
                date=target_date,
                condition=condition,
                confidence=confidence,
                is_forecast=is_forecast,
                model_version=model_version,
            )


with DAG(
    dag_id="condition_score",
    default_args=default_args,
    schedule_interval="30 13 * * *",  # 7:30am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ml"],
) as dag:
    wait_gauge = ExternalTaskSensor(
        task_id="wait_gauge_ingest",
        external_dag_id="gauge_ingest",
        external_task_id="fetch_and_store_readings",
        timeout=3600,
    )
    wait_weather = ExternalTaskSensor(
        task_id="wait_weather_ingest",
        external_dag_id="weather_ingest",
        external_task_id="fetch_and_store_weather",
        timeout=3600,
    )
    score_task = PythonOperator(
        task_id="score_gauges",
        python_callable=score_all_gauges,
    )
    [wait_gauge, wait_weather] >> score_task
