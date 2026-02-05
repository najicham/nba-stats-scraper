# predictions/worker/prediction_systems/breakout_classifier_v1.py

"""
Breakout Classifier V1 - Shadow Mode Integration

Session 128 (2026-02-05): Role player breakout risk classifier.

Purpose:
- Identify role players (PPG 6-20) at risk of breakout games
- Breakout defined as scoring >= 1.75x their season average
- Use to filter OUT high-risk breakout candidates from UNDER bets

Model Performance (EXP_COMBINED_BEST):
- Optimal threshold: 0.769 for 60% precision
- Training: Nov 2025 - Jan 2026 (current season)
- Features: 8 features capturing volatility, cold streaks, and matchup context

Shadow Mode Integration:
- This classifier runs in SHADOW MODE alongside main predictions
- Does NOT modify predictions directly
- Returns risk metadata that can be logged and analyzed
- Future: Use to adjust confidence or filter recommendations

Usage:
    from predictions.worker.prediction_systems.breakout_classifier_v1 import BreakoutClassifierV1

    classifier = BreakoutClassifierV1()
    result = classifier.classify(
        player_lookup='john-collins',
        features=features_dict,
        points_avg_season=12.5,
    )
    # result = {
    #     'risk_score': 0.82,
    #     'risk_category': 'HIGH_RISK',
    #     'is_role_player': True,
    #     'confidence': 0.65,
    #     'metadata': {...}
    # }
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Any

import numpy as np

logger = logging.getLogger(__name__)


class BreakoutRiskCategory(Enum):
    """Risk category for breakout classification."""
    HIGH_RISK = "HIGH_RISK"       # Above optimal threshold (0.769)
    MEDIUM_RISK = "MEDIUM_RISK"   # Between 0.5 and threshold
    LOW_RISK = "LOW_RISK"         # Below 0.5 or not a role player


@dataclass
class BreakoutClassificationResult:
    """Result from breakout risk classification."""
    risk_score: float                 # Raw probability 0-1
    risk_category: BreakoutRiskCategory  # HIGH/MEDIUM/LOW
    is_role_player: bool              # True if PPG 6-20
    confidence: float                 # Model confidence 0-1
    skip_reason: Optional[str]        # Why classification was skipped (if applicable)
    metadata: Dict[str, Any]          # Additional metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'risk_score': round(self.risk_score, 4) if self.risk_score is not None else None,
            'risk_category': self.risk_category.value,
            'is_role_player': self.is_role_player,
            'confidence': round(self.confidence, 4) if self.confidence is not None else None,
            'skip_reason': self.skip_reason,
            'metadata': self.metadata,
        }


class ModelLoadError(Exception):
    """Raised when classifier model fails to load."""

    def __init__(self, message: str, attempts: int = 0, last_error: Exception = None):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(message)

    def __str__(self):
        base = super().__str__()
        if self.attempts > 0:
            base += f" (after {self.attempts} attempts)"
        if self.last_error:
            base += f" Last error: {self.last_error}"
        return base


# Feature names in exact order required by the model
BREAKOUT_FEATURES = [
    "cv_ratio",               # Coefficient of variation ratio (recent vs season)
    "cold_streak_indicator",  # Binary: 1 if below season avg last 3 games
    "pts_vs_season_zscore",   # Z-score: how far below season avg
    "opponent_def_rating",    # Opponent defensive efficiency
    "explosion_ratio",        # Ratio of max game / avg (ceiling capacity)
    "days_since_breakout",    # Days since last breakout game
    "minutes_avg_last_10",    # Recent playing time
    "points_avg_season",      # Season scoring average
]


class BreakoutClassifierV1:
    """
    Breakout Risk Classifier V1 - Shadow Mode

    Predicts probability of role player having a breakout game (>= 1.75x avg).
    Uses CatBoost classifier trained on current season data.

    Design Principles:
    - Graceful degradation: Returns LOW_RISK if model fails to load
    - Shadow mode: Does not block main prediction flow
    - Explicit skip reasons: Always explains why classification was skipped
    - Model versioning: Tracks model file for reproducibility
    """

    # Model configuration
    SYSTEM_ID = "breakout_classifier_v1"
    MODEL_VERSION = "v1_combined_best"

    # Thresholds from experiment analysis
    OPTIMAL_THRESHOLD = 0.769   # 60% precision threshold
    MEDIUM_THRESHOLD = 0.5      # Boundary between LOW and MEDIUM

    # Role player definition (PPG range)
    ROLE_PLAYER_PPG_MIN = 6.0
    ROLE_PLAYER_PPG_MAX = 20.0

    # Breakout multiplier for context
    BREAKOUT_MULTIPLIER = 1.75

    # Retry configuration for model loading
    MODEL_LOAD_MAX_RETRIES = 3
    MODEL_LOAD_INITIAL_DELAY_SECONDS = 1.0
    MODEL_LOAD_BACKOFF_MULTIPLIER = 2.0

    def __init__(
        self,
        model_path: Optional[str] = None,
        require_model: bool = False,  # Shadow mode: don't fail if model unavailable
    ):
        """
        Initialize Breakout Classifier V1.

        Args:
            model_path: Optional explicit path to model file.
                       If not provided, searches for model in standard locations.
            require_model: If True, raise ModelLoadError if model cannot be loaded.
                          Default False for shadow mode (graceful degradation).

        Raises:
            ModelLoadError: If require_model=True and model fails to load after retries.
        """
        import time

        self.model = None
        self._model_path: Optional[str] = None
        self._model_file_name: Optional[str] = None
        self._load_attempts = 0
        self._last_load_error: Optional[Exception] = None

        # Determine model source
        gcs_path = os.environ.get('BREAKOUT_CLASSIFIER_MODEL_PATH')

        if model_path:
            model_source = model_path
        elif gcs_path:
            model_source = gcs_path
            logger.info(f"Loading Breakout Classifier from env var: {gcs_path}")
        else:
            model_source = "local"

        # Load model with retries
        delay = self.MODEL_LOAD_INITIAL_DELAY_SECONDS
        for attempt in range(1, self.MODEL_LOAD_MAX_RETRIES + 1):
            self._load_attempts = attempt
            try:
                if model_source == "local":
                    self._load_local_model()
                else:
                    self._load_model_from_path(model_source)

                if self.model is not None:
                    logger.info(
                        f"Breakout Classifier V1 model loaded successfully on attempt {attempt}. "
                        f"Model file: {self._model_file_name}. "
                        f"Ready for shadow mode classification."
                    )
                    break
            except Exception as e:
                self._last_load_error = e
                logger.warning(
                    f"Breakout Classifier model load attempt {attempt}/{self.MODEL_LOAD_MAX_RETRIES} failed: {e}"
                )

            # Model still None after load attempt
            if self.model is None and attempt < self.MODEL_LOAD_MAX_RETRIES:
                logger.info(f"Retrying model load in {delay:.1f}s...")
                time.sleep(delay)
                delay *= self.MODEL_LOAD_BACKOFF_MULTIPLIER

        # Handle model load failure
        if self.model is None:
            error_msg = (
                f"Breakout Classifier V1 model FAILED to load after {self.MODEL_LOAD_MAX_RETRIES} attempts! "
                f"Model source: {model_source}. "
                f"Shadow mode will return LOW_RISK for all players."
            )

            if require_model:
                logger.critical(error_msg)
                raise ModelLoadError(
                    message=error_msg,
                    attempts=self.MODEL_LOAD_MAX_RETRIES,
                    last_error=self._last_load_error
                )
            else:
                # Shadow mode: warn but continue
                logger.warning(error_msg)

    def _load_local_model(self):
        """Load model from local models/ directory."""
        import catboost as cb

        models_dir = Path(__file__).parent.parent.parent.parent / "models"

        # Look for the specific experiment model
        model_files = list(models_dir.glob("breakout_exp_EXP_COMBINED_BEST_*.cbm"))

        if not model_files:
            # Fallback to any breakout classifier model
            model_files = list(models_dir.glob("breakout_*.cbm"))

        if not model_files:
            raise FileNotFoundError(
                f"No Breakout Classifier model files found in {models_dir}. "
                f"Expected files matching: breakout_exp_EXP_COMBINED_BEST_*.cbm"
            )

        # Use the most recent model
        model_path = sorted(model_files)[-1]
        logger.info(f"Loading Breakout Classifier from {model_path}")

        self.model = cb.CatBoostClassifier()
        self.model.load_model(str(model_path))
        self._model_path = str(model_path)
        self._model_file_name = model_path.name

        logger.info(f"Loaded Breakout Classifier model: {self._model_file_name}")

    def _load_model_from_path(self, model_path: str):
        """Load model from explicit path (local or GCS)."""
        import catboost as cb

        logger.info(f"Loading Breakout Classifier from: {model_path}")

        if model_path.startswith("gs://"):
            # Load from GCS
            from shared.clients import get_storage_client

            parts = model_path.replace("gs://", "").split("/", 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = get_storage_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            local_path = "/tmp/breakout_classifier_v1.cbm"
            blob.download_to_filename(local_path)
            logger.info(f"Downloaded Breakout Classifier model from GCS to {local_path}")

            self.model = cb.CatBoostClassifier()
            self.model.load_model(local_path)
            self._model_file_name = Path(blob_path).name
        else:
            # Load from local path
            self.model = cb.CatBoostClassifier()
            self.model.load_model(model_path)
            self._model_file_name = Path(model_path).name

        self._model_path = model_path
        logger.info(f"Loaded Breakout Classifier model: {self._model_file_name}")

    def classify(
        self,
        player_lookup: str,
        features: Dict[str, Any],
        points_avg_season: Optional[float] = None,
    ) -> BreakoutClassificationResult:
        """
        Classify breakout risk for a player.

        Args:
            player_lookup: Player identifier (e.g., 'john-collins')
            features: Feature dictionary containing breakout features
            points_avg_season: Player's season scoring average (can also be in features)

        Returns:
            BreakoutClassificationResult with risk_score, risk_category, and metadata

        Note:
            - Returns LOW_RISK if player is not a role player (PPG outside 6-20)
            - Returns LOW_RISK if model is not loaded (shadow mode graceful degradation)
            - Never raises exceptions - always returns a valid result
        """
        # Get season average from features if not provided
        if points_avg_season is None:
            points_avg_season = features.get('points_avg_season')

        # Check if we have season average
        if points_avg_season is None:
            return self._create_skip_result(
                player_lookup=player_lookup,
                skip_reason="MISSING_SEASON_AVG",
            )

        # Check if player is a role player (PPG 6-20)
        if not self._is_role_player(points_avg_season):
            return self._create_skip_result(
                player_lookup=player_lookup,
                skip_reason="NOT_ROLE_PLAYER",
                points_avg_season=points_avg_season,
                is_role_player=False,
            )

        # Check if model is loaded
        if self.model is None:
            return self._create_skip_result(
                player_lookup=player_lookup,
                skip_reason="MODEL_NOT_LOADED",
                points_avg_season=points_avg_season,
                is_role_player=True,
            )

        # Prepare feature vector
        try:
            feature_vector = self._prepare_feature_vector(features, points_avg_season)
        except Exception as e:
            logger.warning(
                f"Feature preparation failed for {player_lookup}: {e}",
                extra={"player_lookup": player_lookup, "error": str(e)}
            )
            return self._create_skip_result(
                player_lookup=player_lookup,
                skip_reason="FEATURE_PREPARATION_FAILED",
                points_avg_season=points_avg_season,
                is_role_player=True,
                error=str(e),
            )

        # Run classification
        try:
            # Get probability of breakout (class 1)
            probabilities = self.model.predict_proba(feature_vector)
            risk_score = float(probabilities[0][1])  # Probability of breakout class

            # Determine risk category
            if risk_score >= self.OPTIMAL_THRESHOLD:
                risk_category = BreakoutRiskCategory.HIGH_RISK
            elif risk_score >= self.MEDIUM_THRESHOLD:
                risk_category = BreakoutRiskCategory.MEDIUM_RISK
            else:
                risk_category = BreakoutRiskCategory.LOW_RISK

            # Calculate confidence based on how far from decision boundary
            # Confidence is higher when further from 0.5
            confidence = abs(risk_score - 0.5) * 2  # Scale to 0-1

            # Log classification
            logger.info(
                "breakout_classification",
                extra={
                    "player_lookup": player_lookup,
                    "system_id": self.SYSTEM_ID,
                    "risk_score": round(risk_score, 4),
                    "risk_category": risk_category.value,
                    "confidence": round(confidence, 4),
                    "points_avg_season": points_avg_season,
                    "model_file": self._model_file_name,
                }
            )

            return BreakoutClassificationResult(
                risk_score=risk_score,
                risk_category=risk_category,
                is_role_player=True,
                confidence=confidence,
                skip_reason=None,
                metadata={
                    "system_id": self.SYSTEM_ID,
                    "model_version": self.MODEL_VERSION,
                    "model_file_name": self._model_file_name,
                    "optimal_threshold": self.OPTIMAL_THRESHOLD,
                    "breakout_multiplier": self.BREAKOUT_MULTIPLIER,
                    "points_avg_season": points_avg_season,
                    "breakout_threshold_points": round(points_avg_season * self.BREAKOUT_MULTIPLIER, 1),
                    "feature_values": self._extract_feature_values(features, points_avg_season),
                },
            )

        except Exception as e:
            logger.error(
                f"Breakout classification failed for {player_lookup}: {e}",
                exc_info=True,
                extra={"player_lookup": player_lookup, "error": str(e)}
            )
            return self._create_skip_result(
                player_lookup=player_lookup,
                skip_reason="CLASSIFICATION_FAILED",
                points_avg_season=points_avg_season,
                is_role_player=True,
                error=str(e),
            )

    def _is_role_player(self, points_avg_season: float) -> bool:
        """Check if player is a role player based on PPG."""
        return self.ROLE_PLAYER_PPG_MIN <= points_avg_season <= self.ROLE_PLAYER_PPG_MAX

    def _prepare_feature_vector(
        self,
        features: Dict[str, Any],
        points_avg_season: float,
    ) -> np.ndarray:
        """
        Prepare feature vector for classification.

        Extracts the 8 features in the exact order required by the model.
        Uses reasonable defaults for missing features.
        """
        # Calculate derived features with defaults
        points_std = features.get('points_std_last_10', 5.0)
        points_avg_last_5 = features.get('points_avg_last_5', points_avg_season)
        points_avg_last_10 = features.get('points_avg_last_10', points_avg_season)

        # CV ratio: coefficient of variation ratio (recent volatility vs season)
        cv_season = points_std / points_avg_season if points_avg_season > 0 else 0.5
        cv_recent = points_std / points_avg_last_10 if points_avg_last_10 > 0 else 0.5
        cv_ratio = cv_recent / cv_season if cv_season > 0 else 1.0

        # Cold streak indicator: 1 if last 3 games below season avg
        # Use points_avg_last_5 as proxy (closer to recent performance)
        cold_streak_indicator = 1.0 if points_avg_last_5 < points_avg_season else 0.0

        # Z-score: how far below season average
        pts_vs_season_zscore = (points_avg_last_5 - points_avg_season) / points_std if points_std > 0 else 0.0

        # Opponent defensive rating (higher = worse defense = easier to score)
        opponent_def_rating = features.get('opponent_def_rating', 112.0)

        # Explosion ratio: max game / avg (from features or estimate)
        # This captures "ceiling" - how high can they go
        explosion_ratio = features.get('explosion_ratio', 1.5)
        if explosion_ratio == 1.5 and 'points_max_season' in features:
            points_max = features['points_max_season']
            explosion_ratio = points_max / points_avg_season if points_avg_season > 0 else 1.5

        # Days since breakout: from features or default to 30 (about a month)
        days_since_breakout = features.get('days_since_breakout', 30.0)

        # Minutes avg last 10
        minutes_avg_last_10 = features.get('minutes_avg_last_10', 25.0)

        # Build feature vector in exact order
        vector = np.array([
            cv_ratio,
            cold_streak_indicator,
            pts_vs_season_zscore,
            opponent_def_rating,
            explosion_ratio,
            days_since_breakout,
            minutes_avg_last_10,
            points_avg_season,
        ]).reshape(1, -1)

        # Validate - no NaN or Inf
        if np.any(np.isnan(vector)) or np.any(np.isinf(vector)):
            raise ValueError(
                f"Feature vector contains NaN or Inf values: {vector.flatten().tolist()}"
            )

        return vector

    def _extract_feature_values(
        self,
        features: Dict[str, Any],
        points_avg_season: float,
    ) -> Dict[str, float]:
        """Extract feature values for logging/debugging."""
        try:
            vector = self._prepare_feature_vector(features, points_avg_season)
            return {
                name: round(float(value), 4)
                for name, value in zip(BREAKOUT_FEATURES, vector.flatten())
            }
        except Exception:
            return {}

    def _create_skip_result(
        self,
        player_lookup: str,
        skip_reason: str,
        points_avg_season: Optional[float] = None,
        is_role_player: bool = False,
        error: Optional[str] = None,
    ) -> BreakoutClassificationResult:
        """Create a skip result with LOW_RISK default."""
        metadata = {
            "system_id": self.SYSTEM_ID,
            "model_version": self.MODEL_VERSION,
            "model_file_name": self._model_file_name,
            "skip_reason": skip_reason,
            "player_lookup": player_lookup,
        }

        if points_avg_season is not None:
            metadata["points_avg_season"] = points_avg_season
            metadata["role_player_range"] = f"{self.ROLE_PLAYER_PPG_MIN}-{self.ROLE_PLAYER_PPG_MAX}"

        if error:
            metadata["error"] = error

        return BreakoutClassificationResult(
            risk_score=0.0,
            risk_category=BreakoutRiskCategory.LOW_RISK,
            is_role_player=is_role_player,
            confidence=0.0,
            skip_reason=skip_reason,
            metadata=metadata,
        )

    def get_model_info(self) -> Dict[str, Any]:
        """Get model information for health checks and debugging."""
        return {
            "system_id": self.SYSTEM_ID,
            "model_version": self.MODEL_VERSION,
            "model_path": self._model_path,
            "model_file_name": self._model_file_name,
            "model_loaded": self.model is not None,
            "load_attempts": self._load_attempts,
            "last_load_error": str(self._last_load_error) if self._last_load_error else None,
            "optimal_threshold": self.OPTIMAL_THRESHOLD,
            "role_player_ppg_range": f"{self.ROLE_PLAYER_PPG_MIN}-{self.ROLE_PLAYER_PPG_MAX}",
            "breakout_multiplier": self.BREAKOUT_MULTIPLIER,
            "features": BREAKOUT_FEATURES,
            "feature_count": len(BREAKOUT_FEATURES),
        }

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self.model is not None

    def __str__(self) -> str:
        """String representation."""
        status = "loaded" if self.model else "not loaded"
        return f"BreakoutClassifierV1 ({status})"

    def __repr__(self) -> str:
        """Developer representation."""
        return (
            f"BreakoutClassifierV1("
            f"system_id='{self.SYSTEM_ID}', "
            f"model_loaded={self.model is not None}, "
            f"model_file='{self._model_file_name}'"
            f")"
        )

    def predict(
        self,
        features: Dict[str, Any],
        player_lookup: str,
        season_avg: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Predict breakout risk for a player (convenience method for worker integration).

        This is an alias for classify() that returns a dict instead of BreakoutClassificationResult.
        Designed for easy integration into the prediction worker shadow mode.

        Args:
            features: Feature dictionary containing breakout features
            player_lookup: Player identifier (e.g., 'john-collins')
            season_avg: Player's season scoring average (can also be in features)

        Returns:
            Dict with:
            - risk_score: Probability of breakout (0-1)
            - risk_category: HIGH_RISK/MEDIUM_RISK/LOW_RISK
            - is_role_player: Whether player is in target population (PPG 6-20)
            - model_version: Version identifier
        """
        result = self.classify(
            player_lookup=player_lookup,
            features=features,
            points_avg_season=season_avg,
        )
        return result.to_dict()


# Factory functions
def load_breakout_classifier(require_model: bool = False) -> BreakoutClassifierV1:
    """
    Load Breakout Classifier V1 with local model.

    Args:
        require_model: If True, raise ModelLoadError on failure.
                      Default False for shadow mode.

    Returns:
        BreakoutClassifierV1 instance (may have model=None if loading failed)

    Raises:
        ModelLoadError: If require_model=True and model cannot be loaded.
    """
    return BreakoutClassifierV1(require_model=require_model)


def load_breakout_classifier_from_gcs(
    gcs_path: str,
    require_model: bool = False
) -> BreakoutClassifierV1:
    """
    Load Breakout Classifier V1 from GCS.

    Args:
        gcs_path: GCS path to the model file.
        require_model: If True, raise ModelLoadError on failure.

    Returns:
        BreakoutClassifierV1 instance

    Raises:
        ModelLoadError: If require_model=True and model cannot be loaded.
    """
    return BreakoutClassifierV1(model_path=gcs_path, require_model=require_model)
