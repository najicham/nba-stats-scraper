# predictions/worker/prediction_systems/catboost_monthly.py

"""
CatBoost Monthly Models - Configurable Monthly Retraining System

Session 68 (2026-02-01): Monthly model architecture for continuous improvement.

This module provides a configurable system for running multiple monthly-retrained
CatBoost models in parallel. Each model is trained on progressively expanding
current-season data and identified by its month.

Usage:
    from predictions.worker.prediction_systems.catboost_monthly import (
        get_enabled_monthly_models,
        CatBoostMonthly
    )

    # Get all enabled monthly models
    models = get_enabled_monthly_models()
    for model in models:
        result = model.predict(player_lookup, features, betting_line)
        # Each model produces predictions with its own system_id

Adding a New Monthly Model:
    1. Train model using quick_retrain.py
    2. Rename to: models/catboost_v9_YYYY_MM.cbm
    3. Add entry to MONTHLY_MODELS dict below
    4. Set enabled=True
    5. Deploy worker
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from predictions.worker.prediction_systems.catboost_v8 import (
    CatBoostV8,
    ModelLoadError,
)

logger = logging.getLogger(__name__)


# Monthly Model Configuration
# Add new monthly models here. Each entry defines a separate model that runs in parallel.
MONTHLY_MODELS = {
    "catboost_v9_2026_02": {
        "model_path": "models/catboost_v9_2026_02.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-24",
        "eval_start": "2026-01-25",
        "eval_end": "2026-01-31",
        "mae": 5.0753,
        "hit_rate_overall": 50.84,
        "enabled": True,
        "description": "February 2026 monthly model - 84 day training window",
    },
    # Add future monthly models here:
    # "catboost_v9_2026_03": {
    #     "model_path": "models/catboost_v9_2026_03.cbm",
    #     "train_start": "2025-11-02",
    #     "train_end": "2026-02-28",
    #     "eval_start": "2026-03-01",
    #     "eval_end": "2026-03-07",
    #     "mae": None,  # Fill in after training
    #     "hit_rate_overall": None,
    #     "enabled": True,
    #     "description": "March 2026 monthly model - 118 day training window",
    # },
}


class CatBoostMonthly(CatBoostV8):
    """
    CatBoost Monthly Model - Loads a specific monthly-retrained model.

    This class loads a specific monthly model identified by model_id.
    Each instance produces predictions with its own system_id, allowing
    multiple monthly models to run in parallel.

    Args:
        model_id: Key from MONTHLY_MODELS dict (e.g., "catboost_v9_2026_02")

    Example:
        feb_model = CatBoostMonthly("catboost_v9_2026_02")
        result = feb_model.predict(player_lookup, features, betting_line)
        # Result has system_id = "catboost_v9_2026_02"
    """

    def __init__(self, model_id: str):
        """
        Initialize monthly model with specific model_id.

        Args:
            model_id: Key from MONTHLY_MODELS dict

        Raises:
            ValueError: If model_id not found in MONTHLY_MODELS
            ModelLoadError: If model file cannot be loaded
        """
        if model_id not in MONTHLY_MODELS:
            raise ValueError(
                f"Unknown model_id: {model_id}. "
                f"Available models: {list(MONTHLY_MODELS.keys())}"
            )

        self.model_id = model_id
        self.config = MONTHLY_MODELS[model_id]

        # Don't call super().__init__() - we need custom loading
        self.model = None
        self._load_attempts = 0
        self._last_load_error = None

        # Load the specific monthly model
        model_path = self.config["model_path"]
        self._load_model_from_path(model_path)

        logger.info(
            f"CatBoost Monthly model loaded: {model_id} "
            f"(trained {self.config['train_start']} to {self.config['train_end']}, "
            f"MAE={self.config.get('mae', 'N/A')})"
        )

    def _load_model_from_path(self, model_path: str):
        """Load monthly model from local path."""
        import catboost as cb

        # Resolve relative path from repository root
        if not model_path.startswith('/') and not model_path.startswith('gs://'):
            repo_root = Path(__file__).parent.parent.parent.parent
            model_path = str(repo_root / model_path)

        if not Path(model_path).exists():
            raise ModelLoadError(
                f"Monthly model file not found: {model_path}. "
                f"Expected for model_id: {self.model_id}"
            )

        logger.info(f"Loading CatBoost monthly model from: {model_path}")
        self.model = cb.CatBoostRegressor()
        self.model.load_model(model_path)
        self._model_path = model_path

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
        Generate prediction using this monthly model.

        Uses parent class prediction logic but returns model-specific system_id.
        """
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

        # Override fields with monthly model info
        if result:
            result['system_id'] = self.model_id
            result['model_version'] = self.model_id
            result['training_period'] = (
                f"{self.config['train_start']} to {self.config['train_end']}"
            )
            result['model_type'] = 'monthly_retrain'
            result['training_mae'] = self.config.get('mae')

        return result

    @property
    def system_id(self) -> str:
        """Return monthly model system identifier."""
        return self.model_id

    @property
    def model_version(self) -> str:
        """Return monthly model version."""
        return self.model_id

    def get_model_info(self) -> Dict:
        """Return monthly model information for health checks and debugging."""
        return {
            "system_id": self.model_id,
            "model_version": self.model_id,
            "model_path": getattr(self, '_model_path', 'unknown'),
            "config": self.config,
            "feature_count": 33,
            "status": "loaded" if self.model is not None else "not_loaded",
        }


def get_enabled_monthly_models() -> List[CatBoostMonthly]:
    """
    Get all enabled monthly models.

    Returns:
        List of CatBoostMonthly instances for all models where enabled=True

    Example:
        models = get_enabled_monthly_models()
        logger.info(f"Loaded {len(models)} monthly models")
        for model in models:
            predictions = model.predict(...)
    """
    enabled_models = []

    for model_id, config in MONTHLY_MODELS.items():
        if config.get("enabled", False):
            try:
                model = CatBoostMonthly(model_id)
                enabled_models.append(model)
                logger.info(f"✓ Monthly model enabled: {model_id}")
            except Exception as e:
                logger.error(
                    f"Failed to load monthly model {model_id}: {e}",
                    exc_info=True
                )

    if not enabled_models:
        logger.warning("No monthly models enabled in MONTHLY_MODELS config")
    else:
        logger.info(
            f"Loaded {len(enabled_models)} monthly model(s): "
            f"{[m.model_id for m in enabled_models]}"
        )

    return enabled_models


def get_monthly_model_by_id(model_id: str) -> CatBoostMonthly:
    """
    Get a specific monthly model by ID.

    Args:
        model_id: Key from MONTHLY_MODELS dict

    Returns:
        CatBoostMonthly instance

    Raises:
        ValueError: If model_id not found or not enabled
    """
    if model_id not in MONTHLY_MODELS:
        raise ValueError(
            f"Unknown model_id: {model_id}. "
            f"Available: {list(MONTHLY_MODELS.keys())}"
        )

    if not MONTHLY_MODELS[model_id].get("enabled", False):
        raise ValueError(f"Model {model_id} is not enabled")

    return CatBoostMonthly(model_id)
