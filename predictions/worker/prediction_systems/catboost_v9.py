# predictions/worker/prediction_systems/catboost_v9.py

"""
CatBoost V9 Prediction System - Current Season Training

Session 67 (2026-02-01): New model trained on current season only.

Key Differences from V8:
- Training: Current season only (Nov 2, 2025 - Jan 31, 2026) - 91 days
- Same 33 features as V8 (drop-in replacement)
- Continuous retraining: Model retrained monthly with expanding data window

Why Current Season Training:
1. Avoids historical data quality issues (team_win_pct bug, Vegas mismatch)
2. Captures current player roles, team dynamics
3. Better calibrated for current league trends

Performance (catboost_v9_feb_02_retrain.cbm - Session 76):
- MAE: 4.12 (vs V8's 5.36) - 23% improvement
- Premium Hit Rate: 56.5% (vs V8's 52.5%)
- High-Edge Hit Rate: 74.6% (vs V8's 56.9%)

Monthly Retraining:
V9 is designed for monthly retraining as the season progresses.
Training window expands each month, keeping data fresh.

Usage:
    from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9

    system = CatBoostV9()
    result = system.predict(player_lookup, features, betting_line)
"""

import logging
from pathlib import Path
from typing import Dict, Optional

from predictions.worker.prediction_systems.catboost_v8 import (
    CatBoostV8,
    ModelLoadError,
)

logger = logging.getLogger(__name__)


class CatBoostV9(CatBoostV8):
    """
    CatBoost V9 - Current Season Training Model

    Inherits all functionality from V8 but loads the V9 model file.
    Uses identical features and prediction logic.
    """

    # V9 Model Configuration
    MODEL_VERSION = "v9_current_season"
    SYSTEM_ID = "catboost_v9"

    # Training metadata (for documentation and debugging)
    # NOTE: These reflect the DEFAULT model loaded by CATBOOST_V9_MODEL_PATH env var
    # Current default: catboost_v9_feb_02_retrain.cbm (Session 82)
    TRAINING_INFO = {
        "approach": "current_season_only",
        "training_start": "2025-11-02",
        "training_end": "2026-01-31",  # Updated to match catboost_v9_feb_02_retrain.cbm
        "training_days": 91,
        "mae": 4.12,  # Session 82 retrain performance
        "high_edge_hit_rate": 74.6,  # High-edge (5+ edge) hit rate from validation
        "premium_hit_rate": 56.5,  # Premium (92+ conf, 3+ edge) hit rate
        "feature_count": 33,
        "feature_version": "v2_33features",
        "model_file": "catboost_v9_feb_02_retrain.cbm",
        "session": 82,  # Session that deployed this model
        "trained_at": "2026-02-02T10:15:00Z",  # When this model was trained
    }

    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize CatBoost V9 with current-season trained model.

        Args:
            model_path: Optional explicit path to model file.
                       If not provided, searches for catboost_v9_33features_*.cbm
        """
        # Don't call super().__init__() yet - we need to set up V9-specific paths first
        self.model = None
        self._load_attempts = 0
        self._last_load_error = None
        self._model_path = None
        self._model_file_name = None

        if model_path:
            self._load_model_from_path(model_path)
        else:
            self._load_model_from_default_location()

    def _load_model_from_default_location(self):
        """Load V9 model from default locations (local first, then GCS)."""
        import catboost as cb
        import os

        # Try local models directory first
        models_dir = Path(__file__).parent.parent.parent.parent / "models"
        model_files = list(models_dir.glob("catboost_v9_33features_*.cbm"))

        if model_files:
            # Use most recent model file
            model_path = sorted(model_files)[-1]
            logger.info(f"Loading CatBoost V9 from local: {model_path}")
            self.model = cb.CatBoostRegressor()
            self.model.load_model(str(model_path))
            self._model_path = str(model_path)
            self._model_file_name = model_path.name
            logger.info(
                f"CatBoost V9 loaded successfully from {self._model_file_name}. "
                f"Training: {self.TRAINING_INFO['training_start']} to {self.TRAINING_INFO['training_end']}. "
                f"Ready to generate predictions with 33 features."
            )
            return

        # Try GCS - check for environment variable or use default path
        gcs_path = os.environ.get(
            'CATBOOST_V9_MODEL_PATH',
            'gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260201_011018.cbm'
        )
        logger.info(f"No local V9 model found, loading from GCS: {gcs_path}")

        # Load from GCS using parent class method
        self._load_model_from_path(gcs_path)

    def _load_model_from_path(self, model_path: str):
        """Load V9 model from explicit path (local or GCS)."""
        import catboost as cb
        from pathlib import Path

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

            # Extract file name from GCS path
            self._model_file_name = Path(blob_path).name
        else:
            # Load from local path
            self.model = cb.CatBoostRegressor()
            self.model.load_model(model_path)
            self._model_file_name = Path(model_path).name

        self._model_path = model_path
        logger.info(
            f"CatBoost V9 loaded successfully from {self._model_file_name}. "
            f"Training: {self.TRAINING_INFO['training_start']} to {self.TRAINING_INFO['training_end']}. "
            f"Ready to generate predictions with 33 features."
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

        # Override metadata with V9-specific info + model attribution (Session 84)
        # Create metadata dict if it doesn't exist (V8 doesn't return one)
        if result:
            if 'metadata' not in result:
                result['metadata'] = {}

            result['metadata']['model_version'] = self.MODEL_VERSION
            result['metadata']['system_id'] = self.SYSTEM_ID
            result['metadata']['training_approach'] = self.TRAINING_INFO['approach']
            result['metadata']['training_period'] = (
                f"{self.TRAINING_INFO['training_start']} to {self.TRAINING_INFO['training_end']}"
            )

            # Session 84: Model attribution tracking
            result['metadata']['model_file_name'] = self._model_file_name
            result['metadata']['model_training_start_date'] = self.TRAINING_INFO['training_start']
            result['metadata']['model_training_end_date'] = self.TRAINING_INFO['training_end']
            result['metadata']['model_expected_mae'] = self.TRAINING_INFO['mae']
            result['metadata']['model_expected_hit_rate'] = self.TRAINING_INFO['high_edge_hit_rate']
            result['metadata']['model_trained_at'] = self.TRAINING_INFO['trained_at']

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
            "training_info": self.TRAINING_INFO,
            "feature_count": 33,
            "status": "loaded" if self.model is not None else "not_loaded",
        }
