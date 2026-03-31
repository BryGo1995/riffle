"""gauge_ingest_dag — Daily at 7:00am MT (13:00 UTC).

For each gauge in the registry:
  1. Fetch latest USGS reading (flow, temp, gauge height)
  2. Upsert into gauge_readings table
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime, timezone
from airflow import DAG
from airflow.operators.python import PythonOperator

from config.rivers import GAUGES
from shared.usgs_client import fetch_gauge_reading
from shared.db_client import get_gauge_id, upsert_gauge_reading

default_args = {"owner": "riffle", "retries": 2}


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


with DAG(
    dag_id="gauge_ingest",
    default_args=default_args,
    schedule_interval="0 13 * * *",  # 7:00am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ingest"],
) as dag:
    PythonOperator(
        task_id="fetch_and_store_readings",
        python_callable=fetch_and_store_readings,
    )
