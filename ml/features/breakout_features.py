"""
Shared Breakout Classifier Feature Computation Module

This module provides a SINGLE SOURCE OF TRUTH for breakout feature computation.
Both training (breakout_experiment_runner.py) and evaluation (backfill_breakout_shadow.py)
should use this module to ensure feature consistency.

Session 134 Learning: Training and evaluation used different feature pipelines,
causing the model to have AUC 0.47 (worse than random) on holdout data.

V3 Feature List (13 features in exact order):
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
11. minutes_increase_pct - Minutes trend (V2 - only good V2 feature)
12. star_teammate_out - Star teammates OUT/DOUBTFUL (V3 - HIGH IMPACT)
13. fg_pct_last_game - Previous game shooting % (V3 - momentum signal)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd

PROJECT_ID = "nba-props-platform"

# Exact feature order - DO NOT CHANGE
# This order must match what models are trained with
# V1: Original 10 features (used by breakout_v1_20251102_20260205.cbm)
# V2: Extended with 4 Tier 1 features (Session 135)
BREAKOUT_FEATURE_ORDER_V1 = [
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

BREAKOUT_FEATURE_ORDER_V2 = BREAKOUT_FEATURE_ORDER_V1 + [
    "minutes_increase_pct",    # V2: Recent minutes spike (L7 vs L10)
    "usage_rate_trend",        # V2: Rising usage rate
    "rest_days_numeric",       # V2: Fatigue/freshness
    "fourth_quarter_trust",    # V2: Coach trust (4Q mins %)
]

# V3: Contextual features for high-confidence predictions
BREAKOUT_FEATURE_ORDER_V3 = BREAKOUT_FEATURE_ORDER_V1 + [
    "minutes_increase_pct",    # V2: Recent minutes spike (only good V2 feature)
    "star_teammate_out",       # V3: Count of star teammates OUT/DOUBTFUL
    "fg_pct_last_game",        # V3: Shooting % in previous game
]

# Default to V3 for new training
BREAKOUT_FEATURE_ORDER = BREAKOUT_FEATURE_ORDER_V3

# Default values when features are missing
FEATURE_DEFAULTS = {
    # V1 features
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
    # V2 features (simplified with existing fields)
    "minutes_increase_pct": 0.0,     # No increase
    "usage_rate_trend": 0.0,         # No trend
    "rest_days_numeric": 1.0,        # 1 day rest (B2B)
    "fourth_quarter_trust": 25.0,    # 25% of minutes in 4Q (neutral)
    # V3 features (contextual opportunity signals)
    "star_teammate_out": 0.0,        # No star teammates out
    "fg_pct_last_game": 0.45,        # League average FG%
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
        pgs.team_abbr,
        pgs.points as actual_points,
        pgs.minutes_played,
        dc.points_avg_season,
        dc.points_std_last_10,
        dc.points_avg_last_5,
        dc.points_avg_last_10,
        dc.minutes_avg_last_10,
        dc.avg_minutes_per_game_last_7,  -- V2: For minutes trend
        dc.usage_rate_last_10,  -- V2: For usage_rate_trend
        dc.player_usage_rate_season,  -- V2: For usage_rate_trend
        dc.games_in_last_7_days,  -- V2: For rest calculation
        dc.fourth_quarter_minutes_last_7,  -- V2: Coach trust indicator
        dc.minutes_in_last_7_days,  -- V2: For 4Q trust calculation
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

    -- V3: Get previous game performance for momentum features
    previous_game_performance AS (
      SELECT
        bg.player_lookup,
        bg.game_date as target_date,
        SAFE_DIVIDE(pgs_prev.fg_makes, pgs_prev.fg_attempts) as fg_pct_last_game
      FROM base_games bg
      LEFT JOIN (
        SELECT
          player_lookup,
          game_date,
          fg_makes,
          fg_attempts,
          LEAD(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as next_game_date
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE minutes_played > 0
      ) pgs_prev
        ON pgs_prev.player_lookup = bg.player_lookup
        AND pgs_prev.next_game_date = bg.game_date
    ),

    -- V3: Count star teammates OUT for usage opportunity
    star_teammates_out_calc AS (
      SELECT
        bg.player_lookup,
        bg.game_date as target_date,
        COUNT(DISTINCT CASE
          WHEN ir.injury_status IN ('out', 'doubtful')
            AND dc_teammate.points_avg_season >= 15.0  -- Star threshold (15+ PPG)
            AND ir.player_lookup != bg.player_lookup  -- Exclude self
          THEN ir.player_lookup
          ELSE NULL
        END) as star_teammate_out
      FROM base_games bg
      LEFT JOIN `{PROJECT_ID}.nba_raw.nbac_injury_report` ir
        ON ir.game_date = bg.game_date
        AND ir.team = bg.team_abbr  -- Same team
      LEFT JOIN `{PROJECT_ID}.nba_precompute.player_daily_cache` dc_teammate
        ON dc_teammate.player_lookup = ir.player_lookup
        AND dc_teammate.cache_date = ir.game_date
      GROUP BY bg.player_lookup, bg.game_date
    ),

    -- Join with feature store for context features
    with_context AS (
      SELECT
        bg.*,
        ra.max_points_recent,
        bh.last_breakout_date,
        pgp.fg_pct_last_game,
        sto.star_teammate_out,
        mf.features as feature_store_values,
        mf.feature_names as feature_store_names
      FROM base_games bg
      LEFT JOIN recent_aggregates ra
        ON bg.player_lookup = ra.player_lookup
        AND bg.game_date = ra.target_date
      LEFT JOIN breakout_history bh
        ON bg.player_lookup = bh.player_lookup
        AND bg.game_date = bh.target_date
      LEFT JOIN previous_game_performance pgp
        ON bg.player_lookup = pgp.player_lookup
        AND bg.game_date = pgp.target_date
      LEFT JOIN star_teammates_out_calc sto
        ON bg.player_lookup = sto.player_lookup
        AND bg.game_date = sto.target_date
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

        -- Feature 5-10: From feature store (extracted in prepare_feature_vector)
        feature_store_values,
        feature_store_names,

        -- V2 FEATURES (Simplified - using only existing fields)

        -- Feature 11: minutes_increase_pct (L7 vs L10)
        COALESCE(
          SAFE_DIVIDE(
            avg_minutes_per_game_last_7 - minutes_avg_last_10,
            NULLIF(minutes_avg_last_10, 0)
          ),
          {FEATURE_DEFAULTS['minutes_increase_pct']}
        ) as minutes_increase_pct,

        -- Feature 12: usage_rate_trend
        COALESCE(
          usage_rate_last_10 - player_usage_rate_season,
          {FEATURE_DEFAULTS['usage_rate_trend']}
        ) as usage_rate_trend,

        -- Feature 13: rest_days_numeric (approximation from games_in_last_7_days)
        CASE
          WHEN games_in_last_7_days >= 6 THEN 1.0  -- Back-to-back territory
          WHEN games_in_last_7_days >= 4 THEN 1.5  -- Heavy schedule
          WHEN games_in_last_7_days >= 3 THEN 2.0  -- Normal schedule
          WHEN games_in_last_7_days >= 2 THEN 2.5  -- Light schedule
          ELSE 3.5  -- Well rested
        END as rest_days_numeric,

        -- Feature 14: fourth_quarter_trust (4Q minutes as % of total)
        COALESCE(
          SAFE_DIVIDE(
            fourth_quarter_minutes_last_7,
            NULLIF(minutes_in_last_7_days, 0)
          ) * 100,
          {FEATURE_DEFAULTS['fourth_quarter_trust']}
        ) as fourth_quarter_trust,

        -- V3 FEATURES (Contextual Opportunity Signals)

        -- Feature 12 (V3): star_teammate_out
        COALESCE(star_teammate_out, {FEATURE_DEFAULTS['star_teammate_out']}) as star_teammate_out,

        -- Feature 13 (V3): fg_pct_last_game
        COALESCE(fg_pct_last_game, {FEATURE_DEFAULTS['fg_pct_last_game']}) as fg_pct_last_game,

        -- Context for debugging
        points_avg_season,
        points_avg_last_5,
        points_avg_last_10,
        minutes_avg_last_10,
        avg_minutes_per_game_last_7,
        usage_rate_last_10,
        player_usage_rate_season,
        games_in_last_7_days,
        fourth_quarter_minutes_last_7,
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
        - feature_vector: numpy array of shape (1, 14) for V2, (1, 10) for V1
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

    # V2 FEATURES (Tier 1 Quick Wins)

    # Feature 11: minutes_increase_pct (from query)
    mins_inc = row.get('minutes_increase_pct')
    features['minutes_increase_pct'] = float(mins_inc) if mins_inc is not None and not pd.isna(mins_inc) else FEATURE_DEFAULTS['minutes_increase_pct']

    # Feature 12: usage_rate_trend (from query)
    usage_trend = row.get('usage_rate_trend')
    features['usage_rate_trend'] = float(usage_trend) if usage_trend is not None and not pd.isna(usage_trend) else FEATURE_DEFAULTS['usage_rate_trend']

    # Feature 13: rest_days_numeric (from query)
    rest_days = row.get('rest_days_numeric')
    features['rest_days_numeric'] = float(rest_days) if rest_days is not None and not pd.isna(rest_days) else FEATURE_DEFAULTS['rest_days_numeric']

    # Feature 14: fourth_quarter_trust (from query)
    q4_trust = row.get('fourth_quarter_trust')
    features['fourth_quarter_trust'] = float(q4_trust) if q4_trust is not None and not pd.isna(q4_trust) else FEATURE_DEFAULTS['fourth_quarter_trust']

    # V3 FEATURES (Contextual Opportunity Signals)

    # Feature 12 (V3): star_teammate_out (from query)
    star_out = row.get('star_teammate_out')
    features['star_teammate_out'] = float(star_out) if star_out is not None and not pd.isna(star_out) else FEATURE_DEFAULTS['star_teammate_out']

    # Feature 13 (V3): fg_pct_last_game (from query)
    fg_pct_prev = row.get('fg_pct_last_game')
    features['fg_pct_last_game'] = float(fg_pct_prev) if fg_pct_prev is not None and not pd.isna(fg_pct_prev) else FEATURE_DEFAULTS['fg_pct_last_game']

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
