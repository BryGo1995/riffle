import sys
sys.path.insert(0, "pipeline")
from config.rivers import GAUGES


def test_gauges_count():
    assert len(GAUGES) == 23


def test_no_active_field():
    for g in GAUGES:
        assert "active" not in g, f"{g['usgs_gauge_id']} still has 'active' key"
