"""One-off script to fetch all active USGS flow gauges in Colorado.

Uses the new USGS Water Data API (api.waterdata.usgs.gov).

Strategy:
  1. Query time-series-metadata for all CO sites measuring discharge (00060).
     De-duplicate on monitoring_location_id. Filter to active gauges by
     checking that end_utc is within the last 90 days.
  2. Fetch full site metadata from monitoring-locations for each site.

Saves results to:
  - output/gauges_co.csv — site_no, name, lat, lon, drainage_area, huc, agency

Usage:
  Run from any directory — output/ will be created wherever you are:
    python pipeline/scripts/explore_gauges.py

  Open output/gauges_co.csv in a spreadsheet to browse all active flow gauges
  and find site IDs of interest. Pass those IDs to sample_gauge_data.py
  to pull the actual readings.
"""

import csv
import os
from datetime import datetime, timedelta, timezone

import requests

OUTPUT_DIR = "output"

API_BASE = "https://api.waterdata.usgs.gov/ogcapi/v0"
TS_URL = f"{API_BASE}/collections/time-series-metadata/items"
SITES_URL = f"{API_BASE}/collections/monitoring-locations/items"

DISCHARGE_PARAM = "00060"
ACTIVE_THRESHOLD_DAYS = 90

API_KEY = os.environ.get("USGS_API_KEY")


def fetch_discharge_site_ids():
    """Return a set of monitoring_location_ids that have active discharge data in CO.

    Paginates through time-series-metadata using cursor links.
    Filters to series whose end_utc is within the last ACTIVE_THRESHOLD_DAYS days.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=ACTIVE_THRESHOLD_DAYS)
    active_ids = set()

    url = TS_URL
    params = {
        "parameter_code": DISCHARGE_PARAM,
        "state_name": "Colorado",
        "limit": 1000,
        "f": "json",
        "api_key": API_KEY,
    }

    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for feat in data.get("features", []):
            props = feat.get("properties", {})
            end_utc = props.get("end_utc")
            if end_utc:
                try:
                    end_dt = datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
                    if end_dt >= cutoff:
                        active_ids.add(props["monitoring_location_id"])
                except ValueError:
                    pass

        # Cursor-based pagination — follow next link if present
        next_url = next(
            (lnk["href"] for lnk in data.get("links", []) if lnk.get("rel") == "next"),
            None,
        )
        url = next_url
        params = {}  # params are encoded in the cursor URL

    return active_ids


def fetch_site_metadata(site_ids):
    """Fetch monitoring-location metadata for a collection of site IDs.

    Returns a list of dicts with site_no, name, lat, lon, drainage_area, huc, agency.
    """
    sites = []
    for loc_id in site_ids:
        # loc_id is e.g. "USGS-09085000"
        resp = requests.get(f"{SITES_URL}/{loc_id}", params={"f": "json", "api_key": API_KEY}, timeout=30)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        feat = resp.json()
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [None, None])
        sites.append({
            "agency": props.get("agency_code", "USGS"),
            "site_no": props.get("monitoring_location_number", ""),
            "name": props.get("monitoring_location_name", ""),
            "lat": coords[1] if len(coords) > 1 else "",
            "lon": coords[0] if len(coords) > 0 else "",
            "drainage_area": props.get("drainage_area", ""),
            "huc": props.get("hydrologic_unit_code", ""),
        })
    return sites


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Fetching CO sites with active discharge data (last {ACTIVE_THRESHOLD_DAYS} days) ...")
    site_ids = fetch_discharge_site_ids()
    print(f"Found {len(site_ids)} active discharge sites. Fetching metadata ...")

    sites = fetch_site_metadata(site_ids)
    sites.sort(key=lambda s: s["site_no"])

    csv_path = os.path.join(OUTPUT_DIR, "gauges_co.csv")
    fieldnames = ["site_no", "name", "lat", "lon", "drainage_area", "huc", "agency"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for site in sites:
            writer.writerow(site)
            print(f"  {site['site_no']}  {str(site['lat']):>10}  {str(site['lon']):>11}  {site['name']}")

    print(f"\nCSV saved to {csv_path}")


if __name__ == "__main__":
    main()
