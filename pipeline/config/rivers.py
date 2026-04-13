"""
Gauge registry for Riffle.

flow_thresholds are seasonal, computed from 2-year historical percentiles:
  optimal_low  — P25 (25th percentile) for the season
  optimal_high — P75 (75th percentile) for the season
  blowout      — P95 (95th percentile) for the season

Seasons:
  runoff   — Apr–Jul (snowmelt-driven high water)
  baseflow — Mar, Aug–Nov (stable flows, primary fishing season)
  winter   — Dec–Feb (ice risk at elevation)

freezes: whether the gauge is at a location that typically ices over
in winter. Frozen gauges are auto-labeled "Poor" in Dec–Feb regardless
of flow readings, which can be unreliable under ice.

See docs/flow-threshold-methodology.md for the full methodology.
"""

GAUGES = [
    {
        "usgs_gauge_id": "07091200",
        "name": "Salida",
        "river": "Arkansas River",
        "lat": 38.5347,
        "lon": -106.0008,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 3055, "optimal_low": 406, "optimal_high": 1295},
            "baseflow": {"blowout": 724,  "optimal_low": 306, "optimal_high": 604},
        },
    },
    {
        "usgs_gauge_id": "09085000",
        "name": "Glenwood Springs",
        "river": "Roaring Fork River",
        "lat": 39.5486,
        "lon": -107.3247,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 4938, "optimal_low": 776, "optimal_high": 1878},
            "baseflow": {"blowout": 854,  "optimal_low": 446, "optimal_high": 628},
            "winter":   {"blowout": 482,  "optimal_low": 353, "optimal_high": 439},
        },
    },
    {
        "usgs_gauge_id": "09057500",
        "name": "Silverthorne",
        "river": "Blue River",
        "lat": 39.6328,
        "lon": -106.0694,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 1560, "optimal_low": 105, "optimal_high": 687},
            "baseflow": {"blowout": 939,  "optimal_low": 196, "optimal_high": 668},
            "winter":   {"blowout": 215,  "optimal_low": 137, "optimal_high": 187},
        },
    },
    {
        "usgs_gauge_id": "09070000",
        "name": "Glenwood Springs",
        "river": "Colorado River",
        "lat": 39.5500,
        "lon": -107.3242,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 2855, "optimal_low": 448, "optimal_high": 1390},
            "baseflow": {"blowout": 361,  "optimal_low": 159, "optimal_high": 213},
            "winter":   {"blowout": 196,  "optimal_low": 138, "optimal_high": 176},
        },
    },
    {
        "usgs_gauge_id": "06700000",
        "name": "Above Cheesman Lake",
        "river": "South Platte",
        "lat": 39.1628,
        "lon": -105.3097,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 680, "optimal_low": 123, "optimal_high": 255},
            "baseflow": {"blowout": 272, "optimal_low": 142, "optimal_high": 195},
        },
    },
    {
        "usgs_gauge_id": "06701900",
        "name": "Trumbull (Brush Creek)",
        "river": "South Platte",
        "lat": 39.2600,
        "lon": -105.2219,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 779, "optimal_low": 133, "optimal_high": 417},
            "baseflow": {"blowout": 364, "optimal_low": 146, "optimal_high": 256},
            "winter":   {"blowout": 211, "optimal_low": 132, "optimal_high": 175},
        },
    },
    {
        "usgs_gauge_id": "06716500",
        "name": "Lawson",
        "river": "Clear Creek",
        "lat": 39.7658,
        "lon": -105.6261,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 712, "optimal_low": 65, "optimal_high": 410},
            "baseflow": {"blowout": 94,  "optimal_low": 28, "optimal_high": 56},
        },
    },
    {
        "usgs_gauge_id": "09034250",
        "name": "Windy Gap",
        "river": "Colorado River",
        "lat": 40.1083,
        "lon": -106.0042,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 2215, "optimal_low": 173, "optimal_high": 836},
            "baseflow": {"blowout": 175,  "optimal_low": 95,  "optimal_high": 150},
            "winter":   {"blowout": 97,   "optimal_low": 75,  "optimal_high": 87},
        },
    },
    {
        "usgs_gauge_id": "09046600",
        "name": "Dillon",
        "river": "Blue River",
        "lat": 39.5667,
        "lon": -106.0495,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 444, "optimal_low": 106, "optimal_high": 217},
            "baseflow": {"blowout": 97,  "optimal_low": 39,  "optimal_high": 69},
            "winter":   {"blowout": 35,  "optimal_low": 26,  "optimal_high": 32},
        },
    },
    {
        "usgs_gauge_id": "09058000",
        "name": "Kremmling",
        "river": "Colorado River",
        "lat": 40.0367,
        "lon": -106.4400,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 4190, "optimal_low": 765, "optimal_high": 1920},
            "baseflow": {"blowout": 1250, "optimal_low": 510, "optimal_high": 1050},
            "winter":   {"blowout": 479,  "optimal_low": 389, "optimal_high": 431},
        },
    },
    {
        "usgs_gauge_id": "09073300",
        "name": "Above Difficult Creek",
        "river": "Roaring Fork River",
        "lat": 39.1411,
        "lon": -106.7736,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 260, "optimal_low": 41, "optimal_high": 144},
            "baseflow": {"blowout": 42,  "optimal_low": 11, "optimal_high": 32},
        },
    },
    {
        "usgs_gauge_id": "09107000",
        "name": "Taylor Park",
        "river": "Taylor River",
        "lat": 38.8603,
        "lon": -106.5667,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 560, "optimal_low": 92, "optimal_high": 224},
            "baseflow": {"blowout": 92,  "optimal_low": 41, "optimal_high": 59},
        },
    },
    {
        "usgs_gauge_id": "09109000",
        "name": "Below Taylor Park Reservoir",
        "river": "Taylor River",
        "lat": 38.8183,
        "lon": -106.6092,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 609, "optimal_low": 103, "optimal_high": 378},
            "baseflow": {"blowout": 310, "optimal_low": 81,  "optimal_high": 273},
            "winter":   {"blowout": 97,  "optimal_low": 79,  "optimal_high": 87},
        },
    },
    {
        "usgs_gauge_id": "06719505",
        "name": "Golden",
        "river": "Clear Creek",
        "lat": 39.7530,
        "lon": -105.2353,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 831, "optimal_low": 128, "optimal_high": 458},
            "baseflow": {"blowout": 126, "optimal_low": 46,  "optimal_high": 89},
        },
    },
    {
        "usgs_gauge_id": "09081000",
        "name": "Emma",
        "river": "Roaring Fork River",
        "lat": 39.3733,
        "lon": -107.0839,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 2878, "optimal_low": 469, "optimal_high": 1028},
            "baseflow": {"blowout": 640,  "optimal_low": 297, "optimal_high": 420},
            "winter":   {"blowout": 322,  "optimal_low": 212, "optimal_high": 303},
        },
    },
    {
        "usgs_gauge_id": "383103106594200",
        "name": "Below Gunnison",
        "river": "Gunnison River",
        "lat": 38.5173,
        "lon": -106.9955,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 3153, "optimal_low": 644, "optimal_high": 1485},
            "baseflow": {"blowout": 868,  "optimal_low": 371, "optimal_high": 580},
            "winter":   {"blowout": 364,  "optimal_low": 321, "optimal_high": 348},
        },
    },
    {
        "usgs_gauge_id": "07087050",
        "name": "Granite",
        "river": "Arkansas River",
        "lat": 38.9769,
        "lon": -106.2140,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 2528, "optimal_low": 315, "optimal_high": 1020},
            "baseflow": {"blowout": 584,  "optimal_low": 199, "optimal_high": 440},
        },
    },
    {
        "usgs_gauge_id": "09136100",
        "name": "Lazear",
        "river": "North Fork Gunnison",
        "lat": 38.7852,
        "lon": -107.8334,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 1593, "optimal_low": 166, "optimal_high": 816},
            "baseflow": {"blowout": 268,  "optimal_low": 100, "optimal_high": 161},
            "winter":   {"blowout": 162,  "optimal_low": 97,  "optimal_high": 125},
        },
    },
    {
        "usgs_gauge_id": "09152500",
        "name": "Grand Junction",
        "river": "Gunnison River",
        "lat": 38.9833,
        "lon": -108.4506,
        "freezes": False,
        "flow_thresholds": {
            "runoff":   {"blowout": 7833, "optimal_low": 1320, "optimal_high": 2425},
            "baseflow": {"blowout": 1845, "optimal_low": 1133, "optimal_high": 1550},
            "winter":   {"blowout": 1130, "optimal_low": 826,  "optimal_high": 1100},
        },
    },
    {
        "usgs_gauge_id": "09359020",
        "name": "Below Silverton",
        "river": "Animas River",
        "lat": 37.7883,
        "lon": -107.6682,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 1160, "optimal_low": 184, "optimal_high": 644},
            "baseflow": {"blowout": 277,  "optimal_low": 92,  "optimal_high": 138},
        },
    },
    {
        "usgs_gauge_id": "09240020",
        "name": "Steamboat Springs",
        "river": "Yampa River",
        "lat": 40.4892,
        "lon": -106.8415,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 2985, "optimal_low": 212, "optimal_high": 1740},
            "baseflow": {"blowout": 155,  "optimal_low": 95,  "optimal_high": 133},
        },
    },
    {
        "usgs_gauge_id": "09251000",
        "name": "Maybell",
        "river": "Yampa River",
        "lat": 40.5027,
        "lon": -108.0334,
        "freezes": True,
        "flow_thresholds": {
            "runoff":   {"blowout": 8148, "optimal_low": 874, "optimal_high": 4240},
            "baseflow": {"blowout": 586,  "optimal_low": 135, "optimal_high": 280},
        },
    },
]


def get_season(month: int) -> str:
    """Return the season key for a given month (1-12)."""
    if month in (12, 1, 2):
        return "winter"
    if month in (4, 5, 6, 7):
        return "runoff"
    return "baseflow"


def get_thresholds(gauge: dict, month: int) -> dict:
    """Return the flow_thresholds dict for a gauge in a given month.

    Falls back to baseflow thresholds if the gauge has no winter entry
    (freezing gauges skip winter thresholds entirely).
    """
    season = get_season(month)
    thresholds = gauge["flow_thresholds"]
    if season in thresholds:
        return thresholds[season]
    return thresholds["baseflow"]
