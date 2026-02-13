# predictions/worker/prediction_systems/catboost_v12.py

"""
CatBoost V12 Prediction System - Vegas-Free 50-Feature Model

Session 230: V12 deploys a no-vegas CatBoost model (54 features minus 4 vegas = 50 features).
Validated at 67% avg HR edge 3+ across 4 eval windows (+8.7pp over V9).

Key Differences from V9:
- No vegas features (25-28 excluded) -- predictions are independent of market
- 50 features (15 new: fatigue, trends, usage, streaks, structural changes)
- All 50 features read from ml_feature_store_v2 by name (no augmentation queries)
- MAE loss function (not quantile)

Session 230 update: Removed V12FeatureAugmenter. Features 39-53 are now computed
in Phase 4 (ml_feature_store_processor) and stored in the feature store. V12
reads all features by name from the store dict, same pattern as V8/V9.

Usage:
    from predictions.worker.prediction_systems.catboost_v12 import CatBoostV12

    system = CatBoostV12()
    result = system.predict(player_lookup, features, betting_line)
"""

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from predictions.worker.prediction_systems.catboost_v8 import ModelLoadError

logger = logging.getLogger(__name__)

MODEL_BUCKET = "nba-props-platform-models"
MODEL_PREFIX = "catboost/v12"
DEFAULT_MODEL_GCS = f"gs://{MODEL_BUCKET}/{MODEL_PREFIX}/catboost_v12_50f_noveg_train20251102-20260131.cbm"

# V12 No-Vegas feature order (50 features = V12 minus indices 25-28)
# Must match training exactly.
V12_NOVEG_FEATURES = [
    # 0-4: Recent Performance
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",
    # 5-8: Composite Factors
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",
    # 9-12: Derived Factors
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",
    # 13-17: Matchup Context
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",
    # 18-21: Shot Zones
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",
    # 22-24: Team Context
    "team_pace",
    "team_off_rating",
    "team_win_pct",
    # (vegas 25-28 SKIPPED)
    # 29-30: Opponent History
    "avg_points_vs_opponent",
    "games_vs_opponent",
    # 31-32: Minutes/Efficiency
    "minutes_avg_last_10",
    "ppm_avg_last_10",
    # 33: DNP Risk
    "dnp_rate",
    # 34-36: Player Trajectory
    "pts_slope_10g",
    "pts_vs_season_zscore",
    "breakout_flag",
    # 37-38: V11
    "star_teammates_out",
    "game_total_line",
    # 39-53: V12 features (now from feature store)
    "days_rest",
    "minutes_load_last_7d",
    "spread_magnitude",
    "implied_team_total",
    "points_avg_last_3",
    "scoring_trend_slope",
    "deviation_from_avg_last3",
    "consecutive_games_below_avg",
    "teammate_usage_available",
    "usage_rate_last_5",
    "games_since_structural_change",
    "multi_book_line_std",
    "prop_over_streak",
    "prop_under_streak",
    "line_vs_season_avg",
]

assert len(V12_NOVEG_FEATURES) == 50, f"Expected 50 features, got {len(V12_NOVEG_FEATURES)}"


def _compute_file_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a model file for integrity verification."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:16]


class CatBoostV12:
    """
    CatBoost V12 - Vegas-Free 50-Feature Model

    Independent of market lines, generates predictions using player performance,
    matchup context, and V12 features. All 50 features read by name from the
    feature store (same pattern as V8/V9).
    """

    SYSTEM_ID = "catboost_v12"
    FEATURE_COUNT = 50

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self._model_path = None
        self._model_file_name = None
        self._model_sha256 = None
        self._model_version = None

        if model_path:
            self._load_model_from_path(model_path)
        else:
            self._load_model_from_default_location()

    @property
    def system_id(self) -> str:
        return self.SYSTEM_ID

    @property
    def model_version(self) -> str:
        return self._model_version or "v12_unknown"

    def _load_model_from_default_location(self):
        """Load V12 model: env var first, then local, then default GCS."""
        import catboost as cb

        # Priority 1: CATBOOST_V12_MODEL_PATH env var
        env_path = os.environ.get('CATBOOST_V12_MODEL_PATH')
        if env_path:
            logger.info(f"Loading CatBoost V12 from env var: {env_path}")
            self._load_model_from_path(env_path)
            return

        # Priority 2: Local models directory
        models_dir = Path(__file__).parent.parent.parent.parent / "models"
        model_files = list(models_dir.glob("catboost_v9_50f_noveg*.cbm")) + \
                      list(models_dir.glob("catboost_v12*.cbm"))

        if model_files:
            model_path = sorted(model_files)[-1]
            logger.info(f"Loading CatBoost V12 from local: {model_path}")
            self.model = cb.CatBoostRegressor()
            self.model.load_model(str(model_path))
            self._model_path = str(model_path)
            self._model_file_name = model_path.name
            self._model_sha256 = _compute_file_sha256(str(model_path))
            self._model_version = f"v12_{model_path.stem.split('train')[-1]}" if 'train' in model_path.stem else "v12_local"
            logger.info(
                f"CatBoost V12 loaded: file={self._model_file_name} "
                f"version={self._model_version} sha256={self._model_sha256}"
            )
            return

        # Priority 3: Default GCS path
        logger.info(f"No env var or local V12 model, loading from default GCS: {DEFAULT_MODEL_GCS}")
        self._load_model_from_path(DEFAULT_MODEL_GCS)

    def _load_model_from_path(self, model_path: str):
        """Load V12 model from explicit path (local or GCS)."""
        import catboost as cb

        logger.info(f"Loading CatBoost V12 from: {model_path}")

        if model_path.startswith("gs://"):
            from shared.clients import get_storage_client
            parts = model_path.replace("gs://", "").split("/", 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = get_storage_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            local_path = "/tmp/catboost_v12.cbm"
            blob.download_to_filename(local_path)
            logger.info(f"Downloaded V12 model from GCS to {local_path}")

            self.model = cb.CatBoostRegressor()
            self.model.load_model(local_path)
            self._model_file_name = Path(blob_path).name
            self._model_sha256 = _compute_file_sha256(local_path)
        else:
            self.model = cb.CatBoostRegressor()
            self.model.load_model(model_path)
            self._model_file_name = Path(model_path).name
            self._model_sha256 = _compute_file_sha256(model_path)

        self._model_path = model_path
        # Derive version from filename
        stem = Path(self._model_file_name).stem
        if 'train' in stem:
            self._model_version = f"v12_{stem.split('train')[-1]}"
        else:
            self._model_version = f"v12_{stem}"

        logger.info(
            f"CatBoost V12 loaded: file={self._model_file_name} "
            f"version={self._model_version} sha256={self._model_sha256}"
        )

    def predict(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float] = None,
        **kwargs,
    ) -> Dict:
        """
        Generate prediction using CatBoost V12 model.

        All 50 features are read by name from the feature store dict.
        No augmentation queries needed -- features 39-53 are now in the store.

        Args:
            player_lookup: Player identifier
            features: Feature store features dict (with feature arrays)
            betting_line: Current over/under line

        Returns:
            Dict with predicted_points, confidence_score, recommendation, metadata
        """
        if self.model is None:
            raise ModelLoadError("CatBoost V12 model is not loaded")

        # Build 50-feature vector from feature store by name
        feature_vector = self._prepare_feature_vector(features)

        if feature_vector is None:
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Make prediction
        try:
            raw_prediction = float(self.model.predict(feature_vector)[0])
        except Exception as e:
            logger.error(f"CatBoost V12 prediction failed: {e}", exc_info=True)
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Clamp to reasonable range
        predicted_points = max(0, min(60, raw_prediction))

        # Calculate confidence
        confidence = self._calculate_confidence(features)

        # Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_points, betting_line, confidence
        )

        # Warnings
        warnings = []
        if features.get('early_season_flag'):
            warnings.append('EARLY_SEASON')
        if features.get('feature_quality_score', 100) < 70:
            warnings.append('LOW_QUALITY_SCORE')

        return {
            'system_id': self.SYSTEM_ID,
            'model_version': self._model_version,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'model_type': 'catboost_v12_noveg',
            'feature_count': self.FEATURE_COUNT,
            'feature_version': features.get('feature_version'),
            'feature_quality_score': features.get('feature_quality_score'),
            'feature_data_source': features.get('data_source'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': None,
            'prediction_warnings': warnings if warnings else None,
            'raw_confidence_score': round(confidence / 100, 3),
            'calibration_method': 'none',
            'metadata': {
                'model_version': self._model_version,
                'system_id': self.SYSTEM_ID,
                'model_file_name': self._model_file_name,
                'model_sha256': self._model_sha256,
            },
        }

    def _prepare_feature_vector(self, features: Dict) -> Optional[np.ndarray]:
        """Build 50-feature vector from feature store by name.

        All features (including V12 39-53) are now in the feature store.
        Simply look up each feature name from the features dict.
        """
        try:
            from shared.ml.feature_contract import FEATURE_DEFAULTS

            vector = []
            for name in V12_NOVEG_FEATURES:
                val = features.get(name)
                if val is not None:
                    vector.append(float(val))
                elif name in ('pct_paint', 'pct_mid_range', 'pct_three'):
                    vector.append(np.nan)  # CatBoost handles NaN natively
                elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
                    vector.append(float(FEATURE_DEFAULTS[name]))
                else:
                    vector.append(np.nan)

            vector = np.array(vector).reshape(1, -1)

            if vector.shape[1] != self.FEATURE_COUNT:
                logger.error(f"V12 feature vector has {vector.shape[1]} features, expected {self.FEATURE_COUNT}")
                return None

            return vector

        except Exception as e:
            logger.error(f"Error preparing V12 feature vector: {e}", exc_info=True)
            return None

    def _calculate_confidence(self, features: Dict) -> float:
        """Calculate confidence score for V12 prediction."""
        confidence = 75.0

        quality = features.get('feature_quality_score', 80)
        if quality >= 90:
            confidence += 10
        elif quality >= 80:
            confidence += 7
        elif quality >= 70:
            confidence += 5
        else:
            confidence += 2

        std_dev = features.get('points_std_last_10', 5)
        if std_dev < 4:
            confidence += 10
        elif std_dev < 6:
            confidence += 7
        elif std_dev < 8:
            confidence += 5
        else:
            confidence += 2

        return max(0, min(100, confidence))

    def _generate_recommendation(
        self,
        predicted_points: float,
        betting_line: Optional[float],
        confidence: float,
    ) -> str:
        """Generate betting recommendation."""
        if betting_line is None:
            return 'NO_LINE'
        if confidence < 60:
            return 'PASS'

        edge = predicted_points - betting_line
        min_edge = 1.0

        if edge >= min_edge:
            return 'OVER'
        elif edge <= -min_edge:
            return 'UNDER'
        else:
            return 'PASS'

    def _fallback_prediction(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float],
    ) -> Dict:
        """Fallback for feature/prediction failures."""
        logger.warning(f"V12 FALLBACK for {player_lookup}")

        season_avg = features.get('points_avg_season', 10.0)
        last_5 = features.get('points_avg_last_5', season_avg)
        last_10 = features.get('points_avg_last_10', season_avg)
        predicted = 0.4 * last_5 + 0.35 * last_10 + 0.25 * season_avg

        return {
            'system_id': self.SYSTEM_ID,
            'model_version': self._model_version or 'v12_unknown',
            'predicted_points': round(predicted, 2),
            'confidence_score': 50.0,
            'recommendation': 'PASS',
            'model_type': 'fallback',
            'feature_count': self.FEATURE_COUNT,
            'feature_version': features.get('feature_version'),
            'feature_quality_score': features.get('feature_quality_score'),
            'feature_data_source': features.get('data_source'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': 'V12_FALLBACK',
            'prediction_warnings': ['FALLBACK_USED'],
            'raw_confidence_score': 0.5,
            'calibration_method': 'none',
            'metadata': {
                'model_version': self._model_version or 'v12_unknown',
                'system_id': self.SYSTEM_ID,
                'model_file_name': self._model_file_name,
                'model_sha256': self._model_sha256,
            },
        }

    def get_model_info(self) -> Dict:
        """Return V12 model information for health checks."""
        return {
            "system_id": self.SYSTEM_ID,
            "model_version": self._model_version,
            "model_path": self._model_path or 'unknown',
            "model_file_name": self._model_file_name,
            "model_sha256": self._model_sha256,
            "feature_count": self.FEATURE_COUNT,
            "status": "loaded" if self.model is not None else "not_loaded",
        }
