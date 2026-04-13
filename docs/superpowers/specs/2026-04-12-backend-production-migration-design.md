# Backend Production Migration Design

**Date:** 2026-04-12
**Status:** Draft
**Scope:** Backend services only (API, pipeline worker, database). Frontend deployment to Vercel is out of scope.

---

## Target Architecture

```
Railway Project ("riffle")
├── api          — FastAPI, scale-to-zero (10min idle), auto-deploy on push to main
├── worker       — Prefect 3.x worker, connects to Prefect Cloud, runs daily/weekly flows
└── postgres     — Railway managed plugin, internal networking

External Services
├── Prefect Cloud (free tier)  — orchestration, scheduling, failure notifications
├── Cloudflare R2 (free tier)  — model artifact storage (S3-compatible)
└── GitHub                     — source repo, auto-deploy trigger
```

### Service Communication

- `api` → `postgres` via Railway internal DNS (`postgres.railway.internal`)
- `worker` → `postgres` via same internal DNS
- `worker` → Prefect Cloud via HTTPS (API key auth)
- `worker` → Cloudflare R2 via S3-compatible API (writes model after retrain)
- `worker` scoring task → R2 (reads model artifact before scoring)
- External users → `api` via Railway's public URL

### What's NOT Deployed to Production

- **MLflow** — local dev only for experiment tracking
- **Prefect server** — replaced by Prefect Cloud
- **Frontend** — separate Vercel deploy, not in scope

---

## Database & Schema Management

**Database:** Railway managed PostgreSQL (internal networking, no public exposure).

### Initial Deployment

1. Run `init_schema.sql` to create all 8 tables
2. Run `seed_db.py` to populate the `gauges` table with the 11 Colorado monitoring locations
3. Backfill historical data by running the ingest flows against USGS/Open-Meteo archives

### Schema Migrations

- Add Alembic to the pipeline package
- Baseline migration generated from current `init_schema.sql` (marked as already applied on first deploy)
- Future schema changes go through `alembic upgrade head` — run as part of deploy process
- Migrations are hand-written SQL (no ORM autogenerate, since the project uses raw SQL)

### Backup & Recovery

- Railway's managed Postgres includes automatic backups
- Data is reproducible — gauge readings and weather can be re-ingested from USGS/Open-Meteo APIs if needed. Predictions can be re-scored from the model.
- The only truly irreplaceable data is the `gauges` table config, which lives in `seed_db.py`

---

## Model Artifact Lifecycle

**Storage:** Cloudflare R2 bucket (e.g., `riffle-models`), accessed via S3-compatible API with access key credentials.

### Training Flow (Weekly, Sunday 03:00 MT)

1. Worker runs `train-daily` flow via Prefect Cloud schedule
2. XGBoost model trains against 2 years of historical data from Postgres
3. MLflow logs the run locally (metrics, params) — this happens inside the worker container but is ephemeral; local tracking for the run's duration only
4. Model artifact is serialized and uploaded to R2 at a known key path (e.g., `models/riffle-condition-daily/latest.joblib`)
5. A versioned copy is also written (e.g., `models/riffle-condition-daily/2026-04-13.joblib`) for rollback

### Scoring Flow (Daily, 04:00 MT)

1. Worker runs `score-daily` flow
2. Scoring task pulls `latest.joblib` from R2
3. Generates predictions for today + 7 forecast days, writes to `predictions_daily`

### Rollback

If a newly trained model produces bad predictions, manually update the `latest.joblib` key in R2 to point to a previous dated version. No redeploy needed — next scoring run picks it up.

### Local Development

MLflow continues to work as-is. R2 integration only applies to the production pipeline. Locally, model artifacts are loaded from MLflow's artifact store as they are today.

---

## Deployment & Configuration

### Deploy Trigger

Auto-deploy on push to `main`. Railway watches the GitHub repo and redeploys services whose Dockerfiles or source directories changed.

### Railway Service Mapping

| Service | Build context | Dockerfile | Start command |
|---------|--------------|------------|---------------|
| `api` | `./api` | `api/Dockerfile` | `uvicorn api.main:app` |
| `worker` | `./pipeline` | `pipeline/Dockerfile` | `python serve.py` |
| `postgres` | Railway plugin | n/a | n/a |

### Environment Variables (Railway Dashboard)

**Shared:**
- `DATABASE_URL` — Railway auto-injects for the Postgres plugin (`postgresql://...@postgres.railway.internal:5432/riffle`)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` — managed by Railway plugin

**API-specific:**
- `CORS_ORIGINS` — restrict to Vercel frontend domain (no more wildcard)

**Worker-specific:**
- `PREFECT_API_URL` — Prefect Cloud endpoint
- `PREFECT_API_KEY` — Prefect Cloud API key
- `R2_ENDPOINT_URL` — Cloudflare R2 S3-compatible endpoint
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` — R2 credentials
- `R2_BUCKET_NAME` — e.g., `riffle-models`

### Scale-to-Zero

- **API:** enabled, 10-minute idle timeout
- **Worker:** disabled — must stay running to receive Prefect Cloud flow triggers

### Rollback

Railway dashboard supports instant rollback to any previous deployment.

---

## Observability & Failure Handling

### Notifications

Configure a Prefect Cloud automation trigger: on any flow run entering `Failed` state, send an email notification. Covers both `daily-forecast` and `train-daily` flows.

### Failure Behavior by Flow

| Flow | Failure mode | Impact | Recovery |
|------|-------------|--------|----------|
| `daily-forecast` ingest fails | USGS or Open-Meteo API down | API serves yesterday's predictions (stale but valid) | Automatic retry next day at 04:00 MT |
| `daily-forecast` scoring fails | Model artifact missing or corrupt | Same stale predictions | Fix artifact in R2, trigger manual flow run from Prefect Cloud |
| `train-daily` fails | Training data insufficient or code bug | Existing `latest.joblib` remains in R2, scoring unaffected | Debug locally, push fix, next Sunday retrain picks it up |

### Health Monitoring

- Railway provides built-in service health checks and restart-on-crash
- API health endpoint (`GET /api/v1/health` or similar) — Railway pings this to confirm the service is alive after deploy
- Prefect Cloud dashboard shows flow run history, durations, and failure logs

### Logging

- Railway captures stdout/stderr from all services, viewable in dashboard
- No additional logging infrastructure needed initially

---

## Pre-Production Checklist

1. **Add Alembic** — baseline the current schema, wire `alembic upgrade head` into the deploy process
2. **Add API health endpoint** — Railway needs something to ping for deploy health checks
3. **R2 integration in pipeline** — add S3 client for model upload (train flow) and download (score flow), gated by environment (R2 in prod, local MLflow artifacts in dev)
4. **CORS lockdown** — replace wildcard with the Vercel frontend domain, configurable via env var
5. **Seed data in prod** — run `seed_db.py` once after initial Postgres setup
6. **Historical backfill** — run ingest flows against USGS/Open-Meteo archives to populate enough data for the model to train on
7. **Worker `serve.py` updates** — point at Prefect Cloud instead of local Prefect server, remove hourly flows that are paused/deferred to v1.1
8. **Environment variable wiring** — configure all secrets and config in Railway dashboard before first deploy

---

## Budget Estimate

| Service | Est. Cost |
|---------|-----------|
| Railway subscription | $5/mo |
| FastAPI (scale-to-zero, low traffic) | ~$1-2/mo |
| Prefect worker (runs ~5 min/day + weekly retrain) | ~$0.50-1/mo |
| Railway Postgres (<1GB) | ~$1-3/mo |
| Prefect Cloud | Free |
| Cloudflare R2 | Free |
| **Total** | **~$7-11/mo** |

---

## Key Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Hosting platform | Railway | Docker Compose mental model translates directly, managed Postgres, internal networking |
| Orchestration | Prefect Cloud (free tier) | Eliminates 2 containers (server + SQLite), free dashboard and scheduling |
| MLflow in prod | No — local only | API doesn't query MLflow at runtime; model artifacts stored in R2 |
| Database | Railway managed Postgres | Internal networking, no egress costs, same-platform simplicity |
| Model artifact storage | Cloudflare R2 | Free, S3-compatible, decouples training from scoring |
| Deploy strategy | Auto-deploy on push to `main` | Simple, test locally with Docker Compose first, Railway rollback as safety net |
| Scale-to-zero (API) | Yes, 10min idle | Saves compute on low-traffic portfolio project; ~5-10s cold start acceptable |
| Failure handling | Stale data + Prefect Cloud email alerts | API stays up with yesterday's predictions; user gets notified to investigate |
| Environment separation | Single production environment | Portfolio project — local Docker Compose is the "staging" environment |
| Schema migrations | Alembic (hand-written SQL) | Safety net for future schema changes; no ORM so no autogenerate |
