"""USGS Water Services instantaneous values client.

Fetches: stream flow (00060, cfs), water temp (00010, °C→°F),
gauge height (00065, ft) for a single gauge ID.
"""

from dataclasses import dataclass
from datetime import date as date_type, datetime, timezone
from typing import List, Optional
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


@dataclass
class USGSReadingTimestamped:
    gauge_id: str
    fetched_at: datetime
    flow_cfs: Optional[float]
    water_temp_f: Optional[float]
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


def fetch_gauge_reading_range(
    gauge_id: str,
    start_date: date_type,
    end_date: date_type,
) -> List[USGSReadingTimestamped]:
    """Fetch all instantaneous readings for a date range, sorted by time."""
    request_params = {
        "sites": gauge_id,
        "parameterCd": f"{PARAM_FLOW},{PARAM_TEMP},{PARAM_HEIGHT}",
        "startDT": start_date.isoformat(),
        "endDT": end_date.isoformat(),
        "format": "json",
        "siteStatus": "all",
    }
    resp = requests.get(USGS_IV_URL, params=request_params, timeout=60)
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
    for dt_str, param_vals in readings_by_time.items():
        fetched_at = datetime.fromisoformat(dt_str)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        temp_c = param_vals.get(PARAM_TEMP)
        results.append(USGSReadingTimestamped(
            gauge_id=gauge_id,
            fetched_at=fetched_at,
            flow_cfs=param_vals.get(PARAM_FLOW),
            water_temp_f=(temp_c * 9 / 5 + 32) if temp_c is not None else None,
            gauge_height_ft=param_vals.get(PARAM_HEIGHT),
        ))

    return sorted(results, key=lambda r: r.fetched_at)
