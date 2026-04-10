import sys
sys.path.insert(0, "pipeline")
from config.rivers import GAUGES, ACTIVE_GAUGES


def test_all_gauges_have_active_flag():
    for g in GAUGES:
        assert "active" in g, f"{g['usgs_gauge_id']} missing 'active' key"


def test_active_gauges_are_subset_of_gauges():
    gauge_ids = {g["usgs_gauge_id"] for g in GAUGES}
    for g in ACTIVE_GAUGES:
        assert g["usgs_gauge_id"] in gauge_ids


def test_active_gauges_only_contains_active():
    for g in ACTIVE_GAUGES:
        assert g["active"] is True


def test_active_gauges_match_audit():
    # After the 2026-04-10 audit: 5 stagnant gauges deactivated, 19 new gauges
    # added, 2 more (Eleven Mile Canyon, Ruedi to Basalt) deactivated in favor
    # of nearby alternatives. See notebooks/gauge_audit_map.ipynb section 5.
    assert len(ACTIVE_GAUGES) == 23
