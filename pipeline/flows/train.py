import pandas as pd
from prefect import flow, task

from config.rivers import ACTIVE_GAUGES
from shared.db_client import get_gauge_id, get_recent_gauge_readings, get_recent_weather_readings
from plugins.ml.train import label_condition, train_model
from plugins.ml.score import promote_model_to_production
from plugins.features import build_feature_vector


def _train_and_promote():
    records = []
    for gauge_cfg in ACTIVE_GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_readings(gauge_id, days=365)
        weather_rows = get_recent_weather_readings(gauge_id, hours=365 * 24)

        weather_by_hour = {
            r["observed_at"].replace(minute=0, second=0, microsecond=0): r
            for r in weather_rows
        }

        thresholds = gauge_cfg["flow_thresholds"]
        flow_values = [r["flow_cfs"] for r in gauge_rows if r["flow_cfs"]]
        seasonal_median = float(pd.Series(flow_values).median()) if flow_values else 200.0

        for row in gauge_rows:
            if not row["flow_cfs"]:
                continue
            target_datetime = row["fetched_at"].replace(minute=0, second=0, microsecond=0)
            weather = weather_by_hour.get(target_datetime)
            if not weather:
                continue
            features = build_feature_vector(
                flow_cfs=row["flow_cfs"],
                gauge_height_ft=row["gauge_height_ft"] or 0.0,
                water_temp_f=row["water_temp_f"],
                air_temp_f=weather["air_temp_f"],
                precip_24h_mm=weather["precip_mm"],
                target_datetime=target_datetime,
                weather_history=weather_rows,
                precip_probability=weather.get("precip_probability"),
                snowfall_mm=weather.get("snowfall_mm", 0.0),
                wind_speed_mph=weather.get("wind_speed_mph", 0.0),
                weather_code=weather.get("weather_code", 0),
                cloud_cover_pct=weather.get("cloud_cover_pct", 0),
                surface_pressure_hpa=weather.get("surface_pressure_hpa", 1013.25),
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


@task(retries=1, retry_delay_seconds=300)
def train_and_promote_task():
    _train_and_promote()


@flow(name="train")
def train_flow():
    train_and_promote_task()
