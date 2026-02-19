# predictions/worker/prediction_systems/catboost_monthly.py

"""
CatBoost Monthly Models - DB-Driven Parallel Model System

Session 68 (2026-02-01): Monthly model architecture for continuous improvement.
Session 177 (2026-02-09): Parallel V9 models — GCS loading, SHA256 tracking.
Session 273 (2026-02-16): Model Management Overhaul — DB-driven loading from
    model_registry, feature-set-aware prediction (V9 33-feature and V12 50-feature),
    MONTHLY_MODELS dict kept as fallback.

This module provides a configurable system for running multiple CatBoost models
in parallel. Each model gets its own system_id, runs in shadow mode (no impact
on user-facing picks), and is graded independently.

Models are loaded from model_registry (BQ) at worker startup. The MONTHLY_MODELS
dict serves as a fallback if the registry query fails.

Usage:
    from predictions.worker.prediction_systems.catboost_monthly import (
        get_enabled_monthly_models,
        CatBoostMonthly
    )

    models = get_enabled_monthly_models()
    for model in models:
        result = model.predict(player_lookup, features, betting_line)
"""

import json
import logging
import numpy as np
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


# V12 no-vegas feature names (50 features) — same list as catboost_v12.py
# Imported here to avoid circular imports
V12_NOVEG_FEATURES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10",
    "dnp_rate", "pts_slope_10g", "pts_vs_season_zscore", "breakout_flag",
    "star_teammates_out", "game_total_line",
    "days_rest", "minutes_load_last_7d", "spread_magnitude",
    "implied_team_total", "points_avg_last_3", "scoring_trend_slope",
    "deviation_from_avg_last3", "consecutive_games_below_avg",
    "teammate_usage_available", "usage_rate_last_5",
    "games_since_structural_change", "multi_book_line_std",
    "prop_over_streak", "prop_under_streak", "line_vs_season_avg",
]


# ============================================================================
# Legacy MONTHLY_MODELS dict — fallback if model_registry query fails
# ============================================================================
# New models should be auto-registered via quick_retrain.py --auto-register
# and enabled via: UPDATE model_registry SET enabled=TRUE WHERE model_id='...'
MONTHLY_MODELS = {
    # === V9 MAE (33 features) — Champion ===
    "catboost_v9_train1102_0205": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260205_20260216_191144.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-02-05",
        "backtest_mae": 4.766,
        "backtest_hit_rate_all": 56.07,
        "backtest_hit_rate_edge_3plus": 76.19,
        "backtest_n_edge_3plus": 21,
        "enabled": True,
        "feature_set": "v9",
        "description": "V9_MAE_FEB_RETRAIN — All-Star break retrain, walkforward W1=81.2%",
    },
    # === V12 No-Vegas MAE (50 features) — Shadow ===
    "catboost_v12_noveg_train1102_0205": {
        "model_path": "gs://nba-props-platform-models/catboost/v12/monthly/catboost_v9_50f_noveg_train20251102-20260205_20260216_191227.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-02-05",
        "backtest_mae": 4.701,
        "backtest_hit_rate_all": 59.06,
        "backtest_hit_rate_edge_3plus": 69.23,
        "backtest_n_edge_3plus": 13,
        "enabled": True,
        "feature_set": "v12",
        "description": "V12_NOVEG_MAE_FEB_RETRAIN — 50-feature no-vegas, walkforward W1=69.2%",
    },
    # === V9 Quantile Q43 (33 features) — Shadow ===
    "catboost_v9_q43_train1102_0125": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_q0.43_train20251102-20260125_20260216_192000.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-25",
        "backtest_mae": 4.954,
        "backtest_hit_rate_all": 52.13,
        "backtest_hit_rate_edge_3plus": 62.61,
        "backtest_n_edge_3plus": 115,
        "enabled": True,
        "feature_set": "v9",
        "description": "V9_Q43_FEB_RETRAIN — quantile alpha=0.43, ALL GATES PASSED",
    },
    # === V9 Quantile Q45 (33 features) — Shadow ===
    "catboost_v9_q45_train1102_0125": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_q0.45_train20251102-20260125_20260216_192001.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-25",
        "backtest_mae": 4.942,
        "backtest_hit_rate_all": 50.74,
        "backtest_hit_rate_edge_3plus": 62.89,
        "backtest_n_edge_3plus": 97,
        "enabled": True,
        "feature_set": "v9",
        "description": "V9_Q45_FEB_RETRAIN — quantile alpha=0.45, ALL GATES PASSED",
    },
    # === V12 No-Vegas Quantile Q43 (50 features) — Shadow (FIRST EVER) ===
    "catboost_v12_noveg_q43_train1102_0125": {
        "model_path": "gs://nba-props-platform-models/catboost/v12/monthly/catboost_v9_50f_noveg_train20251102-20260125_20260216_192040.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-25",
        "backtest_mae": 4.930,
        "backtest_hit_rate_all": 53.51,
        "backtest_hit_rate_edge_3plus": 61.6,
        "backtest_n_edge_3plus": 125,
        "enabled": True,
        "feature_set": "v12",
        "description": "V12_NOVEG_Q43_FEB — first V12+quantile, ALL GATES PASSED",
    },
    # === V12 No-Vegas Quantile Q45 (50 features) — Shadow (FIRST EVER) ===
    "catboost_v12_noveg_q45_train1102_0125": {
        "model_path": "gs://nba-props-platform-models/catboost/v12/monthly/catboost_v9_50f_noveg_train20251102-20260125_20260216_192044.cbm",
        "train_start": "2025-11-02",
        "train_end": "2026-01-25",
        "backtest_mae": 4.934,
        "backtest_hit_rate_all": 54.21,
        "backtest_hit_rate_edge_3plus": 61.22,
        "backtest_n_edge_3plus": 98,
        "enabled": True,
        "feature_set": "v12",
        "description": "V12_NOVEG_Q45_FEB — first V12+quantile, ALL GATES PASSED",
    },
    # === V9 Low-Vegas MAE (33 features, 0.25x vegas weight) — Shadow ===
    "catboost_v9_low_vegas_train0106_0205": {
        "model_path": "gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_wt_train20260106-20260205_20260218_231928.cbm",
        "train_start": "2026-01-06",
        "train_end": "2026-02-05",
        "backtest_mae": 5.06,
        "backtest_hit_rate_all": 53.8,
        "backtest_hit_rate_edge_3plus": 56.3,
        "backtest_n_edge_3plus": 48,
        "enabled": True,
        "feature_set": "v9",
        "description": "V9_LOW_VEGAS — 0.25x vegas weight, 5x more edge picks, UNDER 61.1%",
    },
}


def _get_bq_client():
    """Lazy-load BigQuery client for registry queries."""
    from google.cloud import bigquery
    return bigquery.Client(project='nba-props-platform')


def get_enabled_models_from_registry() -> List[dict]:
    """Load enabled shadow models from model_registry (BigQuery).

    Returns list of dicts with model metadata for each enabled non-production model.
    """
    try:
        bq = _get_bq_client()
        query = """
        SELECT
            model_id,
            gcs_path,
            model_family,
            feature_set,
            feature_count,
            loss_function,
            quantile_alpha,
            training_start_date,
            training_end_date,
            evaluation_mae,
            evaluation_hit_rate_edge_3plus AS evaluation_hr_edge_3plus,
            evaluation_n_edge_3plus,
            strengths_json
        FROM `nba-props-platform.nba_predictions.model_registry`
        WHERE enabled = TRUE
          AND is_production = FALSE
          AND status = 'active'
        ORDER BY model_family, training_end_date DESC
        """
        results = list(bq.query(query).result())
        models = []
        for r in results:
            models.append({
                'model_id': r.model_id,
                'model_path': r.gcs_path,
                'model_family': r.model_family,
                'feature_set': r.feature_set or 'v9',  # Default to v9 for legacy entries
                'feature_count': r.feature_count,
                'loss_function': r.loss_function,
                'quantile_alpha': r.quantile_alpha,
                'train_start': str(r.training_start_date) if r.training_start_date else None,
                'train_end': str(r.training_end_date) if r.training_end_date else None,
                'backtest_mae': r.evaluation_mae,
                'backtest_hit_rate_edge_3plus': r.evaluation_hr_edge_3plus,
                'backtest_n_edge_3plus': r.evaluation_n_edge_3plus,
                'strengths_json': r.strengths_json,
                'enabled': True,
                'source': 'registry',
            })
        logger.info(f"Loaded {len(models)} enabled models from model_registry")
        return models
    except Exception as e:
        logger.warning(f"Failed to query model_registry: {e}. Falling back to MONTHLY_MODELS dict.")
        return []


class CatBoostMonthly(CatBoostV8):
    """
    CatBoost Monthly Model - Feature-Set-Aware Shadow Model.

    Loads a monthly-retrained model from GCS. Supports both V9 (33-feature)
    and V12 (50-feature no-vegas) models based on the feature_set metadata.

    Args:
        model_id: Unique model identifier
        config: Dict with model_path, feature_set, train_start, train_end, etc.
            If None, looks up model_id in MONTHLY_MODELS dict (legacy).

    Session 273: Made feature-set-aware. V9 models use parent class (CatBoostV8)
    feature extraction. V12 models use name-based feature extraction from store.
    """

    def __init__(self, model_id: str, config: dict = None):
        if config is None:
            # Legacy: look up in MONTHLY_MODELS dict
            if model_id not in MONTHLY_MODELS:
                raise ValueError(
                    f"Unknown model_id: {model_id}. "
                    f"Available models: {list(MONTHLY_MODELS.keys())}"
                )
            config = MONTHLY_MODELS[model_id]

        self.model_id = model_id
        self.config = config
        self._feature_set = config.get('feature_set', 'v9')

        # Don't call super().__init__() - we need custom loading
        self.model = None
        self._load_attempts = 0
        self._last_load_error = None
        self._model_file_name = None
        self._model_sha256 = None

        # Load the model
        model_path = self.config["model_path"]
        self._load_model_from_path(model_path)

        logger.info(
            f"CatBoost Monthly model loaded: {model_id} "
            f"(feature_set={self._feature_set}, "
            f"trained {self.config.get('train_start')} to {self.config.get('train_end')}, "
            f"file={self._model_file_name}, sha256={self._model_sha256})"
        )

    def _load_model_from_path(self, model_path: str):
        """Load monthly model from local path or GCS."""
        import catboost as cb

        logger.info(f"Loading CatBoost monthly model from: {model_path}")

        if model_path.startswith("gs://"):
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

        Feature-set-aware: V9 models use parent class extraction (33 features),
        V12 models use name-based extraction (50 features, no vegas).
        """
        if self._feature_set in ('v12', 'v12_noveg'):
            # V12 path: extract 50 features by name from feature store
            return self._predict_v12(player_lookup, features, betting_line)
        else:
            # V9 path: use parent class (CatBoostV8) feature extraction
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
                    f"{self.config.get('train_start')} to {self.config.get('train_end')}"
                )
                result['model_type'] = 'monthly_retrain'
                result['training_mae'] = self.config.get('mae') or self.config.get('backtest_mae')

                if 'metadata' not in result:
                    result['metadata'] = {}
                result['metadata']['model_file_name'] = self._model_file_name
                result['metadata']['model_sha256'] = self._model_sha256
                result['metadata']['model_version'] = self.model_id
                result['metadata']['system_id'] = self.model_id

            return result

    def _predict_v12(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float] = None,
    ) -> Dict:
        """V12 prediction path: 50 features, no vegas, name-based extraction."""
        if self.model is None:
            raise ModelLoadError(f"Monthly model {self.model_id} is not loaded")

        # Build 50-feature vector from feature store by name
        feature_vector = self._prepare_v12_feature_vector(features)

        if feature_vector is None:
            return {
                'system_id': self.model_id,
                'model_version': self.model_id,
                'predicted_points': None,
                'confidence_score': 0,
                'recommendation': 'NO_PREDICTION',
                'model_type': 'monthly_retrain_v12',
                'prediction_error_code': 'V12_FEATURE_PREPARATION_FAILED',
                'metadata': {'model_file_name': self._model_file_name},
            }

        try:
            raw_prediction = float(self.model.predict(feature_vector)[0])
        except Exception as e:
            logger.error(f"Monthly V12 model {self.model_id} prediction failed: {e}", exc_info=True)
            return {
                'system_id': self.model_id,
                'model_version': self.model_id,
                'predicted_points': None,
                'confidence_score': 0,
                'recommendation': 'NO_PREDICTION',
                'model_type': 'monthly_retrain_v12',
                'prediction_error_code': 'MODEL_PREDICT_FAILED',
                'metadata': {'model_file_name': self._model_file_name},
            }

        predicted_points = max(0, min(60, raw_prediction))

        # Calculate confidence
        quality = features.get('feature_quality_score', 80)
        confidence = 75.0
        if quality >= 90:
            confidence += 10
        elif quality >= 80:
            confidence += 7
        elif quality >= 70:
            confidence += 5

        std_dev = features.get('points_std_last_10', 5)
        if std_dev < 4:
            confidence += 10
        elif std_dev < 6:
            confidence += 5

        # Generate recommendation
        # V12 quantile models use edge >= 4 (Session 284: HR +5.1pp at edge 4+)
        # V12 MAE models keep edge >= 3
        qa = self.config.get('quantile_alpha')
        min_edge = 4 if qa and qa != 'null' else 3

        recommendation = 'HOLD'
        if betting_line is not None:
            edge = predicted_points - betting_line
            if abs(edge) >= min_edge:
                recommendation = 'OVER' if edge > 0 else 'UNDER'

        warnings = []
        if features.get('early_season_flag'):
            warnings.append('EARLY_SEASON')
        if quality < 70:
            warnings.append('LOW_QUALITY_SCORE')

        return {
            'system_id': self.model_id,
            'model_version': self.model_id,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'model_type': 'monthly_retrain_v12',
            'feature_count': 50,
            'feature_version': features.get('feature_version'),
            'feature_quality_score': quality,
            'training_period': f"{self.config.get('train_start')} to {self.config.get('train_end')}",
            'training_mae': self.config.get('backtest_mae'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': None,
            'prediction_warnings': warnings if warnings else None,
            'raw_confidence_score': round(confidence / 100, 3),
            'calibration_method': 'none',
            'metadata': {
                'model_version': self.model_id,
                'system_id': self.model_id,
                'model_file_name': self._model_file_name,
                'model_sha256': self._model_sha256,
                'feature_set': self._feature_set,
            },
        }

    def _prepare_v12_feature_vector(self, features: Dict) -> Optional[np.ndarray]:
        """Build 50-feature vector for V12 models from feature store by name."""
        try:
            from shared.ml.feature_contract import FEATURE_DEFAULTS

            vector = []
            for name in V12_NOVEG_FEATURES:
                val = features.get(name)
                if val is not None:
                    vector.append(float(val))
                elif name in ('pct_paint', 'pct_mid_range', 'pct_three'):
                    vector.append(np.nan)
                elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
                    vector.append(float(FEATURE_DEFAULTS[name]))
                else:
                    vector.append(np.nan)

            vector = np.array(vector).reshape(1, -1)

            if vector.shape[1] != 50:
                logger.error(f"Monthly V12 feature vector has {vector.shape[1]} features, expected 50")
                return None

            return vector

        except Exception as e:
            logger.error(f"Error preparing V12 feature vector for {self.model_id}: {e}", exc_info=True)
            return None

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
        feature_count = 50 if self._feature_set in ('v12', 'v12_noveg') else 33
        return {
            "system_id": self.model_id,
            "model_version": self.model_id,
            "model_path": getattr(self, '_model_path', 'unknown'),
            "model_file_name": self._model_file_name,
            "model_sha256": self._model_sha256,
            "feature_set": self._feature_set,
            "feature_count": feature_count,
            "config": self.config,
            "source": self.config.get('source', 'dict'),
            "status": "loaded" if self.model is not None else "not_loaded",
        }


def get_enabled_monthly_models() -> List[CatBoostMonthly]:
    """
    Get all enabled monthly models.

    Priority: model_registry (BQ) first, then MONTHLY_MODELS dict as fallback.
    Registry models are deduplicated against dict models by model_id.

    Returns:
        List of CatBoostMonthly instances for all enabled models
    """
    enabled_models = []
    loaded_ids = set()

    # Try loading from model_registry first (Session 273)
    registry_models = get_enabled_models_from_registry()
    if registry_models:
        for config in registry_models:
            model_id = config['model_id']
            try:
                model = CatBoostMonthly(model_id, config=config)
                enabled_models.append(model)
                loaded_ids.add(model_id)
                logger.info(f"Registry model enabled: {model_id} (feature_set={config.get('feature_set', 'v9')})")
            except Exception as e:
                logger.error(
                    f"Failed to load registry model {model_id}: {e}",
                    exc_info=True
                )

    # Fallback: load from MONTHLY_MODELS dict (skip already-loaded IDs)
    for model_id, config in MONTHLY_MODELS.items():
        if model_id in loaded_ids:
            continue
        if config.get("enabled", False):
            try:
                model = CatBoostMonthly(model_id, config=config)
                enabled_models.append(model)
                loaded_ids.add(model_id)
                logger.info(f"Dict model enabled: {model_id}")
            except Exception as e:
                logger.error(
                    f"Failed to load dict model {model_id}: {e}",
                    exc_info=True
                )

    if not enabled_models:
        logger.warning("No monthly models enabled in registry or MONTHLY_MODELS config")
    else:
        registry_count = sum(1 for m in enabled_models if m.config.get('source') == 'registry')
        dict_count = len(enabled_models) - registry_count
        logger.info(
            f"Loaded {len(enabled_models)} monthly model(s) "
            f"({registry_count} from registry, {dict_count} from dict): "
            f"{[m.model_id for m in enabled_models]}"
        )

    return enabled_models


def get_monthly_model_by_id(model_id: str) -> CatBoostMonthly:
    """
    Get a specific monthly model by ID.

    Checks model_registry first, then MONTHLY_MODELS dict.
    """
    # Try registry
    registry_models = get_enabled_models_from_registry()
    for config in registry_models:
        if config['model_id'] == model_id:
            return CatBoostMonthly(model_id, config=config)

    # Try dict
    if model_id in MONTHLY_MODELS:
        if not MONTHLY_MODELS[model_id].get("enabled", False):
            raise ValueError(f"Model {model_id} is not enabled")
        return CatBoostMonthly(model_id)

    raise ValueError(
        f"Unknown model_id: {model_id}. "
        f"Not found in registry or MONTHLY_MODELS dict."
    )
