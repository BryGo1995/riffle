"""Seed the gauges table from the registry.

Run once after `docker-compose up`:
  python pipeline/scripts/seed_db.py
"""

import sys, os, json
sys.path.insert(0, "pipeline")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost:5434/riffle")

from sqlalchemy import create_engine, text
from config.rivers import GAUGES

engine = create_engine(os.environ["DATABASE_URL"])

with engine.begin() as conn:
    for g in GAUGES:
        conn.execute(
            text("""
                INSERT INTO gauges (usgs_gauge_id, name, river, lat, lon, flow_thresholds)
                VALUES (:usgs_gauge_id, :name, :river, :lat, :lon, CAST(:thresholds AS jsonb))
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
