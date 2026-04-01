"""One-off script to fetch Colorado river geometries from the USGS
National Hydrography Dataset (NHD) API and save as GeoJSON.

Saves results to:
  - output/rivers_co.geojson        — all major rivers (default)
  - output/river_<name>.geojson     — single river (when --river is used)

NOTE: The API caps responses at 2000 segments per request. This is fine for
individual rivers but may truncate results when fetching all rivers at once.
If you need complete statewide coverage, use the local file version of this
script with a downloaded GeoPackage from:
  https://data.colorado.gov/Natural-Resources/National-Hydrography-Dataset-NHD-in-Colorado/5ccs-vx79/about_data

--------------------------------------------------------------------------------
SETUP
--------------------------------------------------------------------------------

  Install dependencies if not already installed:
    pip install requests

--------------------------------------------------------------------------------
RUNNING THE SCRIPT
--------------------------------------------------------------------------------

  Run from any directory. An output/ folder will be created wherever you are:

    # List all available river names (use these with --river)
    python pipeline/scripts/fetch_co_rivers.py --list-rivers

    # Fetch a specific river by name
    python pipeline/scripts/fetch_co_rivers.py --river "South Platte River"
    python pipeline/scripts/fetch_co_rivers.py --river "Gunnison River"
    python pipeline/scripts/fetch_co_rivers.py --river "Blue River"

    # Fetch all rivers at the default threshold (stream order >= 4)
    python pipeline/scripts/fetch_co_rivers.py

    # Adjust the threshold — applies to both --list-rivers and fetching
    python pipeline/scripts/fetch_co_rivers.py --min-order 5  # major rivers only
    python pipeline/scripts/fetch_co_rivers.py --min-order 6  # largest mainstems only

  Arguments:
    --list-rivers     Print all river names at the current threshold and exit.
                      Use these names as the value for --river.
    --river NAME      Fetch a single river by exact name (e.g. "Gunnison River").
                      Run --list-rivers first to see valid names.
    --min-order INT   Minimum Strahler stream order. Applies to both --list-rivers
                      and fetching all rivers (default: 4).
                        4 = named rivers and larger creeks (recommended)
                        5 = major rivers only
                        6 = largest mainstems only

--------------------------------------------------------------------------------
HOW TO LOAD INTO PANDAS / GEOPANDAS AFTER RUNNING
--------------------------------------------------------------------------------

  import geopandas as gpd
  import pandas as pd

  # Step 1: Load GeoJSON into a GeoDataFrame (a pandas DataFrame + geometry col)
  gdf = gpd.read_file("output/rivers_co.geojson")
  print(gdf.columns)     # shows all attribute columns + 'geometry'
  print(gdf.head())

  # Step 2: Use it like a normal DataFrame — filter, groupby, etc.
  south_platte = gdf[gdf["gnis_name"] == "South Platte River"]

  # Step 3a: Drop geometry to get a plain pandas DataFrame
  df = pd.DataFrame(gdf.drop(columns="geometry"))

  # Step 3b: Or keep geometry as WKT strings in a plain DataFrame
  df = pd.DataFrame(gdf)
  df["geometry"] = gdf.geometry.to_wkt()

  # Step 4: Extract all lat/lon coordinate pairs from a river's geometry
  #   (useful for plotting or analysis)
  for geom in south_platte.geometry:
      if geom.geom_type == "MultiLineString":
          for line in geom.geoms:
              coords = list(line.coords)  # list of (lon, lat) tuples
      elif geom.geom_type == "LineString":
          coords = list(geom.coords)

--------------------------------------------------------------------------------
"""

import argparse
import json
import os

import requests

CO_BBOX = "-109.06,36.99,-102.04,41.00"
NHD_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3/query"
DEFAULT_STREAM_ORDER_MIN = 4
OUTPUT_DIR = "output"


def list_river_names(min_order):
    """Return curated Colorado river names at or above the given stream order."""
    return sorted(name for name, order in COLORADO_RIVERS.items() if order >= min_order)


# Curated list of major Colorado rivers (stream order 4+).
# Add or remove names here as needed. Use these exact names with --river.
# Stream order is approximate — higher = larger/more significant river.
COLORADO_RIVERS = {
    # Order 9
    "Arkansas River": 9,
    "Colorado River": 9,
    # Order 8
    "Gunnison River": 8,
    "Huerfano River": 8,
    "Rio Grande": 8,
    "South Platte River": 8,
    # Order 7
    "Cache la Poudre River": 7,
    "Dolores River": 7,
    "Green River": 7,
    "Purgatoire River": 7,
    "San Juan River": 7,
    "White River": 7,
    "Yampa River": 7,
    # Order 6
    "Animas River": 6,
    "Eagle River": 6,
    "Elk River": 6,
    "Fountain Creek": 6,
    "North Platte River": 6,
    "Piedra River": 6,
    "Roaring Fork River": 6,
    "San Miguel River": 6,
    "Uncompahgre River": 6,
    # Order 5
    "Blue River": 5,
    "Crystal River": 5,
    "Fryingpan River": 5,
    "Laramie River": 5,
    "Los Pinos River": 5,
    "Mancos River": 5,
    "Michigan River": 5,
    "North Fork South Platte River": 5,
    "Taylor River": 5,
    "Tomichi Creek": 5,
    # Order 4
    "Big Thompson River": 4,
    "Boulder Creek": 4,
    "Cherry Creek": 4,
    "Clear Creek": 4,
    "Cochetopa Creek": 4,
    "Cucharas River": 4,
    "Gore Creek": 4,
    "Illinois River": 4,
    "Lake Fork Gunnison River": 4,
    "Little Snake River": 4,
    "North Fork Gunnison River": 4,
    "Piceance Creek": 4,
    "Saint Vrain Creek": 4,
    "Slate River": 4,
    "South Fork Rio Grande": 4,
    "Spring Creek": 4,
    "Troublesome Creek": 4,
}


def fetch_by_name(name):
    """Fetch all flowline segments for a single named river."""
    params = {
        "where": f"gnis_name = '{name}'",
        "geometry": CO_BBOX,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outFields": "gnis_name,streamorde,lengthkm,reachcode",
        "returnGeometry": "true",
        "f": "geojson",
        "resultRecordCount": 2000,
    }
    resp = requests.get(NHD_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_all(min_order):
    """Fetch all named flowlines above a stream order threshold."""
    params = {
        "where": f"streamorde >= {min_order} AND gnis_name <> ''",
        "geometry": CO_BBOX,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outFields": "gnis_name,streamorde,lengthkm,reachcode",
        "returnGeometry": "true",
        "f": "geojson",
        "resultRecordCount": 2000,
    }
    resp = requests.get(NHD_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def summarize(geojson):
    features = geojson.get("features", [])
    names = sorted({f["properties"].get("gnis_name", "") for f in features if f["properties"].get("gnis_name")})
    print(f"\nFetched {len(features)} flowline segments across {len(names)} named rivers:\n")
    for name in names:
        segs = [f for f in features if f["properties"].get("gnis_name") == name]
        print(f"  {name}  ({len(segs)} segments)")


def main():
    parser = argparse.ArgumentParser(description="Fetch Colorado river geometries from NHD API")
    parser.add_argument("--list-rivers", action="store_true",
                        help="Print all available river names and exit")
    parser.add_argument("--river", type=str, default=None,
                        help="Fetch a single river by exact name (run --list-rivers to see options)")
    parser.add_argument("--min-order", type=int, default=DEFAULT_STREAM_ORDER_MIN,
                        help=f"Minimum stream order for both listing and fetching (default: {DEFAULT_STREAM_ORDER_MIN}). "
                             "Filters out canals, ditches, and small tributaries. "
                             "4 = named rivers and larger creeks, 5 = major rivers only, 6 = largest mainstems only.")
    args = parser.parse_args()

    if args.list_rivers:
        print(f"Fetching river names in Colorado (stream order >= {args.min_order}) ...")
        names = list_river_names(args.min_order)
        print(f"\n{len(names)} rivers found:\n")
        for name in names:
            print(f"  {name}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if args.river:
        print(f"Fetching '{args.river}' ...")
        geojson = fetch_by_name(args.river)
        filename = f"river_{args.river.lower().replace(' ', '_')}.geojson"
    else:
        print(f"Fetching all rivers with stream order >= {args.min_order} ...")
        geojson = fetch_all(args.min_order)
        filename = "rivers_co.geojson"

    out_path = os.path.join(OUTPUT_DIR, filename)
    with open(out_path, "w") as f:
        json.dump(geojson, f, indent=2)

    summarize(geojson)
    print(f"\nGeoJSON saved to {out_path}")


if __name__ == "__main__":
    main()
