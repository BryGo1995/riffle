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
