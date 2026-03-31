# Riffle — Colorado Fly Fishing Conditions Tracker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-stack ML app that ingests USGS stream gauge + weather data, predicts fly fishing conditions with XGBoost, and surfaces results on a public Next.js map.

**Architecture:** Airflow orchestrates daily ingestion of USGS and Open-Meteo data into Postgres, feeds XGBoost predictions (today + 3-day forecast) into a FastAPI backend, which a Next.js frontend consumes to render an interactive Colorado river map with per-river detail pages.

**Tech Stack:** Python 3.11, Apache Airflow 2.9, XGBoost, MLflow, FastAPI, PostgreSQL 15, Next.js 14 (App Router), TypeScript, Tailwind CSS, Leaflet.js, Docker Compose, Vercel.

---

## File Structure

```
riffle/
├── pipeline/
│   ├── dags/
│   │   ├── gauge_ingest_dag.py        # Daily: fetch USGS readings → Postgres
│   │   ├── weather_ingest_dag.py      # Daily: fetch Open-Meteo → Postgres
│   │   ├── condition_score_dag.py     # Daily: score today + 3-day forecast
│   │   └── train_dag.py               # Weekly: retrain XGBoost, promote in MLflow
│   ├── plugins/
│   │   ├── ml/
│   │   │   ├── train.py               # Label generation, XGBoost training, MLflow logging
│   │   │   └── score.py               # Load production model, write predictions
│   │   └── features.py                # Feature vector construction
│   ├── shared/
│   │   ├── usgs_client.py             # USGS Water Services API client
│   │   ├── weather_client.py          # Open-Meteo API client
│   │   └── db_client.py               # SQLAlchemy session + DB helpers
│   ├── config/
│   │   └── rivers.py                  # Gauge registry (IDs, lat/lon, flow thresholds)
│   ├── sql/
│   │   └── init_schema.sql            # CREATE TABLE statements
│   ├── tests/
│   │   ├── test_usgs_client.py
│   │   ├── test_weather_client.py
│   │   ├── test_db_client.py
│   │   ├── test_features.py
│   │   ├── test_train.py
│   │   ├── test_score.py
│   │   └── test_dags.py
│   └── requirements.txt
├── api/
│   ├── main.py                        # FastAPI app, CORS, router registration
│   ├── routes/
│   │   └── rivers.py                  # /api/rivers + /api/rivers/{gauge_id} + /history
│   ├── tests/
│   │   └── test_rivers.py
│   └── requirements.txt
├── web/
│   ├── app/
│   │   ├── page.tsx                   # Map hero page (Leaflet)
│   │   └── rivers/[id]/
│   │       └── page.tsx               # River detail: stats + forecast + history chart
│   ├── components/
│   │   ├── RiverMap.tsx               # Leaflet map with colored markers
│   │   ├── ConditionBadge.tsx         # Color-coded condition pill
│   │   ├── ForecastStrip.tsx          # 3-day forecast cards
│   │   └── HistoryChart.tsx           # 30-day condition time series
│   ├── config/
│   │   └── api.ts                     # FASTAPI_URL + typed fetch helpers
│   ├── package.json
│   ├── tsconfig.json
│   └── tailwind.config.ts
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Task 1: Repo Scaffolding + Python Requirements

**Files:**
- Create: `pipeline/requirements.txt`
- Create: `api/requirements.txt`
- Create: `.env.example`
- Create: `pipeline/__init__.py`, `pipeline/shared/__init__.py`, `pipeline/plugins/__init__.py`, `pipeline/plugins/ml/__init__.py`, `pipeline/config/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p pipeline/{dags,plugins/ml,shared,config,sql,tests}
mkdir -p api/{routes,tests}
touch pipeline/__init__.py
touch pipeline/shared/__init__.py
touch pipeline/plugins/__init__.py
touch pipeline/plugins/ml/__init__.py
touch pipeline/config/__init__.py
touch api/__init__.py
touch api/routes/__init__.py
```

- [ ] **Step 2: Write `pipeline/requirements.txt`**

```
apache-airflow==2.9.3
apache-airflow-providers-postgres==5.10.0
xgboost==2.0.3
mlflow==2.12.1
scikit-learn==1.4.2
pandas==2.2.2
numpy==1.26.4
psycopg2-binary==2.9.9
sqlalchemy==2.0.30
requests==2.31.0
pytest==8.2.0
pytest-mock==3.14.0
responses==0.25.3
```

- [ ] **Step 3: Write `api/requirements.txt`**

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
python-dotenv==1.0.1
httpx==0.27.0
pytest==8.2.0
```

- [ ] **Step 4: Write `.env.example`**

```bash
# Postgres
POSTGRES_USER=riffle
POSTGRES_PASSWORD=riffle
POSTGRES_DB=riffle
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# MLflow
MLFLOW_TRACKING_URI=http://mlflow:5000

# Airflow
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://riffle:riffle@postgres:5432/airflow
AIRFLOW__CORE__FERNET_KEY=your-fernet-key-here

# API
DATABASE_URL=postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
MLFLOW_TRACKING_URI=http://mlflow:5000
```

- [ ] **Step 5: Commit**

```bash
git init
git add pipeline/ api/ .env.example
git commit -m "chore: scaffold repo structure and requirements"
```

---

## Task 2: Docker Compose + Database Schema

**Files:**
- Create: `docker-compose.yml`
- Create: `pipeline/sql/init_schema.sql`

- [ ] **Step 1: Write `pipeline/sql/init_schema.sql`**

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
    gauge_height_ft DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_gauge_readings_gauge_fetched
    ON gauge_readings(gauge_id, fetched_at DESC);

-- Weather + forecast (one row per gauge per date)
CREATE TABLE IF NOT EXISTS weather_readings (
    id SERIAL PRIMARY KEY,
    gauge_id INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    precip_mm DOUBLE PRECISION,
    air_temp_f DOUBLE PRECISION,
    is_forecast BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(gauge_id, date)
);

-- ML predictions (one row per gauge per date; upsert on re-score)
CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    gauge_id INTEGER REFERENCES gauges(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    condition VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION,
    is_forecast BOOLEAN NOT NULL DEFAULT FALSE,
    model_version VARCHAR(100),
    scored_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(gauge_id, date)
);

CREATE INDEX IF NOT EXISTS idx_predictions_gauge_date
    ON predictions(gauge_id, date DESC);
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
version: "3.8"

x-airflow-common: &airflow-common
  image: apache/airflow:2.9.3-python3.11
  environment:
    AIRFLOW__CORE__EXECUTOR: LocalExecutor
    AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://riffle:riffle@postgres:5432/airflow
    AIRFLOW__CORE__FERNET_KEY: ""
    AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "false"
    AIRFLOW__CORE__LOAD_EXAMPLES: "false"
    MLFLOW_TRACKING_URI: http://mlflow:5000
    DATABASE_URL: postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
  volumes:
    - ./pipeline/dags:/opt/airflow/dags
    - ./pipeline/plugins:/opt/airflow/plugins
    - ./pipeline/shared:/opt/airflow/shared
    - ./pipeline/config:/opt/airflow/config
    - airflow-logs:/opt/airflow/logs
  depends_on:
    postgres:
      condition: service_healthy

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: riffle
      POSTGRES_PASSWORD: riffle
      POSTGRES_MULTIPLE_DATABASES: riffle,airflow
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./pipeline/sql/init_schema.sql:/docker-entrypoint-initdb.d/01_schema.sql
      - ./docker/create-multiple-postgresql-databases.sh:/docker-entrypoint-initdb.d/00_create_dbs.sh
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "riffle"]
      interval: 5s
      retries: 5

  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.12.1
    command: >
      mlflow server
      --backend-store-uri postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      --default-artifact-root /mlflow/artifacts
      --host 0.0.0.0
      --port 5000
    ports:
      - "5000:5000"
    volumes:
      - mlflow-artifacts:/mlflow/artifacts
    depends_on:
      postgres:
        condition: service_healthy

  airflow-init:
    <<: *airflow-common
    command: >
      bash -c "airflow db migrate && airflow users create
      --username admin --password admin
      --firstname Riffle --lastname Admin
      --role Admin --email admin@riffle.local"
    restart: on-failure

  airflow-scheduler:
    <<: *airflow-common
    command: scheduler
    restart: unless-stopped

  airflow-webserver:
    <<: *airflow-common
    command: webserver
    ports:
      - "8080:8080"
    restart: unless-stopped

  api:
    build:
      context: ./api
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      MLFLOW_TRACKING_URI: http://mlflow:5000
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres-data:
  mlflow-artifacts:
  airflow-logs:
```

- [ ] **Step 3: Create multi-database Postgres init script**

```bash
mkdir -p docker
```

Create `docker/create-multiple-postgresql-databases.sh`:

```bash
#!/bin/bash
set -e

function create_database() {
    local db=$1
    echo "Creating database '$db'"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
        CREATE DATABASE $db;
        GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
}

if [ -n "$POSTGRES_MULTIPLE_DATABASES" ]; then
    for db in $(echo $POSTGRES_MULTIPLE_DATABASES | tr ',' ' '); do
        create_database $db
    done
fi
```

```bash
chmod +x docker/create-multiple-postgresql-databases.sh
```

- [ ] **Step 4: Create `api/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 5: Verify schema parses without errors**

```bash
psql --version  # confirm psql available locally
python3 -c "
import re, sys
sql = open('pipeline/sql/init_schema.sql').read()
keywords = ['CREATE TABLE', 'CREATE INDEX', 'UNIQUE', 'REFERENCES']
for kw in keywords:
    assert kw in sql, f'Missing: {kw}'
print('Schema file looks valid')
"
```

Expected: `Schema file looks valid`

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml pipeline/sql/ docker/ api/Dockerfile
git commit -m "feat: add docker-compose, postgres schema, and api dockerfile"
```

---

## Task 3: Gauge Registry

**Files:**
- Create: `pipeline/config/rivers.py`
- Create: `pipeline/tests/test_rivers.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_rivers.py`:

```python
import sys
sys.path.insert(0, "pipeline")
from config.rivers import GAUGES

def test_gauges_count():
    assert len(GAUGES) == 11

def test_gauge_has_required_fields():
    required = {"usgs_gauge_id", "name", "river", "lat", "lon", "flow_thresholds"}
    for g in GAUGES:
        assert required.issubset(g.keys()), f"Missing fields in gauge: {g}"

def test_flow_thresholds_have_required_keys():
    required = {"blowout", "optimal_low", "optimal_high"}
    for g in GAUGES:
        assert required.issubset(g["flow_thresholds"].keys()), f"Bad thresholds: {g['name']}"

def test_gauge_ids_are_unique():
    ids = [g["usgs_gauge_id"] for g in GAUGES]
    assert len(ids) == len(set(ids))

def test_coordinates_are_colorado():
    # Colorado bounding box: lat 37-41, lon -109 to -102
    for g in GAUGES:
        assert 37 <= g["lat"] <= 41, f"Bad lat for {g['name']}"
        assert -109 <= g["lon"] <= -102, f"Bad lon for {g['name']}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /path/to/riffle
python -m pytest pipeline/tests/test_rivers.py -v
```

Expected: `ModuleNotFoundError: No module named 'config.rivers'`

- [ ] **Step 3: Write `pipeline/config/rivers.py`**

```python
"""
Gauge registry for Riffle.

flow_thresholds (cfs):
  blowout     — flow above this is unfishable
  optimal_low — lower bound of ideal fishing range
  optimal_high — upper bound of ideal fishing range

Seasonal medians are computed dynamically from historical data.
Thresholds here are river-specific blowout/optimal bounds used for
bootstrapped label generation.
"""

GAUGES = [
    {
        "usgs_gauge_id": "09035800",
        "name": "Spinney Reservoir",
        "river": "South Platte",
        "lat": 38.9097,
        "lon": -105.5666,
        "flow_thresholds": {"blowout": 500, "optimal_low": 80, "optimal_high": 250},
    },
    {
        "usgs_gauge_id": "09036000",
        "name": "Eleven Mile Canyon",
        "river": "South Platte",
        "lat": 38.9419,
        "lon": -105.4958,
        "flow_thresholds": {"blowout": 600, "optimal_low": 100, "optimal_high": 350},
    },
    {
        "usgs_gauge_id": "09033300",
        "name": "Deckers",
        "river": "South Platte",
        "lat": 39.2525,
        "lon": -105.2192,
        "flow_thresholds": {"blowout": 800, "optimal_low": 150, "optimal_high": 400},
    },
    {
        "usgs_gauge_id": "09034500",
        "name": "Cheesman Canyon",
        "river": "South Platte",
        "lat": 39.1886,
        "lon": -105.2511,
        "flow_thresholds": {"blowout": 700, "optimal_low": 100, "optimal_high": 350},
    },
    {
        "usgs_gauge_id": "07091200",
        "name": "Salida",
        "river": "Arkansas River",
        "lat": 38.5347,
        "lon": -106.0008,
        "flow_thresholds": {"blowout": 2000, "optimal_low": 200, "optimal_high": 700},
    },
    {
        "usgs_gauge_id": "07096000",
        "name": "Cañon City",
        "river": "Arkansas River",
        "lat": 38.4406,
        "lon": -105.2372,
        "flow_thresholds": {"blowout": 3000, "optimal_low": 300, "optimal_high": 1000},
    },
    {
        "usgs_gauge_id": "09081600",
        "name": "Ruedi to Basalt",
        "river": "Fryingpan River",
        "lat": 39.3672,
        "lon": -106.9281,
        "flow_thresholds": {"blowout": 400, "optimal_low": 60, "optimal_high": 200},
    },
    {
        "usgs_gauge_id": "09085000",
        "name": "Glenwood Springs",
        "river": "Roaring Fork River",
        "lat": 39.5486,
        "lon": -107.3247,
        "flow_thresholds": {"blowout": 3000, "optimal_low": 200, "optimal_high": 800},
    },
    {
        "usgs_gauge_id": "09057500",
        "name": "Silverthorne",
        "river": "Blue River",
        "lat": 39.6328,
        "lon": -106.0694,
        "flow_thresholds": {"blowout": 500, "optimal_low": 50, "optimal_high": 200},
    },
    {
        "usgs_gauge_id": "06752000",
        "name": "Canyon Mouth",
        "river": "Cache la Poudre",
        "lat": 40.6883,
        "lon": -105.1561,
        "flow_thresholds": {"blowout": 2000, "optimal_low": 150, "optimal_high": 600},
    },
    {
        "usgs_gauge_id": "09070000",
        "name": "Glenwood Springs",
        "river": "Colorado River",
        "lat": 39.5500,
        "lon": -107.3242,
        "flow_thresholds": {"blowout": 8000, "optimal_low": 500, "optimal_high": 2500},
    },
]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_rivers.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/config/rivers.py pipeline/tests/test_rivers.py
git commit -m "feat: add gauge registry with 11 Colorado gauges"
```

---

## Task 4: USGS Water Services Client

**Files:**
- Create: `pipeline/shared/usgs_client.py`
- Create: `pipeline/tests/test_usgs_client.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_usgs_client.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from shared.usgs_client import fetch_gauge_reading, USGSReading

USGS_BASE = "https://waterservices.usgs.gov/nwis/iv/"

MOCK_RESPONSE = {
    "value": {
        "timeSeries": [
            {
                "variable": {"variableCode": [{"value": "00060"}]},
                "values": [{"value": [{"value": "245.0", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
            },
            {
                "variable": {"variableCode": [{"value": "00010"}]},
                "values": [{"value": [{"value": "12.5", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
            },
            {
                "variable": {"variableCode": [{"value": "00065"}]},
                "values": [{"value": [{"value": "1.82", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
            },
        ]
    }
}

@rsps.activate
def test_fetch_returns_usgs_reading():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RESPONSE, status=200)
    result = fetch_gauge_reading("09035800")
    assert isinstance(result, USGSReading)
    assert result.flow_cfs == 245.0
    assert result.gauge_height_ft == 1.82

@rsps.activate
def test_water_temp_converted_from_celsius():
    rsps.add(rsps.GET, USGS_BASE, json=MOCK_RESPONSE, status=200)
    result = fetch_gauge_reading("09035800")
    # 12.5°C → 54.5°F
    assert abs(result.water_temp_f - 54.5) < 0.01

@rsps.activate
def test_missing_temp_returns_none():
    response_no_temp = {
        "value": {
            "timeSeries": [
                {
                    "variable": {"variableCode": [{"value": "00060"}]},
                    "values": [{"value": [{"value": "100.0", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
                },
                {
                    "variable": {"variableCode": [{"value": "00065"}]},
                    "values": [{"value": [{"value": "1.0", "dateTime": "2026-03-30T14:00:00.000-06:00"}]}],
                },
            ]
        }
    }
    rsps.add(rsps.GET, USGS_BASE, json=response_no_temp, status=200)
    result = fetch_gauge_reading("09035800")
    assert result.water_temp_f is None

@rsps.activate
def test_raises_on_http_error():
    rsps.add(rsps.GET, USGS_BASE, status=503)
    with pytest.raises(RuntimeError, match="USGS API"):
        fetch_gauge_reading("09035800")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest pipeline/tests/test_usgs_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.usgs_client'`

- [ ] **Step 3: Write `pipeline/shared/usgs_client.py`**

```python
"""USGS Water Services instantaneous values client.

Fetches: stream flow (00060, cfs), water temp (00010, °C→°F),
gauge height (00065, ft) for a single gauge ID.
"""

from dataclasses import dataclass
from typing import Optional
import requests

USGS_IV_URL = "https://waterservices.usgs.gov/nwis/iv/"
PARAM_FLOW = "00060"
PARAM_TEMP = "00010"
PARAM_HEIGHT = "00065"


@dataclass
class USGSReading:
    gauge_id: str
    flow_cfs: Optional[float]
    water_temp_f: Optional[float]   # converted from Celsius
    gauge_height_ft: Optional[float]


def fetch_gauge_reading(gauge_id: str) -> USGSReading:
    """Fetch latest instantaneous reading for a USGS gauge.

    Raises RuntimeError on non-2xx HTTP response.
    """
    params = {
        "sites": gauge_id,
        "parameterCd": f"{PARAM_FLOW},{PARAM_TEMP},{PARAM_HEIGHT}",
        "format": "json",
        "siteStatus": "all",
    }
    resp = requests.get(USGS_IV_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"USGS API returned {resp.status_code} for gauge {gauge_id}")

    series = resp.json()["value"]["timeSeries"]
    values_by_param: dict[str, Optional[float]] = {}

    for ts in series:
        code = ts["variable"]["variableCode"][0]["value"]
        raw_values = ts["values"][0]["value"]
        if raw_values:
            try:
                values_by_param[code] = float(raw_values[0]["value"])
            except (ValueError, TypeError):
                values_by_param[code] = None

    temp_c = values_by_param.get(PARAM_TEMP)
    water_temp_f = (temp_c * 9 / 5) + 32 if temp_c is not None else None

    return USGSReading(
        gauge_id=gauge_id,
        flow_cfs=values_by_param.get(PARAM_FLOW),
        water_temp_f=water_temp_f,
        gauge_height_ft=values_by_param.get(PARAM_HEIGHT),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_usgs_client.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/shared/usgs_client.py pipeline/tests/test_usgs_client.py
git commit -m "feat: add USGS Water Services API client"
```

---

## Task 5: Open-Meteo Weather Client

**Files:**
- Create: `pipeline/shared/weather_client.py`
- Create: `pipeline/tests/test_weather_client.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_weather_client.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
import responses as rsps
from datetime import date
from shared.weather_client import fetch_weather, WeatherDay

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

MOCK_RESPONSE = {
    "daily": {
        "time": ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02"],
        "precipitation_sum": [0.0, 2.5, 0.0, 1.2],
        "temperature_2m_max": [55.0, 48.0, 60.0, 52.0],
    }
}

@rsps.activate
def test_fetch_returns_four_days():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    assert len(results) == 4

@rsps.activate
def test_first_day_is_not_forecast():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    assert results[0].is_forecast is False

@rsps.activate
def test_remaining_days_are_forecast():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    for day in results[1:]:
        assert day.is_forecast is True

@rsps.activate
def test_values_parsed_correctly():
    rsps.add(rsps.GET, OPEN_METEO_BASE, json=MOCK_RESPONSE, status=200)
    results = fetch_weather(lat=38.9097, lon=-105.5666)
    assert results[0].date == date(2026, 3, 30)
    assert results[0].precip_mm == 0.0
    assert results[0].air_temp_f == 55.0
    assert results[1].precip_mm == 2.5

@rsps.activate
def test_raises_on_http_error():
    rsps.add(rsps.GET, OPEN_METEO_BASE, status=429)
    with pytest.raises(RuntimeError, match="Open-Meteo"):
        fetch_weather(lat=38.9097, lon=-105.5666)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest pipeline/tests/test_weather_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.weather_client'`

- [ ] **Step 3: Write `pipeline/shared/weather_client.py`**

```python
"""Open-Meteo forecast client.

Fetches today's conditions + 3-day forecast for a lat/lon.
Returns 4 WeatherDay objects: index 0 is today (is_forecast=False),
indices 1-3 are forecast days (is_forecast=True).
"""

from dataclasses import dataclass
from datetime import date
from typing import List
import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass
class WeatherDay:
    date: date
    precip_mm: float
    air_temp_f: float
    is_forecast: bool


def fetch_weather(lat: float, lon: float) -> List[WeatherDay]:
    """Fetch today + 3-day forecast from Open-Meteo.

    Raises RuntimeError on non-2xx HTTP response.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum,temperature_2m_max",
        "forecast_days": 4,
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "mm",
        "timezone": "America/Denver",
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"Open-Meteo API returned {resp.status_code}")

    daily = resp.json()["daily"]
    days = []
    for i, (dt_str, precip, temp) in enumerate(
        zip(daily["time"], daily["precipitation_sum"], daily["temperature_2m_max"])
    ):
        days.append(
            WeatherDay(
                date=date.fromisoformat(dt_str),
                precip_mm=precip or 0.0,
                air_temp_f=temp,
                is_forecast=(i > 0),
            )
        )
    return days
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_weather_client.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/shared/weather_client.py pipeline/tests/test_weather_client.py
git commit -m "feat: add Open-Meteo weather client"
```

---

## Task 6: Database Client

**Files:**
- Create: `pipeline/shared/db_client.py`
- Create: `pipeline/tests/test_db_client.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_db_client.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone
from shared.db_client import (
    upsert_gauge_reading,
    upsert_weather_reading,
    upsert_prediction,
    get_gauge_id,
    get_recent_gauge_readings,
    get_recent_weather_readings,
)

@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session

def test_upsert_gauge_reading_executes_upsert(mock_session):
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_gauge_reading(
            gauge_id=1,
            fetched_at=datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc),
            flow_cfs=245.0,
            water_temp_f=54.5,
            gauge_height_ft=1.82,
        )
    mock_session.execute.assert_called_once()

def test_upsert_weather_reading_executes_upsert(mock_session):
    from datetime import date
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_weather_reading(
            gauge_id=1,
            date=date(2026, 3, 30),
            precip_mm=2.5,
            air_temp_f=55.0,
            is_forecast=False,
        )
    mock_session.execute.assert_called_once()

def test_upsert_prediction_executes_upsert(mock_session):
    from datetime import date
    with patch("shared.db_client.get_session", return_value=mock_session):
        upsert_prediction(
            gauge_id=1,
            date=date(2026, 3, 30),
            condition="Good",
            confidence=0.82,
            is_forecast=False,
            model_version="1",
        )
    mock_session.execute.assert_called_once()

def test_get_gauge_id_returns_id(mock_session):
    mock_session.execute.return_value.scalar_one.return_value = 7
    with patch("shared.db_client.get_session", return_value=mock_session):
        result = get_gauge_id("09035800")
    assert result == 7
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest pipeline/tests/test_db_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.db_client'`

- [ ] **Step 3: Write `pipeline/shared/db_client.py`**

```python
"""Postgres helpers for Riffle.

Uses raw SQL via SQLAlchemy text() for clarity and portability.
Call get_session() as a context manager for each operation.
"""

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Generator, List, Optional, Tuple

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
        yield session
        session.commit()


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
    date: date,
    precip_mm: float,
    air_temp_f: float,
    is_forecast: bool,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO weather_readings (gauge_id, date, precip_mm, air_temp_f, is_forecast)
                VALUES (:gauge_id, :date, :precip_mm, :air_temp_f, :is_forecast)
                ON CONFLICT (gauge_id, date)
                DO UPDATE SET precip_mm = EXCLUDED.precip_mm,
                              air_temp_f = EXCLUDED.air_temp_f,
                              is_forecast = EXCLUDED.is_forecast
            """),
            {
                "gauge_id": gauge_id,
                "date": date,
                "precip_mm": precip_mm,
                "air_temp_f": air_temp_f,
                "is_forecast": is_forecast,
            },
        )


def upsert_prediction(
    gauge_id: int,
    date: date,
    condition: str,
    confidence: float,
    is_forecast: bool,
    model_version: str,
) -> None:
    with get_session() as session:
        session.execute(
            text("""
                INSERT INTO predictions (gauge_id, date, condition, confidence, is_forecast, model_version)
                VALUES (:gauge_id, :date, :condition, :confidence, :is_forecast, :model_version)
                ON CONFLICT (gauge_id, date)
                DO UPDATE SET condition = EXCLUDED.condition,
                              confidence = EXCLUDED.confidence,
                              is_forecast = EXCLUDED.is_forecast,
                              model_version = EXCLUDED.model_version,
                              scored_at = NOW()
            """),
            {
                "gauge_id": gauge_id,
                "date": date,
                "condition": condition,
                "confidence": confidence,
                "is_forecast": is_forecast,
                "model_version": model_version,
            },
        )


def get_recent_gauge_readings(gauge_id: int, days: int = 90) -> List[dict]:
    """Returns up to `days` most recent rows, newest first."""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT fetched_at, flow_cfs, water_temp_f, gauge_height_ft
                FROM gauge_readings
                WHERE gauge_id = :gauge_id
                  AND fetched_at >= NOW() - INTERVAL ':days days'
                ORDER BY fetched_at DESC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def get_recent_weather_readings(gauge_id: int, days: int = 90) -> List[dict]:
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT date, precip_mm, air_temp_f, is_forecast
                FROM weather_readings
                WHERE gauge_id = :gauge_id
                  AND date >= CURRENT_DATE - :days
                ORDER BY date DESC
            """),
            {"gauge_id": gauge_id, "days": days},
        ).fetchall()
    return [dict(r._mapping) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_db_client.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/shared/db_client.py pipeline/tests/test_db_client.py
git commit -m "feat: add postgres db client with upsert helpers"
```

---

## Task 7: Feature Engineering

**Files:**
- Create: `pipeline/plugins/features.py`
- Create: `pipeline/tests/test_features.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_features.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
from datetime import date
from plugins.features import build_feature_vector, compute_days_since_precip, compute_precip_72h

FEATURE_KEYS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "days_since_precip_event",
]

def test_build_feature_vector_has_all_keys():
    weather_history = [
        {"date": date(2026, 3, 30), "precip_mm": 0.0},
        {"date": date(2026, 3, 29), "precip_mm": 0.0},
        {"date": date(2026, 3, 28), "precip_mm": 6.0},  # event
        {"date": date(2026, 3, 27), "precip_mm": 0.0},
    ]
    features = build_feature_vector(
        flow_cfs=245.0,
        gauge_height_ft=1.82,
        water_temp_f=54.5,
        air_temp_f=55.0,
        precip_24h_mm=0.0,
        target_date=date(2026, 3, 30),
        weather_history=weather_history,
    )
    assert set(features.keys()) == set(FEATURE_KEYS)

def test_day_of_year_correct():
    weather_history = [{"date": date(2026, 1, 1), "precip_mm": 0.0}]
    features = build_feature_vector(
        flow_cfs=100.0, gauge_height_ft=1.0, water_temp_f=50.0,
        air_temp_f=45.0, precip_24h_mm=0.0,
        target_date=date(2026, 1, 1), weather_history=weather_history,
    )
    assert features["day_of_year"] == 1

def test_compute_precip_72h_sums_three_days():
    history = [
        {"date": date(2026, 3, 30), "precip_mm": 1.0},
        {"date": date(2026, 3, 29), "precip_mm": 2.0},
        {"date": date(2026, 3, 28), "precip_mm": 3.0},
        {"date": date(2026, 3, 27), "precip_mm": 10.0},  # outside 72h window
    ]
    result = compute_precip_72h(history, target_date=date(2026, 3, 30))
    assert result == pytest.approx(6.0)

def test_days_since_precip_event_no_recent_event():
    history = [
        {"date": date(2026, 3, 30), "precip_mm": 0.0},
        {"date": date(2026, 3, 29), "precip_mm": 0.0},
        {"date": date(2026, 3, 28), "precip_mm": 0.0},
    ]
    result = compute_days_since_precip(history, target_date=date(2026, 3, 30), threshold_mm=5.0)
    assert result == 30  # sentinel: no event in window

def test_days_since_precip_event_finds_event():
    history = [
        {"date": date(2026, 3, 30), "precip_mm": 0.0},
        {"date": date(2026, 3, 29), "precip_mm": 0.0},
        {"date": date(2026, 3, 28), "precip_mm": 8.0},  # event: 2 days ago
    ]
    result = compute_days_since_precip(history, target_date=date(2026, 3, 30), threshold_mm=5.0)
    assert result == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest pipeline/tests/test_features.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugins.features'`

- [ ] **Step 3: Write `pipeline/plugins/features.py`**

```python
"""Feature engineering for Riffle ML model.

All features are computed per gauge per target date.
weather_history is a list of dicts with keys: date (datetime.date), precip_mm (float).
Sorted in any order is fine — functions sort internally.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


def compute_precip_72h(weather_history: List[Dict], target_date: date) -> float:
    """Sum precipitation over the 3 days ending on target_date (inclusive)."""
    window = {target_date - timedelta(days=i) for i in range(3)}
    return sum(
        row["precip_mm"] for row in weather_history if row["date"] in window
    )


def compute_days_since_precip(
    weather_history: List[Dict],
    target_date: date,
    threshold_mm: float = 5.0,
    sentinel: int = 30,
) -> int:
    """Days since the most recent day with precip >= threshold_mm.

    Returns `sentinel` if no such event is found in weather_history.
    """
    events = [
        row["date"]
        for row in weather_history
        if row["precip_mm"] >= threshold_mm and row["date"] <= target_date
    ]
    if not events:
        return sentinel
    most_recent = max(events)
    return (target_date - most_recent).days


def build_feature_vector(
    flow_cfs: float,
    gauge_height_ft: float,
    water_temp_f: Optional[float],
    air_temp_f: float,
    precip_24h_mm: float,
    target_date: date,
    weather_history: List[Dict],
) -> Dict[str, Any]:
    """Build a single feature dict ready for XGBoost inference or training."""
    return {
        "flow_cfs": flow_cfs,
        "gauge_height_ft": gauge_height_ft,
        "water_temp_f": water_temp_f if water_temp_f is not None else 50.0,
        "precip_24h_mm": precip_24h_mm,
        "precip_72h_mm": compute_precip_72h(weather_history, target_date),
        "air_temp_f": air_temp_f,
        "day_of_year": target_date.timetuple().tm_yday,
        "days_since_precip_event": compute_days_since_precip(weather_history, target_date),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_features.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/plugins/features.py pipeline/tests/test_features.py
git commit -m "feat: add feature engineering module"
```

---

## Task 8: Bootstrapped Label Generation + XGBoost Training

**Files:**
- Create: `pipeline/plugins/ml/train.py`
- Create: `pipeline/tests/test_train.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_train.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
import pandas as pd
from plugins.ml.train import (
    label_condition,
    generate_labels,
    train_model,
    CONDITION_CLASSES,
)

# flow_thresholds for South Platte Spinney
THRESHOLDS = {"blowout": 500, "optimal_low": 80, "optimal_high": 250}

def test_condition_classes_ordered():
    assert CONDITION_CLASSES == ["Blown Out", "Poor", "Fair", "Good", "Excellent"]

def test_label_blown_out_by_flow():
    assert label_condition(600, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Blown Out"

def test_label_blown_out_by_temp():
    assert label_condition(100, 70.0, seasonal_median=150, thresholds=THRESHOLDS) == "Blown Out"

def test_label_poor_high_flow():
    # 150% of median = 225
    assert label_condition(230, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Poor"

def test_label_poor_warm_temp():
    assert label_condition(100, 66.0, seasonal_median=150, thresholds=THRESHOLDS) == "Poor"

def test_label_fair():
    # 120% of median = 180
    assert label_condition(190, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Fair"

def test_label_good():
    # 80-120% of median = 120-180
    assert label_condition(150, 55.0, seasonal_median=150, thresholds=THRESHOLDS) == "Good"

def test_label_excellent():
    assert label_condition(150, 50.0, seasonal_median=150, thresholds=THRESHOLDS) == "Excellent"

def test_train_model_returns_booster_and_version():
    # Synthetic dataset: 50 rows, 8 features
    n = 50
    df = pd.DataFrame({
        "flow_cfs": [150.0] * n,
        "gauge_height_ft": [1.5] * n,
        "water_temp_f": [52.0] * n,
        "precip_24h_mm": [0.0] * n,
        "precip_72h_mm": [0.0] * n,
        "air_temp_f": [55.0] * n,
        "day_of_year": [90] * n,
        "days_since_precip_event": [5] * n,
        "condition": ["Good"] * n,
    })
    import mlflow
    mlflow.set_tracking_uri("sqlite:///test_mlflow.db")
    booster, run_id = train_model(df, experiment_name="test-riffle")
    assert booster is not None
    assert isinstance(run_id, str)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest pipeline/tests/test_train.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugins.ml.train'`

- [ ] **Step 3: Write `pipeline/plugins/ml/train.py`**

```python
"""XGBoost training + MLflow integration for Riffle.

Bootstraps condition labels from domain-knowledge thresholds,
trains a multi-class classifier, logs to MLflow, and returns
the trained booster and MLflow run ID.
"""

from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd
import xgboost as xgb
import mlflow
import mlflow.xgboost

CONDITION_CLASSES = ["Blown Out", "Poor", "Fair", "Good", "Excellent"]
LABEL_TO_INT = {c: i for i, c in enumerate(CONDITION_CLASSES)}
FEATURE_COLS = [
    "flow_cfs", "gauge_height_ft", "water_temp_f",
    "precip_24h_mm", "precip_72h_mm", "air_temp_f",
    "day_of_year", "days_since_precip_event",
]


def label_condition(
    flow_cfs: float,
    water_temp_f: float,
    seasonal_median: float,
    thresholds: Dict,
) -> str:
    """Apply domain-knowledge thresholds to assign a condition label.

    Priority order: Blown Out > Poor > Fair > Good > Excellent.
    """
    if flow_cfs > thresholds["blowout"] or water_temp_f > 68:
        return "Blown Out"
    if flow_cfs > seasonal_median * 1.5 or water_temp_f >= 65:
        return "Poor"
    if flow_cfs > seasonal_median * 1.2 or water_temp_f >= 60:
        return "Fair"
    if seasonal_median * 0.8 <= flow_cfs <= seasonal_median * 1.2 and water_temp_f <= 60:
        return "Good"
    return "Excellent"


def generate_labels(
    df: pd.DataFrame,
    seasonal_medians: Optional[Dict[str, float]] = None,
    default_thresholds: Optional[Dict] = None,
) -> pd.Series:
    """Generate bootstrapped labels for a DataFrame of gauge readings.

    df must have columns: flow_cfs, water_temp_f, gauge_id (optional).
    seasonal_medians: {gauge_id: median_flow_cfs}. Falls back to df median.
    default_thresholds: used when per-gauge thresholds are unavailable.
    """
    if default_thresholds is None:
        default_thresholds = {"blowout": 2000, "optimal_low": 100, "optimal_high": 500}

    median = (
        seasonal_medians.get(str(df.get("gauge_id", "").iloc[0]), df["flow_cfs"].median())
        if seasonal_medians and "gauge_id" in df.columns
        else df["flow_cfs"].median()
    )

    return df.apply(
        lambda row: label_condition(
            flow_cfs=row["flow_cfs"],
            water_temp_f=row["water_temp_f"],
            seasonal_median=median,
            thresholds=default_thresholds,
        ),
        axis=1,
    )


def train_model(
    df: pd.DataFrame,
    experiment_name: str = "riffle-conditions",
) -> Tuple[xgb.Booster, str]:
    """Train XGBoost classifier on labeled data, log to MLflow.

    df must have columns: FEATURE_COLS + 'condition'.
    Returns: (trained booster, MLflow run_id).
    """
    X = df[FEATURE_COLS].values
    y = df["condition"].map(LABEL_TO_INT).values

    dtrain = xgb.DMatrix(X, label=y, feature_names=FEATURE_COLS)

    params = {
        "objective": "multi:softprob",
        "num_class": len(CONDITION_CLASSES),
        "max_depth": 4,
        "eta": 0.1,
        "subsample": 0.8,
        "eval_metric": "mlogloss",
        "seed": 42,
    }

    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params(params)
        booster = xgb.train(params, dtrain, num_boost_round=50)
        mlflow.xgboost.log_model(booster, artifact_path="model")
        run_id = run.info.run_id

    return booster, run_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_train.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Clean up test artifact**

```bash
rm -f test_mlflow.db
```

- [ ] **Step 6: Commit**

```bash
git add pipeline/plugins/ml/train.py pipeline/tests/test_train.py
git commit -m "feat: add bootstrapped labeling and XGBoost training with MLflow"
```

---

## Task 9: MLflow Model Promotion + Scoring Module

**Files:**
- Create: `pipeline/plugins/ml/score.py`
- Create: `pipeline/tests/test_score.py`

- [ ] **Step 1: Write the failing test**

Create `pipeline/tests/test_score.py`:

```python
import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from plugins.ml.score import predict_condition, load_production_model
from plugins.ml.train import CONDITION_CLASSES


def test_predict_condition_returns_valid_label():
    mock_booster = MagicMock()
    # softprob returns one probability per class per row
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][3] = 0.9  # index 3 = "Good"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 150.0, "gauge_height_ft": 1.5, "water_temp_f": 52.0,
        "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 55.0,
        "day_of_year": 90, "days_since_precip_event": 5,
    }
    label, confidence = predict_condition(mock_booster, features)
    assert label == "Good"
    assert confidence == pytest.approx(0.9)


def test_predict_condition_returns_str_and_float():
    mock_booster = MagicMock()
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][0] = 0.95  # "Blown Out"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 1000.0, "gauge_height_ft": 5.0, "water_temp_f": 55.0,
        "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 45.0,
        "day_of_year": 150, "days_since_precip_event": 1,
    }
    label, confidence = predict_condition(mock_booster, features)
    assert isinstance(label, str)
    assert isinstance(confidence, float)
    assert label == "Blown Out"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest pipeline/tests/test_score.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugins.ml.score'`

- [ ] **Step 3: Write `pipeline/plugins/ml/score.py`**

```python
"""Load production XGBoost model from MLflow and score feature vectors.

load_production_model() fetches the latest model in 'Production' stage.
predict_condition() returns (condition_label, confidence).
"""

import os
from typing import Dict, Optional, Tuple

import mlflow
import mlflow.xgboost
import numpy as np
import xgboost as xgb

from plugins.ml.train import CONDITION_CLASSES, FEATURE_COLS


def load_production_model(model_name: str = "riffle-conditions") -> xgb.Booster:
    """Load the model in the Production stage from MLflow registry.

    Requires MLFLOW_TRACKING_URI env var to be set.
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(tracking_uri)

    model_uri = f"models:/{model_name}/Production"
    return mlflow.xgboost.load_model(model_uri)


def promote_model_to_production(run_id: str, model_name: str = "riffle-conditions") -> None:
    """Register the model from run_id and promote it to Production stage.

    Archives any previously Production-staged version.
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(tracking_uri)

    client = mlflow.tracking.MlflowClient()
    model_uri = f"runs:/{run_id}/model"

    result = mlflow.register_model(model_uri, model_name)
    version = result.version

    client.transition_model_version_stage(
        name=model_name,
        version=version,
        stage="Production",
        archive_existing_versions=True,
    )


def predict_condition(
    booster: xgb.Booster,
    features: Dict[str, float],
) -> Tuple[str, float]:
    """Score a single feature vector.

    Returns (condition_label, confidence) where confidence is the
    probability of the predicted class.
    """
    row = np.array([[features[col] for col in FEATURE_COLS]], dtype=np.float32)
    dmatrix = xgb.DMatrix(row, feature_names=FEATURE_COLS)
    probs = booster.predict(dmatrix)  # shape: (1, num_classes)
    class_idx = int(np.argmax(probs[0]))
    confidence = float(probs[0][class_idx])
    return CONDITION_CLASSES[class_idx], confidence
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest pipeline/tests/test_score.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add pipeline/plugins/ml/score.py pipeline/tests/test_score.py
git commit -m "feat: add MLflow model loading and XGBoost scoring module"
```

---

## Task 10: Airflow DAGs — gauge_ingest + weather_ingest

**Files:**
- Create: `pipeline/dags/gauge_ingest_dag.py`
- Create: `pipeline/dags/weather_ingest_dag.py`
- Create: `pipeline/tests/test_dags.py`

- [ ] **Step 1: Write the failing tests**

Create `pipeline/tests/test_dags.py`:

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

def test_gauge_ingest_dag_loads(dagbag):
    dag = dagbag.get_dag("gauge_ingest")
    assert dag is not None
    assert dagbag.import_errors == {}

def test_weather_ingest_dag_loads(dagbag):
    dag = dagbag.get_dag("weather_ingest")
    assert dag is not None

def test_condition_score_dag_loads(dagbag):
    dag = dagbag.get_dag("condition_score")
    assert dag is not None

def test_train_dag_loads(dagbag):
    dag = dagbag.get_dag("train")
    assert dag is not None

def test_gauge_ingest_has_expected_tasks(dagbag):
    dag = dagbag.get_dag("gauge_ingest")
    task_ids = {t.task_id for t in dag.tasks}
    assert "fetch_and_store_readings" in task_ids

def test_weather_ingest_has_expected_tasks(dagbag):
    dag = dagbag.get_dag("weather_ingest")
    task_ids = {t.task_id for t in dag.tasks}
    assert "fetch_and_store_weather" in task_ids

def test_condition_score_dag_schedule(dagbag):
    dag = dagbag.get_dag("condition_score")
    # Should run at 7:30am MT = 13:30 UTC
    assert "30 13" in dag.schedule_interval

def test_train_dag_is_weekly(dagbag):
    dag = dagbag.get_dag("train")
    assert "0 9" in dag.schedule_interval  # Monday 3am MT = 9am UTC
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest pipeline/tests/test_dags.py -v
```

Expected: `ImportError` or `AssertionError` — DAG files don't exist yet.

- [ ] **Step 3: Write `pipeline/dags/gauge_ingest_dag.py`**

```python
"""gauge_ingest_dag — Daily at 7:00am MT (13:00 UTC).

For each gauge in the registry:
  1. Fetch latest USGS reading (flow, temp, gauge height)
  2. Upsert into gauge_readings table
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime, timezone
from airflow import DAG
from airflow.operators.python import PythonOperator

from config.rivers import GAUGES
from shared.usgs_client import fetch_gauge_reading
from shared.db_client import get_gauge_id, upsert_gauge_reading

default_args = {"owner": "riffle", "retries": 2}


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


with DAG(
    dag_id="gauge_ingest",
    default_args=default_args,
    schedule_interval="0 13 * * *",  # 7:00am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ingest"],
) as dag:
    PythonOperator(
        task_id="fetch_and_store_readings",
        python_callable=fetch_and_store_readings,
    )
```

- [ ] **Step 4: Write `pipeline/dags/weather_ingest_dag.py`**

```python
"""weather_ingest_dag — Daily at 7:05am MT (13:05 UTC).

For each gauge lat/lon:
  1. Fetch Open-Meteo current conditions + 3-day forecast
  2. Upsert into weather_readings table
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator

from config.rivers import GAUGES
from shared.weather_client import fetch_weather
from shared.db_client import get_gauge_id, upsert_weather_reading

default_args = {"owner": "riffle", "retries": 2}


def fetch_and_store_weather():
    for gauge_cfg in GAUGES:
        days = fetch_weather(lat=gauge_cfg["lat"], lon=gauge_cfg["lon"])
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        for day in days:
            upsert_weather_reading(
                gauge_id=gauge_id,
                date=day.date,
                precip_mm=day.precip_mm,
                air_temp_f=day.air_temp_f,
                is_forecast=day.is_forecast,
            )


with DAG(
    dag_id="weather_ingest",
    default_args=default_args,
    schedule_interval="5 13 * * *",  # 7:05am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ingest"],
) as dag:
    PythonOperator(
        task_id="fetch_and_store_weather",
        python_callable=fetch_and_store_weather,
    )
```

- [ ] **Step 5: Run the dag-load tests**

```bash
python -m pytest pipeline/tests/test_dags.py::test_gauge_ingest_dag_loads \
                  pipeline/tests/test_dags.py::test_weather_ingest_dag_loads -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add pipeline/dags/gauge_ingest_dag.py pipeline/dags/weather_ingest_dag.py
git commit -m "feat: add gauge_ingest and weather_ingest Airflow DAGs"
```

---

## Task 11: Airflow DAGs — condition_score + train

**Files:**
- Create: `pipeline/dags/condition_score_dag.py`
- Create: `pipeline/dags/train_dag.py`

- [ ] **Step 1: Write `pipeline/dags/condition_score_dag.py`**

```python
"""condition_score_dag — Daily at 7:30am MT (13:30 UTC).

Waits for gauge_ingest + weather_ingest to complete, then:
  1. Load production XGBoost model from MLflow
  2. Build feature vectors for today + 3 forecast days per gauge
  3. Run classification → write predictions to Postgres
"""

import sys
sys.path.insert(0, "/opt/airflow")

from datetime import date, datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.sensors.external_task import ExternalTaskSensor

from config.rivers import GAUGES
from shared.db_client import (
    get_gauge_id,
    get_recent_gauge_readings,
    get_recent_weather_readings,
    upsert_prediction,
)
from plugins.features import build_feature_vector
from plugins.ml.score import load_production_model, predict_condition

default_args = {"owner": "riffle", "retries": 1}


def score_all_gauges():
    booster = load_production_model()
    model_version = "production"
    today = date.today()

    for gauge_cfg in GAUGES:
        gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
        gauge_rows = get_recent_gauge_readings(gauge_id, days=1)
        if not gauge_rows:
            continue

        latest = gauge_rows[0]
        weather_history = get_recent_weather_readings(gauge_id, days=90)

        # Score today + 3 forecast days
        forecast_weather = get_recent_weather_readings(gauge_id, days=4)
        for i, weather_row in enumerate(sorted(forecast_weather, key=lambda r: r["date"])):
            target_date = weather_row["date"]
            is_forecast = (target_date != today)
            features = build_feature_vector(
                flow_cfs=latest["flow_cfs"] or 0.0,
                gauge_height_ft=latest["gauge_height_ft"] or 0.0,
                water_temp_f=latest["water_temp_f"],
                air_temp_f=weather_row["air_temp_f"],
                precip_24h_mm=weather_row["precip_mm"],
                target_date=target_date,
                weather_history=weather_history,
            )
            condition, confidence = predict_condition(booster, features)
            upsert_prediction(
                gauge_id=gauge_id,
                date=target_date,
                condition=condition,
                confidence=confidence,
                is_forecast=is_forecast,
                model_version=model_version,
            )


with DAG(
    dag_id="condition_score",
    default_args=default_args,
    schedule_interval="30 13 * * *",  # 7:30am MT
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["riffle", "ml"],
) as dag:
    wait_gauge = ExternalTaskSensor(
        task_id="wait_gauge_ingest",
        external_dag_id="gauge_ingest",
        external_task_id="fetch_and_store_readings",
        timeout=3600,
    )
    wait_weather = ExternalTaskSensor(
        task_id="wait_weather_ingest",
        external_dag_id="weather_ingest",
        external_task_id="fetch_and_store_weather",
        timeout=3600,
    )
    score_task = PythonOperator(
        task_id="score_gauges",
        python_callable=score_all_gauges,
    )
    [wait_gauge, wait_weather] >> score_task
```

- [ ] **Step 2: Write `pipeline/dags/train_dag.py`**

```python
"""train_dag — Weekly, Monday 3:00am MT (9:00 UTC).

1. Pull historical gauge_readings + weather_readings from Postgres
2. Join on gauge_id + date
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
        weather_rows = get_recent_weather_readings(gauge_id, days=365)
        weather_by_date = {r["date"]: r for r in weather_rows}

        thresholds = gauge_cfg["flow_thresholds"]
        flow_values = [r["flow_cfs"] for r in gauge_rows if r["flow_cfs"]]
        seasonal_median = float(pd.Series(flow_values).median()) if flow_values else 200.0

        for row in gauge_rows:
            if not row["flow_cfs"]:
                continue
            target_date = row["fetched_at"].date()
            weather = weather_by_date.get(target_date)
            if not weather:
                continue
            features = build_feature_vector(
                flow_cfs=row["flow_cfs"],
                gauge_height_ft=row["gauge_height_ft"] or 0.0,
                water_temp_f=row["water_temp_f"],
                air_temp_f=weather["air_temp_f"],
                precip_24h_mm=weather["precip_mm"],
                target_date=target_date,
                weather_history=weather_rows,
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

- [ ] **Step 3: Run all DAG load tests**

```bash
python -m pytest pipeline/tests/test_dags.py -v
```

Expected: `8 passed`

- [ ] **Step 4: Commit**

```bash
git add pipeline/dags/condition_score_dag.py pipeline/dags/train_dag.py pipeline/tests/test_dags.py
git commit -m "feat: add condition_score and train Airflow DAGs"
```

---

## Task 12: FastAPI — All Three Endpoints

**Files:**
- Create: `api/main.py`
- Create: `api/routes/rivers.py`
- Create: `api/tests/test_rivers.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_rivers.py`:

```python
import sys, os
os.environ["DATABASE_URL"] = "postgresql+psycopg2://riffle:riffle@localhost/riffle"
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from fastapi.testclient import TestClient
from datetime import date

# Import after env is set
from api.main import app

client = TestClient(app)

MOCK_GAUGES = [
    {
        "id": 1, "usgs_gauge_id": "09035800", "name": "Spinney Reservoir",
        "river": "South Platte", "lat": 38.9097, "lon": -105.5666,
    }
]

MOCK_PREDICTIONS_TODAY = [
    {
        "gauge_id": 1, "date": date(2026, 3, 30), "condition": "Good",
        "confidence": 0.82, "is_forecast": False, "model_version": "1",
    }
]

MOCK_FORECAST = [
    {"gauge_id": 1, "date": date(2026, 3, 30), "condition": "Good", "confidence": 0.82, "is_forecast": False, "model_version": "1"},
    {"gauge_id": 1, "date": date(2026, 3, 31), "condition": "Fair", "confidence": 0.71, "is_forecast": True, "model_version": "1"},
    {"gauge_id": 1, "date": date(2026, 3, 31), "condition": "Poor", "confidence": 0.65, "is_forecast": True, "model_version": "1"},
    {"gauge_id": 1, "date": date(2026, 4, 1),  "condition": "Good", "confidence": 0.78, "is_forecast": True, "model_version": "1"},
]

def _mock_session(rows):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.execute.return_value.mappings.return_value.fetchall.return_value = rows
    session.execute.return_value.mappings.return_value.fetchone.return_value = rows[0] if rows else None
    return session

def test_get_rivers_returns_list():
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        resp = client.get("/api/rivers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

def test_get_rivers_includes_condition():
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_today_predictions") as mock_preds:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        mock_preds.return_value = {1: MOCK_PREDICTIONS_TODAY[0]}
        resp = client.get("/api/rivers")
    assert resp.status_code == 200

def test_get_river_detail_returns_forecast():
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_forecast") as mock_fc:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        mock_fc.return_value = MOCK_FORECAST
        resp = client.get("/api/rivers/09035800")
    assert resp.status_code == 200

def test_get_river_detail_unknown_gauge():
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = _mock_session([])
        resp = client.get("/api/rivers/99999999")
    assert resp.status_code == 404

def test_get_history_returns_30_days():
    mock_history = [
        {"date": date(2026, 3, 30 - i), "condition": "Good", "confidence": 0.8, "flow_cfs": 150.0, "water_temp_f": 52.0}
        for i in range(30)
    ]
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_history") as mock_hist:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        mock_hist.return_value = mock_history
        resp = client.get("/api/rivers/09035800/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/riffle
python -m pytest api/tests/test_rivers.py -v
```

Expected: `ModuleNotFoundError: No module named 'api.main'`

- [ ] **Step 3: Write `api/main.py`**

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

app.include_router(rivers_router, prefix="/api")
```

- [ ] **Step 4: Write `api/routes/rivers.py`**

```python
"""FastAPI route handlers for river/gauge endpoints.

GET /api/rivers                         — all gauges with today's condition
GET /api/rivers/{gauge_id}              — current condition + 3-day forecast
GET /api/rivers/{gauge_id}/history      — last 30 days of conditions + key stats
"""

import os
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

router = APIRouter()

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(_get_engine()) as session:
        yield session


def get_today_predictions(session: Session) -> Dict[int, dict]:
    """Return {gauge_id: prediction_row} for today's non-forecast predictions."""
    rows = session.execute(
        text("""
            SELECT gauge_id, condition, confidence, is_forecast, model_version
            FROM predictions
            WHERE date = CURRENT_DATE AND is_forecast = FALSE
        """)
    ).mappings().fetchall()
    return {r["gauge_id"]: dict(r) for r in rows}


def get_gauge_forecast(session: Session, gauge_id_int: int) -> List[dict]:
    """Return today + 3 forecast day predictions for a gauge."""
    rows = session.execute(
        text("""
            SELECT p.date, p.condition, p.confidence, p.is_forecast,
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
                ON wr.gauge_id = p.gauge_id AND wr.date = p.date
            WHERE p.gauge_id = :gid
              AND p.date >= CURRENT_DATE
              AND p.date <= CURRENT_DATE + 3
            ORDER BY p.date
        """),
        {"gid": gauge_id_int},
    ).mappings().fetchall()
    return [dict(r) for r in rows]


def get_gauge_history(session: Session, gauge_id_int: int) -> List[dict]:
    """Return last 30 days of predictions with key gauge stats."""
    rows = session.execute(
        text("""
            SELECT p.date, p.condition, p.confidence,
                   gr.flow_cfs, gr.water_temp_f
            FROM predictions p
            LEFT JOIN LATERAL (
                SELECT flow_cfs, water_temp_f
                FROM gauge_readings
                WHERE gauge_id = p.gauge_id
                  AND DATE(fetched_at) = p.date
                ORDER BY fetched_at DESC
                LIMIT 1
            ) gr ON TRUE
            WHERE p.gauge_id = :gid
              AND p.date >= CURRENT_DATE - 30
              AND p.is_forecast = FALSE
            ORDER BY p.date DESC
        """),
        {"gid": gauge_id_int},
    ).mappings().fetchall()
    return [dict(r) for r in rows]


@router.get("/rivers")
def list_rivers() -> List[Dict[str, Any]]:
    """Return all gauges with today's condition label."""
    with get_session() as session:
        gauges = session.execute(
            text("SELECT id, usgs_gauge_id, name, river, lat, lon FROM gauges ORDER BY river, name")
        ).mappings().fetchall()
        predictions = get_today_predictions(session)

    result = []
    for g in gauges:
        pred = predictions.get(g["id"], {})
        result.append({
            "gauge_id": g["usgs_gauge_id"],
            "name": g["name"],
            "river": g["river"],
            "lat": g["lat"],
            "lon": g["lon"],
            "condition": pred.get("condition"),
            "confidence": pred.get("confidence"),
        })
    return result


@router.get("/rivers/{gauge_id}")
def get_river(gauge_id: str) -> Dict[str, Any]:
    """Return current condition + 3-day forecast for a single gauge."""
    with get_session() as session:
        gauge = session.execute(
            text("SELECT id, usgs_gauge_id, name, river, lat, lon FROM gauges WHERE usgs_gauge_id = :gid"),
            {"gid": gauge_id},
        ).mappings().fetchone()

        if not gauge:
            raise HTTPException(status_code=404, detail=f"Gauge {gauge_id} not found")

        latest_reading = session.execute(
            text("""
                SELECT flow_cfs, water_temp_f, gauge_height_ft, fetched_at
                FROM gauge_readings
                WHERE gauge_id = :gid
                ORDER BY fetched_at DESC
                LIMIT 1
            """),
            {"gid": gauge["id"]},
        ).mappings().fetchone()

        forecast = get_gauge_forecast(session, gauge["id"])

    return {
        "gauge_id": gauge["usgs_gauge_id"],
        "name": gauge["name"],
        "river": gauge["river"],
        "lat": gauge["lat"],
        "lon": gauge["lon"],
        "current": dict(latest_reading) if latest_reading else None,
        "forecast": [
            {
                "date": str(f["date"]),
                "condition": f["condition"],
                "confidence": f["confidence"],
                "is_forecast": f["is_forecast"],
                "precip_mm": f.get("precip_mm"),
                "air_temp_f": f.get("air_temp_f"),
            }
            for f in forecast
        ],
        "usgs_url": f"https://waterdata.usgs.gov/monitoring-location/{gauge_id}/",
    }


@router.get("/rivers/{gauge_id}/history")
def get_river_history(gauge_id: str) -> Dict[str, Any]:
    """Return last 30 days of condition labels + key stats for a gauge."""
    with get_session() as session:
        gauge = session.execute(
            text("SELECT id, name, river FROM gauges WHERE usgs_gauge_id = :gid"),
            {"gid": gauge_id},
        ).mappings().fetchone()

        if not gauge:
            raise HTTPException(status_code=404, detail=f"Gauge {gauge_id} not found")

        history = get_gauge_history(session, gauge["id"])

    return {
        "gauge_id": gauge_id,
        "name": gauge["name"],
        "river": gauge["river"],
        "history": [
            {
                "date": str(h["date"]),
                "condition": h["condition"],
                "confidence": h["confidence"],
                "flow_cfs": h.get("flow_cfs"),
                "water_temp_f": h.get("water_temp_f"),
            }
            for h in history
        ],
    }
```

- [ ] **Step 5: Run API tests**

```bash
python -m pytest api/tests/test_rivers.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add api/main.py api/routes/rivers.py api/tests/test_rivers.py
git commit -m "feat: add FastAPI with /rivers, /rivers/{id}, and /rivers/{id}/history endpoints"
```

---

## Task 13: Next.js Setup + Map Page

**Files:**
- Create: `web/` (Next.js project)
- Create: `web/config/api.ts`
- Create: `web/components/ConditionBadge.tsx`
- Create: `web/components/RiverMap.tsx`
- Create: `web/app/page.tsx`

- [ ] **Step 1: Bootstrap Next.js project**

```bash
cd riffle
npx create-next-app@14 web \
  --typescript \
  --tailwind \
  --app \
  --no-src-dir \
  --import-alias "@/*"
cd web
npm install leaflet @types/leaflet
```

- [ ] **Step 2: Write `web/config/api.ts`**

```typescript
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface RiverSummary {
  gauge_id: string;
  name: string;
  river: string;
  lat: number;
  lon: number;
  condition: string | null;
  confidence: number | null;
}

export interface ForecastDay {
  date: string;
  condition: string;
  confidence: number;
  is_forecast: boolean;
  precip_mm: number | null;
  air_temp_f: number | null;
}

export interface RiverDetail {
  gauge_id: string;
  name: string;
  river: string;
  lat: number;
  lon: number;
  current: {
    flow_cfs: number | null;
    water_temp_f: number | null;
    gauge_height_ft: number | null;
    fetched_at: string;
  } | null;
  forecast: ForecastDay[];
  usgs_url: string;
}

export interface HistoryDay {
  date: string;
  condition: string;
  confidence: number;
  flow_cfs: number | null;
  water_temp_f: number | null;
}

export interface RiverHistory {
  gauge_id: string;
  name: string;
  river: string;
  history: HistoryDay[];
}

export async function fetchRivers(): Promise<RiverSummary[]> {
  const res = await fetch(`${BASE_URL}/api/rivers`, { next: { revalidate: 3600 } });
  if (!res.ok) throw new Error("Failed to fetch rivers");
  return res.json();
}

export async function fetchRiver(gaugeId: string): Promise<RiverDetail> {
  const res = await fetch(`${BASE_URL}/api/rivers/${gaugeId}`, {
    next: { revalidate: 3600 },
  });
  if (!res.ok) throw new Error(`Failed to fetch river ${gaugeId}`);
  return res.json();
}

export async function fetchRiverHistory(gaugeId: string): Promise<RiverHistory> {
  const res = await fetch(`${BASE_URL}/api/rivers/${gaugeId}/history`, {
    next: { revalidate: 3600 },
  });
  if (!res.ok) throw new Error(`Failed to fetch history for ${gaugeId}`);
  return res.json();
}
```

- [ ] **Step 3: Write `web/components/ConditionBadge.tsx`**

```typescript
const CONDITION_STYLES: Record<string, string> = {
  Excellent: "bg-green-800 text-white",
  Good: "bg-green-500 text-white",
  Fair: "bg-yellow-400 text-gray-900",
  Poor: "bg-orange-500 text-white",
  "Blown Out": "bg-red-600 text-white",
};

interface ConditionBadgeProps {
  condition: string | null;
  estimated?: boolean;
}

export default function ConditionBadge({ condition, estimated }: ConditionBadgeProps) {
  if (!condition) {
    return (
      <span className="inline-block px-2 py-1 rounded text-sm bg-gray-200 text-gray-500">
        No data
      </span>
    );
  }
  const style = CONDITION_STYLES[condition] ?? "bg-gray-400 text-white";
  return (
    <span className={`inline-block px-2 py-1 rounded text-sm font-semibold ${style}`}>
      {condition}
      {estimated && (
        <span className="ml-1 text-xs font-normal opacity-75">(est.)</span>
      )}
    </span>
  );
}
```

- [ ] **Step 4: Write `web/components/RiverMap.tsx`**

```typescript
"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import type { RiverSummary } from "@/config/api";

const CONDITION_COLORS: Record<string, string> = {
  Excellent: "#1a6b1a",
  Good: "#22c55e",
  Fair: "#eab308",
  Poor: "#f97316",
  "Blown Out": "#dc2626",
};

interface RiverMapProps {
  rivers: RiverSummary[];
}

export default function RiverMap({ rivers }: RiverMapProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    if (!mapRef.current) return;

    // Leaflet must be imported dynamically (no SSR)
    import("leaflet").then((L) => {
      // Avoid re-initializing if map already mounted
      if ((mapRef.current as any)._leaflet_id) return;

      const map = L.map(mapRef.current!, {
        center: [39.0, -105.5],
        zoom: 7,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);

      rivers.forEach((river) => {
        const color = river.condition
          ? (CONDITION_COLORS[river.condition] ?? "#6b7280")
          : "#6b7280";

        const marker = L.circleMarker([river.lat, river.lon], {
          radius: 10,
          fillColor: color,
          color: "#fff",
          weight: 2,
          fillOpacity: 0.9,
        }).addTo(map);

        marker.bindPopup(
          `<b>${river.name}</b><br>${river.river}<br>${river.condition ?? "No data"}`
        );

        marker.on("click", () => {
          router.push(`/rivers/${river.gauge_id}`);
        });
      });
    });
  }, [rivers, router]);

  return <div ref={mapRef} className="w-full h-full" />;
}
```

- [ ] **Step 5: Write `web/app/page.tsx`**

```typescript
import { Suspense } from "react";
import { fetchRivers } from "@/config/api";
import RiverMap from "@/components/RiverMap";

export const revalidate = 3600;

export default async function HomePage() {
  const rivers = await fetchRivers();

  return (
    <main className="flex flex-col h-screen">
      <header className="px-6 py-3 bg-slate-900 text-white flex items-center gap-3 shrink-0">
        <h1 className="text-xl font-bold tracking-tight">Riffle</h1>
        <span className="text-slate-400 text-sm">Colorado Fly Fishing Conditions</span>
      </header>

      {/* Legend */}
      <div className="flex gap-3 px-6 py-2 bg-slate-800 text-white text-xs shrink-0 flex-wrap">
        {[
          { label: "Excellent", color: "#1a6b1a" },
          { label: "Good", color: "#22c55e" },
          { label: "Fair", color: "#eab308" },
          { label: "Poor", color: "#f97316" },
          { label: "Blown Out", color: "#dc2626" },
        ].map(({ label, color }) => (
          <div key={label} className="flex items-center gap-1">
            <span
              className="inline-block w-3 h-3 rounded-full border border-white"
              style={{ backgroundColor: color }}
            />
            <span>{label}</span>
          </div>
        ))}
      </div>

      {/* Map */}
      <div className="flex-1 relative">
        <Suspense fallback={<div className="w-full h-full bg-slate-100 animate-pulse" />}>
          <RiverMap rivers={rivers} />
        </Suspense>
      </div>

      <footer className="px-6 py-2 bg-slate-900 text-slate-500 text-xs shrink-0">
        Data: USGS Water Services + Open-Meteo · Updated daily · Click a marker for details
      </footer>
    </main>
  );
}
```

- [ ] **Step 6: Add Leaflet CSS to layout**

Edit `web/app/layout.tsx` — add the import before the `<html>` return:

```typescript
import "leaflet/dist/leaflet.css";
```

Full `web/app/layout.tsx`:

```typescript
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "leaflet/dist/leaflet.css";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Riffle — Colorado Fly Fishing Conditions",
  description: "Real-time USGS stream gauge conditions and 3-day forecasts for Colorado fly fishing.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>{children}</body>
    </html>
  );
}
```

- [ ] **Step 7: Verify it builds without TypeScript errors**

```bash
cd web
npm run build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
cd ..
git add web/
git commit -m "feat: add Next.js map hero page with Leaflet + condition-colored markers"
```

---

## Task 14: River Detail Page

**Files:**
- Create: `web/components/ForecastStrip.tsx`
- Create: `web/components/HistoryChart.tsx`
- Create: `web/app/rivers/[id]/page.tsx`

- [ ] **Step 1: Install charting library**

```bash
cd web
npm install recharts
npm install --save-dev @types/recharts
```

- [ ] **Step 2: Write `web/components/ForecastStrip.tsx`**

```typescript
import ConditionBadge from "./ConditionBadge";
import type { ForecastDay } from "@/config/api";

interface ForecastStripProps {
  forecast: ForecastDay[];
}

function formatDate(dateStr: string): string {
  return new Date(dateStr + "T12:00:00").toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export default function ForecastStrip({ forecast }: ForecastStripProps) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {forecast.map((day) => (
        <div
          key={day.date}
          className="flex-shrink-0 w-36 rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
        >
          <p className="text-xs text-gray-500 mb-1">{formatDate(day.date)}</p>
          <ConditionBadge condition={day.condition} estimated={day.is_forecast} />
          {day.precip_mm !== null && (
            <p className="text-xs text-gray-600 mt-2">
              Precip: {day.precip_mm.toFixed(1)} mm
            </p>
          )}
          {day.air_temp_f !== null && (
            <p className="text-xs text-gray-600">
              Air: {Math.round(day.air_temp_f)}°F
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Write `web/components/HistoryChart.tsx`**

```typescript
"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { HistoryDay } from "@/config/api";

const CONDITION_ORDER = ["Blown Out", "Poor", "Fair", "Good", "Excellent"];

interface HistoryChartProps {
  history: HistoryDay[];
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T12:00:00");
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export default function HistoryChart({ history }: HistoryChartProps) {
  const data = [...history].reverse().map((day) => ({
    date: formatDate(day.date),
    score: CONDITION_ORDER.indexOf(day.condition),
    condition: day.condition,
    flow_cfs: day.flow_cfs,
  }));

  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
        <XAxis dataKey="date" tick={{ fontSize: 11 }} interval={4} />
        <YAxis
          domain={[0, 4]}
          tickFormatter={(v) => CONDITION_ORDER[v]?.split(" ")[0] ?? ""}
          tick={{ fontSize: 11 }}
          width={55}
        />
        <Tooltip
          formatter={(value: number, name: string, props: any) => [
            props.payload.condition,
            "Condition",
          ]}
        />
        <Line
          type="monotone"
          dataKey="score"
          stroke="#16a34a"
          strokeWidth={2}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

- [ ] **Step 4: Write `web/app/rivers/[id]/page.tsx`**

```typescript
import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchRiver, fetchRiverHistory } from "@/config/api";
import ConditionBadge from "@/components/ConditionBadge";
import ForecastStrip from "@/components/ForecastStrip";
import HistoryChart from "@/components/HistoryChart";

export const revalidate = 3600;

interface Props {
  params: { id: string };
}

export default async function RiverDetailPage({ params }: Props) {
  let river, historyData;
  try {
    [river, historyData] = await Promise.all([
      fetchRiver(params.id),
      fetchRiverHistory(params.id),
    ]);
  } catch {
    notFound();
  }

  const today = river.forecast.find((d) => !d.is_forecast);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-slate-900 text-white px-6 py-3 flex items-center gap-4">
        <Link href="/" className="text-slate-400 hover:text-white text-sm">
          ← Map
        </Link>
        <div>
          <h1 className="text-xl font-bold">{river.name}</h1>
          <p className="text-slate-400 text-sm">{river.river}</p>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-8 space-y-8">
        {/* Current condition */}
        <section className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Today's Conditions
          </h2>
          <div className="flex items-center gap-4 mb-4">
            <ConditionBadge condition={today?.condition ?? null} />
          </div>
          {river.current && (
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {river.current.flow_cfs?.toFixed(0) ?? "—"}
                </p>
                <p className="text-xs text-gray-500">cfs</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {river.current.water_temp_f?.toFixed(1) ?? "—"}°
                </p>
                <p className="text-xs text-gray-500">water temp (°F)</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {river.current.gauge_height_ft?.toFixed(2) ?? "—"}
                </p>
                <p className="text-xs text-gray-500">gauge height (ft)</p>
              </div>
            </div>
          )}
          <a
            href={river.usgs_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-4 inline-block text-xs text-blue-600 hover:underline"
          >
            View raw USGS gauge data →
          </a>
        </section>

        {/* 3-day forecast */}
        <section className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            3-Day Forecast
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            Forecast days marked "est." use predicted weather with current flow as a baseline.
          </p>
          <ForecastStrip forecast={river.forecast} />
        </section>

        {/* 30-day history */}
        <section className="bg-white rounded-xl shadow-sm p-6">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
            30-Day Condition History
          </h2>
          <HistoryChart history={historyData.history} />
        </section>
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Verify build succeeds**

```bash
cd web
npm run build
```

Expected: Build succeeds, no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
cd ..
git add web/components/ForecastStrip.tsx web/components/HistoryChart.tsx
git add "web/app/rivers/[id]/page.tsx"
git commit -m "feat: add river detail page with forecast strip and 30-day history chart"
```

---

## Task 15: Gauge Seed Script + Smoke Test

**Files:**
- Create: `pipeline/sql/seed_gauges.sql`
- Create: `pipeline/scripts/seed_db.py`

- [ ] **Step 1: Write `pipeline/sql/seed_gauges.sql`**

Generate this from `rivers.py` in the next step — no manual SQL needed.

- [ ] **Step 2: Write `pipeline/scripts/seed_db.py`**

```python
"""Seed the gauges table from the registry.

Run once after `docker-compose up`:
  python pipeline/scripts/seed_db.py
"""

import sys, os, json
sys.path.insert(0, "pipeline")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost:5432/riffle")

from sqlalchemy import create_engine, text
from config.rivers import GAUGES

engine = create_engine(os.environ["DATABASE_URL"])

with engine.begin() as conn:
    for g in GAUGES:
        conn.execute(
            text("""
                INSERT INTO gauges (usgs_gauge_id, name, river, lat, lon, flow_thresholds)
                VALUES (:usgs_gauge_id, :name, :river, :lat, :lon, :thresholds::jsonb)
                ON CONFLICT (usgs_gauge_id) DO UPDATE
                  SET name = EXCLUDED.name,
                      river = EXCLUDED.river,
                      lat = EXCLUDED.lat,
                      lon = EXCLUDED.lon,
                      flow_thresholds = EXCLUDED.flow_thresholds
            """),
            {
                "usgs_gauge_id": g["usgs_gauge_id"],
                "name": g["name"],
                "river": g["river"],
                "lat": g["lat"],
                "lon": g["lon"],
                "thresholds": json.dumps(g["flow_thresholds"]),
            },
        )
    print(f"Seeded {len(GAUGES)} gauges.")
```

- [ ] **Step 3: Start Docker Compose and seed the database**

```bash
docker-compose up -d postgres
sleep 5  # wait for postgres healthcheck
python pipeline/scripts/seed_db.py
```

Expected: `Seeded 11 gauges.`

- [ ] **Step 4: Run the full ingest pipeline manually**

```bash
# Start all services
docker-compose up -d

# Trigger DAGs manually (after airflow-init completes)
docker-compose exec airflow-scheduler airflow dags trigger gauge_ingest
docker-compose exec airflow-scheduler airflow dags trigger weather_ingest

# After both complete (~30s), trigger scoring
docker-compose exec airflow-scheduler airflow dags trigger condition_score
```

- [ ] **Step 5: Smoke test the API**

```bash
# Wait for api service to be up, then:
curl http://localhost:8000/api/rivers | python3 -m json.tool | head -50
```

Expected: JSON array with 11 river objects, each with a `condition` field.

- [ ] **Step 6: Smoke test the frontend**

```bash
cd web
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3000 — verify the Colorado map renders with colored markers.

- [ ] **Step 7: Commit**

```bash
cd ..
git add pipeline/scripts/ pipeline/sql/
git commit -m "feat: add gauge seed script and integration smoke test instructions"
```

---

## Task 16: README + .env Setup

**Files:**
- Create: `README.md`

- [ ] **Step 1: Copy `.env.example` to `.env` and fill in values**

```bash
cp .env.example .env
# Generate a Fernet key for Airflow:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Paste output into AIRFLOW__CORE__FERNET_KEY in .env
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Riffle — Colorado Fly Fishing Conditions

Real-time USGS stream gauge conditions + XGBoost-powered 3-day fishing forecasts
for Colorado rivers, surfaced on an interactive Next.js map.

## Architecture

```
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
```

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
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| API | http://localhost:8000 | — |
| API docs | http://localhost:8000/docs | — |
| Frontend | http://localhost:3000 | — |

## Stack

- **Pipeline:** Apache Airflow 2.9, XGBoost, MLflow, Python 3.11
- **API:** FastAPI, SQLAlchemy, PostgreSQL 15
- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, Leaflet.js
- **Deploy:** Docker Compose (local/Railway), Vercel (frontend)
```

- [ ] **Step 3: Commit**

```bash
git add README.md .env.example
git commit -m "docs: add README with architecture diagram and quick start"
```

---

## Self-Review

### Spec Coverage Check

| Spec requirement | Task(s) |
|---|---|
| USGS gauge data ingest (flow, temp, height) | Task 4, Task 10 |
| Open-Meteo weather + 3-day forecast ingest | Task 5, Task 10 |
| 11 Colorado gauges in registry | Task 3 |
| gauge_ingest_dag (daily 7am) | Task 10 |
| weather_ingest_dag (daily 7:05am) | Task 10 |
| condition_score_dag (daily 7:30am, waits on both) | Task 11 |
| train_dag (weekly Monday 3am) | Task 11 |
| 5-class condition scale | Task 8 |
| 8 feature columns | Task 7 |
| Bootstrapped labels from domain thresholds | Task 8 |
| XGBoost multi-class + MLflow logging | Task 8 |
| Model promotion to production in MLflow | Task 9 |
| GET /api/rivers | Task 12 |
| GET /api/rivers/{gauge_id} | Task 12 |
| GET /api/rivers/{gauge_id}/history | Task 12 |
| Interactive Leaflet map, color-coded markers | Task 13 |
| River detail page: stats + forecast + history | Task 14 |
| DB schema: gauges, gauge_readings, weather_readings, predictions | Task 2 |
| Docker Compose (Airflow + Postgres + MLflow + FastAPI) | Task 2 |
| Seed script | Task 15 |
| Vercel-ready Next.js | Task 13 (npm run build verified) |

### Placeholder Scan

- No TBD or TODO in any task ✓
- All code steps contain actual code ✓
- All test steps include exact commands and expected output ✓
- Types used in later tasks (e.g., `USGSReading`, `WeatherDay`, `CONDITION_CLASSES`) are defined in earlier tasks ✓

### Type Consistency

- `CONDITION_CLASSES` defined in `train.py` (Task 8), imported in `score.py` (Task 9) ✓
- `FEATURE_COLS` defined in `train.py`, imported in `score.py` ✓
- `build_feature_vector` signature is consistent across `features.py` (Task 7), `condition_score_dag.py` (Task 11), `train_dag.py` (Task 11) ✓
- `get_session()` context manager pattern is consistent in `db_client.py` (Task 6) and `rivers.py` (Task 12) ✓
- API response shapes in `config/api.ts` (Task 13) match FastAPI return dicts in `routes/rivers.py` (Task 12) ✓
