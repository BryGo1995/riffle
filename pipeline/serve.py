"""Prefect deployment registrar for the riffle pipeline.

Uses Prefect 3's `serve()` mode: one long-running process polls the local
Prefect server for scheduled runs and executes them in-process. Suitable
for a single always-on dev box; production will migrate to work pools
(tracked by issue #5).

Three deployments:
  - daily-forecast:       ingest yesterday + score today + 7 days. 04:00 MT daily.
  - train-daily-forecast: retrain riffle-condition-daily. 03:00 MT every Sunday.
  - ingest-hourly:        collect USGS gauge + weather data every hour.

Timezones use America/Denver so the cron handles MST/MDT automatically.
"""

from prefect import serve
from prefect.schedules import Cron

from flows.daily_forecast import daily_forecast_flow
from flows.train_daily_forecast import train_daily_forecast_flow
from flows.ingest_hourly import ingest_hourly_flow


if __name__ == "__main__":
    serve(
        daily_forecast_flow.to_deployment(
            name="daily-forecast",
            schedule=Cron("0 4 * * *", timezone="America/Denver"),
        ),
        train_daily_forecast_flow.to_deployment(
            name="train-daily-forecast",
            schedule=Cron("0 3 * * 0", timezone="America/Denver"),
        ),
        ingest_hourly_flow.to_deployment(
            name="ingest-hourly",
            schedule=Cron("0 * * * *", timezone="America/Denver"),
        ),
    )
