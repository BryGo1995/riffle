# api/tests/test_routes.py
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://riffle:riffle@localhost/riffle")

from datetime import date
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

MOCK_GAUGE = {
    "id": 5, "usgs_gauge_id": "07091200", "name": "Salida",
    "river": "Arkansas River", "lat": 38.5347, "lon": -106.0008,
}

MOCK_GAUGE_2 = {
    "id": 9, "usgs_gauge_id": "09057500", "name": "Silverthorne",
    "river": "Blue River", "lat": 39.6328, "lon": -106.0694,
}

MOCK_PREDICTION = {
    "gauge_id": 5, "condition": "Good", "confidence": 0.82,
    "is_forecast": False, "model_version": "daily-v1",
}

MOCK_LATEST_READING = {
    "flow_cfs": 320.5, "water_temp_f": 48.2, "observed_date": date(2026, 4, 11),
}

MOCK_FORECAST = [
    {"target_date": date(2026, 4, 12), "condition": "Good", "confidence": 0.82,
     "is_forecast": False, "precip_mm_sum": 0.0, "air_temp_f_mean": 55.0,
     "air_temp_f_min": 40.0, "air_temp_f_max": 65.0},
    {"target_date": date(2026, 4, 13), "condition": "Fair", "confidence": 0.71,
     "is_forecast": True, "precip_mm_sum": 2.5, "air_temp_f_mean": 52.0,
     "air_temp_f_min": 38.0, "air_temp_f_max": 60.0},
]

MOCK_HISTORY = [
    {"target_date": date(2026, 4, 11), "condition": "Good", "confidence": 0.80,
     "flow_cfs": 320.5, "water_temp_f": 48.2},
    {"target_date": date(2026, 4, 10), "condition": "Poor", "confidence": 0.65,
     "flow_cfs": 1800.0, "water_temp_f": 45.0},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_session_multi(call_results):
    """Return a mock session where successive execute() calls return different rows.

    call_results: list of (fetchall_rows, fetchone_row) tuples.
    """
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)

    side_effects = []
    for fetchall_rows, fetchone_row in call_results:
        result = MagicMock()
        result.mappings.return_value.fetchall.return_value = fetchall_rows
        result.mappings.return_value.fetchone.return_value = fetchone_row
        side_effects.append(result)

    session.execute.side_effect = side_effects
    return session


# ---------------------------------------------------------------------------
# Route existence
# ---------------------------------------------------------------------------

def test_versioned_list_rivers_route_exists():
    """Verify /api/v1/rivers is mounted (may 500 without DB — that's OK)."""
    response = client.get("/api/v1/rivers")
    assert response.status_code != 404


def test_versioned_get_river_route_exists():
    response = client.get("/api/v1/rivers/07091200")
    assert response.status_code != 404


def test_versioned_get_river_history_route_exists():
    response = client.get("/api/v1/rivers/07091200/history")
    assert response.status_code != 404


def test_old_api_prefix_not_mounted():
    """Confirm /api/rivers (unversioned) is no longer served."""
    response = client.get("/api/rivers")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/rivers — list
# ---------------------------------------------------------------------------

def test_list_rivers_returns_list_with_expected_fields():
    """Each gauge in the response should have the full set of keys."""
    session = _mock_session_multi([
        ([MOCK_GAUGE, MOCK_GAUGE_2], None),  # gauges query
        ([MOCK_PREDICTION], None),            # predictions query
    ])
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2

    expected_keys = {"gauge_id", "name", "river", "lat", "lon", "condition", "confidence"}
    for item in data:
        assert set(item.keys()) == expected_keys


def test_list_rivers_gauge_with_prediction_has_condition():
    session = _mock_session_multi([
        ([MOCK_GAUGE], None),
        ([MOCK_PREDICTION], None),
    ])
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers")

    data = response.json()
    assert data[0]["condition"] == "Good"
    assert data[0]["confidence"] == 0.82


def test_list_rivers_gauge_without_prediction_has_null_condition():
    session = _mock_session_multi([
        ([MOCK_GAUGE], None),
        ([], None),  # no predictions
    ])
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers")

    data = response.json()
    assert data[0]["condition"] is None
    assert data[0]["confidence"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/rivers/{gauge_id} — detail
# ---------------------------------------------------------------------------

def test_get_river_returns_full_payload():
    session = _mock_session_multi([
        (None, MOCK_GAUGE),           # gauge lookup
        (None, MOCK_LATEST_READING),  # latest reading
    ])
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_forecast", return_value=MOCK_FORECAST):
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers/07091200")

    assert response.status_code == 200
    data = response.json()

    # Top-level fields
    assert data["gauge_id"] == "07091200"
    assert data["name"] == "Salida"
    assert data["river"] == "Arkansas River"
    assert isinstance(data["lat"], float)
    assert isinstance(data["lon"], float)
    assert "usgs_url" in data

    # Current reading
    assert data["current"]["flow_cfs"] == 320.5
    assert data["current"]["water_temp_f"] == 48.2

    # Forecast
    assert len(data["forecast"]) == 2
    forecast_keys = {"date", "condition", "confidence", "is_forecast",
                     "precip_mm", "air_temp_f_mean", "air_temp_f_min", "air_temp_f_max"}
    for f in data["forecast"]:
        assert set(f.keys()) == forecast_keys


def test_get_river_unknown_gauge_returns_404():
    session = _mock_session_multi([
        (None, None),  # gauge not found
    ])
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers/99999999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_river_no_latest_reading_returns_null_current():
    session = _mock_session_multi([
        (None, MOCK_GAUGE),  # gauge found
        (None, None),        # no reading
    ])
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_forecast", return_value=[]):
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers/07091200")

    assert response.status_code == 200
    data = response.json()
    assert data["current"] is None
    assert data["forecast"] == []


# ---------------------------------------------------------------------------
# GET /api/v1/rivers/{gauge_id}/history — history
# ---------------------------------------------------------------------------

def test_get_history_returns_expected_shape():
    session = _mock_session_multi([
        (None, MOCK_GAUGE),  # gauge lookup
    ])
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_history", return_value=MOCK_HISTORY):
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers/07091200/history")

    assert response.status_code == 200
    data = response.json()

    assert data["gauge_id"] == "07091200"
    assert data["name"] == "Salida"
    assert data["river"] == "Arkansas River"
    assert len(data["history"]) == 2

    history_keys = {"date", "condition", "confidence", "flow_cfs", "water_temp_f"}
    for h in data["history"]:
        assert set(h.keys()) == history_keys


def test_get_history_unknown_gauge_returns_404():
    session = _mock_session_multi([
        (None, None),
    ])
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers/99999999/history")

    assert response.status_code == 404


def test_get_history_empty_returns_empty_list():
    session = _mock_session_multi([
        (None, MOCK_GAUGE),
    ])
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_history", return_value=[]):
        mock_gs.return_value = session
        response = client.get("/api/v1/rivers/07091200/history")

    assert response.status_code == 200
    data = response.json()
    assert data["history"] == []
