#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py

Upcoming Player Game Context Processor - Phase 3 Analytics

Generates comprehensive pre-game context for ALL players with games scheduled.
Combines historical performance, fatigue metrics, prop betting context, and game
situation factors.

FIXES IN THIS VERSION:
- Fixed KeyError when handling players with no historical data (empty DataFrame)
- Made error return dict consistent with success return (includes 'players_failed')
- Fixed deprecation warnings (datetime.utcnow() → datetime.now(timezone.utc))
- Added timezone import

v3.1 ENHANCEMENTS:
- Added BettingPros fallback when Odds API has no data for a date
- Increases historical coverage from 40% to 99.7%
- Fallback logic in _extract_players_with_props() and _extract_prop_lines()

v3.2 ENHANCEMENTS (All-Player Predictions):
- Changed DRIVER query from props-based to gamebook-based
- Now processes ALL active players with games (~67/day), not just those with props (~22/day)
- Added has_prop_line flag to track which players have betting lines
- Enables predictions for all players, improving ML model training coverage

Input: Phase 2 raw tables only
  - nba_raw.nbac_gamebook_player_stats (DRIVER - ALL players with games)
  - nba_raw.odds_api_player_points_props (props info - LEFT JOIN)
  - nba_raw.bettingpros_player_points_props (props fallback - LEFT JOIN)
  - nba_raw.bdl_player_boxscores (PRIMARY - historical performance)
  - nba_raw.nbac_schedule (game timing and context)
  - nba_raw.odds_api_game_lines (spreads, totals)
  - nba_raw.espn_team_rosters (optional - current team)
  - nba_raw.nbac_injury_report (optional - injury status)
  - nba_reference.nba_players_registry (optional - universal player ID)

Output: nba_analytics.upcoming_player_game_context
Strategy: MERGE_UPDATE (update existing or insert new)
Frequency: Multiple times per day (morning, updates throughout day, pre-game)

Key Features:
- Processes ALL active players, not just those with prop lines
- has_prop_line flag indicates which players have betting lines
- Calculates rest days, back-to-backs, fatigue metrics from schedule
- Aggregates historical performance (last 5, last 10, last 30 days)
- Tracks prop line movement (opening vs current) for players with props
- Calculates game situation context (spreads, totals, competitiveness)
- Handles rookies, limited history, missing data gracefully
- Quality flags for data completeness and confidence
"""

import logging
import os
import re
import hashlib
import json
import uuid
import io
import time
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded
import pandas as pd
import numpy as np

from data_processors.analytics.analytics_base import AnalyticsProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

# Completeness checking (Week 5 - Phase 3 Multi-Window)
from shared.utils.completeness_checker import CompletenessChecker

# Team mapping utility (handles abbreviation variants: BKN/BRK, CHA/CHO, etc.)
from shared.utils.nba_team_mapper import get_nba_team_mapper, get_team_info

# Orchestration config for processing mode (Issue 1 fix)
from shared.config.orchestration_config import get_orchestration_config

# Player registry for universal player ID lookup
from shared.utils.player_registry import RegistryReader

# Travel utilities for distance and timezone calculations
from data_processors.analytics.utils.travel_utils import NBATravel

logger = logging.getLogger(__name__)


class UpcomingPlayerGameContextProcessor(
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Process upcoming player game context from Phase 2 raw data.

    This processor creates pre-game context records for every player who has
    a points prop bet available. It combines historical performance, fatigue
    analysis, prop betting context, and game situation factors.

    Phase 3 Analytics Processor - depends only on Phase 2 raw tables
    """

    # Primary key fields for duplicate detection and MERGE operations
    PRIMARY_KEY_FIELDS = ['game_date', 'player_lookup']

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_analytics.upcoming_player_game_context'
        self.processing_strategy = 'MERGE_UPDATE'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'

        # Initialize target_date (set later in extract_raw_data)
        self.target_date = None

        # BigQuery client already initialized by AnalyticsProcessorBase with pooling
        # Don't specify location to allow querying datasets in any location (US and us-west2)
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

        # Initialize completeness checker (Week 5 - Phase 3 Multi-Window)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # Initialize registry reader for universal player ID lookup
        self.registry_reader = RegistryReader(
            source_name='upcoming_player_game_context',
            cache_ttl_seconds=300
        )
        self.registry_stats = {
            'players_found': 0,
            'players_not_found': 0
        }

        # Configuration
        self.lookback_days = 30  # Historical data window
        self.min_games_for_high_quality = 10
        self.min_games_for_medium_quality = 5
        self.min_bookmakers_required = 3  # For consensus calculations

        # Data holders (FIXED: Moved from unreachable code after return statement)
        self.players_to_process = []  # List of (player_lookup, game_id, team_abbr)
        self.historical_boxscores = {}  # player_lookup -> DataFrame
        self.schedule_data = {}  # game_id -> game info
        self.prop_lines = {}  # (player_lookup, game_id) -> prop info
        self.game_lines = {}  # game_id -> lines info
        self.rosters = {}  # player_lookup -> roster info
        self.injuries = {}  # player_lookup -> injury info
        self.registry = {}  # player_lookup -> universal_player_id
        self.standings_data = {}  # team_abbr -> win_percentage (for opponent win pct)

        # Travel utilities for distance/timezone calculations (P1-20)
        self._travel_utils = None  # Lazy-loaded
        self._team_travel_cache = {}  # team_abbr -> travel metrics

        # Season start date (for completeness checking - Week 5)
        self.season_start_date = None

        # Source tracking (for dependency tracking pattern)
        self.source_tracking = {
            'boxscore': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'schedule': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'props': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None},
            'game_lines': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None}
        }

        # Processing results
        self.transformed_data = []
        self.failed_entities = []

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> str:
        """
        Return query to check if upstream data is available for circuit breaker auto-reset.

        This processor depends on nba_raw.nbac_gamebook_player_stats for backfill mode.
        When the circuit breaker trips (due to missing gamebook data), this query
        checks if the data has since become available, allowing auto-reset.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            SQL query that returns a row with 'cnt' column (> 0 if data available)
        """
        return f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """
        # FIXED: Removed unreachable code (moved to __init__ above)

    # ============================================================
    # Pattern #3: Smart Reprocessing - Data Hash Fields
    # ============================================================
    # Fields included in data_hash calculation (meaningful analytics output only)
    # EXCLUDES: metadata (created_at, processed_at, etc.), source tracking, data quality
    HASH_FIELDS = [
        # Core identifiers
        'player_lookup',
        'universal_player_id',
        'game_id',
        'game_date',
        'team_abbr',
        'opponent_team_abbr',
        'has_prop_line',

        # Player prop betting context
        'current_points_line',
        'opening_points_line',
        'line_movement',
        'current_points_line_source',
        'opening_points_line_source',

        # Game spread context
        'game_spread',
        'opening_spread',
        'spread_movement',
        'game_spread_source',
        'spread_public_betting_pct',

        # Game total context
        'game_total',
        'opening_total',
        'total_movement',
        'game_total_source',
        'total_public_betting_pct',

        # Pre-game context
        'pace_differential',
        'opponent_pace_last_10',
        'game_start_time_local',
        'opponent_ft_rate_allowed',
        'home_game',
        'back_to_back',
        'season_phase',
        'projected_usage_rate',

        # Player fatigue analysis
        'days_rest',
        'days_rest_before_last_game',
        'days_since_2_plus_days_rest',
        'games_in_last_7_days',
        'games_in_last_14_days',
        'minutes_in_last_7_days',
        'minutes_in_last_14_days',
        'avg_minutes_per_game_last_7',
        'back_to_backs_last_14_days',
        'avg_usage_rate_last_7_games',
        'fourth_quarter_minutes_last_7',
        'clutch_minutes_last_7_games',

        # Travel context
        'travel_miles',
        'time_zone_changes',
        'consecutive_road_games',
        'miles_traveled_last_14_days',
        'time_zones_crossed_last_14_days',

        # Player characteristics
        'player_age',

        # Recent performance context
        'points_avg_last_5',
        'points_avg_last_10',
        'prop_over_streak',
        'prop_under_streak',
        'star_teammates_out',
        'opponent_def_rating_last_10',
        'shooting_pct_decline_last_5',
        'fourth_quarter_production_last_7',

        # Forward-looking schedule context
        'next_game_days_rest',
        'games_in_next_7_days',
        'next_opponent_win_pct',
        'next_game_is_primetime',

        # Opponent asymmetry context
        'opponent_days_rest',
        'opponent_games_in_next_7_days',
        'opponent_next_game_days_rest',

        # Real-time updates
        'player_status',
        'injury_report',
        'questionable_teammates',
        'probable_teammates',

        # Completeness metrics
        'expected_games_count',
        'actual_games_count',
        'completeness_percentage',
        'missing_games_count',
        'is_production_ready',
        'manual_override_required',
        'season_boundary_detected',
        'backfill_bootstrap_mode',
        'processing_decision_reason',

        # Multi-window completeness
        'l5_completeness_pct',
        'l5_is_complete',
        'l10_completeness_pct',
        'l10_is_complete',
        'l7d_completeness_pct',
        'l7d_is_complete',
        'l14d_completeness_pct',
        'l14d_is_complete',
        'l30d_completeness_pct',
        'l30d_is_complete',
        'all_windows_complete',

        # Update tracking (context_version only - not timestamps)
        'context_version',
    ]
    # Total: 102 fields
    # EXCLUDED: created_at, processed_at, updated_at, source_* fields (16 fields),
    #           data_quality_tier, primary_source_used, processed_with_issues,
    #           data_quality_issues, circuit_breaker fields, data_hash itself

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Player prop sources - RELEVANT (DRIVER - determines which players to process)
        'odds_api_player_points_props': True,
        'bettingpros_player_points_props': True,
        'odds_api_player_rebounds_props': True,
        'odds_api_player_assists_props': True,

        # Player boxscore sources - RELEVANT (historical performance)
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,
        'nbac_player_boxscores': True,

        # Schedule sources - RELEVANT (game timing, rest days)
        'nbacom_schedule': True,
        'espn_scoreboard': True,

        # Game odds sources - RELEVANT (spreads, totals)
        'odds_api_game_lines': True,
        'odds_api_spreads': True,
        'odds_api_totals': True,

        # Injury/roster sources - RELEVANT (player status)
        'nbac_injury_report': True,
        'nbacom_roster': True,
        'espn_team_rosters': True,

        # Team-level stats - NOT RELEVANT (not needed for individual player context)
        'nbac_team_boxscore': False,
        'bdl_team_boxscores': False,
        'espn_team_stats': False,

        # Play-by-play sources - NOT RELEVANT (not needed for pre-game context)
        'bigdataball_play_by_play': False,
        'nbac_play_by_play': False
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = True       # Skip if no games scheduled
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - this is for UPCOMING games (future dates)

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    # ============================================================
    # Soft Dependency Configuration (added after Jan 23 incident)
    # ============================================================
    # When enabled, processor can proceed with degraded upstream data if coverage > threshold
    # This prevents all-or-nothing blocking when upstream processors have partial failures
    use_soft_dependencies = True
    soft_dependency_threshold = 0.80  # Proceed if >80% upstream coverage

    def get_dependencies(self) -> dict:
        """
        Define Phase 2 raw table dependencies.
        
        Note: Phase 3 analytics processors track raw sources but don't use
        the full dependency checking framework (that's for Phase 4 precompute).
        This method documents our Phase 2 sources for reference.
        """
        return {
            'nba_raw.odds_api_player_points_props': {
                'field_prefix': 'source_props',
                'description': 'Player prop bets (optional - fallback to all-player mode without)',
                'critical': False,  # Not critical - processor works without props (all-player mode)
                'check_type': 'date_match'
            },
            'nba_raw.bdl_player_boxscores': {
                'field_prefix': 'source_boxscore',
                'description': 'Historical player performance (last 30 days)',
                'critical': True,
                'check_type': 'lookback_days',
                'lookback_days': 30
            },
            'nba_raw.nbac_schedule': {
                'field_prefix': 'source_schedule',
                'description': 'Game schedule and timing',
                'critical': True,
                'check_type': 'date_match'
            },
            'nba_raw.odds_api_game_lines': {
                'field_prefix': 'source_game_lines',
                'description': 'Game spreads and totals (optional - can predict without)',
                'critical': False,  # Not critical - processor works without game lines
                'check_type': 'date_match'
            }
        }
    
    def process_date(self, target_date: date, **kwargs) -> Dict:
        """
        Process all players with props for a specific date.
        
        Args:
            target_date: Date to process (game date)
            
        Returns:
            Dict with processing results
        """
        self.target_date = target_date
        logger.info(f"Processing upcoming player game context for {target_date}")
        
        try:
            # Step 1: Extract data from Phase 2 sources
            self.extract_raw_data()
            
            # Step 2: Calculate context for each player
            self.calculate_analytics()
            
            # Step 3: Save to BigQuery
            success = self.save_analytics()
            
            # Log results
            logger.info(f"Successfully processed {len(self.transformed_data)} players")
            if self.failed_entities:
                logger.warning(f"Failed to process {len(self.failed_entities)} players")

            # Calculate prop coverage and send alert if critically low (2026-01-09 timing fix)
            total_players = len(self.transformed_data)
            players_with_props = sum(
                1 for p in self.transformed_data if p.get('has_prop_line', False)
            )
            prop_pct = (players_with_props / total_players * 100) if total_players > 0 else 0

            logger.info(f"Prop coverage: {players_with_props}/{total_players} ({prop_pct:.1f}%)")

            # Alert on 0% or very low (<10%) prop coverage when we have significant players
            if total_players >= 50 and prop_pct < 10:
                self._send_prop_coverage_alert(target_date, total_players, players_with_props, prop_pct)

            return {
                'status': 'success' if success else 'failed',
                'date': target_date.isoformat(),
                'players_processed': len(self.transformed_data),
                'players_failed': len(self.failed_entities),
                'players_with_props': players_with_props,
                'prop_coverage_pct': round(prop_pct, 1),
                'errors': [e['reason'] for e in self.failed_entities]
            }
            
        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error processing date {target_date}: {e}", exc_info=True)
            return {
                'status': 'error',
                'date': target_date.isoformat(),
                'error': str(e),
                'players_processed': 0,
                'players_failed': 0  # FIX: Include this field for consistency
            }
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.error(f"Data error processing date {target_date}: {e}", exc_info=True)
            return {
                'status': 'error',
                'date': target_date.isoformat(),
                'error': str(e),
                'players_processed': 0,
                'players_failed': 0  # FIX: Include this field for consistency
            }
    
    def extract_raw_data(self) -> None:
        """
        Extract data from all Phase 2 raw sources.

        Order of operations:
        1. Get players with props (DRIVER)
        2. Get schedule data
        3. Get historical boxscores
        4. Get prop lines (opening + current)
        5. Get game lines (spreads + totals)
        6. Get optional data (rosters, injuries, registry)

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """
        # Set target_date from opts if not already set (for run() vs process_date() compatibility)
        if self.target_date is None:
            end_date = self.opts.get('end_date')
            if isinstance(end_date, str):
                self.target_date = date.fromisoformat(end_date)
            elif isinstance(end_date, date):
                self.target_date = end_date
            else:
                raise ValueError("target_date not set and no valid end_date in opts")

        logger.info(f"Extracting raw data for {self.target_date}")

        # Store season start date for completeness checking (Week 5)
        season_year = self.target_date.year if self.target_date.month >= 10 else self.target_date.year - 1
        self.season_start_date = date(season_year, 10, 1)

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(self.target_date)
        if skip:
            logger.info(f"✅ SMART REPROCESSING: Skipping processing - {reason}")
            self.players_to_process = []
            return

        logger.info(f"🔄 PROCESSING: {reason}")

        # PRE-FLIGHT CHECK: Verify props are available (2026-01-09 timing fix)
        # This prevents 0% prop coverage issues when UPGC runs before props are scraped
        props_check = self._check_props_readiness(self.target_date)
        if not props_check['ready']:
            logger.warning(f"⚠️ PROPS PRE-FLIGHT: {props_check['message']}")
            # Don't fail - continue processing but log warning
            # The 0% coverage alert at the end will catch actual problems
        else:
            logger.info(f"✅ PROPS PRE-FLIGHT: {props_check['message']}")

        # Step 1: Get ALL players with games (DRIVER)
        # Changed in v3.2: Now gets all players, not just those with props
        self._extract_players_with_props()

        if not self.players_to_process:
            logger.warning(f"No players with games found for {self.target_date}")
            return

        logger.info(f"Found {len(self.players_to_process)} players with games")
        
        # Step 2: Get schedule data
        self._extract_schedule_data()
        
        # Step 3: Get historical boxscores
        self._extract_historical_boxscores()
        
        # Step 4: Get prop lines
        self._extract_prop_lines()
        
        # Step 5: Get game lines
        self._extract_game_lines()
        
        # Step 6: Get optional data
        self._extract_rosters()
        self._extract_injuries()
        self._extract_registry()

        # Step 7: Get standings data (for opponent win percentage)
        self._extract_standings_data()

        logger.info("Data extraction complete")

    def validate_extracted_data(self) -> None:
        """
        Override base class validation to check players_to_process instead of raw_data.

        This processor uses self.players_to_process as the main data structure,
        not self.raw_data which the base class checks.
        """
        if not self.players_to_process:
            logger.warning(f"No players to process for {self.target_date}")
            raise ValueError("No data extracted")

        logger.info(f"Validation passed: {len(self.players_to_process)} players to process")

    def _determine_processing_mode(self) -> str:
        """
        Determine whether to use daily or backfill processing mode.

        ISSUE 1 FIX: The processor needs different driver queries for:
        - DAILY mode: Use schedule + roster (pre-game data available)
        - BACKFILL mode: Use gamebook (post-game actual players)

        Detection logic:
        1. Check PROCESSING_MODE environment variable (explicit override only)
        2. Check if gamebook has data for target date
        3. If gamebook empty and date is today/future, use daily mode
        4. Otherwise use backfill mode

        Returns:
            'daily' or 'backfill'
        """
        # Check environment variable first (explicit override only)
        # Only use this if PROCESSING_MODE is explicitly set, not the config default
        env_processing_mode = os.environ.get('PROCESSING_MODE')
        if env_processing_mode in ('daily', 'backfill'):
            logger.info(f"Processing mode from env var override: {env_processing_mode}")
            return env_processing_mode

        # Auto-detect based on gamebook data availability
        gamebook_check_query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = @game_date
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
            ]
        )

        try:
            result = self.bq_client.query(gamebook_check_query, job_config=job_config).result(timeout=60)
            row = next(result, None)
            gamebook_count = row.cnt if row else 0

            # If gamebook has data, use backfill mode (post-game data exists)
            if gamebook_count > 0:
                logger.info(f"Gamebook has {gamebook_count} records for {self.target_date} - using BACKFILL mode")
                return 'backfill'

            # If gamebook empty, check if date is today or future
            today = date.today()
            if self.target_date >= today:
                logger.info(f"No gamebook data and date is {self.target_date} (today={today}) - using DAILY mode")
                return 'daily'
            else:
                # Historical date with no gamebook - might be a gap, try daily
                logger.warning(f"No gamebook data for historical date {self.target_date} - trying DAILY mode")
                return 'daily'

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error checking gamebook availability: {e} - defaulting to DAILY mode")
            return 'daily'
        except (KeyError, AttributeError) as e:
            logger.warning(f"Data error checking gamebook availability: {e} - defaulting to DAILY mode")
            return 'daily'

    def _extract_players_with_props(self) -> None:
        """
        Extract ALL players who have games scheduled for target date.

        This is the DRIVER query - determines which players to process.

        ISSUE 1 FIX (v3.3):
        - Detects processing mode (daily vs backfill)
        - DAILY mode: Uses schedule + roster (pre-game data)
        - BACKFILL mode: Uses gamebook (post-game actual players)

        This fixes the critical issue where daily predictions couldn't work
        because gamebook data doesn't exist until AFTER games finish.
        """
        # Determine processing mode
        processing_mode = self._determine_processing_mode()
        self._processing_mode = processing_mode  # Store for later reference

        if processing_mode == 'daily':
            self._extract_players_daily_mode()
        else:
            self._extract_players_backfill_mode()

    def _extract_players_daily_mode(self) -> None:
        """
        Extract players using DAILY mode (pre-game data).

        Uses schedule + roster to get players who will play today.
        LEFT JOINs with injury report for player status.
        LEFT JOINs with props for has_prop_line flag.

        This is the FIX for Issue 1 - daily predictions now work because
        we don't depend on gamebook (which only exists post-game).
        """
        self._props_source = 'roster'  # Track source used

        # Calculate roster date range for partition filtering
        # We use a wider window (90 days) to handle cases where roster scraping may be behind
        # The query will find the latest roster within this range
        roster_start = (self.target_date - timedelta(days=90)).isoformat()
        roster_end = self.target_date.isoformat()

        logger.info(f"Looking for roster data between {roster_start} and {roster_end}")

        # DAILY MODE: Schedule + Roster + Injury
        # Using date range for partition elimination
        daily_query = f"""
        WITH games_today AS (
            -- Get all games scheduled for target date
            -- FIXED: Use standard game_id format (YYYYMMDD_AWAY_HOME) instead of NBA official ID
            SELECT
                CONCAT(
                    FORMAT_DATE('%Y%m%d', game_date),
                    '_',
                    away_team_tricode,
                    '_',
                    home_team_tricode
                ) as game_id,
                game_date,
                home_team_tricode as home_team_abbr,
                away_team_tricode as away_team_abbr
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = @game_date
        ),
        teams_playing AS (
            -- Get all teams playing today (both home and away)
            SELECT DISTINCT home_team_abbr as team_abbr FROM games_today
            UNION DISTINCT
            SELECT DISTINCT away_team_abbr as team_abbr FROM games_today
        ),
        latest_roster_per_team AS (
            -- Find the most recent roster PER TEAM within partition range
            -- FIX: Previous query found global MAX, but different teams may have different latest dates
            SELECT team_abbr, MAX(roster_date) as roster_date
            FROM `{self.project_id}.nba_raw.espn_team_rosters`
            WHERE roster_date >= @roster_start
              AND roster_date <= @roster_end
            GROUP BY team_abbr
        ),
        roster_players AS (
            -- Get all players from rosters of teams playing today
            -- Using date range for partition elimination, then filter to latest per team
            SELECT DISTINCT
                r.player_lookup,
                r.team_abbr
            FROM `{self.project_id}.nba_raw.espn_team_rosters` r
            INNER JOIN latest_roster_per_team lr
                ON r.team_abbr = lr.team_abbr
                AND r.roster_date = lr.roster_date
            WHERE r.roster_date >= @roster_start
              AND r.roster_date <= @roster_end
              AND r.team_abbr IN (SELECT team_abbr FROM teams_playing)
              AND r.player_lookup IS NOT NULL
        ),
        players_with_games AS (
            -- Join roster players with their game info
            SELECT DISTINCT
                rp.player_lookup,
                g.game_id,
                rp.team_abbr,
                g.home_team_abbr,
                g.away_team_abbr
            FROM roster_players rp
            INNER JOIN games_today g
                ON rp.team_abbr = g.home_team_abbr
                OR rp.team_abbr = g.away_team_abbr
        ),
        injuries AS (
            -- Get latest injury report for target date
            SELECT DISTINCT
                player_lookup,
                injury_status
            FROM `{self.project_id}.nba_raw.nbac_injury_report`
            WHERE report_date = @game_date
              AND player_lookup IS NOT NULL
        ),
        props AS (
            -- Check which players have prop lines (from either source)
            SELECT DISTINCT
                player_lookup,
                points_line,
                'odds_api' as prop_source
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
              AND player_lookup IS NOT NULL
            UNION DISTINCT
            SELECT DISTINCT
                player_lookup,
                points_line,
                'bettingpros' as prop_source
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = @game_date
              AND is_active = TRUE
              AND player_lookup IS NOT NULL
        )
        SELECT
            p.player_lookup,
            p.game_id,
            p.team_abbr,
            p.home_team_abbr,
            p.away_team_abbr,
            i.injury_status,
            pr.points_line,
            pr.prop_source,
            CASE WHEN pr.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
        FROM players_with_games p
        LEFT JOIN injuries i ON p.player_lookup = i.player_lookup
        LEFT JOIN props pr ON p.player_lookup = pr.player_lookup
        -- Filter out players marked OUT or DOUBTFUL in injury report
        WHERE i.injury_status IS NULL
           OR i.injury_status NOT IN ('Out', 'OUT', 'Doubtful', 'DOUBTFUL')
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
                bigquery.ScalarQueryParameter("roster_start", "DATE", roster_start),
                bigquery.ScalarQueryParameter("roster_end", "DATE", roster_end),
            ]
        )

        try:
            df = self.bq_client.query(daily_query, job_config=job_config).to_dataframe()

            # Track source usage
            self.source_tracking['props']['rows_found'] = len(df)
            self.source_tracking['props']['last_updated'] = datetime.now(timezone.utc)

            # Store players to process
            players_with_props = 0
            for _, row in df.iterrows():
                has_prop = row.get('has_prop_line', False)
                if has_prop:
                    players_with_props += 1

                self.players_to_process.append({
                    'player_lookup': row['player_lookup'],
                    'game_id': row['game_id'],
                    'team_abbr': row.get('team_abbr'),
                    'home_team_abbr': row['home_team_abbr'],
                    'away_team_abbr': row['away_team_abbr'],
                    'has_prop_line': has_prop,
                    'current_points_line': row.get('points_line'),
                    'prop_source': row.get('prop_source'),
                    'injury_status': row.get('injury_status')  # Include injury info
                })

            # Count unique teams for coverage monitoring
            unique_teams = set(row.get('team_abbr') for row in self.players_to_process if row.get('team_abbr'))
            teams_count = len(unique_teams)

            logger.info(
                f"[DAILY MODE] Found {len(self.players_to_process)} players for {self.target_date} "
                f"({players_with_props} with prop lines, {len(self.players_to_process) - players_with_props} without) "
                f"from {teams_count} teams"
            )

            # MONITORING: Alert if roster coverage is critically low
            # Expected: 10-16 teams per day (5-8 games), alert if < 6 teams
            if teams_count < 6 and len(self.players_to_process) > 0:
                logger.warning(
                    f"⚠️ LOW ROSTER COVERAGE: Only {teams_count} teams found for {self.target_date}. "
                    f"Expected 10-16 teams. Check ESPN roster scraper and schedule data."
                )
                self._send_roster_coverage_alert(self.target_date, teams_count, len(self.players_to_process))

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting players (daily mode): {e}")
            self.source_tracking['props']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting players (daily mode): {e}")
            self.source_tracking['props']['rows_found'] = 0
            raise

    def _extract_players_backfill_mode(self) -> None:
        """
        Extract players using BACKFILL mode (post-game data).

        Uses gamebook to get players who actually played.
        This is the original query - gamebook has actual player data post-game.
        """
        self._props_source = 'gamebook'  # Track source used

        # BACKFILL MODE: Gamebook (post-game actual players)
        backfill_query = f"""
        WITH schedule_data AS (
            -- Get schedule data with partition filter
            -- FIXED: Create standard game_id format (YYYYMMDD_AWAY_HOME)
            SELECT
                game_id as nba_game_id,
                CONCAT(
                    FORMAT_DATE('%Y%m%d', game_date),
                    '_',
                    away_team_tricode,
                    '_',
                    home_team_tricode
                ) as game_id,
                home_team_tricode,
                away_team_tricode
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = @game_date
        ),
        players_with_games AS (
            -- Get ALL active players from gamebook who have games on target date
            SELECT DISTINCT
                g.player_lookup,
                s.game_id,  -- Use standard game_id from schedule
                g.team_abbr,
                g.player_status,
                -- Get home/away from schedule since gamebook may not have it
                COALESCE(s.home_team_tricode, g.team_abbr) as home_team_abbr,
                COALESCE(s.away_team_tricode, g.team_abbr) as away_team_abbr
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats` g
            LEFT JOIN schedule_data s
                ON g.game_id = s.nba_game_id  -- Join on NBA official ID
            WHERE g.game_date = @game_date
              AND g.player_lookup IS NOT NULL
              AND (g.player_status IS NULL OR g.player_status NOT IN ('DNP', 'DND', 'NWT'))
        ),
        props AS (
            -- Check which players have prop lines (from either source)
            SELECT DISTINCT
                player_lookup,
                points_line,
                'odds_api' as prop_source
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
              AND player_lookup IS NOT NULL
            UNION DISTINCT
            SELECT DISTINCT
                player_lookup,
                points_line,
                'bettingpros' as prop_source
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = @game_date
              AND is_active = TRUE
              AND player_lookup IS NOT NULL
        )
        SELECT
            p.player_lookup,
            p.game_id,
            p.team_abbr,
            p.home_team_abbr,
            p.away_team_abbr,
            p.player_status,
            pr.points_line,
            pr.prop_source,
            CASE WHEN pr.player_lookup IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
        FROM players_with_games p
        LEFT JOIN props pr ON p.player_lookup = pr.player_lookup
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(backfill_query, job_config=job_config).to_dataframe()

            # Track source usage
            self.source_tracking['props']['rows_found'] = len(df)
            self.source_tracking['props']['last_updated'] = datetime.now(timezone.utc)

            # Store players to process (now ALL players, not just those with props)
            players_with_props = 0
            for _, row in df.iterrows():
                has_prop = row.get('has_prop_line', False)
                if has_prop:
                    players_with_props += 1

                self.players_to_process.append({
                    'player_lookup': row['player_lookup'],
                    'game_id': row['game_id'],
                    'team_abbr': row.get('team_abbr'),
                    'home_team_abbr': row['home_team_abbr'],
                    'away_team_abbr': row['away_team_abbr'],
                    'has_prop_line': has_prop,
                    'current_points_line': row.get('points_line'),
                    'prop_source': row.get('prop_source'),
                    'injury_status': row.get('player_status')  # From gamebook
                })

            logger.info(
                f"[BACKFILL MODE] Found {len(self.players_to_process)} players for {self.target_date} "
                f"({players_with_props} with prop lines, {len(self.players_to_process) - players_with_props} without)"
            )

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting players (backfill mode): {e}")
            self.source_tracking['props']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting players (backfill mode): {e}")
            self.source_tracking['props']['rows_found'] = 0
            raise

    def _extract_players_from_bettingpros(self) -> pd.DataFrame:
        """
        Extract players from BettingPros as fallback when Odds API has no data.

        BettingPros doesn't have game_id, so we join with schedule to get it.
        Returns DataFrame with same columns as Odds API query.
        """
        # Query BettingPros and join with schedule to get game_id
        bettingpros_query = f"""
        WITH bp_props AS (
            SELECT DISTINCT
                bp.player_lookup,
                bp.game_date,
                -- Use validated_team if available, otherwise player_team
                COALESCE(bp.validated_team, bp.player_team) as player_team
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props` bp
            WHERE bp.game_date = @game_date
              AND bp.player_lookup IS NOT NULL
              AND bp.is_active = TRUE
        ),
        schedule AS (
            -- FIXED: Use standard game_id format (YYYYMMDD_AWAY_HOME)
            SELECT
                CONCAT(
                    FORMAT_DATE('%Y%m%d', game_date),
                    '_',
                    away_team_tricode,
                    '_',
                    home_team_tricode
                ) as game_id,
                game_date,
                home_team_tricode as home_team_abbr,
                away_team_tricode as away_team_abbr
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = @game_date
        )
        SELECT DISTINCT
            bp.player_lookup,
            s.game_id,
            bp.game_date,
            s.home_team_abbr,
            s.away_team_abbr
        FROM bp_props bp
        INNER JOIN schedule s
            ON bp.game_date = s.game_date
            AND (bp.player_team = s.home_team_abbr OR bp.player_team = s.away_team_abbr)
        WHERE s.game_id IS NOT NULL
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(bettingpros_query, job_config=job_config).to_dataframe()
            logger.info(f"BettingPros fallback: Found {len(df)} players for {self.target_date}")
            return df
        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting from BettingPros: {e}")
            return pd.DataFrame()
        except (KeyError, AttributeError) as e:
            logger.error(f"Data error extracting from BettingPros: {e}")
            return pd.DataFrame()
    
    def _extract_schedule_data(self) -> None:
        """
        Extract schedule data for all games on target date.
        
        Used for:
        - Determining home/away
        - Game start times
        - Back-to-back detection (requires looking at surrounding dates)
        """
        game_ids = list(set([p['game_id'] for p in self.players_to_process if p.get('game_id')]))
        game_ids_str = "', '".join(game_ids)
        
        # Get schedule for target date plus surrounding dates for back-to-back detection
        start_date = self.target_date - timedelta(days=5)
        end_date = self.target_date + timedelta(days=5)
        
        # FIXED: Use standard game_id format (YYYYMMDD_AWAY_HOME) instead of NBA official ID
        query = f"""
        SELECT
            CONCAT(
                FORMAT_DATE('%Y%m%d', game_date),
                '_',
                away_team_tricode,
                '_',
                home_team_tricode
            ) as game_id,
            game_date,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_date_est,
            is_primetime,
            season_year
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= @start_date
          AND game_date <= @end_date
        ORDER BY game_date, game_date_est
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            # Track source usage (count only target date games)
            # FIX: use timezone-aware datetime
            target_games = df[df['game_date'] == self.target_date]
            self.source_tracking['schedule']['rows_found'] = len(target_games)
            self.source_tracking['schedule']['last_updated'] = datetime.now(timezone.utc)
            
            # Use NBATeamMapper for comprehensive abbreviation handling
            team_mapper = get_nba_team_mapper()

            def get_all_abbr_variants(abbr: str) -> list:
                """Return all known abbreviation variants for a team using NBATeamMapper."""
                team_info = get_team_info(abbr)
                if team_info:
                    # Return all tricode variants (nba, br, espn)
                    variants = list(set([
                        team_info.nba_tricode,
                        team_info.br_tricode,
                        team_info.espn_tricode
                    ]))
                    return variants
                # Fallback: just return the original
                return [abbr]

            # Store schedule data by game_id
            # ALSO create lookups using date-based format (YYYYMMDD_AWAY_HOME) to match props table
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                # Store with official NBA game_id
                self.schedule_data[row['game_id']] = row_dict

                # Create all variant game_id keys to handle inconsistent abbreviations
                game_date_str = str(row['game_date']).replace('-', '')
                away_variants = get_all_abbr_variants(row['away_team_abbr'])
                home_variants = get_all_abbr_variants(row['home_team_abbr'])

                # Store all combinations of away/home abbreviation variants
                for away_abbr in away_variants:
                    for home_abbr in home_variants:
                        date_based_id = f"{game_date_str}_{away_abbr}_{home_abbr}"
                        self.schedule_data[date_based_id] = row_dict

            logger.info(f"Extracted schedule for {len(target_games)} games on {self.target_date}")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting schedule data: {e}")
            self.source_tracking['schedule']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting schedule data: {e}")
            self.source_tracking['schedule']['rows_found'] = 0
            raise
    
    def _extract_historical_boxscores(self) -> None:
        """
        Extract historical boxscores for all players (last 30 days).
        
        Priority:
        1. nba_raw.bdl_player_boxscores (PRIMARY)
        2. nba_raw.nbac_player_boxscores (fallback)
        3. nba_raw.nbac_gamebook_player_stats (last resort)
        """
        player_lookups = [p['player_lookup'] for p in self.players_to_process]

        start_date = self.target_date - timedelta(days=self.lookback_days)

        # Try BDL first (PRIMARY)
        query = f"""
        SELECT
            player_lookup,
            game_date,
            team_abbr,
            points,
            minutes,
            assists,
            rebounds,
            field_goals_made,
            field_goals_attempted,
            three_pointers_made,
            three_pointers_attempted,
            free_throws_made,
            free_throws_attempted
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE player_lookup IN UNNEST(@player_lookups)
          AND game_date >= @start_date
          AND game_date < @target_date
        ORDER BY player_lookup, game_date DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            # Convert minutes string to decimal
            if 'minutes' in df.columns:
                df['minutes_decimal'] = df['minutes'].apply(self._parse_minutes)
            else:
                df['minutes_decimal'] = 0.0
            
            # Track source usage (FIX: use timezone-aware datetime)
            self.source_tracking['boxscore']['rows_found'] = len(df)
            self.source_tracking['boxscore']['last_updated'] = datetime.now(timezone.utc)
            
            # FIX: Handle empty DataFrame properly to avoid KeyError
            # Store by player_lookup
            for player_lookup in player_lookups:
                if df.empty or 'player_lookup' not in df.columns:
                    # No data available - store empty DataFrame
                    self.historical_boxscores[player_lookup] = pd.DataFrame()
                else:
                    player_data = df[df['player_lookup'] == player_lookup].copy()
                    self.historical_boxscores[player_lookup] = player_data
            
            logger.info(f"Extracted {len(df)} historical boxscore records for {len(player_lookups)} players")

            # Check for players with insufficient data and try fallback sources
            players_needing_fallback = [
                p for p in player_lookups
                if self.historical_boxscores.get(p, pd.DataFrame()).empty
                or len(self.historical_boxscores.get(p, pd.DataFrame())) < 5
            ]

            if players_needing_fallback:
                logger.info(f"Attempting fallback for {len(players_needing_fallback)} players with insufficient BDL data")
                self._extract_boxscores_fallback(players_needing_fallback, start_date)

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise

    def _extract_boxscores_fallback(self, player_lookups: List[str], start_date: date) -> None:
        """
        Fallback boxscore extraction using nbac_gamebook_player_stats.

        Called when BDL data is insufficient for some players (e.g., rookies,
        recently traded players, or gaps in BDL coverage).

        Args:
            player_lookups: List of player lookups needing fallback data
            start_date: Start date for lookback window
        """
        if not player_lookups:
            return

        # Query nbac_gamebook_player_stats as fallback
        query = f"""
        SELECT
            player_lookup,
            game_date,
            team_abbr,
            points,
            minutes,
            assists,
            total_rebounds as rebounds,
            field_goals_made,
            field_goals_attempted,
            three_pt_made as three_pointers_made,
            three_pt_attempted as three_pointers_attempted,
            ft_made as free_throws_made,
            ft_attempted as free_throws_attempted
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE player_lookup IN UNNEST(@player_lookups)
          AND game_date >= @start_date
          AND game_date < @target_date
          AND player_status = 'active'
        ORDER BY player_lookup, game_date DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if df.empty:
                logger.info("No fallback boxscore data found in nbac_gamebook_player_stats")
                return

            # Convert minutes string to decimal
            if 'minutes' in df.columns:
                df['minutes_decimal'] = df['minutes'].apply(self._parse_minutes)
            else:
                df['minutes_decimal'] = 0.0

            # Merge with existing data or replace if empty
            fallback_count = 0
            for player_lookup in player_lookups:
                existing_data = self.historical_boxscores.get(player_lookup, pd.DataFrame())
                player_fallback = df[df['player_lookup'] == player_lookup].copy()

                if player_fallback.empty:
                    continue

                if existing_data.empty:
                    # No BDL data - use fallback entirely
                    self.historical_boxscores[player_lookup] = player_fallback
                    fallback_count += 1
                else:
                    # Merge: keep BDL data and add missing games from fallback
                    existing_dates = set(existing_data['game_date'].tolist())
                    new_games = player_fallback[~player_fallback['game_date'].isin(existing_dates)]
                    if not new_games.empty:
                        merged = pd.concat([existing_data, new_games]).sort_values(
                            'game_date', ascending=False
                        )
                        self.historical_boxscores[player_lookup] = merged
                        fallback_count += 1

            if fallback_count > 0:
                logger.info(f"Enhanced boxscore data for {fallback_count} players using nbac_gamebook_player_stats fallback")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error in boxscore fallback: {e}. Continuing with available data.")
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error in boxscore fallback: {e}. Continuing with available data.")

    def _extract_prop_lines(self) -> None:
        """
        Extract prop lines (opening and current) for each player.

        Opening line: Earliest snapshot
        Current line: Most recent snapshot

        FALLBACK LOGIC (v3.1):
        - Uses same source as driver query (self._props_source)
        - Odds API has snapshot_timestamp for line history
        - BettingPros has opening_line field and bookmaker_last_update
        """
        player_game_pairs = [(p['player_lookup'], p['game_id']) for p in self.players_to_process]

        # Use the same source as the driver query
        use_bettingpros = getattr(self, '_props_source', 'odds_api') == 'bettingpros'

        if use_bettingpros:
            logger.info(f"Extracting prop lines from BettingPros for {len(player_game_pairs)} players")
            self._extract_prop_lines_from_bettingpros(player_game_pairs)
        else:
            logger.info(f"Extracting prop lines from Odds API for {len(player_game_pairs)} players")
            self._extract_prop_lines_from_odds_api(player_game_pairs)

    def _extract_prop_lines_from_odds_api(self, player_game_pairs: List[Tuple[str, str]]) -> None:
        """Extract prop lines from Odds API using batch query for efficiency."""
        # Build batch query - get opening and current lines for all players in one query
        player_lookups = list(set([p[0] for p in player_game_pairs]))

        batch_query = f"""
        WITH opening_lines AS (
            SELECT
                player_lookup,
                game_id,
                points_line as opening_line,
                bookmaker as opening_source,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id
                    ORDER BY snapshot_timestamp ASC
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @game_date
        ),
        current_lines AS (
            SELECT
                player_lookup,
                game_id,
                points_line as current_line,
                bookmaker as current_source,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_id
                    ORDER BY snapshot_timestamp DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @game_date
        )
        SELECT
            COALESCE(o.player_lookup, c.player_lookup) as player_lookup,
            COALESCE(o.game_id, c.game_id) as game_id,
            o.opening_line,
            o.opening_source,
            c.current_line,
            c.current_source
        FROM opening_lines o
        FULL OUTER JOIN current_lines c
            ON o.player_lookup = c.player_lookup AND o.game_id = c.game_id
        WHERE (o.rn = 1 OR o.rn IS NULL) AND (c.rn = 1 OR c.rn IS NULL)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(batch_query, job_config=job_config).to_dataframe()
            logger.info(f"Odds API batch query returned {len(df)} prop line records")

            # Create lookup dict keyed by (player_lookup, game_id)
            props_lookup = {}
            for _, row in df.iterrows():
                key = (row['player_lookup'], row['game_id'])
                props_lookup[key] = {
                    'opening_line': row['opening_line'],
                    'opening_source': row['opening_source'],
                    'current_line': row['current_line'],
                    'current_source': row['current_source'],
                }

            # Populate prop_lines for each player_game pair
            for player_lookup, game_id in player_game_pairs:
                props = props_lookup.get((player_lookup, game_id), {})

                prop_info = {
                    'opening_line': props.get('opening_line'),
                    'opening_source': props.get('opening_source'),
                    'current_line': props.get('current_line'),
                    'current_source': props.get('current_source'),
                    'line_movement': None
                }

                if prop_info['opening_line'] and prop_info['current_line']:
                    prop_info['line_movement'] = prop_info['current_line'] - prop_info['opening_line']

                self.prop_lines[(player_lookup, game_id)] = prop_info

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error in batch prop lines query: {e}")
            # Fallback: set empty prop info for all players
            for player_lookup, game_id in player_game_pairs:
                self.prop_lines[(player_lookup, game_id)] = {
                    'opening_line': None,
                    'opening_source': None,
                    'current_line': None,
                    'current_source': None,
                    'line_movement': None
                }
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error in batch prop lines query: {e}")
            # Fallback: set empty prop info for all players
            for player_lookup, game_id in player_game_pairs:
                self.prop_lines[(player_lookup, game_id)] = {
                    'opening_line': None,
                    'opening_source': None,
                    'current_line': None,
                    'current_source': None,
                    'line_movement': None
                }

    def _extract_prop_lines_from_bettingpros(self, player_game_pairs: List[Tuple[str, str]]) -> None:
        """
        Extract prop lines from BettingPros as fallback.

        BettingPros has:
        - opening_line: The opening line value
        - points_line: The current line value
        - bookmaker: The bookmaker name
        - bookmaker_last_update: Timestamp of last update
        """
        # Batch query for efficiency - get all players at once
        player_lookups = list(set([p[0] for p in player_game_pairs]))

        batch_query = f"""
        WITH best_lines AS (
            SELECT
                player_lookup,
                points_line as current_line,
                opening_line,
                bookmaker,
                bookmaker_last_update,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY is_best_line DESC, bookmaker_last_update DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @game_date
              AND is_active = TRUE
        )
        SELECT
            player_lookup,
            current_line,
            opening_line,
            bookmaker
        FROM best_lines
        WHERE rn = 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(batch_query, job_config=job_config).to_dataframe()

            # Create lookup dict
            bp_props = {}
            for _, row in df.iterrows():
                bp_props[row['player_lookup']] = {
                    'current_line': row['current_line'],
                    'opening_line': row['opening_line'],
                    'bookmaker': row['bookmaker']
                }

            # Populate prop_lines for each player_game pair
            for player_lookup, game_id in player_game_pairs:
                bp_data = bp_props.get(player_lookup, {})

                opening_line = bp_data.get('opening_line')
                current_line = bp_data.get('current_line')
                bookmaker = bp_data.get('bookmaker')

                prop_info = {
                    'opening_line': opening_line,
                    'opening_source': bookmaker,
                    'current_line': current_line,
                    'current_source': bookmaker,
                    'line_movement': None
                }

                # Calculate line movement if both lines available
                if opening_line is not None and current_line is not None:
                    prop_info['line_movement'] = current_line - opening_line

                self.prop_lines[(player_lookup, game_id)] = prop_info

            logger.info(f"BettingPros: Extracted prop lines for {len(bp_props)} players")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting prop lines from BettingPros: {e}")
            # Fallback: set empty prop info for all players
            for player_lookup, game_id in player_game_pairs:
                self.prop_lines[(player_lookup, game_id)] = {
                    'opening_line': None,
                    'opening_source': None,
                    'current_line': None,
                    'current_source': None,
                    'line_movement': None
                }
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting prop lines from BettingPros: {e}")
            # Fallback: set empty prop info for all players
            for player_lookup, game_id in player_game_pairs:
                self.prop_lines[(player_lookup, game_id)] = {
                    'opening_line': None,
                    'opening_source': None,
                    'current_line': None,
                    'current_source': None,
                    'line_movement': None
                }
    
    def _extract_game_lines(self) -> None:
        """
        Extract game lines (spreads and totals) for each game.
        
        Uses consensus (median) across all bookmakers.
        Opening: Earliest snapshot
        Current: Most recent snapshot
        """
        game_ids = list(set([p['game_id'] for p in self.players_to_process]))
        
        for game_id in game_ids:
            try:
                # Get spread consensus
                spread_info = self._get_game_line_consensus(game_id, 'spreads')
                
                # Get total consensus
                total_info = self._get_game_line_consensus(game_id, 'totals')
                
                self.game_lines[game_id] = {
                    **spread_info,
                    **total_info
                }
                
                # Track source usage
                self.source_tracking['game_lines']['rows_found'] += 1
                
            except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                logger.warning(f"BigQuery error extracting game lines for {game_id}: {e}")
                self.game_lines[game_id] = {
                    'game_spread': None,
                    'opening_spread': None,
                    'spread_movement': None,
                    'spread_source': None,
                    'game_total': None,
                    'opening_total': None,
                    'total_movement': None,
                    'total_source': None
                }
            except (KeyError, AttributeError, TypeError) as e:
                logger.warning(f"Data error extracting game lines for {game_id}: {e}")
                self.game_lines[game_id] = {
                    'game_spread': None,
                    'opening_spread': None,
                    'spread_movement': None,
                    'spread_source': None,
                    'game_total': None,
                    'opening_total': None,
                    'total_movement': None,
                    'total_source': None
                }
        
        # FIX: use timezone-aware datetime
        self.source_tracking['game_lines']['last_updated'] = datetime.now(timezone.utc)
    
    def _get_game_line_consensus(self, game_id: str, market_key: str) -> Dict:
        """
        Get consensus line (median across bookmakers) for a market.

        Args:
            game_id: Game identifier (standard format: YYYYMMDD_AWAY_HOME)
            market_key: 'spreads' or 'totals'

        Returns:
            Dict with opening, current, movement, and source
        """
        # Extract teams from standard game_id format (YYYYMMDD_AWAY_HOME)
        # Or get from schedule_data if available
        if game_id in self.schedule_data:
            home_team = self.schedule_data[game_id].get('home_team_abbr')
            away_team = self.schedule_data[game_id].get('away_team_abbr')
        else:
            # Parse from game_id: format is YYYYMMDD_AWAY_HOME
            parts = game_id.split('_')
            if len(parts) == 3:
                away_team = parts[1]
                home_team = parts[2]
            else:
                logger.warning(f"Invalid game_id format: {game_id}, cannot extract teams")
                away_team = None
                home_team = None

        # FIXED: Join on game_date + home_team + away_team instead of hash game_id
        # odds_api_game_lines uses hash IDs, not standard game_ids
        opening_query = f"""
        WITH earliest_snapshot AS (
            SELECT MIN(snapshot_timestamp) as earliest
            FROM `{self.project_id}.nba_raw.odds_api_game_lines`
            WHERE game_date = @game_date
              AND home_team_abbr = @home_team
              AND away_team_abbr = @away_team
              AND market_key = @market_key
        ),
        opening_lines AS (
            SELECT
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN earliest_snapshot
            WHERE lines.game_date = @game_date
              AND lines.home_team_abbr = @home_team
              AND lines.away_team_abbr = @away_team
              AND lines.market_key = @market_key
              AND lines.snapshot_timestamp = earliest_snapshot.earliest
        ),
        median_calc AS (
            SELECT PERCENTILE_CONT(outcome_point, 0.5) OVER() as median_line
            FROM opening_lines
            LIMIT 1
        ),
        agg_calc AS (
            SELECT
                STRING_AGG(DISTINCT bookmaker_key) as bookmakers,
                COUNT(DISTINCT bookmaker_key) as bookmaker_count
            FROM opening_lines
        )
        SELECT
            median_calc.median_line,
            agg_calc.bookmakers,
            agg_calc.bookmaker_count
        FROM median_calc
        CROSS JOIN agg_calc
        """

        # Get current line (latest snapshot, median across bookmakers)
        # FIXED: Join on game_date + teams instead of hash game_id
        current_query = f"""
        WITH latest_snapshot AS (
            SELECT MAX(snapshot_timestamp) as latest
            FROM `{self.project_id}.nba_raw.odds_api_game_lines`
            WHERE game_date = @game_date
              AND home_team_abbr = @home_team
              AND away_team_abbr = @away_team
              AND market_key = @market_key
        ),
        current_lines AS (
            SELECT
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN latest_snapshot
            WHERE lines.game_date = @game_date
              AND lines.home_team_abbr = @home_team
              AND lines.away_team_abbr = @away_team
              AND lines.market_key = @market_key
              AND lines.snapshot_timestamp = latest_snapshot.latest
        ),
        median_calc AS (
            SELECT PERCENTILE_CONT(outcome_point, 0.5) OVER() as median_line
            FROM current_lines
            LIMIT 1
        ),
        agg_calc AS (
            SELECT
                STRING_AGG(DISTINCT bookmaker_key) as bookmakers,
                COUNT(DISTINCT bookmaker_key) as bookmaker_count
            FROM current_lines
        )
        SELECT
            median_calc.median_line,
            agg_calc.bookmakers,
            agg_calc.bookmaker_count
        FROM median_calc
        CROSS JOIN agg_calc
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", self.target_date),
                bigquery.ScalarQueryParameter("home_team", "STRING", home_team),
                bigquery.ScalarQueryParameter("away_team", "STRING", away_team),
                bigquery.ScalarQueryParameter("market_key", "STRING", market_key),
            ]
        )

        try:
            opening_df = self.bq_client.query(opening_query, job_config=job_config).to_dataframe()
            current_df = self.bq_client.query(current_query, job_config=job_config).to_dataframe()
            
            prefix = 'spread' if market_key == 'spreads' else 'total'
            
            opening_line = opening_df['median_line'].iloc[0] if not opening_df.empty else None
            current_line = current_df['median_line'].iloc[0] if not current_df.empty else None
            
            result = {
                f'opening_{prefix}': opening_line,
                f'game_{prefix}': current_line,
                f'{prefix}_movement': (current_line - opening_line) if (opening_line and current_line) else None,
                f'{prefix}_source': current_df['bookmakers'].iloc[0] if not current_df.empty else None
            }
            
            return result

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error getting {market_key} consensus for {game_id}: {e}")
            prefix = 'spread' if market_key == 'spreads' else 'total'
            return {
                f'opening_{prefix}': None,
                f'game_{prefix}': None,
                f'{prefix}_movement': None,
                f'{prefix}_source': None
            }
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error getting {market_key} consensus for {game_id}: {e}")
            prefix = 'spread' if market_key == 'spreads' else 'total'
            return {
                f'opening_{prefix}': None,
                f'game_{prefix}': None,
                f'{prefix}_movement': None,
                f'{prefix}_source': None
            }
    

    # ============================================================
    # Public Betting Percentage Extraction (Analytics Features)
    # ============================================================

    def _get_spread_public_betting_pct(self, game_id: str) -> Optional[float]:
        """
        Get the percentage of public bets on the spread favorite.

        This metric indicates where the public is betting on the spread,
        which can be a valuable contrarian indicator when combined with
        line movement data.

        Args:
            game_id: Game identifier (standard format: YYYYMMDD_AWAY_HOME)

        Returns:
            Percentage (0-100) of public bets on the spread favorite,
            or None if data is not available.

        TODO: Implement when public betting data source is available.
        Potential data sources to integrate:
        - ActionNetwork API (requires subscription)
        - BettingPros consensus/public betting data
        - Covers.com public betting percentages
        - VSiN betting splits data

        The implementation would query the data source for the game and
        return the percentage of bets on the spread favorite (the team
        that is favored to cover the spread).
        """
        # TODO: Implement when public betting data source is available
        # Example implementation structure when data is available:
        #
        # if game_id in self.schedule_data:
        #     home_team = self.schedule_data[game_id].get('home_team_abbr')
        #     away_team = self.schedule_data[game_id].get('away_team_abbr')
        # else:
        #     parts = game_id.split('_')
        #     if len(parts) != 3:
        #         return None
        #     away_team, home_team = parts[1], parts[2]
        #
        # query = f"""
        # SELECT public_betting_pct_favorite
        # FROM `{self.project_id}.nba_raw.public_betting_data`
        # WHERE game_date = @game_date
        #   AND home_team_abbr = @home_team
        #   AND away_team_abbr = @away_team
        #   AND market_type = 'spread'
        # ORDER BY snapshot_timestamp DESC
        # LIMIT 1
        # """
        # ... execute query and return result ...

        return None

    def _get_total_public_betting_pct(self, game_id: str) -> Optional[float]:
        """
        Get the percentage of public bets on the OVER for the game total.

        This metric indicates where the public is betting on the over/under,
        which can be a valuable contrarian indicator. High public betting
        on OVER combined with line movement DOWN might indicate sharp action
        on the UNDER.

        Args:
            game_id: Game identifier (standard format: YYYYMMDD_AWAY_HOME)

        Returns:
            Percentage (0-100) of public bets on the OVER,
            or None if data is not available.

        TODO: Implement when public betting data source is available.
        Potential data sources to integrate:
        - ActionNetwork API (requires subscription)
        - BettingPros consensus/public betting data
        - Covers.com public betting percentages
        - VSiN betting splits data

        The implementation would query the data source for the game and
        return the percentage of bets on the OVER (as opposed to UNDER).
        """
        # TODO: Implement when public betting data source is available
        # Example implementation structure when data is available:
        #
        # if game_id in self.schedule_data:
        #     home_team = self.schedule_data[game_id].get('home_team_abbr')
        #     away_team = self.schedule_data[game_id].get('away_team_abbr')
        # else:
        #     parts = game_id.split('_')
        #     if len(parts) != 3:
        #         return None
        #     away_team, home_team = parts[1], parts[2]
        #
        # query = f"""
        # SELECT public_betting_pct_over
        # FROM `{self.project_id}.nba_raw.public_betting_data`
        # WHERE game_date = @game_date
        #   AND home_team_abbr = @home_team
        #   AND away_team_abbr = @away_team
        #   AND market_type = 'totals'
        # ORDER BY snapshot_timestamp DESC
        # LIMIT 1
        # """
        # ... execute query and return result ...

        return None

    def _extract_rosters(self) -> None:
        """
        Extract current roster data including player age.

        Loads the latest roster data from espn_team_rosters for player demographics.
        Stores in self.roster_ages as {player_lookup: age}.
        """
        if not hasattr(self, 'roster_ages'):
            self.roster_ages = {}

        if not self.players_to_process:
            logger.info("No players to lookup roster data for")
            return

        unique_players = list(set(p['player_lookup'] for p in self.players_to_process))
        logger.info(f"Extracting roster data for {len(unique_players)} players")

        # Query for latest roster entry per player with age
        query = f"""
            WITH latest_roster AS (
                SELECT
                    player_lookup,
                    age,
                    birth_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup
                        ORDER BY roster_date DESC, scrape_hour DESC
                    ) as rn
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE roster_date <= @target_date
                  AND player_lookup IN UNNEST(@player_lookups)
            )
            SELECT player_lookup, age, birth_date
            FROM latest_roster
            WHERE rn = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date),
                bigquery.ArrayQueryParameter("player_lookups", "STRING", unique_players),
            ]
        )

        try:
            results = self.bq_client.query(query, job_config=job_config).result()

            for row in results:
                player_lookup = row.player_lookup
                age = row.age

                # If age is None but birth_date exists, calculate age
                if age is None and row.birth_date:
                    try:
                        from datetime import date
                        birth = row.birth_date
                        if isinstance(birth, str):
                            birth = date.fromisoformat(birth)
                        age = (self.target_date - birth).days // 365
                    except (ValueError, TypeError, AttributeError):
                        pass

                if age is not None:
                    self.roster_ages[player_lookup] = age

            logger.info(f"Loaded roster ages for {len(self.roster_ages)} players")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error loading roster data: {e}")
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error loading roster data: {e}")
    
    def _extract_injuries(self) -> None:
        """
        Extract injury report data from NBA.com injury report.

        Gets the latest injury status for each player for the target game date.
        Stores results in self.injuries as {player_lookup: {'status': ..., 'report': ...}}.

        Injury statuses:
        - 'out': Definitely not playing
        - 'doubtful': Unlikely to play (usually 25% chance)
        - 'questionable': Uncertain (usually 50% chance)
        - 'probable': Likely to play (usually 75% chance)
        - 'available': Was on report but cleared to play

        NOTE: For real-time processing, this returns the current injury status.
        For backfill, this returns the FINAL status (which may be 'out' for DNP players).
        This is intentional - backfill DNP players are excluded via BET_VOIDED_DNP anyway.
        """
        if not self.players_to_process:
            logger.info("No players to lookup injuries for")
            return

        # Get unique player lookups for matching
        unique_players = list(set(p['player_lookup'] for p in self.players_to_process))

        logger.info(f"Extracting injury data for {len(unique_players)} players")

        # Use parameterized query to avoid SQL injection
        # NOTE: We filter by game_date only, not game_id, because:
        # - Injury report uses format like "20260110_CHA_UTA"
        # - Context table uses format like "0022500543"
        # - Same-day doubleheaders are extremely rare in NBA
        query = f"""
        WITH latest_report AS (
            SELECT
                player_lookup,
                injury_status,
                reason,
                reason_category,
                report_date,
                processed_at,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_date DESC, processed_at DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.nbac_injury_report`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date = @target_date
        )
        SELECT
            player_lookup,
            injury_status,
            reason,
            reason_category,
            processed_at
        FROM latest_report
        WHERE rn = 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", unique_players),
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date.isoformat()),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if df.empty:
                logger.info("No injury report data found for target date")
                # Track in source_tracking for observability
                self.source_tracking['injuries'] = {
                    'last_updated': None,
                    'rows_found': 0,
                    'players_with_status': 0
                }
                return

            # Track latest update time for source tracking
            latest_processed = df['processed_at'].max() if 'processed_at' in df.columns else None

            # Build injuries dict
            for _, row in df.iterrows():
                player_lookup = row['player_lookup']
                reason = row['reason']
                reason_category = row['reason_category']

                # Build a meaningful report string
                if reason and str(reason).lower() not in ('unknown', 'nan', 'none', ''):
                    report = reason
                elif reason_category and str(reason_category).lower() not in ('unknown', 'nan', 'none', ''):
                    report = reason_category
                else:
                    report = None  # No reason available

                self.injuries[player_lookup] = {
                    'status': row['injury_status'],
                    'report': report
                }

            # Log summary by status
            status_counts = {}
            for info in self.injuries.values():
                status = info['status']
                status_counts[status] = status_counts.get(status, 0) + 1

            logger.info(
                f"Extracted injury data for {len(self.injuries)} players: "
                f"{', '.join(f'{k}={v}' for k, v in sorted(status_counts.items()))}"
            )

            # Track in source_tracking for observability
            self.source_tracking['injuries'] = {
                'last_updated': latest_processed,
                'rows_found': len(df),
                'players_with_status': len(self.injuries),
                'status_breakdown': status_counts
            }

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error extracting injury data: {e}. Continuing without injury info.")
            self.source_tracking['injuries'] = {
                'last_updated': None,
                'rows_found': 0,
                'players_with_status': 0,
                'error': str(e)
            }
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error extracting injury data: {e}. Continuing without injury info.")
            self.source_tracking['injuries'] = {
                'last_updated': None,
                'rows_found': 0,
                'players_with_status': 0,
                'error': str(e)
            }
    
    def _extract_registry(self) -> None:
        """
        Extract universal player IDs from registry using batch lookup.

        Populates self.registry dict with {player_lookup: universal_player_id}.
        Uses RegistryReader for efficient batch lookups with caching.
        """
        if not self.players_to_process:
            logger.info("No players to lookup in registry")
            return

        # Get unique player lookups
        unique_players = list(set(p['player_lookup'] for p in self.players_to_process))
        logger.info(f"Looking up {len(unique_players)} unique players in registry")

        try:
            # Batch lookup all players at once
            # Skip logging unresolved players here - we'll log them during game processing
            # with full context (game_id, game_date, etc.)
            uid_map = self.registry_reader.get_universal_ids_batch(
                unique_players,
                skip_unresolved_logging=True
            )

            # Store results in self.registry
            self.registry = uid_map

            # Track stats
            self.registry_stats['players_found'] = len(uid_map)
            self.registry_stats['players_not_found'] = len(unique_players) - len(uid_map)

            logger.info(
                f"Registry lookup complete: {self.registry_stats['players_found']} found, "
                f"{self.registry_stats['players_not_found']} not found"
            )

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error in registry lookup: {e}. Continuing without universal IDs.")
            self.registry = {}
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error in registry lookup: {e}. Continuing without universal IDs.")
            self.registry = {}

    def _extract_standings_data(self) -> None:
        """
        Extract current team standings for opponent win percentage calculation.

        Loads the most recent standings data from bdl_standings.
        Stores in self.standings_data as {team_abbr: win_percentage}.
        """
        logger.info("Extracting standings data for opponent win percentage")

        # Get most recent standings (within last 7 days to ensure fresh data)
        query = f"""
        WITH latest_standings AS (
            SELECT
                team_abbr,
                win_percentage,
                wins,
                losses,
                date_recorded,
                ROW_NUMBER() OVER (
                    PARTITION BY team_abbr
                    ORDER BY date_recorded DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.bdl_standings`
            WHERE date_recorded >= DATE_SUB(@target_date, INTERVAL 7 DAY)
              AND date_recorded <= @target_date
        )
        SELECT team_abbr, win_percentage, wins, losses, date_recorded
        FROM latest_standings
        WHERE rn = 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("target_date", "DATE", self.target_date),
            ]
        )

        try:
            df = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if df.empty:
                logger.warning("No standings data found within last 7 days")
                self.standings_data = {}
                return

            # Store win percentage by team abbreviation
            for _, row in df.iterrows():
                self.standings_data[row['team_abbr']] = row['win_percentage']

            logger.info(f"Extracted standings for {len(self.standings_data)} teams")

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error extracting standings: {e}. Continuing without standings data.")
            self.standings_data = {}
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error extracting standings: {e}. Continuing without standings data.")
            self.standings_data = {}

    # ========================================================================
    # CIRCUIT BREAKER METHODS (Week 5 - Completeness Checking)
    # ========================================================================

    def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
        """Check if circuit breaker is active for entity."""
        query = f"""
        SELECT attempt_number, attempted_at, circuit_breaker_tripped, circuit_breaker_until
        FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = @processor_name
          AND entity_id = @entity_id
          AND analysis_date = @analysis_date
        ORDER BY attempt_number DESC LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("processor_name", "STRING", self.table_name),
                bigquery.ScalarQueryParameter("entity_id", "STRING", entity_id),
                bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
            ]
        )
        try:
            result = list(self.bq_client.query(query, job_config=job_config).result(timeout=60))
            if not result:
                return {'active': False, 'attempts': 0, 'until': None}
            row = result[0]
            if row.circuit_breaker_tripped:
                if row.circuit_breaker_until and datetime.now(timezone.utc) < row.circuit_breaker_until:
                    return {'active': True, 'attempts': row.attempt_number, 'until': row.circuit_breaker_until}
            return {'active': False, 'attempts': row.attempt_number, 'until': None}
        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error checking circuit breaker for {entity_id}: {e}")
            return {'active': False, 'attempts': 0, 'until': None}
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error checking circuit breaker for {entity_id}: {e}")
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
        VALUES (@processor_name, @entity_id, @analysis_date, @attempt_number,
                CURRENT_TIMESTAMP(), @completeness_pct, @skip_reason, @circuit_breaker_tripped,
                @circuit_breaker_until,
                FALSE, @notes)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("processor_name", "STRING", self.table_name),
                bigquery.ScalarQueryParameter("entity_id", "STRING", entity_id),
                bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
                bigquery.ScalarQueryParameter("attempt_number", "INT64", next_attempt),
                bigquery.ScalarQueryParameter("completeness_pct", "FLOAT64", completeness_pct),
                bigquery.ScalarQueryParameter("skip_reason", "STRING", skip_reason),
                bigquery.ScalarQueryParameter("circuit_breaker_tripped", "BOOL", circuit_breaker_tripped),
                bigquery.ScalarQueryParameter("circuit_breaker_until", "TIMESTAMP", circuit_breaker_until),
                bigquery.ScalarQueryParameter("notes", "STRING", f'Attempt {next_attempt}: {completeness_pct:.1f}% complete'),
            ]
        )
        try:
            self.bq_client.query(insert_query, job_config=job_config).result(timeout=60)
        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error recording reprocess attempt for {entity_id}: {e}")
        except (KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Data error recording reprocess attempt for {entity_id}: {e}")

    # ========================================================================
    # CALCULATION - MAIN FLOW
    # ========================================================================

    def calculate_analytics(self) -> None:
        """
        Calculate context for each player.

        For each player with a prop bet:
        1. Batch completeness checking (Week 5 - all 5 windows)
        2. Determine player's team
        3. Calculate fatigue metrics
        4. Calculate performance trends
        5. Assemble context record
        """
        if not self.players_to_process:
            logger.warning("No players to process")
            return

        logger.info(f"Calculating context for {len(self.players_to_process)} players")

        # Get all player lookups
        all_players = [p['player_lookup'] for p in self.players_to_process]

        # ============================================================
        # NEW (Week 5): Batch completeness checking for ALL 5 windows
        # ============================================================
        logger.info(f"Checking completeness for {len(all_players)} players across 5 windows...")

        # PERFORMANCE OPTIMIZATION: Run completeness checks in parallel (5x speedup)
        # Each check takes ~30 sec due to BQ query overhead, running them concurrently
        # reduces total time from ~2.5 min to ~30 sec
        import time
        completeness_start = time.time()
        try:
            # Define all completeness check configurations
            completeness_windows = [
                ('l5', 5, 'games'),      # Window 1: L5 games
                ('l10', 10, 'games'),    # Window 2: L10 games
                ('l7d', 7, 'days'),      # Window 3: L7 days
                ('l14d', 14, 'days'),    # Window 4: L14 days
                ('l30d', 30, 'days'),    # Window 5: L30 days
            ]

            # Helper function to run single completeness check
            def run_completeness_check(window_config):
                name, lookback, window_type = window_config
                return (name, self.completeness_checker.check_completeness_batch(
                    entity_ids=list(all_players),
                    entity_type='player',
                    analysis_date=self.target_date,
                    upstream_table='nba_raw.bdl_player_boxscores',
                    upstream_entity_field='player_lookup',
                    lookback_window=lookback,
                    window_type=window_type,
                    season_start_date=self.season_start_date,
                    dnp_aware=True  # Exclude DNP games from expected count to prevent false positives
                ))

            # Run all 5 completeness checks in parallel
            completeness_results = {}
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(run_completeness_check, config): config[0]
                          for config in completeness_windows}
                for future in as_completed(futures):
                    window_name = futures[future]
                    try:
                        name, result = future.result()
                        completeness_results[name] = result
                    except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                        logger.warning(f"BigQuery error in completeness check for {window_name}: {e}")
                        completeness_results[window_name] = {}
                    except (KeyError, AttributeError, TypeError, ValueError) as e:
                        logger.warning(f"Data error in completeness check for {window_name}: {e}")
                        completeness_results[window_name] = {}

            # Extract results with defaults
            comp_l5 = completeness_results.get('l5', {})
            comp_l10 = completeness_results.get('l10', {})
            comp_l7d = completeness_results.get('l7d', {})
            comp_l14d = completeness_results.get('l14d', {})
            comp_l30d = completeness_results.get('l30d', {})

            # Check bootstrap mode
            is_bootstrap = self.completeness_checker.is_bootstrap_mode(
                self.target_date, self.season_start_date
            )
            is_season_boundary = self.completeness_checker.is_season_boundary(self.target_date)

            completeness_elapsed = time.time() - completeness_start
            logger.info(
                f"Completeness check complete in {completeness_elapsed:.1f}s (5 windows, parallel). "
                f"Bootstrap mode: {is_bootstrap}, Season boundary: {is_season_boundary}"
            )
        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            # Issue #3: Fail-closed - raise exception instead of returning fake data
            logger.error(
                f"Completeness checking FAILED (BigQuery error: {e}). "
                f"Cannot proceed with unreliable data.",
                exc_info=True
            )
            raise
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            # Issue #3: Fail-closed - raise exception instead of returning fake data
            logger.error(
                f"Completeness checking FAILED (Data error: {e}). "
                f"Cannot proceed with unreliable data.",
                exc_info=True
            )
            raise
        # ============================================================

        # Feature flag for player-level parallelization
        ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'

        if ENABLE_PARALLELIZATION:
            self._process_players_parallel(
                comp_l5, comp_l10, comp_l7d, comp_l14d, comp_l30d,
                is_bootstrap, is_season_boundary
            )
        else:
            self._process_players_serial(
                comp_l5, comp_l10, comp_l7d, comp_l14d, comp_l30d,
                is_bootstrap, is_season_boundary
            )

        logger.info(f"Successfully calculated context for {len(self.transformed_data)} players")

        # Save registry failure records to BigQuery for observability (v2.1 feature)
        if self.registry_failures:
            self.save_registry_failures()

    def _process_players_parallel(self, comp_l5: Dict, comp_l10: Dict, comp_l7d: Dict,
                                   comp_l14d: Dict, comp_l30d: Dict,
                                   is_bootstrap: bool, is_season_boundary: bool) -> None:
        """Process all players using ThreadPoolExecutor for parallelization."""
        import time

        # Determine worker count with environment variable support
        DEFAULT_WORKERS = 10
        max_workers = int(os.environ.get(
            'UPGC_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        logger.info(f"Processing {len(self.players_to_process)} players with {max_workers} workers (parallel mode)")

        # Performance timing
        loop_start = time.time()
        processed_count = 0

        # Thread-safe result collection
        results = []
        failures = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all player tasks
            futures = {
                executor.submit(
                    self._process_single_player,
                    player_info, comp_l5, comp_l10, comp_l7d, comp_l14d, comp_l30d,
                    is_bootstrap, is_season_boundary
                ): player_info
                for player_info in self.players_to_process
            }

            # Collect results as they complete
            for future in as_completed(futures):
                player_info = futures[future]
                processed_count += 1

                try:
                    success, data = future.result()
                    if success:
                        results.append(data)
                    else:
                        failures.append(data)

                    # Progress logging every 50 players
                    if processed_count % 50 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed
                        remaining = len(self.players_to_process) - processed_count
                        eta = remaining / rate
                        logger.info(
                            f"Player processing progress: {processed_count}/{len(self.players_to_process)} "
                            f"| Rate: {rate:.1f} players/sec | ETA: {eta/60:.1f}min"
                        )
                except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                    logger.error(f"BigQuery error processing {player_info['player_lookup']}: {e}")
                    failures.append({
                        'player_lookup': player_info['player_lookup'],
                        'game_id': player_info['game_id'],
                        'reason': str(e),
                        'category': 'BIGQUERY_ERROR'
                    })
                except (KeyError, AttributeError, TypeError, ValueError) as e:
                    logger.error(f"Data error processing {player_info['player_lookup']}: {e}")
                    failures.append({
                        'player_lookup': player_info['player_lookup'],
                        'game_id': player_info['game_id'],
                        'reason': str(e),
                        'category': 'DATA_ERROR'
                    })

        # Store results (main thread only - thread-safe)
        self.transformed_data = results
        self.failed_entities = failures

        # Track registry failures for observability (v2.1 feature)
        # Records with NULL universal_player_id were created but need reprocessing after alias
        for record in results:
            if record.get('universal_player_id') is None:
                self.registry_failures.append({
                    'player_lookup': record.get('player_lookup'),
                    'game_date': self.target_date,
                    'team_abbr': record.get('team_abbr'),
                    'season': f"{self.target_date.year}-{str(self.target_date.year + 1)[-2:]}" if self.target_date.month >= 10 else f"{self.target_date.year - 1}-{str(self.target_date.year)[-2:]}",
                    'game_id': record.get('game_id')
                })
        if self.registry_failures:
            logger.info(f"📊 Registry failures tracked: {len(self.registry_failures)} players with NULL universal_player_id")

        # Final timing summary
        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(results)} players in {total_time:.1f}s "
            f"(avg {total_time/len(results) if results else 0:.2f}s/player) "
            f"| {len(failures)} failed"
        )

    def _process_single_player(self, player_info: Dict, comp_l5: Dict, comp_l10: Dict,
                               comp_l7d: Dict, comp_l14d: Dict, comp_l30d: Dict,
                               is_bootstrap: bool, is_season_boundary: bool) -> Tuple[bool, Dict]:
        """Process one player (thread-safe). Returns (success: bool, data: dict)."""
        player_lookup = player_info['player_lookup']
        game_id = player_info['game_id']

        try:
            # Get default completeness
            default_comp = {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            }

            completeness_l5 = comp_l5.get(player_lookup, default_comp)
            completeness_l10 = comp_l10.get(player_lookup, default_comp)
            completeness_l7d = comp_l7d.get(player_lookup, default_comp)
            completeness_l14d = comp_l14d.get(player_lookup, default_comp)
            completeness_l30d = comp_l30d.get(player_lookup, default_comp)

            # Check circuit breaker
            circuit_breaker_status = self._check_circuit_breaker(player_lookup, self.target_date)

            if circuit_breaker_status['active']:
                return (False, {
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                    'category': 'CIRCUIT_BREAKER_ACTIVE'
                })

            # Check if ALL windows are production-ready (skip if not, unless in bootstrap mode)
            all_windows_ready = (
                completeness_l5['is_production_ready'] and
                completeness_l10['is_production_ready'] and
                completeness_l7d['is_production_ready'] and
                completeness_l14d['is_production_ready'] and
                completeness_l30d['is_production_ready']
            )

            # RECOVERY MODE: Skip completeness checks via environment variable
            skip_completeness = os.environ.get('SKIP_COMPLETENESS_CHECK', 'false').lower() == 'true'

            # Allow processing during bootstrap mode OR season boundary (early season dates)
            if not all_windows_ready and not is_bootstrap and not is_season_boundary and not skip_completeness:
                # Calculate average completeness across all windows
                avg_completeness = (
                    completeness_l5['completeness_pct'] +
                    completeness_l10['completeness_pct'] +
                    completeness_l7d['completeness_pct'] +
                    completeness_l14d['completeness_pct'] +
                    completeness_l30d['completeness_pct']
                ) / 5.0

                # Track reprocessing attempt
                self._increment_reprocess_count(
                    player_lookup, self.target_date,
                    avg_completeness, 'incomplete_multi_window_data'
                )

                return (False, {
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': f"Multi-window completeness {avg_completeness:.1f}%",
                    'category': 'INCOMPLETE_DATA_SKIPPED'
                })

            # Calculate context (existing function - thread-safe)
            context = self._calculate_player_context(
                player_info,
                completeness_l5, completeness_l10, completeness_l7d, completeness_l14d, completeness_l30d,
                circuit_breaker_status, is_bootstrap, is_season_boundary
            )

            if context:
                return (True, context)
            else:
                return (False, {
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': 'Failed to calculate context',
                    'category': 'CALCULATION_ERROR'
                })

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            return (False, {
                'player_lookup': player_lookup,
                'game_id': game_id,
                'reason': str(e),
                'category': 'BIGQUERY_ERROR'
            })
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            return (False, {
                'player_lookup': player_lookup,
                'game_id': game_id,
                'reason': str(e),
                'category': 'DATA_ERROR'
            })

    def _process_players_serial(self, comp_l5: Dict, comp_l10: Dict, comp_l7d: Dict,
                                comp_l14d: Dict, comp_l30d: Dict,
                                is_bootstrap: bool, is_season_boundary: bool) -> None:
        """Original serial processing (kept for fallback)."""
        logger.info(f"Processing {len(self.players_to_process)} players (serial mode)")

        for player_info in self.players_to_process:
            try:
                player_lookup = player_info['player_lookup']
                game_id = player_info['game_id']

                # Get default empty completeness results
                default_comp = {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                }

                completeness_l5 = comp_l5.get(player_lookup, default_comp)
                completeness_l10 = comp_l10.get(player_lookup, default_comp)
                completeness_l7d = comp_l7d.get(player_lookup, default_comp)
                completeness_l14d = comp_l14d.get(player_lookup, default_comp)
                completeness_l30d = comp_l30d.get(player_lookup, default_comp)

                # Check circuit breaker
                circuit_breaker_status = self._check_circuit_breaker(player_lookup, self.target_date)

                if circuit_breaker_status['active']:
                    logger.warning(
                        f"{player_lookup}: Circuit breaker active until "
                        f"{circuit_breaker_status['until']} - skipping"
                    )
                    self.failed_entities.append({
                        'player_lookup': player_lookup,
                        'game_id': game_id,
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE'
                    })
                    continue

                # Check if ALL windows are production-ready (skip if not, unless in bootstrap mode)
                all_windows_ready = (
                    completeness_l5['is_production_ready'] and
                    completeness_l10['is_production_ready'] and
                    completeness_l7d['is_production_ready'] and
                    completeness_l14d['is_production_ready'] and
                    completeness_l30d['is_production_ready']
                )

                # RECOVERY MODE: Skip completeness checks via environment variable
                skip_completeness = os.environ.get('SKIP_COMPLETENESS_CHECK', 'false').lower() == 'true'

                # Allow processing during bootstrap mode OR season boundary (early season dates)
                if not all_windows_ready and not is_bootstrap and not is_season_boundary and not skip_completeness:
                    # Calculate average completeness across all windows
                    avg_completeness = (
                        completeness_l5['completeness_pct'] +
                        completeness_l10['completeness_pct'] +
                        completeness_l7d['completeness_pct'] +
                        completeness_l14d['completeness_pct'] +
                        completeness_l30d['completeness_pct']
                    ) / 5.0

                    logger.warning(
                        f"{player_lookup}: Not all windows complete (avg {avg_completeness:.1f}%) - skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, self.target_date,
                        avg_completeness,
                        'incomplete_multi_window_data'
                    )

                    self.failed_entities.append({
                        'player_lookup': player_lookup,
                        'game_id': game_id,
                        'reason': f"Multi-window completeness {avg_completeness:.1f}%",
                        'category': 'INCOMPLETE_DATA_SKIPPED'
                    })
                    continue

                # Calculate context (pass completeness data)
                context = self._calculate_player_context(
                    player_info,
                    completeness_l5, completeness_l10, completeness_l7d, completeness_l14d, completeness_l30d,
                    circuit_breaker_status, is_bootstrap, is_season_boundary
                )

                if context:
                    self.transformed_data.append(context)
                else:
                    self.failed_entities.append({
                        'player_lookup': player_lookup,
                        'game_id': game_id,
                        'reason': 'Failed to calculate context',
                        'category': 'CALCULATION_ERROR'
                    })

            except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                logger.error(f"BigQuery error calculating context for {player_lookup}: {e}")
                self.failed_entities.append({
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': str(e),
                    'category': 'BIGQUERY_ERROR'
                })
            except (KeyError, AttributeError, TypeError, ValueError) as e:
                logger.error(f"Data error calculating context for {player_lookup}: {e}")
                self.failed_entities.append({
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': str(e),
                    'category': 'DATA_ERROR'
                })

        # Track registry failures for observability (v2.1 feature)
        # Records with NULL universal_player_id were created but need reprocessing after alias
        for record in self.transformed_data:
            if record.get('universal_player_id') is None:
                self.registry_failures.append({
                    'player_lookup': record.get('player_lookup'),
                    'game_date': self.target_date,
                    'team_abbr': record.get('team_abbr'),
                    'season': f"{self.target_date.year}-{str(self.target_date.year + 1)[-2:]}" if self.target_date.month >= 10 else f"{self.target_date.year - 1}-{str(self.target_date.year)[-2:]}",
                    'game_id': record.get('game_id')
                })
        if self.registry_failures:
            logger.info(f"📊 Registry failures tracked: {len(self.registry_failures)} players with NULL universal_player_id")

    def _calculate_player_context(self, player_info: Dict,
                                   completeness_l5: Dict, completeness_l10: Dict,
                                   completeness_l7d: Dict, completeness_l14d: Dict, completeness_l30d: Dict,
                                   circuit_breaker_status: Dict, is_bootstrap: bool, is_season_boundary: bool) -> Optional[Dict]:
        """
        Calculate complete context for a single player.

        Args:
            player_info: Dict with player_lookup, game_id, home/away teams
            completeness_l5: L5 games completeness results
            completeness_l10: L10 games completeness results
            completeness_l7d: L7 days completeness results
            completeness_l14d: L14 days completeness results
            completeness_l30d: L30 days completeness results
            circuit_breaker_status: Circuit breaker status
            is_bootstrap: Whether in bootstrap mode
            is_season_boundary: Whether at season boundary

        Returns:
            Dict with all context fields (including 25 completeness metadata fields), or None if failed
        """
        player_lookup = player_info['player_lookup']
        game_id = player_info['game_id']
        
        # Get game info
        game_info = self.schedule_data.get(game_id)
        if not game_info:
            logger.warning(f"No schedule data for game {game_id}")
            return None
        
        # Determine player's team (use player_info which has team_abbr from gamebook)
        team_abbr = self._determine_player_team(player_lookup, player_info)
        if not team_abbr:
            logger.warning(f"Could not determine team for {player_lookup}")
            return None
        
        # Determine opponent
        opponent_team_abbr = self._get_opponent_team(team_abbr, game_info)
        
        # Get historical boxscores
        historical_data = self.historical_boxscores.get(player_lookup, pd.DataFrame())
        
        # Calculate fatigue metrics
        fatigue_metrics = self._calculate_fatigue_metrics(player_lookup, team_abbr, historical_data)

        # Get prop lines first (needed for performance metrics)
        prop_info = self.prop_lines.get((player_lookup, game_id), {})
        current_points_line = prop_info.get('current_line') or player_info.get('current_points_line')

        # Calculate performance metrics (with prop line for streak calculation)
        performance_metrics = self._calculate_performance_metrics(historical_data, current_points_line)
        
        # Get game lines
        game_lines_info = self.game_lines.get(game_id, {})
        
        # Calculate data quality
        data_quality = self._calculate_data_quality(historical_data, game_lines_info)

        # Calculate pace metrics
        pace_differential = self._calculate_pace_differential(team_abbr, opponent_team_abbr, self.target_date)
        opponent_pace_last_10 = self._get_opponent_pace_last_10(opponent_team_abbr, self.target_date)
        opponent_ft_rate_allowed = self._get_opponent_ft_rate_allowed(opponent_team_abbr, self.target_date)
        opponent_def_rating = self._get_opponent_def_rating_last_10(opponent_team_abbr, self.target_date)
        opponent_off_rating = self._get_opponent_off_rating_last_10(opponent_team_abbr, self.target_date)
        opponent_rebounding_rate = self._get_opponent_rebounding_rate(opponent_team_abbr, self.target_date)
        opponent_pace_variance = self._get_opponent_pace_variance(opponent_team_abbr, self.target_date)
        opponent_ft_rate_variance = self._get_opponent_ft_rate_variance(opponent_team_abbr, self.target_date)
        opponent_def_rating_variance = self._get_opponent_def_rating_variance(opponent_team_abbr, self.target_date)
        opponent_off_rating_variance = self._get_opponent_off_rating_variance(opponent_team_abbr, self.target_date)
        opponent_rebounding_rate_variance = self._get_opponent_rebounding_rate_variance(opponent_team_abbr, self.target_date)

        # Calculate star teammates out (Session 106)
        star_teammates_out = self._get_star_teammates_out(team_abbr, self.target_date)

        # Enhanced star tracking (Session 107)
        questionable_star_teammates = self._get_questionable_star_teammates(team_abbr, self.target_date)
        star_tier_out = self._get_star_tier_out(team_abbr, self.target_date)

        # Calculate projected usage rate (Session 108)
        projected_usage_rate = self._calculate_projected_usage_rate(
            player_lookup=player_lookup,
            team_abbr=team_abbr,
            game_date=self.target_date,
            star_teammates_out=star_teammates_out,
            opponent_team_abbr=opponent_team_abbr,
            historical_data=historical_data
        )

        # Calculate travel context (P1-20)
        travel_context = self._calculate_travel_context(team_abbr, game_info)

        # Calculate forward-looking schedule features (Session 110 - implemented)
        forward_schedule = self._calculate_forward_schedule_features(team_abbr, self.target_date)

        # Calculate opponent rest/asymmetry features (Session 110 - implemented)
        opponent_rest = self._calculate_opponent_rest_features(opponent_team_abbr, self.target_date)

        # Get has_prop_line from player_info (passed from extract)
        has_prop_line = player_info.get('has_prop_line', False)

        # Get universal player ID
        universal_player_id = self.registry.get(player_lookup)

        # Log unresolved player with game context if not found
        if universal_player_id is None:
            game_context = {
                'game_id': game_id,
                'game_date': self.target_date.isoformat(),
                'season': f"{self.target_date.year}-{str(self.target_date.year + 1)[-2:]}",
                'team_abbr': team_abbr,
                'source': 'upcoming_player_game_context'
            }
            self.registry_reader._log_unresolved_player(player_lookup, game_context)

        # Build context record (FIX: use timezone-aware datetime)
        context = {
            # Core identifiers
            'player_lookup': player_lookup,
            'universal_player_id': universal_player_id,
            'game_id': game_id,
            'game_date': self.target_date.isoformat(),
            'team_abbr': team_abbr,
            'opponent_team_abbr': opponent_team_abbr,

            # Has prop line flag (NEW - v3.2 All-Player Predictions)
            'has_prop_line': has_prop_line,

            # Prop betting context
            # Use prop_info if has_prop_line, otherwise use from player_info (passed from extract)
            'current_points_line': prop_info.get('current_line') or player_info.get('current_points_line'),
            'opening_points_line': prop_info.get('opening_line'),
            'line_movement': prop_info.get('line_movement'),
            'current_points_line_source': prop_info.get('current_source') or player_info.get('prop_source'),
            'opening_points_line_source': prop_info.get('opening_source'),
            
            # Game spread context
            'game_spread': game_lines_info.get('game_spread'),
            'opening_spread': game_lines_info.get('opening_spread'),
            'spread_movement': game_lines_info.get('spread_movement'),
            'game_spread_source': game_lines_info.get('spread_source'),
            'spread_public_betting_pct': self._get_spread_public_betting_pct(game_id),

            # Game total context
            'game_total': game_lines_info.get('game_total'),
            'opening_total': game_lines_info.get('opening_total'),
            'total_movement': game_lines_info.get('total_movement'),
            'game_total_source': game_lines_info.get('total_source'),
            'total_public_betting_pct': self._get_total_public_betting_pct(game_id),

            # Pre-game context
            'pace_differential': pace_differential,
            'opponent_pace_last_10': opponent_pace_last_10,
            'game_start_time_local': self._extract_game_time(game_info),
            'opponent_ft_rate_allowed': opponent_ft_rate_allowed,
            'home_game': (team_abbr == game_info['home_team_abbr']),
            'back_to_back': fatigue_metrics['back_to_back'],
            'season_phase': self._determine_season_phase(self.target_date, team_abbr),
            'projected_usage_rate': projected_usage_rate,

            # Fatigue metrics
            **fatigue_metrics,
            
            # Travel context (P1-20: implemented)
            'travel_miles': travel_context.get('travel_miles'),
            'time_zone_changes': travel_context.get('time_zone_changes'),
            'consecutive_road_games': travel_context.get('consecutive_road_games'),
            'miles_traveled_last_14_days': travel_context.get('miles_traveled_last_14_days'),
            'time_zones_crossed_last_14_days': travel_context.get('time_zones_crossed_last_14_days'),
            
            # Player characteristics
            'player_age': self.roster_ages.get(player_lookup) if hasattr(self, 'roster_ages') else None,
            
            # Performance metrics
            **performance_metrics,

            # Override opponent metrics with calculated values
            'opponent_def_rating_last_10': opponent_def_rating,
            'opponent_off_rating_last_10': opponent_off_rating,
            'opponent_rebounding_rate': opponent_rebounding_rate,
            'opponent_pace_variance': opponent_pace_variance,
            'opponent_ft_rate_variance': opponent_ft_rate_variance,  # Session 107
            'opponent_def_rating_variance': opponent_def_rating_variance,  # Session 107
            'opponent_off_rating_variance': opponent_off_rating_variance,  # Session 107
            'opponent_rebounding_rate_variance': opponent_rebounding_rate_variance,  # Session 107

            # Forward-looking schedule (Session 110 - implemented)
            'next_game_days_rest': forward_schedule['next_game_days_rest'],
            'games_in_next_7_days': forward_schedule['games_in_next_7_days'],
            'next_opponent_win_pct': forward_schedule['next_opponent_win_pct'],
            'next_game_is_primetime': forward_schedule['next_game_is_primetime'],

            # Opponent asymmetry (Session 110 - implemented)
            'opponent_days_rest': opponent_rest['opponent_days_rest'],
            'opponent_games_in_next_7_days': opponent_rest['opponent_games_in_next_7_days'],
            'opponent_next_game_days_rest': opponent_rest['opponent_next_game_days_rest'],

            # Real-time updates
            'player_status': self.injuries.get(player_lookup, {}).get('status'),
            'injury_report': self.injuries.get(player_lookup, {}).get('report'),
            'star_teammates_out': star_teammates_out,  # Session 106
            'questionable_star_teammates': questionable_star_teammates,  # Session 107
            'star_tier_out': star_tier_out,  # Session 107
            'probable_teammates': None,  # TODO: BLOCKED - needs injury report parsing with probability fields
            
            # Source tracking
            **self._build_source_tracking_fields(),

            # Data quality
            **data_quality,

            # ============================================================
            # NEW (Week 5): Completeness Checking Metadata (25 fields)
            # ============================================================
            # Completeness Metrics (use L30d as primary - full lookback window)
            'expected_games_count': completeness_l30d['expected_count'],
            'actual_games_count': completeness_l30d['actual_count'],
            'completeness_percentage': completeness_l30d['completeness_pct'],
            'missing_games_count': completeness_l30d['missing_count'],

            # Production Readiness
            # During season boundaries, mark as production_ready even if completeness is low
            'is_production_ready': is_season_boundary or is_bootstrap or (
                completeness_l5['is_production_ready'] and
                completeness_l10['is_production_ready'] and
                completeness_l7d['is_production_ready'] and
                completeness_l14d['is_production_ready'] and
                completeness_l30d['is_production_ready']
            ),
            'data_quality_issues': [],  # Populate if specific issues found

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

            # Multi-Window Completeness (11 fields)
            'l5_completeness_pct': completeness_l5['completeness_pct'],
            'l5_is_complete': completeness_l5['is_complete'],
            'l10_completeness_pct': completeness_l10['completeness_pct'],
            'l10_is_complete': completeness_l10['is_complete'],
            'l7d_completeness_pct': completeness_l7d['completeness_pct'],
            'l7d_is_complete': completeness_l7d['is_complete'],
            'l14d_completeness_pct': completeness_l14d['completeness_pct'],
            'l14d_is_complete': completeness_l14d['is_complete'],
            'l30d_completeness_pct': completeness_l30d['completeness_pct'],
            'l30d_is_complete': completeness_l30d['is_complete'],
            'all_windows_complete': (
                completeness_l5['is_complete'] and
                completeness_l10['is_complete'] and
                completeness_l7d['is_complete'] and
                completeness_l14d['is_complete'] and
                completeness_l30d['is_complete']
            ),
            # ============================================================

            # Update tracking (FIX: use timezone-aware datetime)
            'context_version': 1,  # TODO: increment for intraday updates
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }

        # Calculate data_hash AFTER all fields are populated (Pattern #3: Smart Reprocessing)
        context['data_hash'] = self._calculate_data_hash(context)

        return context
    
    def _determine_player_team(self, player_lookup: str, game_info: Dict) -> Optional[str]:
        """
        Determine which team the player is on.

        Strategy:
        1. Check game_info (from gamebook query - already has team_abbr)
        2. Use most recent boxscore (fallback for daily mode)

        Args:
            player_lookup: Player identifier
            game_info: Game information dict (contains team_abbr from gamebook)

        Returns:
            Team abbreviation or None
        """
        # First check game_info - gamebook already has team_abbr
        if game_info.get('team_abbr'):
            return game_info['team_abbr']

        # Fallback: Use most recent boxscore (for daily mode without gamebook)
        historical_data = self.historical_boxscores.get(player_lookup, pd.DataFrame())
        if not historical_data.empty:
            most_recent = historical_data.iloc[0]  # Already sorted by date DESC
            return most_recent.get('team_abbr')

        return None
    
    def _get_opponent_team(self, team_abbr: str, game_info: Dict) -> str:
        """Get opponent team abbreviation."""
        if team_abbr == game_info['home_team_abbr']:
            return game_info['away_team_abbr']
        else:
            return game_info['home_team_abbr']
    
    def _calculate_fatigue_metrics(self, player_lookup: str, team_abbr: str, 
                                   historical_data: pd.DataFrame) -> Dict:
        """
        Calculate fatigue-related metrics.
        
        Args:
            player_lookup: Player identifier
            team_abbr: Player's team
            historical_data: DataFrame of historical boxscores
            
        Returns:
            Dict with fatigue metrics
        """
        if historical_data.empty:
            return {
                'days_rest': None,
                'days_rest_before_last_game': None,
                'days_since_2_plus_days_rest': None,
                'games_in_last_7_days': 0,
                'games_in_last_14_days': 0,
                'minutes_in_last_7_days': 0,
                'minutes_in_last_14_days': 0,
                'avg_minutes_per_game_last_7': None,
                'back_to_backs_last_14_days': 0,
                'avg_usage_rate_last_7_games': None,  # TODO: future
                'fourth_quarter_minutes_last_7': None,  # TODO: future
                'clutch_minutes_last_7_games': None,  # TODO: future
                'back_to_back': False
            }
        
        # Get most recent game date
        last_game_date = historical_data.iloc[0]['game_date']
        
        # Days rest
        days_rest = (self.target_date - last_game_date).days
        
        # Back-to-back
        back_to_back = (days_rest == 0)
        
        # Games in windows
        last_7_days = self.target_date - timedelta(days=7)
        last_14_days = self.target_date - timedelta(days=14)
        
        games_last_7 = historical_data[historical_data['game_date'] >= last_7_days]
        games_last_14 = historical_data[historical_data['game_date'] >= last_14_days]
        
        # Minutes totals
        minutes_last_7 = games_last_7['minutes_decimal'].sum() if 'minutes_decimal' in games_last_7.columns else 0
        minutes_last_14 = games_last_14['minutes_decimal'].sum() if 'minutes_decimal' in games_last_14.columns else 0
        
        # Average minutes per game
        avg_minutes_last_7 = minutes_last_7 / len(games_last_7) if len(games_last_7) > 0 else None
        
        # Back-to-backs in last 14 days
        back_to_backs_count = 0
        if len(games_last_14) > 1:
            dates = sorted(games_last_14['game_date'].tolist())
            for i in range(len(dates) - 1):
                if (dates[i+1] - dates[i]).days == 1:
                    back_to_backs_count += 1
        
        # Days rest before last game (if have at least 2 games)
        days_rest_before_last = None
        if len(historical_data) >= 2:
            second_last_date = historical_data.iloc[1]['game_date']
            days_rest_before_last = (last_game_date - second_last_date).days
        
        # Days since 2+ days rest
        days_since_2_plus_rest = None
        for i in range(len(historical_data) - 1):
            current_date = historical_data.iloc[i]['game_date']
            next_date = historical_data.iloc[i+1]['game_date']
            days_diff = (current_date - next_date).days
            
            if days_diff >= 2:
                days_since_2_plus_rest = (self.target_date - current_date).days
                break
        
        return {
            'days_rest': days_rest,
            'days_rest_before_last_game': days_rest_before_last,
            'days_since_2_plus_days_rest': days_since_2_plus_rest,
            'games_in_last_7_days': len(games_last_7),
            'games_in_last_14_days': len(games_last_14),
            'minutes_in_last_7_days': int(minutes_last_7),
            'minutes_in_last_14_days': int(minutes_last_14),
            'avg_minutes_per_game_last_7': round(avg_minutes_last_7, 1) if avg_minutes_last_7 else None,
            'back_to_backs_last_14_days': back_to_backs_count,
            'avg_usage_rate_last_7_games': None,  # TODO: future (needs play-by-play data parsing)
            'fourth_quarter_minutes_last_7': None,  # TODO: future (needs play-by-play data parsing)
            'clutch_minutes_last_7_games': None,  # TODO: future (needs play-by-play data parsing)
            'back_to_back': back_to_back
        }

    def _calculate_forward_schedule_features(self, team_abbr: str, game_date: date) -> Dict:
        """
        Calculate forward-looking schedule features.

        Uses schedule_data (which includes +/- 5 days around target date) to determine:
        - Days until next game
        - Games in next 7 days
        - Whether next game is primetime
        - Next opponent's win percentage

        Args:
            team_abbr: Team abbreviation
            game_date: Current game date

        Returns:
            Dict with forward schedule metrics
        """
        default_metrics = {
            'next_game_days_rest': None,
            'games_in_next_7_days': 0,
            'next_opponent_win_pct': None,
            'next_game_is_primetime': False,
        }

        if not self.schedule_data:
            return default_metrics

        try:
            # Find all future games for this team (within our schedule window)
            future_games = []
            for game_id, game_info in self.schedule_data.items():
                sched_date = game_info.get('game_date')
                if isinstance(sched_date, str):
                    sched_date = date.fromisoformat(sched_date)

                if sched_date <= game_date:
                    continue

                # Check if team is playing in this game
                home_team = game_info.get('home_team_abbr')
                away_team = game_info.get('away_team_abbr')
                if team_abbr in (home_team, away_team):
                    future_games.append({
                        'game_date': sched_date,
                        'opponent': away_team if team_abbr == home_team else home_team,
                        'is_primetime': game_info.get('is_primetime', False),
                    })

            if not future_games:
                return default_metrics

            # Sort by date
            future_games.sort(key=lambda x: x['game_date'])

            # Next game info
            next_game = future_games[0]
            days_until_next = (next_game['game_date'] - game_date).days

            # Games in next 7 days (excluding current game)
            next_7_days = game_date + timedelta(days=7)
            games_in_next_7 = sum(1 for g in future_games if g['game_date'] <= next_7_days)

            # Next opponent win percentage
            next_opponent = next_game['opponent']
            next_opponent_win_pct = self.standings_data.get(next_opponent)

            return {
                'next_game_days_rest': days_until_next,
                'games_in_next_7_days': games_in_next_7,
                'next_opponent_win_pct': round(next_opponent_win_pct, 3) if next_opponent_win_pct else None,
                'next_game_is_primetime': bool(next_game['is_primetime']),
            }

        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Error calculating forward schedule for {team_abbr}: {e}")
            return default_metrics

    def _calculate_opponent_rest_features(self, opponent_team_abbr: str, game_date: date) -> Dict:
        """
        Calculate opponent rest and schedule asymmetry features.

        Uses schedule_data to determine opponent's rest situation which can
        indicate fatigue advantage/disadvantage.

        Args:
            opponent_team_abbr: Opponent team abbreviation
            game_date: Current game date

        Returns:
            Dict with opponent rest metrics
        """
        default_metrics = {
            'opponent_days_rest': None,
            'opponent_games_in_next_7_days': 0,
            'opponent_next_game_days_rest': None,
        }

        if not self.schedule_data:
            return default_metrics

        try:
            # Find opponent's past and future games
            past_games = []
            future_games = []

            for game_id, game_info in self.schedule_data.items():
                sched_date = game_info.get('game_date')
                if isinstance(sched_date, str):
                    sched_date = date.fromisoformat(sched_date)

                # Check if opponent is playing in this game
                home_team = game_info.get('home_team_abbr')
                away_team = game_info.get('away_team_abbr')
                if opponent_team_abbr not in (home_team, away_team):
                    continue

                if sched_date < game_date:
                    past_games.append(sched_date)
                elif sched_date > game_date:
                    future_games.append(sched_date)

            # Sort
            past_games.sort(reverse=True)  # Most recent first
            future_games.sort()  # Earliest first

            # Opponent days rest (days since last game)
            opponent_days_rest = None
            if past_games:
                opponent_days_rest = (game_date - past_games[0]).days

            # Opponent games in next 7 days
            next_7_days = game_date + timedelta(days=7)
            opponent_games_next_7 = sum(1 for g in future_games if g <= next_7_days)

            # Opponent's next game rest (after current game)
            opponent_next_game_rest = None
            if future_games:
                opponent_next_game_rest = (future_games[0] - game_date).days

            return {
                'opponent_days_rest': opponent_days_rest,
                'opponent_games_in_next_7_days': opponent_games_next_7,
                'opponent_next_game_days_rest': opponent_next_game_rest,
            }

        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Error calculating opponent rest for {opponent_team_abbr}: {e}")
            return default_metrics

    def _calculate_travel_context(self, team_abbr: str, game_info: Dict) -> Dict:
        """
        Calculate travel-related context metrics for the team.

        Uses NBATravel utility to get distance and timezone data.

        Args:
            team_abbr: Team abbreviation
            game_info: Dict with game info including home/away status

        Returns:
            Dict with travel metrics
        """
        default_metrics = {
            'travel_miles': None,
            'time_zone_changes': None,
            'consecutive_road_games': None,
            'miles_traveled_last_14_days': None,
            'time_zones_crossed_last_14_days': None,
        }

        try:
            # Check cache first
            cache_key = f"{team_abbr}_{self.target_date}"
            if cache_key in self._team_travel_cache:
                return self._team_travel_cache[cache_key]

            # Lazy-load travel utils
            if self._travel_utils is None:
                self._travel_utils = NBATravel(self.project_id)

            # Get 14-day travel metrics
            travel_14d = self._travel_utils.get_travel_last_n_days(
                team_abbr=team_abbr,
                current_date=datetime.combine(self.target_date, datetime.min.time()),
                days=14
            )

            if travel_14d:
                metrics = {
                    'travel_miles': None,  # Single game travel TBD
                    'time_zone_changes': None,  # Single game TZ TBD
                    'consecutive_road_games': travel_14d.get('consecutive_away_games', 0),
                    'miles_traveled_last_14_days': travel_14d.get('miles_traveled', 0),
                    'time_zones_crossed_last_14_days': travel_14d.get('time_zones_crossed', 0),
                }
            else:
                metrics = default_metrics

            # Cache result
            self._team_travel_cache[cache_key] = metrics
            return metrics

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.debug(f"BigQuery error calculating travel context for {team_abbr}: {e}")
            return default_metrics
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Data error calculating travel context for {team_abbr}: {e}")
            return default_metrics

    def _calculate_performance_metrics(self, historical_data: pd.DataFrame, current_points_line: Optional[float] = None) -> Dict:
        """
        Calculate recent performance metrics.

        Args:
            historical_data: DataFrame of historical boxscores
            current_points_line: Current prop line for streak calculation (optional)

        Returns:
            Dict with performance metrics
        """
        if historical_data.empty:
            return {
                'points_avg_last_5': None,
                'points_avg_last_10': None,
                'l5_games_used': 0,
                'l5_sample_quality': 'insufficient',
                'l10_games_used': 0,
                'l10_sample_quality': 'insufficient',
                'prop_over_streak': 0,
                'prop_under_streak': 0,
                'opponent_def_rating_last_10': None,
                'shooting_pct_decline_last_5': None,
                'fourth_quarter_production_last_7': None
            }

        # Points averages
        last_5 = historical_data.head(5)
        last_10 = historical_data.head(10)

        points_avg_5 = last_5['points'].mean() if len(last_5) > 0 else None
        points_avg_10 = last_10['points'].mean() if len(last_10) > 0 else None

        # Calculate prop streaks (consecutive games over/under the current line)
        prop_over_streak, prop_under_streak = self._calculate_prop_streaks(
            historical_data, current_points_line
        )

        # Track how many games were actually used for sample size transparency
        l5_games_used = len(last_5)
        l10_games_used = len(last_10)

        return {
            'points_avg_last_5': round(points_avg_5, 1) if points_avg_5 else None,
            'points_avg_last_10': round(points_avg_10, 1) if points_avg_10 else None,
            'l5_games_used': l5_games_used,
            'l5_sample_quality': self._determine_sample_quality(l5_games_used, 5),
            'l10_games_used': l10_games_used,
            'l10_sample_quality': self._determine_sample_quality(l10_games_used, 10),
            'prop_over_streak': prop_over_streak,
            'prop_under_streak': prop_under_streak,
            'opponent_def_rating_last_10': None,
            'shooting_pct_decline_last_5': None,
            'fourth_quarter_production_last_7': None
        }

    def _determine_sample_quality(self, games_count: int, target_window: int) -> str:
        """
        Assess sample quality relative to target window.

        Follows the same pattern as precompute/player_shot_zone_analysis.

        Args:
            games_count: Number of games in sample
            target_window: Target number of games (5 or 10)

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

    def _calculate_prop_streaks(self, historical_data: pd.DataFrame,
                                 current_points_line: Optional[float]) -> Tuple[int, int]:
        """
        Calculate consecutive games over/under the current prop line.

        Args:
            historical_data: DataFrame of historical boxscores (sorted by most recent first)
            current_points_line: The current prop line to compare against

        Returns:
            Tuple of (over_streak, under_streak)
            - over_streak: Consecutive games scoring OVER the line (ends when player goes under)
            - under_streak: Consecutive games scoring UNDER the line (ends when player goes over)
            Only one can be non-zero at a time; if 0, the streak is broken.
        """
        # No line or no data = no streak
        if current_points_line is None or historical_data.empty:
            return 0, 0

        over_streak = 0
        under_streak = 0

        # Iterate through games (most recent first)
        for _, row in historical_data.iterrows():
            points = row.get('points')
            if points is None or pd.isna(points):
                break  # Can't compare, streak ends

            if points > current_points_line:
                if under_streak > 0:
                    break  # Was on an under streak, now it's broken
                over_streak += 1
            elif points < current_points_line:
                if over_streak > 0:
                    break  # Was on an over streak, now it's broken
                under_streak += 1
            else:
                # Exact match (push) - streak continues but doesn't increment
                continue

        return over_streak, under_streak

    def _calculate_pace_differential(self, team_abbr: str, opponent_abbr: str, game_date: date) -> float:
        """
        Calculate difference between team's pace and opponent's pace (last 10 games).

        Args:
            team_abbr: Player's team abbreviation
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Pace differential (team_pace - opponent_pace), rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_team AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @team_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            ),
            recent_opponent AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND((SELECT AVG(pace) FROM recent_team) - (SELECT AVG(pace) FROM recent_opponent), 2) as pace_diff
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.pace_diff if row.pace_diff is not None else 0.0

            logger.warning(f"No pace data found for {team_abbr} vs {opponent_abbr}")
            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error calculating pace differential for {team_abbr} vs {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error calculating pace differential for {team_abbr} vs {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_pace_last_10(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's average pace over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average pace over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(pace), 2) as avg_pace
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.avg_pace if row.avg_pace is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent pace for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent pace for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_ft_rate_allowed(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive FT rate allowed per 100 possessions (last 10 games).

        Calculates FTA allowed per 100 possessions, which normalizes for pace:
        FT Rate = (opp_ft_attempts / opponent_pace) * 100

        This is more meaningful than raw FTA because it accounts for game pace.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average FT attempts allowed per 100 possessions (last 10 games),
                   rounded to 3 decimals. Returns 0.0 if no data available.
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT
                    opp_ft_attempts,
                    opponent_pace,
                    CASE
                        WHEN opponent_pace > 0 THEN
                            ROUND((opp_ft_attempts / opponent_pace) * 100, 3)
                        ELSE NULL
                    END as ft_rate_per_100
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND opp_ft_attempts IS NOT NULL
                  AND opponent_pace IS NOT NULL
                  AND opponent_pace > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND(AVG(ft_rate_per_100), 3) as avg_ft_rate_allowed,
                COUNT(*) as games_count
            FROM recent_games
            WHERE ft_rate_per_100 IS NOT NULL
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                if row.avg_ft_rate_allowed is not None and row.games_count >= 3:
                    return float(row.avg_ft_rate_allowed)
                elif row.avg_ft_rate_allowed is not None:
                    logger.debug(
                        f"FT rate for {opponent_abbr} based on only {row.games_count} games"
                    )
                    return float(row.avg_ft_rate_allowed)

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting FT rate allowed for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting FT rate allowed for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_def_rating_last_10(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive rating over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average defensive rating over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT defensive_rating
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(defensive_rating), 2) as avg_def_rating
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.avg_def_rating if row.avg_def_rating is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent def rating for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent def rating for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_off_rating_last_10(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's offensive rating over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average offensive rating over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT offensive_rating
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(offensive_rating), 2) as avg_off_rating
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.avg_off_rating if row.avg_off_rating is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent off rating for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent off rating for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_rebounding_rate(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's rebounding rate (rebounds per possession) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Rebounding rate (rebounds/possession) over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT rebounds, possessions
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND possessions > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(rebounds) / NULLIF(AVG(possessions), 0), 2) as rebounding_rate
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.rebounding_rate if row.rebounding_rate is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent rebounding rate for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent rebounding rate for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_pace_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's pace variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of pace over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(pace), 2) as pace_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.pace_stddev if row.pace_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent pace variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent pace variance for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_ft_rate_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's FT rate variance (consistency) over last 10 games.

        Calculates the standard deviation of FT rate per 100 possessions,
        which shows how consistent/variable the team is in allowing FTs.

        High variance = unpredictable (some games allow many FTs, others few)
        Low variance = consistent (similar FT rate every game)

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of FT rate per 100 possessions over last 10 games,
                   rounded to 3 decimals. Returns 0.0 if insufficient data.
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT
                    opp_ft_attempts,
                    opponent_pace,
                    CASE
                        WHEN opponent_pace > 0 THEN
                            ROUND((opp_ft_attempts / opponent_pace) * 100, 3)
                        ELSE NULL
                    END as ft_rate_per_100
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND opp_ft_attempts IS NOT NULL
                  AND opponent_pace IS NOT NULL
                  AND opponent_pace > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND(STDDEV(ft_rate_per_100), 3) as ft_rate_stddev,
                COUNT(*) as games_count
            FROM recent_games
            WHERE ft_rate_per_100 IS NOT NULL
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                if row.ft_rate_stddev is not None and row.games_count >= 2:
                    return float(row.ft_rate_stddev)

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent FT rate variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent FT rate variance for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_def_rating_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive rating variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of defensive rating over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT defensive_rating
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(defensive_rating), 2) as def_rating_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.def_rating_stddev if row.def_rating_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent def rating variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent def rating variance for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_off_rating_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's offensive rating variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of offensive rating over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT offensive_rating
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(offensive_rating), 2) as off_rating_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.off_rating_stddev if row.off_rating_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent off rating variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent off rating variance for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_rebounding_rate_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's rebounding rate variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of rebounding rate over last 10 games, rounded to 3 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT
                    rebounds / NULLIF(possessions, 0) as rebounding_rate
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = @opponent_abbr
                  AND game_date < @game_date
                  AND game_date >= '2024-10-01'
                  AND possessions > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(rebounding_rate), 3) as rebounding_rate_stddev
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return row.rebounding_rate_stddev if row.rebounding_rate_stddev is not None else 0.0

            return 0.0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting opponent rebounding rate variance for {opponent_abbr}: {e}")
            return 0.0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting opponent rebounding rate variance for {opponent_abbr}: {e}")
            return 0.0

    def _get_star_teammates_out(self, team_abbr: str, game_date: date) -> int:
        """
        Count star teammates who are OUT or DOUBTFUL for the game.

        Star criteria (last 10 games):
        - Average points >= 18 PPG OR
        - Average minutes >= 28 MPG OR
        - Usage rate >= 25%

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Number of star teammates out (0-5 typical range)
        """
        try:
            query = f"""
            WITH team_roster AS (
                SELECT player_lookup
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE team_abbr = @team_abbr
                  AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                  AND roster_date <= @game_date
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= @game_date
                        AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                        AND team_abbr = @team_abbr
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 10 DAY)
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            star_players AS (
                SELECT s.player_lookup
                FROM player_recent_stats s
                INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
                WHERE s.avg_points >= 18
                   OR s.avg_minutes >= 28
                   OR s.avg_usage >= 25
            ),
            injured_players AS (
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
                  AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) = 1
            )
            SELECT COUNT(*) as star_teammates_out
            FROM star_players s
            INNER JOIN injured_players i ON s.player_lookup = i.player_lookup
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.star_teammates_out) if row.star_teammates_out is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting star teammates out for {team_abbr}: {e}")
            return 0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting star teammates out for {team_abbr}: {e}")
            return 0

    def _get_questionable_star_teammates(self, team_abbr: str, game_date: date) -> int:
        """
        Count star teammates who are QUESTIONABLE for the game.

        Star criteria (last 10 games):
        - Average points >= 18 PPG OR
        - Average minutes >= 28 MPG OR
        - Usage rate >= 25%

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Number of star teammates questionable (0-5 typical range)
        """
        try:
            query = f"""
            WITH team_roster AS (
                SELECT player_lookup
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE team_abbr = @team_abbr
                  AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                  AND roster_date <= @game_date
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= @game_date
                        AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                        AND team_abbr = @team_abbr
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 10 DAY)
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            star_players AS (
                SELECT s.player_lookup
                FROM player_recent_stats s
                INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
                WHERE s.avg_points >= 18
                   OR s.avg_minutes >= 28
                   OR s.avg_usage >= 25
            ),
            questionable_players AS (
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
                  AND UPPER(injury_status) = 'QUESTIONABLE'
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) = 1
            )
            SELECT COUNT(*) as questionable_star_teammates
            FROM star_players s
            INNER JOIN questionable_players q ON s.player_lookup = q.player_lookup
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.questionable_star_teammates) if row.questionable_star_teammates is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting questionable star teammates for {team_abbr}: {e}")
            return 0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting questionable star teammates for {team_abbr}: {e}")
            return 0

    def _get_star_tier_out(self, team_abbr: str, game_date: date) -> int:
        """
        Calculate weighted tier score for OUT/DOUBTFUL star teammates.

        Star tiers (based on PPG last 10 games):
        - Tier 1 (Superstar): 25+ PPG = 3 points
        - Tier 2 (Star): 18-24.99 PPG = 2 points
        - Tier 3 (Quality starter): <18 PPG but 28+ MPG or 25%+ usage = 1 point

        Args:
            team_abbr: Team abbreviation (e.g., 'LAL')
            game_date: Game date to check

        Returns:
            int: Weighted tier score (0-15 typical range)
        """
        try:
            query = f"""
            WITH team_roster AS (
                SELECT player_lookup
                FROM `{self.project_id}.nba_raw.espn_team_rosters`
                WHERE team_abbr = @team_abbr
                  AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                  AND roster_date <= @game_date
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= @game_date
                        AND roster_date >= DATE_SUB(@game_date, INTERVAL 90 DAY)
                        AND team_abbr = @team_abbr
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB(@game_date, INTERVAL 10 DAY)
                  AND game_date < @game_date
                  AND team_abbr = @team_abbr
                GROUP BY player_lookup
            ),
            star_players_with_tier AS (
                SELECT
                    s.player_lookup,
                    CASE
                        WHEN s.avg_points >= 25 THEN 3
                        WHEN s.avg_points >= 18 THEN 2
                        ELSE 1
                    END as tier_weight
                FROM player_recent_stats s
                INNER JOIN team_roster r ON s.player_lookup = r.player_lookup
                WHERE s.avg_points >= 18
                   OR s.avg_minutes >= 28
                   OR s.avg_usage >= 25
            ),
            injured_players AS (
                SELECT DISTINCT player_lookup
                FROM `{self.project_id}.nba_raw.nbac_injury_report`
                WHERE game_date = @game_date
                  AND team = @team_abbr
                  AND UPPER(injury_status) IN ('OUT', 'DOUBTFUL')
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY player_lookup
                    ORDER BY report_hour DESC
                ) = 1
            )
            SELECT SUM(s.tier_weight) as star_tier_out
            FROM star_players_with_tier s
            INNER JOIN injured_players i ON s.player_lookup = i.player_lookup
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )

            result = self.bq_client.query(query, job_config=job_config).result()
            for row in result:
                return int(row.star_tier_out) if row.star_tier_out is not None else 0

            return 0

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error getting star tier out for {team_abbr}: {e}")
            return 0
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error getting star tier out for {team_abbr}: {e}")
            return 0

    def _calculate_projected_usage_rate(self, player_lookup: str, team_abbr: str,
                                        game_date: date, star_teammates_out: int,
                                        opponent_team_abbr: str, historical_data: pd.DataFrame) -> Optional[float]:
        """
        Calculate projected usage rate based on multiple contextual factors.

        The projection combines:
        1. Historical baseline: Player's average usage rate over last 10 games
        2. Teammate availability: Boost when star teammates are out (their usage redistributes)
        3. Matchup context: Adjustment based on opponent's pace and defensive style
        4. Recent trend: Momentum adjustment based on last 5 vs last 10 games

        Formula:
            projected_usage = baseline_usage * (1 + injury_boost + matchup_adj + trend_adj)

        Args:
            player_lookup: Player identifier
            team_abbr: Player's team abbreviation
            game_date: Game date for context
            star_teammates_out: Count of star teammates marked OUT/DOUBTFUL
            opponent_team_abbr: Opponent team abbreviation
            historical_data: DataFrame of player's historical boxscores

        Returns:
            float: Projected usage rate (0-50 range typically), or None if insufficient data
        """
        try:
            # STEP 1: Get baseline usage from player_game_summary
            baseline_query = f"""
            WITH recent_games AS (
                SELECT usage_rate, game_date
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE player_lookup = @player_lookup
                  AND game_date < @game_date
                  AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
                  AND usage_rate IS NOT NULL
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT AVG(usage_rate) as avg_usage_l10, COUNT(*) as games_count
            FROM recent_games
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                ]
            )
            result = self.bq_client.query(baseline_query, job_config=job_config).result()
            row = next(result, None)

            if not row or row.avg_usage_l10 is None or row.games_count < 3:
                return None

            baseline_usage = float(row.avg_usage_l10)

            # STEP 2: Calculate injury boost (teammate availability)
            injury_boost = 0.0
            if star_teammates_out > 0:
                capped_stars_out = min(star_teammates_out, 3)
                base_boost_per_star = 0.03 if baseline_usage < 20 else 0.05
                injury_boost = capped_stars_out * base_boost_per_star

            # STEP 3: Calculate matchup adjustment (opponent context)
            matchup_adj = 0.0
            try:
                matchup_query = f"""
                WITH opponent_games AS (
                    SELECT pace, def_rating
                    FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                    WHERE team_abbr = @opponent_abbr
                      AND game_date < @game_date
                      AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
                    ORDER BY game_date DESC
                    LIMIT 10
                ),
                league_avg AS (
                    SELECT AVG(pace) as avg_pace, AVG(def_rating) as avg_def_rating
                    FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                    WHERE game_date < @game_date
                      AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
                )
                SELECT
                    (SELECT AVG(pace) FROM opponent_games) as opp_pace,
                    (SELECT AVG(def_rating) FROM opponent_games) as opp_def_rating,
                    (SELECT avg_pace FROM league_avg) as league_pace,
                    (SELECT avg_def_rating FROM league_avg) as league_def_rating
                """
                matchup_job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("opponent_abbr", "STRING", opponent_team_abbr),
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                    ]
                )
                matchup_result = self.bq_client.query(matchup_query, job_config=matchup_job_config).result()
                matchup_row = next(matchup_result, None)

                if matchup_row and matchup_row.opp_pace and matchup_row.league_pace:
                    pace_diff = (matchup_row.opp_pace - matchup_row.league_pace) / matchup_row.league_pace
                    matchup_adj += max(-0.03, min(0.03, pace_diff * 0.5))
                    if matchup_row.opp_def_rating and matchup_row.league_def_rating:
                        def_diff = (matchup_row.opp_def_rating - matchup_row.league_def_rating) / matchup_row.league_def_rating
                        matchup_adj += max(-0.02, min(0.02, def_diff * 0.3))
            except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded):
                pass  # Continue without matchup adjustment

            # STEP 4: Calculate recent trend adjustment
            trend_adj = 0.0
            try:
                trend_query = f"""
                WITH recent_5 AS (
                    SELECT AVG(usage_rate) as avg_usage FROM (
                        SELECT usage_rate FROM `{self.project_id}.nba_analytics.player_game_summary`
                        WHERE player_lookup = @player_lookup AND game_date < @game_date
                          AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY) AND usage_rate IS NOT NULL
                        ORDER BY game_date DESC LIMIT 5
                    )
                ),
                recent_10 AS (
                    SELECT AVG(usage_rate) as avg_usage FROM (
                        SELECT usage_rate FROM `{self.project_id}.nba_analytics.player_game_summary`
                        WHERE player_lookup = @player_lookup AND game_date < @game_date
                          AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY) AND usage_rate IS NOT NULL
                        ORDER BY game_date DESC LIMIT 10
                    )
                )
                SELECT (SELECT avg_usage FROM recent_5) as l5_usage, (SELECT avg_usage FROM recent_10) as l10_usage
                """
                trend_job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                    ]
                )
                trend_result = self.bq_client.query(trend_query, job_config=trend_job_config).result()
                trend_row = next(trend_result, None)
                if trend_row and trend_row.l5_usage and trend_row.l10_usage:
                    usage_momentum = (trend_row.l5_usage - trend_row.l10_usage) / trend_row.l10_usage
                    trend_adj = max(-0.05, min(0.05, usage_momentum * 0.5))
            except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded):
                pass  # Continue without trend adjustment

            # STEP 5: Calculate final projected usage
            total_adjustment = 1 + injury_boost + matchup_adj + trend_adj
            projected_usage = baseline_usage * total_adjustment
            projected_usage = max(5.0, min(50.0, projected_usage))

            logger.debug(
                f"Projected usage for {player_lookup}: baseline={baseline_usage:.1f}, "
                f"injury_boost={injury_boost:.3f}, matchup_adj={matchup_adj:.3f}, "
                f"trend_adj={trend_adj:.3f}, projected={projected_usage:.1f}"
            )
            return round(projected_usage, 1)

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error calculating projected usage for {player_lookup}: {e}")
            return None
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.error(f"Data error calculating projected usage for {player_lookup}: {e}")
            return None

    def _calculate_data_quality(self, historical_data: pd.DataFrame,
                                game_lines_info: Dict) -> Dict:
        """
        Calculate data quality metrics using centralized helper.

        Args:
            historical_data: DataFrame of historical boxscores
            game_lines_info: Dict with game lines

        Returns:
            Dict with quality fields (standard + legacy)
        """
        # Sample size determines tier
        games_count = len(historical_data)
        if games_count >= self.min_games_for_high_quality:
            tier = 'gold'
            score = 95.0
        elif games_count >= self.min_games_for_medium_quality:
            tier = 'silver'
            score = 75.0
        else:
            tier = 'bronze'
            score = 50.0

        # Build quality issues list
        issues = []
        if game_lines_info.get('game_spread') is None:
            issues.append('missing_game_spread')
        if game_lines_info.get('game_total') is None:
            issues.append('missing_game_total')
        if games_count < 3:
            issues.append(f'thin_sample:{games_count}/3')

        # Primary source used
        primary_source = 'bdl_player_boxscores'

        # Use centralized helper for standard quality columns
        quality_cols = build_quality_columns_with_legacy(
            tier=tier,
            score=score,
            issues=issues,
            sources=[primary_source],
        )

        # Add additional tracking fields
        quality_cols['primary_source_used'] = primary_source
        quality_cols['processed_with_issues'] = len(issues) > 0

        return quality_cols

    def _calculate_data_hash(self, record: Dict) -> str:
        """
        Calculate SHA256 hash of meaningful analytics fields.

        Pattern #3: Smart Reprocessing
        - Phase 4 processors extract this hash to detect changes
        - Comparison with previous hash detects meaningful changes
        - Unchanged hashes allow Phase 4 to skip expensive reprocessing

        Args:
            record: Dictionary containing analytics fields

        Returns:
            First 16 characters of SHA256 hash (sufficient for uniqueness)
        """
        hash_data = {field: record.get(field) for field in self.HASH_FIELDS}
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]

    def _build_source_tracking_fields(self) -> Dict:
        """
        Build source tracking fields for output record.

        Returns:
            Dict with all source tracking fields (hashes for data lineage)
        """
        import hashlib

        def compute_hash(source_key: str) -> Optional[str]:
            """Compute a hash of source metadata for change detection."""
            tracking = self.source_tracking.get(source_key, {})
            if not tracking.get('last_updated'):
                return None
            # Create hash from source metadata
            hash_input = f"{tracking.get('last_updated', '')}:{tracking.get('rows_found', 0)}"
            return hashlib.md5(hash_input.encode()).hexdigest()[:16]

        # Table expects hash fields for data lineage tracking
        return {
            'source_boxscore_hash': compute_hash('boxscore'),
            'source_schedule_hash': compute_hash('schedule'),
            'source_props_hash': compute_hash('props'),
            'source_game_lines_hash': compute_hash('game_lines'),
        }
    
    def _calculate_completeness(self, source_key: str) -> Optional[float]:
        """
        Calculate completeness percentage for a source.
        
        Args:
            source_key: Key in source_tracking dict
            
        Returns:
            Completeness percentage or None
        """
        rows_found = self.source_tracking[source_key]['rows_found']
        
        # Expected counts based on source type
        if source_key == 'boxscore':
            # Expect roughly 1 game per day for 30 days = ~30 games per player
            # But some players may have fewer (injury, rest, etc.)
            # Use a generous threshold
            rows_expected = self.lookback_days * 0.5  # Expect at least 15 games
        elif source_key == 'schedule':
            # Expect 1 game per player (since we're processing one date)
            rows_expected = len(self.players_to_process)
        elif source_key == 'props':
            # Expect 1 prop per player
            rows_expected = len(self.players_to_process)
        elif source_key == 'game_lines':
            # Expect lines for all unique games
            unique_games = len(set([p['game_id'] for p in self.players_to_process]))
            rows_expected = unique_games
        else:
            return None
        
        if rows_expected == 0:
            return 100.0
        
        completeness = (rows_found / rows_expected) * 100
        return min(completeness, 100.0)  # Cap at 100%
    
    def save_analytics(self) -> bool:
        """
        Save results to BigQuery using atomic MERGE pattern.

        MERGE pattern prevents duplicates by:
        1. Loading data to temp table
        2. Executing atomic MERGE (upsert) operation
        3. Cleaning up temp table

        This replaces the previous DELETE + INSERT pattern which was
        vulnerable to race conditions and streaming buffer issues.

        Returns:
            True if successful, False otherwise
        """
        if not self.transformed_data:
            logger.warning("No data to save")
            return True

        table_id = f"{self.project_id}.{self.table_name}"
        temp_table_id = None
        timing = {}
        overall_start = time.time()

        try:
            # Step 1: Get target table schema
            step_start = time.time()
            target_table = self.bq_client.get_table(table_id)
            target_schema = target_table.schema
            schema_fields = {field.name for field in target_schema}
            required_fields = {f.name for f in target_schema if f.mode == "REQUIRED"}
            timing['get_schema'] = time.time() - step_start
            logger.info(f"Got target schema ({timing['get_schema']:.2f}s)")

            # Step 2: Create temporary table
            step_start = time.time()
            temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
            temp_table = bigquery.Table(temp_table_id, schema=target_schema)
            self.bq_client.create_table(temp_table)
            timing['create_temp_table'] = time.time() - step_start
            logger.info(f"Created temp table ({timing['create_temp_table']:.2f}s)")

            # Step 3: Sanitize and filter data
            step_start = time.time()

            def sanitize_value(v):
                """Convert non-JSON-serializable values to None."""
                import math
                if v is None:
                    return None
                if isinstance(v, float):
                    if math.isnan(v) or math.isinf(v):
                        return None
                # Handle numpy types
                if hasattr(v, 'item'):  # numpy scalar
                    return v.item()
                return v

            current_utc = datetime.now(timezone.utc)
            filtered_data = []
            for record in self.transformed_data:
                out = {k: sanitize_value(v) for k, v in record.items() if k in schema_fields}
                # Ensure required timestamp fields
                if "processed_at" in required_fields and out.get("processed_at") is None:
                    out["processed_at"] = current_utc.isoformat()
                filtered_data.append(out)

            timing['sanitize_data'] = time.time() - step_start
            logger.info(f"Sanitized {len(filtered_data)} records ({timing['sanitize_data']:.2f}s)")

            # Step 4: Load data to temp table
            step_start = time.time()
            ndjson_data = "\n".join(json.dumps(row, default=str) for row in filtered_data)
            ndjson_bytes = ndjson_data.encode('utf-8')

            job_config = bigquery.LoadJobConfig(
                schema=target_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=False
            )

            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                temp_table_id,
                job_config=job_config
            )
            load_job.result(timeout=60)
            timing['load_temp_table'] = time.time() - step_start
            logger.info(f"Loaded {len(filtered_data)} rows to temp table ({timing['load_temp_table']:.2f}s)")

            # Step 5: Execute MERGE (atomic upsert)
            step_start = time.time()

            # Build list of all columns for UPDATE SET clause (exclude merge keys)
            # FIX: Use game_date instead of game_id to match PRIMARY_KEY_FIELDS
            # game_id can have inconsistent formats, game_date is always consistent
            merge_keys = {'player_lookup', 'game_date'}
            update_columns = [f.name for f in target_schema if f.name not in merge_keys]
            update_set_clause = ",\n                ".join(
                f"target.{col} = source.{col}" for col in update_columns
            )

            merge_query = f"""
            MERGE `{table_id}` AS target
            USING (
                SELECT * EXCEPT(row_num) FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY player_lookup, game_date
                        ORDER BY processed_at DESC
                    ) as row_num
                    FROM `{temp_table_id}`
                ) WHERE row_num = 1
            ) AS source
            ON target.player_lookup = source.player_lookup
               AND target.game_date = source.game_date
            WHEN MATCHED THEN
                UPDATE SET
                {update_set_clause}
            WHEN NOT MATCHED THEN
                INSERT ROW
            """

            merge_job = self.bq_client.query(merge_query)
            merge_job.result(timeout=60)

            timing['merge_operation'] = time.time() - step_start
            rows_affected = merge_job.num_dml_affected_rows or 0
            logger.info(f"MERGE completed: {rows_affected} rows affected ({timing['merge_operation']:.2f}s)")

            # Log total timing
            timing['total'] = time.time() - overall_start
            logger.info(
                f"✅ Save complete: {len(filtered_data)} records in {timing['total']:.2f}s "
                f"(schema: {timing['get_schema']:.1f}s, load: {timing['load_temp_table']:.1f}s, "
                f"merge: {timing['merge_operation']:.1f}s)"
            )

            return True

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            error_msg = str(e).lower()

            # Handle streaming buffer gracefully
            if "streaming buffer" in error_msg:
                logger.warning(
                    f"⚠️ MERGE blocked by streaming buffer - {len(self.transformed_data)} records skipped. "
                    f"Will succeed on next run."
                )
                return False

            logger.error(f"BigQuery error saving to BigQuery: {e}")
            return False
        except (KeyError, AttributeError, TypeError, ValueError, json.JSONDecodeError) as e:
            logger.error(f"Data error saving to BigQuery: {e}")
            return False

        finally:
            # Always cleanup temp table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.debug(f"Cleaned up temp table {temp_table_id}")
                except (GoogleAPIError, NotFound) as cleanup_e:
                    logger.warning(f"Failed to cleanup temp table: {cleanup_e}")
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def _parse_minutes(self, minutes_str: str) -> float:
        """
        Parse minutes string "MM:SS" to decimal.
        
        Args:
            minutes_str: Minutes in "MM:SS" format
            
        Returns:
            Decimal minutes
        """
        if not minutes_str or pd.isna(minutes_str):
            return 0.0
        
        try:
            if ':' in str(minutes_str):
                parts = str(minutes_str).split(':')
                minutes = int(parts[0])
                seconds = int(parts[1])
                return minutes + (seconds / 60.0)
            else:
                return float(minutes_str)
        except (ValueError, IndexError):
            logger.warning(f"Could not parse minutes: {minutes_str}")
            return 0.0
    
    def _extract_game_time(self, game_info: Dict) -> Optional[str]:
        """
        Extract game time in local arena timezone.

        Args:
            game_info: Dict containing game_date_est and arena_timezone

        Returns:
            Formatted time string like "7:30 PM ET" or None if unavailable
        """
        try:
            from zoneinfo import ZoneInfo
            from datetime import datetime

            # Get the game timestamp (stored as EST/ET in nbac_schedule)
            game_dt = game_info.get('game_date_est')
            if not game_dt:
                return None

            # Handle different input types
            if isinstance(game_dt, str):
                # Parse ISO format string
                game_dt = datetime.fromisoformat(game_dt.replace('Z', '+00:00'))
            elif not isinstance(game_dt, datetime):
                return None

            # Get arena timezone (default to Eastern if not specified)
            arena_tz_str = game_info.get('arena_timezone', 'America/New_York')
            if not arena_tz_str:
                arena_tz_str = 'America/New_York'

            # Convert to arena local time
            try:
                arena_tz = ZoneInfo(arena_tz_str)
            except (KeyError, ValueError):
                arena_tz = ZoneInfo('America/New_York')

            # If datetime is naive, assume it's Eastern time
            if game_dt.tzinfo is None:
                eastern = ZoneInfo('America/New_York')
                game_dt = game_dt.replace(tzinfo=eastern)

            local_dt = game_dt.astimezone(arena_tz)

            # Get timezone abbreviation
            tz_abbrev_map = {
                'America/New_York': 'ET',
                'America/Chicago': 'CT',
                'America/Denver': 'MT',
                'America/Los_Angeles': 'PT',
                'America/Phoenix': 'MST',
            }
            tz_abbr = tz_abbrev_map.get(arena_tz_str, local_dt.strftime('%Z'))

            # Format as "7:30 PM ET"
            return f"{local_dt.strftime('%I:%M %p').lstrip('0')} {tz_abbr}"

        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.debug(f"Could not extract game time: {e}")
            return None

    def _determine_season_phase(self, game_date: date, team_abbr: str = None) -> str:
        """
        Determine the current NBA season phase based on game date and team game count.

        Phase definitions:
        - preseason: Before regular season starts (typically early-mid October)
        - early_season: First 20 games per team (Oct-Nov typically)
        - mid_season: Games 21-60 (Dec-Feb typically)
        - all_star_break: All-Star Weekend period (mid-February)
        - post_all_star: After All-Star break until game 67 (late Feb-Mar)
        - playoff_push: Last 15 games of regular season (games 68-82, Mar-Apr)
        - playoffs: Postseason games including play-in (Apr-Jun)
        - offseason: July-September, no games scheduled

        Args:
            game_date: Date of game
            team_abbr: Optional team abbreviation for game-count based phases

        Returns:
            Season phase string: 'preseason', 'early_season', 'mid_season',
            'all_star_break', 'post_all_star', 'playoff_push', 'playoffs', or 'offseason'
        """
        # First check for offseason (no games typically Jul-Sep)
        if game_date.month in [7, 8, 9]:
            return 'offseason'

        # Try to get detailed phase from schedule data
        try:
            phase = self._get_season_phase_from_schedule(game_date, team_abbr)
            if phase:
                return phase
        except Exception as e:
            logger.debug(f"Error getting phase from schedule: {e}, using fallback")

        # Fallback: Use date-based heuristics
        return self._get_season_phase_fallback(game_date)

    def _get_season_phase_from_schedule(self, game_date: date, team_abbr: str = None) -> Optional[str]:
        """
        Query schedule to determine season phase with game type flags and team game counts.

        Args:
            game_date: Date of game
            team_abbr: Team abbreviation for game-count based sub-phases

        Returns:
            Season phase string or None if unable to determine
        """
        # Query schedule for game type flags
        query = f"""
        SELECT
            COALESCE(is_all_star, FALSE) as is_all_star,
            COALESCE(is_playoffs, FALSE) as is_playoffs,
            COALESCE(is_regular_season, FALSE) as is_regular_season,
            playoff_round,
            season_year
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date = @game_date
        LIMIT 1
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            rows = list(result)

            if not rows:
                # No games on this date - could be offseason or gap
                return self._check_if_all_star_break(game_date)

            row = rows[0]

            # Check for All-Star Weekend
            if row.is_all_star:
                return 'all_star_break'

            # Check for playoffs (including play-in)
            if row.is_playoffs:
                return 'playoffs'

            # Check for regular season - need to determine sub-phase
            if row.is_regular_season:
                return self._determine_regular_season_subphase(
                    game_date, team_abbr, row.season_year
                )

            # If not regular season and not playoffs, likely preseason
            return 'preseason'

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.debug(f"BigQuery error checking season phase: {e}")
            return None

    def _check_if_all_star_break(self, game_date: date) -> Optional[str]:
        """
        Check if a date with no games falls within All-Star break period.

        All-Star break is typically mid-February, spanning about a week.

        Args:
            game_date: Date to check

        Returns:
            'all_star_break' if within break period, None otherwise
        """
        # All-Star break is typically the weekend around Presidents Day (third Monday of Feb)
        # Usually spans Friday to Wednesday of that week
        if game_date.month != 2:
            return None

        # Query for All-Star games in the same season to find break dates
        season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

        query = f"""
        SELECT
            MIN(game_date) as all_star_start,
            MAX(game_date) as all_star_end
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE season_year = @season_year
          AND is_all_star = TRUE
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            row = list(result)[0]

            if row.all_star_start and row.all_star_end:
                # Expand window to include days around All-Star games
                break_start = row.all_star_start - timedelta(days=2)
                break_end = row.all_star_end + timedelta(days=1)

                if break_start <= game_date <= break_end:
                    return 'all_star_break'

        except Exception as e:
            logger.debug(f"Error checking All-Star break: {e}")

        return None

    def _determine_regular_season_subphase(
        self, game_date: date, team_abbr: str = None, season_year: int = None
    ) -> str:
        """
        Determine the sub-phase within the regular season based on team game count.

        Sub-phases:
        - early_season: Games 1-20
        - mid_season: Games 21-60
        - post_all_star: Games 61-67 (after All-Star break)
        - playoff_push: Games 68-82 (last 15 games)

        Args:
            game_date: Date of game
            team_abbr: Team abbreviation to count games for
            season_year: Season year (e.g., 2024 for 2024-25 season)

        Returns:
            Sub-phase string
        """
        # If no team specified, use first available team from players_to_process
        if not team_abbr and self.players_to_process:
            team_abbr = self.players_to_process[0].get('team_abbr')

        if not team_abbr:
            # No team info - use date-based fallback
            return self._get_regular_season_subphase_by_date(game_date)

        if not season_year:
            season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

        # Count team's games played up to this date
        team_game_count = self._get_team_game_count(team_abbr, game_date, season_year)

        if team_game_count is None:
            return self._get_regular_season_subphase_by_date(game_date)

        # Check if we're past the All-Star break
        is_post_all_star = self._is_after_all_star_break(game_date, season_year)

        # Determine phase based on game count
        if team_game_count <= 20:
            return 'early_season'
        elif team_game_count <= 60:
            return 'mid_season'
        elif team_game_count <= 67:
            return 'post_all_star' if is_post_all_star else 'mid_season'
        else:
            return 'playoff_push'

    def _get_team_game_count(
        self, team_abbr: str, game_date: date, season_year: int
    ) -> Optional[int]:
        """
        Count how many regular season games a team has played up to (but not including) game_date.

        Args:
            team_abbr: Team abbreviation
            game_date: Date of the upcoming game
            season_year: Season year

        Returns:
            Number of games played, or None if query fails
        """
        # Use NBATeamMapper to get all abbreviation variants
        try:
            team_info = get_team_info(team_abbr)
            abbr_variants = [team_abbr]
            if team_info:
                abbr_variants = list(set([
                    team_info.nba_tricode,
                    team_info.br_tricode,
                    team_info.espn_tricode
                ]))
        except Exception:
            abbr_variants = [team_abbr]

        # Build IN clause for team variants
        variants_str = "', '".join(abbr_variants)

        query = f"""
        SELECT COUNT(*) as games_played
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE season_year = @season_year
          AND is_regular_season = TRUE
          AND game_date < @game_date
          AND game_status = 3
          AND (home_team_tricode IN ('{variants_str}')
               OR away_team_tricode IN ('{variants_str}'))
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("season_year", "INT64", season_year),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            row = list(result)[0]
            return row.games_played
        except Exception as e:
            logger.debug(f"Error counting team games: {e}")
            return None

    def _is_after_all_star_break(self, game_date: date, season_year: int) -> bool:
        """
        Check if the game_date is after the All-Star break for the given season.

        Args:
            game_date: Date to check
            season_year: Season year

        Returns:
            True if after All-Star break, False otherwise
        """
        query = f"""
        SELECT MAX(game_date) as all_star_end
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE season_year = @season_year
          AND is_all_star = TRUE
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            row = list(result)[0]

            if row.all_star_end:
                return game_date > row.all_star_end

        except Exception as e:
            logger.debug(f"Error checking All-Star break timing: {e}")

        # Fallback: use typical All-Star timing (mid-February)
        return game_date.month >= 2 and game_date.day >= 20

    def _get_regular_season_subphase_by_date(self, game_date: date) -> str:
        """
        Fallback: Determine regular season sub-phase using date-based heuristics.

        Used when team game count is not available.

        Args:
            game_date: Date of game

        Returns:
            Sub-phase string based on typical season timing
        """
        month = game_date.month
        day = game_date.day

        # October-November: Early season
        if month in [10, 11]:
            return 'early_season'

        # December-early February: Mid season
        if month == 12:
            return 'mid_season'

        if month == 1:
            return 'mid_season'

        if month == 2:
            # Around mid-February is All-Star break
            if 12 <= day <= 20:
                return 'all_star_break'
            elif day > 20:
                return 'post_all_star'
            else:
                return 'mid_season'

        # March: Post All-Star / Playoff push
        if month == 3:
            if day <= 15:
                return 'post_all_star'
            else:
                return 'playoff_push'

        # April: Playoff push (early) or Playoffs (late)
        if month == 4:
            if day <= 12:
                return 'playoff_push'
            else:
                return 'playoffs'

        # May-June: Playoffs
        if month in [5, 6]:
            return 'playoffs'

        return 'offseason'

    def _get_season_phase_fallback(self, game_date: date) -> str:
        """
        Simple date-based fallback for season phase detection.

        Used when schedule data is not available.

        Args:
            game_date: Date of game

        Returns:
            Season phase string
        """
        month = game_date.month
        day = game_date.day

        # July-September: Offseason
        if month in [7, 8, 9]:
            return 'offseason'

        # October: Could be preseason (first half) or early season (second half)
        if month == 10:
            if day <= 15:
                return 'preseason'
            else:
                return 'early_season'

        # November: Early season
        if month == 11:
            return 'early_season'

        # December-January: Mid season
        if month in [12, 1]:
            return 'mid_season'

        # February: Mid season / All-Star break
        if month == 2:
            if 12 <= day <= 20:
                return 'all_star_break'
            elif day > 20:
                return 'post_all_star'
            else:
                return 'mid_season'

        # March: Post All-Star / Playoff push
        if month == 3:
            if day <= 15:
                return 'post_all_star'
            else:
                return 'playoff_push'

        # April: Playoff push (early) or Playoffs (late)
        if month == 4:
            if day <= 12:
                return 'playoff_push'
            else:
                return 'playoffs'

        # May-June: Playoffs
        if month in [5, 6]:
            return 'playoffs'

        return 'offseason'

    # ============================================================
    # TIMING ISSUE PREVENTION (2026-01-09)
    # Pre-flight check for props availability and 0% coverage alert
    # ============================================================

    def _check_props_readiness(self, target_date: date, min_players: int = 20) -> Dict:
        """
        Pre-flight check: Are betting props available for this date?

        This prevents the timing race condition where UPGC runs before
        BettingPros props are scraped, resulting in 0% prop coverage.

        Args:
            target_date: Date to check for props
            min_players: Minimum players with props required (default: 20)

        Returns:
            Dict with 'ready' (bool), 'player_count' (int), 'message' (str)
        """
        query = f"""
        SELECT COUNT(DISTINCT player_lookup) as player_count
        FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
        WHERE game_date = @target_date AND is_active = TRUE
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("target_date", "DATE", target_date)
            ]
        )

        try:
            result = self.bq_client.query(query, job_config=job_config).result()
            row = list(result)[0]
            player_count = row.player_count

            if player_count >= min_players:
                return {
                    'ready': True,
                    'player_count': player_count,
                    'message': f'Props ready: {player_count} players have props'
                }
            else:
                return {
                    'ready': False,
                    'player_count': player_count,
                    'message': f'Props NOT ready: only {player_count}/{min_players} players have props'
                }
        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.warning(f"BigQuery error in props readiness check: {e}")
            return {
                'ready': True,  # Don't block on check failure
                'player_count': 0,
                'message': f'Props check failed (proceeding anyway): {e}'
            }
        except (KeyError, AttributeError, TypeError, IndexError) as e:
            logger.warning(f"Data error in props readiness check: {e}")
            return {
                'ready': True,  # Don't block on check failure
                'player_count': 0,
                'message': f'Props check failed (proceeding anyway): {e}'
            }

    def _send_prop_coverage_alert(self, target_date: date, total_players: int,
                                   players_with_props: int, prop_pct: float) -> None:
        """
        Send alert when prop coverage is critically low (0% or near-0%).

        This alerts operations when the timing race condition has occurred,
        allowing for manual intervention or automated re-processing.

        Args:
            target_date: Date being processed
            total_players: Total players processed
            players_with_props: Players with prop lines
            prop_pct: Percentage of players with props
        """
        try:
            from shared.alerts.alert_manager import AlertManager

            alert_mgr = AlertManager()
            alert_mgr.send_alert(
                severity='critical' if prop_pct == 0 else 'warning',
                title=f'UPGC: {"0%" if prop_pct == 0 else "Low"} Prop Coverage - Timing Issue',
                message=(
                    f'UPGC completed for {target_date} with only {prop_pct:.1f}% prop coverage. '
                    f'({players_with_props}/{total_players} players have props). '
                    f'This typically indicates a timing race condition where UPGC ran before '
                    f'BettingPros props were scraped. Consider re-running UPGC.'
                ),
                category='upgc_prop_coverage',
                context={
                    'game_date': target_date.isoformat(),
                    'total_players': total_players,
                    'players_with_props': players_with_props,
                    'prop_coverage_pct': prop_pct
                }
            )
            logger.warning(
                f"🚨 ALERT SENT: {prop_pct:.1f}% prop coverage for {target_date} "
                f"({players_with_props}/{total_players})"
            )
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            # Don't fail processing if alert fails
            logger.error(f"Failed to send prop coverage alert: {e}")

    def _send_roster_coverage_alert(self, target_date: date, teams_count: int,
                                     players_count: int) -> None:
        """
        Send alert when roster/team coverage is critically low.

        This alerts operations when the roster data is incomplete,
        typically due to ESPN scraper failures or roster query issues.

        Args:
            target_date: Date being processed
            teams_count: Number of unique teams found
            players_count: Total players found
        """
        try:
            from shared.alerts.alert_manager import AlertManager

            alert_mgr = AlertManager()
            alert_mgr.send_alert(
                severity='critical',
                title=f'UPGC: Low Roster Coverage - Only {teams_count} Teams',
                message=(
                    f'UPGC for {target_date} found only {teams_count} teams ({players_count} players). '
                    f'Expected 10-16 teams for a typical game day. '
                    f'This typically indicates ESPN roster scraper failure or schedule data missing. '
                    f'Check: 1) ESPN roster scraper status 2) nbac_schedule for {target_date} '
                    f'3) espn_team_rosters latest date.'
                ),
                category='upgc_roster_coverage',
                context={
                    'game_date': target_date.isoformat(),
                    'teams_count': teams_count,
                    'players_count': players_count,
                    'expected_teams': '10-16'
                }
            )
            logger.warning(
                f"🚨 ALERT SENT: Low roster coverage - only {teams_count} teams for {target_date}"
            )
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            # Don't fail processing if alert fails
            logger.error(f"Failed to send roster coverage alert: {e}")


# Entry point for script execution
if __name__ == '__main__':
    import sys
    import argparse
    from datetime import date

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description="Process upcoming player game context")
    parser.add_argument('target_date', help='Target date (YYYY-MM-DD)')
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 4 (for backfills)'
    )

    args = parser.parse_args()

    target_date = date.fromisoformat(args.target_date)

    processor = UpcomingPlayerGameContextProcessor()

    # Note: This processor uses process_date() instead of run()
    # The skip_downstream_trigger flag would need to be passed if process_date
    # were updated to accept opts. For now, we add the flag for consistency.
    result = processor.process_date(target_date)

    print(f"\nProcessing Result:")
    print(f"Status: {result['status']}")
    print(f"Players Processed: {result['players_processed']}")
    print(f"Players Failed: {result['players_failed']}")

    if result.get('errors'):
        print(f"\nErrors:")
        for error in result['errors'][:10]:  # Show first 10 errors
            print(f"  - {error}")