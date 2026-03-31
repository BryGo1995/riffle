# Hourly Weather & Gauge Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move weather ingestion to hourly resolution with expanded variables, restructure DAGs into a single hourly pipeline, and backfill 2 years of historical data.

**Architecture:** Drop and recreate `weather_readings` and `predictions` tables with timestamp-based keys. Update the weather client to support both forecast and historical Open-Meteo endpoints. Combine three daily DAGs into one hourly DAG. Add `fetch_gauge_reading_range` to the USGS client for backfill. A standalone backfill script populates 2 years of historical data.

**Tech Stack:** PostgreSQL 15, SQLAlchemy, Open-Meteo forecast + archive APIs, USGS IV API, Apache Airflow 2.9.3, XGBoost, pytest + responses

**Spec:** `docs/superpowers/specs/2026-03-31-hourly-weather-gauge-redesign.md`

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `pipeline/sql/init_schema.sql` | Canonical schema — hourly weather_readings + predictions |
| Create | `pipeline/sql/migrate_hourly.sql` | Drop/recreate weather_readings, predictions; add UNIQUE to gauge_readings |
| Modify | `pipeline/shared/weather_client.py` | WeatherHour dataclass, forecast + historical fetch functions |
| Modify | `pipeline/shared/usgs_client.py` | Add USGSReadingTimestamped + fetch_gauge_reading_range |
| Modify | `pipeline/shared/db_client.py` | Updated upsert_weather_reading, get_recent_weather_readings, get_forecast_weather, get_weather_for_hour, upsert_prediction, upsert_gauge_reading |
| Modify | `pipeline/plugins/features.py` | Hourly-aware compute_precip_72h, compute_days_since_precip, build_feature_vector |
| Modify | `pipeline/plugins/ml/train.py` | Updated FEATURE_COLS |
| Modify | `pipeline/dags/train_dag.py` | Hourly weather join, updated build_feature_vector call |
| Create | `pipeline/dags/ingest_score_dag.py` | Hourly DAG: parallel fetch_weather + fetch_gauge >> score_conditions |
| Delete | `pipeline/dags/gauge_ingest_dag.py` | Replaced by ingest_score_dag |
| Delete | `pipeline/dags/weather_ingest_dag.py` | Replaced by ingest_score_dag |
| Delete | `pipeline/dags/condition_score_dag.py` | Replaced by ingest_score_dag |
| Create | `pipeline/scripts/backfill_weather_gauge.py` | CLI backfill script |
| Modify | `pipeline/tests/test_weather_client.py` | Replace daily tests with hourly tests |
| Modify | `pipeline/tests/test_features.py` | Replace date-based tests with datetime-based tests |
| Modify | `pipeline/tests/test_db_client.py` | Update for new function signatures |
| Modify | `pipeline/tests/test_dags.py` | Replace old DAG tests with ingest_score DAG tests |

---

## Task 1: Schema Migration SQL

**Files:**
- Create: `pipeline/sql/migrate_hourly.sql`
- Modify: `pipeline/sql/init_schema.sql`

- [ ] **Step 1: Create migration script**

Create `pipeline/sql/migrate_hourly.sql`:

```sql
-- Drop tables that need schema changes (cascades to FK dependents)
DROP TABLE IF EXISTS predictions;
DROP TABLE IF EXISTS weather_readings;

-- Hourly weather readings
CREATE TABLE weather_readings (
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

-- Hourly predictions
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

CREATE INDEX idx_predictions_gauge_datetime
    ON predictions(gauge_id, target_datetime DESC);

-- Add uniqueness to gauge_readings for idempotent backfill
ALTER TABLE gauge_readings
    DROP CONSTRAINT IF EXISTS gauge_readings_gauge_id_fetched_at_key;
ALTER TABLE gauge_readings
    ADD CONSTRAINT gauge_readings_gauge_id_fetched_at_key UNIQUE (gauge_id, fetched_at);
```

- [ ] **Step 2: Update init_schema.sql to match**

Replace `pipeline/sql/init_schema.sql` with:

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

-- ML predictions (one row per gauge per target hour)
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

- [ ] **Step 3: Commit**

```bash
git add pipeline/sql/migrate_hourly.sql pipeline/sql/init_schema.sql
git commit -m "feat: add hourly schema migration SQL"
```

---

## Task 2: Weather Client — Hourly Forecast

**Files:**
- Modify: `pipeline/shared/weather_client.py`
- Modify: `pipeline/tests/test_weather_client.py`

- [ ] **Step 1: Write failing tests**

Replace the contents of `pipeline/tests/test_weather_client.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from datetime import datetime
from zoneinfo import ZoneInfo
from shared.weather_client import fetch_weather_forecast, WeatherHour

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MT = ZoneInfo("America/Denver")

MOCK_FORECAST = {
    "hourly": {
        "time": [
            "2026-03-31T07:00", "2026-03-31T08:00", "2026-03-31T09:00"
        ],
        "precipitation": [0.0, 1.2, 0.0],
        "precipitation_probability": [10, 40, 5],
        "temperature_2m": [45.0, 43.0, 48.0],
        "snowfall": [0.0, 0.0, 0.0],
        "wind_speed_10m": [5.0, 7.2, 4.1],
        "weather_code": [1, 61, 2],
        "cloud_cover": [20, 80, 30],
        "surface_pressure": [1013.0, 1011.5, 1012.0],
    }
}


@rsps.activate
def test_fetch_forecast_returns_weather_hours():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    assert len(results) == 3
    assert all(isinstance(r, WeatherHour) for r in results)


@rsps.activate
def test_fetch_forecast_first_hour_not_forecast():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    assert results[0].is_forecast is False


@rsps.activate
def test_fetch_forecast_remaining_hours_are_forecast():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    for r in results[1:]:
        assert r.is_forecast is True


@rsps.activate
def test_fetch_forecast_values_parsed_correctly():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    first = results[0]
    assert first.precip_mm == 0.0
    assert first.precip_probability == 10
    assert first.air_temp_f == 45.0
    assert first.snowfall_mm == 0.0
    assert first.wind_speed_mph == 5.0
    assert first.weather_code == 1
    assert first.cloud_cover_pct == 20
    assert first.surface_pressure_hpa == 1013.0


@rsps.activate
def test_fetch_forecast_observed_at_is_timezone_aware():
    rsps.add(rsps.GET, FORECAST_URL, json=MOCK_FORECAST, status=200)
    results = fetch_weather_forecast(lat=38.9097, lon=-105.5666)
    assert results[0].observed_at.tzinfo is not None


@rsps.activate
def test_fetch_forecast_raises_on_http_error():
    rsps.add(rsps.GET, FORECAST_URL, status=429)
    with pytest.raises(RuntimeError, match="Open-Meteo"):
        fetch_weather_forecast(lat=38.9097, lon=-105.5666)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_weather_client.py -v
```

Expected: `ImportError` — `fetch_weather_forecast` and `WeatherHour` not yet defined.

- [ ] **Step 3: Implement WeatherHour + fetch_weather_forecast**

Replace `pipeline/shared/weather_client.py` with:

```python
"""Open-Meteo weather client — forecast and historical.

fetch_weather_forecast: current hour + 72h forecast from Open-Meteo forecast API.
fetch_weather_historical: hourly historical data from Open-Meteo archive API.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MT = ZoneInfo("America/Denver")

HOURLY_VARS = (
    "precipitation,precipitation_probability,temperature_2m,"
    "snowfall,wind_speed_10m,weather_code,cloud_cover,surface_pressure"
)
HISTORICAL_VARS = (
    "precipitation,temperature_2m,snowfall,wind_speed_10m,"
    "weather_code,cloud_cover,surface_pressure"
)


@dataclass
class WeatherHour:
    observed_at: datetime
    precip_mm: float
    precip_probability: Optional[int]
    air_temp_f: float
    snowfall_mm: float
    wind_speed_mph: float
    weather_code: int
    cloud_cover_pct: int
    surface_pressure_hpa: float
    is_forecast: bool


def _parse_hourly(data: dict, has_precip_prob: bool) -> List[WeatherHour]:
    h = data["hourly"]
    times = h["time"]
    hours = []
    for i, t in enumerate(times):
        observed_at = datetime.fromisoformat(t).replace(tzinfo=MT)
        hours.append(WeatherHour(
            observed_at=observed_at,
            precip_mm=h["precipitation"][i] or 0.0,
            precip_probability=h["precipitation_probability"][i] if has_precip_prob else None,
            air_temp_f=h["temperature_2m"][i] if h["temperature_2m"][i] is not None else 0.0,
            snowfall_mm=h["snowfall"][i] or 0.0,
            wind_speed_mph=h["wind_speed_10m"][i] or 0.0,
            weather_code=int(h["weather_code"][i]) if h["weather_code"][i] is not None else 0,
            cloud_cover_pct=int(h["cloud_cover"][i]) if h["cloud_cover"][i] is not None else 0,
            surface_pressure_hpa=h["surface_pressure"][i] or 1013.25,
            is_forecast=(i > 0),
        ))
    return hours


def fetch_weather_forecast(lat: float, lon: float) -> List[WeatherHour]:
    """Fetch current hour + 72h forecast. First row is current (is_forecast=False)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_VARS,
        "forecast_hours": 73,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo forecast API returned {resp.status_code}")
    try:
        return _parse_hourly(resp.json(), has_precip_prob=True)
    except KeyError as e:
        raise RuntimeError(f"Open-Meteo forecast response missing key: {e}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_weather_client.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/shared/weather_client.py pipeline/tests/test_weather_client.py
git commit -m "feat: add WeatherHour dataclass and fetch_weather_forecast"
```

---

## Task 3: Weather Client — Historical

**Files:**
- Modify: `pipeline/shared/weather_client.py`
- Modify: `pipeline/tests/test_weather_client.py`

- [ ] **Step 1: Write failing tests**

Append to `pipeline/tests/test_weather_client.py`:

```python
from datetime import date
from shared.weather_client import fetch_weather_historical

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

MOCK_ARCHIVE = {
    "hourly": {
        "time": ["2024-03-31T00:00", "2024-03-31T01:00"],
        "precipitation": [0.5, 0.0],
        "temperature_2m": [38.0, 37.5],
        "snowfall": [0.0, 0.0],
        "wind_speed_10m": [3.0, 2.5],
        "weather_code": [2, 1],
        "cloud_cover": [40, 20],
        "surface_pressure": [1015.0, 1015.2],
    }
}


@rsps.activate
def test_fetch_historical_returns_weather_hours():
    rsps.add(rsps.GET, ARCHIVE_URL, json=MOCK_ARCHIVE, status=200)
    results = fetch_weather_historical(
        lat=38.9097, lon=-105.5666,
        start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
    )
    assert len(results) == 2
    assert all(isinstance(r, WeatherHour) for r in results)


@rsps.activate
def test_fetch_historical_precip_probability_is_none():
    rsps.add(rsps.GET, ARCHIVE_URL, json=MOCK_ARCHIVE, status=200)
    results = fetch_weather_historical(
        lat=38.9097, lon=-105.5666,
        start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
    )
    assert all(r.precip_probability is None for r in results)


@rsps.activate
def test_fetch_historical_all_rows_not_forecast():
    rsps.add(rsps.GET, ARCHIVE_URL, json=MOCK_ARCHIVE, status=200)
    results = fetch_weather_historical(
        lat=38.9097, lon=-105.5666,
        start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
    )
    assert all(r.is_forecast is False for r in results)


@rsps.activate
def test_fetch_historical_raises_on_http_error():
    rsps.add(rsps.GET, ARCHIVE_URL, status=500)
    with pytest.raises(RuntimeError, match="Open-Meteo"):
        fetch_weather_historical(
            lat=38.9097, lon=-105.5666,
            start_date=date(2024, 3, 31), end_date=date(2024, 3, 31),
        )
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_weather_client.py::test_fetch_historical_returns_weather_hours -v
```

Expected: `ImportError` — `fetch_weather_historical` not yet defined.

- [ ] **Step 3: Implement fetch_weather_historical**

Append to `pipeline/shared/weather_client.py`:

```python
from datetime import date as date_type


def fetch_weather_historical(
    lat: float,
    lon: float,
    start_date: date_type,
    end_date: date_type,
) -> List[WeatherHour]:
    """Fetch hourly historical data. precip_probability is None for all rows."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HISTORICAL_VARS,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo archive API returned {resp.status_code}")
    try:
        hours = _parse_hourly(resp.json(), has_precip_prob=False)
        # All historical rows are observed, not forecast
        for h in hours:
            h.is_forecast = False
        return hours
    except KeyError as e:
        raise RuntimeError(f"Open-Meteo archive response missing key: {e}")
```

- [ ] **Step 4: Run all weather client tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_weather_client.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/shared/weather_client.py pipeline/tests/test_weather_client.py
git commit -m "feat: add fetch_weather_historical to weather client"
```

---

## Task 4: USGS Client — Historical Range

**Files:**
- Modify: `pipeline/shared/usgs_client.py`
- Modify: `pipeline/tests/test_usgs_client.py`

- [ ] **Step 1: Read existing test file to understand pattern**

```bash
cat pipeline/tests/test_usgs_client.py
```

- [ ] **Step 2: Write failing test**

Append to `pipeline/tests/test_usgs_client.py`:

```python
from datetime import date, timezone
from shared.usgs_client import fetch_gauge_reading_range, USGSReadingTimestamped

MOCK_RANGE_RESPONSE = {
    "value": {
        "timeSeries": [
            {
                "variable": {"variableCode": [{"value": "00060"}]},
                "values": [{"value": [
                    {"value": "245.0", "dateTime": "2024-03-31T14:00:00.000-07:00"},
                    {"value": "248.0", "dateTime": "2024-03-31T15:00:00.000-07:00"},
                ]}],
            },
            {
                "variable": {"variableCode": [{"value": "00010"}]},
                "values": [{"value": [
                    {"value": "12.5", "dateTime": "2024-03-31T14:00:00.000-07:00"},
                    {"value": "12.6", "dateTime": "2024-03-31T15:00:00.000-07:00"},
                ]}],
            },
            {
                "variable": {"variableCode": [{"value": "00065"}]},
                "values": [{"value": [
                    {"value": "1.82", "dateTime": "2024-03-31T14:00:00.000-07:00"},
                    {"value": "1.85", "dateTime": "2024-03-31T15:00:00.000-07:00"},
                ]}],
            },
        ]
    }
}


@rsps.activate
def test_fetch_gauge_reading_range_returns_timestamped_readings():
    rsps.add(rsps.GET, USGS_IV_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert len(results) == 2
    assert all(isinstance(r, USGSReadingTimestamped) for r in results)


@rsps.activate
def test_fetch_gauge_reading_range_converts_temp_to_fahrenheit():
    rsps.add(rsps.GET, USGS_IV_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    # 12.5°C → 54.5°F
    assert results[0].water_temp_f == pytest.approx(54.5)


@rsps.activate
def test_fetch_gauge_reading_range_sorted_by_time():
    rsps.add(rsps.GET, USGS_IV_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert results[0].fetched_at < results[1].fetched_at


@rsps.activate
def test_fetch_gauge_reading_range_fetched_at_is_timezone_aware():
    rsps.add(rsps.GET, USGS_IV_URL, json=MOCK_RANGE_RESPONSE, status=200)
    results = fetch_gauge_reading_range(
        "09035800",
        start_date=date(2024, 3, 31),
        end_date=date(2024, 3, 31),
    )
    assert results[0].fetched_at.tzinfo is not None
```

Note: you will need to add `import pytest` and expose `USGS_IV_URL` in the test file. Check the existing imports at the top of `pipeline/tests/test_usgs_client.py` and add what's missing.

- [ ] **Step 3: Run to confirm failure**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_usgs_client.py::test_fetch_gauge_reading_range_returns_timestamped_readings -v
```

Expected: `ImportError` — `fetch_gauge_reading_range` and `USGSReadingTimestamped` not yet defined.

- [ ] **Step 4: Implement in usgs_client.py**

Append to `pipeline/shared/usgs_client.py` (after the existing imports and `USGSReading` dataclass):

```python
from datetime import date as date_type
from typing import List


@dataclass
class USGSReadingTimestamped:
    gauge_id: str
    fetched_at: datetime
    flow_cfs: Optional[float]
    water_temp_f: Optional[float]
    gauge_height_ft: Optional[float]


def fetch_gauge_reading_range(
    gauge_id: str,
    start_date: date_type,
    end_date: date_type,
) -> List[USGSReadingTimestamped]:
    """Fetch all instantaneous readings for a date range, sorted by time."""
    from datetime import timezone
    params = {
        "sites": gauge_id,
        "parameterCd": f"{PARAM_FLOW},{PARAM_TEMP},{PARAM_HEIGHT}",
        "startDT": start_date.isoformat(),
        "endDT": end_date.isoformat(),
        "format": "json",
        "siteStatus": "all",
    }
    resp = requests.get(USGS_IV_URL, params=params, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"USGS API returned {resp.status_code} for gauge {gauge_id}")

    series = resp.json()["value"]["timeSeries"]
    readings_by_time: dict = {}

    for ts in series:
        code = ts["variable"]["variableCode"][0]["value"]
        for entry in ts["values"][0]["value"]:
            dt_str = entry["dateTime"]
            try:
                val = float(entry["value"])
            except (ValueError, TypeError):
                val = None
            if dt_str not in readings_by_time:
                readings_by_time[dt_str] = {}
            readings_by_time[dt_str][code] = val

    results = []
    for dt_str, params_dict in readings_by_time.items():
        fetched_at = datetime.fromisoformat(dt_str)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        temp_c = params_dict.get(PARAM_TEMP)
        results.append(USGSReadingTimestamped(
            gauge_id=gauge_id,
            fetched_at=fetched_at,
            flow_cfs=params_dict.get(PARAM_FLOW),
            water_temp_f=(temp_c * 9 / 5 + 32) if temp_c is not None else None,
            gauge_height_ft=params_dict.get(PARAM_HEIGHT),
        ))

    return sorted(results, key=lambda r: r.fetched_at)
```

Note: add `from datetime import datetime` to the top of `usgs_client.py` if not already present.

- [ ] **Step 5: Run all USGS tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_usgs_client.py -v
```

Expected: all tests PASS (existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add pipeline/shared/usgs_client.py pipeline/tests/test_usgs_client.py
git commit -m "feat: add USGSReadingTimestamped and fetch_gauge_reading_range"
```

---

## Task 5: DB Client — Weather + Prediction Functions

**Files:**
- Modify: `pipeline/shared/db_client.py`
- Modify: `pipeline/tests/test_db_client.py`

- [ ] **Step 1: Write failing tests**

Replace `pipeline/tests/test_db_client.py` with:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from shared.db_client import (
    upsert_gauge_reading,
    upsert_weather_reading,
    upsert_prediction,
    get_gauge_id,
    get_recent_gauge_readings,
    get_recent_weather_readings,
    get_forecast_weather,
    get_weather_for_hour,
)

NOW = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def test_upsert_gauge_reading_executes(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_gauge_reading(
            gauge_id=1,
            fetched_at=NOW,
            flow_cfs=245.0,
            water_temp_f=54.5,
            gauge_height_ft=1.82,
        )
    mock_session.execute.assert_called_once()


def test_upsert_weather_reading_executes(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_weather_reading(
            gauge_id=1,
            observed_at=NOW,
            precip_mm=2.5,
            precip_probability=40,
            air_temp_f=55.0,
            snowfall_mm=0.0,
            wind_speed_mph=5.0,
            weather_code=61,
            cloud_cover_pct=80,
            surface_pressure_hpa=1011.5,
            is_forecast=False,
        )
    mock_session.execute.assert_called_once()


def test_upsert_weather_reading_accepts_none_precip_probability(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_weather_reading(
            gauge_id=1,
            observed_at=NOW,
            precip_mm=0.0,
            precip_probability=None,
            air_temp_f=40.0,
            snowfall_mm=0.0,
            wind_speed_mph=3.0,
            weather_code=1,
            cloud_cover_pct=10,
            surface_pressure_hpa=1015.0,
            is_forecast=False,
        )
    mock_session.execute.assert_called_once()


def test_upsert_prediction_executes(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_prediction(
            gauge_id=1,
            target_datetime=NOW,
            condition="Good",
            confidence=0.82,
            is_forecast=False,
            model_version="production",
        )
    mock_session.execute.assert_called_once()


def test_get_gauge_id_returns_id(mock_session):
    mock_session.execute.return_value.scalar_one.return_value = 7
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_gauge_id("09035800")
    assert result == 7


def test_get_recent_weather_readings_executes(mock_session):
    mock_session.execute.return_value.fetchall.return_value = []
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_recent_weather_readings(gauge_id=1, hours=2160)
    assert result == []
    mock_session.execute.assert_called_once()


def test_get_forecast_weather_executes(mock_session):
    mock_session.execute.return_value.fetchall.return_value = []
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_forecast_weather(gauge_id=1)
    assert result == []
    mock_session.execute.assert_called_once()


def test_get_weather_for_hour_returns_none_when_no_rows(mock_session):
    mock_session.execute.return_value.fetchone.return_value = None
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_weather_for_hour(gauge_id=1, observed_at=NOW)
    assert result is None
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_db_client.py -v
```

Expected: failures on `get_forecast_weather`, `get_weather_for_hour`, and changed signatures.

- [ ] **Step 3: Update db_client.py**

Replace the contents of `pipeline/shared/db_client.py` with:

```python
"""Postgres helpers for Riffle.

Uses raw SQL via SQLAlchemy text() for clarity and portability.
"""

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        url = os.environ["DATABASE_URL"]
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(_get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_gauge_id(usgs_gauge_id: str) -> int:
    with get_session() as session:
        return session.execute(
            text("SELECT id FROM gauges WHERE usgs_gauge_id = :gid"),
            {"gid": usgs_gauge_id},
        ).scalar_one()


def upsert_gauge_reading(
    gauge_id: int,
    fetched_at: datetime,
    flow_cfs: Optional[float],
    water_temp_f: Optional[float],
    gauge_height_ft: Optional[float],
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO gauge_readings (gauge_id, fetched_at, flow_cfs, water_temp_f, gauge_height_ft)
                VALUES (:gauge_id, :fetched_at, :flow_cfs, :water_temp_f, :gauge_height_ft)
                ON CONFLICT (gauge_id, fetched_at) DO NOTHING
            """),
            {
                "gauge_id": gauge_id,
                "fetched_at": fetched_at,
                "flow_cfs": flow_cfs,
                "water_temp_f": water_temp_f,
                "gauge_height_ft": gauge_height_ft,
            },
        )


def upsert_weather_reading(
    gauge_id: int,
    observed_at: datetime,
    precip_mm: float,
    precip_probability: Optional[int],
    air_temp_f: float,
    snowfall_mm: float,
    wind_speed_mph: float,
    weather_code: int,
    cloud_cover_pct: int,
    surface_pressure_hpa: float,
    is_forecast: bool,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO weather_readings (
                    gauge_id, observed_at, precip_mm, precip_probability,
                    air_temp_f, snowfall_mm, wind_speed_mph, weather_code,
                    cloud_cover_pct, surface_pressure_hpa, is_forecast
                )
                VALUES (
                    :gauge_id, :observed_at, :precip_mm, :precip_probability,
                    :air_temp_f, :snowfall_mm, :wind_speed_mph, :weather_code,
                    :cloud_cover_pct, :surface_pressure_hpa, :is_forecast
                )
                ON CONFLICT (gauge_id, observed_at)
                DO UPDATE SET
                    precip_mm = EXCLUDED.precip_mm,
                    precip_probability = EXCLUDED.precip_probability,
                    air_temp_f = EXCLUDED.air_temp_f,
                    snowfall_mm = EXCLUDED.snowfall_mm,
                    wind_speed_mph = EXCLUDED.wind_speed_mph,
                    weather_code = EXCLUDED.weather_code,
                    cloud_cover_pct = EXCLUDED.cloud_cover_pct,
                    surface_pressure_hpa = EXCLUDED.surface_pressure_hpa,
                    is_forecast = EXCLUDED.is_forecast
            """),
            {
                "gauge_id": gauge_id,
                "observed_at": observed_at,
                "precip_mm": precip_mm,
                "precip_probability": precip_probability,
                "air_temp_f": air_temp_f,
                "snowfall_mm": snowfall_mm,
                "wind_speed_mph": wind_speed_mph,
                "weather_code": weather_code,
                "cloud_cover_pct": cloud_cover_pct,
                "surface_pressure_hpa": surface_pressure_hpa,
                "is_forecast": is_forecast,
            },
        )


def upsert_prediction(
    gauge_id: int,
    target_datetime: datetime,
    condition: str,
    confidence: float,
    is_forecast: bool,
    model_version: str,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO predictions (gauge_id, target_datetime, condition, confidence, is_forecast, model_version)
                VALUES (:gauge_id, :target_datetime, :condition, :confidence, :is_forecast, :model_version)
                ON CONFLICT (gauge_id, target_datetime)
                DO UPDATE SET
                    condition = EXCLUDED.condition,
                    confidence = EXCLUDED.confidence,
                    is_forecast = EXCLUDED.is_forecast,
                    model_version = EXCLUDED.model_version,
                    scored_at = NOW()
            """),
            {
                "gauge_id": gauge_id,
                "target_datetime": target_datetime,
                "condition": condition,
                "confidence": confidence,
                "is_forecast": is_forecast,
                "model_version": model_version,
            },
        )


def get_recent_gauge_readings(gauge_id: int, days: int = 90) -> List[dict]:
    """Returns rows for the last `days` days, newest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT fetched_at, flow_cfs, water_temp_f, gauge_height_ft
                FROM gauge_readings
                WHERE gauge_id = :gauge_id
                  AND fetched_at >= NOW() - (:days * INTERVAL '1 day')
                ORDER BY fetched_at DESC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_recent_weather_readings(gauge_id: int, hours: int = 2160) -> List[dict]:
    """Returns hourly rows for the last `hours` hours, newest first. (2160 = 90 days)"""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_at, precip_mm, precip_probability, air_temp_f,
                       snowfall_mm, wind_speed_mph, weather_code,
                       cloud_cover_pct, surface_pressure_hpa, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND observed_at >= NOW() - (:hours * INTERVAL '1 hour')
                  AND is_forecast = FALSE
                ORDER BY observed_at DESC
            """),
            {"gauge_id": gauge_id, "hours": hours},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_forecast_weather(gauge_id: int) -> List[dict]:
    """Returns current hour + all is_forecast=True rows in the next 72 hours, oldest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT observed_at, precip_mm, precip_probability, air_temp_f,
                       snowfall_mm, wind_speed_mph, weather_code,
                       cloud_cover_pct, surface_pressure_hpa, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND observed_at >= DATE_TRUNC('hour', NOW())
                  AND observed_at <= NOW() + INTERVAL '72 hours'
                ORDER BY observed_at ASC
            """),
            {"gauge_id": gauge_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_weather_for_hour(gauge_id: int, observed_at: datetime) -> Optional[dict]:
    """Returns the weather row closest to the given hour, within ±2 hours."""
    hour = observed_at.replace(minute=0, second=0, microsecond=0)
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT observed_at, precip_mm, precip_probability, air_temp_f,
                       snowfall_mm, wind_speed_mph, weather_code,
                       cloud_cover_pct, surface_pressure_hpa, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND observed_at BETWEEN :low AND :high
                ORDER BY ABS(EXTRACT(EPOCH FROM (observed_at - :target))) ASC
                LIMIT 1
            """),
            {
                "gauge_id": gauge_id,
                "low": hour - timedelta(hours=2),
                "high": hour + timedelta(hours=2),
                "target": hour,
            },
        ).fetchone()
    return dict(row._mapping) if row else None
```

- [ ] **Step 4: Run tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_db_client.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/shared/db_client.py pipeline/tests/test_db_client.py
git commit -m "feat: update db_client for hourly weather schema"
```

---

## Task 6: Feature Engineering — Hourly

**Files:**
- Modify: `pipeline/plugins/features.py`
- Modify: `pipeline/tests/test_features.py`

- [ ] **Step 1: Write failing tests**

Replace `pipeline/tests/test_features.py` with:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
from datetime import datetime, timedelta, timezone
from plugins.features import build_feature_vector, compute_days_since_precip, compute_precip_72h

MT_OFFSET = timezone(timedelta(hours=-7))

def make_hour(dt: datetime, precip_mm: float) -> dict:
    return {
        "observed_at": dt,
        "precip_mm": precip_mm,
        "air_temp_f": 50.0,
        "precip_probability": None,
        "snowfall_mm": 0.0,
        "wind_speed_mph": 5.0,
        "weather_code": 1,
        "cloud_cover_pct": 20,
        "surface_pressure_hpa": 1013.0,
        "is_forecast": False,
    }

TARGET = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)

FEATURE_KEYS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "hour_of_day", "days_since_precip_event",
    "precip_probability", "snowfall_mm", "wind_speed_mph",
    "weather_code", "cloud_cover_pct", "surface_pressure_hpa",
]


def test_build_feature_vector_has_all_keys():
    history = [make_hour(TARGET - timedelta(hours=i), 0.0) for i in range(1, 5)]
    features = build_feature_vector(
        flow_cfs=245.0,
        gauge_height_ft=1.82,
        water_temp_f=54.5,
        air_temp_f=55.0,
        precip_24h_mm=0.0,
        target_datetime=TARGET,
        weather_history=history,
    )
    assert set(features.keys()) == set(FEATURE_KEYS)


def test_build_feature_vector_hour_of_day():
    history = [make_hour(TARGET - timedelta(hours=1), 0.0)]
    features = build_feature_vector(
        flow_cfs=100.0, gauge_height_ft=1.0, water_temp_f=50.0,
        air_temp_f=45.0, precip_24h_mm=0.0,
        target_datetime=TARGET, weather_history=history,
    )
    assert features["hour_of_day"] == TARGET.hour


def test_build_feature_vector_none_precip_probability_defaults_to_zero():
    history = [make_hour(TARGET - timedelta(hours=1), 0.0)]
    features = build_feature_vector(
        flow_cfs=100.0, gauge_height_ft=1.0, water_temp_f=50.0,
        air_temp_f=45.0, precip_24h_mm=0.0,
        target_datetime=TARGET, weather_history=history,
        precip_probability=None,
    )
    assert features["precip_probability"] == 0


def test_compute_precip_72h_sums_hourly_window():
    # 72 hours of 1mm/hr + 1 hour outside window
    history = [make_hour(TARGET - timedelta(hours=i), 1.0) for i in range(0, 75)]
    result = compute_precip_72h(history, TARGET)
    assert result == pytest.approx(73.0)  # hours 0 through 72 inclusive


def test_compute_precip_72h_excludes_outside_window():
    history = [
        make_hour(TARGET - timedelta(hours=73), 99.0),  # outside
        make_hour(TARGET - timedelta(hours=1), 2.0),
    ]
    result = compute_precip_72h(history, TARGET)
    assert result == pytest.approx(2.0)


def test_compute_days_since_precip_aggregates_daily():
    # Two hours on same day total >= 5mm — counts as one event
    event_day = TARGET - timedelta(days=3)
    history = [
        make_hour(event_day.replace(hour=10), 3.0),
        make_hour(event_day.replace(hour=11), 3.0),
        make_hour(TARGET - timedelta(hours=1), 0.0),
    ]
    result = compute_days_since_precip(history, TARGET)
    assert result == 3


def test_compute_days_since_precip_returns_sentinel_when_no_event():
    history = [make_hour(TARGET - timedelta(hours=i), 0.1) for i in range(1, 10)]
    result = compute_days_since_precip(history, TARGET, threshold_mm=5.0)
    assert result == 30
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_features.py -v
```

Expected: failures — `target_date` parameter gone, new keys missing, etc.

- [ ] **Step 3: Replace features.py**

Replace `pipeline/plugins/features.py` with:

```python
"""Feature engineering for Riffle ML model.

All features computed per gauge per target datetime (hourly).
weather_history is a list of dicts with key: observed_at (datetime), precip_mm (float).
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def compute_precip_72h(weather_history: List[Dict], target_datetime: datetime) -> float:
    """Sum precipitation over the 72 hours ending at target_datetime (inclusive)."""
    cutoff = target_datetime - timedelta(hours=72)
    return sum(
        row["precip_mm"] for row in weather_history
        if cutoff <= row["observed_at"] <= target_datetime
    )


def compute_days_since_precip(
    weather_history: List[Dict],
    target_datetime: datetime,
    threshold_mm: float = 5.0,
    sentinel: int = 30,
) -> int:
    """Days since last day whose cumulative hourly precip >= threshold_mm."""
    daily_totals: Dict = defaultdict(float)
    for row in weather_history:
        daily_totals[row["observed_at"].date()] += row["precip_mm"]

    target_date = target_datetime.date()
    events = [d for d, total in daily_totals.items() if total >= threshold_mm and d <= target_date]
    if not events:
        return sentinel
    return (target_date - max(events)).days


def build_feature_vector(
    flow_cfs: float,
    gauge_height_ft: float,
    water_temp_f: Optional[float],
    air_temp_f: float,
    precip_24h_mm: float,
    target_datetime: datetime,
    weather_history: List[Dict],
    precip_probability: Optional[int] = None,
    snowfall_mm: float = 0.0,
    wind_speed_mph: float = 0.0,
    weather_code: int = 0,
    cloud_cover_pct: int = 0,
    surface_pressure_hpa: float = 1013.25,
) -> Dict[str, Any]:
    """Build a single feature dict for XGBoost inference or training."""
    return {
        "flow_cfs": flow_cfs,
        "gauge_height_ft": gauge_height_ft,
        "water_temp_f": water_temp_f if water_temp_f is not None else 50.0,
        "precip_24h_mm": precip_24h_mm,
        "precip_72h_mm": compute_precip_72h(weather_history, target_datetime),
        "air_temp_f": air_temp_f,
        "day_of_year": target_datetime.timetuple().tm_yday,
        "hour_of_day": target_datetime.hour,
        "days_since_precip_event": compute_days_since_precip(weather_history, target_datetime),
        "precip_probability": precip_probability if precip_probability is not None else 0,
        "snowfall_mm": snowfall_mm,
        "wind_speed_mph": wind_speed_mph,
        "weather_code": weather_code,
        "cloud_cover_pct": cloud_cover_pct,
        "surface_pressure_hpa": surface_pressure_hpa,
    }
```

- [ ] **Step 4: Run tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_features.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/plugins/features.py pipeline/tests/test_features.py
git commit -m "feat: update feature engineering for hourly weather data"
```

---

## Task 7: Update FEATURE_COLS and train_dag

**Files:**
- Modify: `pipeline/plugins/ml/train.py`
- Modify: `pipeline/dags/train_dag.py`
- Modify: `pipeline/tests/test_train.py`

- [ ] **Step 1: Read existing test_train.py**

```bash
cat pipeline/tests/test_train.py
```

- [ ] **Step 2: Update FEATURE_COLS in train.py**

In `pipeline/plugins/ml/train.py`, replace the `FEATURE_COLS` list:

```python
FEATURE_COLS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "hour_of_day", "days_since_precip_event",
    "precip_probability", "snowfall_mm", "wind_speed_mph",
    "weather_code", "cloud_cover_pct", "surface_pressure_hpa",
]
```

- [ ] **Step 3: Run existing train tests to see what breaks**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_train.py -v
```

Review the failures and update test_train.py so test DataFrames include the new feature columns (`hour_of_day`, `precip_probability`, `snowfall_mm`, `wind_speed_mph`, `weather_code`, `cloud_cover_pct`, `surface_pressure_hpa`). Any test building a DataFrame with only the old FEATURE_COLS will need those columns added with sensible defaults (0 or 1013.25 for pressure).

- [ ] **Step 4: Fix test_train.py**

For each test that builds a DataFrame, add the missing columns. For example, if a test has:

```python
df = pd.DataFrame([{
    "flow_cfs": 200.0, "gauge_height_ft": 1.5, "water_temp_f": 52.0,
    "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 50.0,
    "day_of_year": 90, "days_since_precip_event": 5, "condition": "Good",
}])
```

Update it to:

```python
df = pd.DataFrame([{
    "flow_cfs": 200.0, "gauge_height_ft": 1.5, "water_temp_f": 52.0,
    "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 50.0,
    "day_of_year": 90, "hour_of_day": 8, "days_since_precip_event": 5,
    "precip_probability": 0, "snowfall_mm": 0.0, "wind_speed_mph": 5.0,
    "weather_code": 1, "cloud_cover_pct": 20, "surface_pressure_hpa": 1013.25,
    "condition": "Good",
}])
```

- [ ] **Step 5: Update train_dag.py**

Replace `pipeline/dags/train_dag.py` with:

```python
"""train_dag — Weekly, Monday 3:00am MT (9:00 UTC).

1. Pull historical gauge_readings + weather_readings from Postgres
2. Join on hour-truncated timestamp
3. Generate bootstrapped labels from domain thresholds
4. Train XGBoost classifier, log to MLflow
5. Promote best model to production in MLflow registry
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime
import pandas as pd
from airflow import DAG
from airflow.operators.python import PythonOperator

from config.rivers import GAUGES
from shared.db_client import get_gauge_id, get_recent_gauge_readings, get_recent_weather_readings
from plugins.ml.train import label_condition, train_model, FEATURE_COLS
from plugins.ml.score import promote_model_to_production
from plugins.features import build_feature_vector

default_args = {"owner": "riffle", "retries": 1}


def train_and_promote():
    records = []
    for gauge_cfg in GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_readings(gauge_id, days=365)
        weather_rows = get_recent_weather_readings(gauge_id, hours=365 * 24)

        # Key weather by hour-truncated timestamp for join
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


with DAG(
    dag_id="train",
    default_args=default_args,
    schedule_interval="0 9 * * 1",  # Monday 3:00am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ml", "training"],
) as dag:
    PythonOperator(
        task_id="train_and_promote",
        python_callable=train_and_promote,
    )
```

- [ ] **Step 6: Run train tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_train.py -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline/plugins/ml/train.py pipeline/dags/train_dag.py pipeline/tests/test_train.py
git commit -m "feat: update FEATURE_COLS and train_dag for hourly weather"
```

---

## Task 8: New Hourly DAG + Remove Old DAGs

**Files:**
- Create: `pipeline/dags/ingest_score_dag.py`
- Delete: `pipeline/dags/gauge_ingest_dag.py`
- Delete: `pipeline/dags/weather_ingest_dag.py`
- Delete: `pipeline/dags/condition_score_dag.py`
- Modify: `pipeline/tests/test_dags.py`

- [ ] **Step 1: Write failing DAG tests**

Replace `pipeline/tests/test_dags.py` with:

```python
import sys
sys.path.insert(0, "pipeline")
import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost/riffle")
os.environ.setdefault("MLFLOW_TRACKING_URI", "http://localhost:5000")
import pytest
from airflow.models import DagBag


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder="pipeline/dags", include_examples=False)


def test_ingest_score_dag_loads(dagbag):
    dag = dagbag.get_dag("ingest_score")
    assert dag is not None
    assert dagbag.import_errors == {}


def test_train_dag_loads(dagbag):
    dag = dagbag.get_dag("train")
    assert dag is not None


def test_ingest_score_dag_is_hourly(dagbag):
    dag = dagbag.get_dag("ingest_score")
    assert dag.schedule_interval == "0 * * * *"


def test_ingest_score_dag_has_expected_tasks(dagbag):
    dag = dagbag.get_dag("ingest_score")
    task_ids = {t.task_id for t in dag.tasks}
    assert task_ids == {"fetch_weather", "fetch_gauge", "score_conditions"}


def test_score_conditions_depends_on_both_ingest_tasks(dagbag):
    dag = dagbag.get_dag("ingest_score")
    score_task = dag.get_task("score_conditions")
    upstream_ids = {t.task_id for t in score_task.upstream_list}
    assert "fetch_weather" in upstream_ids
    assert "fetch_gauge" in upstream_ids


def test_old_dags_removed(dagbag):
    assert dagbag.get_dag("gauge_ingest") is None
    assert dagbag.get_dag("weather_ingest") is None
    assert dagbag.get_dag("condition_score") is None
```

- [ ] **Step 2: Run to confirm failures**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_dags.py -v
```

Expected: `ingest_score` DAG not found; old DAG tests still passing.

- [ ] **Step 3: Create ingest_score_dag.py**

Create `pipeline/dags/ingest_score_dag.py`:

```python
"""ingest_score_dag — Hourly.

Parallel ingest:
  fetch_weather  ──┐
                   ├──> score_conditions
  fetch_gauge    ──┘

score_conditions uses TriggerRule.ALL_DONE so scoring proceeds
even if one ingest fails, using the most recent data in the DB.
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime, timezone
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

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

default_args = {"owner": "riffle", "retries": 2}


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


with DAG(
    dag_id="ingest_score",
    default_args=default_args,
    schedule_interval="0 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ingest", "ml"],
) as dag:
    fetch_weather_task = PythonOperator(
        task_id="fetch_weather",
        python_callable=fetch_and_store_weather,
    )
    fetch_gauge_task = PythonOperator(
        task_id="fetch_gauge",
        python_callable=fetch_and_store_readings,
    )
    score_task = PythonOperator(
        task_id="score_conditions",
        python_callable=score_all_gauges,
        trigger_rule=TriggerRule.ALL_DONE,
    )
    [fetch_weather_task, fetch_gauge_task] >> score_task
```

- [ ] **Step 4: Delete old DAG files**

```bash
rm pipeline/dags/gauge_ingest_dag.py
rm pipeline/dags/weather_ingest_dag.py
rm pipeline/dags/condition_score_dag.py
```

- [ ] **Step 5: Run DAG tests**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/test_dags.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add pipeline/dags/ingest_score_dag.py pipeline/tests/test_dags.py
git rm pipeline/dags/gauge_ingest_dag.py pipeline/dags/weather_ingest_dag.py pipeline/dags/condition_score_dag.py
git commit -m "feat: add hourly ingest_score_dag, remove old daily DAGs"
```

---

## Task 9: Backfill Script

**Files:**
- Modify: `pipeline/shared/usgs_client.py` — already done in Task 4
- Create: `pipeline/scripts/backfill_weather_gauge.py`

- [ ] **Step 1: Create the backfill script**

Create `pipeline/scripts/backfill_weather_gauge.py`:

```python
"""Backfill historical weather and gauge readings.

Fetches 2 years of hourly data from Open-Meteo archive and USGS IV APIs.
Safe to re-run — all writes are idempotent upserts.

Usage:
  python pipeline/scripts/backfill_weather_gauge.py
  python pipeline/scripts/backfill_weather_gauge.py --start 2023-01-01 --end 2025-12-31
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, "pipeline")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost:5432/riffle")

from config.rivers import GAUGES
from shared.weather_client import fetch_weather_historical
from shared.usgs_client import fetch_gauge_reading_range
from shared.db_client import get_gauge_id, upsert_weather_reading, upsert_gauge_reading


def daterange_chunks(start: date, end: date, days: int):
    """Yield (chunk_start, chunk_end) tuples of at most `days` days."""
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def backfill_weather(gauge_id: int, lat: float, lon: float, start: date, end: date) -> int:
    total = 0
    for chunk_start, chunk_end in daterange_chunks(start, end, 180):
        print(f"    Weather {chunk_start} → {chunk_end}")
        hours = fetch_weather_historical(lat, lon, chunk_start, chunk_end)
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
                is_forecast=False,
            )
        total += len(hours)
        time.sleep(0.5)
    return total


def backfill_gauge(gauge_id: int, usgs_id: str, start: date, end: date) -> int:
    total = 0
    for chunk_start, chunk_end in daterange_chunks(start, end, 30):
        print(f"    Gauge {chunk_start} → {chunk_end}")
        readings = fetch_gauge_reading_range(usgs_id, chunk_start, chunk_end)
        for reading in readings:
            upsert_gauge_reading(
                gauge_id=gauge_id,
                fetched_at=reading.fetched_at,
                flow_cfs=reading.flow_cfs,
                water_temp_f=reading.water_temp_f,
                gauge_height_ft=reading.gauge_height_ft,
            )
        total += len(readings)
        time.sleep(0.5)
    return total


def main():
    parser = argparse.ArgumentParser(description="Backfill historical weather and gauge data")
    two_years_ago = (date.today() - timedelta(days=730)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    parser.add_argument("--start", default=two_years_ago, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=yesterday, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    total_gauges = len(GAUGES)

    print(f"Backfilling {start} → {end} for {total_gauges} gauges")

    for i, gauge_cfg in enumerate(GAUGES, 1):
        name = gauge_cfg["name"]
        usgs_id = gauge_cfg["usgs_gauge_id"]
        print(f"\n[{i}/{total_gauges}] {name} ({usgs_id})")

        gauge_id = get_gauge_id(usgs_id)

        weather_count = backfill_weather(gauge_id, gauge_cfg["lat"], gauge_cfg["lon"], start, end)
        gauge_count = backfill_gauge(gauge_id, usgs_id, start, end)

        print(f"  Done: {weather_count} weather rows, {gauge_count} gauge readings")

    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/scripts/backfill_weather_gauge.py
git commit -m "feat: add historical backfill script for weather and gauge data"
```

---

## Task 10: Run Migration and Full Test Suite

- [ ] **Step 1: Ensure postgres container is running**

```bash
docker compose ps postgres
```

Expected: `Up` and healthy.

- [ ] **Step 2: Run migration SQL**

```bash
docker compose exec postgres psql -U riffle -d riffle -f /dev/stdin < pipeline/sql/migrate_hourly.sql
```

Expected: output like:
```
DROP TABLE
CREATE TABLE
CREATE TABLE
CREATE INDEX
ALTER TABLE
ALTER TABLE
```

- [ ] **Step 3: Run full test suite**

```bash
cd /home/bryang/Dev_Space/ml_projects/riffle && pytest pipeline/tests/ -v --ignore=pipeline/tests/test_dags.py
```

Expected: all tests PASS. (test_dags.py excluded here — it requires a live Airflow environment.)

- [ ] **Step 4: Run the seed script to repopulate gauges table**

```bash
python pipeline/scripts/seed_db.py
```

Expected: `Seeded N gauges.`

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: run hourly schema migration"
```

---

## Post-Implementation: Run Backfill

After all tasks pass, run the backfill from the project root. This is a long-running operation (~10–30 minutes depending on gauge count):

```bash
python pipeline/scripts/backfill_weather_gauge.py
```

Monitor output for per-gauge progress. If it fails partway through, re-run — all writes are idempotent.
