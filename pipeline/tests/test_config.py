import sys
sys.path.insert(0, "pipeline")
from config.rivers import GAUGES, get_season, get_thresholds


def test_gauges_count():
    assert len(GAUGES) == 22


def test_no_active_field():
    for g in GAUGES:
        assert "active" not in g, f"{g['usgs_gauge_id']} still has 'active' key"


def test_all_gauges_have_freezes_flag():
    for g in GAUGES:
        assert "freezes" in g, f"{g['usgs_gauge_id']} missing 'freezes' key"
        assert isinstance(g["freezes"], bool)


def test_flow_thresholds_are_seasonal():
    for g in GAUGES:
        thresholds = g["flow_thresholds"]
        # Every gauge must have at least runoff and baseflow
        assert "runoff" in thresholds, f"{g['name']} missing runoff thresholds"
        assert "baseflow" in thresholds, f"{g['name']} missing baseflow thresholds"
        for season, t in thresholds.items():
            assert {"blowout", "optimal_low", "optimal_high"} == set(t.keys()), \
                f"{g['name']} {season} has wrong keys"
            assert t["optimal_low"] < t["optimal_high"] < t["blowout"], \
                f"{g['name']} {season} thresholds not ordered: {t}"


def test_freezing_gauges_have_no_winter_thresholds():
    """Gauges that freeze shouldn't define winter thresholds — they auto-label Poor."""
    for g in GAUGES:
        if g["freezes"]:
            assert "winter" not in g["flow_thresholds"], \
                f"{g['name']} freezes but has winter thresholds"


def test_get_season():
    assert get_season(1) == "winter"
    assert get_season(2) == "winter"
    assert get_season(3) == "baseflow"
    assert get_season(4) == "runoff"
    assert get_season(7) == "runoff"
    assert get_season(8) == "baseflow"
    assert get_season(11) == "baseflow"
    assert get_season(12) == "winter"


def test_get_thresholds_returns_correct_season():
    # Pick a gauge with all three seasons
    gauge = next(g for g in GAUGES if "winter" in g["flow_thresholds"])
    assert get_thresholds(gauge, 1) == gauge["flow_thresholds"]["winter"]
    assert get_thresholds(gauge, 4) == gauge["flow_thresholds"]["runoff"]
    assert get_thresholds(gauge, 9) == gauge["flow_thresholds"]["baseflow"]


def test_get_thresholds_falls_back_to_baseflow():
    """Gauges without winter thresholds should fall back to baseflow in winter."""
    gauge = next(g for g in GAUGES if "winter" not in g["flow_thresholds"])
    assert get_thresholds(gauge, 1) == gauge["flow_thresholds"]["baseflow"]
