# Airflow to Prefect Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Apache Airflow with Prefect as the pipeline orchestration layer, reducing Railway infrastructure from 5 services to 4 while keeping all scheduling, retry, and observability behavior intact.

**Architecture:** Both Airflow DAGs (`ingest_score` hourly, `train` weekly) are rewritten as Prefect flows. The business logic callables are unchanged — only the orchestration wrapper changes. A single `serve.py` entrypoint starts a long-lived process that registers both deployments with Prefect Cloud and executes scheduled runs locally, eliminating the need for a separate scheduler and webserver container.

**Tech Stack:** Prefect 3.x, Python 3.11, XGBoost, MLflow, Docker, docker-compose

---

## File Structure

**New files:**
- `pipeline/flows/__init__.py` — package marker
- `pipeline/flows/ingest_score.py` — Prefect flow: fetch weather, fetch gauge, score conditions (parallel ingest → score)
- `pipeline/flows/train.py` — Prefect flow: train XGBoost model and promote to MLflow production
- `pipeline/serve.py` — entry point; serves both flows with their cron schedules via `prefect.serve()`
- `pipeline/tests/test_flows.py` — replaces `test_dags.py`; verifies flow types, names, retry counts, and deployment construction
- `pipeline/Dockerfile` — lightweight `python:3.11-slim` image, replaces `docker/Dockerfile.airflow`

**Modified files:**
- `pipeline/requirements.txt` — remove `apache-airflow*`, add `prefect>=3.0`
- `docker-compose.yml` — remove `airflow-init/scheduler/webserver` services and `airflow-logs` volume; add `prefect-worker` service; simplify Postgres to single `riffle` DB
- `.env.example` — remove `AIRFLOW__*` variables; add `PREFECT_API_URL` and `PREFECT_API_KEY`

**Deleted files:**
- `pipeline/dags/ingest_score_dag.py`
- `pipeline/dags/train_dag.py`
- `pipeline/tests/test_dags.py`
- `docker/Dockerfile.airflow`

**Unchanged files (business logic — do not touch):**
- `pipeline/plugins/` — ML logic (`train.py`, `score.py`, `features.py`)
- `pipeline/shared/` — data clients (`db_client.py`, `usgs_client.py`, `weather_client.py`)
- `pipeline/config/` — river gauge registry
- All other `pipeline/tests/` files (test_score.py, test_train.py, test_features.py, etc.)

---

## Task 1: Update Requirements and Remove Stale Airflow Files

**Files:**
- Modify: `pipeline/requirements.txt`
- Delete: `pipeline/tests/test_dags.py`
- Delete: `docker/Dockerfile.airflow`

- [ ] **Step 1: Update pipeline/requirements.txt**

Replace the full contents with:

```
prefect>=3.0
xgboost==2.0.3
mlflow==2.12.1
scikit-learn==1.4.2
pandas==2.2.2
numpy==1.26.4
psycopg2-binary==2.9.9
requests==2.31.0
pytest==8.2.0
pytest-mock==3.14.0
responses==0.25.3
```

- [ ] **Step 2: Install updated dependencies**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pip install -r pipeline/requirements.txt
```

Expected: clean install, no Airflow packages, `prefect` installed.

- [ ] **Step 3: Delete stale test and Dockerfile**

```bash
rm pipeline/tests/test_dags.py
rm docker/Dockerfile.airflow
```

- [ ] **Step 4: Verify existing tests still pass (minus the deleted test_dags.py)**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/ -v --ignore=pipeline/tests/test_dags.py
```

Expected: all tests pass (test_score, test_train, test_features, test_db_client, test_usgs_client, test_weather_client, test_rivers).

- [ ] **Step 5: Commit**

```bash
git add pipeline/requirements.txt
git rm pipeline/tests/test_dags.py docker/Dockerfile.airflow
git commit -m "chore: remove airflow, add prefect to requirements"
```

---

## Task 2: Write Failing Tests for Prefect Flows

**Files:**
- Create: `pipeline/tests/test_flows.py`

- [ ] **Step 1: Create pipeline/tests/test_flows.py**

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
from prefect.flows import Flow
from prefect.tasks import Task

from flows.ingest_score import (
    ingest_score_flow,
    fetch_weather_task,
    fetch_gauge_task,
    score_conditions_task,
)
from flows.train import train_flow, train_and_promote_task


# --- Flow type and name ---

def test_ingest_score_is_prefect_flow():
    assert isinstance(ingest_score_flow, Flow)


def test_ingest_score_flow_name():
    assert ingest_score_flow.name == "ingest-score"


def test_train_is_prefect_flow():
    assert isinstance(train_flow, Flow)


def test_train_flow_name():
    assert train_flow.name == "train"


# --- Task types ---

def test_fetch_weather_is_prefect_task():
    assert isinstance(fetch_weather_task, Task)


def test_fetch_gauge_is_prefect_task():
    assert isinstance(fetch_gauge_task, Task)


def test_score_conditions_is_prefect_task():
    assert isinstance(score_conditions_task, Task)


def test_train_and_promote_is_prefect_task():
    assert isinstance(train_and_promote_task, Task)


# --- Retry configuration ---

def test_fetch_weather_task_retries():
    assert fetch_weather_task.retries == 2


def test_fetch_gauge_task_retries():
    assert fetch_gauge_task.retries == 2


def test_score_conditions_task_retries():
    assert score_conditions_task.retries == 1


def test_train_and_promote_task_retries():
    assert train_and_promote_task.retries == 1


# --- Deployment construction ---

def test_ingest_score_deployment_name():
    deployment = ingest_score_flow.to_deployment(name="ingest-score", cron="0 * * * *")
    assert deployment.name == "ingest-score"


def test_train_deployment_name():
    deployment = train_flow.to_deployment(name="train", cron="0 9 * * 1")
    assert deployment.name == "train"
```

- [ ] **Step 2: Run tests to confirm they fail with ModuleNotFoundError**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/test_flows.py -v
```

Expected: `ModuleNotFoundError: No module named 'flows'` — the flows package doesn't exist yet.

---

## Task 3: Create the Ingest/Score Flow

**Files:**
- Create: `pipeline/flows/__init__.py`
- Create: `pipeline/flows/ingest_score.py`

- [ ] **Step 1: Create the flows package**

```bash
mkdir -p pipeline/flows
touch pipeline/flows/__init__.py
```

- [ ] **Step 2: Create pipeline/flows/ingest_score.py**

```python
from datetime import datetime, timezone

from prefect import flow, task

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


@task(retries=2, retry_delay_seconds=60)
def fetch_weather_task():
    fetch_and_store_weather()


@task(retries=2, retry_delay_seconds=60)
def fetch_gauge_task():
    fetch_and_store_readings()


@task(retries=1, retry_delay_seconds=120)
def score_conditions_task():
    score_all_gauges()


@flow(name="ingest-score")
def ingest_score_flow():
    # Parallel ingest: equivalent to [fetch_weather, fetch_gauge] >> score_conditions
    # raise_on_failure=False preserves TriggerRule.ALL_DONE semantics:
    # scoring proceeds even if one ingest task fails, using latest data in DB.
    weather = fetch_weather_task.submit()
    gauge = fetch_gauge_task.submit()
    weather.result(raise_on_failure=False)
    gauge.result(raise_on_failure=False)
    score_conditions_task()
```

- [ ] **Step 3: Run ingest_score-related tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/test_flows.py -v -k "ingest_score or fetch_weather or fetch_gauge or score_conditions"
```

Expected: all 9 ingest_score tests pass.

---

## Task 4: Create the Train Flow

**Files:**
- Create: `pipeline/flows/train.py`

- [ ] **Step 1: Create pipeline/flows/train.py**

```python
import pandas as pd
from prefect import flow, task

from config.rivers import GAUGES
from shared.db_client import get_gauge_id, get_recent_gauge_readings, get_recent_weather_readings
from plugins.ml.train import label_condition, train_model
from plugins.ml.score import promote_model_to_production
from plugins.features import build_feature_vector


def _train_and_promote():
    records = []
    for gauge_cfg in GAUGES:
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
```

- [ ] **Step 2: Run full test_flows.py**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/test_flows.py -v
```

Expected: all 14 tests pass.

---

## Task 5: Create serve.py

**Files:**
- Create: `pipeline/serve.py`

- [ ] **Step 1: Create pipeline/serve.py**

```python
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
```

- [ ] **Step 2: Verify serve.py can be imported without errors**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
PYTHONPATH=pipeline python -c "
import sys
sys.path.insert(0, 'pipeline')
from flows.ingest_score import ingest_score_flow
from flows.train import train_flow
from prefect import serve
d1 = ingest_score_flow.to_deployment(name='ingest-score', cron='0 * * * *')
d2 = train_flow.to_deployment(name='train', cron='0 9 * * 1')
print('ingest deployment:', d1.name)
print('train deployment:', d2.name)
"
```

Expected output:
```
ingest deployment: ingest-score
train deployment: train
```

- [ ] **Step 3: Commit flows and serve.py**

```bash
git add pipeline/flows/ pipeline/serve.py
git commit -m "feat: add prefect flows and serve entrypoint replacing airflow DAGs"
```

---

## Task 6: Remove Old DAG Files, Run Full Test Suite

**Files:**
- Delete: `pipeline/dags/ingest_score_dag.py`
- Delete: `pipeline/dags/train_dag.py`
- Delete: `pipeline/dags/` directory

- [ ] **Step 1: Delete the dags directory**

```bash
git rm -r pipeline/dags/
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/ -v
```

Expected: all tests pass. Verify `test_flows.py` appears in the output and `test_dags.py` does not.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove airflow DAGs directory"
```

---

## Task 7: Create the Pipeline Dockerfile

**Files:**
- Create: `pipeline/Dockerfile`

- [ ] **Step 1: Create pipeline/Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

CMD ["python", "serve.py"]
```

The build context is `./pipeline`, so `COPY . .` puts all pipeline contents at `/app`. `ENV PYTHONPATH=/app` makes `from flows.*`, `from plugins.*`, `from shared.*`, `from config.*` all resolve correctly.

- [ ] **Step 2: Build the image to verify it compiles**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
docker build -t riffle-pipeline ./pipeline
```

Expected: image builds successfully. No errors on `pip install`. The `CMD` line should be visible at the end of the build output.

- [ ] **Step 3: Commit**

```bash
git add pipeline/Dockerfile
git commit -m "feat: add lightweight prefect worker Dockerfile"
```

---

## Task 8: Update docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

Changes from current:
- Remove `x-airflow-common` anchor
- Remove `airflow-init`, `airflow-scheduler`, `airflow-webserver` services
- Remove `airflow-logs` volume
- Simplify Postgres to a single `riffle` DB (drop `POSTGRES_MULTIPLE_DATABASES` and the `create-multiple-postgresql-databases.sh` mount)
- Remove `odds-pipeline_default` external network (cross-project Airflow wiring no longer needed locally)
- Add `prefect-worker` service

- [ ] **Step 1: Replace docker-compose.yml with the following**

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: riffle
      POSTGRES_PASSWORD: riffle
      POSTGRES_DB: riffle
    ports:
      - "5434:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./pipeline/sql/init_schema.sql:/docker-entrypoint-initdb.d/01_schema.sql
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "riffle"]
      interval: 5s
      retries: 5

  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.12.1
    command: >
      mlflow server
      --backend-store-uri postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      --default-artifact-root /mlflow/artifacts
      --host 0.0.0.0
      --port 5000
    ports:
      - "5000:5000"
    volumes:
      - mlflow-artifacts:/mlflow/artifacts
    depends_on:
      postgres:
        condition: service_healthy

  api:
    build:
      context: ./api
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      MLFLOW_TRACKING_URI: http://mlflow:5000
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy

  prefect-worker:
    build:
      context: ./pipeline
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      MLFLOW_TRACKING_URI: http://mlflow:5000
      PREFECT_API_URL: ${PREFECT_API_URL:-}
      PREFECT_API_KEY: ${PREFECT_API_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

volumes:
  postgres-data:
  mlflow-artifacts:
```

Note on `PREFECT_API_URL` and `PREFECT_API_KEY`: if not set in your `.env`, Prefect uses a local ephemeral SQLite-backed API. Flows will execute on schedule but the Prefect Cloud UI won't be connected. Set both vars for full cloud observability.

- [ ] **Step 2: Validate the compose file**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
docker-compose config
```

Expected: valid YAML printed to stdout with 4 services (postgres, mlflow, api, prefect-worker). No errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: replace airflow services with prefect-worker in docker-compose"
```

---

## Task 9: Update .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Replace .env.example with the following**

```
# Postgres
POSTGRES_USER=riffle
POSTGRES_PASSWORD=riffle
POSTGRES_DB=riffle
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# MLflow
MLFLOW_TRACKING_URI=http://mlflow:5000

# API / Pipeline
DATABASE_URL=postgresql+psycopg2://riffle:riffle@postgres:5432/riffle

# Prefect (optional for local dev — leave blank to use local ephemeral API)
# For Railway production: set to your Prefect Cloud workspace values
PREFECT_API_URL=
PREFECT_API_KEY=
```

- [ ] **Step 2: Run the full test suite one final time**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/ -v
```

Expected: all tests pass. Output should include `test_flows.py` with 14 tests and no reference to `test_dags.py`.

- [ ] **Step 3: Final commit**

```bash
git add .env.example
git commit -m "chore: update env example for prefect, remove airflow vars"
```

---

## Post-Migration: Railway Deployment Notes

These steps happen in the Railway dashboard, not in code:

1. **PostgreSQL**: Add the Railway Postgres plugin to the project. Note the auto-generated `DATABASE_URL`.
2. **MLflow service**: Add a new service, point it at `./pipeline` with `pipeline/Dockerfile`... wait, no — MLflow uses `ghcr.io/mlflow/mlflow:v2.12.1` as its image. Add a new Railway service, set the Docker image to `ghcr.io/mlflow/mlflow:v2.12.1`, set the start command to `mlflow server --backend-store-uri $DATABASE_URL --default-artifact-root /mlflow/artifacts --host 0.0.0.0 --port 5000`, and add a Railway volume mounted at `/mlflow/artifacts`. Keep MLflow internal (no public domain).
3. **API service**: Add a new Railway service pointing at the GitHub repo, root directory `./api`. Set `DATABASE_URL` (reference Postgres plugin) and `MLFLOW_TRACKING_URI=http://mlflow.railway.internal:5000`. Expose on a public domain.
4. **Prefect worker service**: Add a new Railway service pointing at the GitHub repo, root directory `./pipeline`. Set `DATABASE_URL`, `MLFLOW_TRACKING_URI=http://mlflow.railway.internal:5000`, `PREFECT_API_URL`, and `PREFECT_API_KEY`. No public domain needed.
5. **Schema init**: After first deploy, run `railway run python pipeline/scripts/seed_db.py` to seed the gauges table.
6. **Prefect Cloud**: Sign up at prefect.io (free), create a workspace, generate an API key. Set `PREFECT_API_URL` and `PREFECT_API_KEY` in the Railway prefect-worker service environment.
