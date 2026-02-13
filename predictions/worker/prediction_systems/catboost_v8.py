# predictions/worker/prediction_systems/catboost_v8.py

"""
CatBoost V8 Prediction System (Shadow Mode) - Updated 2026-01-25

Production ML model trained on 76,863 games achieving 3.40 MAE.
Runs in shadow mode alongside the mock-based XGBoost V1 for comparison.

Key Differences from XGBoost V1:
- Uses 34 features (vs 25 in v1) - updated from 33 on 2026-01-25
- Includes Vegas lines, opponent history, minutes/PPM history
- NEW: Shot zone missingness indicator (Feature #33)
- Uses stacked ensemble (XGBoost + LightGBM + CatBoost with Ridge meta-learner)
- Trained on real historical data (2021-2024)

Performance:
- MAE: 3.40 (vs mock's 4.80)
- Beats Vegas by 25% on out-of-sample 2024-25 data
- 71.6% betting accuracy

Shot Zone Handling (Updated 2026-01-25):
- Features 18-20 (paint%, mid-range%, three%) now NULLABLE
- Uses np.nan when shot zone data unavailable (CatBoost handles natively)
- Feature 33: has_shot_zone_data indicator (1.0 = all zones available, 0.0 = missing)
- Allows model to distinguish "average shooter" from "data unavailable"

Prometheus Metrics (Added 2026-01-29 - Prevention Task #9):
- catboost_v8_feature_fallback_total: Counter of predictions using fallback values
- catboost_v8_prediction_points: Histogram of predicted points distribution
- catboost_v8_extreme_prediction_total: Counter of predictions at clamp boundaries

Usage:
    from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8

    system = CatBoostV8()
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
# Model Load Error - Critical Failure (Session 40)
# =============================================================================
# Model not loading is a HARD FAILURE. The system should not silently fall back
# to weighted averages. This exception is raised when the model cannot be loaded
# after retries, signaling that the service should not accept traffic.
# =============================================================================

class ModelLoadError(Exception):
    """
    Raised when CatBoost model fails to load after all retry attempts.

    This is a critical error that should prevent the worker from accepting
    prediction requests. The service should fail health checks and not
    receive traffic until the model is available.
    """

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


# =============================================================================
# Prometheus Metrics (Prevention Plan Task #9)
# =============================================================================
# These metrics enable real-time monitoring of CatBoost V8 prediction quality
# and feature fallback usage. They help detect issues like the +29 point bug
# before they impact production predictions.
#
# Metrics are exposed via the /metrics endpoint in the worker service.
# =============================================================================

# Feature fallback counter - tracks when default values are used
# Labels: feature_name (which feature used fallback), severity (critical/major/minor)
catboost_v8_feature_fallback_total = Counter(
    name='catboost_v8_feature_fallback_total',
    help_text='Count of CatBoost V8 predictions using fallback values by feature and severity',
    label_names=['feature_name', 'severity']
)

# Prediction distribution histogram - tracks predicted point values
# Buckets designed for typical NBA player points (5-60 range)
catboost_v8_prediction_points = Histogram(
    name='catboost_v8_prediction_points',
    help_text='Distribution of CatBoost V8 predicted points',
    label_names=[],
    buckets=[5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0]
)

# Extreme prediction counter - tracks predictions at clamp boundaries
# Labels: boundary ('high_60' or 'low_0')
catboost_v8_extreme_prediction_total = Counter(
    name='catboost_v8_extreme_prediction_total',
    help_text='Count of CatBoost V8 predictions clamped at boundaries (0 or 60)',
    label_names=['boundary']
)


# =============================================================================
# Fallback Severity Classification (Prevention Plan Task #8)
# =============================================================================
# Categorizes fallback severity to enable loud failures for critical missing
# features. This prevents silent degradation that led to the +29 point bug.
# =============================================================================


class FallbackSeverity(Enum):
    """
    Severity levels for feature fallbacks in CatBoost V8 predictions.

    Used to classify how concerning a missing feature is:
    - NONE: All features present, no fallbacks used
    - MINOR: Non-critical features missing (acceptable degradation)
    - MAJOR: Important features missing (degraded prediction quality)
    - CRITICAL: Critical features missing (prediction may be unreliable)
    """
    NONE = "none"           # All features present
    MINOR = "minor"         # Non-critical feature missing (e.g., games_vs_opponent)
    MAJOR = "major"         # Important feature missing (e.g., minutes_avg_last_10)
    CRITICAL = "critical"   # Critical feature missing (e.g., vegas_points_line, has_vegas_line)


# Feature sets for severity classification
# Critical: Features that most directly impact prediction accuracy
CRITICAL_FEATURES: Set[str] = {
    'vegas_points_line',    # Most predictive feature, correlates strongly with actual points
    'has_vegas_line',       # Indicator flag - wrong value corrupts feature semantics
    'ppm_avg_last_10',      # Points-per-minute - key efficiency metric
}

# Major: Important features that affect prediction quality
MAJOR_FEATURES: Set[str] = {
    'avg_points_vs_opponent',   # Historical matchup data
    'minutes_avg_last_10',      # Playing time consistency
}

# All other V8-specific features are considered minor
# (vegas_opening_line, vegas_line_move, games_vs_opponent)


def classify_fallback_severity(used_defaults: List[str]) -> FallbackSeverity:
    """
    Classify the severity of fallback values used in feature preparation.

    This function enables "loud failures" for missing features as specified
    in the CatBoost V8 Prevention Plan. Instead of silently using defaults,
    the system can now respond appropriately based on severity:

    - NONE: Normal prediction flow
    - MINOR: Predict, log at INFO level
    - MAJOR: Predict, log at WARNING level, consider marking prediction_quality='degraded'
    - CRITICAL: Log at ERROR level, consider refusing to predict

    Args:
        used_defaults: List of feature names that used default/fallback values

    Returns:
        FallbackSeverity: The highest severity level among all fallbacks

    Example:
        >>> classify_fallback_severity([])
        FallbackSeverity.NONE
        >>> classify_fallback_severity(['games_vs_opponent'])
        FallbackSeverity.MINOR
        >>> classify_fallback_severity(['minutes_avg_last_10'])
        FallbackSeverity.MAJOR
        >>> classify_fallback_severity(['vegas_points_line', 'has_vegas_line'])
        FallbackSeverity.CRITICAL
    """
    if not used_defaults:
        return FallbackSeverity.NONE

    used_defaults_set = set(used_defaults)

    # Check from highest to lowest severity
    if used_defaults_set & CRITICAL_FEATURES:
        return FallbackSeverity.CRITICAL
    elif used_defaults_set & MAJOR_FEATURES:
        return FallbackSeverity.MAJOR
    elif used_defaults:
        return FallbackSeverity.MINOR

    return FallbackSeverity.NONE


def get_fallback_details(used_defaults: List[str]) -> Dict:
    """
    Get detailed breakdown of fallback features by severity.

    Useful for logging and debugging to understand exactly which features
    contributed to each severity level.

    Args:
        used_defaults: List of feature names that used default/fallback values

    Returns:
        Dict with severity classification and feature breakdown
    """
    used_defaults_set = set(used_defaults)

    critical = list(used_defaults_set & CRITICAL_FEATURES)
    major = list(used_defaults_set & MAJOR_FEATURES)
    minor = list(used_defaults_set - CRITICAL_FEATURES - MAJOR_FEATURES)

    return {
        'severity': classify_fallback_severity(used_defaults).value,
        'total_fallbacks': len(used_defaults),
        'critical_features': critical,
        'major_features': major,
        'minor_features': minor,
        'critical_count': len(critical),
        'major_count': len(major),
        'minor_count': len(minor),
    }


def record_feature_fallback_metrics(used_defaults: List[str]) -> None:
    """
    Record Prometheus metrics for feature fallbacks (Prevention Task #9).

    Increments the catboost_v8_feature_fallback_total counter for each
    feature that used a fallback value, labeled by feature name and severity.

    This enables monitoring dashboards and alerts for:
    - High fallback rates indicating data pipeline issues
    - Critical feature fallbacks that may degrade prediction quality
    - Trends in feature availability over time

    Args:
        used_defaults: List of feature names that used default/fallback values
    """
    if not used_defaults:
        return

    used_defaults_set = set(used_defaults)

    # Record each fallback with its severity label
    for feature_name in used_defaults:
        if feature_name in CRITICAL_FEATURES:
            severity = 'critical'
        elif feature_name in MAJOR_FEATURES:
            severity = 'major'
        else:
            severity = 'minor'

        catboost_v8_feature_fallback_total.inc(
            labels={'feature_name': feature_name, 'severity': severity}
        )


def record_prediction_metrics(raw_prediction: float, clamped_prediction: float) -> None:
    """
    Record Prometheus metrics for a prediction (Prevention Task #9).

    Records:
    - Prediction value in histogram for distribution monitoring
    - Extreme prediction counter if clamped at boundaries

    This enables monitoring dashboards and alerts for:
    - Prediction distribution drift from expected ranges
    - High rate of extreme predictions indicating model issues
    - Mean prediction tracking over time

    Args:
        raw_prediction: The raw model prediction before clamping
        clamped_prediction: The prediction after clamping to [0, 60]
    """
    # Record in histogram (use clamped value for consistent distribution)
    catboost_v8_prediction_points.observe(clamped_prediction)

    # Track extreme predictions (those that hit clamp boundaries)
    if raw_prediction >= 60:
        catboost_v8_extreme_prediction_total.inc(labels={'boundary': 'high_60'})
    elif raw_prediction <= 0:
        catboost_v8_extreme_prediction_total.inc(labels={'boundary': 'low_0'})


# Feature order must match training exactly
V8_FEATURES = [
    # Base features (25) - from ml_feature_store_v2
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",
    "team_pace",
    "team_off_rating",
    "team_win_pct",
    # Vegas features (4)
    "vegas_points_line",
    "vegas_opening_line",
    "vegas_line_move",
    "has_vegas_line",
    # Opponent history (2)
    "avg_points_vs_opponent",
    "games_vs_opponent",
    # Minutes/PPM history (2)
    "minutes_avg_last_10",
    "ppm_avg_last_10",
    # Shot zone data availability (1) - Added 2026-01-25
    "has_shot_zone_data",
]


class CatBoostV8:
    """
    CatBoost V8 Stacked Ensemble prediction system

    Uses the v8 model trained with 33 features achieving 3.40 MAE.
    Designed to run in shadow mode for comparison with existing systems.
    """

    # Retry configuration for model loading
    MODEL_LOAD_MAX_RETRIES = 3
    MODEL_LOAD_INITIAL_DELAY_SECONDS = 1.0
    MODEL_LOAD_BACKOFF_MULTIPLIER = 2.0

    def __init__(
        self,
        model_path: Optional[str] = None,
        use_local: bool = True,
        require_model: bool = True
    ):
        """
        Initialize CatBoost V8 system

        Args:
            model_path: Path to CatBoost model file (local or GCS)
            use_local: If True, load from local models/ directory.
                       If CATBOOST_V8_MODEL_PATH env var is set, uses that instead.
            require_model: If True (default), raise ModelLoadError if model cannot be loaded.
                          This is the production behavior - no silent fallbacks.
                          Set to False only for testing.

        Raises:
            ModelLoadError: If require_model=True and model fails to load after retries.
        """
        import os
        import time

        self.system_id = 'catboost_v8'
        self.model_version = 'v8'
        self.model = None
        self.metadata = None
        self._last_load_error: Optional[Exception] = None

        # Check for GCS path in environment (production)
        gcs_path = os.environ.get('CATBOOST_V8_MODEL_PATH')

        # Determine model source
        if model_path:
            model_source = model_path
            load_method = self._load_model_from_path
        elif gcs_path:
            model_source = gcs_path
            load_method = self._load_model_from_path
            logger.info(f"Loading CatBoost v8 from env var: {gcs_path}")
        elif use_local:
            model_source = "local"
            load_method = lambda _: self._load_local_model()
        else:
            model_source = None
            load_method = None

        # Load model with retries
        if load_method:
            delay = self.MODEL_LOAD_INITIAL_DELAY_SECONDS
            for attempt in range(1, self.MODEL_LOAD_MAX_RETRIES + 1):
                try:
                    load_method(model_source)

                    if self.model is not None:
                        logger.info(
                            f"✓ CatBoost V8 model loaded successfully on attempt {attempt}. "
                            f"Ready to generate real predictions with 33 features."
                        )
                        break
                except Exception as e:
                    self._last_load_error = e
                    logger.warning(
                        f"CatBoost V8 model load attempt {attempt}/{self.MODEL_LOAD_MAX_RETRIES} failed: {e}"
                    )

                # Model still None after load attempt
                if self.model is None and attempt < self.MODEL_LOAD_MAX_RETRIES:
                    logger.info(f"Retrying model load in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= self.MODEL_LOAD_BACKOFF_MULTIPLIER

        # CRITICAL: Enforce model requirement (Session 40 - no silent fallbacks)
        if self.model is None:
            error_msg = (
                f"CRITICAL: CatBoost V8 model FAILED to load after {self.MODEL_LOAD_MAX_RETRIES} attempts! "
                f"Model source: {model_source}. "
                f"Check: 1) CATBOOST_V8_MODEL_PATH env var, 2) catboost library installed, "
                f"3) model file exists and is accessible, 4) GCS permissions."
            )

            # Structured logging for Cloud Monitoring alerts
            logger.critical(
                error_msg,
                extra={
                    "severity": "CRITICAL",
                    "alert_type": "model_load_failure",
                    "model_id": "catboost_v8",
                    "model_source": model_source,
                    "attempts": self.MODEL_LOAD_MAX_RETRIES,
                    "last_error": str(self._last_load_error) if self._last_load_error else None,
                }
            )

            if require_model:
                raise ModelLoadError(
                    message=error_msg,
                    attempts=self.MODEL_LOAD_MAX_RETRIES,
                    last_error=self._last_load_error
                )

    def _load_local_model(self):
        """
        Load model from local models/ directory.

        Raises exceptions on failure to enable retry logic in __init__.
        """
        import catboost as cb

        # Find the v8 model file
        models_dir = Path(__file__).parent.parent.parent.parent / "models"
        model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))

        if not model_files:
            raise FileNotFoundError(
                f"No CatBoost v8 model files found in {models_dir}. "
                f"Expected files matching: catboost_v8_33features_*.cbm"
            )

        # Use the most recent model
        model_path = sorted(model_files)[-1]
        logger.info(f"Loading CatBoost v8 model from {model_path}")

        self.model = cb.CatBoostRegressor()
        self.model.load_model(str(model_path))

        # Load metadata if available
        metadata_path = models_dir / "ensemble_v8_20260108_211817_metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                self.metadata = json.load(f)

        logger.info(f"Loaded CatBoost v8 model successfully")

    def _load_model_from_path(self, model_path: str):
        """
        Load model from specified path (local or GCS).

        Raises exceptions on failure to enable retry logic in __init__.
        """
        import catboost as cb

        if model_path.startswith("gs://"):
            # Load from GCS with circuit breaker protection
            parts = model_path.replace("gs://", "").split("/", 1)
            bucket_name, blob_path = parts[0], parts[1]

            # Get circuit breaker for GCS model loading
            # This prevents cascading failures if GCS is unavailable
            gcs_cb = get_service_circuit_breaker("gcs_model_loading")

            def download_model():
                from shared.clients import get_storage_client
                client = get_storage_client()
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(blob_path)
                local_path = "/tmp/catboost_v8.cbm"
                blob.download_to_filename(local_path)
                return local_path

            # Let CircuitBreakerError propagate - it's a retriable error
            model_path = gcs_cb.call(download_model)
            logger.info(f"GCS model download successful for catboost_v8")

        self.model = cb.CatBoostRegressor()
        self.model.load_model(model_path)
        logger.info(f"Loaded CatBoost v8 model from {model_path}")

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
        Generate prediction using CatBoost v8 model

        Args:
            player_lookup: Player identifier
            features: Base features dictionary (25 features)
            betting_line: Current over/under line for recommendation
            vegas_line: Vegas consensus points line (for feature)
            vegas_opening: Vegas opening line (for feature)
            opponent_avg: Player's avg points vs this opponent
            games_vs_opponent: Number of games vs this opponent
            minutes_avg_last_10: Avg minutes last 10 games
            ppm_avg_last_10: Points per minute last 10 games

        Returns:
            dict: Prediction with metadata

        Raises:
            ModelLoadError: If model is not loaded (should never happen in production
                           since __init__ enforces model loading with require_model=True)
        """
        # CRITICAL: Model must be loaded - no silent fallback to weighted average
        # If we reach this point with model=None, it's a bug in initialization
        if self.model is None:
            raise ModelLoadError(
                message=(
                    "CatBoost V8 model is not loaded. This should never happen in production. "
                    "The worker should have failed to start if model loading failed. "
                    f"player_lookup={player_lookup}"
                ),
                attempts=0,
                last_error=self._last_load_error
            )

        # FAIL-FAST: Assert correct feature version (v2_33features required for V8 model)
        feature_version = features.get('feature_version')
        # Accept v2_33features, v2_37features, or v2_39features (model extracts 33 features by name)
        # v2_39features adds breakout features (37-38) which this model doesn't use, but that's OK
        if feature_version not in ('v2_33features', 'v2_37features', 'v2_39features', 'v2_54features'):
            raise ValueError(
                f"CatBoost V8 requires feature_version in (v2_33features, v2_37features, v2_39features, v2_54features), got '{feature_version}'. "
                f"This model is trained on 33 features from ML Feature Store v2. "
                f"Ensure ml_feature_store_processor.py is upgraded to one of these versions."
            )

        # FAIL-FAST: Assert correct feature count (defense-in-depth)
        # Model extracts features by name, so any version >= 33 features is acceptable
        feature_count = features.get('feature_count')
        features_array = features.get('features_array', [])
        actual_count = feature_count if feature_count else len(features_array)
        if actual_count < 33 and actual_count != 0:  # 0 means field not present, allow that
            raise ValueError(
                f"CatBoost V8 requires at least 33 features, got {actual_count}. "
                f"Feature version is '{feature_version}' but count is too low. "
                f"Check ml_feature_store_processor.py feature extraction."
            )

        # Prepare 33-feature vector
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
            return self._fallback_prediction(player_lookup, features, betting_line,
                                             error_code='FEATURE_PREPARATION_FAILED')

        # Make prediction
        try:
            raw_prediction = float(self.model.predict(feature_vector)[0])
        except Exception as e:
            logger.error(f"CatBoost prediction failed: {e}", exc_info=True)
            return self._fallback_prediction(player_lookup, features, betting_line,
                                             error_code='MODEL_PREDICTION_FAILED')

        # Warn on extreme predictions before clamping (for monitoring/alerting)
        if raw_prediction >= 55 or raw_prediction <= 5:
            logger.warning(
                "extreme_prediction_detected",
                extra={
                    "player_lookup": player_lookup,
                    "raw_prediction": round(raw_prediction, 2),
                    "vegas_line": features.get('vegas_points_line'),
                    "season_avg": features.get('points_avg_season'),
                    "points_avg_last_5": features.get('points_avg_last_5'),
                    "betting_line": betting_line,
                }
            )

        # Clamp to reasonable range
        predicted_points = max(0, min(60, raw_prediction))

        # Record Prometheus metrics for prediction monitoring (Prevention Task #9)
        record_prediction_metrics(raw_prediction, predicted_points)

        # Calculate confidence
        confidence = self._calculate_confidence(features, feature_vector)

        # Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_points, betting_line, confidence
        )

        # Structured logging for monitoring and alerting
        # This enables log-based detection of prediction quality issues
        logger.info(
            "prediction_generated",
            extra={
                "player_lookup": player_lookup,
                "system_id": self.system_id,
                "model_type": "real",
                "predicted_points": round(predicted_points, 2),
                "confidence": round(confidence, 2),
                "recommendation": recommendation,
                "feature_version": feature_version,
                "betting_line": betting_line,
            }
        )

        # Collect warnings for this prediction
        warnings = []
        if features.get('early_season_flag'):
            warnings.append('EARLY_SEASON')
        if features.get('feature_quality_score', 100) < 70:
            warnings.append('LOW_QUALITY_SCORE')
        if features.get('points_std_last_10', 0) > 8:
            warnings.append('HIGH_VARIANCE')

        return {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'model_type': 'catboost_v8_real',
            'feature_count': 33,
            # Error tracking fields (Session 37)
            'feature_version': feature_version,
            'feature_quality_score': features.get('feature_quality_score'),
            'feature_data_source': features.get('data_source'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': None,  # No error for successful prediction
            'prediction_warnings': warnings if warnings else None,
            'raw_confidence_score': round(confidence / 100, 3),  # Store as 0-1
            'calibration_method': 'none',  # No calibration yet applied
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
        Prepare 33-feature vector in exact order required by model

        Uses player's season average as fallback for missing features.
        """
        try:
            # Get season average for imputation
            season_avg = features.get('points_avg_season', 10.0)

            # Log when critical features are missing from both params and dict
            # This helps detect data pipeline issues before they affect predictions
            missing_features = []
            if vegas_line is None and features.get('vegas_points_line') is None:
                missing_features.append(('vegas_points_line', season_avg))
            if opponent_avg is None and features.get('avg_points_vs_opponent') is None:
                missing_features.append(('avg_points_vs_opponent', season_avg))
            if ppm_avg_last_10 is None and features.get('ppm_avg_last_10') is None:
                missing_features.append(('ppm_avg_last_10', 0.4))

            if missing_features:
                logger.info(
                    "features_using_defaults",
                    extra={
                        "player_lookup": features.get('player_lookup', 'unknown'),
                        "missing_features": [f[0] for f in missing_features],
                        "default_values": {f[0]: f[1] for f in missing_features},
                    }
                )

            # Build feature vector in exact order
            vector = np.array([
                # Base features (25)
                features.get('points_avg_last_5', season_avg),
                features.get('points_avg_last_10', season_avg),
                features.get('points_avg_season', season_avg),
                features.get('points_std_last_10', 5.0),
                features.get('games_in_last_7_days', 2),
                features.get('fatigue_score', 70),
                features.get('shot_zone_mismatch_score', 0),
                features.get('pace_score', 0),
                features.get('usage_spike_score', 0),
                features.get('rest_advantage', 0),
                features.get('injury_risk', 0),
                features.get('recent_trend', 0),
                features.get('minutes_change', 0),
                features.get('opponent_def_rating', 112),
                features.get('opponent_pace', 100),
                features.get('home_away', 0),
                features.get('back_to_back', 0),
                features.get('playoff_game', 0),
                # Shot zone features (18-20) - NULLABLE since 2026-01-25
                # Use np.nan to allow CatBoost to handle missingness natively
                features.get('pct_paint') if features.get('pct_paint') is not None else np.nan,
                features.get('pct_mid_range') if features.get('pct_mid_range') is not None else np.nan,
                features.get('pct_three') if features.get('pct_three') is not None else np.nan,
                features.get('pct_free_throw', 20),
                features.get('team_pace', 100),
                features.get('team_off_rating', 112),
                features.get('team_win_pct', 0.5),
                # Vegas features (4) - use features dict, np.nan if no real Vegas line
                # CRITICAL FIX (2026-01-29): Worker passes features dict, not separate params
                # IMPORTANT: Do NOT use season_avg as fallback - that would corrupt the feature
                # CatBoost handles np.nan natively; has_vegas_line flag indicates data availability
                vegas_line if vegas_line is not None else features.get('vegas_points_line') if features.get('vegas_points_line') is not None else np.nan,
                vegas_opening if vegas_opening is not None else features.get('vegas_opening_line') if features.get('vegas_opening_line') is not None else np.nan,
                (vegas_line - vegas_opening) if vegas_line and vegas_opening else features.get('vegas_line_move') if features.get('vegas_line_move') is not None else np.nan,
                1.0 if (vegas_line is not None or features.get('vegas_points_line') is not None) else 0.0,
                # Opponent history (2)
                opponent_avg if opponent_avg is not None else features.get('avg_points_vs_opponent', season_avg),
                float(games_vs_opponent) if games_vs_opponent else features.get('games_vs_opponent', 0.0),
                # Minutes/PPM history (2)
                minutes_avg_last_10 if minutes_avg_last_10 is not None else features.get('minutes_avg_last_10', 25),
                ppm_avg_last_10 if ppm_avg_last_10 is not None else features.get('ppm_avg_last_10', 0.4),
                # Feature 33: Shot zone data availability indicator (NEW - 2026-01-25)
                features.get('has_shot_zone_data', 0.0),
            ]).reshape(1, -1)

            # Validate
            # NOTE: Allow NaN for features that CatBoost handles natively:
            # - Shot zone features (indices 18-20) - not available for all players
            # - Vegas line features (indices 25-27) - not available when no prop line exists
            # The has_vegas_line flag (index 28) indicates whether Vegas data is real
            nullable_features_mask = np.ones(vector.shape[1], dtype=bool)
            nullable_features_mask[18:21] = False  # Allow NaN for shot zones (features 18, 19, 20)
            nullable_features_mask[25:28] = False  # Allow NaN for Vegas lines (features 25, 26, 27)

            if np.any(np.isnan(vector[:, nullable_features_mask])) or np.any(np.isinf(vector)):
                logger.warning("Feature vector contains NaN or Inf values in non-nullable features")
                return None

            return vector

        except Exception as e:
            logger.error(f"Error preparing v8 feature vector: {e}", exc_info=True)
            return None

    def _calculate_confidence(
        self,
        features: Dict,
        feature_vector: np.ndarray
    ) -> float:
        """
        Calculate confidence score

        V8 model has higher base confidence due to training on real data.
        """
        confidence = 75.0  # Higher base for trained model

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
        """Generate betting recommendation"""
        if betting_line is None:
            return 'NO_LINE'

        if confidence < 60:
            return 'PASS'

        edge = predicted_points - betting_line

        # V8 model can use tighter threshold (1.0 vs 1.5) due to better accuracy
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
        error_code: str = 'FEATURE_PREPARATION_FAILED'
    ) -> Dict:
        """
        Fallback for feature or prediction failures - use simple weighted average.

        NOTE: This is ONLY used for:
        - FEATURE_PREPARATION_FAILED: Feature vector preparation returned None
        - MODEL_PREDICTION_FAILED: Model.predict() threw an exception

        MODEL_NOT_LOADED should NEVER use this fallback. If the model isn't loaded,
        the system should have failed at startup (require_model=True) or raised
        ModelLoadError in predict().
        """
        # CRITICAL: Log fallback usage so it's visible in Cloud Logging
        logger.warning(
            f"FALLBACK_PREDICTION: CatBoost V8 using fallback for {player_lookup}. "
            f"Error code: {error_code}. Confidence will be 50.0, recommendation will be PASS. "
            f"This fallback is for feature/prediction issues only, not model loading failures."
        )

        season_avg = features.get('points_avg_season', 10.0)
        last_5 = features.get('points_avg_last_5', season_avg)
        last_10 = features.get('points_avg_last_10', season_avg)

        # Simple weighted average fallback
        predicted = 0.4 * last_5 + 0.35 * last_10 + 0.25 * season_avg

        return {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'predicted_points': round(predicted, 2),
            'confidence_score': 50.0,
            'recommendation': 'PASS',
            'model_type': 'fallback',
            'error': f'{error_code}: Using fallback prediction',
            # Error tracking fields (Session 37)
            'feature_version': features.get('feature_version'),
            'feature_count': features.get('feature_count'),
            'feature_quality_score': features.get('feature_quality_score'),
            'feature_data_source': features.get('data_source'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': error_code,
            'prediction_warnings': ['FALLBACK_USED'],
            'raw_confidence_score': 0.5,
            'calibration_method': 'none',
        }

    def get_model_info(self) -> Dict:
        """Get model information"""
        info = {
            'system_id': self.system_id,
            'model_version': self.model_version,
            'model_loaded': self.model is not None,
            'feature_count': 33,
            'features': V8_FEATURES,
        }

        if self.metadata:
            info['training_mae'] = self.metadata.get('best_mae')
            info['training_samples'] = self.metadata.get('training_samples')

        return info


# Factory functions
def load_catboost_v8_system(require_model: bool = True) -> CatBoostV8:
    """
    Load CatBoost V8 system with local model.

    Args:
        require_model: If True (default), raise ModelLoadError on failure.

    Raises:
        ModelLoadError: If require_model=True and model cannot be loaded.
    """
    return CatBoostV8(use_local=True, require_model=require_model)


def load_catboost_v8_from_gcs(gcs_path: str, require_model: bool = True) -> CatBoostV8:
    """
    Load CatBoost V8 system from GCS.

    Args:
        gcs_path: GCS path to the model file.
        require_model: If True (default), raise ModelLoadError on failure.

    Raises:
        ModelLoadError: If require_model=True and model cannot be loaded.
    """
    return CatBoostV8(model_path=gcs_path, use_local=False, require_model=require_model)
