# File: data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
"""
ML Feature Store V2 Processor - Phase 4 Precompute
==================================================

Generates feature vectors for ML predictions by extracting data from
Phase 3 analytics and Phase 4 precompute tables.

Schedule: Nightly at 12:00 AM (AFTER all other Phase 4 processors)
Duration: ~2 minutes for 450 players
Output: nba_predictions.ml_feature_store_v2

Features Generated: 25 total
- 19 direct copy from Phase 3/4
- 6 calculated on-the-fly (indices 9-12, 21, 24)

CRITICAL: This processor runs LAST in Phase 4 because it depends on:
- player_daily_cache (11:45 PM)
- player_composite_factors (11:30 PM)
- player_shot_zone_analysis (11:15 PM)
- team_defense_zone_analysis (11:00 PM)

Version: 2.0 (Added v4.0 dependency tracking)
Date: November 6, 2025
"""

import logging
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
import pandas as pd
from google.cloud import bigquery

from data_processors.precompute.base import PrecomputeProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin
from shared.config.source_coverage import get_tier_from_score  # Legacy, still used by early-season path
from data_processors.precompute.ml_feature_store.quality_scorer import get_feature_quality_tier

# Smart Idempotency (Pattern #1)
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Completeness checking (Week 4 - Phase 4 Cascade Dependencies)
from shared.utils.completeness_checker import CompletenessChecker

from .feature_extractor import FeatureExtractor
from .feature_calculator import FeatureCalculator
from .quality_scorer import QualityScorer
from .batch_writer import BatchWriter
from .breakout_risk_calculator import BreakoutRiskCalculator

# Bootstrap period support (Week 5 - Early Season Handling)
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.validation.config import BOOTSTRAP_DAYS

# Historical Completeness Tracking (Data Cascade Architecture - Jan 2026)
from shared.validation.historical_completeness import (
    assess_historical_completeness,
    should_skip_feature_generation,
    HistoricalCompletenessResult,
    WINDOW_SIZE,
    MINIMUM_GAMES_THRESHOLD
)

# Configure logging
logger = logging.getLogger(__name__)

# Session 97: Phase 4 Completion Gate
# Minimum records required to consider Phase 4 "complete" for a game date
# Lower threshold for dates with few games (e.g., 4 games = ~100 players)
PHASE4_MINIMUM_RECORDS = 50
# Maximum data staleness for SAME-DAY processing (hours)
# For historical dates, we only check existence, not staleness
PHASE4_MAX_STALENESS_HOURS = 6

# Feature version and names
# v2_33features: Added 8 features for V8 model (Vegas, opponent, minutes/efficiency)
# v2_37features: Added 4 features (DNP rate + 3 player trajectory) - current version
# v2_38features: Added breakout_risk_score (Session 126 - Feb 2026)
# - Composite 0-100 score predicting role player breakout probability
# v2_39features: Added composite_breakout_signal (Session 126 - Feb 2026)
# - 0-5 score combining top predictive factors (37% breakout rate at 4+)
# v2_39features (Session 226): Replaced disabled breakout features (37-38) with
# star_teammates_out and game_total_line for V11 experiments.
# V9/V10 models are unaffected (name-based extraction ignores extra features).
# v2_54features (Session 230): Extended with 15 V12 features (39-53) for
# scoring trends, usage, fatigue, streaks, structural changes.
FEATURE_VERSION = 'v2_60features'
FEATURE_COUNT = 60

FEATURE_NAMES = [
    # Recent Performance (0-4)
    'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
    'points_std_last_10', 'games_in_last_7_days',

    # Composite Factors (5-8)
    'fatigue_score', 'shot_zone_mismatch_score', 'pace_score', 'usage_spike_score',

    # Derived Factors (9-12)
    'rest_advantage', 'injury_risk', 'recent_trend', 'minutes_change',

    # Matchup Context (13-17)
    'opponent_def_rating', 'opponent_pace', 'home_away', 'back_to_back', 'playoff_game',

    # Shot Zones (18-21)
    'pct_paint', 'pct_mid_range', 'pct_three', 'pct_free_throw',

    # Team Context (22-24)
    'team_pace', 'team_off_rating', 'team_win_pct',

    # Vegas Lines (25-28) - V8 Model Features
    'vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line',

    # Opponent History (29-30) - V8 Model Features
    'avg_points_vs_opponent', 'games_vs_opponent',

    # Minutes/Efficiency (31-32) - V8 Model Features (14.6% + 10.9% importance)
    'minutes_avg_last_10', 'ppm_avg_last_10',

    # DNP Risk (33) - v2.1 Gamebook-based DNP pattern detection
    'dnp_rate',

    # Player Trajectory (34-36) - Session 28 model degradation fix
    # Captures whether players are trending up/down to adapt to NBA dynamics shift
    'pts_slope_10g',        # Linear regression slope of points over L10
    'pts_vs_season_zscore', # Z-score of L5 avg vs season avg
    'breakout_flag',        # 1.0 if L5 > season_avg + 1.5*std

    # V11 Features (37-38) - Session 226 (replaces disabled breakout features)
    'star_teammates_out',   # Count of star teammates OUT/DOUBTFUL (18+ PPG / 28+ MPG / 25%+ usage)
    'game_total_line',      # Game total over/under line from odds API

    # V12 Features (39-53) - Session 230 (feature store extension)
    'days_rest',                      # 39: From UPCG.days_rest
    'minutes_load_last_7d',           # 40: From UPCG.minutes_in_last_7_days
    'spread_magnitude',               # 41: abs(UPCG.game_spread) — dead feature, default 5.0
    'implied_team_total',             # 42: (game_total ± spread)/2 — dead feature, default 112.0
    'points_avg_last_3',              # 43: Ultra-short average from rolling stats
    'scoring_trend_slope',            # 44: OLS slope last 7 games
    'deviation_from_avg_last3',       # 45: Z-score of L3 avg vs 60-day avg
    'consecutive_games_below_avg',    # 46: Cold streak counter
    'teammate_usage_available',       # 47: Dead feature, always 0.0
    'usage_rate_last_5',              # 48: Recent usage rate average
    'games_since_structural_change',  # 49: Games since trade/ASB/return
    'multi_book_line_std',            # 50: Dead feature, always 0.5
    'prop_over_streak',               # 51: Consecutive games over prop line
    'prop_under_streak',              # 52: Consecutive games under prop line
    'line_vs_season_avg',             # 53: vegas_line - season_avg (or 0.0)

    # Feature 54: prop_line_delta (Session 294)
    'prop_line_delta',                # 54: current_line - previous_game_line

    # V16 Features (55-56) - Session 356 (prop line history)
    'over_rate_last_10',              # 55: Fraction of last 10 where actual > prop_line
    'margin_vs_line_avg_last_5',      # 56: Mean(actual - prop_line) over last 5

    # V17 Features (57-59) - Session 360 (opportunity risk)
    'blowout_minutes_risk',           # 57: Fraction of team's L10 games with 15+ margin
    'minutes_volatility_last_10',     # 58: Stdev of player minutes over L10
    'opponent_pace_mismatch',         # 59: team_pace - opponent_pace
]

# ============================================================================
# FEATURE VALIDATION RANGES (Session 48 - Pre-write validation)
# ============================================================================
# Maps feature index to (min, max, is_critical) - critical features block writes
# Added to catch bugs like fatigue_score=0 before data is written to BigQuery
# This would have caught the Jan 25-30 fatigue bug within 1 hour instead of 6 days
ML_FEATURE_RANGES = {
    # Recent Performance (0-4) - wide ranges, not critical
    0: (0, 70, False, 'points_avg_last_5'),       # Typical: 0-50
    1: (0, 70, False, 'points_avg_last_10'),
    2: (0, 70, False, 'points_avg_season'),
    3: (0, 30, False, 'points_std_last_10'),
    4: (0, 4, False, 'games_in_last_7_days'),

    # Composite Factors (5-8) - CRITICAL - these have caused bugs
    5: (0, 100, True, 'fatigue_score'),           # CRITICAL: Must be 0-100, not adjustment
    6: (-15, 15, False, 'shot_zone_mismatch_score'),
    7: (-8, 8, False, 'pace_score'),
    8: (-8, 8, False, 'usage_spike_score'),

    # Derived Factors (9-12)
    9: (-3, 3, False, 'rest_advantage'),
    10: (0, 3, False, 'injury_risk'),
    11: (-2, 2, False, 'recent_trend'),
    12: (-2, 2, False, 'minutes_change'),

    # Matchup Context (13-17)
    13: (90, 130, False, 'opponent_def_rating'),
    14: (90, 115, False, 'opponent_pace'),
    15: (0, 1, False, 'home_away'),
    16: (0, 1, False, 'back_to_back'),
    17: (0, 1, False, 'playoff_game'),

    # Shot Zones (18-21)
    18: (0, 1, False, 'pct_paint'),
    19: (0, 1, False, 'pct_mid_range'),
    20: (0, 1, False, 'pct_three'),
    21: (0, 0.5, False, 'pct_free_throw'),

    # Team Context (22-24)
    22: (90, 115, False, 'team_pace'),
    23: (90, 130, False, 'team_off_rating'),
    24: (0, 1, False, 'team_win_pct'),

    # Vegas Lines (25-28) - high importance, check ranges
    25: (0, 80, False, 'vegas_points_line'),       # Typical: 5-50
    26: (0, 80, False, 'vegas_opening_line'),
    27: (-15, 15, False, 'vegas_line_move'),
    28: (0, 1, False, 'has_vegas_line'),

    # Opponent History (29-30)
    29: (0, 70, False, 'avg_points_vs_opponent'),
    30: (0, 100, False, 'games_vs_opponent'),  # Session 50: data shows max 76 (multi-season)

    # Minutes/Efficiency (31-32) - high model importance
    31: (0, 48, False, 'minutes_avg_last_10'),
    32: (0, 1.5, False, 'ppm_avg_last_10'),  # Session 50: p99=1.0, max realistic ~1.2

    # DNP Risk (33)
    33: (0, 1, False, 'dnp_rate'),

    # Player Trajectory (34-36)
    34: (-5, 5, False, 'pts_slope_10g'),
    35: (-4, 4, False, 'pts_vs_season_zscore'),
    36: (0, 1, False, 'breakout_flag'),

    # V11 Features (37-38) - Session 226
    37: (0, 5, False, 'star_teammates_out'),     # 0-5 star teammates out
    38: (180, 280, False, 'game_total_line'),     # Typical game totals 200-260

    # V12 Features (39-53) - Session 230
    39: (0, 10, False, 'days_rest'),              # 0-10 days rest
    40: (0, 250, False, 'minutes_load_last_7d'),  # 0-250 minutes in 7 days
    41: (0, 25, False, 'spread_magnitude'),        # abs(spread), 0-25
    42: (90, 140, False, 'implied_team_total'),    # (total +/- spread)/2
    43: (0, 70, False, 'points_avg_last_3'),       # Ultra-short average
    44: (-5, 5, False, 'scoring_trend_slope'),     # OLS slope
    45: (-4, 4, False, 'deviation_from_avg_last3'),# Z-score
    46: (0, 20, False, 'consecutive_games_below_avg'), # Cold streak
    47: (0, 100, False, 'teammate_usage_available'), # NOT dead (avg=44), total usage of available teammates
    48: (0, 40, False, 'usage_rate_last_5'),       # Usage %
    49: (0, 60, False, 'games_since_structural_change'), # Games since change
    50: (0, 5, False, 'multi_book_line_std'),      # Dead feature (always 0.5)
    51: (0, 20, False, 'prop_over_streak'),        # Consecutive overs
    52: (0, 20, False, 'prop_under_streak'),       # Consecutive unders
    53: (-30, 30, False, 'line_vs_season_avg'),    # Line - season avg
    54: (-20, 20, False, 'prop_line_delta'),       # Line change from prev game (Session 294)

    # V16 Features (55-56) - Session 356
    55: (0, 1, False, 'over_rate_last_10'),       # Rate [0.0-1.0]
    56: (-25, 25, False, 'margin_vs_line_avg_last_5'),  # Points margin

    # V17 Features (57-59) - Session 360
    57: (0, 1, False, 'blowout_minutes_risk'),     # Rate [0.0-1.0]
    58: (0, 20, False, 'minutes_volatility_last_10'),  # Stdev of minutes
    59: (-20, 20, False, 'opponent_pace_mismatch'),    # Pace difference
}


def validate_feature_ranges(features: list, player_lookup: str = None) -> tuple:
    """
    Validate feature values against expected ranges BEFORE writing to BigQuery.

    This is a critical prevention mechanism that catches data quality bugs
    at write time instead of waiting for model degradation (5+ days).

    Args:
        features: List of 39 feature values
        player_lookup: Player identifier for logging

    Returns:
        (is_valid, warnings, critical_errors)
        - is_valid: True if no critical errors
        - warnings: List of non-critical range violations (logged but written)
        - critical_errors: List of critical violations (blocks write)
    """
    warnings = []
    critical_errors = []

    for idx, value in enumerate(features):
        if value is None:
            continue  # NULL values are allowed for missing data

        if idx not in ML_FEATURE_RANGES:
            continue  # No range defined for this feature

        min_val, max_val, is_critical, feature_name = ML_FEATURE_RANGES[idx]

        if value < min_val or value > max_val:
            msg = f"{feature_name}[{idx}]={value:.2f} outside [{min_val}, {max_val}]"
            if is_critical:
                critical_errors.append(msg)
                logger.error(f"CRITICAL_VALIDATION [{player_lookup}]: {msg}")
            else:
                warnings.append(msg)
                # Only log warnings at debug level to reduce noise
                logger.debug(f"VALIDATION_WARNING [{player_lookup}]: {msg}")

    is_valid = len(critical_errors) == 0
    return is_valid, warnings, critical_errors


# ============================================================================
# FEATURE VARIANCE THRESHOLDS (Session 49 - Pre-write variance validation)
# ============================================================================
# Maps feature index to (min_stddev, min_distinct, feature_name)
# Features with variance below threshold across a batch indicate potential bugs
# where calculations are returning constant/default values (e.g., team_win_pct=0.5)
FEATURE_VARIANCE_THRESHOLDS = {
    # Team Context - these MUST vary across players/teams
    22: (0.5, 5, 'team_pace'),           # 30 teams, pace varies 95-110
    23: (1.0, 5, 'team_off_rating'),     # 30 teams, rating varies 100-120
    24: (0.05, 5, 'team_win_pct'),       # CRITICAL: Caught the 0.5 bug

    # Vegas Lines - should vary per player
    25: (2.0, 10, 'vegas_points_line'),  # Lines typically 5-50

    # Recent Performance - highly variable across players
    0: (3.0, 20, 'points_avg_last_5'),   # Players score 0-50 PPG
    1: (3.0, 20, 'points_avg_last_10'),
    2: (3.0, 20, 'points_avg_season'),

    # Fatigue/Composite - should vary based on game schedule
    5: (5.0, 10, 'fatigue_score'),       # CRITICAL: Caught the Jan 25-30 bug
    6: (1.0, 10, 'shot_zone_mismatch_score'),

    # Minutes context
    31: (5.0, 15, 'minutes_avg_last_10'),  # Varies 0-40 mins

    # Session 375: Expanded coverage to catch constant-value bugs like Feature 41
    3: (1.0, 10, 'points_std_last_10'),    # Scoring variance across players
    13: (1.0, 5, 'opponent_def_rating'),   # 30 teams, rating varies 100-120
    14: (0.5, 5, 'opponent_pace'),         # 30 teams, pace varies 95-110
    32: (0.1, 10, 'ppm_avg_last_10'),      # Points per minute, varies 0-1.2
    38: (2.0, 5, 'game_total_line'),       # Game totals 200-260
    41: (1.0, 5, 'spread_magnitude'),      # THE BUG: was ALL ZEROS for 4 months
    42: (2.0, 5, 'implied_team_total'),    # Derived from total/spread, varies 100-130
    43: (3.0, 15, 'points_avg_last_3'),    # Ultra-short avg, highly variable
    47: (2.0, 10, 'teammate_usage_available'),  # NOT dead (avg=44), varies 0-100
    48: (2.0, 10, 'usage_rate_last_5'),    # Usage %, varies 5-35
}


def validate_batch_variance(records: list, min_records: int = 50) -> dict:
    """
    Validate feature variance across a batch BEFORE writing.

    Detects bugs where calculated features return constant/default values
    (like team_win_pct always being 0.5 due to missing team_abbr passthrough).

    Args:
        records: List of ML feature store records with 'features' key
        min_records: Minimum records required for variance check

    Returns:
        Dict with is_valid, warnings, critical_errors, stats
    """
    import numpy as np
    from collections import defaultdict

    if len(records) < min_records:
        return {
            'is_valid': True,
            'warnings': [],
            'critical_errors': [],
            'stats': {},
            'reason': f'Skipped: only {len(records)} records (need {min_records})'
        }

    warnings = []
    critical_errors = []
    stats = {}

    # Extract feature arrays
    feature_values = defaultdict(list)
    for record in records:
        features = record.get('features', [])
        for idx, value in enumerate(features):
            if value is not None:
                feature_values[idx].append(value)

    # Check variance for monitored features
    for idx, (min_variance, min_distinct, feature_name) in FEATURE_VARIANCE_THRESHOLDS.items():
        values = feature_values.get(idx, [])

        if len(values) < min_records // 2:
            continue  # Not enough data for this feature

        arr = np.array(values)
        variance = float(np.std(arr))
        distinct_values = len(set(round(v, 4) for v in values))
        mean = float(np.mean(arr))

        stats[feature_name] = {
            'stddev': variance,
            'distinct_values': distinct_values,
            'mean': mean,
            'count': len(values)
        }

        # Check for zero/near-zero variance (constant value)
        if variance < 0.0001 and distinct_values == 1:
            msg = (f"ZERO_VARIANCE: {feature_name}[{idx}] = {mean:.4f} "
                   f"(all {len(values)} values identical)")
            critical_errors.append(msg)
            logger.error(f"CRITICAL_VARIANCE: {msg}")

        # Check for suspiciously low variance
        elif variance < min_variance or distinct_values < min_distinct:
            msg = (f"LOW_VARIANCE: {feature_name}[{idx}] "
                   f"stddev={variance:.4f} < {min_variance}, "
                   f"distinct={distinct_values} < {min_distinct}")
            warnings.append(msg)
            logger.warning(f"VARIANCE_WARNING: {msg}")

    is_valid = len(critical_errors) == 0

    return {
        'is_valid': is_valid,
        'warnings': warnings,
        'critical_errors': critical_errors,
        'stats': stats
    }


class MLFeatureStoreProcessor(
    SmartIdempotencyMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase
):
    """
    Generate and cache 34 ML features for all active NBA players.

    This is a Phase 4 processor that:
    1. Checks Phase 4 dependencies (hard requirements)
    2. Queries Phase 4 tables for player data (preferred)
    3. Falls back to Phase 3 if Phase 4 incomplete
    4. Calculates 7 derived features (including dnp_rate)
    5. Extracts 8 V8 model features (Vegas, opponent, minutes/efficiency)
    6. Scores feature quality (0-100)
    7. Writes to nba_predictions.ml_feature_store_v2 in batches

    v2.0 (Nov 2025): Added v4.0 dependency tracking
    v3.0 (Jan 2026): Upgraded to 33 features for V8 CatBoost model
    v3.1 (Jan 2026): Added Feature 33: dnp_rate (gamebook DNP pattern detection)

    Consumers: All 5 Phase 5 prediction systems (especially CatBoost V8)
    """
    
    # Processor configuration
    table_name = "ml_feature_store_v2"
    dataset_id = "nba_predictions"  # Cross-dataset write!

    # Required options
    required_opts = ['analysis_date']

    # Feature version
    feature_version = FEATURE_VERSION
    feature_count = FEATURE_COUNT

    # Defensive check configuration (upstream Phase 3 dependency)
    upstream_processor_name = 'PlayerGameSummaryProcessor'
    upstream_table = 'nba_analytics.player_game_summary'
    lookback_days = 10  # Must match feature requirements

    # Smart Idempotency: Fields to hash (meaningful business fields only)
    HASH_FIELDS = [
        'player_lookup', 'universal_player_id', 'game_date', 'game_id',
        'features', 'feature_names', 'feature_count', 'feature_version',
        'feature_quality_score', 'opponent_team_abbr', 'is_home', 'days_rest',
        'data_source', 'early_season_flag', 'insufficient_data_reason'
    ]

    # Primary key fields for duplicate detection and MERGE operations
    PRIMARY_KEY_FIELDS = ['game_date', 'player_lookup']

    def __init__(self):
        """Initialize processor and helper classes."""
        super().__init__()

        # Initialize completeness checker (Week 4 - Cascade Dependencies)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # Helper classes
        self.feature_extractor = FeatureExtractor(self.bq_client, self.project_id)
        self.feature_calculator = FeatureCalculator()
        self.quality_scorer = QualityScorer()
        self.batch_writer = BatchWriter(self.bq_client, self.project_id)
        self.breakout_risk_calculator = BreakoutRiskCalculator()

        # Data storage
        self.players_with_games = None

        # Source hash cache (4 Phase 4 dependencies)
        self.source_daily_cache_hash = None
        self.source_composite_hash = None
        self.source_shot_zones_hash = None
        self.source_team_defense_hash = None

        # Season start date (for completeness checking - Week 4)
        self.season_start_date = None

        # Tracking
        self.early_season_flag = False
        self.insufficient_data_reason = None
        self.failed_entities = []

        # Timing instrumentation (added for performance optimization tracking)
        self._timing = {}

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 4 Precompute sources - RELEVANT (CRITICAL - depends on these)
        'player_daily_cache': True,
        'player_composite_factors': True,
        'player_shot_zone_analysis': True,
        'team_defense_zone_analysis': True,

        # Phase 3 Analytics sources - RELEVANT (fallback sources)
        'player_game_summary': True,
        'team_offense_game_summary': True,
        'team_defense_game_summary': True,
        'upcoming_player_game_context': True,
        'upcoming_team_game_context': True,

        # Phase 2 Raw sources - NOT RELEVANT (reads from Phase 3/4, not Phase 2)
        'nbac_gamebook_player_stats': False,
        'bdl_player_boxscores': False,
        'nbac_team_boxscore': False,
        'odds_api_player_points_props': False,
        'odds_api_game_lines': False,
        'nbac_schedule': False,
        'bigdataball_play_by_play': False,
        'nbac_play_by_play': False,
        'nbac_injury_report': False
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = False      # Don't skip - generates features for next day
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - can generate for any future date

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Prevents retry storms by checking Phase 3 analytics data exists.
        ML Feature Store depends on player_game_summary (Phase 3) as foundation.

        Args:
            start_date: Start of date range (YYYY-MM-DD)
            end_date: End of date range (YYYY-MM-DD)

        Returns:
            SQL query that returns {data_available: boolean}
        """
        return f"""
        SELECT COUNT(*) > 0 AS data_available
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """

    # ============================================================
    # Soft Dependency Configuration (added after Jan 23 incident)
    # ============================================================
    # When enabled, processor can proceed with degraded upstream data if coverage > threshold
    # This prevents all-or-nothing blocking when upstream processors have partial failures
    use_soft_dependencies = True
    soft_dependency_threshold = 0.80  # Proceed if >80% upstream coverage

    # ========================================================================
    # DEPENDENCY CONFIGURATION (v4.0)
    # ========================================================================

    def get_dependencies(self) -> dict:
        """
        Define upstream Phase 4 data dependencies.

        Returns 4 critical sources with HARD requirements:
        - player_daily_cache (features 0-4, 18-20, 22-23)
        - player_composite_factors (features 5-8)
        - player_shot_zone_analysis (features 18-20)
        - team_defense_zone_analysis (features 13-14)

        Note: These are HARD dependencies - processor fails if missing
        (except during early season when placeholders are written).
        Phase 3 tables are fallback only, not tracked as dependencies.

        Thresholds are lowered in backfill mode to accommodate early season
        where fewer players have enough games for rolling calculations.
        """
        # Lower thresholds for backfill mode (early season has fewer players with history)
        # Production: 100 players expected, Backfill: 20 (minimum viable)
        player_threshold = 20 if self.is_backfill_mode else 100

        return {
            'nba_precompute.player_daily_cache': {
                'field_prefix': 'source_daily_cache',
                'description': 'Player performance cache (features 0-4, 18-20, 22-23)',
                'check_type': 'date_match',
                'date_field': 'cache_date',
                'expected_count_min': player_threshold,
                'max_age_hours': 2,  # Should be fresh (just ran at 11:45 PM)
                'critical': True
            },
            'nba_precompute.player_composite_factors': {
                'field_prefix': 'source_composite',
                'description': 'Composite adjustment factors (features 5-8)',
                'check_type': 'date_match',
                'date_field': 'game_date',
                'expected_count_min': player_threshold,
                'max_age_hours': 2,  # Should be fresh (just ran at 11:30 PM)
                'critical': True
            },
            'nba_precompute.player_shot_zone_analysis': {
                'field_prefix': 'source_shot_zones',
                'description': 'Player shot distribution (features 18-20)',
                'check_type': 'date_match',
                'date_field': 'analysis_date',
                'expected_count_min': player_threshold,
                'max_age_hours': 2,  # Should be fresh (just ran at 11:15 PM)
                'critical': True
            },
            'nba_precompute.team_defense_zone_analysis': {
                'field_prefix': 'source_team_defense',
                'description': 'Team defensive zones (features 13-14)',
                'check_type': 'date_match',
                'date_field': 'analysis_date',
                'expected_count_min': 20,  # At least 20 teams
                'max_age_hours': 2,  # Should be fresh (just ran at 11:00 PM)
                'critical': True
            }
        }

    # ========================================================================
    # SESSION 97: PHASE 4 COMPLETION GATE
    # ========================================================================

    def _check_phase4_completion_gate(self, analysis_date: str) -> tuple:
        """
        Verify Phase 4 data exists and is fresh before generating features.

        This gate prevents the Feb 2 issue (Session 96) where ML Feature Store
        ran BEFORE Phase 4 completed, causing predictions to use stale/default
        feature values (40 points instead of 100 points), resulting in 49.1% hit rate.

        Checks:
        1. player_daily_cache has sufficient records for the game_date
        2. player_composite_factors has sufficient records for the game_date
        3. For same-day processing: Data freshness within PHASE4_MAX_STALENESS_HOURS
        4. For historical processing: Only check data existence (staleness OK)

        Args:
            analysis_date: Target game date (YYYY-MM-DD)

        Returns:
            tuple: (is_complete: bool, details: str)
        """
        try:
            from datetime import date as date_type

            # Parse analysis_date
            if isinstance(analysis_date, str):
                target_date = date_type.fromisoformat(analysis_date)
            else:
                target_date = analysis_date

            today = date_type.today()
            is_same_day = (target_date == today)

            query = f"""
            WITH cache_check AS (
                SELECT
                    COUNT(*) as records,
                    MAX(created_at) as last_created
                FROM `{self.project_id}.nba_precompute.player_daily_cache`
                WHERE cache_date = DATE('{analysis_date}')
            ),
            composite_check AS (
                SELECT
                    COUNT(*) as records,
                    MAX(created_at) as last_created
                FROM `{self.project_id}.nba_precompute.player_composite_factors`
                WHERE game_date = DATE('{analysis_date}')
            )
            SELECT
                c.records as cache_records,
                c.last_created as cache_created,
                TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), c.last_created, HOUR) as cache_hours_old,
                f.records as composite_records,
                f.last_created as composite_created,
                TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), f.last_created, HOUR) as composite_hours_old
            FROM cache_check c, composite_check f
            """

            result = self.bq_client.query(query).result()
            row = next(iter(result), None)

            if not row:
                return False, "Query returned no results"

            cache_records = row.cache_records or 0
            composite_records = row.composite_records or 0
            cache_hours = row.cache_hours_old
            composite_hours = row.composite_hours_old

            issues = []

            # Check record counts (always required)
            if cache_records < PHASE4_MINIMUM_RECORDS:
                issues.append(f"player_daily_cache: {cache_records} records (need {PHASE4_MINIMUM_RECORDS}+)")
            if composite_records < PHASE4_MINIMUM_RECORDS:
                issues.append(f"player_composite_factors: {composite_records} records (need {PHASE4_MINIMUM_RECORDS}+)")

            # Check data freshness ONLY for same-day processing
            # For historical dates, data existence is sufficient
            if is_same_day:
                if cache_hours is not None and cache_hours > PHASE4_MAX_STALENESS_HOURS:
                    issues.append(f"player_daily_cache is {cache_hours}h old (max {PHASE4_MAX_STALENESS_HOURS}h for same-day)")
                if composite_hours is not None and composite_hours > PHASE4_MAX_STALENESS_HOURS:
                    issues.append(f"player_composite_factors is {composite_hours}h old (max {PHASE4_MAX_STALENESS_HOURS}h for same-day)")

            if issues:
                return False, "; ".join(issues)

            mode = "same-day" if is_same_day else "historical"
            details = (
                f"[{mode}] cache={cache_records} records ({cache_hours}h old), "
                f"composite={composite_records} records ({composite_hours}h old)"
            )
            return True, details

        except Exception as e:
            logger.error(f"Error checking Phase 4 completion: {e}")
            return False, f"Error: {str(e)}"

    # ========================================================================
    # DATA EXTRACTION
    # ========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract data from Phase 3/4 tables.

        Steps:
        1. Check Phase 4 dependencies (HARD requirements)
        2. Check for early season (>50% players lack data)
        3. Track source usage (v4.0 dependency tracking)
        4. Get list of players with games today

        Early season: Creates placeholders for all players
        Normal season: Phase 4 must be complete or processor fails
        """
        extract_start = time.time()

        if 'analysis_date' not in self.opts:
            raise ValueError("analysis_date required in opts")

        analysis_date = self.opts['analysis_date']
        logger.info(f"Extracting data for {analysis_date}")

        # Determine season year using schedule service (Bootstrap period - Week 5)
        season_year = self.opts.get('season_year')
        if season_year is None:
            season_year = get_season_year_from_date(analysis_date)
            self.opts['season_year'] = season_year
            logger.debug(f"Determined season year: {season_year} for date {analysis_date}")

        # Store season start date for completeness checking (Week 4)
        self.season_start_date = date(season_year, 10, 1)

        # NOTE: Dependency check was already performed by base class run() method.
        # We reuse the results stored in self.dependency_check_passed and self.source_metadata.
        # This avoids duplicate BQ queries that were causing performance issues.

        # BOOTSTRAP PERIOD: Check for early season BEFORE failing on missing dependencies
        # If early season (days 0-6), CREATE PLACEHOLDERS instead of failing
        # Session 144: skip_early_season_check allows backfill to generate real features
        # for bootstrap period dates where historical data now exists
        if not self.opts.get('skip_early_season_check', False) and self._is_early_season(analysis_date, season_year):
            logger.info(
                f"📝 Early season detected for {analysis_date} (day 0-6 of season {season_year}): "
                f"creating placeholder records with NULL features"
            )
            self._create_early_season_placeholders(analysis_date)
            self._timing['extract_raw_data'] = time.time() - extract_start
            return

        # Normal season: Phase 4 dependencies MUST be present
        # (Already checked by base class, but we log stale data warning here for MLFS-specific context)
        if self.missing_dependencies_list:
            logger.warning(f"Stale Phase 4 data detected (from base class check)")

        # Session 97: Phase 4 Completion Gate
        # Verify Phase 4 data exists and is fresh before proceeding
        # This prevents using stale features that caused Feb 2 49.1% hit rate
        # Skip gate in backfill mode - backfill is explicitly for reprocessing with existing data
        # Session 95 Amendment: Also skip when skip_dependency_check=True (upcoming games mode)
        # For upcoming games, Phase 4 won't have today's data - we use fallback queries instead
        skip_phase4_gate = self.is_backfill_mode or self.opts.get('skip_dependency_check', False)
        if skip_phase4_gate:
            skip_reason = "backfill mode" if self.is_backfill_mode else "upcoming games mode (skip_dependency_check=True)"
            logger.info(f"SESSION 97 QUALITY_GATE SKIPPED: {skip_reason} - using fallback data")
        else:
            phase4_complete, phase4_details = self._check_phase4_completion_gate(analysis_date)
            if not phase4_complete:
                error_msg = (
                    f"SESSION 97 QUALITY_GATE FAILED: Phase 4 incomplete for {analysis_date}. "
                    f"Details: {phase4_details}. "
                    f"ML Feature Store should NOT run until Phase 4 completes."
                )
                logger.error(error_msg)
                raise ValueError(error_msg)
            else:
                logger.info(f"SESSION 97 QUALITY_GATE PASSED: Phase 4 complete for {analysis_date}. {phase4_details}")

        # Get players with games today
        # v3.3: In backfill mode, query actual played roster instead of expected roster
        step_start = time.time()
        self.players_with_games = self.feature_extractor.get_players_with_games(
            analysis_date, backfill_mode=self.is_backfill_mode
        )
        self._timing['get_players_with_games'] = time.time() - step_start
        logger.info(f"Found {len(self.players_with_games)} players with games on {analysis_date}" +
                   (" [BACKFILL MODE: actual roster]" if self.is_backfill_mode else ""))

        # Extract source hashes from all 4 Phase 4 dependencies (Smart Reprocessing - Pattern #3)
        # Note: _extract_source_hashes has its own timing
        self._extract_source_hashes(analysis_date)

        if len(self.players_with_games) == 0:
            if not self._has_games_on_date(analysis_date):
                logger.info(f"No regular-season games scheduled for {analysis_date}, skipping gracefully")
                self.stats['processing_decision'] = 'skipped_no_games'
                self.raw_data = self.players_with_games
                return
            raise ValueError(f"No players found with games on {analysis_date}")

        # BATCH EXTRACTION (20x speedup for backfill!)
        # Query all Phase 3/4 tables once upfront instead of per-player queries
        # v3.6 (Session 62): Pass backfill_mode to enable raw betting table joins for Vegas lines
        step_start = time.time()
        self.feature_extractor.batch_extract_all_data(
            analysis_date, self.players_with_games, backfill_mode=self.is_backfill_mode
        )
        self._timing['batch_extract_all_data'] = time.time() - step_start

        # Session 156: Filter out players with no recent game history
        # Require presence in _last_10_games_lookup (games in the 60-day window).
        # Players returning from 3+ month injury or with zero recent games would produce
        # feature store records that are 7+ defaults — these:
        # 1. Get blocked by quality gate anyway (required_default_count > 0)
        # 2. Risk contaminating training data (breakout classifier had NO quality filter)
        # 3. Inflate quality monitoring metrics with noise
        # Season-only stats (from _season_stats_lookup) are NOT sufficient — a player with
        # 2 games from October but 0 games in the last 60 days has no meaningful recent features.
        # These players naturally re-enter once they play games and accumulate recent history.
        pre_filter_count = len(self.players_with_games)
        self.players_with_games = [
            p for p in self.players_with_games
            if p['player_lookup'] in self.feature_extractor._last_10_games_lookup
        ]
        filtered_count = pre_filter_count - len(self.players_with_games)
        if filtered_count > 0:
            logger.info(
                f"Session 156: Filtered {filtered_count} players with no recent games "
                f"(not in 60-day lookback window) ({pre_filter_count} → {len(self.players_with_games)})"
            )

        # Set raw_data to pass base class validation
        self.raw_data = self.players_with_games

        self._timing['extract_raw_data'] = time.time() - extract_start
        logger.info(f"Extract phase complete in {self._timing['extract_raw_data']:.2f}s")

    def _extract_source_hashes(self, analysis_date: date) -> None:
        """
        Extract data_hash from all 4 Phase 4 upstream tables.

        OPTIMIZED: Single UNION ALL query instead of 4 sequential queries.
        Reduces BigQuery round-trips from 4 to 1 (~30-60 seconds saved).
        """
        try:
            query_start = time.time()

            # Single combined query for all 4 sources
            query = f"""
            WITH latest_hashes AS (
                SELECT 'daily_cache' as source, data_hash, processed_at
                FROM `{self.project_id}.nba_precompute.player_daily_cache`
                WHERE cache_date = '{analysis_date}' AND data_hash IS NOT NULL

                UNION ALL

                SELECT 'composite' as source, data_hash, processed_at
                FROM `{self.project_id}.nba_precompute.player_composite_factors`
                WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL

                UNION ALL

                SELECT 'shot_zones' as source, data_hash, processed_at
                FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
                WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL

                UNION ALL

                SELECT 'team_defense' as source, data_hash, processed_at
                FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
                WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL
            ),
            ranked_hashes AS (
                SELECT
                    source,
                    data_hash,
                    ROW_NUMBER() OVER (PARTITION BY source ORDER BY processed_at DESC) as rn
                FROM latest_hashes
            )
            SELECT source, data_hash
            FROM ranked_hashes
            WHERE rn = 1
            """

            result = self.bq_client.query(query).to_dataframe()

            # Parse results into source-specific attributes
            self.source_daily_cache_hash = None
            self.source_composite_hash = None
            self.source_shot_zones_hash = None
            self.source_team_defense_hash = None

            for _, row in result.iterrows():
                source = row['source']
                data_hash = str(row['data_hash'])
                if source == 'daily_cache':
                    self.source_daily_cache_hash = data_hash
                elif source == 'composite':
                    self.source_composite_hash = data_hash
                elif source == 'shot_zones':
                    self.source_shot_zones_hash = data_hash
                elif source == 'team_defense':
                    self.source_team_defense_hash = data_hash

            query_time = time.time() - query_start
            logger.info(f"Extracted 4 source hashes in {query_time:.2f}s (single query)")

        except Exception as e:
            logger.warning(f"Failed to extract source hashes: {e}")

    def _is_early_season(self, analysis_date: date, season_year: int) -> bool:
        """
        Check if we're in early season (first 7 days of season).

        Bootstrap Period Handling:
            Uses deterministic date-based check instead of threshold-based.
            Queries schedule service for accurate season start date.

        Changed from threshold-based (>50% players) to date-based (first 7 days).
        This is more reliable and consistent with other Phase 4 processors.

        Args:
            analysis_date: Date being analyzed
            season_year: Season year (e.g., 2024 for 2024-25 season)

        Returns:
            True if within first BOOTSTRAP_DAYS of regular season, False otherwise
        """
        # Use schedule service-based detection (Week 5 - Bootstrap period fix)
        if is_early_season(analysis_date, season_year, days_threshold=BOOTSTRAP_DAYS):
            self.early_season_flag = True
            self.insufficient_data_reason = f'early_season_skip_first_{BOOTSTRAP_DAYS}_days'
            logger.info(
                f"Early season detected for {analysis_date} (season {season_year}): "
                f"within first {BOOTSTRAP_DAYS} days of regular season"
            )
            return True

        return False
    
    def _create_early_season_placeholders(self, analysis_date: date) -> None:
        """
        Create placeholder records for early season.
        
        All features set to NULL, early_season_flag = TRUE.
        Source tracking still populated to show Phase 4 status.
        """
        # Get list of players with games
        # v3.3: In backfill mode, query actual played roster
        players = self.feature_extractor.get_players_with_games(
            analysis_date, backfill_mode=self.is_backfill_mode
        )

        self.transformed_data = []

        for player_row in players:
            record = {
                'player_lookup': player_row['player_lookup'],
                'universal_player_id': player_row.get('universal_player_id'),
                'game_date': analysis_date.isoformat(),
                'game_id': player_row['game_id'],
                
                # NULL feature array
                'features': [None] * FEATURE_COUNT,
                'feature_names': FEATURE_NAMES,
                'feature_count': FEATURE_COUNT,
                'feature_version': FEATURE_VERSION,
                
                # Context
                'opponent_team_abbr': player_row.get('opponent_team_abbr'),
                'is_home': player_row.get('is_home'),
                'days_rest': player_row.get('days_rest'),
                
                # Quality
                'feature_quality_score': 0.0,
                'feature_generation_time_ms': None,
                'data_source': 'early_season',
                
                # v4.0 Source tracking (still populated!)
                **self.build_source_tracking_fields(),

                # Early season flags (AFTER source tracking to override if needed)
                'early_season_flag': True,
                'insufficient_data_reason': self.insufficient_data_reason,

                # Completeness Checking Metadata (14 fields) - Early season defaults
                'expected_games_count': 0,
                'actual_games_count': 0,
                'completeness_percentage': 0.0,
                'missing_games_count': 0,
                'is_production_ready': False,
                'data_quality_issues': [],
                'last_reprocess_attempt_at': None,
                'reprocess_attempt_count': 0,
                'circuit_breaker_active': False,
                'circuit_breaker_until': None,
                'manual_override_required': False,
                'season_boundary_detected': False,
                'backfill_bootstrap_mode': True,
                'processing_decision_reason': 'early_season_placeholder',

                # Historical Completeness (Data Cascade Architecture - Jan 2026)
                # Early season = bootstrap mode, no historical data available
                'historical_completeness': {
                    'games_found': 0,
                    'games_expected': 0,
                    'is_complete': True,  # 0/0 = complete (nothing expected)
                    'is_bootstrap': True,  # Early season = bootstrap
                    'contributing_game_dates': []
                },

                # Timestamps
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': None
            }

            # Add source hashes (Smart Reprocessing - Pattern #3)
            record['source_daily_cache_hash'] = self.source_daily_cache_hash
            record['source_composite_hash'] = self.source_composite_hash
            record['source_shot_zones_hash'] = self.source_shot_zones_hash
            record['source_team_defense_hash'] = self.source_team_defense_hash

            # Compute and add data hash (Smart Idempotency - Pattern #1)
            record['data_hash'] = self.compute_data_hash(record)

            self.transformed_data.append(record)
        
        logger.info(f"Created {len(self.transformed_data)} early season placeholder records")

    # ========================================================================
    # CIRCUIT BREAKER METHODS (Week 4 - Completeness Checking)
    # ========================================================================

    def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
        """Check if circuit breaker is active for entity."""
        query = f"""
        SELECT attempt_number, attempted_at, circuit_breaker_tripped, circuit_breaker_until
        FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = '{self.table_name}'
          AND entity_id = '{entity_id}'
          AND analysis_date = DATE('{analysis_date}')
        ORDER BY attempt_number DESC LIMIT 1
        """
        try:
            result = list(self.bq_client.query(query).result(timeout=60))
            if not result:
                return {'active': False, 'attempts': 0, 'until': None}
            row = result[0]
            if row.circuit_breaker_tripped:
                if row.circuit_breaker_until and datetime.now(timezone.utc) < row.circuit_breaker_until:
                    return {'active': True, 'attempts': row.attempt_number, 'until': row.circuit_breaker_until}
            return {'active': False, 'attempts': row.attempt_number, 'until': None}
        except Exception as e:
            logger.warning(f"Error checking circuit breaker for {entity_id}: {e}")
            return {'active': False, 'attempts': 0, 'until': None}

    def _increment_reprocess_count(self, entity_id: str, analysis_date: date, completeness_pct: float, skip_reason: str) -> None:
        """Track reprocessing attempt and trip circuit breaker if needed."""
        from shared.config.orchestration_config import get_orchestration_config
        config = get_orchestration_config()

        circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
        next_attempt = circuit_status['attempts'] + 1
        circuit_breaker_tripped = next_attempt >= 3
        circuit_breaker_until = None
        if circuit_breaker_tripped:
            # Use config for lockout duration (default: 24 hours, was 7 days)
            circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=config.circuit_breaker.entity_lockout_hours)
            logger.error(f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts (lockout: {config.circuit_breaker.entity_lockout_hours}h)")
        insert_query = f"""
        INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
        (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
         completeness_pct, skip_reason, circuit_breaker_tripped, circuit_breaker_until,
         manual_override_applied, notes)
        VALUES ('{self.table_name}', '{entity_id}', DATE('{analysis_date}'), {next_attempt},
                CURRENT_TIMESTAMP(), {completeness_pct}, '{skip_reason}', {circuit_breaker_tripped},
                {'TIMESTAMP("' + circuit_breaker_until.isoformat() + '")' if circuit_breaker_until else 'NULL'},
                FALSE, 'Attempt {next_attempt}: {completeness_pct:.1f}% complete')
        """
        try:
            self.bq_client.query(insert_query).result(timeout=60)
        except Exception as e:
            logger.warning(f"Failed to record reprocess attempt for {entity_id}: {e}")

    def _query_upstream_completeness(self, all_players: List[str], analysis_date: date) -> Dict[str, Dict[str, bool]]:
        """
        Query upstream Phase 4 tables for is_production_ready status (CASCADE PATTERN).

        OPTIMIZED: Reduced from 4 sequential queries to 2 combined queries.
        Saves ~120-180 seconds by reducing BigQuery round-trips.

        Checks 4 upstream dependencies:
        1. player_daily_cache.is_production_ready (per player)
        2. player_composite_factors.is_production_ready (per player)
        3. player_shot_zone_analysis.is_production_ready (per player)
        4. team_defense_zone_analysis.is_production_ready (per opponent team)

        Args:
            all_players: List of player_lookup IDs
            analysis_date: Date to check

        Returns:
            Dict mapping player_lookup to upstream status dict
        """
        upstream_status = {}
        query_start = time.time()

        try:
            # Get opponent teams for each player from feature_extractor (cached data)
            # v3.3: In backfill mode, query actual played roster
            players_with_games = self.feature_extractor.get_players_with_games(
                analysis_date, backfill_mode=self.is_backfill_mode
            )
            opponent_map = {p['player_lookup']: p.get('opponent_team_abbr') for p in players_with_games}
            unique_opponents = [t for t in set(opponent_map.values()) if t]

            # Query 1: All player-level upstream tables in one query
            player_query = f"""
            WITH daily_cache AS (
                SELECT player_lookup, is_production_ready as daily_cache_ready
                FROM `{self.project_id}.nba_precompute.player_daily_cache`
                WHERE cache_date = '{analysis_date}'
                  AND player_lookup IN UNNEST(@players)
            ),
            composite AS (
                SELECT player_lookup, is_production_ready as composite_ready
                FROM `{self.project_id}.nba_precompute.player_composite_factors`
                WHERE game_date = '{analysis_date}'
                  AND player_lookup IN UNNEST(@players)
            ),
            shot_zone AS (
                SELECT player_lookup, is_production_ready as shot_zone_ready
                FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
                WHERE analysis_date = '{analysis_date}'
                  AND player_lookup IN UNNEST(@players)
            )
            SELECT
                COALESCE(dc.player_lookup, cf.player_lookup, sz.player_lookup) as player_lookup,
                COALESCE(dc.daily_cache_ready, FALSE) as daily_cache_ready,
                COALESCE(cf.composite_ready, FALSE) as composite_ready,
                COALESCE(sz.shot_zone_ready, FALSE) as shot_zone_ready
            FROM daily_cache dc
            FULL OUTER JOIN composite cf ON dc.player_lookup = cf.player_lookup
            FULL OUTER JOIN shot_zone sz ON COALESCE(dc.player_lookup, cf.player_lookup) = sz.player_lookup
            """

            player_df = self.bq_client.query(
                player_query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("players", "STRING", list(all_players))]
                )
            ).to_dataframe()

            # Query 2: Team defense completeness
            team_query = f"""
            SELECT team_abbr, is_production_ready as team_defense_ready
            FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date = '{analysis_date}'
              AND team_abbr IN UNNEST(@teams)
            """
            team_df = self.bq_client.query(
                team_query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("teams", "STRING", unique_opponents)]
                )
            ).to_dataframe()

            # Build lookup dicts for fast access
            player_status_lookup = {}
            for _, row in player_df.iterrows():
                player_status_lookup[row['player_lookup']] = {
                    'daily_cache_ready': bool(row['daily_cache_ready']),
                    'composite_ready': bool(row['composite_ready']),
                    'shot_zone_ready': bool(row['shot_zone_ready'])
                }

            team_defense_lookup = {}
            for _, row in team_df.iterrows():
                team_defense_lookup[row['team_abbr']] = bool(row['team_defense_ready'])

            # Build status dict for each player
            for player in all_players:
                player_data = player_status_lookup.get(player, {
                    'daily_cache_ready': False,
                    'composite_ready': False,
                    'shot_zone_ready': False
                })

                opponent_team = opponent_map.get(player)
                team_defense_ready = team_defense_lookup.get(opponent_team, False) if opponent_team else False

                upstream_status[player] = {
                    'player_daily_cache_ready': player_data['daily_cache_ready'],
                    'player_composite_factors_ready': player_data['composite_ready'],
                    'player_shot_zone_ready': player_data['shot_zone_ready'],
                    'team_defense_zone_ready': team_defense_ready,
                    'all_upstreams_ready': (
                        player_data['daily_cache_ready'] and
                        player_data['composite_ready'] and
                        player_data['shot_zone_ready'] and
                        team_defense_ready
                    )
                }

            query_time = time.time() - query_start
            ready_count = sum(1 for s in upstream_status.values() if s['all_upstreams_ready'])
            logger.info(
                f"Upstream completeness check: {ready_count}/{len(upstream_status)} players ready "
                f"({query_time:.2f}s, 2 queries)"
            )

        except Exception as e:
            logger.error(f"Error querying upstream completeness: {e}")
            # Return empty dict on error - will be treated as not ready
            for player in all_players:
                upstream_status[player] = {
                    'player_daily_cache_ready': False,
                    'player_composite_factors_ready': False,
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'all_upstreams_ready': False
                }

        return upstream_status

    # ========================================================================
    # CALCULATION - MAIN FLOW
    # ========================================================================
    
    def calculate_precompute(self) -> None:
        """
        Calculate 25 features for each player.

        Flow:
        1. Batch completeness checking (Week 4)
        2. Iterate through each player with a game today
        3. Extract Phase 4 data (preferred)
        4. Fallback to Phase 3 if Phase 4 incomplete
        5. Calculate 6 derived features
        6. Calculate quality score
        7. Build output record with source tracking
        """
        calculate_start = time.time()

        if self.early_season_flag:
            # Placeholders already created in extract_raw_data()
            logger.info("Early season - using placeholder records")
            self._timing['calculate_precompute'] = time.time() - calculate_start
            return

        if self.players_with_games is None or len(self.players_with_games) == 0:
            logger.warning("No players to process")
            self._timing['calculate_precompute'] = time.time() - calculate_start
            return

        self.transformed_data = []
        self.failed_entities = []

        # Get all players and analysis date
        all_players = [p['player_lookup'] for p in self.players_with_games]
        analysis_date = self.opts['analysis_date']

        # ============================================================
        # NEW (Week 4): Batch completeness checking
        # ============================================================
        # OPTIMIZATION (Session 64): Skip slow completeness check in backfill mode
        # Backfill already has preflight checks at date-level; player-level is redundant
        # Session 170: Also skip in same-day mode (skip_dependency_check=True or strict_mode=False)
        # Session 6 (2026-01-10): Also skip for same-day/future games where player_game_summary
        # won't have data yet because games haven't been played. Players with valid context
        # from upcoming_player_game_context should be processed even without completeness data.
        step_start = time.time()
        is_same_day_or_future = analysis_date >= date.today()
        skip_completeness = (
            self.is_backfill_mode or
            self.opts.get('skip_dependency_check', False) or
            not self.opts.get('strict_mode', True) or
            is_same_day_or_future  # Games haven't been played yet, skip completeness check
        )
        if skip_completeness:
            if self.is_backfill_mode:
                mode_reason = "BACKFILL"
            elif is_same_day_or_future:
                mode_reason = "SAME-DAY/FUTURE"
            else:
                mode_reason = "SAME-DAY"
            logger.info(f"⏭️ {mode_reason} MODE: Skipping completeness check for {len(all_players)} players")
            # Use actual game counts from already-loaded data (feature_extractor has last 10 games)
            # This makes metadata accurate for debugging without additional BQ queries
            completeness_results = {
                player: {
                    'is_production_ready': True,
                    'completeness_pct': 100.0,
                    'expected_count': len(self.feature_extractor._last_10_games_lookup.get(player, [])),
                    'actual_count': len(self.feature_extractor._last_10_games_lookup.get(player, [])),
                    'missing_count': 0,
                    'is_complete': True
                }
                for player in all_players
            }
            is_bootstrap = False
            is_season_boundary = False
        else:
            logger.info(f"Checking completeness for {len(all_players)} players...")

            # Check own data completeness (player_game_summary - base data for features)
            completeness_results = self.completeness_checker.check_completeness_batch(
                entity_ids=list(all_players),
                entity_type='player',
                analysis_date=analysis_date,
                upstream_table='nba_analytics.player_game_summary',
                upstream_entity_field='player_lookup',
                lookback_window=10,
                window_type='games',
                season_start_date=self.season_start_date
            )

            # Check bootstrap mode
            is_bootstrap = self.completeness_checker.is_bootstrap_mode(
                analysis_date, self.season_start_date
            )
            is_season_boundary = self.completeness_checker.is_season_boundary(analysis_date)

        self._timing['completeness_check'] = time.time() - step_start

        if not skip_completeness:
            logger.info(
                f"Completeness check complete in {self._timing['completeness_check']:.2f}s. "
                f"Bootstrap mode: {is_bootstrap}, Season boundary: {is_season_boundary}"
            )

        # Check upstream completeness (CASCADE PATTERN - Week 5)
        # Note: _query_upstream_completeness has its own timing
        upstream_completeness = self._query_upstream_completeness(list(all_players), analysis_date)
        # ============================================================

        # ============================================================
        # PARALLELIZATION: Replace serial loop with parallel/serial dispatcher
        # ============================================================
        ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'

        step_start = time.time()
        if ENABLE_PARALLELIZATION:
            successful, failed = self._process_players_parallel(
                self.players_with_games, completeness_results, upstream_completeness,
                is_bootstrap, is_season_boundary, analysis_date
            )
        else:
            successful, failed = self._process_players_serial(
                self.players_with_games, completeness_results, upstream_completeness,
                is_bootstrap, is_season_boundary, analysis_date
            )
        self._timing['player_processing'] = time.time() - step_start

        self.transformed_data = successful
        self.failed_entities = failed

        success_count = len(self.transformed_data)
        fail_count = len(self.failed_entities)
        success_rate = (success_count / (success_count + fail_count) * 100) if (success_count + fail_count) > 0 else 0

        self._timing['calculate_precompute'] = time.time() - calculate_start
        logger.info(
            f"Feature generation complete: {success_count} success, {fail_count} failed "
            f"({success_rate:.1f}% success rate) in {self._timing['calculate_precompute']:.2f}s"
        )

        # Session 146: Log cache miss summary for investigation
        cache_miss_summary = self.feature_extractor.get_cache_miss_summary()
        if cache_miss_summary['cache_miss_count'] > 0:
            logger.info(
                f"📊 Cache miss summary: {cache_miss_summary['cache_miss_count']} misses "
                f"/ {cache_miss_summary['cache_hit_count']} hits "
                f"({cache_miss_summary['cache_miss_rate']:.1%} miss rate). "
                f"Players: {', '.join(cache_miss_summary['cache_miss_players'][:10])}"
                f"{'...' if cache_miss_summary['cache_miss_count'] > 10 else ''}"
            )

        # Session 52: Feature source validation
        # Alert when Phase 4 composite features are all using defaults (indicates upstream issue)
        if success_count >= 50:
            composite_features = [
                (5, 'fatigue_score', 50.0),
                (6, 'shot_zone_mismatch_score', 0.0),
                (7, 'pace_score', 0.0),
                (8, 'usage_spike_score', 0.0),
            ]
            for idx, feature_name, default_val in composite_features:
                # Count how many used Phase 4 vs default
                phase4_count = sum(
                    1 for r in self.transformed_data
                    if r.get('feature_sources', {}).get(idx) == 'phase4'
                )
                default_pct = ((success_count - phase4_count) / success_count * 100)
                if default_pct >= 90:
                    logger.warning(
                        f"FEATURE SOURCE ALERT: {feature_name} (idx {idx}) is {default_pct:.1f}% defaults "
                        f"(only {phase4_count}/{success_count} from Phase 4). Check player_composite_factors backfill."
                    )

        # Count failures by category for clear visibility
        if self.failed_entities:
            category_counts = {}
            for f in self.failed_entities:
                cat = f.get('category', 'UNKNOWN')
                category_counts[cat] = category_counts.get(cat, 0) + 1

            # Show breakdown with clear labeling
            expected_skips = (category_counts.get('INSUFFICIENT_DATA', 0) +
                            category_counts.get('INCOMPLETE_DATA', 0) +
                            category_counts.get('MISSING_UPSTREAM', 0))
            errors_to_investigate = category_counts.get('PROCESSING_ERROR', 0) + category_counts.get('UNKNOWN', 0)

            logger.info(f"📊 Failure breakdown ({fail_count} total):")
            for cat, count in sorted(category_counts.items()):
                if cat in ('INSUFFICIENT_DATA', 'INCOMPLETE_DATA', 'MISSING_UPSTREAM', 'CIRCUIT_BREAKER_ACTIVE'):
                    logger.info(f"   {cat}: {count} (expected - data quality)")
                else:
                    logger.warning(f"   {cat}: {count} ⚠️ INVESTIGATE")

            if errors_to_investigate == 0:
                logger.info(f"✅ No errors to investigate - all {expected_skips} skips are expected (data quality)")

            # Store category breakdown in stats
            self.stats['failure_categories'] = category_counts
            self.stats['errors_to_investigate'] = errors_to_investigate

            # Save failures to BigQuery for auditing
            self.save_failures_to_bq()

            # Session 144: Record gaps for automatic backfill tracking
            self._record_feature_store_gaps(analysis_date)

    def _record_feature_store_gaps(self, analysis_date: date) -> None:
        """Record feature store gaps for failed/skipped players (Session 144).

        Maps failure categories to gap reasons and writes to feature_store_gaps table
        for automatic detection and backfill.
        """
        if not self.failed_entities:
            return

        # Map failure categories to gap reasons
        category_to_reason = {
            'CIRCUIT_BREAKER_ACTIVE': 'circuit_breaker',
            'INCOMPLETE_DATA_SKIPPED': 'missing_phase4',
            'UPSTREAM_INCOMPLETE': 'upstream_incomplete',
            'FEATURE_VALIDATION_ERROR': 'processing_error',
            'INSUFFICIENT_DATA': 'insufficient_data',
            'MISSING_UPSTREAM': 'missing_phase4',
            'calculation_error': 'processing_error',
            'PROCESSING_ERROR': 'processing_error',
        }

        from shared.config.nba_season_dates import get_season_year_from_date
        season_year = get_season_year_from_date(analysis_date)

        # Build player context lookup from players_with_games
        player_context = {}
        if self.players_with_games:
            for p in self.players_with_games:
                pl = p.get('player_lookup', '')
                player_context[pl] = p

        rows = []
        now = datetime.now(timezone.utc)
        for entity in self.failed_entities:
            player_lookup = entity.get('entity_id', '')
            category = entity.get('category', 'UNKNOWN')
            reason = category_to_reason.get(category, 'unknown')
            ctx = player_context.get(player_lookup, {})

            rows.append({
                'player_lookup': player_lookup,
                'game_date': analysis_date.isoformat(),
                'game_id': ctx.get('game_id'),
                'reason': reason,
                'reason_detail': entity.get('reason', ''),
                'team_abbr': ctx.get('team_abbr'),
                'opponent_team_abbr': ctx.get('opponent_team_abbr'),
                'season_year': season_year,
                'detected_at': now.isoformat(),
                'detected_by': 'processor',
                'resolved_at': None,
                'resolved_by': None,
                'backfill_attempt_count': 0,
                'last_backfill_attempt_at': None,
                'last_backfill_error': None,
            })

        if not rows:
            return

        try:
            table_ref = f'{self.project_id}.nba_predictions.feature_store_gaps'
            errors = self.bq_client.insert_rows_json(table_ref, rows)
            if errors:
                logger.warning(f"Failed to insert {len(errors)} gap records: {errors[:2]}")
            else:
                logger.info(f"Recorded {len(rows)} feature store gaps for {analysis_date}")
        except Exception as e:
            logger.warning(f"Gap tracking write failed (non-fatal): {e}")

    def _generate_player_features(self, player_row: Dict, completeness: Dict, upstream_status: Dict, circuit_breaker_status: Dict, is_bootstrap: bool, is_season_boundary: bool) -> Dict:
        """
        Generate complete feature vector for one player.

        Args:
            player_row: Dict with player_lookup, game_date, game_id, etc.
            completeness: Completeness check results for this player (own data)
            upstream_status: Upstream completeness status (CASCADE PATTERN)
            circuit_breaker_status: Circuit breaker status for this player
            is_bootstrap: Whether in bootstrap mode
            is_season_boundary: Whether at season boundary

        Returns:
            Dict with complete record ready for BigQuery (with v4.0 source tracking + completeness metadata)
        """
        player_lookup = player_row['player_lookup']
        game_date = self.opts['analysis_date']
        opponent_team_abbr = player_row.get('opponent_team_abbr')

        # ============================================================
        # HISTORICAL COMPLETENESS TRACKING (Data Cascade Architecture)
        # Build completeness metadata BEFORE feature extraction
        # ============================================================
        hist_completeness_data = self.feature_extractor.get_historical_completeness_data(player_lookup)
        historical_completeness = assess_historical_completeness(
            games_found=hist_completeness_data['games_found'],
            games_available=hist_completeness_data['games_available'],
            contributing_dates=hist_completeness_data['contributing_game_dates'],
            window_size=WINDOW_SIZE
        )

        # Log if incomplete (and not bootstrap)
        if historical_completeness.is_data_gap:
            logger.warning(
                f"{player_lookup}: Historical data gap - {historical_completeness.games_found}/{historical_completeness.games_expected} games"
            )
        # ============================================================

        # Extract Phase 4 data (preferred) - pass opponent from player_row
        phase4_data = self.feature_extractor.extract_phase4_data(
            player_lookup, game_date, opponent_team_abbr=opponent_team_abbr
        )

        # Extract Phase 3 data (fallback + calculated features)
        phase3_data = self.feature_extractor.extract_phase3_data(player_lookup, game_date)

        # Generate 37 features (v2_37features)
        features, feature_sources = self._extract_all_features(
            phase4_data, phase3_data,
            player_lookup=player_lookup,
            opponent=opponent_team_abbr
        )

        # Calculate quality score and build quality visibility fields
        quality_score = self.quality_scorer.calculate_quality_score(feature_sources)
        data_source = self.quality_scorer.determine_primary_source(feature_sources)
        quality_fields = self.quality_scorer.build_quality_visibility_fields(
            feature_sources=feature_sources,
            feature_values=features,
            feature_names=FEATURE_NAMES,
            quality_score=quality_score,
        )

        # Build output record with v4.0 source tracking
        record = {
            'player_lookup': player_lookup,
            'universal_player_id': player_row.get('universal_player_id'),
            'game_date': game_date.isoformat(),
            'game_id': player_row['game_id'],

            # Features
            'features': features,  # List of 37 floats (v2_37features)
            'feature_sources': feature_sources,  # Session 95 fix: Store for FEATURE SOURCE ALERT counting
            'feature_names': FEATURE_NAMES,
            'feature_count': FEATURE_COUNT,
            'feature_version': FEATURE_VERSION,
            
            # Context
            'opponent_team_abbr': player_row.get('opponent_team_abbr'),
            'is_home': player_row.get('is_home'),
            'days_rest': phase3_data.get('days_rest'),
            
            # Quality (quality_tier uses feature store visibility tiers)
            'quality_tier': get_feature_quality_tier(quality_score),
            'feature_quality_score': quality_score,
            'data_source': data_source,
            
            # v4.0 Source tracking (one line via base class method!)
            **self.build_source_tracking_fields(),

            # ============================================================
            # NEW (Week 4): Completeness Checking Metadata (14 fields)
            # ============================================================
            # Completeness Metrics
            'expected_games_count': completeness['expected_count'],
            'actual_games_count': completeness['actual_count'],
            'completeness_percentage': completeness['completeness_pct'],
            'missing_games_count': completeness['missing_count'],

            # Production Readiness (CASCADE PATTERN: own complete AND all Phase 4 upstreams complete)
            'is_production_ready': (
                completeness['is_production_ready'] and
                upstream_status['all_upstreams_ready']
            ),
            'data_quality_issues': [issue for issue in [
                "upstream_player_daily_cache_incomplete" if not upstream_status['player_daily_cache_ready'] else None,
                "upstream_player_composite_factors_incomplete" if not upstream_status['player_composite_factors_ready'] else None,
                "upstream_player_shot_zone_incomplete" if not upstream_status['player_shot_zone_ready'] else None,
                "upstream_team_defense_zone_incomplete" if not upstream_status['team_defense_zone_ready'] else None,
            ] if issue is not None],

            # Circuit Breaker
            'last_reprocess_attempt_at': None,  # Would need separate query
            'reprocess_attempt_count': circuit_breaker_status['attempts'],
            'circuit_breaker_active': circuit_breaker_status['active'],
            'circuit_breaker_until': (
                circuit_breaker_status['until'].isoformat()
                if circuit_breaker_status['until'] else None
            ),

            # Bootstrap/Override
            'manual_override_required': False,
            'season_boundary_detected': is_season_boundary,
            'backfill_bootstrap_mode': is_bootstrap,
            'processing_decision_reason': 'processed_successfully',
            # ============================================================

            # ============================================================
            # HISTORICAL COMPLETENESS (Data Cascade Architecture - Jan 2026)
            # Tracks whether rolling window calculations had all required data.
            # Different from schedule completeness above (which tracks today's games).
            # ============================================================
            'historical_completeness': historical_completeness.to_bq_struct(),

            # Timestamps
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': None
        }

        # Add source hashes (Smart Reprocessing - Pattern #3)
        record['source_daily_cache_hash'] = self.source_daily_cache_hash
        record['source_composite_hash'] = self.source_composite_hash
        record['source_shot_zones_hash'] = self.source_shot_zones_hash
        record['source_team_defense_hash'] = self.source_team_defense_hash

        # ============================================================
        # DATA PROVENANCE (Session 99 - Feb 2026)
        # Track what data sources were used and whether matchup data was valid
        # ============================================================
        provenance = self.feature_extractor.get_data_provenance()
        player_provenance = self.feature_extractor.get_player_data_provenance(player_lookup)

        record['matchup_data_status'] = provenance['matchup_data_status']
        record['fallback_reasons'] = provenance['fallback_reasons'] or None

        # Per-player provenance
        if not player_provenance['matchup_valid']:
            # Add to data_quality_issues if matchup data was not valid
            if record.get('data_quality_issues') is None:
                record['data_quality_issues'] = []
            record['data_quality_issues'].append('matchup_factors_used_defaults')

        # Session 146: Track cache miss fallback usage for investigation
        record['cache_miss_fallback_used'] = self.feature_extractor.was_cache_miss(player_lookup)

        # Session 152: Vegas line source tracking (which scraper provided ML features 25-28)
        vegas_data = self.feature_extractor.get_vegas_lines(player_lookup)
        record['vegas_line_source'] = vegas_data.get('vegas_line_source', 'none')

        # Add early season fields (required for hash calculation)
        record['early_season_flag'] = False  # Normal processing, not early season
        record['insufficient_data_reason'] = None

        # Compute and add data hash (Smart Idempotency - Pattern #1)
        record['data_hash'] = self.compute_data_hash(record)

        # ============================================================
        # QUALITY VISIBILITY (Session 137 - 120 new fields)
        # Merge quality visibility fields into the record.
        # quality_tier is overwritten with the feature-store-specific tier.
        # is_production_ready is NOT overwritten (kept as completeness-based).
        # is_quality_ready is a NEW field for quality-based gating.
        # ============================================================
        record.update(quality_fields)

        # ============================================================
        # INDIVIDUAL FEATURE VALUE COLUMNS (Session 235 - Phase 1)
        # Dual-write: array stays for backward compat, individual columns
        # enable proper NULLs (no fake defaults) and per-model gating.
        # Rule: source in (default, missing, fallback) → NULL, otherwise → actual value.
        # ============================================================
        for i, val in enumerate(features):
            source = feature_sources.get(i, 'unknown')
            if source in ('default', 'missing', 'fallback'):
                record[f'feature_{i}_value'] = None
            else:
                record[f'feature_{i}_value'] = val

        return record
    
    def _extract_all_features(self, phase4_data: Dict, phase3_data: Dict,
                               player_lookup: str = None, opponent: str = None) -> tuple:
        """
        Extract all 55 features with Phase 4 → Phase 3 → Default fallback.

        Args:
            phase4_data: Dict with Phase 4 table data
            phase3_data: Dict with Phase 3 table data
            player_lookup: Player identifier (for V8+ features)
            opponent: Opponent team abbreviation (for V8+ features)

        Returns:
            tuple: (features_list, feature_sources_dict)
                features_list: List of 54 float values
                feature_sources_dict: Dict mapping feature index to source
        """
        features = []
        feature_sources = {}
        
        # Features 0-4: Recent Performance
        features.append(self._get_feature_with_fallback(0, 'points_avg_last_5', phase4_data, phase3_data, 10.0, feature_sources))
        features.append(self._get_feature_with_fallback(1, 'points_avg_last_10', phase4_data, phase3_data, 10.0, feature_sources))
        features.append(self._get_feature_with_fallback(2, 'points_avg_season', phase4_data, phase3_data, 10.0, feature_sources))
        features.append(self._get_feature_with_fallback(3, 'points_std_last_10', phase4_data, phase3_data, 5.0, feature_sources))
        features.append(self._get_feature_with_fallback(4, 'games_in_last_7_days', phase4_data, phase3_data, 3.0, feature_sources))
        
        # Features 5-8: Composite Factors (Phase 4 ONLY)
        features.append(self._get_feature_phase4_only(5, 'fatigue_score', phase4_data, 50.0, feature_sources))
        features.append(self._get_feature_phase4_only(6, 'shot_zone_mismatch_score', phase4_data, 0.0, feature_sources))
        features.append(self._get_feature_phase4_only(7, 'pace_score', phase4_data, 0.0, feature_sources))
        features.append(self._get_feature_phase4_only(8, 'usage_spike_score', phase4_data, 0.0, feature_sources))
        
        # Features 9-12: Derived Factors (CALCULATE)
        features.append(self.feature_calculator.calculate_rest_advantage(phase3_data))
        feature_sources[9] = 'calculated'
        
        features.append(self.feature_calculator.calculate_injury_risk(phase3_data))
        feature_sources[10] = 'calculated'
        
        features.append(self.feature_calculator.calculate_recent_trend(phase3_data))
        feature_sources[11] = 'calculated'
        
        features.append(self.feature_calculator.calculate_minutes_change(phase4_data, phase3_data))
        feature_sources[12] = 'calculated'
        
        # Features 13-14: Matchup Context
        features.append(self._get_feature_with_fallback(13, 'opponent_def_rating', phase4_data, phase3_data, 112.0, feature_sources))
        features.append(self._get_feature_with_fallback(14, 'opponent_pace', phase4_data, phase3_data, 100.0, feature_sources))
        
        # Features 15-17: Game Context (Phase 3 only)
        features.append(float(phase3_data.get('home_game') or 0))
        feature_sources[15] = 'phase3'

        features.append(float(phase3_data.get('back_to_back') or 0))
        feature_sources[16] = 'phase3'
        
        features.append(1.0 if (phase3_data.get('season_phase') or '').lower() == 'playoffs' else 0.0)
        feature_sources[17] = 'phase3'
        
        # Features 18-21: Shot Zones (NULLABLE - use NULL instead of defaults)
        # Shot zone features - use NULL instead of defaults when data missing
        paint_rate = self._get_feature_nullable(18, 'paint_rate_last_10', phase4_data, phase3_data, feature_sources)
        mid_range_rate = self._get_feature_nullable(19, 'mid_range_rate_last_10', phase4_data, phase3_data, feature_sources)
        three_pt_rate = self._get_feature_nullable(20, 'three_pt_rate_last_10', phase4_data, phase3_data, feature_sources)

        # Convert to decimal if not None
        features.append(paint_rate / 100.0 if paint_rate is not None else None)
        features.append(mid_range_rate / 100.0 if mid_range_rate is not None else None)
        features.append(three_pt_rate / 100.0 if three_pt_rate is not None else None)

        features.append(self.feature_calculator.calculate_pct_free_throw(phase3_data))
        feature_sources[21] = 'calculated'
        
        # Features 22-24: Team Context
        features.append(self._get_feature_with_fallback(22, 'team_pace_last_10', phase4_data, phase3_data, 100.0, feature_sources))
        features.append(self._get_feature_with_fallback(23, 'team_off_rating_last_10', phase4_data, phase3_data, 112.0, feature_sources))
        
        features.append(self.feature_calculator.calculate_team_win_pct(phase3_data))
        feature_sources[24] = 'calculated'

        # ============================================================
        # V8 MODEL FEATURES (25-32) - Added Jan 2026
        # ============================================================

        # Features 25-28: Vegas Lines
        # IMPORTANT: Do NOT use season_avg as fallback - that corrupts the feature meaning
        # If no real Vegas line exists, store None (will be np.nan in CatBoost)
        # The has_vegas_line flag (feature 28) indicates whether Vegas data is real
        vegas_data = self.feature_extractor.get_vegas_lines(player_lookup) if player_lookup else {}

        vegas_points_line = vegas_data.get('vegas_points_line')
        features.append(float(vegas_points_line) if vegas_points_line is not None else None)
        feature_sources[25] = 'vegas' if vegas_points_line is not None else 'missing'

        vegas_opening_line = vegas_data.get('vegas_opening_line')
        features.append(float(vegas_opening_line) if vegas_opening_line is not None else None)
        feature_sources[26] = 'vegas' if vegas_opening_line is not None else 'missing'

        vegas_line_move = vegas_data.get('vegas_line_move')
        features.append(float(vegas_line_move) if vegas_line_move is not None else None)
        feature_sources[27] = 'vegas' if vegas_line_move is not None else 'missing'

        has_vegas_line = 1.0 if vegas_points_line is not None else 0.0
        features.append(has_vegas_line)
        feature_sources[28] = 'calculated'

        # Features 29-30: Opponent History
        opponent_data = self.feature_extractor.get_opponent_history(player_lookup, opponent) if player_lookup and opponent else {}

        # Use player's season average as fallback for avg_points_vs_opponent
        # NaN-safe: pandas NaN is truthy, so `or` chain won't catch it
        def _safe_float(val, default=10.0):
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return None
            return float(val)

        season_avg_fallback = (
            _safe_float(phase4_data.get('points_avg_season'))
            or _safe_float(phase3_data.get('points_avg_season'))
            or 10.0
        )

        # Session 291 Fix: Handle pandas NaN from BQ NULL (LEFT JOIN with no matches).
        # BQ NULL → pandas NaN → NaN passes `is not None` check → sanitizer converts to None
        # for feature_N_value column but 0.0 for features array → inconsistency.
        # Fix: explicitly check for NaN before using the value.
        avg_points_vs_opp = _safe_float(opponent_data.get('avg_points_vs_opponent'))
        if avg_points_vs_opp is None:
            avg_points_vs_opp = season_avg_fallback
            feature_sources[29] = 'calculated'  # Season avg is a valid calculated fallback
        else:
            feature_sources[29] = 'opponent_history'
        features.append(float(avg_points_vs_opp))

        games_vs_opp = _safe_float(opponent_data.get('games_vs_opponent'), default=0.0)
        if games_vs_opp is None:
            games_vs_opp = 0.0
        features.append(float(games_vs_opp))
        feature_sources[30] = 'opponent_history' if opponent_data else 'calculated'

        # Features 31-32: Minutes/PPM (HIGH IMPORTANCE: 14.6% + 10.9%)
        # Session 156: Try dedicated lookup first, fall back to phase4_data (cache fallback)
        minutes_ppm_data = self.feature_extractor.get_minutes_ppm(player_lookup) if player_lookup else {}

        minutes_avg = minutes_ppm_data.get('minutes_avg_last_10')
        if not self._is_valid_value(minutes_avg):
            minutes_avg = phase4_data.get('minutes_avg_last_10')
        if not self._is_valid_value(minutes_avg):
            minutes_avg = 28.0
        features.append(float(minutes_avg))
        feature_sources[31] = 'minutes_ppm' if self._is_valid_value(minutes_ppm_data.get('minutes_avg_last_10')) else (
            'phase4' if self._is_valid_value(phase4_data.get('minutes_avg_last_10')) else 'default'
        )

        ppm_avg = minutes_ppm_data.get('ppm_avg_last_10')
        if not self._is_valid_value(ppm_avg):
            ppm_avg = phase4_data.get('ppm_avg_last_10')
        if not self._is_valid_value(ppm_avg):
            ppm_avg = 0.4
        features.append(float(ppm_avg))
        feature_sources[32] = 'minutes_ppm' if self._is_valid_value(minutes_ppm_data.get('ppm_avg_last_10')) else (
            'phase4' if self._is_valid_value(phase4_data.get('ppm_avg_last_10')) else 'default'
        )

        # Feature 33: DNP Rate (v2.1 - gamebook-based DNP pattern detection)
        # Uses is_dnp field from player_game_summary to catch late scratches,
        # coach decisions, and other DNPs not in pre-game injury reports
        features.append(self.feature_calculator.calculate_dnp_rate(phase3_data))
        feature_sources[33] = 'calculated'

        # ============================================================
        # PLAYER TRAJECTORY FEATURES (34-36) - Session 28 model fix
        # Added to capture NBA dynamics shift where stars are trending up
        # and bench players are trending down
        # ============================================================

        # Feature 34: Points slope over L10 (trend direction and magnitude)
        features.append(self.feature_calculator.calculate_pts_slope_10g(phase3_data))
        feature_sources[34] = 'calculated'

        # Feature 35: Z-score of L5 vs season (how far from baseline)
        features.append(self.feature_calculator.calculate_pts_vs_season_zscore(phase4_data, phase3_data))
        feature_sources[35] = 'calculated'

        # Feature 36: Breakout flag (exceptional recent performance)
        features.append(self.feature_calculator.calculate_breakout_flag(phase4_data, phase3_data))
        feature_sources[36] = 'calculated'

        # ============================================================
        # V11 FEATURES (37-38) - Session 226
        # Replaces disabled breakout features (Session 131)
        # ============================================================

        # Feature 37: Star Teammates Out (Injury Context)
        # Count of star teammates OUT/DOUBTFUL (18+ PPG / 28+ MPG / 25%+ usage)
        # Default 0.0 is valid (means no stars out, the common case)
        star_out = self.feature_extractor.get_star_teammates_out(player_lookup) if player_lookup else None
        features.append(float(star_out) if star_out is not None else 0.0)
        feature_sources[37] = 'phase3' if star_out is not None else 'default'

        # Feature 38: Game Total Line (Game Environment)
        # Game total over/under line from odds API
        # Optional feature (like vegas 25-27) - depends on odds data availability
        game_total = self.feature_extractor.get_game_total(player_lookup) if player_lookup else None
        features.append(float(game_total) if game_total is not None else None)
        feature_sources[38] = 'phase3' if game_total is not None else 'missing'

        # ============================================================
        # V12 FEATURES (39-53) - Session 230 Feature Store Extension
        # Previously computed at prediction time by V12FeatureAugmenter.
        # Now computed in Phase 4 for quality visibility + zero-tolerance.
        # ============================================================

        # Feature 39: days_rest (from UPCG)
        days_rest_val = self.feature_extractor.get_days_rest_float(player_lookup) if player_lookup else None
        features.append(float(days_rest_val) if days_rest_val is not None else float('nan'))
        feature_sources[39] = 'phase3' if days_rest_val is not None else 'missing'

        # Feature 40: minutes_load_last_7d (from UPCG)
        mins_7d = self.feature_extractor.get_minutes_load_last_7d(player_lookup) if player_lookup else None
        features.append(float(mins_7d) if mins_7d is not None else float('nan'))
        feature_sources[40] = 'phase3' if mins_7d is not None else 'missing'

        # Feature 41: spread_magnitude (from UPCG)
        game_spread = self.feature_extractor.get_game_spread(player_lookup) if player_lookup else None
        if game_spread is not None:
            features.append(abs(float(game_spread)))
            feature_sources[41] = 'phase3'
        else:
            features.append(float('nan'))
            feature_sources[41] = 'missing'

        # Feature 42: implied_team_total
        # (game_total ± spread) / 2 based on home/away
        if game_total is not None and game_spread is not None:
            gt = float(game_total)
            gs = float(game_spread)
            is_home = phase3_data.get('home_game')
            if is_home:
                implied_tt = (gt - gs) / 2.0
            else:
                implied_tt = (gt + gs) / 2.0
            features.append(implied_tt)
            feature_sources[42] = 'phase3'
        else:
            features.append(float('nan'))
            feature_sources[42] = 'missing'

        # Features 43-46, 48-49: from rolling stats query
        rolling_stats = self.feature_extractor.get_player_rolling_stats(player_lookup) if player_lookup else {}

        # Feature 43: points_avg_last_3
        pts_l3 = rolling_stats.get('points_avg_last_3')
        features.append(float(pts_l3) if pts_l3 is not None else float('nan'))
        feature_sources[43] = 'calculated' if pts_l3 is not None else 'missing'

        # Feature 44: scoring_trend_slope
        slope = rolling_stats.get('scoring_trend_slope')
        features.append(float(slope) if slope is not None else float('nan'))
        feature_sources[44] = 'calculated' if slope is not None else 'missing'

        # Feature 45: deviation_from_avg_last3
        dev = rolling_stats.get('deviation_from_avg_last3')
        features.append(float(dev) if dev is not None else float('nan'))
        feature_sources[45] = 'calculated' if dev is not None else 'missing'

        # Feature 46: consecutive_games_below_avg
        consec = rolling_stats.get('consecutive_games_below_avg')
        features.append(float(consec) if consec is not None else float('nan'))
        feature_sources[46] = 'calculated' if consec is not None else 'missing'

        # Feature 47: teammate_usage_available
        teammate_usage = self.feature_extractor.get_teammate_usage_available(player_lookup) if player_lookup else None
        features.append(float(teammate_usage) if teammate_usage is not None else float('nan'))
        feature_sources[47] = 'calculated' if teammate_usage is not None else 'missing'

        # Feature 48: usage_rate_last_5
        usage = rolling_stats.get('usage_rate_last_5')
        features.append(float(usage) if usage is not None else float('nan'))
        feature_sources[48] = 'calculated' if usage is not None else 'missing'

        # Feature 49: games_since_structural_change
        gsc = rolling_stats.get('games_since_structural_change')
        features.append(float(gsc) if gsc is not None else float('nan'))
        feature_sources[49] = 'calculated' if gsc is not None else 'missing'

        # Feature 50: multi_book_line_std
        line_std = self.feature_extractor.get_multi_book_line_std(player_lookup) if player_lookup else None
        features.append(float(line_std) if line_std is not None else float('nan'))
        feature_sources[50] = 'vegas' if line_std is not None else 'missing'

        # Feature 51: prop_over_streak (from UPCG)
        streaks = self.feature_extractor.get_prop_streaks(player_lookup) if player_lookup else {}
        over_streak = streaks.get('prop_over_streak')
        features.append(float(over_streak) if over_streak is not None else float('nan'))
        feature_sources[51] = 'phase3' if over_streak is not None else 'missing'

        # Feature 52: prop_under_streak (from UPCG)
        under_streak = streaks.get('prop_under_streak')
        features.append(float(under_streak) if under_streak is not None else float('nan'))
        feature_sources[52] = 'phase3' if under_streak is not None else 'missing'

        # Feature 53: line_vs_season_avg (calculated from vegas_line - season_avg)
        # features[25] = vegas_points_line, features[2] = points_avg_season
        vegas_line_val = features[25]  # May be None if no vegas
        season_avg_val = features[2]
        if vegas_line_val is not None and season_avg_val is not None:
            features.append(float(vegas_line_val) - float(season_avg_val))
            feature_sources[53] = 'calculated'
        else:
            features.append(float('nan'))
            feature_sources[53] = 'missing'

        # Feature 54: prop_line_delta (Session 294)
        line_delta = self.feature_extractor.get_prop_line_delta(player_lookup) if player_lookup else None
        features.append(float(line_delta) if line_delta is not None else float('nan'))
        feature_sources[54] = 'vegas' if line_delta is not None else 'missing'

        # Features 55-56: V16 prop line history (Session 356)
        v16_data = self.feature_extractor.get_v16_line_history(player_lookup) if player_lookup else {}

        # Feature 55: over_rate_last_10
        over_rate = v16_data.get('over_rate_last_10')
        features.append(float(over_rate) if over_rate is not None else float('nan'))
        feature_sources[55] = 'calculated' if over_rate is not None else 'missing'

        # Feature 56: margin_vs_line_avg_last_5
        margin_avg = v16_data.get('margin_vs_line_avg_last_5')
        features.append(float(margin_avg) if margin_avg is not None else float('nan'))
        feature_sources[56] = 'calculated' if margin_avg is not None else 'missing'

        # Features 57-59: V17 opportunity risk (Session 360)
        v17_data = self.feature_extractor.get_v17_opportunity_risk(player_lookup) if player_lookup else {}

        # Feature 57: blowout_minutes_risk
        blowout_risk = v17_data.get('blowout_minutes_risk')
        features.append(float(blowout_risk) if blowout_risk is not None else float('nan'))
        feature_sources[57] = 'calculated' if blowout_risk is not None else 'missing'

        # Feature 58: minutes_volatility_last_10
        mins_vol = v17_data.get('minutes_volatility_last_10')
        features.append(float(mins_vol) if mins_vol is not None else float('nan'))
        feature_sources[58] = 'calculated' if mins_vol is not None else 'missing'

        # Feature 59: opponent_pace_mismatch (computed from existing features 22 and 14)
        team_pace_val = features[22]    # team_pace
        opp_pace_val = features[14]     # opponent_pace
        if team_pace_val is not None and opp_pace_val is not None:
            try:
                features.append(float(team_pace_val) - float(opp_pace_val))
                feature_sources[59] = 'calculated'
            except (TypeError, ValueError):
                features.append(float('nan'))
                feature_sources[59] = 'missing'
        else:
            features.append(float('nan'))
            feature_sources[59] = 'missing'

        return features, feature_sources
    
    @staticmethod
    def _is_valid_value(val) -> bool:
        """Check if a value is non-None and non-NaN (handles pandas NaN from BQ NULL)."""
        if val is None:
            return False
        if isinstance(val, float) and math.isnan(val):
            return False
        return True

    def _get_feature_with_fallback(self, index: int, field_name: str,
                                   phase4_data: Dict, phase3_data: Dict,
                                   default: float, feature_sources: Dict) -> float:
        """
        Get feature with Phase 4 → Phase 3 → default fallback.
        NaN-safe: BQ NULL → pandas NaN is treated as missing.
        """
        # Try Phase 4 first
        if field_name in phase4_data and self._is_valid_value(phase4_data[field_name]):
            feature_sources[index] = 'phase4'
            return float(phase4_data[field_name])

        # Fallback to Phase 3
        if field_name in phase3_data and self._is_valid_value(phase3_data[field_name]):
            feature_sources[index] = 'phase3'
            return float(phase3_data[field_name])

        # Last resort: default
        feature_sources[index] = 'default'
        return float(default)

    def _get_feature_nullable(self, index: int, field_name: str,
                              phase4_data: Dict, phase3_data: Dict,
                              feature_sources: Dict) -> Optional[float]:
        """
        Get feature value, returning None if not available (no default fallback).
        NaN-safe: BQ NULL → pandas NaN is treated as missing.
        """
        # Try Phase 4 first
        if field_name in phase4_data and self._is_valid_value(phase4_data[field_name]):
            feature_sources[index] = 'phase4'
            return float(phase4_data[field_name])

        # Fallback to Phase 3
        if field_name in phase3_data and self._is_valid_value(phase3_data[field_name]):
            feature_sources[index] = 'phase3'
            return float(phase3_data[field_name])

        # Data not available - return None instead of default
        feature_sources[index] = 'missing'
        return None
    
    def _get_injured_teammates_ppg(self, team_abbr: str, game_date: date) -> float:
        """
        Calculate total PPG of injured teammates (OUT/QUESTIONABLE/DOUBTFUL).

        Session 127B: Uses NBA.com official injury reports as primary source,
        with Ball Don't Lie as fallback.

        Impact: 30+ PPG injured → 24.5% breakout rate vs 16.2% baseline

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL', 'OKC')
            game_date: Game date to check injuries for

        Returns:
            float: Sum of season PPG for injured teammates
        """
        try:
            # Get previous day's feature store data for season PPG lookup
            prev_date = game_date - timedelta(days=1)

            # PRIMARY: NBA.com official injury reports
            query_nbacom = f"""
            WITH latest_features AS (
              SELECT
                player_lookup,
                feature_2_value as season_ppg
              FROM `nba_predictions.ml_feature_store_v2`
              WHERE game_date = '{prev_date.isoformat()}'
                AND feature_2_value > 0  -- Only players with PPG
            ),
            injured_players AS (
              SELECT DISTINCT
                i.player_lookup,
                COALESCE(f.season_ppg, 0) as season_ppg
              FROM `nba_raw.nbac_injury_report` i
              LEFT JOIN latest_features f
                ON i.player_lookup = f.player_lookup
              WHERE i.game_date = '{game_date.isoformat()}'
                AND i.team = '{team_abbr}'
                AND i.injury_status IN ('out', 'questionable', 'doubtful')
                AND i.confidence_score >= 0.6  -- Only confident parses
            )
            SELECT
              ROUND(SUM(season_ppg), 1) as total_injured_ppg,
              COUNT(DISTINCT player_lookup) as injured_count
            FROM injured_players
            """

            result = self.bq_client.query(query_nbacom).to_dataframe()

            # Check if NBA.com has data
            if not result.empty and result['injured_count'].iloc[0] > 0:
                injured_ppg = float(result['total_injured_ppg'].iloc[0] or 0.0)
                logger.debug(f"Team {team_abbr}: {injured_ppg:.1f} PPG injured (NBA.com)")
                return injured_ppg

            # FALLBACK: Ball Don't Lie if NBA.com has no data
            logger.debug(f"Team {team_abbr}: No NBA.com data, trying BDL fallback")
            query_bdl = f"""
            WITH latest_features AS (
              SELECT
                player_lookup,
                feature_2_value as season_ppg
              FROM `nba_predictions.ml_feature_store_v2`
              WHERE game_date = '{prev_date.isoformat()}'
                AND feature_2_value > 0
            ),
            injured_players AS (
              SELECT DISTINCT
                i.player_lookup,
                COALESCE(f.season_ppg, 0) as season_ppg
              FROM `nba_raw.bdl_injuries` i
              LEFT JOIN latest_features f
                ON i.player_lookup = f.player_lookup
              WHERE i.scrape_date = '{game_date.isoformat()}'
                AND i.team_abbr = '{team_abbr}'
                AND i.injury_status_normalized IN ('out', 'questionable', 'doubtful')
            )
            SELECT ROUND(SUM(season_ppg), 1) as total_injured_ppg
            FROM injured_players
            """

            result = self.bq_client.query(query_bdl).to_dataframe()
            if result.empty or result['total_injured_ppg'].iloc[0] is None:
                logger.debug(f"Team {team_abbr}: No injury data from either source")
                return 0.0

            injured_ppg = float(result['total_injured_ppg'].iloc[0])
            logger.debug(f"Team {team_abbr}: {injured_ppg:.1f} PPG injured (BDL fallback)")
            return injured_ppg

        except Exception as e:
            logger.warning(f"Failed to get injured teammates PPG for {team_abbr}: {e}")
            return 0.0  # Fallback to 0 if query fails

    def _get_feature_phase4_only(self, index: int, field_name: str,
                                 phase4_data: Dict, default: float,
                                 feature_sources: Dict) -> float:
        """
        Get feature from Phase 4 ONLY (no Phase 3 fallback).
        NaN-safe: BQ NULL → pandas NaN is treated as missing.
        """
        if field_name in phase4_data and self._is_valid_value(phase4_data[field_name]):
            feature_sources[index] = 'phase4'
            return float(phase4_data[field_name])

        # No Phase 3 fallback - use default
        feature_sources[index] = 'default'
        logger.warning(f"Feature {index} ({field_name}) missing from Phase 4, using default={default}")
        return float(default)
    
    # ========================================================================
    # SAVE TO BIGQUERY (Override base class)
    # ========================================================================
    
    def save_precompute(self) -> None:
        """
        Save feature vectors to BigQuery using BatchWriter.
        
        Overrides base class because:
        1. Cross-dataset write (nba_predictions not nba_precompute)
        2. Uses specialized BatchWriter with retry logic
        3. Different merge key (player_lookup + game_date)
        """
        if not self.transformed_data:
            logger.warning("No transformed data to write")
            return
        
        analysis_date = self.opts['analysis_date']
        
        logger.info(f"Writing {len(self.transformed_data)} feature records to {self.dataset_id}.{self.table_name}")

        # Session 49: Validate batch variance BEFORE writing
        # This catches bugs like team_win_pct=0.5 due to missing field passthrough
        variance_result = validate_batch_variance(self.transformed_data, min_records=50)
        if variance_result.get('critical_errors'):
            logger.error(
                f"BATCH_VARIANCE_CRITICAL: {len(variance_result['critical_errors'])} critical variance issues detected:\n"
                f"  {', '.join(variance_result['critical_errors'][:5])}"
            )
            # Track but don't block (can change to raise ValueError after validation)
            self.stats['variance_critical_errors'] = len(variance_result['critical_errors'])
        if variance_result.get('warnings'):
            logger.warning(
                f"BATCH_VARIANCE_WARNING: {len(variance_result['warnings'])} low variance issues:\n"
                f"  {', '.join(variance_result['warnings'][:3])}"
            )
            self.stats['variance_warnings'] = len(variance_result['warnings'])

        # Session 99: Convert feature_sources dict to JSON string for BigQuery storage
        # This provides complete per-feature audit trail
        import json
        rows_to_write = []
        for row in self.transformed_data:
            row_copy = row.copy()
            # Convert feature_sources dict to JSON string
            if 'feature_sources' in row_copy and isinstance(row_copy['feature_sources'], dict):
                row_copy['feature_sources_json'] = json.dumps(row_copy['feature_sources'])
            del row_copy['feature_sources']  # Remove original dict (not valid BQ type)
            rows_to_write.append(row_copy)

        # Write using BatchWriter (handles DELETE + batch INSERT with retries)
        write_stats = self.batch_writer.write_batch(
            rows=rows_to_write,
            dataset_id=self.dataset_id,  # nba_predictions
            table_name=self.table_name,   # ml_feature_store_v2
            game_date=analysis_date
        )
        
        # Track stats for monitoring
        self.stats['rows_processed'] = write_stats['rows_processed']
        self.stats['rows_failed'] = write_stats['rows_failed']
        self.stats['batches_written'] = write_stats['batches_written']
        self.stats['batches_failed'] = write_stats['batches_failed']
        
        if write_stats['errors']:
            logger.error(f"Write errors: {write_stats['errors']}")
        
        logger.info(f"Write complete: {write_stats['rows_processed']}/{len(self.transformed_data)} rows "
                   f"({write_stats['batches_written']} batches)")

        # Session 158: Post-write validation — catches contamination early
        self._validate_written_data(analysis_date)

    def _validate_written_data(self, analysis_date: date) -> None:
        """
        Session 158: Validate written feature store data for contamination.

        Queries the just-written records and checks for high default rates,
        which indicate upstream processor failures (e.g., Session 157 scenario
        where composite factors didn't run and 33.2% of training data was contaminated).

        This is observability-only — data is already written, but alerts enable
        fast response to quality issues before they contaminate training data.
        """
        try:
            date_str = analysis_date.isoformat() if isinstance(analysis_date, date) else str(analysis_date)

            query = f"""
            SELECT
                COUNT(*) as total_records,
                COUNTIF(required_default_count > 0) as records_with_defaults,
                ROUND(COUNTIF(required_default_count > 0) * 100.0 / NULLIF(COUNT(*), 0), 1) as pct_with_defaults,
                ROUND(AVG(required_default_count), 2) as avg_required_defaults,
                COUNTIF(is_quality_ready = TRUE) as quality_ready_count,
                ROUND(COUNTIF(is_quality_ready = TRUE) * 100.0 / NULLIF(COUNT(*), 0), 1) as pct_quality_ready,
                ROUND(AVG(default_feature_count), 2) as avg_total_defaults,
                ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality,
                ROUND(AVG(feature_quality_score), 1) as avg_quality_score
            FROM `{self.project_id}.{self.dataset_id}.{self.table_name}`
            WHERE game_date = '{date_str}'
            """

            result = list(self.bq_client.query(query).result())
            if not result or result[0].total_records == 0:
                logger.warning(f"POST_WRITE_VALIDATION: No records found for {date_str} — possible write failure")
                return

            row = result[0]
            total = row.total_records
            pct_defaults = float(row.pct_with_defaults or 0)
            pct_ready = float(row.pct_quality_ready or 0)
            avg_matchup = float(row.avg_matchup_quality or 0)

            # Always log quality summary for observability
            logger.info(
                f"POST_WRITE_VALIDATION [{date_str}]: "
                f"{total} records, "
                f"{pct_defaults:.1f}% with required defaults, "
                f"{pct_ready:.1f}% quality-ready, "
                f"avg_matchup_quality={avg_matchup:.1f}, "
                f"avg_defaults={row.avg_total_defaults:.2f}, "
                f"avg_quality_score={row.avg_quality_score:.1f}"
            )

            # Track in stats for run history
            self.stats['post_write_pct_with_defaults'] = pct_defaults
            self.stats['post_write_pct_quality_ready'] = pct_ready
            self.stats['post_write_avg_matchup_quality'] = avg_matchup

            # Alert if contamination is high (>30% indicates upstream processor failure)
            if pct_defaults > 30:
                logger.error(
                    f"POST_WRITE_CONTAMINATION_ALERT [{date_str}]: "
                    f"{pct_defaults:.1f}% of records have required defaults! "
                    f"This indicates an upstream Phase 4 processor may not have run. "
                    f"avg_matchup_quality={avg_matchup:.1f}, quality_ready={pct_ready:.1f}%"
                )
                self._send_contamination_alert(date_str, total, pct_defaults, pct_ready, avg_matchup)

        except Exception as e:
            # Non-blocking — validation failure should not prevent completion
            logger.warning(f"POST_WRITE_VALIDATION: Failed to validate written data: {e}")

    def _send_contamination_alert(self, date_str: str, total: int, pct_defaults: float,
                                   pct_ready: float, avg_matchup: float) -> None:
        """Send Slack alert when post-write validation detects high contamination."""
        try:
            webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
            if not webhook_url:
                logger.warning("SLACK_WEBHOOK_URL not configured, skipping contamination alert")
                return

            from shared.utils.slack_retry import send_slack_webhook_with_retry

            payload = {
                "attachments": [{
                    "color": "#FF0000",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "ML Feature Store Contamination Alert",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*High default rate detected in feature store data for {date_str}!*\n"
                                       f"This may indicate an upstream Phase 4 processor didn't run."
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Date:*\n{date_str}"},
                                {"type": "mrkdwn", "text": f"*Records:*\n{total}"},
                                {"type": "mrkdwn", "text": f"*With Defaults:*\n{pct_defaults:.1f}%"},
                                {"type": "mrkdwn", "text": f"*Quality Ready:*\n{pct_ready:.1f}%"},
                            ]
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": f"Avg matchup quality: {avg_matchup:.1f}. "
                                       f"Session 158 prevention mechanism. Check Phase 4 processor logs."
                            }]
                        }
                    ]
                }]
            }

            send_slack_webhook_with_retry(webhook_url, payload, timeout=10)
            logger.info(f"Contamination alert sent for {date_str}")

        except Exception as e:
            logger.warning(f"Failed to send contamination alert: {e}")

    # ========================================================================
    # PARALLELIZATION METHODS
    # ========================================================================

    def _process_players_parallel(
        self,
        players_with_games: List[Dict],
        completeness_results: dict,
        upstream_completeness: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Process all players using ThreadPoolExecutor."""
        # Determine worker count with environment variable support
        DEFAULT_WORKERS = 10
        max_workers = int(os.environ.get(
            'MLFS_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        logger.info(f"Processing {len(players_with_games)} players with {max_workers} workers (parallel mode)")

        loop_start = time.time()
        processed_count = 0
        successful = []
        failed = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._process_single_player,
                    player_row,
                    completeness_results,
                    upstream_completeness,
                    is_bootstrap,
                    is_season_boundary,
                    analysis_date
                ): player_row.get('player_lookup', 'unknown')
                for player_row in players_with_games
            }

            for future in as_completed(futures):
                player_lookup = futures[future]
                processed_count += 1

                try:
                    success, data = future.result()
                    if success:
                        successful.append(data)
                    else:
                        failed.append(data)

                    # Progress logging every 50 players
                    if processed_count % 50 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed
                        remaining = len(players_with_games) - processed_count
                        eta = remaining / rate if rate > 0 else 0
                        logger.info(
                            f"Player processing progress: {processed_count}/{len(players_with_games)} "
                            f"| Rate: {rate:.1f} players/sec | ETA: {eta/60:.1f}min"
                        )
                except Exception as e:
                    logger.error(f"Error processing {player_lookup}: {e}")
                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': str(e),
                        'category': 'PROCESSING_ERROR',
                        'can_retry': False
                    })

        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(successful)} players in {total_time:.1f}s "
            f"(avg {total_time/len(successful) if successful else 0:.2f}s/player) "
            f"| {len(failed)} failed"
        )

        return successful, failed

    def _process_single_player(
        self,
        player_row: Dict,
        completeness_results: dict,
        upstream_completeness: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Process one player (thread-safe). Returns (success: bool, data: dict)."""
        try:
            player_lookup = player_row.get('player_lookup', 'unknown')

            # Get completeness for this player
            completeness = completeness_results.get(player_lookup, {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            })

            # Check circuit breaker
            circuit_breaker_status = self._check_circuit_breaker(player_lookup, analysis_date)

            if circuit_breaker_status['active']:
                logger.warning(
                    f"{player_lookup}: Circuit breaker active until "
                    f"{circuit_breaker_status['until']} - skipping"
                )
                return (False, {
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                    'category': 'CIRCUIT_BREAKER_ACTIVE'
                })

            # BACKFILL MODE FIX: Skip completeness checks in backfill mode
            # Session 170: Also skip in same-day mode (skip_dependency_check=True or strict_mode=False)
            # Session 6 (2026-01-10): Also skip for same-day/future games (games haven't been played)
            is_same_day_or_future = analysis_date >= date.today()
            skip_completeness_checks = (
                self.is_backfill_mode or
                is_bootstrap or
                self.opts.get('skip_dependency_check', False) or
                not self.opts.get('strict_mode', True) or
                is_same_day_or_future  # Games haven't been played yet
            )

            # Check production readiness (skip if incomplete, unless in bootstrap/backfill/same-day mode)
            if not completeness['is_production_ready'] and not skip_completeness_checks:
                logger.warning(
                    f"{player_lookup}: Completeness {completeness['completeness_pct']:.1f}% "
                    f"({completeness['actual_count']}/{completeness['expected_count']} games) - skipping"
                )

                # Track reprocessing attempt
                self._increment_reprocess_count(
                    player_lookup, analysis_date,
                    completeness['completeness_pct'],
                    'incomplete_own_data'
                )

                return (False, {
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': f"Incomplete own data: {completeness['completeness_pct']:.1f}%",
                    'category': 'INCOMPLETE_DATA_SKIPPED'
                })

            # Check upstream completeness (CASCADE PATTERN)
            upstream_status = upstream_completeness.get(player_lookup, {
                'player_daily_cache_ready': False,
                'player_composite_factors_ready': False,
                'player_shot_zone_ready': False,
                'team_defense_zone_ready': False,
                'all_upstreams_ready': False
            })

            if not upstream_status['all_upstreams_ready'] and not skip_completeness_checks:
                logger.warning(
                    f"{player_lookup}: Upstream not ready "
                    f"(daily_cache={upstream_status['player_daily_cache_ready']}, "
                    f"composite={upstream_status['player_composite_factors_ready']}, "
                    f"shot_zone={upstream_status['player_shot_zone_ready']}, "
                    f"team_defense={upstream_status['team_defense_zone_ready']}) - skipping"
                )

                # Track reprocessing attempt
                self._increment_reprocess_count(
                    player_lookup, analysis_date,
                    completeness['completeness_pct'],
                    'incomplete_upstream_dependencies'
                )

                return (False, {
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': f"Upstream Phase 4 dependencies not ready",
                    'category': 'UPSTREAM_INCOMPLETE'
                })

            # Generate features for this player
            start_time = datetime.now()
            record = self._generate_player_features(player_row, completeness, upstream_status, circuit_breaker_status, is_bootstrap, is_season_boundary)
            generation_time_ms = (datetime.now() - start_time).total_seconds() * 1000

            record['feature_generation_time_ms'] = int(generation_time_ms)

            # ============================================================
            # PRE-WRITE VALIDATION (Session 48 - Feature Quality)
            # Validate feature ranges BEFORE writing to BigQuery
            # This catches bugs like fatigue_score=0 immediately
            # ============================================================
            is_valid, warnings, critical_errors = validate_feature_ranges(
                record.get('features', []),
                player_lookup
            )

            # Add validation issues to data_quality_issues for tracking
            if warnings:
                record['data_quality_issues'] = record.get('data_quality_issues', []) + [
                    f"range_warning:{w}" for w in warnings[:3]  # Limit to 3 to avoid bloat
                ]

            if critical_errors:
                # BLOCK write for critical validation failures
                logger.error(
                    f"BLOCKING_WRITE [{player_lookup}]: Critical validation failed: {critical_errors}"
                )
                return (False, {
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': f"Critical feature validation failed: {critical_errors}",
                    'category': 'FEATURE_VALIDATION_ERROR'
                })
            # ============================================================

            return (True, record)

        except Exception as e:
            player_lookup = player_row.get('player_lookup', 'unknown')
            logger.error(f"Failed to process {player_lookup}: {e}")
            return (False, {
                'entity_id': player_lookup,
                'entity_type': 'player',
                'reason': str(e),
                'category': 'calculation_error'
            })

    def _process_players_serial(
        self,
        players_with_games: List[Dict],
        completeness_results: dict,
        upstream_completeness: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Original serial processing (kept for fallback)."""
        logger.info(f"Calculating features for {len(players_with_games)} players (serial mode)")

        successful = []
        failed = []

        for idx, player_row in enumerate(players_with_games):
            try:
                player_lookup = player_row.get('player_lookup', 'unknown')

                # Get completeness for this player
                completeness = completeness_results.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })

                # Check circuit breaker
                circuit_breaker_status = self._check_circuit_breaker(player_lookup, analysis_date)

                if circuit_breaker_status['active']:
                    logger.warning(
                        f"{player_lookup}: Circuit breaker active until "
                        f"{circuit_breaker_status['until']} - skipping"
                    )
                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE'
                    })
                    continue

                # BACKFILL MODE FIX: Skip completeness checks in backfill mode
                # Session 170: Also skip in same-day mode (skip_dependency_check=True or strict_mode=False)
                skip_completeness_checks = (
                    self.is_backfill_mode or
                    is_bootstrap or
                    self.opts.get('skip_dependency_check', False) or
                    not self.opts.get('strict_mode', True)
                )

                # Check production readiness (skip if incomplete, unless in bootstrap/backfill/same-day mode)
                if not completeness['is_production_ready'] and not skip_completeness_checks:
                    logger.warning(
                        f"{player_lookup}: Completeness {completeness['completeness_pct']:.1f}% "
                        f"({completeness['actual_count']}/{completeness['expected_count']} games) - skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_own_data'
                    )

                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Incomplete own data: {completeness['completeness_pct']:.1f}%",
                        'category': 'INCOMPLETE_DATA_SKIPPED'
                    })
                    continue

                # Check upstream completeness (CASCADE PATTERN)
                upstream_status = upstream_completeness.get(player_lookup, {
                    'player_daily_cache_ready': False,
                    'player_composite_factors_ready': False,
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'all_upstreams_ready': False
                })

                if not upstream_status['all_upstreams_ready'] and not skip_completeness_checks:
                    logger.warning(
                        f"{player_lookup}: Upstream not ready "
                        f"(daily_cache={upstream_status['player_daily_cache_ready']}, "
                        f"composite={upstream_status['player_composite_factors_ready']}, "
                        f"shot_zone={upstream_status['player_shot_zone_ready']}, "
                        f"team_defense={upstream_status['team_defense_zone_ready']}) - skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_upstream_dependencies'
                    )

                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Upstream Phase 4 dependencies not ready",
                        'category': 'UPSTREAM_INCOMPLETE'
                    })
                    continue

                # Generate features for this player
                start_time = datetime.now()
                record = self._generate_player_features(player_row, completeness, upstream_status, circuit_breaker_status, is_bootstrap, is_season_boundary)
                generation_time_ms = (datetime.now() - start_time).total_seconds() * 1000

                record['feature_generation_time_ms'] = int(generation_time_ms)

                successful.append(record)

                if (idx + 1) % 50 == 0:
                    logger.info(f"Processed {idx + 1}/{len(players_with_games)} players")

            except Exception as e:
                player_lookup = player_row.get('player_lookup', 'unknown')
                logger.error(f"Failed to process {player_lookup}: {e}")

                failed.append({
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': str(e),
                    'category': 'calculation_error'
                })

        return successful, failed

    # ========================================================================
    # STATS & REPORTING
    # ========================================================================

    def get_precompute_stats(self) -> dict:
        """Get processor-specific stats for logging with timing breakdown."""
        stats = {
            'players_processed': len(self.transformed_data) if self.transformed_data else 0,
            'players_failed': len(self.failed_entities) if hasattr(self, 'failed_entities') else 0,
            'early_season': self.early_season_flag,
            'feature_version': self.feature_version,
            'feature_count': self.feature_count,
        }

        # Add timing breakdown if available
        if self._timing:
            stats['timing'] = self._timing

            # Log timing summary
            total = self._timing.get('extract_raw_data', 0) + self._timing.get('calculate_precompute', 0)
            if total > 0:
                logger.info(
                    f"📊 PERFORMANCE TIMING BREAKDOWN:\n"
                    f"   Extract Phase: {self._timing.get('extract_raw_data', 0):.1f}s\n"
                    f"     - check_dependencies: {self._timing.get('check_dependencies', 0):.1f}s\n"
                    f"     - get_players_with_games: {self._timing.get('get_players_with_games', 0):.1f}s\n"
                    f"     - batch_extract_all_data: {self._timing.get('batch_extract_all_data', 0):.1f}s\n"
                    f"   Calculate Phase: {self._timing.get('calculate_precompute', 0):.1f}s\n"
                    f"     - completeness_check: {self._timing.get('completeness_check', 0):.1f}s\n"
                    f"     - player_processing: {self._timing.get('player_processing', 0):.1f}s\n"
                    f"   (Write timing in BatchWriter logs above)"
                )

        return stats


def main():
    """Main entry point for command-line execution."""
    import argparse

    parser = argparse.ArgumentParser(description='ML Feature Store V2 Processor')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--force', action='store_true', help='Force reprocessing')
    parser.add_argument('--backfill', action='store_true', help='Backfill mode')

    args = parser.parse_args()

    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Process date range
    current_date = start_date
    while current_date <= end_date:
        logger.info(f"Processing {current_date}...")

        # Initialize processor
        processor = MLFeatureStoreProcessor()

        # Set options
        processor.opts = {
            'analysis_date': current_date,
            'force': args.force,
            'backfill': args.backfill
        }

        try:
            # Extract data
            logger.info("Starting data extraction...")
            processor.extract_raw_data()

            # Calculate features
            logger.info("Starting feature calculation...")
            processor.calculate_precompute()

            # Save results
            logger.info("Saving features to BigQuery...")
            success = processor.save_precompute()

            if success:
                logger.info(f"✓ ML feature store processing complete for {current_date}!")
                logger.info(f"  - Processed: {len(processor.transformed_data)} players")
                logger.info(f"  - Failed: {len(processor.failed_entities)} players")
            else:
                logger.error(f"✗ Failed to save ML feature store for {current_date}")

        except Exception as e:
            logger.error(f"✗ Fatal error for {current_date}: {e}", exc_info=True)

        # Move to next date
        current_date += timedelta(days=1)

    return 0


if __name__ == '__main__':
    exit(main())