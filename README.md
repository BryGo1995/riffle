# Riffle — Colorado Fly Fishing Conditions

Real-time USGS stream gauge conditions + XGBoost-powered 3-day fishing forecasts
for Colorado rivers, surfaced on an interactive Next.js map.

## Architecture

````
USGS API ──► gauge_ingest_dag ──► gauge_readings (Postgres)
                                           │
Open-Meteo ──► weather_ingest_dag ──► weather_readings (Postgres)
                                           │
                               condition_score_dag ──► predictions (Postgres)
                               train_dag (weekly) ──► MLflow model registry
                                           │
                                      FastAPI :8000
                                           │
                                   Next.js (Vercel)
````

## Quick Start

```bash
cp .env.example .env          # fill in AIRFLOW__CORE__FERNET_KEY
docker-compose up -d
python pipeline/scripts/seed_db.py   # one-time gauge seed

# Trigger initial pipeline run
docker-compose exec airflow-scheduler airflow dags trigger gauge_ingest
docker-compose exec airflow-scheduler airflow dags trigger weather_ingest
# (wait ~30s for both to complete)
docker-compose exec airflow-scheduler airflow dags trigger condition_score

# Frontend
cd web && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Services

| Service | URL | Credentials |
|---------|-----|-------------|
| Airflow | http://localhost:8082 | admin / admin |
| MLflow | http://localhost:5000 | — |
| API | http://localhost:8000 | — |
| API docs | http://localhost:8000/docs | — |
| Frontend (dev) | http://localhost:3001 | — |

> **Port notes:** Airflow runs on 8082 (8080 occupied by another stack). Next.js dev server runs on 3001 (`npm run dev -- -p 3001`) since 3000 is used by Grafana.

## Data Sources

- **[USGS Water Services API](https://waterservices.usgs.gov/)** — Real-time stream gauge readings (flow, water temperature, gauge height) for 11 Colorado monitoring locations
- **[Open-Meteo](https://open-meteo.com/)** — Free weather forecast API providing current conditions and 3-day precipitation/temperature forecasts

## Stack

- **Pipeline:** Apache Airflow 2.9, XGBoost, MLflow, Python 3.11
- **API:** FastAPI, SQLAlchemy, PostgreSQL 15
- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, Leaflet.js
- **Deploy:** Docker Compose (local/Railway), Vercel (frontend)
