"""
MLB Prediction Configuration

Centralized configuration for prediction thresholds, red flag rules,
and model parameters. All magic numbers extracted here for easy tuning.

Usage:
    from predictions.mlb.config import PredictionConfig, RedFlagConfig

    config = PredictionConfig()
    if edge >= config.min_edge:
        ...

Environment variables can override defaults:
    MLB_MIN_EDGE=0.75 python ...
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List


def _env_float(key: str, default: float) -> float:
    """Get float from environment variable or use default."""
    val = os.environ.get(key)
    if val is not None:
        try:
            return float(val)
        except ValueError:
            pass
    return default


def _env_int(key: str, default: int) -> int:
    """Get int from environment variable or use default."""
    val = os.environ.get(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return default


@dataclass
class PredictionConfig:
    """
    Configuration for prediction thresholds.

    V1 uses stricter thresholds (min_edge=0.5).
    V2 uses higher thresholds (min_edge=1.0) based on backtesting.
    """

    # Minimum edge (in strikeouts) to make a recommendation
    # Below this, recommend PASS regardless of confidence
    min_edge: float = field(default_factory=lambda: _env_float('MLB_MIN_EDGE', 0.5))

    # Minimum confidence to make a recommendation
    # Below this threshold, recommend PASS
    min_confidence: float = field(default_factory=lambda: _env_float('MLB_MIN_CONFIDENCE', 60.0))

    # Classifier probability thresholds (for classifier models)
    # prob >= over_threshold -> OVER, prob <= under_threshold -> UNDER
    classifier_over_threshold: float = field(default_factory=lambda: _env_float('MLB_CLASSIFIER_OVER_THRESHOLD', 0.53))
    classifier_under_threshold: float = field(default_factory=lambda: _env_float('MLB_CLASSIFIER_UNDER_THRESHOLD', 0.47))

    # Maximum confidence to cap at
    max_confidence: float = 100.0


@dataclass
class PredictionConfigV2(PredictionConfig):
    """V2-specific configuration with higher edge threshold."""
    min_edge: float = field(default_factory=lambda: _env_float('MLB_MIN_EDGE_V2', 1.0))


@dataclass
class RedFlagConfig:
    """
    Configuration for red flag system thresholds.

    Red flags can either:
    - SKIP: Skip the bet entirely (hard stop)
    - REDUCE: Apply confidence multiplier (soft adjustment)
    - BOOST: Increase confidence for favorable conditions
    """

    # ==========================================================================
    # SKIP THRESHOLDS (Hard stops - don't bet at all)
    # ==========================================================================

    # Minimum IP average to consider (below = bullpen/opener)
    min_ip_avg: float = field(default_factory=lambda: _env_float('MLB_MIN_IP_AVG', 4.0))

    # Minimum career starts to bet on
    min_career_starts: int = field(default_factory=lambda: _env_int('MLB_MIN_CAREER_STARTS', 2))

    # ==========================================================================
    # REDUCE THRESHOLDS (Soft adjustments)
    # ==========================================================================

    # Early season threshold (games started)
    early_season_starts: int = field(default_factory=lambda: _env_int('MLB_EARLY_SEASON_STARTS', 3))
    early_season_multiplier: float = 0.7

    # High variance threshold (K standard deviation)
    high_variance_k_std: float = field(default_factory=lambda: _env_float('MLB_HIGH_VARIANCE_K_STD', 4.0))
    high_variance_over_multiplier: float = 0.4   # Very bad for OVER (34.4% hit rate)
    high_variance_under_multiplier: float = 1.1  # Good for UNDER (62.5% hit rate)

    # Short rest threshold (days)
    short_rest_days: int = field(default_factory=lambda: _env_int('MLB_SHORT_REST_DAYS', 4))
    short_rest_over_multiplier: float = 0.7  # Only affects OVER

    # High workload threshold (games in 30 days)
    high_workload_games: int = field(default_factory=lambda: _env_int('MLB_HIGH_WORKLOAD_GAMES', 6))
    high_workload_over_multiplier: float = 0.85  # Only affects OVER

    # ==========================================================================
    # SWSTR% THRESHOLDS (Backtest validated)
    # ==========================================================================

    # Elite SwStr% threshold (above = elite stuff)
    elite_swstr_pct: float = field(default_factory=lambda: _env_float('MLB_ELITE_SWSTR_PCT', 0.12))
    elite_swstr_over_multiplier: float = 1.1   # Favors OVER
    elite_swstr_under_multiplier: float = 0.8  # Avoid UNDER

    # Low SwStr% threshold (below = weak stuff)
    low_swstr_pct: float = field(default_factory=lambda: _env_float('MLB_LOW_SWSTR_PCT', 0.08))
    low_swstr_over_multiplier: float = 0.85   # Lean UNDER
    low_swstr_under_multiplier: float = 1.05  # Slight boost

    # ==========================================================================
    # SWSTR% TREND THRESHOLDS (Session 57 backtest)
    # ==========================================================================

    # Hot streak threshold (recent - season SwStr%)
    hot_streak_trend: float = field(default_factory=lambda: _env_float('MLB_HOT_STREAK_TREND', 0.03))
    hot_streak_over_multiplier: float = 1.08   # Favors OVER (54.6% hit rate)
    hot_streak_under_multiplier: float = 0.92  # Avoid UNDER

    # Cold streak threshold (recent - season SwStr%)
    cold_streak_trend: float = field(default_factory=lambda: _env_float('MLB_COLD_STREAK_TREND', -0.03))
    cold_streak_over_multiplier: float = 0.92   # Lean UNDER
    cold_streak_under_multiplier: float = 1.05  # Slight boost (49.8% hit rate)

    # ==========================================================================
    # LIMITS
    # ==========================================================================

    # Minimum confidence multiplier (floor)
    min_confidence_multiplier: float = 0.3


@dataclass
class CacheConfig:
    """Configuration for caching behavior."""

    # IL pitcher cache TTL (hours)
    il_cache_ttl_hours: int = field(default_factory=lambda: _env_int('MLB_IL_CACHE_TTL_HOURS', 6))


@dataclass
class SystemConfig:
    """Configuration for prediction system registry."""

    # Active systems to run (comma-separated system IDs)
    # Default: v1_baseline only (Phase 1)
    # Phase 2: v1_baseline,v1_6_rolling
    # Phase 3: v1_baseline,v1_6_rolling,ensemble_v1
    active_systems: str = field(default_factory=lambda: os.environ.get('MLB_ACTIVE_SYSTEMS', 'v1_baseline'))

    # Model paths for each system
    v1_model_path: str = field(default_factory=lambda: os.environ.get(
        'MLB_V1_MODEL_PATH',
        'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json'
    ))
    v1_6_model_path: str = field(default_factory=lambda: os.environ.get(
        'MLB_V1_6_MODEL_PATH',
        'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
    ))

    # Ensemble weights (V1, V1.6)
    ensemble_v1_weight: float = field(default_factory=lambda: float(os.environ.get('MLB_ENSEMBLE_V1_WEIGHT', '0.3')))
    ensemble_v1_6_weight: float = field(default_factory=lambda: float(os.environ.get('MLB_ENSEMBLE_V1_6_WEIGHT', '0.5')))

    def get_active_systems(self) -> List[str]:
        """Get list of active system IDs."""
        return [s.strip() for s in self.active_systems.split(',') if s.strip()]


@dataclass
class MLBConfig:
    """Master configuration combining all sub-configs."""

    prediction: PredictionConfig = field(default_factory=PredictionConfig)
    prediction_v2: PredictionConfigV2 = field(default_factory=PredictionConfigV2)
    red_flags: RedFlagConfig = field(default_factory=RedFlagConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    systems: SystemConfig = field(default_factory=SystemConfig)

    @classmethod
    def from_env(cls) -> 'MLBConfig':
        """Create config from environment variables."""
        return cls()


# Default singleton instance
_default_config: MLBConfig = None


def get_config() -> MLBConfig:
    """Get the default MLB configuration instance."""
    global _default_config
    if _default_config is None:
        _default_config = MLBConfig.from_env()
    return _default_config


def reset_config():
    """Reset config (useful for testing)."""
    global _default_config
    _default_config = None
