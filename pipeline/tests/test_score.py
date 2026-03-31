import sys
sys.path.insert(0, "pipeline")
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from plugins.ml.score import predict_condition, load_production_model
from plugins.ml.train import CONDITION_CLASSES


def test_predict_condition_returns_valid_label():
    mock_booster = MagicMock()
    # softprob returns one probability per class per row
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][3] = 0.9  # index 3 = "Good"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 150.0, "gauge_height_ft": 1.5, "water_temp_f": 52.0,
        "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 55.0,
        "day_of_year": 90, "days_since_precip_event": 5,
    }
    label, confidence = predict_condition(mock_booster, features)
    assert label == "Good"
    assert confidence == pytest.approx(0.9)


def test_predict_condition_returns_str_and_float():
    mock_booster = MagicMock()
    probs = np.zeros((1, len(CONDITION_CLASSES)))
    probs[0][0] = 0.95  # "Blown Out"
    mock_booster.predict.return_value = probs

    features = {
        "flow_cfs": 1000.0, "gauge_height_ft": 5.0, "water_temp_f": 55.0,
        "precip_24h_mm": 0.0, "precip_72h_mm": 0.0, "air_temp_f": 45.0,
        "day_of_year": 150, "days_since_precip_event": 1,
    }
    label, confidence = predict_condition(mock_booster, features)
    assert isinstance(label, str)
    assert isinstance(confidence, float)
    assert label == "Blown Out"
