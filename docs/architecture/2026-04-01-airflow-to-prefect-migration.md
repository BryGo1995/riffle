# Airflow → Prefect Migration

**Date:** 2026-04-01
**Branch merged:** `feat/airflow-to-prefect`

---

## Why We Migrated

The original design used Apache Airflow 2.9 for pipeline orchestration, which required three separate
Railway services: `airflow-init`, `airflow-scheduler`, and `airflow-webserver`. Combined with Postgres
and MLflow, that was 5 services total. Airflow also needed a second database (`airflow` alongside
`riffle`) and a shared `odds-pipeline_default` Docker network for cross-project coordination.

Prefect 3.x replaces all three Airflow services with a single long-lived process (`serve.py`) that:
- Registers both flow deployments with their cron schedules on startup
- Executes runs locally when the schedule fires
- Reports run history and status to Prefect Cloud (optional — works locally without it)

Result: **5 services → 4**, one database, no external network wiring, simpler Railway config.

---

## Files Changed

### Added
| File | Purpose |
|------|---------|
| `pipeline/flows/__init__.py` | Package marker |
| `pipeline/flows/ingest_score.py` | Prefect flow: hourly weather + gauge ingest → scoring |
| `pipeline/flows/train.py` | Prefect flow: weekly XGBoost training + MLflow promotion |
| `pipeline/serve.py` | Entrypoint — registers both deployments and starts the scheduler loop |
| `pipeline/Dockerfile` | Lightweight `python:3.11-slim` image replacing `docker/Dockerfile.airflow` |
| `pipeline/tests/test_flows.py` | 14 tests replacing `test_dags.py` |

### Modified
| File | What changed |
|------|-------------|
| `pipeline/requirements.txt` | Removed `apache-airflow==2.9.3` + providers; added `prefect>=3.0` |
| `docker-compose.yml` | Removed `x-airflow-common`, `airflow-init/scheduler/webserver` services, `airflow-logs` volume, `odds-pipeline_default` network; simplified Postgres to single `riffle` DB; added `prefect-worker` service |
| `.env.example` | Removed `AIRFLOW__*` vars; added `PREFECT_API_URL` and `PREFECT_API_KEY` |

### Deleted
| File | Reason |
|------|--------|
| `pipeline/dags/ingest_score_dag.py` | Replaced by `pipeline/flows/ingest_score.py` |
| `pipeline/dags/train_dag.py` | Replaced by `pipeline/flows/train.py` |
| `pipeline/tests/test_dags.py` | Replaced by `pipeline/tests/test_flows.py` |
| `docker/Dockerfile.airflow` | Replaced by `pipeline/Dockerfile` |

### Unchanged (business logic — intentionally untouched)
- `pipeline/plugins/` — ML logic (`train.py`, `score.py`, `features.py`)
- `pipeline/shared/` — data clients (`db_client.py`, `usgs_client.py`, `weather_client.py`)
- `pipeline/config/` — river/gauge registry
- `pipeline/sql/` — database schema
- All other `pipeline/tests/` files (test_score, test_train, test_features, test_db_client, etc.)

---

## Architecture: Before vs After

### Before (Airflow)

```
docker-compose services (5):
  postgres        — two databases: riffle + airflow
  mlflow          — experiment tracking
  api             — FastAPI
  airflow-init    — one-shot DB migration container
  airflow-scheduler + airflow-webserver (via x-airflow-common)

Scheduling:
  ingest_score_dag.py  @hourly   — fetch weather, fetch gauge, score in sequence
  train_dag.py         @weekly   — train XGBoost + promote to MLflow production

Retry config:
  default_args = {"retries": 2}  (blanket, no per-task delay)

DAG dependency:
  fetch_weather >> score  AND  fetch_gauge >> score
  (trigger_rule=ALL_DONE — score runs even if one ingest fails)
```

### After (Prefect)

```
docker-compose services (4):
  postgres        — one database: riffle
  mlflow          — experiment tracking
  api             — FastAPI
  prefect-worker  — single long-lived process running serve.py

Scheduling (serve.py):
  ingest_score_flow  cron="0 * * * *"   (hourly)
  train_flow         cron="0 9 * * 1"   (Monday 09:00 UTC / 03:00 AM MT)

Retry config (per-task, with explicit delays):
  fetch_weather_task     retries=2, retry_delay_seconds=60
  fetch_gauge_task       retries=2, retry_delay_seconds=60
  score_conditions_task  retries=1, retry_delay_seconds=120
  train_and_promote_task retries=1, retry_delay_seconds=300

Parallel ingest (equivalent to ALL_DONE trigger_rule):
  weather = fetch_weather_task.submit()
  gauge   = fetch_gauge_task.submit()
  weather.result(raise_on_failure=False)
  gauge.result(raise_on_failure=False)
  score_conditions_task()          # runs after both, regardless of failures
```

---

## Key Design Decisions

### serve.py as the single entrypoint

`prefect.serve()` starts an event loop that polls for scheduled runs and executes them in the same
process. This is the Prefect 3.x recommended approach for simple deployments — no separate worker
pool, no external queue. The Docker container just runs `python serve.py` and stays alive.

If Prefect Cloud credentials (`PREFECT_API_URL`, `PREFECT_API_KEY`) are provided, runs are visible
in the Cloud UI with full history and logs. If not set, Prefect falls back to a local ephemeral
SQLite-backed API — flows execute on schedule with no cloud dependency.

### ALL_DONE semantics preserved via raise_on_failure=False

The original Airflow DAG used `trigger_rule=ALL_DONE` on the scoring task so that scoring would run
even if the weather or gauge ingest failed (using whatever data was already in the DB). The Prefect
equivalent is `.submit()` + `.result(raise_on_failure=False)` — both futures are awaited without
raising, then scoring runs unconditionally. This preserves the fault-tolerant ingest behavior.

### Business logic untouched

All helper functions (`fetch_and_store_weather`, `fetch_and_store_readings`, `score_all_gauges`,
`_train_and_promote`) are direct copies of the callables that Airflow's `PythonOperator` was calling.
The only change is that they are now called by thin `@task`-decorated wrappers instead. This means
the existing unit tests for ML logic, feature engineering, and data clients needed no changes.

### Per-task retry delays

Airflow's `default_args = {"retries": 2}` applied a blanket retry count with no delay. The Prefect
version adds explicit `retry_delay_seconds` per task calibrated to the failure mode:
- Weather/gauge APIs: 60s delay — gives transient HTTP errors / rate limits time to clear
- Scoring: 120s delay — unlikely to fail transiently; one retry is conservative
- Training: 300s delay — weekly job, long-running; extra time before retrying

---

## Flow Structure

### `ingest_score_flow` (hourly)

```
ingest_score_flow()
  ├── fetch_weather_task.submit()   ─── parallel
  ├── fetch_gauge_task.submit()     ─── parallel
  ├── weather.result(raise_on_failure=False)   # wait + suppress errors
  ├── gauge.result(raise_on_failure=False)     # wait + suppress errors
  └── score_conditions_task()       ─── sequential, always runs
```

Internally:
- `fetch_weather_task` → iterates GAUGES, calls `fetch_weather_forecast()`, upserts via `upsert_weather_reading()`
- `fetch_gauge_task` → iterates GAUGES, calls `fetch_gauge_reading()`, upserts via `upsert_gauge_reading()`
- `score_conditions_task` → loads production XGBoost model from MLflow, builds feature vectors for
  each gauge's forecast hours, writes predictions via `upsert_prediction()`

### `train_flow` (weekly, Monday 09:00 UTC)

```
train_flow()
  └── train_and_promote_task()
        └── _train_and_promote()
              ├── Pull 365 days of gauge_readings + weather_readings per gauge
              ├── Join by hour bucket
              ├── build_feature_vector() per row
              ├── label_condition() per row (domain-knowledge thresholds)
              ├── train_model(df) → XGBoost booster + MLflow run_id
              └── promote_model_to_production(run_id)
```

---

## Docker Image

`pipeline/Dockerfile` uses `python:3.11-slim` (not the heavy `apache/airflow` base image):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
CMD ["python", "serve.py"]
```

The build context in `docker-compose.yml` is `./pipeline`, so `COPY . .` places all pipeline
contents at `/app`. `PYTHONPATH=/app` makes `from flows.*`, `from plugins.*`, `from shared.*`,
`from config.*` all resolve correctly without any `sys.path` manipulation.

---

## Testing

`pipeline/tests/test_flows.py` (14 tests) verifies the Prefect layer without touching business logic:

| Category | Tests |
|----------|-------|
| Flow type | `isinstance(ingest_score_flow, Flow)`, `isinstance(train_flow, Flow)` |
| Flow name | `ingest_score_flow.name == "ingest-score"`, `train_flow.name == "train"` |
| Task type | all 4 tasks are `isinstance(task, Task)` |
| Retry counts | fetch tasks retries=2, score/train tasks retries=1 |
| Deployment construction | `to_deployment(name=..., cron=...)` returns correct `.name` |

Full test suite: 63 tests (49 pre-existing + 14 new), all passing.

---

## Railway Deployment (post-merge)

1. **Remove** `airflow-init`, `airflow-scheduler`, `airflow-webserver` Railway services
2. **Update** Postgres plugin — drop the `airflow` database (only `riffle` needed now)
3. **Add** `prefect-worker` service: root directory `./pipeline`, auto-detects `pipeline/Dockerfile`
4. Set env vars on prefect-worker: `DATABASE_URL`, `MLFLOW_TRACKING_URI`, `PREFECT_API_URL`, `PREFECT_API_KEY`
5. **Prefect Cloud setup** (optional but recommended for observability):
   - Sign up at prefect.io (free tier)
   - Create a workspace, generate API key
   - Set `PREFECT_API_URL` and `PREFECT_API_KEY` in the Railway service
