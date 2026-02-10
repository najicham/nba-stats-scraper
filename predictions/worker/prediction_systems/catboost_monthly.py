# predictions/worker/prediction_systems/catboost_monthly.py

"""
CatBoost Monthly Models - Configurable Parallel Model System

Session 68 (2026-02-01): Monthly model architecture for continuous improvement.
Session 177 (2026-02-09): Parallel V9 models — GCS loading, SHA256 tracking,
    training-date naming convention for running multiple challengers in shadow mode.

This module provides a configurable system for running multiple CatBoost V9
models in parallel. Each model gets its own system_id, runs in shadow mode
(no impact on user-facing picks or alerts), and is graded independently.

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

Adding a New Challenger Model:
    1. Train model using quick_retrain.py (prints MONTHLY_MODELS config snippet)
    2. Upload to GCS: gsutil cp model.cbm gs://nba-props-platform-models/catboost/v9/monthly/
    3. Add entry to MONTHLY_MODELS dict below with GCS path
    4. Set enabled=True
    5. Deploy worker (push to main triggers auto-deploy)
    6. Monitor: python bin/compare-model-performance.py <system_id>
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from predictions.worker.prediction_systems.catboost_v8 import (
    CatBoostV8,
    ModelLoadError,
)
from predictions.worker.prediction_systems.catboost_v9 import (
    _compute_file_sha256,
)

logger = logging.getLogger(__name__)


# Parallel Model Configuration
# Each entry runs as a shadow challenger alongside the production champion (catboost_v9).
# Naming convention: catboost_v9_train{MMDD}_{MMDD} — training dates visible in every BQ query.
# Challengers don't affect user-facing picks (subset_picks_notifier is champion-only).
MONTHLY_MODELS = {
    "catboost_v9_2026_02": {
        "model_path": "models/catboost_v9_2026_02.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-24",
        "mae": 5.0753,
        "hit_rate_overall": 50.84,
        "enabled": False,  # Session 169: Disabled — 50.84% hit rate, UNDER bias (Session 163)
        "description": "February 2026 monthly model - DISABLED",
    },
    "catboost_v9_train1102_0108": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260108_20260209_175818.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-08",
        "backtest_mae": 4.784,
        "backtest_hit_rate_all": 62.4,
        "backtest_hit_rate_edge_3plus": 87.0,
        "backtest_n_edge_3plus": 131,
        "enabled": True,
        "description": "V9_BASELINE_CLEAN — same train dates as prod, better feature quality",
    },
    "catboost_v9_train1102_0208": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260208_20260209_172523.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-02-08",
        "backtest_mae": 4.44,
        "backtest_hit_rate_all": 75.37,
        "backtest_hit_rate_edge_3plus": 91.8,
        "backtest_n_edge_3plus": 159,
        "enabled": False,  # Session 178: RETIRED — contaminated backtest (31-day train/eval overlap)
        "description": "V9_FULL_FEB — RETIRED: contaminated backtest metrics",
    },
    "catboost_v9_train1102_0208_tuned": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260208_20260209_174344.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-02-08",
        "backtest_mae": 4.50,
        "backtest_hit_rate_all": 74.79,
        "backtest_hit_rate_edge_3plus": 93.0,
        "backtest_n_edge_3plus": 157,
        "enabled": False,  # Session 178: RETIRED — contaminated backtest metrics
        "description": "V9_TUNED_FEB — RETIRED: contaminated backtest metrics",
    },
    "catboost_v9_train1102_0131": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260131_20260209_212708.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-31",
        "backtest_mae": 4.9455,
        "backtest_hit_rate_all": 60.0,
        "backtest_hit_rate_edge_3plus": 33.3,
        "backtest_n_edge_3plus": 6,
        "enabled": False,  # Session 186: RETIRED — identical to _tuned in production (53.6% vs 53.4%), redundant
        "description": "V9_JAN31_DEFAULTS — RETIRED: redundant with _tuned",
    },
    "catboost_v9_train1102_0131_tuned": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260131_20260209_212715.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-31",
        "backtest_mae": 4.9425,
        "backtest_hit_rate_all": 58.62,
        "backtest_hit_rate_edge_3plus": 33.3,
        "backtest_n_edge_3plus": 6,
        "enabled": True,
        "description": "V9_JAN31_TUNED — extended training (91 days), tuned (depth=5,l2=5,lr=0.03) + recency 30d, clean eval Feb 1-8",
    },
    "catboost_v9_q43_train1102_0131": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_q0.43_train20251102-20260131_20260210_094854.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-31",
        "backtest_mae": 5.1571,
        "backtest_hit_rate_all": 50.0,
        "backtest_hit_rate_edge_3plus": 65.79,
        "backtest_n_edge_3plus": 38,
        "enabled": True,
        "description": "Q43_SHADOW — quantile alpha=0.43, staleness-independent edge (Session 186). 65.8% HR 3+ when fresh, 67.6% UNDER HR.",
    },
    "catboost_v9_q45_train1102_0131": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_q0.45_train20251102-20260131_20260210_103216.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-31",
        "backtest_mae": 5.0871,
        "backtest_hit_rate_all": 50.0,
        "backtest_hit_rate_edge_3plus": 61.9,
        "backtest_n_edge_3plus": 21,
        "enabled": True,
        "description": "Q45_SHADOW — quantile alpha=0.45, less aggressive than Q43 (Session 186). 61.9% HR 3+, 65.0% UNDER HR. Vegas bias -1.34 (within limits).",
    },
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
        self._model_file_name = None
        self._model_sha256 = None

        # Load the specific monthly model
        model_path = self.config["model_path"]
        self._load_model_from_path(model_path)

        logger.info(
            f"CatBoost Monthly model loaded: {model_id} "
            f"(trained {self.config['train_start']} to {self.config['train_end']}, "
            f"file={self._model_file_name}, sha256={self._model_sha256})"
        )

    def _load_model_from_path(self, model_path: str):
        """Load monthly model from local path or GCS.

        Session 177: Ported GCS loading from CatBoostV9 to support cloud-stored
        challenger models. Each model downloads to a unique /tmp path to avoid
        collisions when multiple models load simultaneously.
        """
        import catboost as cb

        logger.info(f"Loading CatBoost monthly model from: {model_path}")

        if model_path.startswith("gs://"):
            # Load from GCS — unique temp file per model_id to avoid collisions
            from shared.clients import get_storage_client
            parts = model_path.replace("gs://", "").split("/", 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = get_storage_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            local_path = f"/tmp/catboost_monthly_{self.model_id}.cbm"
            blob.download_to_filename(local_path)
            logger.info(f"Downloaded monthly model from GCS to {local_path}")

            self.model = cb.CatBoostRegressor()
            self.model.load_model(local_path)
            self._model_file_name = Path(blob_path).name
            self._model_sha256 = _compute_file_sha256(local_path)
        else:
            # Resolve relative path from repository root
            if not model_path.startswith('/'):
                repo_root = Path(__file__).parent.parent.parent.parent
                model_path = str(repo_root / model_path)

            if not Path(model_path).exists():
                raise ModelLoadError(
                    f"Monthly model file not found: {model_path}. "
                    f"Expected for model_id: {self.model_id}"
                )

            self.model = cb.CatBoostRegressor()
            self.model.load_model(model_path)
            self._model_file_name = Path(model_path).name
            self._model_sha256 = _compute_file_sha256(model_path)

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
            result['training_mae'] = self.config.get('mae') or self.config.get('backtest_mae')

            # Session 177: Model attribution metadata for format_prediction_for_bigquery
            if 'metadata' not in result:
                result['metadata'] = {}
            result['metadata']['model_file_name'] = self._model_file_name
            result['metadata']['model_sha256'] = self._model_sha256
            result['metadata']['model_version'] = self.model_id
            result['metadata']['system_id'] = self.model_id

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
            "model_file_name": self._model_file_name,
            "model_sha256": self._model_sha256,
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
