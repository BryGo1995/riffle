import sys
sys.path.insert(0, "pipeline")
from config.rivers import GAUGES


def test_gauges_count():
    assert len(GAUGES) == 11

def test_gauge_has_required_fields():
    required = {"usgs_gauge_id", "name", "river", "lat", "lon", "flow_thresholds"}
    for g in GAUGES:
        assert required.issubset(g.keys()), f"Missing fields in gauge: {g}"

def test_flow_thresholds_have_required_keys():
    required = {"blowout", "optimal_low", "optimal_high"}
    for g in GAUGES:
        assert required.issubset(g["flow_thresholds"].keys()), f"Bad thresholds: {g['name']}"

def test_gauge_ids_are_unique():
    ids = [g["usgs_gauge_id"] for g in GAUGES]
    assert len(ids) == len(set(ids))

def test_coordinates_are_colorado():
    # Colorado bounding box: lat 37-41, lon -109 to -102
    for g in GAUGES:
        assert 37 <= g["lat"] <= 41, f"Bad lat for {g['name']}"
        assert -109 <= g["lon"] <= -102, f"Bad lon for {g['name']}"
