"""Prefect deployment registrar for the riffle pipeline.

Uses Prefect 3's `serve()` mode: one long-running process polls the local
Prefect server for scheduled runs and executes them in-process. Suitable
for a single always-on dev box; production will migrate to work pools
(tracked by issue #5).

Four deployments:
  - daily-forecast: ingest yesterday + score today + 7 days. 04:00 MT daily.
  - train-daily:    retrain riffle-condition-daily. 03:00 MT every Sunday.
  - ingest-score-hourly: hourly ingest + score for the hourly model (PAUSED,
      deferred to v1.1 per PR #11).
  - train-hourly:   weekly retrain for the hourly model (PAUSED, same reason).

Timezones use America/Denver so the cron handles MST/MDT automatically.
"""

from prefect import serve
from prefect.schedules import Cron

from flows.daily_forecast import daily_forecast_flow
from flows.train_daily import train_daily_flow
from flows.ingest_score import ingest_score_flow
from flows.train import train_flow


if __name__ == "__main__":
    serve(
        daily_forecast_flow.to_deployment(
            name="daily-forecast",
            schedule=Cron("0 4 * * *", timezone="America/Denver"),
        ),
        train_daily_flow.to_deployment(
            name="train-daily",
            schedule=Cron("0 3 * * 0", timezone="America/Denver"),
        ),
        ingest_score_flow.to_deployment(
            name="ingest-score-hourly",
            schedule=Cron("0 * * * *"),
            paused=True,
        ),
        train_flow.to_deployment(
            name="train-hourly",
            schedule=Cron("0 9 * * 1"),
            paused=True,
        ),
    )
