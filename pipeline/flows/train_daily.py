"""Daily forecasting model training flow.

Builds the v1.0 daily forecast model: one feature vector per gauge per day,
labeled via the same flow_thresholds bootstrap as the hourly model. Registers
under MLflow model name 'riffle-condition-daily' to keep it isolated from the
existing hourly 'riffle-conditions' model.
"""

import pandas as pd
from prefect import flow, task

from config.rivers import GAUGES, get_thresholds
from shared.db_client import (
    get_gauge_id,
    get_recent_gauge_daily_readings,
    get_recent_weather_daily_readings,
)
from plugins.ml.train import label_condition, train_daily_model
from plugins.ml.score import promote_model_to_production
from plugins.features import build_daily_feature_vector

DAILY_MODEL_NAME = "riffle-condition-daily"


def _train_and_promote_daily():
    records = []
    for gauge_cfg in GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_daily_readings(gauge_id, days=730)
        weather_rows = get_recent_weather_daily_readings(gauge_id, days=730)

        weather_by_date = {r["observed_date"]: r for r in weather_rows}

        for row in gauge_rows:
            if not row["flow_cfs"]:
                continue
            target_date = row["observed_date"]
            weather = weather_by_date.get(target_date)
            if not weather:
                continue

            thresholds = get_thresholds(gauge_cfg, target_date.month)

            features = build_daily_feature_vector(
                flow_cfs=row["flow_cfs"],
                water_temp_f=row["water_temp_f"],
                air_temp_f_mean=weather["air_temp_f_mean"],
                air_temp_f_min=weather["air_temp_f_min"],
                air_temp_f_max=weather["air_temp_f_max"],
                precip_mm_sum=weather["precip_mm_sum"],
                snowfall_mm_sum=weather["snowfall_mm_sum"],
                wind_speed_mph_max=weather["wind_speed_mph_max"],
                target_date=target_date,
                weather_history_daily=weather_rows,
            )
            condition = label_condition(
                flow_cfs=row["flow_cfs"],
                water_temp_f=row["water_temp_f"] or 55.0,
                thresholds=thresholds,
                freezes=gauge_cfg.get("freezes", False),
                month=target_date.month,
            )
            features["observed_date"] = target_date
            features["condition"] = condition
            records.append(features)

    if not records:
        raise ValueError("No daily training records found — check gauge_readings_daily data")

    df = pd.DataFrame(records)
    _, run_id = train_daily_model(df, holdout_days=60)
    promote_model_to_production(run_id, model_name=DAILY_MODEL_NAME)


@task(retries=1, retry_delay_seconds=300)
def train_and_promote_daily_task():
    _train_and_promote_daily()


@flow(name="train-daily")
def train_daily_flow():
    train_and_promote_daily_task()
