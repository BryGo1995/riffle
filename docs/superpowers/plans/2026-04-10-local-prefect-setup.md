# Local Prefect Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a self-hosted Prefect server and serve() process on the always-on local Fedora box, wire up a daily ingest → score chain at 04:00 America/Denver, schedule weekly training, and provide a monitoring UI. Hourly flows remain registered but paused.

**Architecture:** Two new Docker services — `prefect-server` (Prefect 3 API+UI, SQLite-backed via named volume) and `prefect-serve` (renamed from the existing `prefect-worker`, runs `python serve.py`). The daily ingest gap is closed by extracting `scripts/backfill_daily.py`'s per-gauge helpers into `pipeline/shared/ingest_daily.py`, then calling them for `yesterday → yesterday` inside a new `ingest_daily_task` that runs before `score_daily_task` inside a single `daily_forecast_flow`. The old `flows/score_daily.py` is replaced by `flows/daily_forecast.py`.

**Tech Stack:** Prefect 3, Python 3.11, Docker Compose, pytest, SQLite (Prefect state), existing Postgres 15 + MLflow 3.10.1 for the pipeline.

**Spec:** `docs/superpowers/specs/2026-04-10-local-prefect-setup-design.md`

**Issue:** [#13](https://github.com/BryGo1995/riffle/issues/13)

---

## Task 1: Extract ingest helpers into `shared/ingest_daily.py`

Create a new shared module that exposes `IngestResult`, `ingest_gauge_daily`, and `ingest_weather_daily`. Refactor `scripts/backfill_daily.py` to import from it so there is exactly one copy of the "fetch + upsert N days for one gauge" logic. Built test-first.

**Files:**
- Create: `pipeline/shared/ingest_daily.py`
- Create: `pipeline/tests/test_ingest_daily.py`
- Modify: `pipeline/scripts/backfill_daily.py` (replace local helpers with imports)

- [ ] **Step 1: Write the failing tests for `shared.ingest_daily`**

Create `pipeline/tests/test_ingest_daily.py`:

```python
import sys
sys.path.insert(0, "pipeline")

from datetime import date
from unittest.mock import patch, MagicMock

from shared.ingest_daily import (
    IngestResult,
    ingest_gauge_daily,
    ingest_weather_daily,
)
from shared.usgs_client import USGSDailyReading
from shared.weather_client import WeatherDay


def _fake_usgs_row(observed_date: date, flow: float | None) -> USGSDailyReading:
    return USGSDailyReading(
        gauge_id="09085000",
        observed_date=observed_date,
        flow_cfs=flow,
        water_temp_f=48.0,
    )


def _fake_weather_day(observed_date: date) -> WeatherDay:
    return WeatherDay(
        observed_date=observed_date,
        precip_mm_sum=1.0,
        air_temp_f_mean=50.0,
        air_temp_f_min=40.0,
        air_temp_f_max=60.0,
        snowfall_mm_sum=0.0,
        wind_speed_mph_max=5.0,
    )


@patch("shared.ingest_daily.upsert_gauge_daily_reading")
@patch("shared.ingest_daily.fetch_gauge_daily_range")
def test_ingest_gauge_daily_returns_counts_for_valid_rows(
    mock_fetch, mock_upsert
):
    mock_fetch.return_value = [
        _fake_usgs_row(date(2026, 4, 9), flow=150.0),
        _fake_usgs_row(date(2026, 4, 10), flow=160.0),
    ]

    result = ingest_gauge_daily(
        gauge_id=1,
        usgs_id="09085000",
        start=date(2026, 4, 9),
        end=date(2026, 4, 10),
    )

    assert isinstance(result, IngestResult)
    assert result.rows_written == 2
    assert result.valid_flow_rows == 2
    mock_fetch.assert_called_once_with("09085000", date(2026, 4, 9), date(2026, 4, 10))
    assert mock_upsert.call_count == 2


@patch("shared.ingest_daily.upsert_gauge_daily_reading")
@patch("shared.ingest_daily.fetch_gauge_daily_range")
def test_ingest_gauge_daily_counts_null_flow_as_invalid(
    mock_fetch, mock_upsert
):
    mock_fetch.return_value = [
        _fake_usgs_row(date(2026, 4, 9), flow=None),
        _fake_usgs_row(date(2026, 4, 10), flow=150.0),
    ]

    result = ingest_gauge_daily(
        gauge_id=1,
        usgs_id="09085000",
        start=date(2026, 4, 9),
        end=date(2026, 4, 10),
    )

    assert result.rows_written == 2
    assert result.valid_flow_rows == 1


@patch("shared.ingest_daily.upsert_gauge_daily_reading")
@patch("shared.ingest_daily.fetch_gauge_daily_range")
def test_ingest_gauge_daily_handles_empty_response(mock_fetch, mock_upsert):
    mock_fetch.return_value = []

    result = ingest_gauge_daily(
        gauge_id=1,
        usgs_id="09085000",
        start=date(2026, 4, 10),
        end=date(2026, 4, 10),
    )

    assert result.rows_written == 0
    assert result.valid_flow_rows == 0
    mock_upsert.assert_not_called()


@patch("shared.ingest_daily.upsert_weather_daily_reading")
@patch("shared.ingest_daily.fetch_weather_daily_archive")
def test_ingest_weather_daily_upserts_each_day(mock_fetch, mock_upsert):
    mock_fetch.return_value = [
        _fake_weather_day(date(2026, 4, 9)),
        _fake_weather_day(date(2026, 4, 10)),
    ]

    count = ingest_weather_daily(
        gauge_id=1,
        lat=39.5,
        lon=-106.0,
        start=date(2026, 4, 9),
        end=date(2026, 4, 10),
    )

    assert count == 2
    mock_fetch.assert_called_once_with(39.5, -106.0, date(2026, 4, 9), date(2026, 4, 10))
    assert mock_upsert.call_count == 2
    # Confirm is_forecast=False is passed (historical archive)
    for call in mock_upsert.call_args_list:
        assert call.kwargs["is_forecast"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest pipeline/tests/test_ingest_daily.py -v
```

Expected: `ModuleNotFoundError: No module named 'shared.ingest_daily'` (or ImportError for `IngestResult`).

- [ ] **Step 3: Create `pipeline/shared/ingest_daily.py`**

```python
"""Shared daily ingest core used by both the scheduled daily flow and the
one-shot backfill script.

Keeps "fetch + upsert N days for one gauge" logic in exactly one place so the
scheduled 04:00 run and a manual re-backfill produce identical rows.
"""

from dataclasses import dataclass
from datetime import date

from shared.usgs_client import fetch_gauge_daily_range
from shared.weather_client import fetch_weather_daily_archive
from shared.db_client import (
    upsert_gauge_daily_reading,
    upsert_weather_daily_reading,
)


@dataclass
class IngestResult:
    rows_written: int
    valid_flow_rows: int  # subset of rows_written where flow_cfs is not None


def ingest_gauge_daily(
    gauge_id: int,
    usgs_id: str,
    start: date,
    end: date,
) -> IngestResult:
    """Fetch USGS daily-mean flow/temp for [start, end] and upsert each row.

    Returns an IngestResult so callers can distinguish "rows arrived but USGS
    hasn't finalized yesterday's flow yet" from "rows arrived with valid flow".
    """
    readings = fetch_gauge_daily_range(usgs_id, start, end)
    valid = 0
    for r in readings:
        upsert_gauge_daily_reading(
            gauge_id=gauge_id,
            observed_date=r.observed_date,
            flow_cfs=r.flow_cfs,
            water_temp_f=r.water_temp_f,
        )
        if r.flow_cfs is not None:
            valid += 1
    return IngestResult(rows_written=len(readings), valid_flow_rows=valid)


def ingest_weather_daily(
    gauge_id: int,
    lat: float,
    lon: float,
    start: date,
    end: date,
) -> int:
    """Fetch Open-Meteo daily archive for [start, end] and upsert each day.

    Returns the number of days written. Weather archive is reliable enough
    that we don't track a separate "valid" count — if the fetch succeeds at
    all, the rows are usable.
    """
    days = fetch_weather_daily_archive(lat, lon, start, end)
    for d in days:
        upsert_weather_daily_reading(
            gauge_id=gauge_id,
            observed_date=d.observed_date,
            precip_mm_sum=d.precip_mm_sum,
            air_temp_f_mean=d.air_temp_f_mean,
            air_temp_f_min=d.air_temp_f_min,
            air_temp_f_max=d.air_temp_f_max,
            snowfall_mm_sum=d.snowfall_mm_sum,
            wind_speed_mph_max=d.wind_speed_mph_max,
            is_forecast=False,
        )
    return len(days)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest pipeline/tests/test_ingest_daily.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Refactor `scripts/backfill_daily.py` to use the shared module**

Replace the local `backfill_weather_daily` and `backfill_gauge_daily` functions. Open `pipeline/scripts/backfill_daily.py` and replace lines 23-59 (the imports-through-`backfill_gauge_daily` block) with:

```python
from config.rivers import ACTIVE_GAUGES
from shared.db_client import get_gauge_id
from shared.ingest_daily import ingest_gauge_daily, ingest_weather_daily
```

Then replace the two calls inside the `main()` loop. Find this block:

```python
        gauge_id = get_gauge_id(usgs_id)

        weather_count = backfill_weather_daily(gauge_id, cfg["lat"], cfg["lon"], start, end)
        print(f"  weather: {weather_count} days")

        gauge_count = backfill_gauge_daily(gauge_id, usgs_id, start, end)
        print(f"  gauge:   {gauge_count} days")
```

Replace with:

```python
        gauge_id = get_gauge_id(usgs_id)

        weather_count = ingest_weather_daily(gauge_id, cfg["lat"], cfg["lon"], start, end)
        print(f"  weather: {weather_count} days")

        gauge_result = ingest_gauge_daily(gauge_id, usgs_id, start, end)
        print(f"  gauge:   {gauge_result.rows_written} days ({gauge_result.valid_flow_rows} with flow)")
```

- [ ] **Step 6: Run the full pipeline test suite to confirm no regressions**

```bash
pytest pipeline/tests/ -v
```

Expected: all existing tests pass plus the 4 new `test_ingest_daily.py` tests. Total: 112 passing.

- [ ] **Step 7: Commit**

```bash
git add pipeline/shared/ingest_daily.py pipeline/tests/test_ingest_daily.py pipeline/scripts/backfill_daily.py
git commit -m "$(cat <<'EOF'
refactor: extract daily ingest core into shared/ingest_daily.py

Lifts the per-gauge USGS + Open-Meteo fetch-and-upsert logic out of
scripts/backfill_daily.py into a reusable module so the upcoming
scheduled daily ingest task and the existing backfill script share
exactly one code path. Adds IngestResult to distinguish "rows written"
from "rows with valid flow_cfs" — the scheduled task needs that to
decide whether USGS has actually published yesterday's mean yet.

Refs #13

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create `flows/daily_forecast.py` with ingest → score chain

Replace `flows/score_daily.py` with a new `flows/daily_forecast.py` that contains both an `ingest_daily_task` (3 retries with 5m/15m/30m backoff) and the existing scoring logic moved verbatim into `score_daily_task`. The new `daily_forecast_flow` calls them in order; Prefect's task dependency skips scoring automatically if ingest fails after all retries. Update `tests/test_score.py` imports accordingly.

**Files:**
- Create: `pipeline/flows/daily_forecast.py`
- Delete: `pipeline/flows/score_daily.py`
- Modify: `pipeline/tests/test_score.py` (update imports, add yesterday-fetch test)

- [ ] **Step 1: Write the failing test for `ingest_daily_task` yesterday-fetch behavior**

Add to `pipeline/tests/test_score.py` at the bottom of the file:

```python


# --- daily_forecast ingest task tests ---


@patch("flows.daily_forecast.ingest_weather_daily")
@patch("flows.daily_forecast.ingest_gauge_daily")
@patch("flows.daily_forecast.get_gauge_id")
def test_ingest_daily_task_fetches_yesterday_for_each_active_gauge(
    mock_get_id, mock_ingest_gauge, mock_ingest_weather
):
    from datetime import date, timedelta
    from shared.ingest_daily import IngestResult
    from flows.daily_forecast import ingest_daily_task
    from config.rivers import ACTIVE_GAUGES

    yesterday = date.today() - timedelta(days=1)
    mock_get_id.side_effect = lambda usgs_id: hash(usgs_id) % 10000
    mock_ingest_gauge.return_value = IngestResult(rows_written=1, valid_flow_rows=1)
    mock_ingest_weather.return_value = 1

    # Prefect tasks can be called directly like plain functions in tests using .fn
    ingest_daily_task.fn()

    assert mock_ingest_gauge.call_count == len(ACTIVE_GAUGES)
    # Every call must use yesterday as both start and end
    for call in mock_ingest_gauge.call_args_list:
        assert call.kwargs["start"] == yesterday
        assert call.kwargs["end"] == yesterday
    # Same check for weather
    assert mock_ingest_weather.call_count == len(ACTIVE_GAUGES)
    for call in mock_ingest_weather.call_args_list:
        assert call.kwargs["start"] == yesterday
        assert call.kwargs["end"] == yesterday


@patch("flows.daily_forecast.ingest_weather_daily")
@patch("flows.daily_forecast.ingest_gauge_daily")
@patch("flows.daily_forecast.get_gauge_id")
def test_ingest_daily_task_raises_when_zero_gauges_get_valid_flow(
    mock_get_id, mock_ingest_gauge, mock_ingest_weather
):
    from shared.ingest_daily import IngestResult
    from flows.daily_forecast import ingest_daily_task

    mock_get_id.side_effect = lambda usgs_id: 1
    # Every gauge comes back with zero valid flow rows
    mock_ingest_gauge.return_value = IngestResult(rows_written=1, valid_flow_rows=0)
    mock_ingest_weather.return_value = 1

    with pytest.raises(RuntimeError, match="no gauges received valid flow_cfs"):
        ingest_daily_task.fn()


@patch("flows.daily_forecast.ingest_weather_daily")
@patch("flows.daily_forecast.ingest_gauge_daily")
@patch("flows.daily_forecast.get_gauge_id")
def test_ingest_daily_task_succeeds_when_any_gauge_has_valid_flow(
    mock_get_id, mock_ingest_gauge, mock_ingest_weather
):
    from shared.ingest_daily import IngestResult
    from flows.daily_forecast import ingest_daily_task

    mock_get_id.side_effect = lambda usgs_id: 1
    # Alternate: some valid, some not. Task should NOT raise.
    results = [
        IngestResult(rows_written=1, valid_flow_rows=1 if i % 2 == 0 else 0)
        for i in range(len(__import__("config.rivers", fromlist=["ACTIVE_GAUGES"]).ACTIVE_GAUGES))
    ]
    mock_ingest_gauge.side_effect = results
    mock_ingest_weather.return_value = 1

    # Should not raise
    ingest_daily_task.fn()
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest pipeline/tests/test_score.py -v -k "ingest_daily_task"
```

Expected: `ImportError: cannot import name 'ingest_daily_task' from 'flows.daily_forecast'` (or ModuleNotFoundError since the file doesn't exist yet).

- [ ] **Step 3: Create `pipeline/flows/daily_forecast.py`**

```python
"""Daily forecasting pipeline: ingest yesterday's data, then score today + 7
forecast days for each active gauge.

Structure: one flow, two tasks as a DAG. If ingest fails after all retries,
score is skipped automatically by Prefect's task dependency mechanism — we
never score stale data.

The ingest task retries on a 5m / 15m / 30m backoff so the 04:00 MT run has
roughly 45 minutes of slack for USGS to finalize yesterday's daily-mean row.
"""

from datetime import date, timedelta

from prefect import flow, task

from config.rivers import ACTIVE_GAUGES
from shared.db_client import (
    get_gauge_id,
    get_recent_gauge_daily_readings,
    get_recent_weather_daily_readings,
    upsert_weather_daily_reading,
    upsert_prediction_daily,
)
from shared.ingest_daily import ingest_gauge_daily, ingest_weather_daily
from shared.weather_client import fetch_weather_daily_forecast
from plugins.features import build_daily_feature_vector
from plugins.ml.score import load_production_model, predict_daily_condition


DAILY_MODEL_NAME = "riffle-condition-daily"
FORECAST_DAYS = 7


@task(
    name="ingest-daily",
    retries=3,
    retry_delay_seconds=[300, 900, 1800],  # 5m, 15m, 30m
)
def ingest_daily_task():
    """Fetch yesterday's daily gauge + weather data for every active gauge.

    Raises RuntimeError if zero gauges received a valid flow_cfs row — that
    indicates a real USGS outage worth retrying. Per-gauge missing-flow cases
    are logged and then handled gracefully by score_daily_task's existing
    "no recent flow_cfs — skipping" path.
    """
    yesterday = date.today() - timedelta(days=1)
    print(f"Ingesting daily data for {yesterday}")

    total_valid = 0
    total_gauges = 0
    for cfg in ACTIVE_GAUGES:
        name = cfg["name"]
        usgs_id = cfg["usgs_gauge_id"]
        gauge_id = get_gauge_id(usgs_id)

        ingest_weather_daily(
            gauge_id=gauge_id,
            lat=cfg["lat"],
            lon=cfg["lon"],
            start=yesterday,
            end=yesterday,
        )
        result = ingest_gauge_daily(
            gauge_id=gauge_id,
            usgs_id=usgs_id,
            start=yesterday,
            end=yesterday,
        )
        total_gauges += 1
        if result.valid_flow_rows > 0:
            total_valid += 1
            print(f"  {name} ({usgs_id}): {result.valid_flow_rows} valid flow rows")
        else:
            print(f"  {name} ({usgs_id}): no valid flow yet")

    print(f"\nIngest complete: {total_valid}/{total_gauges} gauges have valid flow_cfs for {yesterday}")

    if total_valid == 0:
        raise RuntimeError(
            f"no gauges received valid flow_cfs for {yesterday} — USGS may not have "
            f"finalized yesterday's mean yet, triggering retry"
        )


def _score_one_gauge(model, gauge_cfg: dict) -> int:
    """Score today + 7 forecast days for one gauge. Returns rows written."""
    gauge_id = get_gauge_id(gauge_cfg["usgs_gauge_id"])
    history = get_recent_gauge_daily_readings(gauge_id, days=730)
    weather_history = get_recent_weather_daily_readings(gauge_id, days=730)

    if not history:
        print(f"  no daily history — skipping")
        return 0

    latest = history[-1]
    latest_flow = latest["flow_cfs"]
    latest_temp = latest["water_temp_f"]
    if latest_flow is None:
        print(f"  no recent flow_cfs — skipping")
        return 0

    forecast_days = fetch_weather_daily_forecast(
        lat=gauge_cfg["lat"],
        lon=gauge_cfg["lon"],
        days=FORECAST_DAYS + 1,  # include today
    )

    for d in forecast_days:
        upsert_weather_daily_reading(
            gauge_id=gauge_id,
            observed_date=d.observed_date,
            precip_mm_sum=d.precip_mm_sum,
            air_temp_f_mean=d.air_temp_f_mean,
            air_temp_f_min=d.air_temp_f_min,
            air_temp_f_max=d.air_temp_f_max,
            snowfall_mm_sum=d.snowfall_mm_sum,
            wind_speed_mph_max=d.wind_speed_mph_max,
            is_forecast=True,
        )

    model_version = "daily-v1"
    written = 0
    today = date.today()

    forecast_as_dicts = [
        {
            "observed_date": d.observed_date,
            "precip_mm_sum": d.precip_mm_sum,
            "air_temp_f_mean": d.air_temp_f_mean,
            "air_temp_f_min": d.air_temp_f_min,
            "air_temp_f_max": d.air_temp_f_max,
            "snowfall_mm_sum": d.snowfall_mm_sum,
            "wind_speed_mph_max": d.wind_speed_mph_max,
            "is_forecast": True,
        }
        for d in forecast_days
    ]
    combined_weather = weather_history + forecast_as_dicts

    for d in forecast_days:
        target_date = d.observed_date
        is_forecast = target_date > today

        features = build_daily_feature_vector(
            flow_cfs=latest_flow,
            water_temp_f=latest_temp,
            air_temp_f_mean=d.air_temp_f_mean,
            air_temp_f_min=d.air_temp_f_min,
            air_temp_f_max=d.air_temp_f_max,
            precip_mm_sum=d.precip_mm_sum,
            snowfall_mm_sum=d.snowfall_mm_sum,
            wind_speed_mph_max=d.wind_speed_mph_max,
            target_date=target_date,
            weather_history_daily=combined_weather,
        )

        condition, confidence = predict_daily_condition(model, features)
        upsert_prediction_daily(
            gauge_id=gauge_id,
            target_date=target_date,
            condition=condition,
            confidence=confidence,
            is_forecast=is_forecast,
            model_version=model_version,
        )
        written += 1

    return written


def _score_all():
    model = load_production_model(model_name=DAILY_MODEL_NAME)
    total = 0
    for cfg in ACTIVE_GAUGES:
        print(f"Scoring {cfg['name']} ({cfg['usgs_gauge_id']})")
        total += _score_one_gauge(model, cfg)
    print(f"\nWrote {total} daily predictions across {len(ACTIVE_GAUGES)} gauges")


@task(name="score-daily", retries=1, retry_delay_seconds=300)
def score_daily_task():
    _score_all()


@flow(name="daily-forecast")
def daily_forecast_flow():
    # Synchronous calls — if ingest_daily_task raises after all retries,
    # the exception propagates and score_daily_task never runs. No need
    # for explicit wait_for.
    ingest_daily_task()
    score_daily_task()
```

- [ ] **Step 4: Delete the old `flows/score_daily.py`**

```bash
rm pipeline/flows/score_daily.py
```

- [ ] **Step 5: Update existing test imports in `tests/test_score.py`**

Find any line in `pipeline/tests/test_score.py` that imports from `flows.score_daily` and change it to import from `flows.daily_forecast`. As of the spec date, there are no such imports in `test_score.py` directly — the imports-from-flows happen in the new tests added in Step 1. Check with:

```bash
grep -n "score_daily" pipeline/tests/test_score.py
```

Expected: only the new test code added in Step 1 references `flows.daily_forecast` / `ingest_daily_task`. If any older test imports `flows.score_daily`, rewrite that import to `flows.daily_forecast` and update the symbol name if needed.

- [ ] **Step 6: Run the full test suite**

```bash
pytest pipeline/tests/ -v
```

Expected: all existing tests pass plus the 3 new ingest-task tests from Step 1. Total: 115 passing. No ImportError for `flows.score_daily` anywhere in the codebase.

- [ ] **Step 7: Verify nothing else imports the deleted module**

```bash
grep -rn "flows.score_daily\|from flows import score_daily\|score_daily_flow" pipeline/ api/ || echo "clean"
```

Expected: `clean`. If any hit surfaces, update it to `flows.daily_forecast` / `daily_forecast_flow`.

- [ ] **Step 8: Commit**

```bash
git add pipeline/flows/daily_forecast.py pipeline/tests/test_score.py
git rm pipeline/flows/score_daily.py
git commit -m "$(cat <<'EOF'
feat: daily_forecast flow with ingest → score DAG (#13)

Replaces flows/score_daily.py with flows/daily_forecast.py, adding an
ingest_daily_task that fetches yesterday's USGS daily-mean and
Open-Meteo daily archive for every active gauge before the existing
scoring logic runs. Ingest has retries=3 with [5m, 15m, 30m] backoff
to tolerate USGS late-publishing at the 04:00 MT scheduled run; score
skips automatically if ingest fails after all retries.

Raises only when zero gauges received a valid flow_cfs (real outage),
so a single broken gauge does not block scoring for the other 22.

Refs #13

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Rewrite `pipeline/serve.py` with four deployments

Register `daily-forecast` (active, 04:00 America/Denver daily), `train-daily` (active, 03:00 America/Denver Sunday), and the two hourly flows `ingest-score-hourly` / `train-hourly` as **paused** deployments so the hourly-model code stays in one-click-resume state when v1.1 arrives.

**Files:**
- Modify: `pipeline/serve.py` (full rewrite)

- [ ] **Step 1: Read the current `pipeline/serve.py`**

```bash
cat pipeline/serve.py
```

Expected: the existing 2-deployment file from the brainstorming walkthrough (ingest_score hourly, train weekly).

- [ ] **Step 2: Rewrite `pipeline/serve.py`**

Overwrite the file with:

```python
"""Prefect deployment registrar for the riffle pipeline.

Uses Prefect 3's `serve()` mode: one long-running process polls the local
Prefect server for scheduled runs and executes them in-process. Suitable
for a single always-on dev box; production will migrate to work pools.

Four deployments:
  - daily-forecast: ingest yesterday + score today + 7 days. 04:00 MT daily.
  - train-daily:    retrain riffle-condition-daily. 03:00 MT every Sunday.
  - ingest-score-hourly: hourly ingest + score for the hourly model (PAUSED,
      deferred to v1.1 per PR #11).
  - train-hourly:   weekly retrain for the hourly model (PAUSED, same reason).

Timezones use America/Denver so the cron handles MST/MDT automatically.
"""

from prefect import serve

from flows.daily_forecast import daily_forecast_flow
from flows.train_daily import train_daily_flow
from flows.ingest_score import ingest_score_flow
from flows.train import train_flow


if __name__ == "__main__":
    serve(
        daily_forecast_flow.to_deployment(
            name="daily-forecast",
            cron="0 4 * * *",
            timezone="America/Denver",
        ),
        train_daily_flow.to_deployment(
            name="train-daily",
            cron="0 3 * * 0",
            timezone="America/Denver",
        ),
        ingest_score_flow.to_deployment(
            name="ingest-score-hourly",
            cron="0 * * * *",
            paused=True,
        ),
        train_flow.to_deployment(
            name="train-hourly",
            cron="0 9 * * 1",
            paused=True,
        ),
    )
```

- [ ] **Step 3: Syntax-check the new `serve.py` without actually running it**

```bash
python -c "import ast; ast.parse(open('pipeline/serve.py').read()); print('ok')"
```

Expected: `ok`. (We can't actually run `python serve.py` outside Docker — it tries to connect to a Prefect server.)

- [ ] **Step 4: Confirm all imported flow modules still exist**

```bash
ls pipeline/flows/daily_forecast.py pipeline/flows/train_daily.py pipeline/flows/ingest_score.py pipeline/flows/train.py
```

Expected: all four files listed with no errors.

- [ ] **Step 5: Run the pipeline test suite**

```bash
pytest pipeline/tests/ -v
```

Expected: still 115 passing. `serve.py` has no direct tests (behavior is verified end-to-end in Task 6).

- [ ] **Step 6: Commit**

```bash
git add pipeline/serve.py
git commit -m "$(cat <<'EOF'
feat: register four Prefect deployments in serve.py (#13)

- daily-forecast: active, 04:00 America/Denver daily
- train-daily:    active, 03:00 America/Denver Sunday
- ingest-score-hourly: paused (hourly model deferred to v1.1)
- train-hourly:   paused (same reason)

Timezones use America/Denver so cron handles MST/MDT automatically via
Prefect 3's timezone kwarg on to_deployment().

Refs #13

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `prefect-server` service + rename `prefect-worker` → `prefect-serve`

Two new containers in `docker-compose.yml`: the Prefect API/UI server (SQLite in a named volume) and the renamed serve process. The serve process depends on the server being healthy before it registers deployments. All new services get `restart: unless-stopped`.

**Files:**
- Modify: `docker-compose.yml` (add `prefect-server`, rewrite `prefect-worker` block, add `prefect-data` volume)

- [ ] **Step 1: Read the current `docker-compose.yml`**

```bash
cat docker-compose.yml
```

Expected: the current 4-service compose file (postgres, mlflow, api, prefect-worker) plus 2 volumes (postgres-data, mlflow-artifacts).

- [ ] **Step 2: Add the `prefect-server` service**

Insert the following block in `docker-compose.yml` *before* the existing `prefect-worker:` line:

```yaml
  prefect-server:
    image: prefecthq/prefect:3-python3.11
    restart: unless-stopped
    command: prefect server start --host 0.0.0.0
    environment:
      PREFECT_SERVER_API_HOST: 0.0.0.0
      PREFECT_HOME: /root/.prefect
    ports:
      - "4200:4200"
    volumes:
      - prefect-data:/root/.prefect
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:4200/api/health').read()"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 20s
    networks:
      default:
        aliases:
          - prefect-server

```

- [ ] **Step 3: Replace the `prefect-worker` block with `prefect-serve`**

Find the existing block in `docker-compose.yml`:

```yaml
  prefect-worker:
    build:
      context: ./pipeline
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      MLFLOW_TRACKING_URI: http://mlflow:5000
      PREFECT_API_URL: ${PREFECT_API_URL:-}
      PREFECT_API_KEY: ${PREFECT_API_KEY:-}
      USGS_API_KEY: ${USGS_API_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
```

Replace it with:

```yaml
  prefect-serve:
    build:
      context: ./pipeline
      dockerfile: Dockerfile
    restart: unless-stopped
    command: python serve.py
    environment:
      DATABASE_URL: postgresql+psycopg2://riffle:riffle@postgres:5432/riffle
      MLFLOW_TRACKING_URI: http://mlflow:5000
      PREFECT_API_URL: ${PREFECT_API_URL:-http://prefect-server:4200/api}
      USGS_API_KEY: ${USGS_API_KEY:-}
    depends_on:
      postgres:
        condition: service_healthy
      prefect-server:
        condition: service_healthy
      mlflow:
        condition: service_started
```

- [ ] **Step 4: Declare the `prefect-data` volume**

Find the `volumes:` block at the bottom of `docker-compose.yml`:

```yaml
volumes:
  postgres-data:
  mlflow-artifacts:
```

Replace with:

```yaml
volumes:
  postgres-data:
  mlflow-artifacts:
  prefect-data:
```

- [ ] **Step 5: Validate the compose file syntax**

```bash
docker compose config --quiet && echo "ok"
```

Expected: `ok`. If the compose file has a YAML error or a service reference that can't resolve, this will fail loudly.

- [ ] **Step 6: Confirm the old service name is gone and the new ones are present**

```bash
docker compose config --services | sort
```

Expected output (alphabetically):
```
api
mlflow
postgres
prefect-serve
prefect-server
```

No `prefect-worker` line.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml
git commit -m "$(cat <<'EOF'
chore: add local prefect-server and rename worker to serve (#13)

Adds a self-hosted prefecthq/prefect:3-python3.11 server container with
SQLite state on a prefect-data named volume, exposing the UI on :4200.
Renames prefect-worker to prefect-serve, points it at the local server
via internal DNS, drops the unused PREFECT_API_KEY env var, and
health-gates its dependency on the server + postgres + mlflow so
deployment registration only runs once everything is ready.

Refs #13

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Documentation — README + `.env.example`

Add a "Scheduled Pipelines" section to the README covering start, UI access, the four deployments, manual triggers, pause/resume, logs, reset procedure, and the one-time `systemctl enable docker` host-setup note. Append a commented `PREFECT_API_URL` line to `.env.example` for future Cloud experiments.

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Check if `.env.example` exists and what it currently contains**

```bash
cat .env.example 2>/dev/null || echo "(file does not exist)"
```

If it doesn't exist, create it in Step 3 with just the new content. If it does, Step 3 appends.

- [ ] **Step 2: Find the right insertion point in `README.md`**

```bash
grep -n "^##\|^### " README.md
```

Look for a "Development" / "Running the stack" / "Getting started" / similar section. The "Scheduled Pipelines" section should live right after whichever section covers `docker compose up`.

- [ ] **Step 3: Append to `.env.example`**

Append the following lines (if the file exists, `>>` it; if it doesn't, create it fresh with only these lines):

```bash
cat >> .env.example <<'EOF'

# Prefect (optional) — override only if pointing at Prefect Cloud instead of
# the bundled self-hosted server at http://prefect-server:4200/api. Leave
# unset for local dev.
# PREFECT_API_URL=https://api.prefect.cloud/api/accounts/<id>/workspaces/<id>
EOF
```

- [ ] **Step 4: Add the "Scheduled Pipelines" section to `README.md`**

Insert the following block after the `docker compose up` section (exact location depends on the README structure found in Step 2 — use your judgement to place it near other "how to run the stack" content):

```markdown
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

### One-time host setup (Fedora 43)

Fedora does not enable the Docker daemon at boot by default. Without this, `restart: unless-stopped` only applies while Docker is already running — after a host reboot the containers stay down until someone manually starts Docker.

```bash
systemctl is-enabled docker
# If it returns "disabled":
sudo systemctl enable --now docker
```
```

- [ ] **Step 5: Validate the README renders reasonably**

```bash
head -20 README.md && echo "---" && grep -n "Scheduled Pipelines" README.md
```

Expected: the section heading appears exactly once.

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example
git commit -m "$(cat <<'EOF'
docs: README section for local Prefect setup (#13)

Documents how to start the stack, access the UI at localhost:4200,
the four registered deployments, how to manually trigger / pause /
resume schedules, how to view logs, how to reset run history, and
common troubleshooting. Also documents the one-time systemctl
enable docker step needed on Fedora for reboot survival.

Adds a commented PREFECT_API_URL override to .env.example for
future Prefect Cloud experiments.

Refs #13

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: End-to-end verification

Bring up the full stack on the branch and confirm every moving piece works: both new containers start and reach healthy state, the four deployments appear in the UI, a manual trigger of `daily-forecast` runs successfully end-to-end, the API still returns fresh data, a manual trigger of `train-daily` registers a new MLflow model version, and the state survives a container restart.

No code commits in this task — only verification. If any step fails, pause and fix before proceeding to the PR.

**Files:** none modified (verification-only task)

- [ ] **Step 1: Bring the stack down cleanly and remove stale prefect-worker container**

```bash
docker compose down
docker ps -a --filter name=riffle-prefect-worker --format '{{.Names}}' | xargs -r docker rm -f
```

Expected: all riffle containers removed. The `xargs` line explicitly kills any lingering `riffle-prefect-worker-1` from the old service name since compose's `down` only removes containers matching services currently in the file.

- [ ] **Step 2: Build and start the updated stack**

```bash
docker compose up -d --build
```

Expected: all 6 services start. The `prefect-server` image (`prefecthq/prefect:3-python3.11`) may take a few minutes to pull on the first run.

- [ ] **Step 3: Confirm all services are healthy**

```bash
sleep 20 && docker compose ps
```

Expected: `postgres`, `mlflow`, `api`, `prefect-server` all in `healthy` / `running (healthy)` state. `prefect-serve` shows `running` (no healthcheck on that service).

- [ ] **Step 4: Confirm `prefect-serve` successfully registered the deployments**

```bash
docker logs riffle-prefect-serve-1 2>&1 | tail -40
```

Expected: log lines mentioning "Your deployments are being served" and the four deployment names (`daily-forecast`, `train-daily`, `ingest-score-hourly`, `train-hourly`). No connection errors to `prefect-server:4200`.

- [ ] **Step 5: Verify the UI is reachable and lists four deployments**

```bash
curl -s http://localhost:4200/api/health && echo
curl -s http://localhost:4200/api/deployments/filter -X POST -H "Content-Type: application/json" -d '{}' | python -c "import json,sys; d=json.load(sys.stdin); print('\n'.join(sorted(x['name']+' paused=' + str(x.get('paused', False)) for x in d)))"
```

Expected:
```
True
daily-forecast paused=False
ingest-score-hourly paused=True
train-daily paused=False
train-hourly paused=True
```

If the second command fails with a schema error, open `http://localhost:4200` in a browser instead and visually confirm the same four deployments and their paused state on the Deployments page.

- [ ] **Step 6: Manually trigger `daily-forecast` and watch it run end-to-end**

Open `http://localhost:4200` → Deployments → `daily-forecast` → **Quick run**.

Then watch the run in the UI (Flow Runs tab) or tail container logs:

```bash
docker logs -f riffle-prefect-serve-1 2>&1 | grep -iE "daily-forecast|ingest|score"
```

Expected: run transitions Pending → Running → Completed within ~2-5 minutes. The `ingest-daily` task logs per-gauge results ("valid flow rows" or "no valid flow yet"). The `score-daily` task logs ~23 "Scoring <name>" lines and a total at the end.

- [ ] **Step 7: Verify the API still returns fresh data**

```bash
curl -s http://localhost:8000/api/v1/rivers | head -100
curl -s http://localhost:8000/api/v1/rivers/09085000 | python -m json.tool
```

Expected: `/api/v1/rivers` returns a list of river objects with current condition labels. `/api/v1/rivers/09085000` returns `current` and a 7-entry `forecast` array. The `model_version` field should show `daily-v1`.

- [ ] **Step 8: Manually trigger `train-daily` and verify a new MLflow model version appears**

Open `http://localhost:4200` → Deployments → `train-daily` → **Quick run**.

Wait for completion, then check MLflow:

```bash
curl -s "http://localhost:5000/api/2.0/mlflow/registered-models/get?name=riffle-condition-daily" | python -m json.tool
```

Expected: `latest_versions` contains at least one version with `current_stage: "Production"`. Note the version number — it should be higher than whatever was there before (it was version 1 after PR #11's verification).

- [ ] **Step 9: Restart `prefect-serve` and confirm state survives**

```bash
docker compose restart prefect-serve
sleep 15
docker logs riffle-prefect-serve-1 2>&1 | tail -20
curl -s http://localhost:4200/api/deployments/filter -X POST -H "Content-Type: application/json" -d '{}' | python -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} deployments')"
```

Expected: serve process re-registers the same four deployments. The filter query still returns `4 deployments`. Past run history from Steps 6 and 8 is still visible in the UI (it lives in the SQLite DB on the `prefect-data` volume, not in the container).

- [ ] **Step 10: Sanity-check port / container map**

```bash
docker ps --filter name=riffle --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Expected output should include rows for `riffle-prefect-server-1` (port `4200:4200`) and `riffle-prefect-serve-1` (no published port) — both showing `Up`. No `riffle-prefect-worker-1` anywhere.

- [ ] **Step 11: If anything in Steps 1-10 failed, document the failure and fix before PR**

No commit needed if everything passes. If something fails, the fix gets its own commit referencing `#13` in the message.

---

## Self-Review Notes

Reviewed this plan against `docs/superpowers/specs/2026-04-10-local-prefect-setup-design.md`:

- ✅ Decision 1 (`serve()` over work pools): Task 3 uses `serve()` directly in `pipeline/serve.py`.
- ✅ Decision 2 (self-hosted vs Cloud): Task 4 adds the `prefect-server` container; no Cloud config anywhere.
- ✅ Decision 3 (SQLite in named volume): Task 4 creates `prefect-data` volume mounted at `/root/.prefect`.
- ✅ Decision 4 (extract ingest core): Task 1 creates `shared/ingest_daily.py` and refactors the backfill script.
- ✅ Decision 5 (single flow with two tasks): Task 2 creates `daily_forecast_flow` calling `ingest_daily_task` then `score_daily_task` synchronously — if ingest raises after all retries, the exception propagates and score is skipped.
- ✅ Decision 6 (file rename): Task 2 creates `flows/daily_forecast.py` and deletes `flows/score_daily.py`.
- ✅ Decision 7 (cadence 04:00 daily, 03:00 Sunday, America/Denver): Task 3 `serve.py` has exactly these cron + timezone values.
- ✅ Decision 8 (ingest retry `[300, 900, 1800]`): Task 2 `ingest_daily_task` uses this retry policy literally.
- ✅ Decision 9 (hourly flows paused): Task 3 passes `paused=True` on both hourly deployments.
- ✅ Decision 10 (default-on, internal DNS, health-gated): Task 4 adds no compose profile, defaults `PREFECT_API_URL` to internal DNS, and adds health-gated `depends_on`.
- ✅ Verification plan from spec covered by Task 6 steps 2-9.
- ✅ Host setup (`systemctl enable docker`) documented in Task 5 README update.
- ✅ Signature `ingest_gauge_daily(..., start, end) -> IngestResult` is consistent across Task 1 (definition), Task 2 (call from flow), and Task 1 Step 5 (call from backfill script).
- ✅ `IngestResult` field names (`rows_written`, `valid_flow_rows`) match across all call sites.
- ✅ No placeholders, no "similar to Task N" references, no "add appropriate error handling".

One minor ambiguity to flag for the executor: in Task 5 Step 4, the exact insertion point in `README.md` depends on the current structure of that file. I did not prescribe a line number because the README may have been updated since the spec was written. The executor should use judgment to place the new section near the existing `docker compose up` / "Development" content.

---

## Completion criteria

When all tasks are done and committed:
- 6 new commits on `riffle-13-local-prefect` (one per task 1-5, plus task 6 verification).
- `docker compose up -d` brings up the full stack including prefect-server and prefect-serve.
- `http://localhost:4200` shows four deployments (two active, two paused).
- `daily-forecast` and `train-daily` can be triggered manually from the UI and complete successfully end-to-end.
- `pytest pipeline/tests/ -v` shows ~115 passing (108 existing + 4 new in `test_ingest_daily.py` + 3 new in `test_score.py`).
- No references to `flows.score_daily` anywhere in the repo.
- README has a "Scheduled Pipelines" section covering operation, troubleshooting, and host setup.

Ready for PR: `riffle-13-local-prefect` → `main`.
