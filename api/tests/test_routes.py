# api/tests/test_routes.py
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app, raise_server_exceptions=False)


def test_versioned_list_rivers_route_exists():
    """Verify /api/v1/rivers is mounted (may 500 without DB — that's OK)."""
    response = client.get("/api/v1/rivers")
    assert response.status_code != 404


def test_versioned_get_river_route_exists():
    response = client.get("/api/v1/rivers/09035800")
    assert response.status_code != 404


def test_versioned_get_river_history_route_exists():
    response = client.get("/api/v1/rivers/09035800/history")
    assert response.status_code != 404


def test_old_api_prefix_not_mounted():
    """Confirm /api/rivers (unversioned) is no longer served."""
    response = client.get("/api/rivers")
    assert response.status_code == 404


def test_list_rivers_returns_list_shape():
    """With DB mocked, list endpoint returns expected shape."""
    mock_gauge = {
        "id": 1, "usgs_gauge_id": "09035800", "name": "Spinney",
        "river": "South Platte", "lat": 38.9, "lon": -105.5,
    }
    mock_pred = {1: {"condition": "Good", "confidence": 0.82}}
    with patch("api.routes.rivers.get_session") as mock_ctx:
        mock_session = MagicMock()
        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = [mock_gauge]
        mock_ctx.return_value.__enter__.return_value = mock_session
        with patch("api.routes.rivers.get_today_predictions", return_value=mock_pred):
            response = client.get("/api/v1/rivers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["gauge_id"] == "09035800"
    assert data[0]["condition"] == "Good"
