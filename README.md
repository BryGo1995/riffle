# Riffle — Colorado Fly Fishing Conditions

Real-time USGS stream gauge conditions + XGBoost-powered 3-day fishing forecasts
for Colorado rivers, surfaced on an interactive Next.js map.

## Architecture

```
USGS API ──► fetch_gauge_task ──► gauge_readings (Postgres)
                                          │
Open-Meteo ──► fetch_weather_task ──► weather_readings (Postgres)
                    (parallel)                │
                                  score_conditions_task ──► predictions (Postgres)
                                  train_flow (weekly) ──────► MLflow model registry
                                          │
                                     FastAPI :8000
                                          │
                                  Next.js (Vercel)
```

Orchestrated by **Prefect 3.x** — a single `prefect-worker` container runs `serve.py`, which
registers both flow deployments with their cron schedules and executes runs locally.

## Quick Start

```bash
cp .env.example .env
docker-compose up -d
python pipeline/scripts/seed_db.py   # one-time gauge seed
```

The `prefect-worker` container will begin executing the `ingest-score` flow on its hourly schedule
automatically. To trigger a run immediately:

```bash
# Requires PREFECT_API_URL + PREFECT_API_KEY set in .env (Prefect Cloud)
prefect deployment run ingest-score/ingest-score

# Or run the flow directly for local testing
PYTHONPATH=pipeline python -c "
from flows.ingest_score import ingest_score_flow
ingest_score_flow()
"
```

```bash
# Frontend
cd web && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Services

| Service | URL | Notes |
|---------|-----|-------|
| MLflow | http://localhost:5000 | Experiment tracking + model registry |
| API | http://localhost:8000 | FastAPI |
| API docs | http://localhost:8000/docs | |
| Frontend (dev) | http://localhost:3001 | `npm run dev -- -p 3001` |
| Prefect Cloud UI | https://app.prefect.cloud | Optional — set `PREFECT_API_URL` + `PREFECT_API_KEY` |

> **Port notes:** Postgres runs on 5434 (5432/5433 occupied by other instances). Next.js dev
> server on 3001 (3000 used by Grafana).

## Pipeline Flows

### `ingest-score` — hourly

Fetches weather forecast and gauge readings in parallel, then scores conditions for all gauges:

```
fetch_weather_task  ─┐  (retries=2, delay=60s)
fetch_gauge_task    ─┤  (retries=2, delay=60s)  ──► score_conditions_task  (retries=1)
         (parallel)  ┘      raise_on_failure=False → scoring always runs
```

### `train` — Monday 09:00 UTC (03:00 AM MT)

Pulls 365 days of gauge + weather history, trains XGBoost classifier, promotes best model to
MLflow production registry. (`retries=1, delay=300s`)

## Data Sources

- **[USGS Water Services API](https://waterservices.usgs.gov/)** — Real-time stream gauge readings
  (flow, water temperature, gauge height) for 11 Colorado monitoring locations. No API key required.
- **[Open-Meteo](https://open-meteo.com/)** — Free weather forecast API providing current conditions
  and 3-day precipitation/temperature forecasts per lat/lon. No API key required.

## Stack

- **Pipeline:** Prefect 3.x, XGBoost, MLflow, Python 3.11
- **API:** FastAPI, SQLAlchemy, PostgreSQL 15
- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, Leaflet.js
- **Deploy:** Docker Compose (local/Railway), Vercel (frontend)

## Tests

```bash
PYTHONPATH=pipeline pytest pipeline/tests/ -v   # 63 tests
```
