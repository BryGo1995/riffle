# MVP: Active Flag, Weather-Only Scoring, and API Versioning

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a robust MVP by adding a config-driven active/inactive gauge flag, routing inactive gauges to rule-based weather-only scoring, versioning the API to `/api/v1`, and rebuilding the database using the new USGS OGC API.

**Architecture:** `config/rivers.py` is the single source of truth for gauge state — `ACTIVE_GAUGES` is derived from `GAUGES` at import time. The ingest flow fetches weather for all gauges and USGS gauge readings only for active ones; scoring branches on active status. A new `plugins/ml/weather_score.py` provides a rule-based fallback scorer for inactive gauges using weather fields only. API routes move from `/api` to `/api/v1`, and two pre-existing broken SQL column references are fixed in the same pass.

**Tech Stack:** Python, Prefect, XGBoost/MLflow, FastAPI, SQLAlchemy, PostgreSQL, USGS Water Data OGC API v0, Open-Meteo

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `pipeline/config/rivers.py` | Modify | Add `active: True` to each entry; export `ACTIVE_GAUGES` |
| `pipeline/tests/test_config.py` | **Create** | Tests for active flag and ACTIVE_GAUGES |
| `pipeline/plugins/ml/weather_score.py` | **Create** | Rule-based weather-only scorer |
| `pipeline/tests/test_weather_score.py` | **Create** | Tests for weather scorer rules and return types |
| `pipeline/flows/ingest_score.py` | Modify | Weather fetch for all gauges; gauge reads + ML scoring for active only; weather-only scoring for inactive |
| `pipeline/flows/train.py` | Modify | Use `ACTIVE_GAUGES` only |
| `pipeline/scripts/backfill_weather_gauge.py` | Modify | Weather backfill for all gauges; gauge reading backfill for active only |
| `pipeline/sql/init_schema.sql` | Modify | Consolidate `migrate_hourly.sql` changes into canonical schema |
| `api/main.py` | Modify | Change route prefix from `/api` to `/api/v1` |
| `api/routes/rivers.py` | Modify | Fix broken SQL column refs (`p.date` → `DATE(p.target_datetime)`); update docstring |
| `api/tests/test_routes.py` | **Create** | Tests for versioned route registration and response shape |

---

### Task 1: Add active flag to config

**Files:**
- Modify: `pipeline/config/rivers.py`
- Create: `pipeline/tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# pipeline/tests/test_config.py
import sys
sys.path.insert(0, "pipeline")
from config.rivers import GAUGES, ACTIVE_GAUGES


def test_all_gauges_have_active_flag():
    for g in GAUGES:
        assert "active" in g, f"{g['usgs_gauge_id']} missing 'active' key"


def test_active_gauges_are_subset_of_gauges():
    gauge_ids = {g["usgs_gauge_id"] for g in GAUGES}
    for g in ACTIVE_GAUGES:
        assert g["usgs_gauge_id"] in gauge_ids


def test_active_gauges_only_contains_active():
    for g in ACTIVE_GAUGES:
        assert g["active"] is True


def test_initial_11_gauges_all_active():
    assert len(ACTIVE_GAUGES) == 11
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest pipeline/tests/test_config.py -v
```
Expected: ImportError — `ACTIVE_GAUGES` not defined

- [ ] **Step 3: Add active flag and ACTIVE_GAUGES to config**

In `pipeline/config/rivers.py`, add `"active": True` to each of the 11 gauge entries and append at the bottom (after the closing `]` of `GAUGES`):

```python
# Gauges participating in the full ingest → ML pipeline.
# Set active=False for gauges with no USGS flow data — they still
# receive weather ingestion and weather-only rule-based scoring.
ACTIVE_GAUGES = [g for g in GAUGES if g.get("active", True)]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest pipeline/tests/test_config.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/config/rivers.py pipeline/tests/test_config.py
git commit -m "feat: add active flag and ACTIVE_GAUGES to gauge config"
```

---

### Task 2: Weather-only scorer

**Files:**
- Create: `pipeline/plugins/ml/weather_score.py`
- Create: `pipeline/tests/test_weather_score.py`

- [ ] **Step 1: Write the failing tests**

```python
# pipeline/tests/test_weather_score.py
import sys
sys.path.insert(0, "pipeline")
from plugins.ml.weather_score import score_weather_only
from plugins.ml.train import CONDITION_CLASSES


# --- Return type ---

def test_returns_tuple():
    result = score_weather_only(
        air_temp_f=55.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert isinstance(result, tuple) and len(result) == 2


def test_confidence_is_float_between_0_and_1():
    _, conf = score_weather_only(
        air_temp_f=55.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert 0.0 < conf <= 1.0


def test_condition_is_valid_label():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond in CONDITION_CLASSES


# --- Rule boundaries ---

def test_blown_out_extreme_precip_mm():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=21.0, precip_probability=50,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Blown Out"


def test_blown_out_high_probability_and_heavy_rain():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=12.0, precip_probability=85,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Blown Out"


def test_poor_high_precip_probability():
    cond, _ = score_weather_only(
        air_temp_f=55.0, precip_mm=3.0, precip_probability=70,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Poor"


def test_poor_freezing_temp():
    cond, _ = score_weather_only(
        air_temp_f=30.0, precip_mm=0.0, precip_probability=0,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Poor"


def test_poor_significant_snowfall():
    cond, _ = score_weather_only(
        air_temp_f=32.0, precip_mm=0.0, precip_probability=20,
        snowfall_mm=5.0, wind_speed_mph=5.0,
    )
    assert cond == "Poor"


def test_fair_moderate_precip_probability():
    cond, _ = score_weather_only(
        air_temp_f=60.0, precip_mm=1.0, precip_probability=45,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Fair"


def test_fair_marginal_cold_temp():
    cond, _ = score_weather_only(
        air_temp_f=40.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Fair"


def test_excellent_ideal_conditions():
    cond, _ = score_weather_only(
        air_temp_f=58.0, precip_mm=0.0, precip_probability=10,
        snowfall_mm=0.0, wind_speed_mph=5.0,
    )
    assert cond == "Excellent"


def test_good_decent_conditions():
    cond, _ = score_weather_only(
        air_temp_f=72.0, precip_mm=1.0, precip_probability=20,
        snowfall_mm=0.0, wind_speed_mph=8.0,
    )
    assert cond == "Good"


# --- Confidence ceiling (weather-only is less certain than ML model) ---

def test_confidence_ceiling_across_conditions():
    cases = [
        dict(air_temp_f=55.0, precip_mm=25.0, precip_probability=90, snowfall_mm=0.0, wind_speed_mph=5.0),
        dict(air_temp_f=30.0, precip_mm=0.0, precip_probability=0, snowfall_mm=0.0, wind_speed_mph=5.0),
        dict(air_temp_f=58.0, precip_mm=0.0, precip_probability=5, snowfall_mm=0.0, wind_speed_mph=3.0),
        dict(air_temp_f=72.0, precip_mm=1.0, precip_probability=20, snowfall_mm=0.0, wind_speed_mph=8.0),
    ]
    for kwargs in cases:
        _, conf = score_weather_only(**kwargs)
        assert conf <= 0.80, f"confidence {conf} exceeds ceiling for {kwargs}"
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest pipeline/tests/test_weather_score.py -v
```
Expected: ImportError — `weather_score` module not found

- [ ] **Step 3: Implement the scorer**

Create `pipeline/plugins/ml/weather_score.py`:

```python
"""Rule-based weather-only condition scorer for inactive gauges.

Used when a gauge has active=False in config, meaning no USGS gauge
readings are available. Derives a fishing condition label from weather
data only. Returns lower confidence than the ML model (capped at 0.75)
to signal this is a weather-only estimate.

Condition priority: Blown Out > Poor > Fair > Good > Excellent
"""

from typing import Tuple


def score_weather_only(
    air_temp_f: float,
    precip_mm: float,
    precip_probability: int,
    snowfall_mm: float,
    wind_speed_mph: float,
) -> Tuple[str, float]:
    """Return (condition, confidence) derived from weather data only.

    Confidence is capped at 0.75 — lower than ML predictions — to make
    clear this is a weather-only estimate with no gauge flow data.
    """
    # Blown Out: extreme precipitation
    if precip_mm > 20 or (precip_probability >= 80 and precip_mm > 10):
        return "Blown Out", 0.75

    # Poor: heavy precip, freezing temps, or significant snowfall
    if (
        precip_probability > 60
        or precip_mm > 8
        or snowfall_mm > 3
        or air_temp_f < 34
        or air_temp_f > 88
    ):
        return "Poor", 0.65

    # Fair: moderate precip or marginal temperatures
    if precip_probability > 35 or precip_mm > 3 or air_temp_f < 42 or air_temp_f > 80:
        return "Fair", 0.60

    # Excellent: ideal temps, clear skies
    if 48 <= air_temp_f <= 68 and precip_probability <= 15 and snowfall_mm == 0:
        return "Excellent", 0.55

    # Good: decent conditions that don't meet the excellent threshold
    return "Good", 0.55
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest pipeline/tests/test_weather_score.py -v
```
Expected: all 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/plugins/ml/weather_score.py pipeline/tests/test_weather_score.py
git commit -m "feat: add rule-based weather-only scorer for inactive gauges"
```

---

### Task 3: Update ingest_score flow

**Files:**
- Modify: `pipeline/flows/ingest_score.py`

- [ ] **Step 1: Verify existing structural tests pass before touching the flow**

```
pytest pipeline/tests/test_flows.py -v
```
Expected: all 12 tests PASS

- [ ] **Step 2: Replace ingest_score.py**

```python
# pipeline/flows/ingest_score.py
from datetime import datetime, timezone

from prefect import flow, task

from config.rivers import GAUGES, ACTIVE_GAUGES
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
from plugins.ml.weather_score import score_weather_only

_ACTIVE_IDS = {g["usgs_gauge_id"] for g in ACTIVE_GAUGES}


def fetch_and_store_weather():
    # Fetch weather for ALL gauges — inactive gauges need it for scoring.
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
    # Only fetch USGS gauge readings for active gauges.
    fetched_at = datetime.now(tz=timezone.utc)
    for gauge_cfg in ACTIVE_GAUGES:
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
    booster = load_production_model() if _ACTIVE_IDS else None

    for gauge_cfg in GAUGES:
        usgs_id = gauge_cfg["usgs_gauge_id"]
        gauge_id = get_gauge_id(usgs_id)
        forecast_weather = get_forecast_weather(gauge_id)

        if usgs_id in _ACTIVE_IDS:
            gauge_rows = get_recent_gauge_readings(gauge_id, days=1)
            if not gauge_rows:
                continue

            latest = gauge_rows[0]
            weather_history = get_recent_weather_readings(gauge_id, hours=2160)

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
                    model_version="production",
                )
        else:
            for weather_row in forecast_weather:
                target_datetime = weather_row["observed_at"]
                condition, confidence = score_weather_only(
                    air_temp_f=weather_row["air_temp_f"] or 55.0,
                    precip_mm=weather_row["precip_mm"] or 0.0,
                    precip_probability=weather_row["precip_probability"] or 0,
                    snowfall_mm=weather_row["snowfall_mm"] or 0.0,
                    wind_speed_mph=weather_row["wind_speed_mph"] or 0.0,
                )
                upsert_prediction(
                    gauge_id=gauge_id,
                    target_datetime=target_datetime,
                    condition=condition,
                    confidence=confidence,
                    is_forecast=weather_row["is_forecast"],
                    model_version="weather-rule-based",
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

- [ ] **Step 3: Run structural tests**

```
pytest pipeline/tests/test_flows.py -v
```
Expected: all 12 tests PASS

- [ ] **Step 4: Commit**

```bash
git add pipeline/flows/ingest_score.py
git commit -m "feat: route active/inactive gauges in ingest-score flow"
```

---

### Task 4: Update train flow

**Files:**
- Modify: `pipeline/flows/train.py`

- [ ] **Step 1: Update import and loop in train.py**

In `pipeline/flows/train.py`, change line 4:

```python
# Before
from config.rivers import GAUGES

# After
from config.rivers import ACTIVE_GAUGES
```

Change line 13:

```python
# Before
    for gauge_cfg in GAUGES:

# After
    for gauge_cfg in ACTIVE_GAUGES:
```

- [ ] **Step 2: Run structural tests**

```
pytest pipeline/tests/test_flows.py -v
```
Expected: all 12 tests PASS

- [ ] **Step 3: Commit**

```bash
git add pipeline/flows/train.py
git commit -m "feat: train only on active gauges"
```

---

### Task 5: Update backfill script

**Files:**
- Modify: `pipeline/scripts/backfill_weather_gauge.py`

- [ ] **Step 1: Update import line 23**

```python
# Before
from config.rivers import GAUGES

# After
from config.rivers import GAUGES, ACTIVE_GAUGES
```

- [ ] **Step 2: Replace the main() function**

```python
def main():
    parser = argparse.ArgumentParser(description="Backfill historical weather and gauge data")
    two_years_ago = (date.today() - timedelta(days=730)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    parser.add_argument("--start", default=two_years_ago, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=yesterday, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print(f"Backfilling weather for {len(GAUGES)} gauges ({start} → {end})")
    for i, gauge_cfg in enumerate(GAUGES, 1):
        name = gauge_cfg["name"]
        print(f"\n[{i}/{len(GAUGES)}] {name} — weather")
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        weather_count = backfill_weather(gauge_id, gauge_cfg["lat"], gauge_cfg["lon"], start, end)
        print(f"  {weather_count} weather rows")

    print(f"\nBackfilling gauge readings for {len(ACTIVE_GAUGES)} active gauges ({start} → {end})")
    for i, gauge_cfg in enumerate(ACTIVE_GAUGES, 1):
        name = gauge_cfg["name"]
        usgs_id = gauge_cfg["usgs_gauge_id"]
        print(f"\n[{i}/{len(ACTIVE_GAUGES)}] {name} ({usgs_id}) — gauge readings")
        gauge_id = get_gauge_id(usgs_id)
        gauge_count = backfill_gauge(gauge_id, usgs_id, start, end)
        print(f"  {gauge_count} gauge readings")

    print("\nBackfill complete.")
```

- [ ] **Step 3: Verify import**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
python -c "import sys; sys.path.insert(0, 'pipeline'); from scripts import backfill_weather_gauge; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pipeline/scripts/backfill_weather_gauge.py
git commit -m "feat: backfill weather for all gauges, gauge readings for active only"
```

---

### Task 6: Consolidate init_schema.sql

**Files:**
- Modify: `pipeline/sql/init_schema.sql`

The current `init_schema.sql` is stale — it predates the `migrate_hourly.sql` changes (`target_datetime` vs `date` column, extended `weather_readings`). A fresh `docker-compose down -v && up` would create the wrong schema. This task makes `init_schema.sql` the canonical current schema so the DB rebuild in Task 8 works correctly.

- [ ] **Step 1: Replace init_schema.sql with the canonical schema**

```sql
-- Gauge registry
CREATE TABLE IF NOT EXISTS gauges (
    id SERIAL PRIMARY KEY,
    usgs_gauge_id VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    river VARCHAR(100) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    flow_thresholds JSONB NOT NULL
);

-- Raw USGS readings (one row per gauge per fetch)
CREATE TABLE IF NOT EXISTS gauge_readings (
    id SERIAL PRIMARY KEY,
    gauge_id INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    flow_cfs DOUBLE PRECISION,
    water_temp_f DOUBLE PRECISION,
    gauge_height_ft DOUBLE PRECISION,
    UNIQUE(gauge_id, fetched_at)
);

CREATE INDEX IF NOT EXISTS idx_gauge_readings_gauge_fetched
    ON gauge_readings(gauge_id, fetched_at DESC);

-- Hourly weather readings
CREATE TABLE IF NOT EXISTS weather_readings (
    id                    SERIAL PRIMARY KEY,
    gauge_id              INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    observed_at           TIMESTAMP WITH TIME ZONE NOT NULL,
    precip_mm             DOUBLE PRECISION,
    precip_probability    INTEGER,
    air_temp_f            DOUBLE PRECISION,
    snowfall_mm           DOUBLE PRECISION,
    wind_speed_mph        DOUBLE PRECISION,
    weather_code          INTEGER,
    cloud_cover_pct       INTEGER,
    surface_pressure_hpa  DOUBLE PRECISION,
    is_forecast           BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(gauge_id, observed_at)
);

-- Hourly ML predictions
CREATE TABLE IF NOT EXISTS predictions (
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

CREATE INDEX IF NOT EXISTS idx_predictions_gauge_datetime
    ON predictions(gauge_id, target_datetime DESC);
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/sql/init_schema.sql
git commit -m "chore: consolidate migrate_hourly into init_schema as canonical schema"
```

---

### Task 7: API versioning and SQL bug fixes

**Files:**
- Create: `api/tests/test_routes.py`
- Modify: `api/main.py`
- Modify: `api/routes/rivers.py`

The routes file has two broken SQL column references that would cause all endpoints to fail at runtime: `p.date` and `wr.date` don't exist — the columns are `target_datetime` and `observed_at`. These are fixed in the same pass as versioning since we're touching the file anyway.

- [ ] **Step 1: Write failing tests**

```python
# api/tests/test_routes.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_versioned_list_rivers_route_exists():
    """Verify /api/v1/rivers is mounted (may 500 without DB — that's OK)."""
    response = client.get("/api/v1/rivers")
    assert response.status_code != 404


def test_versioned_get_river_route_exists():
    response = client.get("/api/v1/rivers/09035800")
    assert response.status_code != 404


def test_versioned_get_river_history_route_exists():
    response = client.get("/api/v1/rivers/09035800/history")
    assert response.status_code != 404


def test_old_api_prefix_not_mounted():
    """Confirm /api/rivers (unversioned) is no longer served."""
    response = client.get("/api/rivers")
    assert response.status_code == 404


def test_list_rivers_returns_list_shape():
    """With DB mocked, list endpoint returns expected shape."""
    mock_gauge = {
        "id": 1, "usgs_gauge_id": "09035800", "name": "Spinney",
        "river": "South Platte", "lat": 38.9, "lon": -105.5,
    }
    mock_pred = {1: {"condition": "Good", "confidence": 0.82}}
    with patch("api.routes.rivers.get_session") as mock_ctx:
        mock_session = MagicMock()
        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = [mock_gauge]
        mock_ctx.return_value.__enter__.return_value = mock_session
        with patch("api.routes.rivers.get_today_predictions", return_value=mock_pred):
            response = client.get("/api/v1/rivers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["gauge_id"] == "09035800"
    assert data[0]["condition"] == "Good"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/bryang/Dev_Space/ml_projects/riffle
pytest api/tests/test_routes.py -v
```
Expected: `test_old_api_prefix_not_mounted` PASSES (old prefix still live); the four `/api/v1/` tests FAIL with 404.

- [ ] **Step 3: Update api/main.py**

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes.rivers import router as rivers_router

app = FastAPI(title="Riffle API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(rivers_router, prefix="/api/v1")
```

- [ ] **Step 4: Fix SQL column references and update docstring in api/routes/rivers.py**

Replace the module docstring:
```python
"""FastAPI route handlers for river/gauge endpoints.

GET /api/v1/rivers                         — all gauges with today's condition
GET /api/v1/rivers/{gauge_id}              — current condition + 3-day forecast
GET /api/v1/rivers/{gauge_id}/history      — last 30 days of conditions + key stats
"""
```

Replace `get_today_predictions`:
```python
def get_today_predictions(session: Session) -> Dict[int, dict]:
    """Return {gauge_id: prediction_row} for today's non-forecast predictions."""
    rows = session.execute(
        text("""
            SELECT gauge_id, condition, confidence, is_forecast, model_version
            FROM predictions
            WHERE DATE(target_datetime) = CURRENT_DATE AND is_forecast = FALSE
        """)
    ).mappings().fetchall()
    return {r["gauge_id"]: dict(r) for r in rows if "gauge_id" in r}
```

Replace `get_gauge_forecast`:
```python
def get_gauge_forecast(session: Session, gauge_id_int: int) -> List[dict]:
    """Return today + 3 forecast day predictions for a gauge."""
    rows = session.execute(
        text("""
            SELECT p.target_datetime, p.condition, p.confidence, p.is_forecast,
                   gr.flow_cfs, gr.water_temp_f, gr.gauge_height_ft,
                   wr.precip_mm, wr.air_temp_f
            FROM predictions p
            LEFT JOIN LATERAL (
                SELECT flow_cfs, water_temp_f, gauge_height_ft
                FROM gauge_readings
                WHERE gauge_id = p.gauge_id
                ORDER BY fetched_at DESC
                LIMIT 1
            ) gr ON TRUE
            LEFT JOIN weather_readings wr
                ON wr.gauge_id = p.gauge_id
                AND DATE(wr.observed_at) = DATE(p.target_datetime)
            WHERE p.gauge_id = :gid
              AND DATE(p.target_datetime) >= CURRENT_DATE
              AND DATE(p.target_datetime) <= CURRENT_DATE + 3
            ORDER BY p.target_datetime
        """),
        {"gid": gauge_id_int},
    ).mappings().fetchall()
    return [dict(r) for r in rows]
```

Replace `get_gauge_history`:
```python
def get_gauge_history(session: Session, gauge_id_int: int) -> List[dict]:
    """Return last 30 days of predictions with key gauge stats."""
    rows = session.execute(
        text("""
            SELECT p.target_datetime, p.condition, p.confidence,
                   gr.flow_cfs, gr.water_temp_f
            FROM predictions p
            LEFT JOIN LATERAL (
                SELECT flow_cfs, water_temp_f
                FROM gauge_readings
                WHERE gauge_id = p.gauge_id
                  AND DATE(fetched_at) = DATE(p.target_datetime)
                ORDER BY fetched_at DESC
                LIMIT 1
            ) gr ON TRUE
            WHERE p.gauge_id = :gid
              AND DATE(p.target_datetime) >= CURRENT_DATE - 30
              AND p.is_forecast = FALSE
            ORDER BY p.target_datetime DESC
        """),
        {"gid": gauge_id_int},
    ).mappings().fetchall()
    return [dict(r) for r in rows]
```

In `get_river`, update forecast serialization to use `target_datetime`:
```python
"forecast": [
    {
        "date": str(f["target_datetime"]),
        "condition": f["condition"],
        "confidence": f["confidence"],
        "is_forecast": f["is_forecast"],
        "precip_mm": f.get("precip_mm"),
        "air_temp_f": f.get("air_temp_f"),
    }
    for f in forecast
],
```

In `get_river_history`, update history serialization:
```python
"history": [
    {
        "date": str(h["target_datetime"]),
        "condition": h["condition"],
        "confidence": h["confidence"],
        "flow_cfs": h.get("flow_cfs"),
        "water_temp_f": h.get("water_temp_f"),
    }
    for h in history
],
```

- [ ] **Step 5: Run API tests**

```
pytest api/tests/test_routes.py -v
```
Expected: all 5 tests PASS

- [ ] **Step 6: Run full test suite**

```
pytest pipeline/tests/ api/tests/ -v
```
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/routes/rivers.py api/tests/test_routes.py
git commit -m "feat: version API to /api/v1 and fix SQL column references in routes"
```

---

### Task 8: DB rebuild

This is an operational task — no code changes. Run after all code tasks are committed.

- [ ] **Step 1: Tear down postgres volume (wipes all data)**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle
docker-compose down -v
```

- [ ] **Step 2: Start postgres (init_schema.sql runs automatically)**

```bash
docker-compose up -d postgres
docker-compose ps   # wait until postgres status = healthy
```

- [ ] **Step 3: Seed the gauge registry**

```bash
USGS_API_KEY=<your-key> python pipeline/scripts/seed_db.py
```
Expected output: `Seeded 11 gauges.`

- [ ] **Step 4: Run the backfill**

Weather is backfilled for all 11 gauges; gauge readings for active gauges only (currently all 11).
This will take several minutes — 2 years of hourly data in 30-day and 180-day chunks.

```bash
USGS_API_KEY=<your-key> python pipeline/scripts/backfill_weather_gauge.py
```

To target a specific range instead of the default 2-year window:
```bash
USGS_API_KEY=<your-key> python pipeline/scripts/backfill_weather_gauge.py --start 2024-01-01 --end 2026-03-31
```

- [ ] **Step 5: Bring remaining services back up**

```bash
docker-compose up -d
```

---

## Self-Review

**Spec coverage:**
- ✅ `active` flag on every gauge entry in `config/rivers.py`
- ✅ `ACTIVE_GAUGES` derived list exported from config
- ✅ USGS gauge readings fetched only for active gauges (ingest_score, backfill)
- ✅ Weather fetched for all gauges (active and inactive need it)
- ✅ Inactive gauges scored via rule-based weather-only scorer with lower confidence ceiling
- ✅ `model_version="weather-rule-based"` distinguishes weather-only predictions from ML predictions
- ✅ Train flow uses only active gauges
- ✅ `init_schema.sql` consolidated — fresh DB rebuild produces correct schema
- ✅ API versioned to `/api/v1`
- ✅ Pre-existing broken SQL column refs fixed (`p.date` → `DATE(p.target_datetime)`, `wr.date` → `DATE(wr.observed_at)`)
- ✅ DB rebuild procedure documented

**Placeholder scan:** No TBDs, no "implement later", no "similar to Task N" references found.

**Type consistency:**
- `score_weather_only` returns `Tuple[str, float]`; consumed as `condition, confidence = score_weather_only(...)` in `ingest_score.py` — consistent.
- `ACTIVE_GAUGES` imported in `ingest_score.py`, `train.py`, `backfill_weather_gauge.py` — all use the same export from `config.rivers`.
- `target_datetime` used as column name in SQL and as dict key in serialization throughout `routes/rivers.py` — consistent.
