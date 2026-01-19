#!/usr/bin/env python3
"""
Path: data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py

Player Shot Zone Analysis Processor

Analyzes each player's shot distribution and efficiency by court zone over their
last 10 games. Produces pre-calculated shot zone metrics for Phase 5 predictions.

Input: nba_analytics.player_game_summary (last 10 games per player)
Output: nba_precompute.player_shot_zone_analysis
Strategy: MERGE (update existing or insert new)
Schedule: Nightly at 11:15 PM (after team defense completes)
Duration: ~5-8 minutes for 450 players

Shot Zones:
- Paint: ≤8 feet from basket
- Mid-range: 9+ feet, 2-point shots
- Three-point: Beyond the arc

Version: 1.0 with v4.0 dependency tracking
Updated: October 30, 2025 - Fixed save method and datetime deprecations
"""

import logging
import os
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import time

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

# Smart Idempotency (Pattern #1)
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Completeness checking (Week 2 - Phase 4 Historical Dependency Checking)
from shared.utils.completeness_checker import CompletenessChecker

# Bootstrap period support (Week 5 - Early Season Handling)
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.validation.config import BOOTSTRAP_DAYS

# Custom exceptions for dependency handling
class DependencyError(Exception):
    """Raised when critical dependencies are missing."""
    pass

class DataTooStaleError(Exception):
    """Raised when source data is too old."""
    pass

logger = logging.getLogger(__name__)


# ============================================================
# MODULE-LEVEL FUNCTIONS FOR ProcessPoolExecutor
# ============================================================
# ProcessPoolExecutor requires picklable functions. Module-level functions
# are picklable, instance methods are not (they reference self with BQ client).

import hashlib

def _compute_hash_static(record: dict, hash_fields: list) -> str:
    """
    Compute SHA256 hash (16 chars) from meaningful fields only.
    Static version for ProcessPool workers.
    """
    hash_values = []
    for field in hash_fields:
        value = record.get(field)
        # Normalize value to string representation
        if value is None:
            normalized = "NULL"
        elif isinstance(value, (int, float)):
            normalized = str(value)
        elif isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value)
        hash_values.append(f"{field}:{normalized}")

    # Create canonical string (sorted for consistency)
    canonical_string = "|".join(sorted(hash_values))

    # Compute SHA256 hash
    hash_bytes = canonical_string.encode('utf-8')
    sha256_hash = hashlib.sha256(hash_bytes).hexdigest()

    # Return first 16 characters
    return sha256_hash[:16]


def _calculate_zone_metrics_static(games_df: pd.DataFrame) -> dict:
    """Calculate shot zone metrics (static version for worker processes)."""
    paint_att = games_df['paint_attempts'].sum()
    paint_makes = games_df['paint_makes'].sum()
    mid_att = games_df['mid_range_attempts'].sum()
    mid_makes = games_df['mid_range_makes'].sum()
    three_att = games_df['three_pt_attempts'].sum()
    three_makes = games_df['three_pt_makes'].sum()

    total_att = paint_att + mid_att + three_att
    total_makes = games_df['fg_makes'].sum()
    assisted_makes = games_df['assisted_fg_makes'].sum()
    unassisted_makes = games_df['unassisted_fg_makes'].sum()

    games_count = len(games_df)

    paint_rate = (paint_att / total_att * 100) if total_att > 0 else None
    mid_rate = (mid_att / total_att * 100) if total_att > 0 else None
    three_rate = (three_att / total_att * 100) if total_att > 0 else None

    paint_pct = (paint_makes / paint_att) if paint_att > 0 else None
    mid_pct = (mid_makes / mid_att) if mid_att > 0 else None
    three_pct = (three_makes / three_att) if three_att > 0 else None

    paint_pg = paint_att / games_count if games_count > 0 else None
    mid_pg = mid_att / games_count if games_count > 0 else None
    three_pg = three_att / games_count if games_count > 0 else None

    assisted_rate = (assisted_makes / total_makes * 100) if total_att > 0 and total_makes > 0 else None
    unassisted_rate = (unassisted_makes / total_makes * 100) if total_att > 0 and total_makes > 0 else None

    return {
        'paint_rate': round(paint_rate, 2) if paint_rate is not None else None,
        'mid_range_rate': round(mid_rate, 2) if mid_rate is not None else None,
        'three_pt_rate': round(three_rate, 2) if three_rate is not None else None,
        'paint_pct': round(paint_pct, 3) if paint_pct is not None else None,
        'mid_range_pct': round(mid_pct, 3) if mid_pct is not None else None,
        'three_pt_pct': round(three_pct, 3) if three_pct is not None else None,
        'paint_attempts_pg': round(paint_pg, 1) if paint_pg is not None else None,
        'mid_range_attempts_pg': round(mid_pg, 1) if mid_pg is not None else None,
        'three_pt_attempts_pg': round(three_pg, 1) if three_pg is not None else None,
        'assisted_rate': round(assisted_rate, 2) if assisted_rate is not None else None,
        'unassisted_rate': round(unassisted_rate, 2) if unassisted_rate is not None else None,
        'total_shots': int(total_att) if total_att > 0 else None
    }


def _determine_primary_zone_static(metrics: dict) -> Optional[str]:
    """Determine primary scoring zone (static version for worker processes)."""
    paint_rate = metrics.get('paint_rate', 0) or 0
    mid_rate = metrics.get('mid_range_rate', 0) or 0
    three_rate = metrics.get('three_pt_rate', 0) or 0

    if paint_rate == 0 and mid_rate == 0 and three_rate == 0:
        return None

    if paint_rate >= 40:
        return 'paint'
    elif three_rate >= 40:
        return 'perimeter'
    elif mid_rate >= 35:
        return 'mid_range'
    else:
        return 'balanced'


def _determine_quality_tier_static(games_count: int, min_games_required: int) -> str:
    """Assess data quality (static version for worker processes)."""
    if games_count >= min_games_required:
        return 'high'
    elif games_count >= 7:
        return 'medium'
    else:
        return 'low'


def _determine_sample_quality_static(games_count: int, target_window: int) -> str:
    """Assess sample quality (static version for worker processes)."""
    if games_count >= target_window:
        return 'excellent'
    elif games_count >= int(target_window * 0.7):
        return 'good'
    elif games_count >= int(target_window * 0.5):
        return 'limited'
    else:
        return 'insufficient'


def _process_single_player_worker(
    player_lookup: str,
    completeness: dict,
    circuit_breaker_status: dict,
    is_bootstrap: bool,
    is_season_boundary: bool,
    analysis_date: date,
    player_games_data: List[dict],
    sample_window: int,
    trend_window: int,
    min_games_required: int,
    source_hash: Optional[str],
    opts: dict,
    hash_fields: List[str]
) -> tuple:
    """
    Process one player in a separate process.

    This is a module-level function that can be pickled by ProcessPoolExecutor.
    All data must be passed as arguments (no access to class instance).

    Returns:
        tuple: (success: bool, data: dict, needs_reprocess_increment: bool)
    """
    try:
        # Check circuit breaker (pre-fetched status)
        if circuit_breaker_status['active']:
            return (False, {
                'entity_id': player_lookup,
                'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                'category': 'CIRCUIT_BREAKER_ACTIVE',
                'can_retry': False
            }, False)

        # Check production readiness
        if not completeness['is_production_ready'] and not is_bootstrap and not is_season_boundary:
            return (False, {
                'entity_id': player_lookup,
                'reason': (
                    f"Incomplete data: {completeness['completeness_pct']}% "
                    f"({completeness['actual_count']}/{completeness['expected_count']} games)"
                ),
                'category': 'INCOMPLETE_DATA',
                'can_retry': True
            }, True)  # needs_reprocess_increment = True

        # Convert to DataFrame
        if not player_games_data:
            return (False, {
                'entity_id': player_lookup,
                'reason': "No game data available",
                'category': 'INSUFFICIENT_DATA',
                'can_retry': True
            }, False)

        player_data = pd.DataFrame(player_games_data)

        # Separate windows
        games_10 = player_data[player_data['game_rank'] <= sample_window]
        games_20 = player_data[player_data['game_rank'] <= trend_window]

        # Check sufficient games
        if len(games_10) < min_games_required:
            actual_games = len(games_10)
            expected_games = completeness.get('expected_count', 0)

            if actual_games < min_games_required and expected_games < min_games_required:
                category = 'EXPECTED_INCOMPLETE'
                can_retry = False
                reason = f"Season bootstrap: {actual_games}/{expected_games} games (need {min_games_required})"
            else:
                category = 'INCOMPLETE_UPSTREAM'
                can_retry = True
                reason = f"Missing upstream data: {actual_games}/{expected_games} games (need {min_games_required})"

            return (False, {
                'entity_id': player_lookup,
                'reason': reason,
                'category': category,
                'can_retry': can_retry
            }, False)

        # Calculate metrics
        metrics_10 = _calculate_zone_metrics_static(games_10)
        metrics_20 = _calculate_zone_metrics_static(games_20) if len(games_20) >= 15 else {}

        primary_zone = _determine_primary_zone_static(metrics_10)
        quality_tier = _determine_quality_tier_static(len(games_10), min_games_required)
        sample_quality_10 = _determine_sample_quality_static(len(games_10), sample_window)
        sample_quality_20 = _determine_sample_quality_static(len(games_20), trend_window)

        # Build record
        record = {
            'player_lookup': player_lookup,
            'universal_player_id': player_data.iloc[0].get('universal_player_id'),
            'analysis_date': analysis_date.isoformat() if hasattr(analysis_date, 'isoformat') else str(analysis_date),

            'paint_rate_last_10': metrics_10.get('paint_rate'),
            'mid_range_rate_last_10': metrics_10.get('mid_range_rate'),
            'three_pt_rate_last_10': metrics_10.get('three_pt_rate'),
            'total_shots_last_10': metrics_10.get('total_shots'),
            'games_in_sample_10': int(len(games_10)),
            'sample_quality_10': sample_quality_10,

            'paint_pct_last_10': metrics_10.get('paint_pct'),
            'mid_range_pct_last_10': metrics_10.get('mid_range_pct'),
            'three_pt_pct_last_10': metrics_10.get('three_pt_pct'),

            'paint_attempts_per_game': metrics_10.get('paint_attempts_pg'),
            'mid_range_attempts_per_game': metrics_10.get('mid_range_attempts_pg'),
            'three_pt_attempts_per_game': metrics_10.get('three_pt_attempts_pg'),

            'paint_rate_last_20': metrics_20.get('paint_rate'),
            'paint_pct_last_20': metrics_20.get('paint_pct'),
            'games_in_sample_20': int(len(games_20)),
            'sample_quality_20': sample_quality_20,

            'assisted_rate_last_10': metrics_10.get('assisted_rate'),
            'unassisted_rate_last_10': metrics_10.get('unassisted_rate'),

            'player_position': None,
            'primary_scoring_zone': primary_zone,
            'data_quality_tier': quality_tier,
            'calculation_notes': None,

            'source_player_game_last_updated': f"{opts.get('analysis_date').isoformat()} 00:00:00" if opts.get('analysis_date') else None,
            'source_player_game_hash': source_hash,

            'early_season_flag': False,
            'insufficient_data_reason': None,

            'expected_games_count': completeness['expected_count'],
            'actual_games_count': completeness['actual_count'],
            'completeness_percentage': completeness['completeness_pct'],
            'missing_games_count': completeness['missing_count'],
            'is_production_ready': completeness['is_production_ready'],
            'data_quality_issues': [],
            'last_reprocess_attempt_at': None,
            'reprocess_attempt_count': circuit_breaker_status['attempts'],
            'circuit_breaker_active': circuit_breaker_status['active'],
            'circuit_breaker_until': (
                circuit_breaker_status['until'].isoformat()
                if circuit_breaker_status.get('until') and hasattr(circuit_breaker_status['until'], 'isoformat')
                else str(circuit_breaker_status['until']) if circuit_breaker_status.get('until') else None
            ),
            'manual_override_required': False,
            'season_boundary_detected': is_season_boundary,
            'backfill_bootstrap_mode': is_bootstrap,
            'processing_decision_reason': 'processed_successfully',

            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }

        # Compute hash (use module-level static function for ProcessPool compatibility)
        record['data_hash'] = _compute_hash_static(record, hash_fields)

        return (True, record, False)

    except Exception as e:
        return (False, {
            'entity_id': player_lookup,
            'reason': str(e),
            'category': 'PROCESSING_ERROR',
            'can_retry': False
        }, False)


class PlayerShotZoneAnalysisProcessor(
    SmartIdempotencyMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase
):
    """
    Analyze player shot distribution and efficiency by court zone.

    Calculates for each player:
    - Shot distribution rates (paint %, mid-range %, three-point %)
    - Efficiency by zone (FG% in each zone)
    - Volume by zone (attempts per game)
    - Shot creation (assisted vs unassisted rates)
    - Primary scoring zone identification

    Uses last 10 games for primary analysis, last 20 games for trend comparison.
    """

    # Smart Idempotency: Fields to hash (meaningful business fields only)
    HASH_FIELDS = [
        'player_lookup', 'universal_player_id', 'analysis_date',
        'paint_rate_last_10', 'mid_range_rate_last_10', 'three_pt_rate_last_10',
        'total_shots_last_10', 'games_in_sample_10', 'sample_quality_10',
        'paint_pct_last_10', 'mid_range_pct_last_10', 'three_pt_pct_last_10',
        'paint_attempts_per_game', 'mid_range_attempts_per_game', 'three_pt_attempts_per_game',
        'paint_rate_last_20', 'paint_pct_last_20', 'games_in_sample_20', 'sample_quality_20',
        'assisted_rate_last_10', 'unassisted_rate_last_10',
        'player_position', 'primary_scoring_zone',
        'data_quality_tier', 'calculation_notes'
    ]

    # Primary key fields for duplicate detection and MERGE operations
    PRIMARY_KEY_FIELDS = ['analysis_date', 'player_lookup']

    # Defensive check configuration (upstream Phase 3 dependency)
    upstream_processor_name = 'PlayerGameSummaryProcessor'
    upstream_table = 'nba_analytics.player_game_summary'
    lookback_days = 10  # Must match min_games_required

    def __init__(self):
        """Initialize the processor."""
        super().__init__()

        # Table configuration
        self.table_name = 'player_shot_zone_analysis'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'

        # Processing requirements
        self.min_games_required = 10  # Minimum games for quality analysis
        self.sample_window = 10       # Primary analysis window
        self.trend_window = 20        # Broader trend window

        # BigQuery client already initialized by PrecomputeProcessorBase with pooling
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

        # Initialize completeness checker (Week 2 - Phase 4 Completeness Checking)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # Data containers
        self.raw_data = None
        self.transformed_data = []
        self.failed_entities = []

        # Source hash cache (extracted from upstream table)
        self.source_hash = None

        # Season start date (will be set in extract_raw_data)
        self.season_start_date = None

        logger.info(f"Initialized {self.__class__.__name__}")

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 3 Analytics sources - RELEVANT (depends on these)
        'player_game_summary': True,
        'team_offense_game_summary': True,
        'team_defense_game_summary': True,

        # Play-by-play sources - RELEVANT (for shot zone data)
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Phase 4 Precompute sources - NOT RELEVANT (this processor doesn't depend on other Phase 4 tables)
        'player_composite_factors': False,
        'team_defense_zone_analysis': False,
        'player_daily_cache': False,

        # Phase 2 Raw sources - NOT RELEVANT (Phase 4 reads from Phase 3, not Phase 2 directly)
        'nbac_gamebook_player_stats': False,
        'bdl_player_boxscores': False,
        'nbac_team_boxscore': False,
        'odds_api_player_points_props': False,
        'odds_api_game_lines': False,
        'nbac_schedule': False,
        'nbac_injury_report': False
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = False      # Don't skip - analyzes historical games
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - can analyze any past date

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    def get_dependencies(self) -> dict:
        """
        Define source table requirements.
        
        Returns:
            dict: Dependency configuration for player_game_summary
        """
        return {
            'nba_analytics.player_game_summary': {
                'field_prefix': 'source_player_game',
                'description': 'Player game-level shot zone stats',
                'check_type': 'per_player_game_count',
                
                # Requirements
                'min_games_required': self.min_games_required,
                'min_players_with_data': 400,  # Expect at least 400 active players
                'entity_field': 'player_lookup',
                
                # Freshness thresholds
                'max_age_hours_warn': 24,   # Warn if >24 hours old
                'max_age_hours_fail': 72,   # Fail if >72 hours old
                
                # Early season handling (first 2 weeks of season)
                'early_season_days': 14,
                'early_season_behavior': 'WRITE_PLACEHOLDER',
                
                'critical': True
            }
        }
    
    def extract_raw_data(self) -> None:
        """
        Extract player game data from Phase 3 analytics.

        Bootstrap Period Handling:
            Skips processing for first 7 days of season (days 0-6).
            Uses schedule service to determine season start date.

        Queries last 10 games (and last 20 for trends) per player from
        player_game_summary. Includes dependency checking and early season handling.
        """
        analysis_date = self.opts.get('analysis_date')
        if not analysis_date:
            raise ValueError("analysis_date is required")

        # Determine season year
        season_year = self.opts.get('season_year')
        if season_year is None:
            season_year = get_season_year_from_date(analysis_date)
            self.opts['season_year'] = season_year
            logger.debug(f"Determined season year: {season_year} for date {analysis_date}")

        # BOOTSTRAP PERIOD: Skip early season (days 0-13)
        # Uses schedule service to get accurate season start date
        if is_early_season(analysis_date, season_year, days_threshold=BOOTSTRAP_DAYS):
            logger.info(
                f"⏭️  Skipping {analysis_date}: early season period (day 0-{BOOTSTRAP_DAYS-1} of season {season_year}). "
                f"Regular processing starts day {BOOTSTRAP_DAYS}."
            )
            # Set flag for run history logging
            self.stats['processing_decision'] = 'skipped_early_season'
            self.stats['processing_decision_reason'] = f'bootstrap_period_day_0_{BOOTSTRAP_DAYS-1}_of_season_{season_year}'

            # Exit early - no data extraction, no records written
            self.raw_data = None
            return

        logger.info(f"Extracting player shot zone data for {analysis_date}")

        # Use cached dependency check from precompute_base.run()
        # (already checked and validated, track_source_usage already called)
        dep_check = self.dep_check

        # Handle early season (not enough games yet)
        if dep_check and dep_check.get('is_early_season'):
            logger.warning(f"Early season detected: {dep_check.get('early_season_reason')}")
            self._write_placeholder_rows(dep_check)
            return

        # Note: critical dependency and stale checks already done in precompute_base.run()
        
        # Determine season start date (for filtering)
        season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1
        season_start_date = date(season_year, 10, 1)
        self.season_start_date = season_start_date  # Store for completeness checking
        
        # Query player game data
        # Get last 20 games to support both 10-game and 20-game windows
        query = f"""
        WITH ranked_games AS (
            SELECT 
                -- Identifiers
                player_lookup,
                universal_player_id,
                game_id,
                game_date,
                opponent_team_abbr,
                
                -- Shot zone fields
                paint_attempts,
                paint_makes,
                mid_range_attempts,
                mid_range_makes,
                three_pt_attempts,
                three_pt_makes,
                
                -- Shot creation
                assisted_fg_makes,
                unassisted_fg_makes,
                fg_makes,
                
                -- Supporting fields
                minutes_played,
                is_active,
                
                -- Rank by recency
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup 
                    ORDER BY game_date DESC
                ) as game_rank
                
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date <= '{analysis_date}'
              AND game_date >= '{season_start_date}'
              AND is_active = TRUE
              AND (minutes_played > 0 OR fg_attempts > 0)  -- Fallback for historical data where minutes_played is NULL
        )
        SELECT * 
        FROM ranked_games
        WHERE game_rank <= {self.trend_window}
        ORDER BY player_lookup, game_date DESC
        """
        
        logger.info(f"Querying player_game_summary for last {self.trend_window} games per player")
        
        try:
            self.raw_data = self.bq_client.query(query).to_dataframe()
            
            if self.raw_data.empty:
                logger.warning(f"No player game data found for {analysis_date}")
                return
            
            logger.info(f"Extracted {len(self.raw_data)} game records for "
                       f"{self.raw_data['player_lookup'].nunique()} players")

            # Extract source hash from upstream table (Smart Reprocessing - Pattern #3)
            self._extract_source_hash()

        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            raise

    def _extract_source_hash(self) -> None:
        """
        Extract data_hash from upstream Phase 3 table (player_game_summary).

        This hash represents the source data used for this analysis.
        Used for Smart Reprocessing (Pattern #3) to skip processing when
        upstream data hasn't changed.
        """
        try:
            query = f"""
            SELECT data_hash
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date <= '{self.opts['analysis_date']}'
              AND data_hash IS NOT NULL
            ORDER BY processed_at DESC
            LIMIT 1
            """

            result = self.bq_client.query(query).to_dataframe()

            if not result.empty and result['data_hash'].iloc[0]:
                self.source_hash = str(result['data_hash'].iloc[0])
                logger.info(f"Extracted source hash: {self.source_hash[:16]}...")
            else:
                logger.warning("No data_hash found in upstream table")
                self.source_hash = None

        except Exception as e:
            logger.warning(f"Failed to extract source hash: {e}")
            self.source_hash = None

    def _write_placeholder_rows(self, dep_check: dict) -> None:
        """
        Write placeholder rows for early season when insufficient games available.
        
        Args:
            dep_check: Dependency check results with early season info
        """
        analysis_date = self.opts.get('analysis_date')
        
        logger.info(f"Writing early season placeholders for {analysis_date}")
        
        # Query active players (even if <10 games)
        query = f"""
        SELECT DISTINCT
            player_lookup,
            universal_player_id
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date <= '{analysis_date}'
          AND game_date >= DATE_SUB('{analysis_date}', INTERVAL 30 DAY)
          AND is_active = TRUE
        """
        
        try:
            players_df = self.bq_client.query(query).to_dataframe()
            
            placeholder_rows = []
            for _, player in players_df.iterrows():
                row = {
                    # Identifiers
                    'player_lookup': player['player_lookup'],
                    'universal_player_id': player.get('universal_player_id'),
                    'analysis_date': analysis_date.isoformat(),
                    
                    # All metrics NULL for early season
                    'paint_rate_last_10': None,
                    'mid_range_rate_last_10': None,
                    'three_pt_rate_last_10': None,
                    'total_shots_last_10': None,
                    'games_in_sample_10': 0,
                    'sample_quality_10': 'insufficient',
                    
                    'paint_pct_last_10': None,
                    'mid_range_pct_last_10': None,
                    'three_pt_pct_last_10': None,
                    
                    'paint_attempts_per_game': None,
                    'mid_range_attempts_per_game': None,
                    'three_pt_attempts_per_game': None,
                    
                    'paint_rate_last_20': None,
                    'paint_pct_last_20': None,
                    'games_in_sample_20': 0,
                    'sample_quality_20': 'insufficient',
                    
                    'assisted_rate_last_10': None,
                    'unassisted_rate_last_10': None,
                    
                    'player_position': None,
                    'primary_scoring_zone': None,
                    
                    'data_quality_tier': 'low',
                    'calculation_notes': 'Early season - insufficient games for analysis',
                    
                    # v4.0 source tracking
                    **self.build_source_tracking_fields(),
                    
                    # Early season flags
                    'early_season_flag': True,
                    'insufficient_data_reason': dep_check.get('early_season_reason', 
                                                              'Season start - insufficient games'),
                    
                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                # Add source hash (Smart Reprocessing - Pattern #3)
                row['source_player_game_hash'] = self.source_hash

                # Compute and add data hash (Smart Idempotency - Pattern #1)
                row['data_hash'] = self.compute_data_hash(row)

                placeholder_rows.append(row)
            
            self.transformed_data = placeholder_rows
            logger.info(f"Created {len(placeholder_rows)} early season placeholder rows")
            
        except Exception as e:
            logger.error(f"Error creating placeholder rows: {e}")
            raise

    # ============================================================
    # Completeness Checking Methods (Week 2 - Phase 4)
    # ============================================================

    def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
        """
        Check if circuit breaker is active for entity.

        Returns dict with:
            - active: bool (True if circuit breaker active)
            - attempts: int (number of attempts so far)
            - until: datetime (when circuit breaker expires)
        """
        query = f"""
        SELECT
            attempt_number,
            attempted_at,
            circuit_breaker_tripped,
            circuit_breaker_until
        FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = '{self.table_name}'
          AND entity_id = '{entity_id}'
          AND analysis_date = DATE('{analysis_date}')
        ORDER BY attempt_number DESC
        LIMIT 1
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=60))

            if not result:
                return {'active': False, 'attempts': 0, 'until': None}

            row = result[0]

            if row.circuit_breaker_tripped:
                # Check if 7 days have passed
                if row.circuit_breaker_until and datetime.now(timezone.utc) < row.circuit_breaker_until:
                    return {
                        'active': True,
                        'attempts': row.attempt_number,
                        'until': row.circuit_breaker_until
                    }

            return {
                'active': False,
                'attempts': row.attempt_number,
                'until': None
            }

        except Exception as e:
            logger.warning(f"Error checking circuit breaker for {entity_id}: {e}")
            return {'active': False, 'attempts': 0, 'until': None}

    def _increment_reprocess_count(self, entity_id: str, analysis_date: date, completeness_pct: float, skip_reason: str) -> None:
        """
        Track reprocessing attempt and trip circuit breaker if needed.

        Circuit breaker trips on 3rd attempt.
        """
        circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
        next_attempt = circuit_status['attempts'] + 1

        # Trip circuit breaker on 3rd attempt
        circuit_breaker_tripped = next_attempt >= 3
        circuit_breaker_until = None

        if circuit_breaker_tripped:
            # Use config for lockout duration (default: 24 hours, was 7 days)
            from shared.config.orchestration_config import get_orchestration_config
            config = get_orchestration_config()
            circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=config.circuit_breaker.entity_lockout_hours)
            logger.error(
                f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts "
                f"(lockout: {config.circuit_breaker.entity_lockout_hours}h). "
                f"Next retry allowed: {circuit_breaker_until}"
            )

        # Record attempt
        insert_query = f"""
        INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
        (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
         completeness_pct, skip_reason, circuit_breaker_tripped, circuit_breaker_until,
         manual_override_applied, notes)
        VALUES (
            '{self.table_name}',
            '{entity_id}',
            DATE('{analysis_date}'),
            {next_attempt},
            CURRENT_TIMESTAMP(),
            {completeness_pct},
            '{skip_reason}',
            {circuit_breaker_tripped},
            {'TIMESTAMP("' + circuit_breaker_until.isoformat() + '")' if circuit_breaker_until else 'NULL'},
            FALSE,
            'Attempt {next_attempt}: {completeness_pct:.1f}% complete'
        )
        """

        try:
            self.bq_client.query(insert_query).result(timeout=60)
            logger.debug(f"{entity_id}: Recorded reprocess attempt {next_attempt}")
        except Exception as e:
            logger.warning(f"Failed to record reprocess attempt for {entity_id}: {e}")

    def calculate_precompute(self) -> None:
        """
        Calculate shot zone metrics for each player.
        
        For each player with sufficient games:
        - Calculate shot distribution rates by zone
        - Calculate efficiency by zone (FG%)
        - Calculate volume per game
        - Calculate assisted vs unassisted rates
        - Determine primary scoring zone
        - Assess sample quality
        """
        if self.raw_data is None or self.raw_data.empty:
            logger.warning("No raw data to process")
            return
        
        logger.info("Calculating shot zone metrics for all players")

        successful = []
        failed = []

        # Get all unique players
        all_players = self.raw_data['player_lookup'].unique()
        analysis_date = self.opts['analysis_date']

        # ============================================================
        # NEW (Week 2): Batch completeness checking
        # ============================================================
        # Check if all players have complete historical data (L10 games)
        # OPTIMIZATION (Session 64): Skip slow completeness check in backfill mode
        # Backfill already has preflight checks at date-level; player-level is redundant
        if self.is_backfill_mode:
            logger.info(f"⏭️ BACKFILL MODE: Skipping completeness check for {len(all_players)} players")
            # Use actual game counts from already-loaded raw_data
            # In backfill mode, we trust upstream is complete, so expected = actual
            # This makes failure classification accurate without additional BQ queries
            games_per_player = self.raw_data.groupby('player_lookup').size().to_dict()
            completeness_results = {
                player: {
                    'is_production_ready': True,
                    'completeness_pct': 100.0,
                    'expected_count': games_per_player.get(player, 0),  # Actual games = expected in backfill
                    'actual_count': games_per_player.get(player, 0),
                    'missing_count': 0,
                    'is_complete': True
                }
                for player in all_players
            }
            is_bootstrap = False
            is_season_boundary = False
        else:
            logger.info(f"Checking completeness for {len(all_players)} players...")
            completeness_results = self.completeness_checker.check_completeness_batch(
                entity_ids=list(all_players),
                entity_type='player',
                analysis_date=analysis_date,
                upstream_table='nba_analytics.player_game_summary',
                upstream_entity_field='player_lookup',
                lookback_window=self.min_games_required,
                window_type='games',
                season_start_date=self.season_start_date
            )

            # Check bootstrap mode
            is_bootstrap = self.completeness_checker.is_bootstrap_mode(
                analysis_date, self.season_start_date
            )
            is_season_boundary = self.completeness_checker.is_season_boundary(analysis_date)

            logger.info(
                f"Completeness check complete. Bootstrap mode: {is_bootstrap}, "
                f"Season boundary: {is_season_boundary}"
            )
        # ============================================================

        # ============================================================
        # PARALLELIZATION: Choose between parallel and serial processing
        # ============================================================
        ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'

        if ENABLE_PARALLELIZATION:
            successful, failed = self._process_players_parallel(
                all_players, completeness_results, is_bootstrap, is_season_boundary, analysis_date
            )
        else:
            successful, failed = self._process_players_serial(
                all_players, completeness_results, is_bootstrap, is_season_boundary, analysis_date
            )

        self.transformed_data = successful
        self.failed_entities = failed

        # Count failures by category for clear visibility
        category_counts = {}
        for f in failed:
            cat = f.get('category', 'UNKNOWN')
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Log clear breakdown - distinguish expected skips from errors
        logger.info(f"Calculated metrics for {len(successful)} players, "
                   f"{len(failed)} failures")

        if failed:
            # Show breakdown with clear labeling of what needs investigation
            expected_skips = (
                category_counts.get('EXPECTED_INCOMPLETE', 0) +
                category_counts.get('INCOMPLETE_DATA', 0) +
                category_counts.get('INSUFFICIENT_DATA', 0)  # Legacy category, being phased out
            )
            needs_backfill = category_counts.get('INCOMPLETE_UPSTREAM', 0)
            errors_to_investigate = category_counts.get('PROCESSING_ERROR', 0) + category_counts.get('UNKNOWN', 0)

            logger.info(f"📊 Failure breakdown by category:")
            for cat, count in sorted(category_counts.items()):
                if cat == 'EXPECTED_INCOMPLETE':
                    logger.info(f"   {cat}: {count} (expected - season bootstrap)")
                elif cat == 'INCOMPLETE_UPSTREAM':
                    logger.warning(f"   {cat}: {count} (needs upstream backfill)")
                elif cat in ('INCOMPLETE_DATA', 'INSUFFICIENT_DATA', 'CIRCUIT_BREAKER_ACTIVE'):
                    logger.info(f"   {cat}: {count} (expected - data quality)")
                else:
                    logger.warning(f"   {cat}: {count} ⚠️ INVESTIGATE")

            if errors_to_investigate == 0 and needs_backfill == 0:
                logger.info(f"✅ No errors to investigate - all {expected_skips} skips are expected (data quality)")
            elif errors_to_investigate == 0:
                logger.info(f"✅ No errors to investigate - {expected_skips} expected skips, {needs_backfill} need backfill")

        # Store category breakdown in stats for backfill summary
        self.stats['failure_categories'] = category_counts
        self.stats['errors_to_investigate'] = category_counts.get('PROCESSING_ERROR', 0) + category_counts.get('UNKNOWN', 0)

    def _process_players_parallel(self, all_players, completeness_results,
                                   is_bootstrap, is_season_boundary, analysis_date):
        """Process all players using ProcessPoolExecutor for 4-5x speedup."""
        # Determine worker count - ProcessPool can handle more than ThreadPool
        DEFAULT_WORKERS = min(32, os.cpu_count() or 10)
        max_workers = int(os.environ.get(
            'PSZA_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))

        if self.is_backfill_mode:
            max_workers = min(max_workers, 32)
        else:
            max_workers = min(max_workers, os.cpu_count() or 10)

        logger.info(f"Processing {len(all_players)} players with {max_workers} workers (ProcessPool mode)")

        # ============================================================
        # PRE-FETCH CIRCUIT BREAKER DATA (BQ client not picklable)
        # ============================================================
        circuit_breaker_statuses = {}

        # Skip circuit breaker checks in backfill mode (historical data doesn't need this)
        if self.is_backfill_mode or is_bootstrap or is_season_boundary:
            logger.info(f"⏭️  Skipping circuit breaker checks (backfill/bootstrap mode)")
            for player_lookup in all_players:
                circuit_breaker_statuses[player_lookup] = {
                    'active': False, 'attempts': 0, 'until': None
                }
        else:
            logger.info(f"Pre-fetching circuit breaker statuses for {len(all_players)} players...")
            for player_lookup in all_players:
                circuit_breaker_statuses[player_lookup] = self._check_circuit_breaker(
                    player_lookup, analysis_date
                )
            logger.info(f"Circuit breaker pre-fetch complete")

        # Performance timing
        loop_start = time.time()
        processed_count = 0

        successful = []
        failed = []
        reprocess_increments = []  # Track BQ writes needed

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all player tasks
            futures = {
                executor.submit(
                    _process_single_player_worker,
                    player_lookup,
                    completeness_results.get(player_lookup, {
                        'expected_count': 0,
                        'actual_count': 0,
                        'completeness_pct': 0.0,
                        'missing_count': 0,
                        'is_complete': False,
                        'is_production_ready': False
                    }),
                    circuit_breaker_statuses[player_lookup],
                    is_bootstrap,
                    is_season_boundary,
                    analysis_date,
                    self.raw_data[self.raw_data['player_lookup'] == player_lookup].to_dict('records'),
                    self.sample_window,
                    self.trend_window,
                    self.min_games_required,
                    self.source_hash,
                    self.opts,
                    self.HASH_FIELDS
                ): player_lookup
                for player_lookup in all_players
            }

            # Collect results
            for future in as_completed(futures):
                player_lookup = futures[future]
                processed_count += 1

                try:
                    success, data, needs_reprocess_increment = future.result()
                    if success:
                        successful.append(data)
                    else:
                        failed.append(data)

                    if needs_reprocess_increment:
                        reprocess_increments.append(data)

                    # Progress logging every 50 players
                    if processed_count % 50 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed
                        remaining = len(all_players) - processed_count
                        eta = remaining / rate if rate > 0 else 0
                        logger.info(
                            f"Player processing progress: {processed_count}/{len(all_players)} "
                            f"| Rate: {rate:.1f} players/sec | ETA: {eta/60:.1f}min"
                        )
                except Exception as e:
                    logger.error(f"Error processing {player_lookup}: {e}")
                    failed.append({
                        'entity_id': player_lookup,
                        'reason': str(e),
                        'category': 'PROCESSING_ERROR',
                        'can_retry': False
                    })

        # ============================================================
        # POST-PROCESSING: BQ writes in main thread
        # ============================================================
        if reprocess_increments:
            logger.info(f"Incrementing reprocess count for {len(reprocess_increments)} players...")
            for failure_data in reprocess_increments:
                entity_id = failure_data['entity_id']
                reason = failure_data['reason']
                if 'Incomplete data:' in reason:
                    completeness_str = reason.split('Incomplete data:')[1].split('%')[0].strip()
                    try:
                        completeness_pct = float(completeness_str)
                    except ValueError:
                        completeness_pct = 0.0
                else:
                    completeness_pct = 0.0

                self._increment_reprocess_count(
                    entity_id, analysis_date, completeness_pct, 'incomplete_upstream_data'
                )

        # Final timing
        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(successful)} players in {total_time:.1f}s "
            f"(avg {total_time/len(successful) if successful else 0:.2f}s/player) "
            f"| {len(failed)} failed"
        )

        return successful, failed

    def _process_single_player(self, player_lookup, completeness_results,
                                is_bootstrap, is_season_boundary, analysis_date):
        """Process one player (thread-safe). Returns (success: bool, data: dict)."""
        try:
            # Get completeness for this player
            completeness = completeness_results.get(player_lookup, {
                'expected_count': 0,
                'actual_count': 0,
                'completeness_pct': 0.0,
                'missing_count': 0,
                'is_complete': False,
                'is_production_ready': False
            })

            # Check circuit breaker (skip in bootstrap/season boundary mode for speed)
            if not is_bootstrap and not is_season_boundary:
                circuit_breaker_status = self._check_circuit_breaker(player_lookup, analysis_date)
            else:
                circuit_breaker_status = {'active': False, 'attempts': 0, 'until': None}

            if circuit_breaker_status['active']:
                return (False, {
                    'entity_id': player_lookup,
                    'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                    'category': 'CIRCUIT_BREAKER_ACTIVE',
                    'can_retry': False
                })

            # Check production readiness
            if not completeness['is_production_ready'] and not is_bootstrap and not is_season_boundary:
                # Track reprocessing attempt
                self._increment_reprocess_count(
                    player_lookup, analysis_date,
                    completeness['completeness_pct'],
                    'incomplete_upstream_data'
                )

                return (False, {
                    'entity_id': player_lookup,
                    'reason': (
                        f"Incomplete data: {completeness['completeness_pct']}% "
                        f"({completeness['actual_count']}/{completeness['expected_count']} games)"
                    ),
                    'category': 'INCOMPLETE_DATA',
                    'can_retry': True
                })

            # Filter data for this player
            player_data = self.raw_data[
                self.raw_data['player_lookup'] == player_lookup
            ].copy()

            # Separate 10-game and 20-game samples
            games_10 = player_data[player_data['game_rank'] <= self.sample_window]
            games_20 = player_data[player_data['game_rank'] <= self.trend_window]

            # Check sufficient games for 10-game analysis
            if len(games_10) < self.min_games_required:
                # Determine failure category based on expected vs actual game counts
                actual_games = len(games_10)
                expected_games = completeness.get('expected_count', 0)

                # Classification logic:
                # - EXPECTED_INCOMPLETE: Both actual and expected < 10 (early season/bootstrap)
                # - INCOMPLETE_UPSTREAM: Actual < 10 but expected >= 10 (missing upstream data)
                if actual_games < self.min_games_required and expected_games < self.min_games_required:
                    # Early season - not enough games played yet
                    category = 'EXPECTED_INCOMPLETE'
                    can_retry = False
                    reason = (
                        f"Season bootstrap: {actual_games}/{expected_games} games "
                        f"(need {self.min_games_required})"
                    )
                    logger.debug(f"{player_lookup}: {reason}")
                else:
                    # Missing upstream data - games were played but not in our data
                    category = 'INCOMPLETE_UPSTREAM'
                    can_retry = True
                    reason = (
                        f"Missing upstream data: {actual_games}/{expected_games} games "
                        f"(need {self.min_games_required})"
                    )
                    logger.warning(f"{player_lookup}: {reason}")

                return (False, {
                    'entity_id': player_lookup,
                    'reason': reason,
                    'category': category,
                    'can_retry': can_retry
                })

            # Calculate metrics for 10-game window
            metrics_10 = self._calculate_zone_metrics(games_10)

            # Calculate metrics for 20-game window (for trends)
            metrics_20 = self._calculate_zone_metrics(games_20) if len(games_20) >= 15 else {}

            # Determine primary scoring zone
            primary_zone = self._determine_primary_zone(metrics_10)

            # Assess data quality
            quality_tier = self._determine_quality_tier(len(games_10))
            sample_quality_10 = self._determine_sample_quality(len(games_10), self.sample_window)
            sample_quality_20 = self._determine_sample_quality(len(games_20), self.trend_window)

            # Build output record
            record = {
                # Identifiers
                'player_lookup': player_lookup,
                'universal_player_id': player_data.iloc[0].get('universal_player_id'),
                'analysis_date': self.opts['analysis_date'].isoformat(),

                # Shot distribution - Last 10 games
                'paint_rate_last_10': metrics_10.get('paint_rate'),
                'mid_range_rate_last_10': metrics_10.get('mid_range_rate'),
                'three_pt_rate_last_10': metrics_10.get('three_pt_rate'),
                'total_shots_last_10': metrics_10.get('total_shots'),
                'games_in_sample_10': int(len(games_10)),
                'sample_quality_10': sample_quality_10,

                # Efficiency - Last 10 games
                'paint_pct_last_10': metrics_10.get('paint_pct'),
                'mid_range_pct_last_10': metrics_10.get('mid_range_pct'),
                'three_pt_pct_last_10': metrics_10.get('three_pt_pct'),

                # Volume - Last 10 games
                'paint_attempts_per_game': metrics_10.get('paint_attempts_pg'),
                'mid_range_attempts_per_game': metrics_10.get('mid_range_attempts_pg'),
                'three_pt_attempts_per_game': metrics_10.get('three_pt_attempts_pg'),

                # Trend comparison - Last 20 games
                'paint_rate_last_20': metrics_20.get('paint_rate'),
                'paint_pct_last_20': metrics_20.get('paint_pct'),
                'games_in_sample_20': int(len(games_20)),
                'sample_quality_20': sample_quality_20,

                # Shot creation
                'assisted_rate_last_10': metrics_10.get('assisted_rate'),
                'unassisted_rate_last_10': metrics_10.get('unassisted_rate'),

                # Player characteristics
                'player_position': None,
                'primary_scoring_zone': primary_zone,

                # Data quality
                'data_quality_tier': quality_tier,
                'calculation_notes': None,

                # v4.0 source tracking
                **self.build_source_tracking_fields(),

                # Early season
                'early_season_flag': False,
                'insufficient_data_reason': None,

                # Completeness metadata
                'expected_games_count': completeness['expected_count'],
                'actual_games_count': completeness['actual_count'],
                'completeness_percentage': completeness['completeness_pct'],
                'missing_games_count': completeness['missing_count'],
                'is_production_ready': completeness['is_production_ready'],
                'data_quality_issues': [],
                'last_reprocess_attempt_at': None,
                'reprocess_attempt_count': circuit_breaker_status['attempts'],
                'circuit_breaker_active': circuit_breaker_status['active'],
                'circuit_breaker_until': (
                    circuit_breaker_status['until'].isoformat()
                    if circuit_breaker_status['until'] else None
                ),
                'manual_override_required': False,
                'season_boundary_detected': is_season_boundary,
                'backfill_bootstrap_mode': is_bootstrap,
                'processing_decision_reason': 'processed_successfully',

                # Processing metadata
                'created_at': datetime.now(timezone.utc).isoformat(),
                'processed_at': datetime.now(timezone.utc).isoformat()
            }

            # Add source hash
            record['source_player_game_hash'] = self.source_hash

            # Compute and add data hash
            record['data_hash'] = self.compute_data_hash(record)

            return (True, record)

        except Exception as e:
            return (False, {
                'entity_id': player_lookup,
                'reason': str(e),
                'category': 'PROCESSING_ERROR',
                'can_retry': False
            })

    def _process_players_serial(self, all_players, completeness_results,
                                 is_bootstrap, is_season_boundary, analysis_date):
        """Original serial processing (kept for fallback)."""
        logger.info(f"Processing {len(all_players)} players (serial mode)")

        successful = []
        failed = []

        for player_lookup in all_players:
            try:
                # Get completeness for this player
                completeness = completeness_results.get(player_lookup, {
                    'expected_count': 0,
                    'actual_count': 0,
                    'completeness_pct': 0.0,
                    'missing_count': 0,
                    'is_complete': False,
                    'is_production_ready': False
                })

                # Check circuit breaker (skip in bootstrap/season boundary mode for speed)
                if not is_bootstrap and not is_season_boundary:
                    circuit_breaker_status = self._check_circuit_breaker(player_lookup, analysis_date)
                else:
                    circuit_breaker_status = {'active': False, 'attempts': 0, 'until': None}

                if circuit_breaker_status['active']:
                    logger.warning(
                        f"{player_lookup}: Circuit breaker active until "
                        f"{circuit_breaker_status['until']} - skipping"
                    )
                    failed.append({
                        'entity_id': player_lookup,
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE',
                        'can_retry': False
                    })
                    continue

                # Check production readiness
                if not completeness['is_production_ready'] and not is_bootstrap and not is_season_boundary:
                    logger.warning(
                        f"{player_lookup}: Completeness {completeness['completeness_pct']}% "
                        f"({completeness['actual_count']}/{completeness['expected_count']} games) "
                        f"- below 90% threshold, skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_upstream_data'
                    )

                    failed.append({
                        'entity_id': player_lookup,
                        'reason': (
                            f"Incomplete data: {completeness['completeness_pct']}% "
                            f"({completeness['actual_count']}/{completeness['expected_count']} games)"
                        ),
                        'category': 'INCOMPLETE_DATA',
                        'can_retry': True
                    })
                    continue

                # Filter data for this player
                player_data = self.raw_data[
                    self.raw_data['player_lookup'] == player_lookup
                ].copy()

                # Separate 10-game and 20-game samples
                games_10 = player_data[player_data['game_rank'] <= self.sample_window]
                games_20 = player_data[player_data['game_rank'] <= self.trend_window]

                # Check sufficient games for 10-game analysis
                if len(games_10) < self.min_games_required:
                    # Determine failure category based on expected vs actual game counts
                    actual_games = len(games_10)
                    expected_games = completeness.get('expected_count', 0)

                    # Classification logic:
                    # - EXPECTED_INCOMPLETE: Both actual and expected < 10 (early season/bootstrap)
                    # - INCOMPLETE_UPSTREAM: Actual < 10 but expected >= 10 (missing upstream data)
                    if actual_games < self.min_games_required and expected_games < self.min_games_required:
                        # Early season - not enough games played yet
                        category = 'EXPECTED_INCOMPLETE'
                        can_retry = False
                        reason = (
                            f"Season bootstrap: {actual_games}/{expected_games} games "
                            f"(need {self.min_games_required})"
                        )
                        logger.debug(f"{player_lookup}: {reason}")
                    else:
                        # Missing upstream data - games were played but not in our data
                        category = 'INCOMPLETE_UPSTREAM'
                        can_retry = True
                        reason = (
                            f"Missing upstream data: {actual_games}/{expected_games} games "
                            f"(need {self.min_games_required})"
                        )
                        logger.warning(f"{player_lookup}: {reason}")

                    failed.append({
                        'entity_id': player_lookup,
                        'reason': reason,
                        'category': category,
                        'can_retry': can_retry
                    })
                    continue

                # Calculate metrics for 10-game window
                metrics_10 = self._calculate_zone_metrics(games_10)

                # Calculate metrics for 20-game window (for trends)
                metrics_20 = self._calculate_zone_metrics(games_20) if len(games_20) >= 15 else {}

                # Determine primary scoring zone
                primary_zone = self._determine_primary_zone(metrics_10)

                # Assess data quality
                quality_tier = self._determine_quality_tier(len(games_10))
                sample_quality_10 = self._determine_sample_quality(len(games_10), self.sample_window)
                sample_quality_20 = self._determine_sample_quality(len(games_20), self.trend_window)

                # Build output record
                record = {
                    # Identifiers
                    'player_lookup': player_lookup,
                    'universal_player_id': player_data.iloc[0].get('universal_player_id'),
                    'analysis_date': self.opts['analysis_date'].isoformat(),

                    # Shot distribution - Last 10 games
                    'paint_rate_last_10': metrics_10.get('paint_rate'),
                    'mid_range_rate_last_10': metrics_10.get('mid_range_rate'),
                    'three_pt_rate_last_10': metrics_10.get('three_pt_rate'),
                    'total_shots_last_10': metrics_10.get('total_shots'),
                    'games_in_sample_10': int(len(games_10)),
                    'sample_quality_10': sample_quality_10,

                    # Efficiency - Last 10 games
                    'paint_pct_last_10': metrics_10.get('paint_pct'),
                    'mid_range_pct_last_10': metrics_10.get('mid_range_pct'),
                    'three_pt_pct_last_10': metrics_10.get('three_pt_pct'),

                    # Volume - Last 10 games
                    'paint_attempts_per_game': metrics_10.get('paint_attempts_pg'),
                    'mid_range_attempts_per_game': metrics_10.get('mid_range_attempts_pg'),
                    'three_pt_attempts_per_game': metrics_10.get('three_pt_attempts_pg'),

                    # Trend comparison - Last 20 games
                    'paint_rate_last_20': metrics_20.get('paint_rate'),
                    'paint_pct_last_20': metrics_20.get('paint_pct'),
                    'games_in_sample_20': int(len(games_20)),
                    'sample_quality_20': sample_quality_20,

                    # Shot creation
                    'assisted_rate_last_10': metrics_10.get('assisted_rate'),
                    'unassisted_rate_last_10': metrics_10.get('unassisted_rate'),

                    # Player characteristics
                    'player_position': None,
                    'primary_scoring_zone': primary_zone,

                    # Data quality
                    'data_quality_tier': quality_tier,
                    'calculation_notes': None,

                    # v4.0 source tracking
                    **self.build_source_tracking_fields(),

                    # Early season
                    'early_season_flag': False,
                    'insufficient_data_reason': None,

                    # Completeness metadata
                    'expected_games_count': completeness['expected_count'],
                    'actual_games_count': completeness['actual_count'],
                    'completeness_percentage': completeness['completeness_pct'],
                    'missing_games_count': completeness['missing_count'],
                    'is_production_ready': completeness['is_production_ready'],
                    'data_quality_issues': [],
                    'last_reprocess_attempt_at': None,
                    'reprocess_attempt_count': circuit_breaker_status['attempts'],
                    'circuit_breaker_active': circuit_breaker_status['active'],
                    'circuit_breaker_until': (
                        circuit_breaker_status['until'].isoformat()
                        if circuit_breaker_status['until'] else None
                    ),
                    'manual_override_required': False,
                    'season_boundary_detected': is_season_boundary,
                    'backfill_bootstrap_mode': is_bootstrap,
                    'processing_decision_reason': 'processed_successfully',

                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                # Add source hash
                record['source_player_game_hash'] = self.source_hash

                # Compute and add data hash
                record['data_hash'] = self.compute_data_hash(record)

                successful.append(record)

            except Exception as e:
                logger.error(f"Failed to process {player_lookup}: {e}")
                failed.append({
                    'entity_id': player_lookup,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })

        return successful, failed
    
    def _calculate_zone_metrics(self, games_df: pd.DataFrame) -> dict:
        """
        Calculate shot zone metrics for a sample of games.
        
        Args:
            games_df: DataFrame of games for a player
            
        Returns:
            dict: Calculated metrics
        """
        # Aggregate totals
        paint_att = games_df['paint_attempts'].sum()
        paint_makes = games_df['paint_makes'].sum()
        mid_att = games_df['mid_range_attempts'].sum()
        mid_makes = games_df['mid_range_makes'].sum()
        three_att = games_df['three_pt_attempts'].sum()
        three_makes = games_df['three_pt_makes'].sum()
        
        total_att = paint_att + mid_att + three_att
        total_makes = games_df['fg_makes'].sum()
        assisted_makes = games_df['assisted_fg_makes'].sum()
        unassisted_makes = games_df['unassisted_fg_makes'].sum()
        
        games_count = len(games_df)
        
        # Calculate rates (distribution)
        paint_rate = (paint_att / total_att * 100) if total_att > 0 else None
        mid_rate = (mid_att / total_att * 100) if total_att > 0 else None
        three_rate = (three_att / total_att * 100) if total_att > 0 else None
        
        # Calculate efficiency (FG%)
        paint_pct = (paint_makes / paint_att) if paint_att > 0 else None
        mid_pct = (mid_makes / mid_att) if mid_att > 0 else None
        three_pct = (three_makes / three_att) if three_att > 0 else None
        
        # Calculate volume per game
        paint_pg = paint_att / games_count if games_count > 0 else None
        mid_pg = mid_att / games_count if games_count > 0 else None
        three_pg = three_att / games_count if games_count > 0 else None
        
        # Calculate assisted rates
        # FIX (Session 64): Check total_att > 0 for consistency with zone rates
        # When total_att = 0, assisted/unassisted rates should also be None
        assisted_rate = (assisted_makes / total_makes * 100) if total_att > 0 and total_makes > 0 else None
        unassisted_rate = (unassisted_makes / total_makes * 100) if total_att > 0 and total_makes > 0 else None
        
        return {
            'paint_rate': round(paint_rate, 2) if paint_rate is not None else None,
            'mid_range_rate': round(mid_rate, 2) if mid_rate is not None else None,
            'three_pt_rate': round(three_rate, 2) if three_rate is not None else None,
            'paint_pct': round(paint_pct, 3) if paint_pct is not None else None,
            'mid_range_pct': round(mid_pct, 3) if mid_pct is not None else None,
            'three_pt_pct': round(three_pct, 3) if three_pct is not None else None,
            'paint_attempts_pg': round(paint_pg, 1) if paint_pg is not None else None,
            'mid_range_attempts_pg': round(mid_pg, 1) if mid_pg is not None else None,
            'three_pt_attempts_pg': round(three_pg, 1) if three_pg is not None else None,
            'assisted_rate': round(assisted_rate, 2) if assisted_rate is not None else None,
            'unassisted_rate': round(unassisted_rate, 2) if unassisted_rate is not None else None,
            'total_shots': int(total_att) if total_att > 0 else None
        }
    
    def _determine_primary_zone(self, metrics: dict) -> Optional[str]:
        """
        Determine player's primary scoring zone based on shot distribution.
        """
        paint_rate = metrics.get('paint_rate', 0) or 0
        mid_rate = metrics.get('mid_range_rate', 0) or 0
        three_rate = metrics.get('three_pt_rate', 0) or 0
        
        # If missing data, return None
        if paint_rate == 0 and mid_rate == 0 and three_rate == 0:
            return None
        
        # Check for clear dominance first
        if paint_rate >= 40:
            return 'paint'
        elif three_rate >= 40:
            return 'perimeter'
        elif mid_rate >= 35:  # Raised threshold so 33.3% doesn't trigger
            return 'mid_range'
        else:
            return 'balanced'
    
    def _determine_quality_tier(self, games_count: int) -> str:
        """
        Assess data quality based on sample size.
        
        Args:
            games_count: Number of games in sample
            
        Returns:
            str: 'high', 'medium', or 'low'
        """
        if games_count >= self.min_games_required:
            return 'high'
        elif games_count >= 7:
            return 'medium'
        else:
            return 'low'
    
    def _determine_sample_quality(self, games_count: int, target_window: int) -> str:
        """
        Assess sample quality relative to target window.
        
        Args:
            games_count: Number of games in sample
            target_window: Target number of games (10 or 20)
            
        Returns:
            str: 'excellent', 'good', 'limited', or 'insufficient'
        """
        if games_count >= target_window:
            return 'excellent'
        elif games_count >= int(target_window * 0.7):
            return 'good'
        elif games_count >= int(target_window * 0.5):
            return 'limited'
        else:
            return 'insufficient'
    
    def save_precompute(self) -> bool:
        """
        Save calculated metrics to BigQuery using parent class implementation.
        
        Parent class handles:
        - MERGE_UPDATE strategy (delete + insert)
        - Batch INSERT via BigQuery load jobs
        - Streaming buffer error handling
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.transformed_data:
            logger.warning("No data to save")
            return True
        
        logger.info(f"Saving {len(self.transformed_data)} records")
        
        try:
            # Use parent class save implementation
            super().save_precompute()
            
            # Save failure records if any
            if self.failed_entities:
                self._save_failures()
            
            logger.info(f"Successfully saved {len(self.transformed_data)} records")
            return True
            
        except Exception as e:
            logger.error(f"Error saving to BigQuery: {e}")
            return False
    
    def _save_failures(self) -> None:
        """Save failed entity records for debugging."""
        if not self.failed_entities:
            return

        try:
            table_id = f"{self.project_id}.nba_processing.precompute_failures"

            failure_records = []
            for failure in self.failed_entities:
                failure_records.append({
                    'processor_name': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': self.opts['analysis_date'].isoformat(),
                    'entity_id': failure['entity_id'],
                    'failure_category': failure['category'],
                    'failure_reason': failure['reason'],
                    'can_retry': failure['can_retry'],
                    'created_at': datetime.now(timezone.utc).isoformat()
                })

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Configure load job with schema enforcement
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            # Load data using batch load job
            load_job = self.bq_client.load_table_from_json(
                failure_records, table_id, job_config=job_config
            )
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

            logger.info(f"Saved {len(failure_records)} failure records")

        except Exception as e:
            logger.warning(f"Failed to save failure records: {e}")


# CLI entry point for testing
if __name__ == '__main__':
    import sys
    from datetime import date
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        analysis_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    else:
        analysis_date = date.today()
    
    logger.info(f"Running Player Shot Zone Analysis for {analysis_date}")
    
    # Initialize and run processor
    processor = PlayerShotZoneAnalysisProcessor()
    processor.opts = {'analysis_date': analysis_date}
    
    try:
        # Extract data
        processor.extract_raw_data()
        
        # Calculate metrics
        processor.calculate_precompute()
        
        # Save results
        if processor.save_precompute():
            logger.info("✓ Processing complete!")
        else:
            logger.error("✗ Processing failed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"✗ Processing error: {e}")
        sys.exit(1)