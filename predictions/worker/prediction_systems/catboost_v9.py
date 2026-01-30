# predictions/worker/prediction_systems/catboost_v9.py

"""
CatBoost V9 Prediction System (Shadow Mode) - 2026-01-30

V9 extends V8 with:
1. Recency-weighted training (half-life=180 days) - recent games matter more
2. Trajectory features (3 new) - capture rising/declining player trends

New Features (34-36):
- pts_slope_10g: Linear regression slope of points over last 10 games
- pts_vs_season_zscore: Z-score of L5 avg vs season average
- breakout_flag: 1.0 if L5 > season_avg + 1.5*std

Why Trajectory Features?
- NBA dynamics shift mid-season (stars trending up, bench players down)
- V8's static averages miss these trends
- Trajectory features adapt to current player form

Performance Target: MAE < 3.40 (V8 baseline)

Usage:
    from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9
    system = CatBoostV9()
    result = system.predict(player_lookup, features, betting_line)
"""

from typing import Dict, Optional, List, Set
from datetime import date
from enum import Enum
import numpy as np
import logging
import json
from pathlib import Path

from shared.utils.external_service_circuit_breaker import (
    get_service_circuit_breaker,
    CircuitBreakerError,
)
from shared.utils.prometheus_metrics import Counter, Histogram

logger = logging.getLogger(__name__)


# =============================================================================
# Prometheus Metrics
# =============================================================================

catboost_v9_feature_fallback_total = Counter(
    name='catboost_v9_feature_fallback_total',
    help_text='Count of CatBoost V9 predictions using fallback values by feature and severity',
    label_names=['feature_name', 'severity']
)

catboost_v9_prediction_points = Histogram(
    name='catboost_v9_prediction_points',
    help_text='Distribution of CatBoost V9 predicted points',
    label_names=[],
    buckets=[5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0]
)

catboost_v9_extreme_prediction_total = Counter(
    name='catboost_v9_extreme_prediction_total',
    help_text='Count of CatBoost V9 predictions clamped at boundaries (0 or 60)',
    label_names=['boundary']
)


# =============================================================================
# Fallback Severity Classification
# =============================================================================

class FallbackSeverity(Enum):
    NONE = "none"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


CRITICAL_FEATURES: Set[str] = {
    'vegas_points_line',
    'has_vegas_line',
    'ppm_avg_last_10',
}

MAJOR_FEATURES: Set[str] = {
    'avg_points_vs_opponent',
    'minutes_avg_last_10',
}


def classify_fallback_severity(used_defaults: List[str]) -> FallbackSeverity:
    if not used_defaults:
        return FallbackSeverity.NONE
    used_defaults_set = set(used_defaults)
    if used_defaults_set & CRITICAL_FEATURES:
        return FallbackSeverity.CRITICAL
    elif used_defaults_set & MAJOR_FEATURES:
        return FallbackSeverity.MAJOR
    elif used_defaults:
        return FallbackSeverity.MINOR
    return FallbackSeverity.NONE


def record_prediction_metrics(raw_prediction: float, clamped_prediction: float) -> None:
    catboost_v9_prediction_points.observe(clamped_prediction)
    if raw_prediction >= 60:
        catboost_v9_extreme_prediction_total.inc(labels={'boundary': 'high_60'})
    elif raw_prediction <= 0:
        catboost_v9_extreme_prediction_total.inc(labels={'boundary': 'low_0'})


# =============================================================================
# V9 Feature Configuration
# =============================================================================

# V9 Features: V8's 33 features + 3 trajectory features = 36 total
V9_FEATURES = [
    # =========== V8 BASE FEATURES (0-32) ===========
    # Recent Performance (0-4)
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",
    # Composite Factors (5-8)
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",
    # Derived Factors (9-12)
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",
    # Matchup Context (13-17)
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",
    # Shot Zones (18-21)
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",
    # Team Context (22-24)
    "team_pace",
    "team_off_rating",
    "team_win_pct",
    # Vegas features (25-28)
    "vegas_points_line",
    "vegas_opening_line",
    "vegas_line_move",
    "has_vegas_line",
    # Opponent history (29-30)
    "avg_points_vs_opponent",
    "games_vs_opponent",
    # Minutes/PPM history (31-32)
    "minutes_avg_last_10",
    "ppm_avg_last_10",

    # =========== V9 NEW: TRAJECTORY FEATURES (33-35) ===========
    # These capture player momentum and trend direction
    "pts_slope_10g",         # Linear regression slope over L10 (points/game trend)
    "pts_vs_season_zscore",  # How far current form deviates from baseline
    "breakout_flag",         # Binary flag for exceptional recent performance
]

# Feature count
V9_FEATURE_COUNT = len(V9_FEATURES)  # 36


class CatBoostV9:
    """
    CatBoost V9 prediction system with trajectory features and recency-weighted training.

    Key improvements over V8:
    1. Trajectory features (33-35): Capture player momentum
       - pts_slope_10g: Are they scoring more or less each game?
       - pts_vs_season_zscore: How hot/cold vs their baseline?
       - breakout_flag: Is this an exceptional stretch?

    2. Recency-weighted training: Recent games weighted higher
       - Half-life of 180 days (6 months)
       - Adapts to mid-season dynamics shifts

    Shadow mode: Runs alongside V8 for A/B comparison.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        use_local: bool = True
    ):
        """
        Initialize CatBoost V9 system.

        Args:
            model_path: Path to CatBoost model file (local or GCS)
            use_local: If True, load from local models/ directory.
                       If CATBOOST_V9_MODEL_PATH env var is set, uses that instead.
        """
        import os

        self.system_id = 'catboost_v9'
        self.model_version = 'v9'
        self.model = None
        self.metadata = None
        self.feature_count = V9_FEATURE_COUNT

        # Check for GCS path in environment (production)
        gcs_path = os.environ.get('CATBOOST_V9_MODEL_PATH')

        # Load model - priority: explicit path > env var > local
        if model_path:
            self._load_model_from_path(model_path)
        elif gcs_path:
            logger.info(f"Loading CatBoost v9 from env var: {gcs_path}")
            self._load_model_from_path(gcs_path)
        elif use_local:
            self._load_local_model()

        # Log final model load status
        if self.model is not None:
            logger.info(
                f"✓ CatBoost V9 model loaded successfully. "
                f"Ready to generate predictions with {self.feature_count} features "
                f"(includes trajectory features)."
            )
        else:
            logger.warning(
                f"⚠ CatBoost V9 model not loaded. Predictions will use fallback. "
                f"Check: 1) CATBOOST_V9_MODEL_PATH env var, 2) local model file."
            )

    def _load_local_model(self):
        """Load model from local models/ directory."""
        try:
            import catboost as cb

            models_dir = Path(__file__).parent.parent.parent.parent / "models"

            # Look for v9 models with various naming patterns
            model_patterns = [
                "catboost_v9_*features_*.cbm",
                "catboost_v9_*.cbm",
            ]

            model_files = []
            for pattern in model_patterns:
                model_files.extend(models_dir.glob(pattern))

            if not model_files:
                logger.info("No CatBoost v9 model found locally, will use fallback")
                return

            # Use the most recent model
            model_path = sorted(model_files)[-1]
            logger.info(f"Loading CatBoost v9 model from {model_path}")

            self.model = cb.CatBoostRegressor()
            self.model.load_model(str(model_path))

            # Detect feature count from model
            try:
                self.feature_count = self.model.feature_count_
                logger.info(f"Model has {self.feature_count} features")
            except:
                pass

            # Load metadata if available
            metadata_patterns = [
                model_path.with_suffix('').with_suffix('.json'),
                model_path.parent / f"{model_path.stem}_metadata.json",
            ]
            for meta_path in metadata_patterns:
                if meta_path.exists():
                    with open(meta_path) as f:
                        self.metadata = json.load(f)
                    break

            logger.info(f"Loaded CatBoost v9 model successfully")

        except ImportError:
            logger.error("CatBoost not installed. Run: pip install catboost", exc_info=True)
        except Exception as e:
            logger.error(f"Error loading CatBoost v9 model: {e}", exc_info=True)

    def _load_model_from_path(self, model_path: str):
        """Load model from specified path (local or GCS)."""
        try:
            import catboost as cb

            if model_path.startswith("gs://"):
                from google.cloud import storage

                parts = model_path.replace("gs://", "").split("/", 1)
                bucket_name, blob_path = parts[0], parts[1]

                gcs_cb = get_service_circuit_breaker("gcs_model_loading")

                try:
                    def download_model():
                        from shared.clients import get_storage_client
                        client = get_storage_client()
                        bucket = client.bucket(bucket_name)
                        blob = bucket.blob(blob_path)
                        local_path = "/tmp/catboost_v9.cbm"
                        blob.download_to_filename(local_path)
                        return local_path

                    model_path = gcs_cb.call(download_model)
                    logger.info(f"GCS model download successful for catboost_v9")

                except CircuitBreakerError as e:
                    logger.error(
                        f"Circuit breaker OPEN for GCS model loading: {e}. "
                        f"CatBoost v9 will use fallback predictions.",
                        exc_info=True
                    )
                    return

            self.model = cb.CatBoostRegressor()
            self.model.load_model(model_path)

            # Detect feature count from model
            try:
                self.feature_count = self.model.feature_count_
            except:
                pass

            logger.info(f"Loaded CatBoost v9 model from {model_path}")

        except Exception as e:
            logger.error(f"Error loading model from {model_path}: {e}", exc_info=True)

    def predict(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float] = None,
        vegas_line: Optional[float] = None,
        vegas_opening: Optional[float] = None,
        opponent_avg: Optional[float] = None,
        games_vs_opponent: int = 0,
        minutes_avg_last_10: Optional[float] = None,
        ppm_avg_last_10: Optional[float] = None,
    ) -> Dict:
        """
        Generate prediction using CatBoost v9 model.

        Args:
            player_lookup: Player identifier
            features: Feature dictionary from ml_feature_store_v2
            betting_line: Current over/under line for recommendation
            vegas_line: Vegas consensus points line
            vegas_opening: Vegas opening line
            opponent_avg: Player's avg points vs this opponent
            games_vs_opponent: Number of games vs this opponent
            minutes_avg_last_10: Avg minutes last 10 games
            ppm_avg_last_10: Points per minute last 10 games

        Returns:
            dict: Prediction with metadata
        """
        if self.model is None:
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Prepare feature vector (handles variable feature counts)
        feature_vector = self._prepare_feature_vector(
            features=features,
            vegas_line=vegas_line,
            vegas_opening=vegas_opening,
            opponent_avg=opponent_avg,
            games_vs_opponent=games_vs_opponent,
            minutes_avg_last_10=minutes_avg_last_10,
            ppm_avg_last_10=ppm_avg_last_10,
        )

        if feature_vector is None:
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Make prediction
        try:
            raw_prediction = float(self.model.predict(feature_vector)[0])
        except Exception as e:
            logger.error(f"CatBoost v9 prediction failed: {e}", exc_info=True)
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Warn on extreme predictions
        if raw_prediction >= 55 or raw_prediction <= 5:
            logger.warning(
                "extreme_prediction_detected",
                extra={
                    "player_lookup": player_lookup,
                    "system_id": self.system_id,
                    "raw_prediction": round(raw_prediction, 2),
                    "vegas_line": features.get('vegas_points_line'),
                    "season_avg": features.get('points_avg_season'),
                }
            )

        # Clamp to reasonable range
        predicted_points = max(0, min(60, raw_prediction))

        # Record Prometheus metrics
        record_prediction_metrics(raw_prediction, predicted_points)

        # Calculate confidence
        confidence = self._calculate_confidence(features, feature_vector)

        # Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_points, betting_line, confidence
        )

        logger.info(
            "prediction_generated",
            extra={
                "player_lookup": player_lookup,
                "system_id": self.system_id,
                "model_type": "real",
                "predicted_points": round(predicted_points, 2),
                "confidence": round(confidence, 2),
                "recommendation": recommendation,
                "feature_count": self.feature_count,
            }
        )

        return {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'model_type': 'catboost_v9_real',
            'feature_count': self.feature_count,
        }

    def _prepare_feature_vector(
        self,
        features: Dict,
        vegas_line: Optional[float],
        vegas_opening: Optional[float],
        opponent_avg: Optional[float],
        games_vs_opponent: int,
        minutes_avg_last_10: Optional[float],
        ppm_avg_last_10: Optional[float],
    ) -> Optional[np.ndarray]:
        """
        Prepare feature vector matching model's expected feature count.

        Handles both 33-feature (V8 compatible) and 36-feature (full V9) models.
        """
        try:
            season_avg = features.get('points_avg_season', 10.0)

            # Get features array from feature store if available
            features_array = features.get('features_array', features.get('features', []))

            # Build base 33 features (V8 compatible)
            base_features = [
                # 0-4: Recent Performance
                features.get('points_avg_last_5', season_avg),
                features.get('points_avg_last_10', season_avg),
                features.get('points_avg_season', season_avg),
                features.get('points_std_last_10', 5.0),
                features.get('games_in_last_7_days', 2),
                # 5-8: Composite Factors
                features.get('fatigue_score', 70),
                features.get('shot_zone_mismatch_score', 0),
                features.get('pace_score', 0),
                features.get('usage_spike_score', 0),
                # 9-12: Derived Factors
                features.get('rest_advantage', 0),
                features.get('injury_risk', 0),
                features.get('recent_trend', 0),
                features.get('minutes_change', 0),
                # 13-14: Matchup Context
                features.get('opponent_def_rating', 112),
                features.get('opponent_pace', 100),
                # 15-17: Game Context
                features.get('home_away', 0),
                features.get('back_to_back', 0),
                features.get('playoff_game', 0),
                # 18-21: Shot Zones (NULLABLE)
                features.get('pct_paint') if features.get('pct_paint') is not None else np.nan,
                features.get('pct_mid_range') if features.get('pct_mid_range') is not None else np.nan,
                features.get('pct_three') if features.get('pct_three') is not None else np.nan,
                features.get('pct_free_throw', 0.15),
                # 22-24: Team Context
                features.get('team_pace', 100),
                features.get('team_off_rating', 112),
                features.get('team_win_pct', 0.5),
                # 25-28: Vegas features (NULLABLE)
                vegas_line if vegas_line is not None else features.get('vegas_points_line') if features.get('vegas_points_line') is not None else np.nan,
                vegas_opening if vegas_opening is not None else features.get('vegas_opening_line') if features.get('vegas_opening_line') is not None else np.nan,
                (vegas_line - vegas_opening) if vegas_line and vegas_opening else features.get('vegas_line_move') if features.get('vegas_line_move') is not None else np.nan,
                1.0 if (vegas_line is not None or features.get('vegas_points_line') is not None) else 0.0,
                # 29-30: Opponent history
                opponent_avg if opponent_avg is not None else features.get('avg_points_vs_opponent', season_avg),
                float(games_vs_opponent) if games_vs_opponent else features.get('games_vs_opponent', 0.0),
                # 31-32: Minutes/PPM
                minutes_avg_last_10 if minutes_avg_last_10 is not None else features.get('minutes_avg_last_10', 25),
                ppm_avg_last_10 if ppm_avg_last_10 is not None else features.get('ppm_avg_last_10', 0.4),
            ]

            # Add trajectory features if model expects them
            if self.feature_count > 33:
                # Feature 33: pts_slope_10g
                pts_slope = features.get('pts_slope_10g', 0.0)
                if pts_slope is None:
                    pts_slope = self._calculate_pts_slope(features)
                base_features.append(pts_slope)

            if self.feature_count > 34:
                # Feature 34: pts_vs_season_zscore
                zscore = features.get('pts_vs_season_zscore', 0.0)
                if zscore is None:
                    zscore = self._calculate_zscore(features)
                base_features.append(zscore)

            if self.feature_count > 35:
                # Feature 35: breakout_flag
                breakout = features.get('breakout_flag', 0.0)
                if breakout is None:
                    breakout = self._calculate_breakout_flag(features)
                base_features.append(breakout)

            vector = np.array(base_features).reshape(1, -1)

            # Validate - allow NaN for nullable features only
            nullable_indices = list(range(18, 21)) + list(range(25, 28))  # Shot zones + Vegas
            non_nullable_mask = np.ones(vector.shape[1], dtype=bool)
            for idx in nullable_indices:
                if idx < vector.shape[1]:
                    non_nullable_mask[idx] = False

            if np.any(np.isnan(vector[:, non_nullable_mask])) or np.any(np.isinf(vector)):
                logger.warning("Feature vector contains NaN/Inf in non-nullable features")
                return None

            return vector

        except Exception as e:
            logger.error(f"Error preparing v9 feature vector: {e}", exc_info=True)
            return None

    def _calculate_pts_slope(self, features: Dict) -> float:
        """Calculate points slope from available features."""
        # Simple approximation: (L5 - L10) / 5 games
        l5 = features.get('points_avg_last_5', 0)
        l10 = features.get('points_avg_last_10', 0)
        if l5 and l10:
            return (l5 - l10) / 5.0
        return 0.0

    def _calculate_zscore(self, features: Dict) -> float:
        """Calculate z-score from available features."""
        l5 = features.get('points_avg_last_5')
        season = features.get('points_avg_season')
        std = features.get('points_std_last_10')
        if l5 and season and std and std > 0:
            z = (l5 - season) / std
            return max(-3.0, min(3.0, z))
        return 0.0

    def _calculate_breakout_flag(self, features: Dict) -> float:
        """Calculate breakout flag from available features."""
        l5 = features.get('points_avg_last_5')
        season = features.get('points_avg_season')
        std = features.get('points_std_last_10')
        if l5 and season and std:
            threshold = season + 1.5 * std
            return 1.0 if l5 > threshold else 0.0
        return 0.0

    def _calculate_confidence(self, features: Dict, feature_vector: np.ndarray) -> float:
        """Calculate confidence score."""
        confidence = 75.0  # Base confidence

        # Data quality adjustment
        quality = features.get('feature_quality_score', 80)
        if quality >= 90:
            confidence += 10
        elif quality >= 80:
            confidence += 7
        elif quality >= 70:
            confidence += 5
        else:
            confidence += 2

        # Consistency adjustment
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
        confidence: float
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
        betting_line: Optional[float]
    ) -> Dict:
        """Fallback when model not available."""
        logger.warning(
            f"FALLBACK_PREDICTION: CatBoost V9 model not loaded for {player_lookup}. "
            f"Check CATBOOST_V9_MODEL_PATH env var."
        )

        season_avg = features.get('points_avg_season', 10.0)
        last_5 = features.get('points_avg_last_5', season_avg)
        last_10 = features.get('points_avg_last_10', season_avg)

        predicted = 0.4 * last_5 + 0.35 * last_10 + 0.25 * season_avg

        return {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'predicted_points': round(predicted, 2),
            'confidence_score': 50.0,
            'recommendation': 'PASS',
            'model_type': 'fallback',
            'error': 'Model not loaded, using fallback',
        }

    def get_model_info(self) -> Dict:
        """Get model information."""
        info = {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'model_loaded': self.model is not None,
            'feature_count': self.feature_count,
            'features': V9_FEATURES[:self.feature_count],
            'new_features': ['pts_slope_10g', 'pts_vs_season_zscore', 'breakout_flag'],
            'training_method': 'recency_weighted',
        }

        if self.metadata:
            info['training_mae'] = self.metadata.get('training_results', {}).get('validation_mae')
            info['recency_weighting'] = self.metadata.get('recency_weighting', {})

        return info


# Factory functions
def load_catboost_v9_system() -> CatBoostV9:
    """Load CatBoost V9 system with local model."""
    return CatBoostV9(use_local=True)


def load_catboost_v9_from_gcs(gcs_path: str) -> CatBoostV9:
    """Load CatBoost V9 system from GCS."""
    return CatBoostV9(model_path=gcs_path, use_local=False)
