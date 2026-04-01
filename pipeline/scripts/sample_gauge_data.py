"""One-off script to pull and inspect data for a single USGS gauge.

Uses the new USGS Water Data OGC API (api.waterdata.usgs.gov).

Saves results to:
  - output/gauge_<site_no>.json — raw GeoJSON response (all pages combined)
  - output/gauge_<site_no>.csv  — parsed datetime/flow/temp/height readings

Usage:
  Run from any directory — output/ will be created wherever you are:
    python pipeline/scripts/sample_gauge_data.py <site_no>
    python pipeline/scripts/sample_gauge_data.py <site_no> --start 2025-01-01 --end 2025-12-31

  Arguments:
    site_no         USGS site number to query (required). Find site numbers by
                    running explore_gauges.py and opening output/gauges_co.csv.
    --start         Start date in YYYY-MM-DD format (default: 90 days ago)
    --end           End date in YYYY-MM-DD format (default: today)

  Environment:
    USGS_API_KEY    Optional API key for higher rate limits. Without it you may
                    hit 429 responses for large date ranges.

  Examples:
    python pipeline/scripts/sample_gauge_data.py 09033300
    python pipeline/scripts/sample_gauge_data.py 06700000 --start 2024-01-01 --end 2026-03-31
"""

import argparse
import csv
import json
import os
from datetime import date, timedelta

import requests

PARAM_CODES = "00060,00010,00065"
PARAM_NAMES = {
    "00060": "flow_cfs",
    "00010": "water_temp_c",
    "00065": "gauge_height_ft",
}

API_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0"
RANGE_URL = f"{API_BASE}/collections/continuous/items"
OUTPUT_DIR = "output"


def _build_params(site_no, start, end):
    params = {
        "monitoring_location_id": f"USGS-{site_no}",
        "parameter_code": PARAM_CODES,
        "datetime": f"{start}/{end}",
        "limit": 1000,
        "f": "json",
    }
    api_key = os.environ.get("USGS_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def fetch_gauge(site_no, start, end):
    """Fetch all readings for a date range, paginating via cursor links."""
    all_features = []
    url = RANGE_URL
    params = _build_params(site_no, start, end)

    while url:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        all_features.extend(data.get("features", []))

        next_url = next(
            (lnk["href"] for lnk in data.get("links", []) if lnk.get("rel") == "next"),
            None,
        )
        url = next_url
        params = {}  # params are encoded in the cursor URL

    return {"type": "FeatureCollection", "features": all_features}


def parse_readings(data):
    """Group features by timestamp and build one row per timestamp."""
    rows = {}
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        time_str = props.get("time", "")
        code = props.get("parameter_code", "")
        field = PARAM_NAMES.get(code, code)
        raw_value = props.get("value")
        rows.setdefault(time_str, {"datetime": time_str})
        rows[time_str][field] = raw_value

    return sorted(rows.values(), key=lambda r: r["datetime"])


def print_summary(site_no, start, end, readings):
    print(f"\nSite    : {site_no}")
    print(f"Queried : {start} → {end}")
    print(f"Rows    : {len(readings)}")

    if not readings:
        print("  NO DATA returned for this site/date range.")
        return

    flow_vals = [float(r["flow_cfs"]) for r in readings if r.get("flow_cfs") not in (None, "")]
    print(f"First   : {readings[0]['datetime']}")
    print(f"Last    : {readings[-1]['datetime']}")
    print(f"Flow    : {len(flow_vals)} values", end="")
    if flow_vals:
        print(f"  (min={min(flow_vals):.1f}  max={max(flow_vals):.1f}  avg={sum(flow_vals)/len(flow_vals):.1f} cfs)")
    else:
        print("  (no flow data)")


def main():
    parser = argparse.ArgumentParser(description="Pull USGS gauge data for a single site")
    parser.add_argument("site_no", help="USGS site number (e.g. 09033300)")
    parser.add_argument("--start", default=(date.today() - timedelta(days=90)).isoformat(),
                        help="Start date YYYY-MM-DD (default: 90 days ago)")
    parser.add_argument("--end", default=date.today().isoformat(),
                        help="End date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Fetching {args.site_no} from {args.start} to {args.end} ...")
    data = fetch_gauge(args.site_no, args.start, args.end)

    json_path = os.path.join(OUTPUT_DIR, f"gauge_{args.site_no}.json")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Raw GeoJSON saved to {json_path}")

    readings = parse_readings(data)

    csv_path = os.path.join(OUTPUT_DIR, f"gauge_{args.site_no}.csv")
    fieldnames = ["datetime", "flow_cfs", "water_temp_c", "gauge_height_ft"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in readings:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"CSV saved to {csv_path}")

    print_summary(args.site_no, args.start, args.end, readings)


if __name__ == "__main__":
    main()
