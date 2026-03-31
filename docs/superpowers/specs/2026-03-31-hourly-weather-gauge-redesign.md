# Hourly Weather & Gauge Redesign

**Date:** 2026-03-31
**Status:** Approved

## Overview

Move weather ingestion from daily to hourly resolution, expand the weather variable set, restructure the DAGs into a single hourly pipeline, and backfill 2 years of historical data to enable meaningful ML training from day one.

## Motivation

- Daily weather aggregates (max temp, precip sum) lose intra-day signal that affects river conditions and fish behavior
- A single morning scoring snapshot is insufficient — conditions change throughout the day
- The model needs richer features (snowfall, cloud cover, barometric pressure, wind) to learn meaningful patterns
- Hourly predictions stored persistently create a long-term dataset for future model improvement

---

## Schema

### `weather_readings` (drop and recreate)

Replace `date DATE` with `observed_at TIMESTAMP WITH TIME ZONE`. One row per gauge per hour.

```sql
CREATE TABLE weather_readings (
    id                    SERIAL PRIMARY KEY,
    gauge_id              INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    observed_at           TIMESTAMP WITH TIME ZONE NOT NULL,
    precip_mm             DOUBLE PRECISION,
    precip_probability    INTEGER,          -- NULL for historical/observed rows (forecast-only variable)
    air_temp_f            DOUBLE PRECISION,
    snowfall_mm           DOUBLE PRECISION,
    wind_speed_mph        DOUBLE PRECISION,
    weather_code          INTEGER,
    cloud_cover_pct       INTEGER,
    surface_pressure_hpa  DOUBLE PRECISION,
    is_forecast           BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(gauge_id, observed_at)
);
```

### `predictions` (drop and recreate)

Replace `date DATE` with `target_datetime TIMESTAMP WITH TIME ZONE`. One row per gauge per predicted hour, preserving full hourly scoring history.

```sql
CREATE TABLE predictions (
    id              SERIAL PRIMARY KEY,
    gauge_id        INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    target_datetime TIMESTAMP WITH TIME ZONE NOT NULL,
    condition       VARCHAR(20) NOT NULL,
    confidence      DOUBLE PRECISION,
    is_forecast     BOOLEAN NOT NULL DEFAULT FALSE,
    model_version   VARCHAR(100),
    scored_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(gauge_id, target_datetime)
);

CREATE INDEX idx_predictions_gauge_datetime ON predictions(gauge_id, target_datetime DESC);
```

### Migration

A drop-and-recreate SQL script (`pipeline/sql/migrate_hourly.sql`) handles the transition. `init_schema.sql` is updated to reflect the new schema as the canonical definition.

---

## Weather Client

`weather_client.py` exposes two functions backed by the same `WeatherHour` dataclass:

```python
@dataclass
class WeatherHour:
    observed_at:          datetime
    precip_mm:            float
    precip_probability:   Optional[int]   # None for historical rows
    air_temp_f:           float
    snowfall_mm:          float
    wind_speed_mph:       float
    weather_code:         int
    cloud_cover_pct:      int
    surface_pressure_hpa: float
    is_forecast:          bool
```

**`fetch_weather_forecast(lat, lon)`** — calls `forecast-api.open-meteo.com`, returns current hour + 72h of forecast hours.

**`fetch_weather_historical(lat, lon, start_date, end_date)`** — calls `archive-api.open-meteo.com`, returns hourly rows for the given date range. `precip_probability` is `None` for all rows.

Open-Meteo hourly variables requested:
- `precipitation`, `precipitation_probability`, `temperature_2m`, `snowfall`, `wind_speed_10m`, `weather_code`, `cloud_cover`, `surface_pressure`

Temperature converted to Fahrenheit. Wind speed converted to mph. Timezone set to `America/Denver`.

---

## DB Client

Updated functions in `db_client.py`:

- **`upsert_weather_reading`** — new signature matching hourly schema, upserts on `(gauge_id, observed_at)`
- **`get_recent_weather_readings(gauge_id, hours)`** — returns hourly rows ordered by `observed_at DESC`
- **`get_weather_for_hour(gauge_id, observed_at)`** — returns the weather row whose `observed_at` matches the hour-truncated gauge timestamp, falling back to the most recent row within 2 hours if no exact match exists
- **`upsert_prediction`** — `target_datetime` replaces `date`; `scored_at` is a separate explicit column

---

## Feature Engineering

`build_feature_vector` receives hourly weather rows in `weather_history`. Updated helpers:

- **`compute_precip_72h`** — sums hourly `precip_mm` over the 72 hours ending at `target_datetime`
- **`compute_days_since_precip`** — aggregates hourly rows to daily totals, finds last day with >= 5mm total

New features added to the vector:

| Feature | Source |
|---|---|
| `precip_probability` | Current weather hour (`None` → `0.0`) |
| `snowfall_mm` | Current weather hour |
| `wind_speed_mph` | Current weather hour |
| `cloud_cover_pct` | Current weather hour |
| `surface_pressure_hpa` | Current weather hour |
| `weather_code` | Current weather hour |
| `hour_of_day` | Derived from `target_datetime` (0–23) |

Existing features retained: `flow_cfs`, `gauge_height_ft`, `water_temp_f`, `precip_24h_mm`, `precip_72h_mm`, `air_temp_f`, `day_of_year`, `days_since_precip_event`.

The weekly `train_dag` retrains automatically once the backfill populates the DB with the new schema.

---

## DAG Restructure

### Removed
- `gauge_ingest_dag.py`
- `weather_ingest_dag.py`
- `condition_score_dag.py`

### New: `ingest_score_dag.py` (hourly)

Schedule: `0 * * * *`

```
fetch_weather ──┐
                ├──> score_conditions
fetch_gauge   ──┘
```

`fetch_weather` and `fetch_gauge` run in parallel via `TriggerRule.ALL_DONE` on `score_conditions` — if one ingest fails, scoring still runs using the most recent available data from the DB rather than blocking entirely.

### Unchanged: `train_dag.py`

Weekly, Monday 3:00am MT. Trains on hourly `gauge_readings` joined with hourly `weather_readings`. No structural changes needed — the richer dataset is consumed automatically.

---

## Backfill Script

**`pipeline/scripts/backfill_weather_gauge.py`**

- CLI args: `--start` (default: 2 years ago), `--end` (default: yesterday)
- Iterates over all gauges in `GAUGES` config
- Fetches Open-Meteo historical hourly data via `fetch_weather_historical`
- Fetches USGS historical instantaneous values via the `iv` (instantaneous values) time series endpoint with `period` chunked into 30-day windows to stay within API limits
- Writes via `upsert_weather_reading` and `upsert_gauge_reading` — fully idempotent, safe to re-run
- Logs progress per gauge: `[1/8] Spinney Reservoir: fetching 2024-03-31 → 2026-03-30`

---

## What Is Not Changing

- `gauges` table — no changes
- `gauge_readings` table — already hourly, no schema changes needed
- `train_dag.py` structure — schedule and task structure unchanged
- `db_client.get_gauge_id` and `upsert_gauge_reading` — unchanged
- Existing API and frontend — out of scope for this change. The API and frontend will need a separate update to consume hourly predictions (e.g. returning the latest scored row per gauge, or exposing a full hourly series). This is not a blocker for the pipeline work.
