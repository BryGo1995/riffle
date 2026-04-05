"""Audit USGS monitoring locations for a given state.

Fetches all stream-type monitoring locations, then queries the latest-continuous
endpoint to assess data availability for key fly-fishing parameters.

Outputs both CSV and GeoJSON for use in Jupyter / Folium.

Usage:
    python pipeline/scripts/audit_gauges.py                        # Colorado streams
    python pipeline/scripts/audit_gauges.py --state 08             # same (FIPS code)
    python pipeline/scripts/audit_gauges.py --state 08 --all-types # include reservoirs etc.
    python pipeline/scripts/audit_gauges.py --out /tmp/gauges      # custom output path prefix
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

API_KEY = os.environ.get("USGS_API_KEY", "")
BASE = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"

PARAMS = {
    "00060": "discharge",
    "00065": "gage_height",
    "00010": "water_temp",
    "00045": "precipitation",
}

# Parameters that count toward the 0-3 "active" rating.
# Precipitation (00045) is excluded — it's supplemental context only.
RATING_PARAMS = {"00060", "00065", "00010"}

ACTIVE_THRESHOLD_HOURS = 48


def api_get(url: str, retries: int = 3) -> dict:
    req = urllib.request.Request(url, headers={"X-Api-Key": API_KEY})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60 * (2 ** attempt)
                print(f"  429 — waiting {wait}s", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Failed after {retries} retries: {url}")


def fetch_monitoring_locations(state_code: str, stream_only: bool) -> list[dict]:
    """Return all monitoring locations for the given state."""
    locations = []
    offset = 0
    limit = 500
    filters = f"state_code={state_code}&limit={limit}"
    if stream_only:
        filters += "&site_type_code=ST"

    print(f"Fetching monitoring locations (state={state_code}, stream_only={stream_only})...")
    while True:
        url = f"{BASE}/monitoring-locations/items?{filters}&offset={offset}&f=json"
        data = api_get(url)
        features = data.get("features", [])
        for f in features:
            p = f.get("properties", {})
            coords = f.get("geometry", {}).get("coordinates", [None, None])
            locations.append({
                "gauge_id": p.get("monitoring_location_number"),
                "name": p.get("monitoring_location_name"),
                "site_type": p.get("site_type_code"),
                "huc_code": p.get("hydrologic_unit_code"),
                "lon": coords[0],
                "lat": coords[1],
                "state_code": p.get("state_fips_code"),
                "county": p.get("county_name"),
                "altitude_ft": p.get("altitude"),
                "drainage_area_sqmi": p.get("drainage_area"),
                "contrib_drainage_area_sqmi": p.get("contributing_drainage_area"),
            })
        returned = data.get("numberReturned", 0)
        print(f"  fetched {offset + returned} locations so far", flush=True)
        if returned < limit:
            break
        offset += limit
        time.sleep(0.5)

    return locations


def fetch_all_latest_by_param(param_code: str, co_gauge_ids: set[str]) -> dict[str, dict]:
    """Fetch latest readings for one parameter nationwide, return only CO gauges.

    Returns {gauge_id: {value, unit, time}} for gauges in co_gauge_ids.
    Uses bulk parameter query (1 paginated fetch) instead of per-gauge requests.
    """
    results = {}
    url = f"{BASE}/latest-continuous/items?parameter_code={param_code}&f=json&limit=5000"
    page = 1
    while url:
        print(f"  {param_code} page {page}...", end=" ", flush=True)
        data = api_get(url)
        count = 0
        for f in data.get("features", []):
            p = f.get("properties", {})
            loc_id = p.get("monitoring_location_id", "")
            gid = loc_id.replace("USGS-", "")
            if gid in co_gauge_ids and gid not in results:
                results[gid] = {
                    "value": p.get("value"),
                    "unit": p.get("unit_of_measure"),
                    "time": p.get("time"),
                }
                count += 1
        print(f"matched {count}", flush=True)
        next_link = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
        url = next_link
        page += 1
        time.sleep(1.0)
    return results


def fmt_ts(time_str: str | None) -> str | None:
    """Reformat ISO 8601 timestamp to 'YYYY-MM-DD HH:MM UTC'.

    geopandas auto-parses ISO strings (e.g. '2024-01-15T14:30:00Z') to
    Timestamp objects when loading GeoJSON, which Folium cannot re-serialize.
    This format is human-readable but won't be auto-parsed by pandas/geopandas.
    """
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return time_str


def hours_since(time_str: str | None, now: datetime) -> float | None:
    if not time_str:
        return None
    try:
        dt = datetime.fromisoformat(time_str)
        return (now - dt).total_seconds() / 3600
    except Exception:
        return None


def build_row(loc: dict, readings: dict, now: datetime) -> dict:
    row = {
        "gauge_id": loc["gauge_id"],
        "name": loc["name"],
        "site_type": loc["site_type"],
        "huc_code": loc["huc_code"],
        "county": loc["county"],
        "lat": loc["lat"],
        "lon": loc["lon"],
        "altitude_ft": loc["altitude_ft"],
        "drainage_area_sqmi": loc["drainage_area_sqmi"],
        "contrib_drainage_area_sqmi": loc["contrib_drainage_area_sqmi"],
    }

    # Per-parameter columns
    rating = 0
    rating_4 = 0
    last_reading_times = []
    for code, label in PARAMS.items():
        r = readings.get(code, {})
        value = r.get("value")
        t = r.get("time")
        hrs = hours_since(t, now)

        row[f"{label}_value"] = value
        row[f"{label}_unit"] = r.get("unit")
        row[f"{label}_last_at"] = fmt_ts(t)
        row[f"{label}_hours_ago"] = round(hrs, 1) if hrs is not None else None
        row[f"{label}_active"] = (hrs is not None and 0 <= hrs < ACTIVE_THRESHOLD_HOURS)

        if row[f"{label}_active"]:
            rating_4 += 1
        if code in RATING_PARAMS and row[f"{label}_active"]:
            rating += 1
        if t:
            last_reading_times.append(t)

    row["reading_rating"] = rating    # 0-3: discharge + gage_height + water_temp (ML feature set)
    row["reading_rating_4"] = rating_4  # 0-4: all parameters including precipitation (audit use)
    row["last_any_reading_at"] = fmt_ts(max(last_reading_times)) if last_reading_times else None
    row["parameter_count"] = len(readings)

    return row


def rows_to_geojson(rows: list[dict]) -> dict:
    features = []
    for row in rows:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        props = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": features}


def rows_to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    lines = [",".join(str(h) for h in headers)]
    for row in rows:
        cells = []
        for h in headers:
            v = row.get(h, "")
            if v is None:
                v = ""
            s = str(v).replace('"', '""')
            if "," in s or '"' in s or "\n" in s:
                s = f'"{s}"'
            cells.append(s)
        lines.append(",".join(cells))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit USGS gauge data availability")
    parser.add_argument("--state", default="08", help="State FIPS code (default: 08 = Colorado)")
    parser.add_argument("--all-types", action="store_true", help="Include all site types (default: streams only)")
    parser.add_argument("--out", default=None, help="Output file path prefix (no extension); defaults to gauge_audit_logs/gauge_audit_YYYYMMDD_HHMMSS")
    parser.add_argument("--max", type=int, default=0, help="Limit to first N gauges (0 = all, for testing)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: USGS_API_KEY environment variable not set")
        sys.exit(1)

    now = datetime.now(timezone.utc)

    if args.out is None:
        log_dir = "gauge_audit_logs"
        os.makedirs(log_dir, exist_ok=True)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        args.out = os.path.join(log_dir, f"gauge_audit_{timestamp}")

    locations = fetch_monitoring_locations(args.state, stream_only=not args.all_types)
    if args.max:
        locations = locations[:args.max]

    co_gauge_ids = {loc["gauge_id"] for loc in locations if loc["gauge_id"]}

    print(f"\nFetching latest readings for {len(co_gauge_ids)} gauges via bulk parameter queries...")
    param_data: dict[str, dict[str, dict]] = {}
    for code in PARAMS:
        print(f"  Parameter {code} ({PARAMS[code]}):")
        param_data[code] = fetch_all_latest_by_param(code, co_gauge_ids)
        print(f"    → {len(param_data[code])} gauges have {PARAMS[code]} data")

    print("\nBuilding rows...")
    rows = []
    for loc in locations:
        gid = loc["gauge_id"]
        if not gid:
            continue
        readings = {code: param_data[code][gid] for code in PARAMS if gid in param_data[code]}
        rows.append(build_row(loc, readings, now))

    # Write CSV
    csv_path = f"{args.out}.csv"
    with open(csv_path, "w") as f:
        f.write(rows_to_csv(rows))
    print(f"\nCSV written: {csv_path} ({len(rows)} rows)")

    # Write GeoJSON
    geojson_path = f"{args.out}.geojson"
    with open(geojson_path, "w") as f:
        json.dump(rows_to_geojson(rows), f, indent=2)
    print(f"GeoJSON written: {geojson_path}")

    # Quick summary (reading_rating_4 = all 4 params including precipitation)
    active_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    for row in rows:
        active_counts[row["reading_rating_4"]] += 1
    print(f"\nRating summary (out of 4 params):")
    for score, count in sorted(active_counts.items(), reverse=True):
        print(f"  {score}/4 — {count} gauges")


if __name__ == "__main__":
    main()
