from prefect import serve

from flows.ingest_score import ingest_score_flow
from flows.train import train_flow

if __name__ == "__main__":
    serve(
        ingest_score_flow.to_deployment(
            name="ingest-score",
            cron="0 * * * *",        # hourly
        ),
        train_flow.to_deployment(
            name="train",
            cron="0 9 * * 1",        # Monday 9:00 UTC / 3:00 AM MT
        ),
    )
