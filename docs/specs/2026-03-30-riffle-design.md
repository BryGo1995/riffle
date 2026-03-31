# Riffle — Colorado Fly Fishing Conditions Tracker — Design Spec

**Date:** 2026-03-30
**Status:** Approved
**Project name:** Riffle

---

## Overview

A full-stack portfolio project that ingests real-time USGS stream gauge data and weather forecasts,
runs an XGBoost classifier to predict fly fishing conditions, and surfaces results on a public-facing
Next.js site with an interactive Colorado river map. Users can see today's conditions and a 3-day
forecast per gauge location to plan fishing trips.

**Goals:**
- Demonstrate end-to-end ML engineering (pipeline → model → serving → UI)
- Produce a live, publicly accessible site for portfolio and LinkedIn visibility
- Reuse existing skills (Airflow, XGBoost, MLflow, FastAPI, Next.js) in a new domain
- Keep scope simpler than odds-pipeline (4 DAGs vs 7)

---

## Repo Structure

Single monorepo — one GitHub link tells the whole story for hiring managers.

```
fishing-conditions/
├── pipeline/            # Airflow DAGs, XGBoost training, MLflow integration
│   ├── dags/
│   │   ├── gauge_ingest_dag.py
│   │   ├── weather_ingest_dag.py
│   │   ├── condition_score_dag.py
│   │   └── train_dag.py
│   ├── plugins/
│   │   ├── ml/
│   │   │   ├── train.py       # XGBoost training + MLflow promotion
│   │   │   └── score.py       # load production model, write predictions
│   │   └── features.py        # feature engineering
│   ├── shared/
│   │   ├── usgs_client.py     # USGS Water Services API client
│   │   ├── weather_client.py  # Open-Meteo API client
│   │   └── db_client.py       # Postgres utilities
│   ├── config/
│   │   └── rivers.py          # river/gauge registry (names, gauge IDs, lat/lon)
│   ├── sql/
│   │   └── init_schema.sql
│   └── tests/
├── api/                 # FastAPI — serves predictions to the frontend
│   ├── main.py
│   ├── routes/
│   └── tests/
├── web/                 # Next.js (App Router) + TypeScript + Tailwind
│   ├── app/
│   │   ├── page.tsx           # map hero page
│   │   └── rivers/[id]/
│   │       └── page.tsx       # river detail page
│   ├── components/
│   └── config/
├── docker-compose.yml   # Airflow + Postgres + MLflow + FastAPI
├── .env.example
└── README.md            # top-level overview with architecture diagram
```

---

## Architecture

```
USGS Water Services API ──► gauge_ingest_dag  ──► gauge_readings (Postgres)
                                                           │
Open-Meteo API ──────────► weather_ingest_dag ──► weather_readings (Postgres)
                                                           │
                                               condition_score_dag ──► predictions (Postgres)
                                                           │         (today + 3-day forecast)
                                               train_dag (weekly) ──► MLflow model registry
                                                           │
                                                      FastAPI
                                                           │
                                                      Next.js (Vercel)
                                               ┌───────────┴───────────┐
                                           Map view             River detail page
                                    (color-coded markers)   (charts + 3-day forecast)
```

---

## Data Sources

### USGS Water Services API
- **Free, no API key required**
- Provides: stream flow (cfs), water temperature (°F), gauge height (ft)
- Historical data available for decades — used for ML training
- Real-time data updated every 15–60 minutes

### Open-Meteo API
- **Free, no API key required**
- Provides: current weather + 7-day forecast per lat/lon
- Fields used: precipitation (mm), air temperature (°F)

### Gauge Registry (~10 Colorado rivers, ~15 gauges)

| River               | Location / Section         | USGS Gauge ID |
|---------------------|---------------------------|---------------|
| South Platte        | Spinney Reservoir          | 09035800      |
| South Platte        | Eleven Mile Canyon         | 09036000      |
| South Platte        | Deckers                    | 09033300      |
| South Platte        | Cheesman Canyon            | 09034500      |
| Arkansas River      | Salida                     | 07091200      |
| Arkansas River      | Cañon City                 | 07096000      |
| Fryingpan River     | Ruedi Reservoir to Basalt  | 09081600      |
| Roaring Fork River  | Glenwood Springs           | 09085000      |
| Blue River          | Silverthorne               | 09057500      |
| Cache la Poudre     | Canyon Mouth               | 06752000      |
| Colorado River      | Glenwood Springs           | 09070000      |

---

## Pipeline (Airflow DAGs)

### `gauge_ingest_dag` — Daily, 7:00am MT
1. For each gauge in the registry, fetch latest USGS reading (flow, temp, gauge height)
2. Write raw response to `gauge_readings_raw` (JSON)
3. Transform and upsert into `gauge_readings` (normalized)

### `weather_ingest_dag` — Daily, 7:05am MT
1. For each gauge lat/lon, fetch Open-Meteo current conditions + 3-day forecast
2. Write to `weather_readings` table (one row per gauge per day, including forecast days)

### `condition_score_dag` — Daily, 7:30am MT (waits on both ingest DAGs)
1. Load production XGBoost model from MLflow registry
2. Build feature vectors for today + 3 forecast days per gauge
3. Run classification → 5-class condition label per gauge per day
4. Write to `predictions` table

### `train_dag` — Weekly, Monday 3:00am MT
1. Pull historical `gauge_readings` + `weather_readings` from Postgres
2. Generate bootstrapped labels from domain-knowledge thresholds (see ML section)
3. Train XGBoost classifier, log experiment to MLflow
4. Promote best model to production in MLflow registry

---

## ML Layer

### Problem
Multi-class classification: given stream and weather conditions for a gauge location and date,
predict fishing condition as one of 5 classes.

### Condition Scale
| Label     | Meaning                                              |
|-----------|------------------------------------------------------|
| Excellent | Optimal flow, ideal temp, clear water                |
| Good      | Slightly off-ideal but productive fishing            |
| Fair      | Fishable but challenging — fish are finicky          |
| Poor      | Difficult conditions — high flow or marginal temp    |
| Blown Out | Unfishable — extreme flow, flood conditions, or >68°F|

### Features (per gauge per day)
- `flow_cfs` — stream flow in cubic feet per second
- `gauge_height_ft` — gauge height
- `water_temp_f` — water temperature (°F)
- `precip_24h_mm` — precipitation in last 24 hours
- `precip_72h_mm` — precipitation in last 72 hours
- `air_temp_f` — air temperature (°F)
- `day_of_year` — captures seasonal patterns (spring runoff, late summer low flows)
- `days_since_precip_event` — days since last significant precipitation (>5mm)

### Training Labels
Bootstrapped from domain-knowledge thresholds applied to historical USGS data:
- **Blown Out:** flow > river-specific blowout threshold OR water temp > 68°F
- **Poor:** flow > 150% of seasonal median OR water temp 65–68°F
- **Fair:** flow 120–150% of seasonal median OR water temp 60–65°F
- **Good:** flow 80–120% of seasonal median AND water temp 50–60°F
- **Excellent:** flow at seasonal optimal range AND water temp 45–55°F AND no recent precip event

Each river has its own flow thresholds defined in `config/rivers.py` (a tailwater like the
Fryingpan fishes well at lower flows than a freestone river like the Cache la Poudre).

### Model
- **Algorithm:** XGBoost multi-class classifier (same as odds-pipeline — reinforces existing skill)
- **Tracking:** MLflow logs all experiments; best model promoted to `production` stage
- **Forecast predictions:** 3-day forecast uses Open-Meteo predicted precipitation and air temp
  as features alongside the most recent gauge readings. Flow is treated as a near-term baseline
  (significant flow changes from upstream precip typically take 24–48h to propagate). The UI
  clearly labels forecast days as estimated.

---

## API (FastAPI)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/rivers` | List all gauges with today's condition |
| `GET` | `/api/rivers/{gauge_id}` | Current condition + 3-day forecast for one gauge |
| `GET` | `/api/rivers/{gauge_id}/history` | Last 30 days of condition labels + key stats |

---

## Frontend (Next.js)

### Map Page (hero)
- Interactive Colorado map via **Leaflet.js** (open source, no API key)
- One marker per USGS gauge, color-coded by today's condition:
  - Excellent → dark green
  - Good → green
  - Fair → yellow
  - Poor → orange
  - Blown Out → red
- Clicking a marker navigates to the river detail page

### River Detail Page `/rivers/[gauge_id]`
- Gauge name, river name, current condition badge
- Key stats: flow (cfs), water temp (°F), gauge height (ft)
- **3-day forecast strip** — one card per day with condition badge + expected precip + air temp
  - Forecast days labeled "Estimated" to communicate uncertainty
- **30-day condition history chart** — time series of condition labels
- Link out to the USGS gauge page for raw data

### Stack
- Next.js 14 (App Router) + TypeScript + Tailwind CSS
- Deployed on **Vercel** (free tier, sufficient for portfolio traffic)

---

## Database Schema (Postgres)

```sql
-- Gauge registry
gauges (id, name, river, usgs_gauge_id, lat, lon, flow_thresholds JSONB)

-- Raw + normalized ingest
gauge_readings (id, gauge_id, fetched_at, flow_cfs, water_temp_f, gauge_height_ft)
weather_readings (id, gauge_id, date, precip_mm, air_temp_f, is_forecast)

-- ML output
predictions (id, gauge_id, date, condition, confidence, is_forecast, model_version, scored_at)
```

---

## Deployment Path

### Phase 1 — Portfolio (now)
- Pipeline + API run locally via Docker Compose
- Frontend deployed on Vercel, pointed at a temporary public API endpoint (ngrok or Railway)

### Phase 2 — Stable Public URL
- Deploy pipeline + API to **Railway** (Docker Compose → Railway services)
- Managed Postgres on Railway
- Update Vercel `FASTAPI_URL` env var to Railway URL
- Site is fully public and always live

### Phase 3 — Production (if going public at scale)
- Migrate to AWS: ECS Fargate (FastAPI) + MWAA or EC2 (Airflow) + RDS (Postgres)
- CloudFront CDN in front of Vercel/ALB
- Same pattern as PropDrop Phase 2

---

## v2 Features (post-launch)

- **River-line interpolation:** Draw colored river lines between gauges using OpenStreetMap /
  USGS NHD geometry. Linear interpolation of condition score along the river corridor.
  Interpolated stretches visually distinguished (dashed line or "Estimated" tooltip) to
  communicate uncertainty. Known limitation: tributaries between gauges are not modeled.
- **Hatch calendar overlay:** Overlay expected insect hatch activity by river and month
  (based on water temp + time of year) as an additional planning layer.
- **Email/push alerts:** Subscribe to a river and get notified when conditions improve.

---

## What This Demonstrates to Employers

| Skill | How it shows |
|-------|-------------|
| Data pipeline (Airflow) | 4 DAGs with scheduling, dependencies, and backfill support |
| ML engineering (XGBoost + MLflow) | Training, experiment tracking, model promotion, serving |
| API design (FastAPI) | Clean REST endpoints, async SQLAlchemy |
| Frontend (Next.js + TypeScript) | Map UI, detail pages, charting |
| Data sourcing | Two free public APIs, no vendor lock-in |
| ML honesty | Bootstrapped labels, forecast uncertainty, documented limitations |
| System thinking | Medallion-style data flow, deployment progression plan |
