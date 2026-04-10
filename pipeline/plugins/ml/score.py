"""Load production XGBoost model from MLflow and score feature vectors.

load_production_model() fetches the latest model in 'Production' stage.
predict_condition() returns (condition_label, confidence).
"""

import os
from typing import Dict, Optional, Tuple

import mlflow
import mlflow.xgboost
import numpy as np
import xgboost as xgb

from plugins.ml.train import CONDITION_CLASSES, DAILY_FEATURE_COLS, FEATURE_COLS


def load_production_model(model_name: str = "riffle-conditions") -> xgb.Booster:
    """Load the model in the Production stage from MLflow registry.

    Requires MLFLOW_TRACKING_URI env var to be set.
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(tracking_uri)

    model_uri = f"models:/{model_name}/Production"
    return mlflow.xgboost.load_model(model_uri)


def promote_model_to_production(run_id: str, model_name: str = "riffle-conditions") -> None:
    """Register the model from run_id and promote it to Production stage.

    Archives any previously Production-staged version.
    """
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(tracking_uri)

    client = mlflow.tracking.MlflowClient()
    model_uri = f"runs:/{run_id}/model"

    result = mlflow.register_model(model_uri, model_name)
    version = result.version

    client.transition_model_version_stage(
        name=model_name,
        version=version,
        stage="Production",
        archive_existing_versions=True,
    )


def predict_condition(
    booster: xgb.Booster,
    features: Dict[str, float],
) -> Tuple[str, float]:
    """Score a single feature vector.

    Returns (condition_label, confidence) where confidence is the
    probability of the predicted class.
    """
    row = np.array([[features[col] for col in FEATURE_COLS]], dtype=np.float32)
    dmatrix = xgb.DMatrix(row, feature_names=FEATURE_COLS)
    probs = booster.predict(dmatrix)  # shape: (1, num_classes)
    class_idx = int(np.argmax(probs[0]))
    confidence = float(probs[0][class_idx])
    return CONDITION_CLASSES[class_idx], confidence


def predict_daily_condition(
    booster: xgb.Booster,
    features: Dict[str, float],
) -> Tuple[str, float]:
    """Score a single daily feature vector against the daily model."""
    row = np.array([[features[col] for col in DAILY_FEATURE_COLS]], dtype=np.float32)
    dmatrix = xgb.DMatrix(row, feature_names=DAILY_FEATURE_COLS)
    probs = booster.predict(dmatrix)
    class_idx = int(np.argmax(probs[0]))
    confidence = float(probs[0][class_idx])
    return CONDITION_CLASSES[class_idx], confidence
