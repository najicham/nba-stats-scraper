#!/usr/bin/env python3
"""
Path: data_processors/precompute/player_daily_cache/player_daily_cache_processor.py

Player Daily Cache Processor

Purpose:
    Cache static daily player data that won't change during the day.
    Eliminates repeated BigQuery queries during Phase 5 real-time updates.
    
Input Sources:
    - nba_analytics.player_game_summary (recent performance)
    - nba_analytics.team_offense_game_summary (team context)
    - nba_analytics.upcoming_player_game_context (fatigue metrics)
    - nba_precompute.player_shot_zone_analysis (shot tendencies)
    
Output:
    - nba_precompute.player_daily_cache
    
Schedule:
    - Nightly at 12:00 AM (after all Phase 4 processors complete)
    - Processes ~450 active players in 5-10 minutes
    
Performance Impact:
    - Cost savings: 79% reduction vs repeated queries
    - Speed: 2000x faster lookups (cache vs BigQuery)
    - Phase 5 loads cache once at 6 AM and reuses all day

Version: 1.0
Date: October 30, 2025
"""

import logging
import os
import time
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
from google.cloud import bigquery

from data_processors.precompute.base import PrecomputeProcessorBase
from data_processors.precompute.mixins.backfill_mode_mixin import BackfillModeMixin

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin
from shared.config.source_coverage import get_tier_from_score

# Smart Idempotency (Pattern #1)
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Completeness checking (Week 3 - Phase 4 Historical Dependency Checking - Multi-Window)
from shared.utils.completeness_checker import CompletenessChecker

# Bootstrap period support (Week 5 - Early Season Handling)
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.validation.config import BOOTSTRAP_DAYS

# Module components (extracted for better organization)
from .worker import _process_single_player_worker
from .aggregators import StatsAggregator, TeamAggregator, ContextAggregator, ShotZoneAggregator
from .builders import CacheBuilder, MultiWindowCompletenessChecker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PlayerDailyCacheProcessor(
    SmartIdempotencyMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase  # Already includes BackfillModeMixin
):
    """
    Cache static daily player data for fast Phase 5 real-time updates.

    This processor aggregates player performance, team context, fatigue metrics,
    and shot zone tendencies into a single cache table. Phase 5 loads this cache
    once at 6 AM and reuses it for all real-time predictions during the day.

    Dependencies:
        - nba_analytics.player_game_summary (CRITICAL)
        - nba_analytics.team_offense_game_summary (CRITICAL)
        - nba_analytics.upcoming_player_game_context (CRITICAL)
        - nba_precompute.player_shot_zone_analysis (CRITICAL)

    Processing Strategy:
        - MERGE: Update existing rows or insert new ones
        - One row per player per cache_date
        - Handles early season (< 10 games) with partial data
        - Minimum 5 games required to write cache record
    """

    # Smart Idempotency: Fields to hash (meaningful business fields only)
    HASH_FIELDS = [
        'player_lookup', 'universal_player_id', 'cache_date',
        'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
        'points_std_last_10', 'minutes_avg_last_10', 'usage_rate_last_10',
        'ts_pct_last_10', 'games_played_season',
        'team_pace_last_10', 'team_off_rating_last_10', 'player_usage_rate_season',
        'games_in_last_7_days', 'games_in_last_14_days',
        'minutes_in_last_7_days', 'minutes_in_last_14_days',
        'back_to_backs_last_14_days', 'avg_minutes_per_game_last_7',
        'fourth_quarter_minutes_last_7',
        'primary_scoring_zone', 'paint_rate_last_10', 'three_pt_rate_last_10',
        'assisted_rate_last_10', 'player_age', 'cache_quality_score',
        'cache_version'
    ]

    # Override date column from base class (player_daily_cache uses cache_date, not analysis_date)
    date_column: str = "cache_date"

    # Defensive check configuration (upstream Phase 3 dependency)
    upstream_processor_name = 'PlayerGameSummaryProcessor'
    upstream_table = 'nba_analytics.player_game_summary'
    lookback_days = 10  # Must match data requirements

    # ============================================================
    # SOFT DEPENDENCY CONFIGURATION (added Session 10)
    # ============================================================
    # When enabled, processor can proceed with degraded upstream data if coverage > threshold
    # This prevents all-or-nothing blocking when upstream processors have partial failures
    use_soft_dependencies = True
    soft_dependency_threshold = 0.80  # Proceed if >80% upstream coverage

    # Primary key fields for duplicate detection and MERGE operations
    PRIMARY_KEY_FIELDS = ['cache_date', 'player_lookup']

    def __init__(self):
        """Initialize the player daily cache processor."""
        super().__init__()
        
        # Table configuration
        self.table_name = 'player_daily_cache'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'
        
        # Data requirements
        self.min_games_required = 10  # Preferred minimum
        self.absolute_min_games = 5   # Absolute minimum to write record

        # BigQuery client already initialized by PrecomputeProcessorBase with pooling
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

        # Initialize completeness checker (Week 3 - Multi-Window Completeness Checking)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)
        self.multi_window_checker = MultiWindowCompletenessChecker(self.completeness_checker)

        # Data containers
        self.player_game_data = None
        self.team_offense_data = None
        self.upcoming_context_data = None
        self.shot_zone_data = None

        # Source hash cache (4 dependencies)
        self.source_player_game_hash = None
        self.source_team_offense_hash = None
        self.source_upcoming_context_hash = None
        self.source_shot_zone_hash = None

        # Cache version
        self.cache_version = "v1"

        # Season start date (will be set in extract_raw_data)
        self.season_start_date = None

        logger.info("PlayerDailyCacheProcessor initialized")

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 3 Analytics sources - RELEVANT (depends on these)
        'player_game_summary': True,
        'team_offense_game_summary': True,
        'team_defense_game_summary': True,
        'upcoming_player_game_context': True,
        'upcoming_team_game_context': True,

        # Phase 4 Precompute sources - RELEVANT (depends on these)
        'player_shot_zone_analysis': True,
        'player_composite_factors': True,
        'team_defense_zone_analysis': True,

        # Phase 2 Raw sources - NOT RELEVANT (Phase 4 reads from Phase 3, not Phase 2 directly)
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
    ENABLE_NO_GAMES_CHECK = False      # Don't skip - builds cache regardless of games
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - can build cache for any date

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Prevents retry storms by checking Phase 3 player_game_summary data exists.

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

    def get_dependencies(self) -> dict:
        """
        Define upstream source requirements.
        
        Returns:
            dict: Dependency configuration for each source table
        """
        return {
            'nba_analytics.player_game_summary': {
                'field_prefix': 'source_player_game',
                'description': 'Player performance stats (season to date)',
                'check_type': 'lookback',
                'lookback_days': 180,  # Full season
                'expected_count_min': 1000,  # ~450 players × 5+ games
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'early_season_days': 14,
                'early_season_behavior': 'WRITE_PLACEHOLDER',
                'critical': True
            },
            'nba_analytics.team_offense_game_summary': {
                'field_prefix': 'source_team_offense',
                'description': 'Team offensive stats (last 10 games)',
                'check_type': 'lookback',
                'lookback_days': 30,
                'expected_count_min': 300,  # ~30 teams × 10 games
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': True
            },
            'nba_analytics.upcoming_player_game_context': {
                'field_prefix': 'source_upcoming_context',
                'description': 'Pre-calculated fatigue metrics and context',
                'check_type': 'date_match',
                'expected_count_min': 30,  # Lowered for early season (was 100)
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': True
            },
            'nba_precompute.player_shot_zone_analysis': {
                'field_prefix': 'source_shot_zone',
                'description': 'Shot zone tendencies (optional - proceeds with nulls if missing)',
                'check_type': 'date_match',
                'date_field': 'analysis_date',  # This table uses analysis_date, not game_date
                'expected_count_min': 30,  # Lowered for early season (was 100)
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': False  # Changed: shot zone is now optional enrichment
            }
        }

    def build_source_tracking_fields(self) -> Dict:
        """
        Build source tracking fields from tracked source attributes.

        This method collects all source tracking data (timestamps, row counts,
        completeness percentages) from processor attributes and returns them
        as a dictionary ready to be included in output records.

        Note: Returns empty dict in backfill mode since these fields don't exist
        in the BigQuery schema and would cause MERGE failures.

        Returns:
            Dict: Source tracking fields for all dependencies

        Example output:
            {
                'source_player_game_last_updated': datetime(2025, 1, 21, 2, 15),
                'source_player_game_rows_found': 450,
                'source_player_game_completeness_pct': 98.5,
                'source_team_offense_last_updated': datetime(2025, 1, 21, 2, 20),
                ...
            }
        """
        # Skip source tracking in backfill mode - fields don't exist in BigQuery schema
        if getattr(self, 'is_backfill_mode', False):
            return {}

        tracking_fields = {}
        
        # Get dependencies to know which sources to track
        deps = self.get_dependencies()
        
        for source_table, config in deps.items():
            prefix = config['field_prefix']
            
            # Build field names based on prefix
            last_updated_field = f"{prefix}_last_updated"
            rows_found_field = f"{prefix}_rows_found"
            completeness_field = f"{prefix}_completeness_pct"
            
            # Get values from processor attributes (set by track_source_usage during extract)
            tracking_fields[last_updated_field] = getattr(self, last_updated_field, None)
            tracking_fields[rows_found_field] = getattr(self, rows_found_field, None)
            tracking_fields[completeness_field] = getattr(self, completeness_field, None)
        
        return tracking_fields
    
    def extract_raw_data(self) -> None:
        """
        Extract data from all upstream sources with dependency checking.

        Bootstrap Period Handling:
            Skips processing for first 7 days of season (days 0-6).
            Uses schedule service to determine season start date.

        Queries:
            1. player_game_summary: Season games for all active players
            2. team_offense_game_summary: Last 10 games per team
            3. upcoming_player_game_context: Today's context (fatigue, age)
            4. player_shot_zone_analysis: Today's shot zone analysis

        Raises:
            DependencyError: If critical dependencies missing
            DataTooStaleError: If critical data too old
        """
        analysis_date = self.opts['analysis_date']
        season_year = self.opts.get('season_year')

        # Determine season year if not provided
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
            # This signals to base class to skip transform/load phases
            self.raw_data = None
            return

        # Store season start date for completeness checking (Week 3)
        self.season_start_date = date(season_year, 10, 1)

        logger.info(f"Extracting data for cache_date: {analysis_date}")

        # Use cached dependency check from precompute_base.run()
        # (already checked and validated, track_source_usage already called)
        dep_check = self.dep_check

        # Handle early season
        if dep_check and dep_check.get('is_early_season'):
            logger.warning("Early season detected - will write partial cache records")
            self.early_season_flag = True
            self.insufficient_data_reason = "Season just started, using available games"

        # Note: critical dependency and stale checks already done in precompute_base.run()
        
        # Extract from each source
        logger.info("Extracting player game summary data...")
        self._extract_player_game_data(analysis_date, season_year)
        
        logger.info("Extracting team offense data...")
        self._extract_team_offense_data(analysis_date)
        
        logger.info("Extracting upcoming player context data...")
        self._extract_upcoming_context_data(analysis_date)
        
        logger.info("Extracting shot zone analysis data...")
        self._extract_shot_zone_data(analysis_date)

        logger.info(f"Extraction complete: {len(self.upcoming_context_data)} players to process")

        # Extract source hashes from all 4 dependencies (Smart Reprocessing - Pattern #3)
        self._extract_source_hashes(analysis_date)
    
    def _extract_player_game_data(self, analysis_date: date, season_year: int) -> None:
        """Extract player game summary data (season to date)."""
        
        query = f"""
        WITH ranked_games AS (
            SELECT
                player_lookup,
                universal_player_id,
                game_date,
                team_abbr,
                points,
                minutes_played,
                usage_rate,
                ts_pct,
                fg_makes,
                assisted_fg_makes,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date < '{analysis_date.isoformat()}'  -- FIX: Changed <= to < (cache should only include games BEFORE analysis_date)
              AND season_year = {season_year}
              AND is_active = TRUE
              AND (minutes_played > 0 OR points > 0)  -- Fallback for historical data with NULL minutes
        )
        SELECT *
        FROM ranked_games
        WHERE game_rank <= 82  -- Full season
        ORDER BY player_lookup, game_date DESC
        """
        
        self.player_game_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.player_game_data)} player game records")
    
    def _extract_team_offense_data(self, analysis_date: date) -> None:
        """Extract team offense data (last 10 games per team)."""

        query = f"""
        WITH ranked_games AS (
            SELECT
                team_abbr,
                game_date,
                pace,
                offensive_rating,
                ROW_NUMBER() OVER (
                    PARTITION BY team_abbr
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date < '{analysis_date.isoformat()}'  -- FIX: Changed <= to < (cache should only include games BEFORE analysis_date)
        )
        SELECT *
        FROM ranked_games
        WHERE game_rank <= 10
        ORDER BY team_abbr, game_date DESC
        """
        
        self.team_offense_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.team_offense_data)} team offense records")
    
    def _extract_upcoming_context_data(self, analysis_date: date) -> None:
        """Extract upcoming player game context (today's games).

        In backfill mode, if no context data exists, generates synthetic context
        from player_game_summary instead (who actually played vs who was expected).
        """

        query = f"""
        SELECT
            player_lookup,
            universal_player_id,
            team_abbr,
            game_date,
            games_in_last_7_days,
            games_in_last_14_days,
            minutes_in_last_7_days,
            minutes_in_last_14_days,
            back_to_backs_last_14_days,
            avg_minutes_per_game_last_7,
            fourth_quarter_minutes_last_7,
            player_age
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date.isoformat()}'
        """

        self.upcoming_context_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.upcoming_context_data)} upcoming player contexts")

        # BACKFILL MODE: Generate synthetic context from PGS if no context data exists
        if self.upcoming_context_data.empty and self.is_backfill_mode:
            logger.warning(f"No upcoming_player_game_context for {analysis_date}, generating synthetic context from PGS (backfill mode)")
            self._generate_synthetic_context_data(analysis_date)

    def _generate_synthetic_context_data(self, analysis_date: date) -> None:
        """Generate synthetic context data from player_game_summary for backfill.

        This allows historical backfills to work even when upcoming_player_game_context
        was never populated (betting data wasn't scraped before games).

        Uses players who ACTUALLY played on the date (from PGS) instead of
        who was EXPECTED to play (from upcoming_player_game_context).
        """
        query = f"""
        WITH players_on_date AS (
            -- Get players who actually played on this date
            SELECT DISTINCT
                player_lookup,
                universal_player_id,
                team_abbr
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = '{analysis_date.isoformat()}'
        ),
        game_history AS (
            -- Get each player's game history for fatigue metrics
            SELECT
                pgs.player_lookup,
                pgs.game_date,
                pgs.minutes_played
            FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
            WHERE pgs.game_date >= DATE_SUB('{analysis_date.isoformat()}', INTERVAL 14 DAY)
              AND pgs.game_date < '{analysis_date.isoformat()}'
        ),
        fatigue_metrics AS (
            SELECT
                p.player_lookup,
                -- Games in last 7 days
                COUNTIF(gh.game_date >= DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)) as games_in_last_7_days,
                -- Games in last 14 days
                COUNT(gh.game_date) as games_in_last_14_days,
                -- Minutes in last 7 days
                COALESCE(SUM(CASE WHEN gh.game_date >= DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)
                    THEN gh.minutes_played ELSE 0 END), 0) as minutes_in_last_7_days,
                -- Minutes in last 14 days
                COALESCE(SUM(gh.minutes_played), 0) as minutes_in_last_14_days,
                -- Avg minutes per game last 7 (simplified)
                SAFE_DIVIDE(
                    SUM(CASE WHEN gh.game_date >= DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)
                        THEN gh.minutes_played ELSE 0 END),
                    COUNTIF(gh.game_date >= DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY))
                ) as avg_minutes_per_game_last_7
            FROM players_on_date p
            LEFT JOIN game_history gh ON p.player_lookup = gh.player_lookup
            GROUP BY p.player_lookup
        )
        SELECT
            p.player_lookup,
            p.universal_player_id,
            p.team_abbr,
            DATE('{analysis_date.isoformat()}') as game_date,
            COALESCE(fm.games_in_last_7_days, 0) as games_in_last_7_days,
            COALESCE(fm.games_in_last_14_days, 0) as games_in_last_14_days,
            CAST(COALESCE(fm.minutes_in_last_7_days, 0) AS INT64) as minutes_in_last_7_days,
            CAST(COALESCE(fm.minutes_in_last_14_days, 0) AS INT64) as minutes_in_last_14_days,
            0 as back_to_backs_last_14_days,  -- Not computed in synthetic mode
            COALESCE(fm.avg_minutes_per_game_last_7, 0) as avg_minutes_per_game_last_7,
            NULL as fourth_quarter_minutes_last_7,  -- Not available in PGS
            NULL as player_age  -- Could be computed from player registry if needed
        FROM players_on_date p
        LEFT JOIN fatigue_metrics fm ON p.player_lookup = fm.player_lookup
        """

        self.upcoming_context_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Generated {len(self.upcoming_context_data)} synthetic player contexts from PGS (backfill mode)")
    
    def _extract_shot_zone_data(self, analysis_date: date) -> None:
        """Extract shot zone analysis (today's analysis)."""
        
        query = f"""
        SELECT 
            player_lookup,
            universal_player_id,
            analysis_date,
            primary_scoring_zone,
            paint_rate_last_10,
            three_pt_rate_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{analysis_date.isoformat()}'
        """
        
        self.shot_zone_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.shot_zone_data)} shot zone analyses")

    def validate_extracted_data(self) -> None:
        """
        Validate that we have extracted data to process.

        Overrides base class to check upcoming_context_data instead of raw_data.
        """
        if self.upcoming_context_data is None or self.upcoming_context_data.empty:
            raise ValueError("No upcoming player context data extracted")

        # Log extraction summary
        logger.info(
            f"Data validation passed: {len(self.upcoming_context_data)} players, "
            f"{len(self.player_game_data) if self.player_game_data is not None else 0} game records, "
            f"{len(self.shot_zone_data) if self.shot_zone_data is not None else 0} shot zone records"
        )

    def _extract_source_hashes(self, analysis_date: date) -> None:
        """
        Extract data_hash from all 4 upstream tables.

        PERFORMANCE OPTIMIZATION: Consolidated 4 separate queries into 1 UNION ALL query
        for 4x speedup (reduces query overhead from ~8-12s to ~2-3s).

        These hashes represent the source data used for this cache generation.
        Used for Smart Reprocessing (Pattern #3) to skip processing when
        upstream data hasn't changed.
        """
        try:
            # Consolidated query - fetches all 4 hashes in ONE query using UNION ALL
            # Note: Each subquery must be wrapped in parentheses for BigQuery UNION syntax
            query = f"""
            (SELECT 'player_game_summary' as source, data_hash
             FROM `{self.project_id}.nba_analytics.player_game_summary`
             WHERE game_date <= '{analysis_date}' AND data_hash IS NOT NULL
             ORDER BY processed_at DESC LIMIT 1)

            UNION ALL

            (SELECT 'team_offense_game_summary' as source, data_hash
             FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
             WHERE game_date <= '{analysis_date}' AND data_hash IS NOT NULL
             ORDER BY processed_at DESC LIMIT 1)

            UNION ALL

            (SELECT 'upcoming_player_game_context' as source, data_hash
             FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
             WHERE game_date = '{analysis_date}' AND data_hash IS NOT NULL
             ORDER BY processed_at DESC LIMIT 1)

            UNION ALL

            (SELECT 'player_shot_zone_analysis' as source, data_hash
             FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
             WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL
             ORDER BY processed_at DESC LIMIT 1)
            """

            # Execute single consolidated query
            result = self.bq_client.query(query).to_dataframe()

            # Extract hashes from consolidated result
            self.source_player_game_hash = None
            self.source_team_offense_hash = None
            self.source_upcoming_context_hash = None
            self.source_shot_zone_hash = None

            if not result.empty:
                for _, row in result.iterrows():
                    source = row['source']
                    data_hash = str(row['data_hash']) if row['data_hash'] else None

                    if source == 'player_game_summary':
                        self.source_player_game_hash = data_hash
                    elif source == 'team_offense_game_summary':
                        self.source_team_offense_hash = data_hash
                    elif source == 'upcoming_player_game_context':
                        self.source_upcoming_context_hash = data_hash
                    elif source == 'player_shot_zone_analysis':
                        self.source_shot_zone_hash = data_hash

            logger.info(f"Extracted source hashes: player_game={self.source_player_game_hash[:16] if self.source_player_game_hash else 'None'}..., "
                       f"team_offense={self.source_team_offense_hash[:16] if self.source_team_offense_hash else 'None'}..., "
                       f"upcoming_context={self.source_upcoming_context_hash[:16] if self.source_upcoming_context_hash else 'None'}..., "
                       f"shot_zone={self.source_shot_zone_hash[:16] if self.source_shot_zone_hash else 'None'}...")

        except Exception as e:
            logger.warning(f"Failed to extract source hashes: {e}")
            self.source_player_game_hash = None
            self.source_team_offense_hash = None
            self.source_upcoming_context_hash = None
            self.source_shot_zone_hash = None

    # ============================================================
    # Completeness Checking Methods (Week 3 - Phase 4 Multi-Window)
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

    def _check_circuit_breakers_batch(self, entity_ids: List[str], analysis_date: date) -> Dict[str, dict]:
        """
        Check circuit breaker status for multiple entities in one query.

        Returns dict mapping entity_id to status dict with:
            - active: bool (True if circuit breaker active)
            - attempts: int (number of attempts so far)
            - until: datetime (when circuit breaker expires)
        """
        if not entity_ids:
            return {}

        # Build IN clause for query
        entity_ids_str = "', '".join(entity_ids)

        query = f"""
        WITH latest_attempts AS (
            SELECT
                entity_id,
                attempt_number,
                attempted_at,
                circuit_breaker_tripped,
                circuit_breaker_until,
                ROW_NUMBER() OVER (
                    PARTITION BY entity_id
                    ORDER BY attempt_number DESC
                ) as rn
            FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
            WHERE processor_name = '{self.table_name}'
              AND entity_id IN ('{entity_ids_str}')
              AND analysis_date = DATE('{analysis_date}')
        )
        SELECT
            entity_id,
            attempt_number,
            circuit_breaker_tripped,
            circuit_breaker_until
        FROM latest_attempts
        WHERE rn = 1
        """

        try:
            result = self.bq_client.query(query).to_dataframe()

            # Build status dict for each entity
            status_map = {}
            now = datetime.now(timezone.utc)

            for _, row in result.iterrows():
                entity_id = row['entity_id']

                if row['circuit_breaker_tripped']:
                    # Check if circuit breaker still active
                    if pd.notna(row['circuit_breaker_until']):
                        cb_until = row['circuit_breaker_until']
                        # Handle timezone-aware comparison
                        if cb_until.tzinfo is None:
                            cb_until = cb_until.replace(tzinfo=timezone.utc)

                        if now < cb_until:
                            status_map[entity_id] = {
                                'active': True,
                                'attempts': int(row['attempt_number']),
                                'until': cb_until
                            }
                            continue

                # Circuit breaker not active or expired
                status_map[entity_id] = {
                    'active': False,
                    'attempts': int(row['attempt_number']),
                    'until': None
                }

            # Add default status for entities not in results
            for entity_id in entity_ids:
                if entity_id not in status_map:
                    status_map[entity_id] = {
                        'active': False,
                        'attempts': 0,
                        'until': None
                    }

            return status_map

        except Exception as e:
            logger.warning(f"Error checking circuit breakers in batch: {e}")
            # Return default status for all entities
            return {
                entity_id: {'active': False, 'attempts': 0, 'until': None}
                for entity_id in entity_ids
            }

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

    def _batch_increment_reprocess_counts(self, items: list, analysis_date: date) -> None:
        """
        Batch insert reprocess attempts using a single multi-row INSERT query.

        This is ~50x faster than individual inserts (1 query vs N queries).
        Each BQ query has ~2-3s overhead, so batching 50 items saves ~100-150s.
        """
        if not items:
            return

        # Get config for lockout duration (default: 24 hours, was 7 days)
        from shared.config.orchestration_config import get_orchestration_config
        config = get_orchestration_config()

        # First, batch check all circuit breakers
        entity_ids = [item['entity_id'] for item in items]
        circuit_status_map = self._check_circuit_breakers_batch(entity_ids, analysis_date)

        # Build batch INSERT with UNION ALL
        value_rows = []
        tripped_count = 0

        for item in items:
            entity_id = item['entity_id']
            completeness_pct = item.get('completeness_pct', 0.0)
            skip_reason = item.get('skip_reason', 'unknown')

            circuit_status = circuit_status_map.get(entity_id, {'active': False, 'attempts': 0, 'until': None})
            next_attempt = circuit_status['attempts'] + 1

            # Trip circuit breaker on 3rd attempt
            circuit_breaker_tripped = next_attempt >= 3
            circuit_breaker_until_sql = 'NULL'

            if circuit_breaker_tripped:
                tripped_count += 1
                circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=config.circuit_breaker.entity_lockout_hours)
                circuit_breaker_until_sql = f'TIMESTAMP("{circuit_breaker_until.isoformat()}")'

            value_rows.append(f"""
                SELECT
                    '{self.table_name}' as processor_name,
                    '{entity_id}' as entity_id,
                    DATE('{analysis_date}') as analysis_date,
                    {next_attempt} as attempt_number,
                    CURRENT_TIMESTAMP() as attempted_at,
                    {completeness_pct} as completeness_pct,
                    '{skip_reason}' as skip_reason,
                    {circuit_breaker_tripped} as circuit_breaker_tripped,
                    {circuit_breaker_until_sql} as circuit_breaker_until,
                    FALSE as manual_override_applied,
                    'Attempt {next_attempt}: {completeness_pct:.1f}% complete' as notes
            """)

        # Combine into single INSERT with UNION ALL
        batch_query = f"""
        INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
        (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
         completeness_pct, skip_reason, circuit_breaker_tripped, circuit_breaker_until,
         manual_override_applied, notes)
        {' UNION ALL '.join(value_rows)}
        """

        try:
            self.bq_client.query(batch_query).result(timeout=60)
            logger.info(f"Batch recorded {len(items)} reprocess attempts ({tripped_count} circuit breakers tripped)")
        except Exception as e:
            logger.warning(f"Failed to batch record reprocess attempts: {e}")
            # Fall back to individual inserts if batch fails
            logger.info("Falling back to individual inserts...")
            for item in items:
                self._increment_reprocess_count(
                    item['entity_id'],
                    analysis_date,
                    item.get('completeness_pct', 0.0),
                    item.get('skip_reason', 'unknown')
                )

    def calculate_precompute(self) -> None:
        """
        Calculate cache records for all players.
        
        Process:
            1. Iterate through all players in upcoming_context
            2. Calculate recent performance metrics (last 5, last 10, season)
            3. Calculate team context (pace, offensive rating)
            4. Copy fatigue metrics from upcoming_context
            5. Copy shot zone tendencies from shot_zone_analysis
            6. Calculate assisted rate from player_game_summary
            7. Build complete cache record with source tracking
        
        Output:
            - self.transformed_data: List of successful cache records
            - self.failed_entities: List of failed players with reasons
        """
        analysis_date = self.opts['analysis_date']
        
        successful = []
        failed = []

        if self.upcoming_context_data.empty:
            logger.info("No players scheduled today - skipping cache generation")
            self.transformed_data = successful
            self.failed_entities = failed
            return
        
        # Get all players scheduled to play today
        all_players = self.upcoming_context_data['player_lookup'].unique()
        logger.info(f"Processing cache for {len(all_players)} players")

        # ============================================================
        # PERFORMANCE OPTIMIZATION: Run completeness checks in parallel (4x speedup)
        # Each check takes ~30 sec due to BQ query overhead, running them concurrently
        # reduces total time from ~2 min to ~30 sec
        # ============================================================
        import time
        completeness_start = time.time()
        logger.info(f"Checking completeness for {len(all_players)} players across 4 windows...")

        # Use MultiWindowCompletenessChecker to orchestrate parallel checks
        completeness_results = self.multi_window_checker.check_all_windows(
            player_ids=list(all_players),
            analysis_date=analysis_date,
            season_start_date=self.season_start_date
        )
        is_bootstrap, is_season_boundary = self.multi_window_checker.check_bootstrap_and_boundary(
            analysis_date=analysis_date,
            season_start_date=self.season_start_date
        )

        # Extract results with defaults
        completeness_l5 = completeness_results.get('L5', {})
        completeness_l10 = completeness_results.get('L10', {})
        completeness_l7d = completeness_results.get('L7d', {})
        completeness_l14d = completeness_results.get('L14d', {})

        # Check for same-day/future predictions mode
        # For same-day predictions, games haven't been played yet so player_game_summary
        # won't have today's data. We should skip completeness checks in this case.
        from datetime import date
        is_same_day_or_future = analysis_date >= date.today()
        skip_dependency_check = self.opts.get('skip_dependency_check', False)
        strict_mode = self.opts.get('strict_mode', True)

        # Determine if we should skip completeness checks
        # Same logic as MLFeatureStoreProcessor for consistency
        skip_completeness_checks = (
            is_bootstrap or
            is_season_boundary or
            is_same_day_or_future or
            skip_dependency_check or
            not strict_mode
        )

        completeness_elapsed = time.time() - completeness_start
        logger.info(
            f"Completeness check complete in {completeness_elapsed:.1f}s (4 windows, parallel). "
            f"Bootstrap mode: {is_bootstrap}, Season boundary: {is_season_boundary}, "
            f"Same-day mode: {is_same_day_or_future}, Skip completeness: {skip_completeness_checks}"
        )
        # ============================================================

        # ============================================================
        # PRE-FETCH CIRCUIT BREAKER STATUS (for ProcessPoolExecutor compatibility)
        # Skip in bootstrap/season boundary/same-day mode for speed
        # ============================================================
        circuit_breaker_map = {}
        if not skip_completeness_checks:
            logger.info(f"Checking circuit breakers for {len(all_players)} players...")
            cb_start = time.time()
            circuit_breaker_map = self._check_circuit_breakers_batch(list(all_players), analysis_date)
            cb_elapsed = time.time() - cb_start
            logger.info(f"Circuit breaker check complete in {cb_elapsed:.1f}s")
        else:
            # Default status for all players in bootstrap/boundary/same-day mode
            circuit_breaker_map = {
                player: {'active': False, 'attempts': 0, 'until': None}
                for player in all_players
            }
        # ============================================================

        # ============================================================
        # Feature flag for parallelization
        # ============================================================
        ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'

        # When skip_completeness_checks is True, we pass it as is_bootstrap=True
        # to bypass the completeness validation in process_single_player
        # This is simpler than changing the function signature of all internal methods
        effective_is_bootstrap = is_bootstrap or skip_completeness_checks

        if ENABLE_PARALLELIZATION:
            successful, failed = self._process_players_parallel(
                all_players, completeness_l5, completeness_l10, completeness_l7d, completeness_l14d,
                effective_is_bootstrap, is_season_boundary, analysis_date, circuit_breaker_map
            )
        else:
            successful, failed = self._process_players_serial(
                all_players, completeness_l5, completeness_l10, completeness_l7d, completeness_l14d,
                effective_is_bootstrap, is_season_boundary, analysis_date
            )

        self.transformed_data = successful
        self.failed_entities = failed

        logger.info(f"Cache calculation complete: {len(successful)} successful, {len(failed)} failed")

        # Count failures by category for clear visibility
        if failed:
            category_counts = {}
            for f in failed:
                cat = f.get('category', 'UNKNOWN')
                category_counts[cat] = category_counts.get(cat, 0) + 1

            # Show breakdown with clear labeling
            expected_skips = category_counts.get('INSUFFICIENT_DATA', 0) + category_counts.get('INCOMPLETE_DATA', 0) + category_counts.get('NO_SHOT_ZONE', 0)
            errors_to_investigate = category_counts.get('PROCESSING_ERROR', 0) + category_counts.get('UNKNOWN', 0)

            logger.info(f"📊 Failure breakdown by category:")
            for cat, count in sorted(category_counts.items()):
                if cat in ('INSUFFICIENT_DATA', 'INCOMPLETE_DATA', 'NO_SHOT_ZONE', 'CIRCUIT_BREAKER_ACTIVE'):
                    logger.info(f"   {cat}: {count} (expected - data quality)")
                else:
                    logger.warning(f"   {cat}: {count} ⚠️ INVESTIGATE")

            if errors_to_investigate == 0:
                logger.info(f"✅ No errors to investigate - all {expected_skips} skips are expected (data quality)")

            # Store category breakdown in stats for backfill summary
            self.stats['failure_categories'] = category_counts
            self.stats['errors_to_investigate'] = errors_to_investigate

            # Save failures to BigQuery for auditing
            self.save_failures_to_bq()

    def _process_players_parallel(
        self,
        all_players: List[str],
        completeness_l5: dict,
        completeness_l10: dict,
        completeness_l7d: dict,
        completeness_l14d: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date,
        circuit_breaker_map: Dict[str, dict]
    ) -> tuple:
        """
        Process all players using ProcessPoolExecutor for parallelization.

        ProcessPoolExecutor provides better performance for CPU-bound tasks (pandas calculations)
        compared to ThreadPoolExecutor (limited by Python GIL).

        Key differences from ThreadPoolExecutor:
        - Uses separate processes instead of threads (bypasses GIL)
        - Requires all data to be picklable (no BigQuery client access in workers)
        - Circuit breaker status pre-fetched before parallelization
        - Reprocess count increments handled in main thread after workers complete
        """
        # Determine worker count with environment variable support
        DEFAULT_WORKERS = 32  # Higher default for ProcessPool (vs 8 for ThreadPool)
        max_workers = int(os.environ.get(
            'PDC_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        logger.info(f"Processing {len(all_players)} players with {max_workers} workers (ProcessPool mode)")

        # Performance timing
        loop_start = time.time()
        processed_count = 0

        # Process-safe result collection
        successful = []
        failed = []
        needs_reprocess_increment = []  # Track entities needing reprocess count increment

        # Prepare data for worker functions (must be picklable)
        source_tracking_fields = self.build_source_tracking_fields()
        source_hashes = {
            'player_game': self.source_player_game_hash,
            'team_offense': self.source_team_offense_hash,
            'upcoming_context': self.source_upcoming_context_hash,
            'shot_zone': self.source_shot_zone_hash
        }

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all player tasks using module-level worker function
            futures = {
                executor.submit(
                    _process_single_player_worker,  # Module-level function (picklable)
                    player_lookup,
                    self.upcoming_context_data,     # DataFrames are picklable
                    self.player_game_data,
                    self.team_offense_data,
                    self.shot_zone_data,
                    completeness_l5,
                    completeness_l10,
                    completeness_l7d,
                    completeness_l14d,
                    is_bootstrap,
                    is_season_boundary,
                    analysis_date,
                    circuit_breaker_map.get(player_lookup, {'active': False, 'attempts': 0, 'until': None}),
                    self.min_games_required,
                    self.absolute_min_games,
                    self.cache_version,
                    source_tracking_fields,
                    source_hashes
                ): player_lookup
                for player_lookup in all_players
            }

            # Collect results as they complete
            for future in as_completed(futures):
                player_lookup = futures[future]
                processed_count += 1

                try:
                    success, data = future.result()
                    if success:
                        successful.append(data)
                    else:
                        failed.append(data)
                        # Track incomplete data failures for reprocess count increment
                        if data.get('category') == 'INCOMPLETE_DATA' and data.get('can_retry'):
                            needs_reprocess_increment.append({
                                'entity_id': player_lookup,
                                'completeness_pct': data.get('completeness_pct', 0.0),
                                'skip_reason': 'incomplete_upstream_data_multi_window'
                            })

                    # Progress logging every 50 players
                    if processed_count % 50 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed
                        remaining = len(all_players) - processed_count
                        eta = remaining / rate if rate > 0 else 0
                        logger.info(
                            f"Player cache progress: {processed_count}/{len(all_players)} "
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

        # Final timing summary
        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(successful)} players in {total_time:.1f}s "
            f"(avg {total_time/len(successful) if successful else 0:.2f}s/player) "
            f"| {len(failed)} failed"
        )

        # Handle reprocess count increments in main thread (requires BQ client)
        # SKIP in backfill mode - saves ~2.5s per failure × 50 failures = 125s per date
        # For 680 dates with 50 failures each, this saves ~24 hours of processing time
        if needs_reprocess_increment:
            if self.is_backfill_mode:
                logger.info(f"⏭️  BACKFILL MODE: Skipping {len(needs_reprocess_increment)} reprocess attempt recordings")
            else:
                logger.info(f"Recording {len(needs_reprocess_increment)} reprocess attempts...")
                # Batch the inserts instead of individual queries for better performance
                self._batch_increment_reprocess_counts(needs_reprocess_increment, analysis_date)

        return successful, failed

    def _process_single_player(
        self,
        player_lookup: str,
        completeness_l5: dict,
        completeness_l10: dict,
        completeness_l7d: dict,
        completeness_l14d: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date,
        circuit_breaker_map: Dict[str, dict] = None
    ) -> tuple:
        """
        Process one player (process-safe for ProcessPoolExecutor).

        Returns (success: bool, data: dict).

        Note: This method must be picklable for ProcessPoolExecutor, so it cannot
        access self.bq_client or any other non-picklable attributes. All BQ-dependent
        data (circuit breaker status) must be pre-fetched and passed as parameters.
        """
        try:
            # ============================================================
            # Get completeness for all windows
            # ============================================================
            comp_l5 = completeness_l5.get(player_lookup, {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            })
            comp_l10 = completeness_l10.get(player_lookup, {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            })
            comp_l7d = completeness_l7d.get(player_lookup, {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            })
            comp_l14d = completeness_l14d.get(player_lookup, {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            })

            # ALL windows must be production-ready for overall production readiness
            all_windows_complete = (
                comp_l5['is_production_ready'] and
                comp_l10['is_production_ready'] and
                comp_l7d['is_production_ready'] and
                comp_l14d['is_production_ready']
            )

            # Use L10 as primary completeness metric
            completeness = comp_l10

            # Get pre-fetched circuit breaker status (no BQ access in worker)
            if circuit_breaker_map is None:
                circuit_breaker_map = {}

            circuit_breaker_status = circuit_breaker_map.get(player_lookup, {
                'active': False, 'attempts': 0, 'until': None
            })

            if circuit_breaker_status['active']:
                logger.warning(
                    f"{player_lookup}: Circuit breaker active until "
                    f"{circuit_breaker_status['until']} - skipping"
                )
                return (False, {
                    'entity_id': player_lookup,
                    'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                    'category': 'CIRCUIT_BREAKER_ACTIVE',
                    'can_retry': False
                })

            # Check production readiness (skip if any window incomplete, unless in bootstrap mode or season boundary)
            if not all_windows_complete and not is_bootstrap and not is_season_boundary:
                logger.warning(
                    f"{player_lookup}: Not all windows complete - "
                    f"L5={comp_l5['completeness_pct']:.1f}%, L10={comp_l10['completeness_pct']:.1f}%, "
                    f"L7d={comp_l7d['completeness_pct']:.1f}%, L14d={comp_l14d['completeness_pct']:.1f}% - skipping"
                )

                # DON'T increment reprocess count here (requires BQ client)
                # Main thread will handle this after collecting all results
                return (False, {
                    'entity_id': player_lookup,
                    'reason': f"Incomplete data across windows",
                    'category': 'INCOMPLETE_DATA',
                    'can_retry': True,
                    'completeness_pct': completeness['completeness_pct']  # Include for main thread
                })
            # ============================================================

            # Get player's context data
            context_row = self.upcoming_context_data[
                self.upcoming_context_data['player_lookup'] == player_lookup
            ].iloc[0]

            # Get player's game history
            player_games = self.player_game_data[
                self.player_game_data['player_lookup'] == player_lookup
            ].copy()

            # Check minimum games requirement
            games_count = len(player_games)
            if games_count < self.absolute_min_games:
                return (False, {
                    'entity_id': player_lookup,
                    'reason': f"Only {games_count} games played, need {self.absolute_min_games} minimum",
                    'category': 'INSUFFICIENT_DATA',
                    'can_retry': True
                })

            # Flag if below preferred minimum
            is_early_season = games_count < self.min_games_required

            # Get team context
            current_team = context_row['team_abbr']
            team_games = self.team_offense_data[
                self.team_offense_data['team_abbr'] == current_team
            ].copy()

            # Get shot zone data (optional - proceeds with nulls if missing)
            shot_zone_row = self.shot_zone_data[
                self.shot_zone_data['player_lookup'] == player_lookup
            ]

            # Track shot zone availability for state tracking
            shot_zone_available = not shot_zone_row.empty
            if shot_zone_row.empty:
                # Create placeholder with null values - shot zone is optional enrichment
                shot_zone_row = pd.Series({
                    'primary_scoring_zone': None,
                    'paint_rate_last_10': None,
                    'three_pt_rate_last_10': None
                })
            else:
                shot_zone_row = shot_zone_row.iloc[0]

            # Calculate all metrics
            cache_record = self._calculate_player_cache(
                player_lookup=player_lookup,
                context_row=context_row,
                player_games=player_games,
                team_games=team_games,
                shot_zone_row=shot_zone_row,
                analysis_date=analysis_date,
                is_early_season=is_early_season,
                completeness_data={
                    'comp_l5': comp_l5,
                    'comp_l10': comp_l10,
                    'comp_l7d': comp_l7d,
                    'comp_l14d': comp_l14d,
                    'all_windows_complete': all_windows_complete,
                    'is_bootstrap': is_bootstrap,
                    'is_season_boundary': is_season_boundary,
                    'circuit_breaker_status': circuit_breaker_status,
                },
                shot_zone_available=shot_zone_available
            )

            return (True, cache_record)

        except Exception as e:
            logger.error(f"Failed to process {player_lookup}: {e}", exc_info=True)
            return (False, {
                'entity_id': player_lookup,
                'reason': str(e),
                'category': 'PROCESSING_ERROR',
                'can_retry': False
            })

    def _process_players_serial(
        self,
        all_players: List[str],
        completeness_l5: dict,
        completeness_l10: dict,
        completeness_l7d: dict,
        completeness_l14d: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Original serial processing (kept for fallback)."""
        logger.info(f"Processing {len(all_players)} players (serial mode)")

        successful = []
        failed = []
        processed_count = 0

        for player_lookup in all_players:
            try:
                # Progress logging every 50 players
                processed_count += 1
                if processed_count % 50 == 0 or processed_count == len(all_players):
                    logger.info(f"Processing player {processed_count}/{len(all_players)} ({100*processed_count/len(all_players):.1f}%)")

                # ============================================================
                # Get completeness for all windows
                # ============================================================
                comp_l5 = completeness_l5.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })
                comp_l10 = completeness_l10.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })
                comp_l7d = completeness_l7d.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })
                comp_l14d = completeness_l14d.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })

                # ALL windows must be production-ready for overall production readiness
                all_windows_complete = (
                    comp_l5['is_production_ready'] and
                    comp_l10['is_production_ready'] and
                    comp_l7d['is_production_ready'] and
                    comp_l14d['is_production_ready']
                )

                # Use L10 as primary completeness metric
                completeness = comp_l10

                # Check circuit breaker
                circuit_breaker_status = self._check_circuit_breaker(player_lookup, analysis_date)

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

                # Check production readiness (skip if any window incomplete, unless in bootstrap mode or season boundary)
                if not all_windows_complete and not is_bootstrap and not is_season_boundary:
                    logger.warning(
                        f"{player_lookup}: Not all windows complete - "
                        f"L5={comp_l5['completeness_pct']:.1f}%, L10={comp_l10['completeness_pct']:.1f}%, "
                        f"L7d={comp_l7d['completeness_pct']:.1f}%, L14d={comp_l14d['completeness_pct']:.1f}% - skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_upstream_data_multi_window'
                    )

                    failed.append({
                        'entity_id': player_lookup,
                        'reason': f"Incomplete data across windows",
                        'category': 'INCOMPLETE_DATA',
                        'can_retry': True
                    })
                    continue
                # ============================================================

                # Get player's context data
                context_row = self.upcoming_context_data[
                    self.upcoming_context_data['player_lookup'] == player_lookup
                ].iloc[0]

                # Get player's game history
                player_games = self.player_game_data[
                    self.player_game_data['player_lookup'] == player_lookup
                ].copy()

                # Check minimum games requirement
                games_count = len(player_games)
                if games_count < self.absolute_min_games:
                    failed.append({
                        'entity_id': player_lookup,
                        'reason': f"Only {games_count} games played, need {self.absolute_min_games} minimum",
                        'category': 'INSUFFICIENT_DATA',
                        'can_retry': True
                    })
                    continue
                
                # Flag if below preferred minimum
                is_early_season = games_count < self.min_games_required
                
                # Get team context
                current_team = context_row['team_abbr']
                team_games = self.team_offense_data[
                    self.team_offense_data['team_abbr'] == current_team
                ].copy()
                
                # Get shot zone data (optional - proceeds with nulls if missing)
                shot_zone_row = self.shot_zone_data[
                    self.shot_zone_data['player_lookup'] == player_lookup
                ]

                # Track shot zone availability for state tracking
                shot_zone_available = not shot_zone_row.empty
                if shot_zone_row.empty:
                    # Create placeholder with null values - shot zone is optional enrichment
                    shot_zone_row = pd.Series({
                        'primary_scoring_zone': None,
                        'paint_rate_last_10': None,
                        'three_pt_rate_last_10': None
                    })
                else:
                    shot_zone_row = shot_zone_row.iloc[0]
                
                # Calculate all metrics
                cache_record = self._calculate_player_cache(
                    player_lookup=player_lookup,
                    context_row=context_row,
                    player_games=player_games,
                    team_games=team_games,
                    shot_zone_row=shot_zone_row,
                    analysis_date=analysis_date,
                    is_early_season=is_early_season,
                    completeness_data={
                        'comp_l5': comp_l5,
                        'comp_l10': comp_l10,
                        'comp_l7d': comp_l7d,
                        'comp_l14d': comp_l14d,
                        'all_windows_complete': all_windows_complete,
                        'is_bootstrap': is_bootstrap,
                        'is_season_boundary': is_season_boundary,
                        'circuit_breaker_status': circuit_breaker_status,
                    },
                    shot_zone_available=shot_zone_available
                )

                successful.append(cache_record)

            except Exception as e:
                logger.error(f"Failed to process {player_lookup}: {e}", exc_info=True)
                failed.append({
                    'entity_id': player_lookup,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })

        return successful, failed
    
    def _calculate_player_cache(
        self,
        player_lookup: str,
        context_row: pd.Series,
        player_games: pd.DataFrame,
        team_games: pd.DataFrame,
        shot_zone_row: pd.Series,
        analysis_date: date,
        is_early_season: bool,
        completeness_data: Dict = None,
        shot_zone_available: bool = True
    ) -> Dict:
        """
        Calculate complete cache record for a single player.

        Args:
            player_lookup: Player identifier
            context_row: Row from upcoming_player_game_context
            player_games: Player's game history (sorted desc by date)
            team_games: Team's game history (sorted desc by date)
            shot_zone_row: Row from player_shot_zone_analysis
            analysis_date: Cache date
            is_early_season: Whether player has < min_games_required
            shot_zone_available: Whether shot zone data was available (for re-run tracking)

        Returns:
            Dict: Complete cache record ready for BigQuery
        """
        # Extract completeness data
        if completeness_data:
            comp_l5 = completeness_data.get('comp_l5', {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False})
            comp_l10 = completeness_data.get('comp_l10', {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False})
            comp_l7d = completeness_data.get('comp_l7d', {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False})
            comp_l14d = completeness_data.get('comp_l14d', {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False})
            all_windows_complete = completeness_data.get('all_windows_complete', False)
            is_bootstrap = completeness_data.get('is_bootstrap', False)
            is_season_boundary = completeness_data.get('is_season_boundary', False)
            circuit_breaker_status = completeness_data.get('circuit_breaker_status', {'active': False, 'until': None, 'attempts': 0})
        else:
            # Default values for backwards compatibility
            comp_l5 = {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False}
            comp_l10 = {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False}
            comp_l7d = {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False}
            comp_l14d = {'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0, 'missing_count': 0, 'is_production_ready': False}
            all_windows_complete = False
            is_bootstrap = False
            is_season_boundary = False
            circuit_breaker_status = {'active': False, 'until': None, 'attempts': 0}

        # Aggregate data from all sources using specialized aggregators
        stats_data = StatsAggregator.aggregate(player_games)
        team_data = TeamAggregator.aggregate(team_games)
        context_data = ContextAggregator.aggregate(context_row)
        shot_zone_data = ShotZoneAggregator.aggregate(shot_zone_row)

        # Build completeness results dict
        completeness_results = {
            'L5': comp_l5,
            'L10': comp_l10,
            'L7d': comp_l7d,
            'L14d': comp_l14d,
        }

        # Build source tracking fields and hashes
        source_tracking_fields = self.build_source_tracking_fields()
        source_hashes = {
            'player_game': self.source_player_game_hash,
            'team_offense': self.source_team_offense_hash,
            'upcoming_context': self.source_upcoming_context_hash,
            'shot_zone': self.source_shot_zone_hash
        }

        # Build complete cache record using CacheBuilder
        record = CacheBuilder.build_record(
            player_lookup=player_lookup,
            analysis_date=analysis_date,
            stats_data=stats_data,
            team_data=team_data,
            context_data=context_data,
            shot_zone_data=shot_zone_data,
            completeness_results=completeness_results,
            circuit_breaker_status=circuit_breaker_status,
            source_tracking=source_tracking_fields,
            source_hashes=source_hashes,
            is_early_season=is_early_season,
            is_season_boundary=is_season_boundary,
            is_bootstrap=is_bootstrap,
            shot_zone_available=shot_zone_available,
            min_games_required=self.min_games_required,
            cache_version=self.cache_version,
            context_row=context_row
        )

        # Compute and add data hash (Smart Idempotency - Pattern #1)
        record['data_hash'] = self.compute_data_hash(record)

        return record

    # ========================================================================
    # STATS & REPORTING
    # ========================================================================

    def get_precompute_stats(self) -> dict:
        """
        Get processor-specific stats for logging and backfill tracking.

        Returns:
            dict: Stats including players_processed, players_failed, and cache metadata
        """
        return {
            'players_processed': len(self.transformed_data) if self.transformed_data else 0,
            'players_failed': len(self.failed_entities) if self.failed_entities else 0,
            'early_season': getattr(self, 'early_season_flag', False),
            'cache_version': self.cache_version
        }


def main():
    """
    Main entry point for the player daily cache processor.
    
    Usage:
        python player_daily_cache_processor.py --analysis_date 2025-01-21
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Player Daily Cache Processor')
    parser.add_argument(
        '--analysis_date',
        type=str,
        required=True,
        help='Analysis date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--season_year',
        type=int,
        help='Season year (optional, will auto-detect from date)'
    )
    
    args = parser.parse_args()
    
    # Parse analysis date
    analysis_date = datetime.strptime(args.analysis_date, '%Y-%m-%d').date()
    
    # Auto-detect season year if not provided
    season_year = args.season_year
    if not season_year:
        season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1
    
    # Initialize processor
    processor = PlayerDailyCacheProcessor()
    
    # Set options
    processor.opts = {
        'analysis_date': analysis_date,
        'season_year': season_year
    }
    
    try:
        # Extract data
        logger.info("Starting data extraction...")
        processor.extract_raw_data()
        
        # Calculate cache
        logger.info("Starting cache calculation...")
        processor.calculate_precompute()
        
        # Save results
        logger.info("Saving cache to BigQuery...")
        success = processor.save_precompute()
        
        if success:
            logger.info("✓ Player daily cache processing complete!")
            logger.info(f"  - Cached: {len(processor.transformed_data)} players")
            logger.info(f"  - Failed: {len(processor.failed_entities)} players")
        else:
            logger.error("✗ Failed to save player daily cache")
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    exit(main())
