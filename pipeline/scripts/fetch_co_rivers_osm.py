"""One-off script to fetch Colorado river geometries from OpenStreetMap
via the Overpass API and save as GeoJSON.

Saves results to:
  - output/rivers_co_osm.geojson           — all major rivers (default)
  - output/river_osm_<name>.geojson        — single river (when --river is used)

--------------------------------------------------------------------------------
SETUP
--------------------------------------------------------------------------------

  Install dependencies if not already installed:
    pip install requests

--------------------------------------------------------------------------------
RUNNING THE SCRIPT
--------------------------------------------------------------------------------

  Run from any directory. An output/ folder will be created wherever you are:

    # List all available river names
    python pipeline/scripts/fetch_co_rivers_osm.py --list-rivers

    # Fetch a specific river by name
    python pipeline/scripts/fetch_co_rivers_osm.py --river "South Platte River"
    python pipeline/scripts/fetch_co_rivers_osm.py --river "Gunnison River"
    python pipeline/scripts/fetch_co_rivers_osm.py --river "Blue River"

    # Fetch all major rivers at once
    python pipeline/scripts/fetch_co_rivers_osm.py

  Arguments:
    --list-rivers     Print all available river names and exit.
    --river NAME      Fetch a single river by name. Run --list-rivers to see
                      valid names. Names are case-sensitive.

  Note: River names come from OpenStreetMap and may differ slightly from USGS
  names (e.g. "Cache la Poudre River" vs "Poudre River"). Use --list-rivers
  to find the exact name to pass to --river.

--------------------------------------------------------------------------------
HOW TO LOAD INTO PANDAS / GEOPANDAS AFTER RUNNING
--------------------------------------------------------------------------------

  import geopandas as gpd
  import pandas as pd

  # Step 1: Load GeoJSON into a GeoDataFrame (a pandas DataFrame + geometry col)
  gdf = gpd.read_file("output/rivers_co_osm.geojson")
  print(gdf.columns)     # shows all attribute columns + 'geometry'
  print(gdf.head())

  # Step 2: Use it like a normal DataFrame — filter, groupby, etc.
  south_platte = gdf[gdf["name"] == "South Platte River"]

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

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUTPUT_DIR = "output"

# Colorado admin boundary relation ID in OpenStreetMap
CO_AREA_ID = 3600161961

# Curated list of major Colorado rivers as they appear in OpenStreetMap.
# Note: OSM names may differ slightly from USGS names.
# Run --list-rivers to see the full current list pulled from OSM.
COLORADO_RIVERS = [
    "Animas River",
    "Arkansas River",
    "Big Thompson River",
    "Blue River",
    "Boulder Creek",
    "Cache la Poudre River",
    "Cherry Creek",
    "Clear Creek",
    "Colorado River",
    "Crystal River",
    "Dolores River",
    "Eagle River",
    "Elk River",
    "Fountain Creek",
    "Fryingpan River",
    "Gore Creek",
    "Green River",
    "Gunnison River",
    "Illinois River",
    "Lake Fork",
    "Laramie River",
    "Little Snake River",
    "Los Pinos River",
    "Mancos River",
    "Michigan River",
    "North Fork South Platte River",
    "North Platte River",
    "Piedra River",
    "Purgatoire River",
    "Rio Grande",
    "Roaring Fork River",
    "San Juan River",
    "San Miguel River",
    "Slate River",
    "South Platte River",
    "Taylor River",
    "Tomichi Creek",
    "Uncompahgre River",
    "White River",
    "Yampa River",
]


def build_query(river_name=None):
    """Build an Overpass QL query for rivers within Colorado."""
    if river_name:
        name_filter = f'["name"="{river_name}"]'
    else:
        name_filter = '["name"]'

    return f"""
[out:json][timeout:120];
area({CO_AREA_ID})->.co;
(
  way["waterway"="river"]{name_filter}(area.co);
  relation["waterway"="river"]{name_filter}(area.co);
);
out geom;
"""


def fetch_overpass(query):
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=120)
    resp.raise_for_status()
    return resp.json()


def to_geojson(osm_data):
    """Convert Overpass JSON response to a GeoJSON FeatureCollection."""
    features = []

    for element in osm_data.get("elements", []):
        props = element.get("tags", {})
        geom = None

        if element["type"] == "way":
            coords = [[n["lon"], n["lat"]] for n in element.get("geometry", [])]
            if len(coords) >= 2:
                geom = {"type": "LineString", "coordinates": coords}

        elif element["type"] == "relation":
            lines = []
            for member in element.get("members", []):
                if member.get("type") == "way" and member.get("role") in ("", "main_stream", "side_stream"):
                    coords = [[n["lon"], n["lat"]] for n in member.get("geometry", [])]
                    if len(coords) >= 2:
                        lines.append(coords)
            if lines:
                geom = {"type": "MultiLineString", "coordinates": lines}

        if geom:
            features.append({"type": "Feature", "properties": props, "geometry": geom})

    return {"type": "FeatureCollection", "features": features}


def summarize(geojson):
    features = geojson.get("features", [])
    names = sorted({f["properties"].get("name", "") for f in features if f["properties"].get("name")})
    print(f"\nFetched {len(features)} segments across {len(names)} named rivers:\n")
    for name in names:
        segs = [f for f in features if f["properties"].get("name") == name]
        print(f"  {name}  ({len(segs)} segments)")


def main():
    parser = argparse.ArgumentParser(description="Fetch Colorado river geometries from OpenStreetMap")
    parser.add_argument("--list-rivers", action="store_true",
                        help="Print all available river names and exit")
    parser.add_argument("--river", type=str, default=None,
                        help="Fetch a single river by name (run --list-rivers to see options)")
    args = parser.parse_args()

    if args.list_rivers:
        print(f"{len(COLORADO_RIVERS)} rivers available:\n")
        for name in COLORADO_RIVERS:
            print(f"  {name}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if args.river:
        print(f"Fetching '{args.river}' from OpenStreetMap ...")
        query = build_query(args.river)
        filename = f"river_osm_{args.river.lower().replace(' ', '_')}.geojson"
    else:
        print("Fetching all major Colorado rivers from OpenStreetMap ...")
        query = build_query()
        filename = "rivers_co_osm.geojson"

    osm_data = fetch_overpass(query)
    geojson = to_geojson(osm_data)

    out_path = os.path.join(OUTPUT_DIR, filename)
    with open(out_path, "w") as f:
        json.dump(geojson, f, indent=2)

    summarize(geojson)
    print(f"\nGeoJSON saved to {out_path}")


if __name__ == "__main__":
    main()
