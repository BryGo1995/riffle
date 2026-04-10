# Local Prefect Setup — Design Spec

**Issue:** [#13](https://github.com/BryGo1995/riffle/issues/13)
**Branch:** `riffle-13-local-prefect`
**Date:** 2026-04-10

## Problem

The daily forecasting pipeline (shipped in PR #11, merged via PR #14) has three Prefect flows — `train_daily`, `score_daily`, and the existing hourly `ingest_score`/`train` — but nothing schedules or monitors them on the always-on dev box. There is also no incremental daily ingest: `score_daily` reads from `gauge_readings_daily`/`weather_readings_daily` but nothing refreshes those tables on a cadence. `pipeline/scripts/backfill_daily.py` exists as a manual range-based script.

The goal for this issue is to stand up a self-hosted Prefect server and a `serve()` process on the local box, wire up a daily ingest → score chain, schedule training, and give the developer a UI for monitoring. Production deployment (Railway, Prefect Cloud) is explicitly deferred.

## Goals

1. Scheduled daily ingest of yesterday's USGS daily-mean and Open-Meteo daily archive for all `ACTIVE_GAUGES`.
2. Scheduled daily scoring immediately after ingest, short-circuiting if ingest fails.
3. Scheduled weekly retraining of the `riffle-condition-daily` model.
4. Self-hosted Prefect UI for run history, logs, manual triggers, and schedule pause/resume — available at `http://localhost:4200`.
5. Services restart automatically when the box reboots (modulo enabling the Docker daemon at boot).
6. Code and docker-compose changes small enough to review in one PR.

## Non-goals

- Prefect Cloud migration (deferred until production deploy — #5).
- Work pools, dedicated workers, or multi-node execution.
- Notifications (Slack/email) on flow failure.
- Reviving the hourly diurnal model or its flows (deferred to v1.1 per #11).
- Moving MLflow or Prefect off SQLite onto a shared Postgres (see #12 for MLflow; Prefect stays on SQLite for now).
- Authentication on the Prefect UI — single-user local dev box, not exposed to the public internet.

## Design Decisions

Each decision below is the outcome of an explicit brainstorming discussion. Rejected alternatives are listed so future readers can reconstruct the reasoning.

### 1. Execution model: `flow.serve()` rather than work pools + workers

**Chosen:** a single long-running `python serve.py` process inside a container, using Prefect 3's `serve()` API to register deployments in code and execute scheduled runs in-process.

**Rejected alternatives:**

- **Work pool + separate worker.** Prefect's production-recommended model. Rejected because it adds a work-pool resource, a worker process, and deployment YAMLs for no benefit at single-user dev scale. The migration path from `serve()` to work pools is ~10 lines of code change when we do need it (production deploy via #5).
- **Host-level systemd timers calling `python -m flows.daily_forecast` directly.** Rejected because it gives up the Prefect UI, retry engine, and run history — the things that justified picking Prefect in the first place.

### 2. Prefect Cloud vs. self-hosted server

**Chosen:** self-hosted `prefect server start` inside a container on the local box.

**Rejected alternative:** Prefect Cloud. The free tier would cover a single-user dev workload fine, but it would require configuring work pools, workers, blocks, and auth for a pipeline that is still changing shape. That work gets redone when the design settles. Cloud is worth revisiting at production-deploy time alongside #5.

### 3. Prefect server state: SQLite in a named volume

**Chosen:** SQLite at `/root/.prefect/prefect.db` inside the `prefect-server` container, persisted via a `prefect-data` named Docker volume.

**Rejected alternatives:**

- **Postgres-backed, reusing the `riffle` instance.** Would match MLflow's pattern once #12 lands and give us one backup target. Rejected because it couples Prefect's state lifecycle to Postgres for no benefit at single-user scale. Prefect's docs only recommend Postgres for multi-worker or high-volume setups.
- **Postgres in a new dedicated `prefect` database.** Same objection plus additional provisioning work.

### 4. Daily ingest gap: extract shared core into `shared/ingest_daily.py`

**Chosen:** Add a new `pipeline/shared/ingest_daily.py` module exposing `ingest_gauge_daily()` and `ingest_weather_daily()` functions. Refactor `pipeline/scripts/backfill_daily.py` to import from this module. Create a new `ingest_daily_task` in the flow that calls these functions with `start == end == yesterday`.

**Rejected alternatives:**

- **Duplicate the ~20 lines of ingest logic inline in the new flow.** Rejected because it guarantees drift: any future change to retry behavior, rate limits, or upsert semantics has to land in two places.
- **Call `score_daily_flow` with an inline ingest step and no shared module.** Rejected because "how do we ingest one day of daily data?" should have exactly one answer in the codebase. The refactor cost is ~15 lines of moving code.
- **Defer the daily ingest flow to a separate follow-up issue.** Rejected because scheduling `score_daily` without ingest would score stale data, making the "scheduled daily pipeline" story false on day one.

### 5. Flow structure: single `daily_forecast_flow` with two tasks

**Chosen:** One flow named `daily-forecast` containing `ingest_daily_task` → `score_daily_task` as a DAG. Prefect's native task dependency ensures score is skipped automatically if ingest fails after all retries.

**Rejected alternative:** Two separate deployments (`ingest-daily` at 04:00, `score-daily` at 04:15) with no hard dependency. Rejected because scoring stale data when ingest failed is never the desired behavior — if ingest is broken, scoring should not run at all. Keeping them in one flow also gives a single UI row per day instead of two, with a task-level DAG view showing the full execution.

### 6. File rename: `flows/score_daily.py` → `flows/daily_forecast.py`

**Chosen:** Rename the file and rename the flow from `score_daily_flow` / `"score-daily"` to `daily_forecast_flow` / `"daily-forecast"`.

**Rationale:** Once the flow also ingests, the name `score_daily` is a misnomer. The flow is the full daily forecast pipeline, not just scoring. `train_daily.py` stays separate (weekly cadence, unrelated schedule).

### 7. Cadence: 04:00 America/Denver for daily, 03:00 Sunday for training

**Chosen:**
- `daily-forecast` — `cron="0 4 * * *", timezone="America/Denver"`
- `train-daily` — `cron="0 3 * * 0", timezone="America/Denver"`

**Rejected alternatives:**

- **06:00 MT daily** (original recommendation). Safer against USGS lateness but delays the fresh predictions into the late morning. User preferred 04:00 with a more generous retry policy on ingest.
- **Retry-spaced hourly ingest through the morning (04:00, 06:00, 08:00 with early-exit).** Most robust against USGS lateness but introduces multiple Prefect runs per day to sift through. Rejected as over-engineering for a problem we haven't observed.
- **Monthly retraining** instead of weekly. Cheaper in MLflow-run noise, but weekly retraining is essentially free and keeps "drift caught within a week" as a property. Can dial back if noise becomes annoying.

**DST handling:** Prefect 3's `timezone` kwarg on `to_deployment()` handles the MST/MDT switch automatically. No manual UTC conversion.

### 8. Retry policy on `ingest_daily_task`: 3 retries with backoff `[5m, 15m, 30m]`

**Chosen:** `retries=3, retry_delay_seconds=[300, 900, 1800]` on `ingest_daily_task`. Gives the chain up to ~45 minutes of slack to wait for USGS to finalize yesterday's daily row.

**Rejected alternative:** Keep the existing `retries=1, retry_delay_seconds=300` pattern from `score_daily_task`. Rejected because one 5-minute retry is too tight against USGS publication lateness at 04:00 MT.

`score_daily_task` keeps its existing `retries=1, retry_delay_seconds=300` since its failure modes are more likely "MLflow unreachable" or "DB connection dropped" than "data not yet available."

### 9. Hourly flows fate: registered but paused

**Chosen:** Register `ingest-score-hourly` and `train-hourly` in `serve.py` with `paused=True` on `to_deployment()`. The code and cron strings stay in version control for a v1.1 un-pausing.

**Rejected alternatives:**

- **Leave hourly schedules active.** Burns USGS API quota, Open-Meteo calls, MLflow runs, and Postgres I/O on data nothing reads. ~24 ingest runs/day writing to `gauge_readings`/`predictions` which the API no longer queries.
- **Remove the hourly deployments from `serve.py` entirely.** Cleaner code but loses the "one click to un-pause" ergonomics when v1.1 comes back. The flow modules stay in the repo either way.

### 10. Docker Compose: default-on, internal DNS, health-gated dependency

**Chosen:**
- `prefect-server` and `prefect-serve` are in the default services list (no compose profile). `docker compose up -d` brings up the whole stack.
- `PREFECT_API_URL` defaults to `http://prefect-server:4200/api` (internal Docker-network DNS), still overridable via `.env` for future Cloud experiments.
- `prefect-serve` has `depends_on: prefect-server` with `condition: service_healthy`. Healthcheck uses a Python urllib call against `/api/health` (the official Prefect image doesn't ship `curl`).
- All services get `restart: unless-stopped`.

**Rejected alternative:** Compose profile (`--profile prefect`) gating the two services. Rejected because Prefect isn't optional on this box — it's the reason the box is always on.

## Architecture

```
┌────────────────── docker compose (Fedora host) ─────────────────┐
│                                                                  │
│  postgres ─── mlflow ───── api ───── (external :8000)            │
│     │                                                            │
│     └──── prefect-serve ──── prefect-server ── (external :4200)  │
│             (runs serve.py)      (SQLite DB in named volume)     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Two new containers:**

1. **`prefect-server`** — Prefect's API + UI. Image `prefecthq/prefect:3-python3.11`. Command `prefect server start --host 0.0.0.0`. Exposes `4200` on the host. SQLite DB on named volume `prefect-data` at `/root/.prefect`. Healthcheck via Python urllib call against `/api/health`, with `start_period: 20s` to allow first-boot migrations.

2. **`prefect-serve`** — renamed from the current `prefect-worker`. Same build context (`./pipeline/Dockerfile`). Command `python serve.py`. Depends on `prefect-server` (health-gated), `postgres` (health-gated), `mlflow` (started).

**`serve.py` registers four deployments:**

| Deployment | Cron | Timezone | Paused? |
|---|---|---|---|
| `daily-forecast` | `0 4 * * *` | America/Denver | no |
| `train-daily` | `0 3 * * 0` | America/Denver | no |
| `ingest-score-hourly` | `0 * * * *` | (n/a) | **yes** |
| `train-hourly` | `0 9 * * 1` | (n/a) | **yes** |

## File & Code Changes

### New files

**`pipeline/shared/ingest_daily.py`** (~40 lines) — extracted shared core:

```python
def ingest_gauge_daily(gauge_id: int, usgs_id: str, start: date, end: date) -> int:
    """Fetch USGS daily-mean flow/temp for [start, end] and upsert. Returns row count."""

def ingest_weather_daily(
    gauge_id: int, lat: float, lon: float, start: date, end: date
) -> int:
    """Fetch Open-Meteo daily archive for [start, end] and upsert. Returns row count."""
```

Both call the existing `fetch_*` helpers in `shared/usgs_client.py` and `shared/weather_client.py`, and the existing `upsert_*` helpers in `shared/db_client.py`. Single source of truth for "fetch + upsert N days for one gauge."

**`pipeline/flows/daily_forecast.py`** — new flow file, replaces `flows/score_daily.py`:

- `ingest_daily_task` with `retries=3, retry_delay_seconds=[300, 900, 1800]`. Loops `ACTIVE_GAUGES`, calls `ingest_gauge_daily(..., yesterday, yesterday)` and `ingest_weather_daily(..., yesterday, yesterday)` for each. Logs per-gauge success/failure. Raises only if **zero** gauges received a valid `flow_cfs` for yesterday (indicates a real USGS/network outage, worth retrying). If some gauges succeed and others don't, the task succeeds and `score_daily_task` handles individual missing-gauge cases via its existing "no recent flow_cfs — skipping" path.
- `score_daily_task` — logic moved verbatim from the old `score_daily.py`. Keeps `retries=1, retry_delay_seconds=300`.
- `daily_forecast_flow` (flow name `"daily-forecast"`) calls the two tasks in order.

**`pipeline/tests/test_ingest_daily.py`** — unit tests for `shared.ingest_daily` covering the happy path and the null-flow retry case, using the same fake USGS/weather clients as existing tests.

### Modified files

**`pipeline/scripts/backfill_daily.py`** — replace local `backfill_gauge_daily` / `backfill_weather_daily` with imports from `shared.ingest_daily`. CLI, date-range handling, and the 1-second pace between gauges stay identical.

**`pipeline/serve.py`** — rewrite to register the four deployments listed in the Architecture section. Two active, two `paused=True`.

**`pipeline/tests/test_score.py`** — update imports from `flows.score_daily` to `flows.daily_forecast`. Add one new test: `test_ingest_daily_task_fetches_yesterday` asserting that `ingest_gauge_daily` and `ingest_weather_daily` are called with `start == end == yesterday` for each active gauge.

**`docker-compose.yml`** — add `prefect-server` service, rename `prefect-worker` → `prefect-serve` with updated command/env/depends_on, add `prefect-data` volume declaration.

**`.env.example`** — add commented `PREFECT_API_URL` override for future Cloud experiments.

**`README.md`** — new "Scheduled Pipelines" section covering start, UI access, deployment list, manual triggers, pause/resume, log access, reset-run-history procedure, and troubleshooting. Plus a one-time host-setup note about `systemctl enable docker`.

### Deleted files

**`pipeline/flows/score_daily.py`** — flow moves to `daily_forecast.py`. Any import left pointing at the old path is caught by the test update.

### Unchanged files

- `pipeline/flows/train_daily.py` — only gets a new cron in `serve.py`.
- `pipeline/flows/ingest_score.py`, `pipeline/flows/train.py` — registered paused, code untouched.
- `pipeline/shared/usgs_client.py`, `weather_client.py`, `db_client.py` — primitives already exist.
- `pipeline/Dockerfile` — `requirements.txt` already pins `prefect>=3.0`, no changes expected.

## Host Setup (one-time)

Fedora 43 does not enable Docker at boot by default. Without this, `restart: unless-stopped` only takes effect while the daemon is already running.

```
systemctl is-enabled docker
# If "disabled":
sudo systemctl enable --now docker
```

Documented in `README.md` under the Scheduled Pipelines section.

## Verification Plan

1. `docker compose down && docker compose up -d --build` on the branch, confirm all 6 services reach healthy state.
2. Open `http://localhost:4200`, confirm the four deployments are listed: `daily-forecast` and `train-daily` active, `ingest-score-hourly` and `train-hourly` paused.
3. Click "Run" on `daily-forecast` from the UI, confirm it executes successfully end-to-end (ingest task writes yesterday's rows to `gauge_readings_daily` / `weather_readings_daily`, score task writes 8 rows to `predictions_daily` for each active gauge).
4. Verify API response: `curl localhost:8000/api/v1/rivers/09085000` still returns `current` and a 7-entry `forecast` array.
5. Click "Run" on `train-daily`, confirm a new `riffle-condition-daily` model version is registered in MLflow and promoted to Production.
6. Confirm the existing test suite stays green: 108 tests → ~115 tests after the additions (new `test_ingest_daily.py` plus one new test in `test_score.py`).
7. `docker compose restart prefect-serve`, confirm deployments re-register and scheduled runs resume from the same point (SQLite persistence).
8. Reboot the box, confirm (post-boot) that `docker ps` shows the riffle services running without manual intervention, provided `systemctl is-enabled docker` returns `enabled`.

## Out of Scope (captured here for follow-up)

- **Prefect Cloud migration + production deploy** — tracked in #5.
- **MLflow Postgres DB split** — tracked in #12. Unrelated to Prefect but shares the "untangle shared Postgres" theme.
- **Notifications on flow failure** — deferred. Prefect 3 supports webhook/email automations; easy to add when we have a real channel to notify.
- **Hourly diurnal model v1.1** — when revived, un-pause the two hourly deployments from the UI. No code change needed.
- **Flow projection model for future `flow_cfs`** — currently held constant from latest observation in `score_daily_task`. Noted in `flows/daily_forecast.py` as a future iteration.
