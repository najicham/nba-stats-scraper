# predictions/worker/prediction_systems/catboost_v9.py

"""
CatBoost V9 Prediction System - Current Season Training

Session 67 (2026-02-01): New model trained on current season only.
Session 163 (2026-02-08): Model governance — dynamic version from filename, SHA256 tracking.

Key Differences from V8:
- Training: Current season only (Nov 2, 2025+)
- Same 33 features as V8 (drop-in replacement)
- Continuous retraining: Model retrained monthly with expanding data window

Model Governance (Session 163):
- MODEL_VERSION is derived from the loaded model filename (not hardcoded)
- SHA256 hash computed at load time for audit trail
- Model manifest in GCS tracks all models, metrics, and deployment history
- See docs/08-projects/current/model-governance/ for full process

Usage:
    from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9

    system = CatBoostV9()
    result = system.predict(player_lookup, features, betting_line)
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from predictions.worker.prediction_systems.catboost_v8 import (
    CatBoostV8,
    ModelLoadError,
)

logger = logging.getLogger(__name__)

# GCS bucket for all models
MODEL_BUCKET = "nba-props-platform-models"
MODEL_PREFIX = "catboost/v9"
DEFAULT_MODEL_GCS = f"gs://{MODEL_BUCKET}/{MODEL_PREFIX}/catboost_v9_33features_20260201_011018.cbm"


def _compute_file_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a model file for integrity verification."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:16]  # First 16 chars for brevity


def _derive_model_version(filename: str) -> str:
    """Derive a unique model_version string from the model filename.

    Examples:
        catboost_v9_33features_20260201_011018.cbm -> v9_20260201_011018
        catboost_v9_feb_02_retrain.cbm -> v9_feb_02_retrain
        catboost_v9_2026_02.cbm -> v9_2026_02
    """
    stem = Path(filename).stem  # Remove .cbm
    # Remove common prefix patterns
    for prefix in ["catboost_v9_33features_", "catboost_v9_"]:
        if stem.startswith(prefix):
            return f"v9_{stem[len(prefix):]}"
    return f"v9_{stem}"


class CatBoostV9(CatBoostV8):
    """
    CatBoost V9 - Current Season Training Model

    Inherits all functionality from V8 but loads the V9 model file.
    Uses identical features and prediction logic.

    Model version is derived dynamically from the loaded model filename
    so that predictions from different retrains can be distinguished in grading.
    """

    SYSTEM_ID = "catboost_v9"

    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize CatBoost V9 with current-season trained model.

        Args:
            model_path: Optional explicit path to model file.
                       If not provided, uses CATBOOST_V9_MODEL_PATH env var or default GCS path.
        """
        # Don't call super().__init__() yet - we need to set up V9-specific paths first
        self.model = None
        self._load_attempts = 0
        self._last_load_error = None
        self._model_path = None
        self._model_file_name = None
        self._model_sha256 = None
        self._model_version = None  # Derived from filename at load time

        if model_path:
            self._load_model_from_path(model_path)
        else:
            self._load_model_from_default_location()

    @property
    def MODEL_VERSION(self) -> str:
        """Model version derived from the loaded model filename."""
        return self._model_version or "v9_unknown"

    def _load_model_from_default_location(self):
        """Load V9 model from default locations (local first, then GCS)."""
        import catboost as cb

        # Try local models directory first — match any catboost_v9*.cbm file
        models_dir = Path(__file__).parent.parent.parent.parent / "models"
        model_files = list(models_dir.glob("catboost_v9*.cbm"))

        if model_files:
            # Use most recent model file
            model_path = sorted(model_files)[-1]
            logger.info(f"Loading CatBoost V9 from local: {model_path}")
            self.model = cb.CatBoostRegressor()
            self.model.load_model(str(model_path))
            self._model_path = str(model_path)
            self._model_file_name = model_path.name
            self._model_sha256 = _compute_file_sha256(str(model_path))
            self._model_version = _derive_model_version(self._model_file_name)
            logger.info(
                f"CatBoost V9 loaded: file={self._model_file_name} "
                f"version={self._model_version} sha256={self._model_sha256}"
            )
            return

        # Try GCS - check for environment variable or use default path
        gcs_path = os.environ.get('CATBOOST_V9_MODEL_PATH', DEFAULT_MODEL_GCS)
        logger.info(f"No local V9 model found, loading from GCS: {gcs_path}")

        # Load from GCS
        self._load_model_from_path(gcs_path)

    def _load_model_from_path(self, model_path: str):
        """Load V9 model from explicit path (local or GCS)."""
        import catboost as cb

        logger.info(f"Loading CatBoost V9 from: {model_path}")

        if model_path.startswith("gs://"):
            # Load from GCS
            from shared.clients import get_storage_client
            parts = model_path.replace("gs://", "").split("/", 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = get_storage_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            local_path = "/tmp/catboost_v9.cbm"
            blob.download_to_filename(local_path)
            logger.info(f"Downloaded V9 model from GCS to {local_path}")

            self.model = cb.CatBoostRegressor()
            self.model.load_model(local_path)

            self._model_file_name = Path(blob_path).name
            self._model_sha256 = _compute_file_sha256(local_path)
        else:
            # Load from local path
            self.model = cb.CatBoostRegressor()
            self.model.load_model(model_path)
            self._model_file_name = Path(model_path).name
            self._model_sha256 = _compute_file_sha256(model_path)

        self._model_path = model_path
        self._model_version = _derive_model_version(self._model_file_name)
        logger.info(
            f"CatBoost V9 loaded: file={self._model_file_name} "
            f"version={self._model_version} sha256={self._model_sha256}"
        )

    def predict(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float] = None,
        opponent_avg: Optional[float] = None,
        games_vs_opponent: Optional[int] = None,
        minutes_avg_last_10: Optional[float] = None,
        ppm_avg_last_10: Optional[float] = None,
        vegas_line: Optional[float] = None,
        vegas_opening: Optional[float] = None,
    ) -> Dict:
        """
        Generate prediction using CatBoost V9 model.

        Same interface as V8 - returns dict with prediction, confidence, metadata.
        """
        # Use parent class prediction logic (identical features)
        result = super().predict(
            player_lookup=player_lookup,
            features=features,
            betting_line=betting_line,
            opponent_avg=opponent_avg,
            games_vs_opponent=games_vs_opponent,
            minutes_avg_last_10=minutes_avg_last_10,
            ppm_avg_last_10=ppm_avg_last_10,
            vegas_line=vegas_line,
            vegas_opening=vegas_opening,
        )

        # Override metadata with V9-specific info + model attribution (Session 84, 163)
        if result:
            if 'metadata' not in result:
                result['metadata'] = {}

            result['metadata']['model_version'] = self.MODEL_VERSION
            result['metadata']['system_id'] = self.SYSTEM_ID
            result['metadata']['model_file_name'] = self._model_file_name
            result['metadata']['model_sha256'] = self._model_sha256

        return result

    @property
    def system_id(self) -> str:
        """Return V9 system identifier."""
        return self.SYSTEM_ID

    @property
    def model_version(self) -> str:
        """Return V9 model version."""
        return self.MODEL_VERSION

    def get_model_info(self) -> Dict:
        """Return V9 model information for health checks and debugging."""
        return {
            "system_id": self.SYSTEM_ID,
            "model_version": self.MODEL_VERSION,
            "model_path": getattr(self, '_model_path', 'unknown'),
            "model_file_name": self._model_file_name,
            "model_sha256": self._model_sha256,
            "feature_count": 33,
            "status": "loaded" if self.model is not None else "not_loaded",
        }
