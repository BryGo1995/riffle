"""train_dag — Weekly, Monday 3:00am MT (9:00 UTC).

1. Pull historical gauge_readings + weather_readings from Postgres
2. Join on gauge_id + date
3. Generate bootstrapped labels from domain thresholds
4. Train XGBoost classifier, log to MLflow
5. Promote best model to production in MLflow registry
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime
import pandas as pd
from airflow import DAG
from airflow.operators.python import PythonOperator

from config.rivers import GAUGES
from shared.db_client import get_gauge_id, get_recent_gauge_readings, get_recent_weather_readings
from plugins.ml.train import label_condition, train_model, FEATURE_COLS
from plugins.ml.score import promote_model_to_production
from plugins.features import build_feature_vector

default_args = {"owner": "riffle", "retries": 1}


def train_and_promote():
    records = []
    for gauge_cfg in GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_readings(gauge_id, days=365)
        weather_rows = get_recent_weather_readings(gauge_id, days=365)
        weather_by_date = {r["date"]: r for r in weather_rows}

        thresholds = gauge_cfg["flow_thresholds"]
        flow_values = [r["flow_cfs"] for r in gauge_rows if r["flow_cfs"]]
        seasonal_median = float(pd.Series(flow_values).median()) if flow_values else 200.0

        for row in gauge_rows:
            if not row["flow_cfs"]:
                continue
            target_date = row["fetched_at"].date()
            weather = weather_by_date.get(target_date)
            if not weather:
                continue
            features = build_feature_vector(
                flow_cfs=row["flow_cfs"],
                gauge_height_ft=row["gauge_height_ft"] or 0.0,
                water_temp_f=row["water_temp_f"],
                air_temp_f=weather["air_temp_f"],
                precip_24h_mm=weather["precip_mm"],
                target_date=target_date,
                weather_history=weather_rows,
            )
            condition = label_condition(
                flow_cfs=row["flow_cfs"],
                water_temp_f=row["water_temp_f"] or 55.0,
                seasonal_median=seasonal_median,
                thresholds=thresholds,
            )
            features["condition"] = condition
            records.append(features)

    if not records:
        raise ValueError("No training records found — check gauge_readings data")

    df = pd.DataFrame(records)
    _, run_id = train_model(df)
    promote_model_to_production(run_id)


with DAG(
    dag_id="train",
    default_args=default_args,
    schedule_interval="0 9 * * 1",  # Monday 3:00am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ml", "training"],
) as dag:
    PythonOperator(
        task_id="train_and_promote",
        python_callable=train_and_promote,
    )
