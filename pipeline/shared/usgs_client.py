"""USGS Water Data OGC API client.

Fetches: stream flow (00060, cfs), water temp (00010, °C→°F),
gauge height (00065, ft) for a single gauge ID.

New API: https://api.waterdata.usgs.gov/ogcapi/v0
"""

import os
import time
from dataclasses import dataclass
from datetime import date as date_type, datetime, timezone
from typing import List, Optional

import requests

USGS_BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
USGS_LATEST_URL = f"{USGS_BASE_URL}/latest-continuous/items"
USGS_RANGE_URL = f"{USGS_BASE_URL}/continuous/items"
USGS_DAILY_URL = f"{USGS_BASE_URL}/daily/items"

PARAM_FLOW = "00060"
PARAM_TEMP = "00010"
PARAM_HEIGHT = "00065"

STAT_MEAN = "00003"


@dataclass
class USGSReading:
    gauge_id: str
    flow_cfs: Optional[float]
    water_temp_f: Optional[float]   # converted from Celsius
    gauge_height_ft: Optional[float]


@dataclass
class USGSReadingTimestamped:
    gauge_id: str
    fetched_at: datetime
    flow_cfs: Optional[float]
    water_temp_f: Optional[float]
    gauge_height_ft: Optional[float]


@dataclass
class USGSDailyReading:
    gauge_id: str
    observed_date: date_type
    flow_cfs: Optional[float]
    water_temp_f: Optional[float]


def _build_params(base: dict) -> dict:
    """Add api_key to params only if USGS_API_KEY env var is set."""
    api_key = os.environ.get("USGS_API_KEY")
    if api_key:
        base["api_key"] = api_key
    return base


def _celsius_to_fahrenheit(temp_c: float) -> float:
    return temp_c * 9 / 5 + 32


def fetch_gauge_reading(gauge_id: str) -> USGSReading:
    """Fetch latest reading for a USGS gauge using the latest-continuous collection.

    Raises RuntimeError on non-2xx HTTP response.
    """
    params = _build_params({
        "monitoring_location_id": f"USGS-{gauge_id}",
        "parameter_code": f"{PARAM_FLOW},{PARAM_TEMP},{PARAM_HEIGHT}",
        "f": "json",
    })

    resp = requests.get(USGS_LATEST_URL, params=params, timeout=30)
    if not resp.ok:
        raise RuntimeError(f"USGS API returned {resp.status_code} for gauge {gauge_id}")

    features = resp.json().get("features", [])
    values_by_param: dict[str, Optional[float]] = {}

    for feature in features:
        props = feature.get("properties", {})
        code = props.get("parameter_code")
        raw_value = props.get("value")
        if code is not None:
            try:
                values_by_param[code] = float(raw_value)
            except (ValueError, TypeError):
                values_by_param[code] = None

    temp_c = values_by_param.get(PARAM_TEMP)
    water_temp_f = _celsius_to_fahrenheit(temp_c) if temp_c is not None else None

    return USGSReading(
        gauge_id=gauge_id,
        flow_cfs=values_by_param.get(PARAM_FLOW),
        water_temp_f=water_temp_f,
        gauge_height_ft=values_by_param.get(PARAM_HEIGHT),
    )


def fetch_gauge_reading_range(
    gauge_id: str,
    start_date: date_type,
    end_date: date_type,
) -> List[USGSReadingTimestamped]:
    """Fetch all readings for a date range using the continuous collection.

    Follows cursor-based pagination via links[rel=next].
    Returns readings sorted by timestamp ascending.
    """
    params = _build_params({
        "monitoring_location_id": f"USGS-{gauge_id}",
        "parameter_code": f"{PARAM_FLOW},{PARAM_TEMP},{PARAM_HEIGHT}",
        "datetime": f"{start_date.isoformat()}/{end_date.isoformat()}",
        "f": "json",
        "skipGeometry": "true",
        "limit": 50000,
    })

    readings_by_time: dict = {}
    url: Optional[str] = USGS_RANGE_URL

    while url is not None:
        for attempt in range(4):
            if url == USGS_RANGE_URL:
                resp = requests.get(url, params=params, timeout=120)
            else:
                resp = requests.get(url, timeout=120)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60 * (2 ** attempt)))
                print(f"    429 rate limit — waiting {retry_after}s before retry {attempt + 1}/4")
                time.sleep(retry_after)
                continue
            break

        if not resp.ok:
            raise RuntimeError(f"USGS API returned {resp.status_code} for gauge {gauge_id}")

        time.sleep(0.5)
        data = resp.json()
        features = data.get("features", [])

        for feature in features:
            props = feature.get("properties", {})
            code = props.get("parameter_code")
            raw_value = props.get("value")
            time_str = props.get("time")

            if code is None or time_str is None:
                continue

            try:
                val = float(raw_value)
            except (ValueError, TypeError):
                val = None

            if time_str not in readings_by_time:
                readings_by_time[time_str] = {}
            readings_by_time[time_str][code] = val

        # Follow pagination
        url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                url = link.get("href")
                break

    results = []
    for time_str, param_vals in readings_by_time.items():
        fetched_at = datetime.fromisoformat(time_str)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)

        # Keep only on-the-hour readings (discard 15/30/45-min intervals)
        if fetched_at.minute != 0:
            continue

        temp_c = param_vals.get(PARAM_TEMP)
        results.append(USGSReadingTimestamped(
            gauge_id=gauge_id,
            fetched_at=fetched_at,
            flow_cfs=param_vals.get(PARAM_FLOW),
            water_temp_f=_celsius_to_fahrenheit(temp_c) if temp_c is not None else None,
            gauge_height_ft=param_vals.get(PARAM_HEIGHT),
        ))

    return sorted(results, key=lambda r: r.fetched_at)


def fetch_gauge_daily_range(
    gauge_id: str,
    start_date: date_type,
    end_date: date_type,
) -> List[USGSDailyReading]:
    """Fetch daily-mean readings for a date range using the daily collection.

    Replaces the chunked, paginated continuous-collection backfill. The daily
    collection returns one row per day per parameter per statistic; we keep
    only the mean (statistic_id=00003). For 2 years of one gauge, the entire
    response (~3000 features for flow + temp) fits in a single page.

    Returns readings sorted by date ascending.
    """
    params = _build_params({
        "monitoring_location_id": f"USGS-{gauge_id}",
        "parameter_code": f"{PARAM_FLOW},{PARAM_TEMP}",
        "datetime": f"{start_date.isoformat()}/{end_date.isoformat()}",
        "f": "json",
        "limit": 10000,
    })

    readings_by_date: dict[date_type, dict[str, Optional[float]]] = {}
    url: Optional[str] = USGS_DAILY_URL

    while url is not None:
        for attempt in range(4):
            if url == USGS_DAILY_URL:
                resp = requests.get(url, params=params, timeout=60)
            else:
                resp = requests.get(url, timeout=60)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60 * (2 ** attempt)))
                print(f"    429 rate limit — waiting {retry_after}s before retry {attempt + 1}/4")
                time.sleep(retry_after)
                continue
            break

        if not resp.ok:
            raise RuntimeError(f"USGS daily API returned {resp.status_code} for gauge {gauge_id}")

        data = resp.json()

        for feature in data.get("features", []):
            props = feature.get("properties", {})
            if props.get("statistic_id") != STAT_MEAN:
                continue

            code = props.get("parameter_code")
            time_str = props.get("time")
            raw_value = props.get("value")
            if code is None or time_str is None:
                continue

            try:
                obs_date = date_type.fromisoformat(time_str)
            except ValueError:
                continue

            try:
                val = float(raw_value)
            except (ValueError, TypeError):
                val = None

            if obs_date not in readings_by_date:
                readings_by_date[obs_date] = {}
            readings_by_date[obs_date][code] = val

        url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                url = link.get("href")
                break

    results = []
    for obs_date, param_vals in readings_by_date.items():
        temp_c = param_vals.get(PARAM_TEMP)
        results.append(USGSDailyReading(
            gauge_id=gauge_id,
            observed_date=obs_date,
            flow_cfs=param_vals.get(PARAM_FLOW),
            water_temp_f=_celsius_to_fahrenheit(temp_c) if temp_c is not None else None,
        ))

    return sorted(results, key=lambda r: r.observed_date)
