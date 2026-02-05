"""
Shared Breakout Classifier Feature Computation Module

This module provides a SINGLE SOURCE OF TRUTH for breakout feature computation.
Both training (breakout_experiment_runner.py) and evaluation (backfill_breakout_shadow.py)
should use this module to ensure feature consistency.

Session 134 Learning: Training and evaluation used different feature pipelines,
causing the model to have AUC 0.47 (worse than random) on holdout data.

Feature List (10 features in exact order):
1. pts_vs_season_zscore - Z-score of recent performance
2. points_std_last_10 - Volatility measure
3. explosion_ratio - Max L5 / season avg (explosive potential)
4. days_since_breakout - Recency of last breakout
5. opponent_def_rating - Matchup quality
6. home_away - Home court advantage
7. back_to_back - Fatigue indicator
8. points_avg_last_5 - Recent form
9. points_avg_season - Baseline scoring
10. minutes_avg_last_10 - Playing time opportunity
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd

PROJECT_ID = "nba-props-platform"

# Exact feature order - DO NOT CHANGE
# This order must match what models are trained with
BREAKOUT_FEATURE_ORDER = [
    "pts_vs_season_zscore",
    "points_std_last_10",
    "explosion_ratio",
    "days_since_breakout",
    "opponent_def_rating",
    "home_away",
    "back_to_back",
    "points_avg_last_5",
    "points_avg_season",
    "minutes_avg_last_10",
]

# Default values when features are missing
FEATURE_DEFAULTS = {
    "pts_vs_season_zscore": 0.0,
    "points_std_last_10": 5.0,
    "explosion_ratio": 1.5,
    "days_since_breakout": 30.0,
    "opponent_def_rating": 112.0,
    "home_away": 0.5,
    "back_to_back": 0.0,
    "points_avg_last_5": 10.0,
    "points_avg_season": 12.0,
    "minutes_avg_last_10": 25.0,
}


@dataclass
class BreakoutFeatureConfig:
    """Configuration for breakout feature computation."""
    min_ppg: float = 8.0
    max_ppg: float = 16.0
    breakout_multiplier: float = 1.5
    lookback_days: int = 30
    recent_games: int = 5


def get_training_data_query(
    start_date: str,
    end_date: str,
    config: BreakoutFeatureConfig = None,
) -> str:
    """
    Generate SQL query for loading training/evaluation data with all features.

    This query computes ALL features consistently for both training and evaluation.
    Use this for both experiment_runner and backfill to ensure consistency.

    Args:
        start_date: Start date for data (YYYY-MM-DD)
        end_date: End date for data (YYYY-MM-DD)
        config: Feature configuration (uses defaults if None)

    Returns:
        SQL query string
    """
    if config is None:
        config = BreakoutFeatureConfig()

    return f"""
    -- Base player games in date range with daily cache stats
    WITH base_games AS (
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.game_id,
        pgs.points as actual_points,
        pgs.minutes_played,
        dc.points_avg_season,
        dc.points_std_last_10,
        dc.points_avg_last_5,
        dc.points_avg_last_10,
        dc.minutes_avg_last_10,
        -- Target variable: is this game a breakout?
        CASE
          WHEN pgs.points >= dc.points_avg_season * {config.breakout_multiplier} THEN 1
          ELSE 0
        END as is_breakout
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      JOIN `{PROJECT_ID}.nba_precompute.player_daily_cache` dc
        ON pgs.player_lookup = dc.player_lookup
        AND pgs.game_date = dc.cache_date
      WHERE pgs.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND dc.points_avg_season BETWEEN {config.min_ppg} AND {config.max_ppg}
        AND pgs.minutes_played > 0
        AND pgs.points IS NOT NULL
    ),

    -- Compute max points in last N games for explosion_ratio
    recent_game_stats AS (
      SELECT
        bg.player_lookup,
        bg.game_date as target_date,
        pgs2.points,
        pgs2.game_date as prior_game_date,
        ROW_NUMBER() OVER (
          PARTITION BY bg.player_lookup, bg.game_date
          ORDER BY pgs2.game_date DESC
        ) as game_rank
      FROM base_games bg
      JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs2
        ON pgs2.player_lookup = bg.player_lookup
        AND pgs2.game_date < bg.game_date
        AND pgs2.game_date >= DATE_SUB(bg.game_date, INTERVAL {config.lookback_days} DAY)
        AND pgs2.minutes_played > 0
    ),

    -- Aggregate recent game stats
    recent_aggregates AS (
      SELECT
        player_lookup,
        target_date,
        MAX(points) as max_points_recent
      FROM recent_game_stats
      WHERE game_rank <= {config.recent_games}
      GROUP BY player_lookup, target_date
    ),

    -- Find last breakout date for each player-game
    breakout_history AS (
      SELECT
        bg.player_lookup,
        bg.game_date as target_date,
        MAX(pgs3.game_date) as last_breakout_date
      FROM base_games bg
      LEFT JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs3
        ON pgs3.player_lookup = bg.player_lookup
        AND pgs3.game_date < bg.game_date
        AND pgs3.minutes_played > 0
      LEFT JOIN `{PROJECT_ID}.nba_precompute.player_daily_cache` dc3
        ON pgs3.player_lookup = dc3.player_lookup
        AND pgs3.game_date = dc3.cache_date
      WHERE pgs3.points >= dc3.points_avg_season * {config.breakout_multiplier}
      GROUP BY bg.player_lookup, bg.game_date
    ),

    -- Join with feature store for context features
    with_context AS (
      SELECT
        bg.*,
        ra.max_points_recent,
        bh.last_breakout_date,
        mf.features as feature_store_values,
        mf.feature_names as feature_store_names
      FROM base_games bg
      LEFT JOIN recent_aggregates ra
        ON bg.player_lookup = ra.player_lookup
        AND bg.game_date = ra.target_date
      LEFT JOIN breakout_history bh
        ON bg.player_lookup = bh.player_lookup
        AND bg.game_date = bh.target_date
      LEFT JOIN `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        ON bg.player_lookup = mf.player_lookup
        AND bg.game_date = mf.game_date
    ),

    -- Compute final features
    final_features AS (
      SELECT
        player_lookup,
        game_date,
        game_id,
        actual_points,
        is_breakout,

        -- Feature 1: pts_vs_season_zscore (compute consistently)
        SAFE_DIVIDE(
          points_avg_last_5 - points_avg_season,
          NULLIF(points_std_last_10, 0)
        ) as pts_vs_season_zscore,

        -- Feature 2: points_std_last_10
        points_std_last_10,

        -- Feature 3: explosion_ratio (max recent / season avg)
        COALESCE(
          SAFE_DIVIDE(max_points_recent, points_avg_season),
          {FEATURE_DEFAULTS['explosion_ratio']}
        ) as explosion_ratio,

        -- Feature 4: days_since_breakout
        COALESCE(
          DATE_DIFF(game_date, last_breakout_date, DAY),
          {FEATURE_DEFAULTS['days_since_breakout']}
        ) as days_since_breakout,

        -- Feature 5: opponent_def_rating (from feature store)
        feature_store_values,
        feature_store_names,

        -- Context for debugging
        points_avg_season,
        points_avg_last_5,
        points_avg_last_10,
        minutes_avg_last_10,
        max_points_recent,
        last_breakout_date

      FROM with_context
    )

    SELECT * FROM final_features
    ORDER BY game_date, player_lookup
    """


def extract_feature_from_store(
    features: List[float],
    feature_names: List[str],
    target_name: str,
    default: float,
) -> float:
    """
    Extract a single feature from feature store arrays.

    Args:
        features: Array of feature values from ml_feature_store_v2
        feature_names: Array of feature names
        target_name: Name of feature to extract
        default: Default value if not found

    Returns:
        Feature value or default
    """
    if features is None or feature_names is None:
        return default

    try:
        if target_name in feature_names:
            idx = feature_names.index(target_name)
            if idx < len(features) and features[idx] is not None:
                return float(features[idx])
    except (ValueError, IndexError, TypeError):
        pass

    return default


def prepare_feature_vector(
    row: pd.Series,
    validate: bool = True,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    Prepare feature vector from a DataFrame row.

    This is the SINGLE function that should be used for preparing features
    for both training and inference.

    Args:
        row: DataFrame row with columns from get_training_data_query()
        validate: If True, validate feature distributions

    Returns:
        Tuple of (feature_vector, feature_dict)
        - feature_vector: numpy array of shape (1, 10)
        - feature_dict: dict mapping feature names to values (for debugging)
    """
    # Extract feature store arrays
    fs_values = row.get('feature_store_values')
    fs_names = row.get('feature_store_names')

    if fs_values is not None:
        fs_values = [float(v) if v is not None else None for v in fs_values]
    if fs_names is not None:
        fs_names = list(fs_names)

    # Build feature dict
    features = {}

    # Feature 1: pts_vs_season_zscore (from query computation)
    zscore = row.get('pts_vs_season_zscore')
    features['pts_vs_season_zscore'] = float(zscore) if zscore is not None and not pd.isna(zscore) else FEATURE_DEFAULTS['pts_vs_season_zscore']

    # Feature 2: points_std_last_10 (from query)
    std = row.get('points_std_last_10')
    features['points_std_last_10'] = float(std) if std is not None and not pd.isna(std) else FEATURE_DEFAULTS['points_std_last_10']

    # Feature 3: explosion_ratio (from query)
    explosion = row.get('explosion_ratio')
    features['explosion_ratio'] = float(explosion) if explosion is not None and not pd.isna(explosion) else FEATURE_DEFAULTS['explosion_ratio']

    # Feature 4: days_since_breakout (from query)
    days = row.get('days_since_breakout')
    features['days_since_breakout'] = float(days) if days is not None and not pd.isna(days) else FEATURE_DEFAULTS['days_since_breakout']

    # Feature 5: opponent_def_rating (from feature store)
    features['opponent_def_rating'] = extract_feature_from_store(
        fs_values, fs_names, 'opponent_def_rating', FEATURE_DEFAULTS['opponent_def_rating']
    )

    # Feature 6: home_away (from feature store)
    features['home_away'] = extract_feature_from_store(
        fs_values, fs_names, 'home_away', FEATURE_DEFAULTS['home_away']
    )

    # Feature 7: back_to_back (from feature store)
    features['back_to_back'] = extract_feature_from_store(
        fs_values, fs_names, 'back_to_back', FEATURE_DEFAULTS['back_to_back']
    )

    # Feature 8: points_avg_last_5 (from query)
    avg5 = row.get('points_avg_last_5')
    features['points_avg_last_5'] = float(avg5) if avg5 is not None and not pd.isna(avg5) else FEATURE_DEFAULTS['points_avg_last_5']

    # Feature 9: points_avg_season (from query)
    avg_season = row.get('points_avg_season')
    features['points_avg_season'] = float(avg_season) if avg_season is not None and not pd.isna(avg_season) else FEATURE_DEFAULTS['points_avg_season']

    # Feature 10: minutes_avg_last_10 (from query)
    mins = row.get('minutes_avg_last_10')
    features['minutes_avg_last_10'] = float(mins) if mins is not None and not pd.isna(mins) else FEATURE_DEFAULTS['minutes_avg_last_10']

    # Build vector in exact order
    vector = np.array([features[name] for name in BREAKOUT_FEATURE_ORDER]).reshape(1, -1)

    # Validate
    if validate:
        if np.any(np.isnan(vector)) or np.any(np.isinf(vector)):
            raise ValueError(f"Feature vector contains NaN/Inf: {features}")

    return vector, features


def validate_feature_distributions(
    df: pd.DataFrame,
    context: str = "unknown",
) -> Dict[str, Dict[str, float]]:
    """
    Validate and log feature distributions.

    Use this to compare training vs evaluation distributions.

    Args:
        df: DataFrame with feature columns
        context: Description for logging (e.g., "training", "evaluation")

    Returns:
        Dict mapping feature names to distribution stats
    """
    stats = {}

    for feature in BREAKOUT_FEATURE_ORDER:
        if feature in df.columns:
            values = pd.to_numeric(df[feature], errors='coerce').dropna()
            stats[feature] = {
                'mean': float(values.mean()),
                'std': float(values.std()),
                'min': float(values.min()),
                'max': float(values.max()),
                'null_pct': float(df[feature].isna().mean() * 100),
            }

    print(f"\n=== Feature Distributions ({context}) ===")
    for feature, s in stats.items():
        print(f"  {feature}: mean={s['mean']:.3f}, std={s['std']:.3f}, "
              f"range=[{s['min']:.3f}, {s['max']:.3f}], null={s['null_pct']:.1f}%")

    return stats
