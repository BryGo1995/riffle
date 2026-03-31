"""weather_ingest_dag — Daily at 7:05am MT (13:05 UTC).

For each gauge lat/lon:
  1. Fetch Open-Meteo current conditions + 3-day forecast
  2. Upsert into weather_readings table
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator

from config.rivers import GAUGES
from shared.weather_client import fetch_weather
from shared.db_client import get_gauge_id, upsert_weather_reading

default_args = {"owner": "riffle", "retries": 2}


def fetch_and_store_weather():
    for gauge_cfg in GAUGES:
        days = fetch_weather(lat=gauge_cfg["lat"], lon=gauge_cfg["lon"])
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        for day in days:
            upsert_weather_reading(
                gauge_id=gauge_id,
                date=day.date,
                precip_mm=day.precip_mm,
                air_temp_f=day.air_temp_f,
                is_forecast=day.is_forecast,
            )


with DAG(
    dag_id="weather_ingest",
    default_args=default_args,
    schedule_interval="5 13 * * *",  # 7:05am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ingest"],
) as dag:
    PythonOperator(
        task_id="fetch_and_store_weather",
        python_callable=fetch_and_store_weather,
    )
