"""
Gauge registry for Riffle.

flow_thresholds (cfs):
  blowout     — flow above this is unfishable
  optimal_low — lower bound of ideal fishing range
  optimal_high — upper bound of ideal fishing range

Seasonal medians are computed dynamically from historical data.
Thresholds here are river-specific blowout/optimal bounds used for
bootstrapped label generation.
"""

GAUGES = [
    {
        "usgs_gauge_id": "09035800",
        "name": "Spinney Reservoir",
        "river": "South Platte",
        "lat": 38.9097,
        "lon": -105.5666,
        "flow_thresholds": {"blowout": 500, "optimal_low": 80, "optimal_high": 250},
        "active": True,
    },
    {
        "usgs_gauge_id": "09036000",
        "name": "Eleven Mile Canyon",
        "river": "South Platte",
        "lat": 38.9419,
        "lon": -105.4958,
        "flow_thresholds": {"blowout": 600, "optimal_low": 100, "optimal_high": 350},
        "active": True,
    },
    {
        "usgs_gauge_id": "09033300",
        "name": "Deckers",
        "river": "South Platte",
        "lat": 39.2525,
        "lon": -105.2192,
        "flow_thresholds": {"blowout": 800, "optimal_low": 150, "optimal_high": 400},
        "active": True,
    },
    {
        "usgs_gauge_id": "09034500",
        "name": "Cheesman Canyon",
        "river": "South Platte",
        "lat": 39.1886,
        "lon": -105.2511,
        "flow_thresholds": {"blowout": 700, "optimal_low": 100, "optimal_high": 350},
        "active": True,
    },
    {
        "usgs_gauge_id": "07091200",
        "name": "Salida",
        "river": "Arkansas River",
        "lat": 38.5347,
        "lon": -106.0008,
        "flow_thresholds": {"blowout": 2000, "optimal_low": 200, "optimal_high": 700},
        "active": True,
    },
    {
        "usgs_gauge_id": "07096000",
        "name": "Cañon City",
        "river": "Arkansas River",
        "lat": 38.4406,
        "lon": -105.2372,
        "flow_thresholds": {"blowout": 3000, "optimal_low": 300, "optimal_high": 1000},
        "active": True,
    },
    {
        "usgs_gauge_id": "09081600",
        "name": "Ruedi to Basalt",
        "river": "Fryingpan River",
        "lat": 39.3672,
        "lon": -106.9281,
        "flow_thresholds": {"blowout": 400, "optimal_low": 60, "optimal_high": 200},
        "active": True,
    },
    {
        "usgs_gauge_id": "09085000",
        "name": "Glenwood Springs",
        "river": "Roaring Fork River",
        "lat": 39.5486,
        "lon": -107.3247,
        "flow_thresholds": {"blowout": 3000, "optimal_low": 200, "optimal_high": 800},
        "active": True,
    },
    {
        "usgs_gauge_id": "09057500",
        "name": "Silverthorne",
        "river": "Blue River",
        "lat": 39.6328,
        "lon": -106.0694,
        "flow_thresholds": {"blowout": 500, "optimal_low": 50, "optimal_high": 200},
        "active": True,
    },
    {
        "usgs_gauge_id": "06752000",
        "name": "Canyon Mouth",
        "river": "Cache la Poudre",
        "lat": 40.6883,
        "lon": -105.1561,
        "flow_thresholds": {"blowout": 2000, "optimal_low": 150, "optimal_high": 600},
        "active": True,
    },
    {
        "usgs_gauge_id": "09070000",
        "name": "Glenwood Springs",
        "river": "Colorado River",
        "lat": 39.5500,
        "lon": -107.3242,
        "flow_thresholds": {"blowout": 8000, "optimal_low": 500, "optimal_high": 2500},
        "active": True,
    },
]

# Gauges participating in the full ingest → ML pipeline.
# Set active=False for gauges with no USGS flow data — they still
# receive weather ingestion and weather-only rule-based scoring.
ACTIVE_GAUGES = [g for g in GAUGES if g.get("active", True)]
