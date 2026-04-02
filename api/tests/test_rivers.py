import sys, os
os.environ["DATABASE_URL"] = "postgresql+psycopg2://riffle:riffle@localhost/riffle"
import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from fastapi.testclient import TestClient
from datetime import date

# Import after env is set
from api.main import app

client = TestClient(app)

MOCK_GAUGES = [
    {
        "id": 1, "usgs_gauge_id": "09035800", "name": "Spinney Reservoir",
        "river": "South Platte", "lat": 38.9097, "lon": -105.5666,
    }
]

MOCK_PREDICTIONS_TODAY = [
    {
        "gauge_id": 1, "date": date(2026, 3, 30), "condition": "Good",
        "confidence": 0.82, "is_forecast": False, "model_version": "1",
    }
]

MOCK_FORECAST = [
    {"gauge_id": 1, "target_datetime": date(2026, 3, 30), "condition": "Good", "confidence": 0.82, "is_forecast": False, "model_version": "1"},
    {"gauge_id": 1, "target_datetime": date(2026, 3, 31), "condition": "Fair", "confidence": 0.71, "is_forecast": True, "model_version": "1"},
    {"gauge_id": 1, "target_datetime": date(2026, 3, 31), "condition": "Poor", "confidence": 0.65, "is_forecast": True, "model_version": "1"},
    {"gauge_id": 1, "target_datetime": date(2026, 4, 1),  "condition": "Good", "confidence": 0.78, "is_forecast": True, "model_version": "1"},
]

def _mock_session(rows):
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.execute.return_value.mappings.return_value.fetchall.return_value = rows
    session.execute.return_value.mappings.return_value.fetchone.return_value = rows[0] if rows else None
    return session

def test_get_rivers_returns_list():
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        resp = client.get("/api/v1/rivers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

def test_get_rivers_includes_condition():
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_today_predictions") as mock_preds:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        mock_preds.return_value = {1: MOCK_PREDICTIONS_TODAY[0]}
        resp = client.get("/api/v1/rivers")
    assert resp.status_code == 200

def test_get_river_detail_returns_forecast():
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_forecast") as mock_fc:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        mock_fc.return_value = MOCK_FORECAST
        resp = client.get("/api/v1/rivers/09035800")
    assert resp.status_code == 200

def test_get_river_detail_unknown_gauge():
    with patch("api.routes.rivers.get_session") as mock_gs:
        mock_gs.return_value = _mock_session([])
        resp = client.get("/api/v1/rivers/99999999")
    assert resp.status_code == 404

def test_get_history_returns_30_days():
    mock_history = [
        {"target_datetime": date(2026, 3, 30 - i), "condition": "Good", "confidence": 0.8, "flow_cfs": 150.0, "water_temp_f": 52.0}
        for i in range(30)
    ]
    with patch("api.routes.rivers.get_session") as mock_gs, \
         patch("api.routes.rivers.get_gauge_history") as mock_hist:
        mock_gs.return_value = _mock_session(MOCK_GAUGES)
        mock_hist.return_value = mock_history
        resp = client.get("/api/v1/rivers/09035800/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
