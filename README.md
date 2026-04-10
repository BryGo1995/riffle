# Riffle — Colorado Fly Fishing Conditions

Real-time USGS stream gauge conditions + XGBoost-powered 3-day fishing forecasts
for Colorado rivers, surfaced on an interactive Next.js map.

## Architecture

```
                         daily_forecast_flow (04:00 MT)
USGS API ──► ingest_daily_task ──► gauge_readings_daily (Postgres)
                                            │
Open-Meteo ──► ingest_daily_task ──► weather_readings_daily (Postgres)
                                            │
                               score_daily_task ──► predictions_daily (Postgres)

                         train_daily_flow (Sunday 03:00 MT)
                         gauge+weather history ──► XGBoost ──► MLflow registry

                                     FastAPI :8000
                                            │
                                   Next.js (Vercel)
```

Orchestrated by **Prefect 3.x** — a `prefect-server` container hosts the API + UI on `:4200`,
and a `prefect-serve` container runs `serve.py` to register deployments and execute scheduled
runs. The hourly pipeline (`ingest-score-hourly`, `train-hourly`) is registered but **paused**
— deferred to v1.1.

## Quick Start

```bash
cp .env.example .env
docker compose up -d
python pipeline/scripts/seed_db.py   # one-time gauge seed
```

The `prefect-serve` container registers deployments with the bundled Prefect server and begins
executing scheduled runs automatically. To trigger a run immediately, see
[Manually trigger a run](#manually-trigger-a-run) in the Scheduled Pipelines section below.

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
| Prefect UI | http://localhost:4200 | Self-hosted — no auth; do not expose to public internet |

> **Port notes:** Postgres runs on 5434 (5432/5433 occupied by other instances). Next.js dev
> server on 3001 (3000 used by Grafana).

## Scheduled Pipelines

The pipeline runs on a self-hosted Prefect server inside the compose stack. No Prefect Cloud account needed.

### Start the stack

```bash
docker compose up -d
```

This brings up postgres, mlflow, api, **prefect-server**, and **prefect-serve**. The Prefect serve process automatically registers four deployments with the server on first start.

### Open the Prefect UI

Point a browser at `http://localhost:4200` (or `http://<box-hostname>:4200` from another device on your LAN). The UI is unauthenticated — **do not expose port 4200 to the public internet**.

### Deployments

| Deployment | Schedule | Status |
|---|---|---|
| `daily-forecast` | 04:00 America/Denver daily | active |
| `train-daily` | 03:00 America/Denver every Sunday | active |
| `ingest-score-hourly` | every hour | **paused** (hourly model deferred to v1.1) |
| `train-hourly` | Mondays 09:00 UTC | **paused** (same reason) |

`daily-forecast` is a single flow containing two tasks: `ingest-daily` (fetches yesterday's USGS + Open-Meteo data for every active gauge, with 3 retries on a 5m/15m/30m backoff) and `score-daily` (scores today + 7 forecast days against `riffle-condition-daily`). If ingest fails after all retries, score is skipped automatically.

### Manually trigger a run

UI → **Deployments** → three-dot menu on a row → **Quick run**. Useful for testing without waiting for the cron.

From inside the container:

```bash
docker exec -it riffle-prefect-serve-1 prefect deployment run daily-forecast/daily-forecast
```

From your host shell (note the explicit `PREFECT_API_URL` — the internal DNS name doesn't resolve here):

```bash
PREFECT_API_URL=http://localhost:4200/api prefect deployment run daily-forecast/daily-forecast
```

### Pause or resume a schedule

UI → **Deployments** → toggle the schedule switch on the deployment row. State persists in the Prefect SQLite DB across restarts.

### View logs

UI → **Flow Runs** → click a run → **Logs** tab.

Container stdout (same log stream):

```bash
docker logs -f riffle-prefect-serve-1
docker logs -f riffle-prefect-server-1
```

### Reset run history (nuclear option)

```bash
docker compose down
docker volume rm riffle_prefect-data
docker compose up -d
```

Only needed if the Prefect SQLite DB gets corrupted or you want a fresh slate. Deployments re-register on next startup.

### Troubleshooting

- **Deployments missing from the UI after `docker compose up`:** `prefect-serve` probably couldn't talk to `prefect-server` yet. `docker logs riffle-prefect-serve-1` will show the connection error. Usually resolves on the next restart thanks to the health-gated `depends_on`, but worth checking.
- **`daily-forecast` failing at 04:00 with "no gauges received valid flow_cfs":** USGS was late finalizing yesterday's daily-mean row. The retry policy (`[5m, 15m, 30m]`) gives the run ~45 minutes of slack. If this happens repeatedly, tune the cron to a later time in `pipeline/serve.py`.
- **`prefect` CLI from the host shell errors with DNS / "name or service not known":** You need to set `PREFECT_API_URL=http://localhost:4200/api` explicitly in that shell. The compose-level default `http://prefect-server:4200/api` is only valid inside the Docker network.

### One-time host setup (Fedora 43)

Fedora does not enable the Docker daemon at boot by default. Without this, `restart: unless-stopped` only applies while Docker is already running — after a host reboot the containers stay down until someone manually starts Docker.

```bash
systemctl is-enabled docker
# If it returns "disabled":
sudo systemctl enable --now docker
```

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
pytest pipeline/tests/ api/tests/ -v   # 90 tests
```
