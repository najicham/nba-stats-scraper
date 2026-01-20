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
            
        except Exception as e:
            logger.error(f"Error processing date {target_date}: {e}", exc_info=True)
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
        WHERE game_date = '{self.target_date}'
        """

        try:
            result = self.bq_client.query(gamebook_check_query).result(timeout=60)
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

        except Exception as e:
            logger.warning(f"Error checking gamebook availability: {e} - defaulting to DAILY mode")
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
            WHERE game_date = '{self.target_date}'
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
            WHERE roster_date >= '{roster_start}'
              AND roster_date <= '{roster_end}'
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
            WHERE r.roster_date >= '{roster_start}'
              AND r.roster_date <= '{roster_end}'
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
            WHERE report_date = '{self.target_date}'
              AND player_lookup IS NOT NULL
        ),
        props AS (
            -- Check which players have prop lines (from either source)
            SELECT DISTINCT
                player_lookup,
                points_line,
                'odds_api' as prop_source
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = '{self.target_date}'
              AND player_lookup IS NOT NULL
            UNION DISTINCT
            SELECT DISTINCT
                player_lookup,
                points_line,
                'bettingpros' as prop_source
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = '{self.target_date}'
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

        try:
            df = self.bq_client.query(daily_query).to_dataframe()

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

        except Exception as e:
            logger.error(f"Error extracting players (daily mode): {e}")
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
            WHERE game_date = '{self.target_date}'
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
            WHERE g.game_date = '{self.target_date}'
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
            WHERE game_date = '{self.target_date}'
              AND player_lookup IS NOT NULL
            UNION DISTINCT
            SELECT DISTINCT
                player_lookup,
                points_line,
                'bettingpros' as prop_source
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = '{self.target_date}'
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

        try:
            df = self.bq_client.query(backfill_query).to_dataframe()

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

        except Exception as e:
            logger.error(f"Error extracting players (backfill mode): {e}")
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
            WHERE bp.game_date = '{self.target_date}'
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
            WHERE game_date = '{self.target_date}'
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

        try:
            df = self.bq_client.query(bettingpros_query).to_dataframe()
            logger.info(f"BettingPros fallback: Found {len(df)} players for {self.target_date}")
            return df
        except Exception as e:
            logger.error(f"Error extracting from BettingPros: {e}")
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
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        ORDER BY game_date, game_date_est
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            
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
            
        except Exception as e:
            logger.error(f"Error extracting schedule data: {e}")
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
        player_lookups_str = "', '".join(player_lookups)
        
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
        WHERE player_lookup IN ('{player_lookups_str}')
          AND game_date >= '{start_date}'
          AND game_date < '{self.target_date}'
        ORDER BY player_lookup, game_date DESC
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            
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
            
            # TODO: Implement fallback to nbac_player_boxscores if BDL insufficient
            # TODO: Implement last resort fallback to nbac_gamebook_player_stats
            
        except Exception as e:
            logger.error(f"Error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise
    
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
        player_lookups_str = "', '".join(player_lookups)

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
            WHERE player_lookup IN ('{player_lookups_str}')
              AND game_date = '{self.target_date}'
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
            WHERE player_lookup IN ('{player_lookups_str}')
              AND game_date = '{self.target_date}'
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

        try:
            df = self.bq_client.query(batch_query).to_dataframe()
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

        except Exception as e:
            logger.error(f"Error in batch prop lines query: {e}")
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
        player_lookups_str = "', '".join(player_lookups)

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
            WHERE player_lookup IN ('{player_lookups_str}')
              AND game_date = '{self.target_date}'
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

        try:
            df = self.bq_client.query(batch_query).to_dataframe()

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

        except Exception as e:
            logger.error(f"Error extracting prop lines from BettingPros: {e}")
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
                
            except Exception as e:
                logger.warning(f"Error extracting game lines for {game_id}: {e}")
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
            WHERE game_date = '{self.target_date}'
              AND home_team_abbr = '{home_team}'
              AND away_team_abbr = '{away_team}'
              AND market_key = '{market_key}'
        ),
        opening_lines AS (
            SELECT
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN earliest_snapshot
            WHERE lines.game_date = '{self.target_date}'
              AND lines.home_team_abbr = '{home_team}'
              AND lines.away_team_abbr = '{away_team}'
              AND lines.market_key = '{market_key}'
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
            WHERE game_date = '{self.target_date}'
              AND home_team_abbr = '{home_team}'
              AND away_team_abbr = '{away_team}'
              AND market_key = '{market_key}'
        ),
        current_lines AS (
            SELECT
                outcome_point,
                bookmaker_key
            FROM `{self.project_id}.nba_raw.odds_api_game_lines` lines
            CROSS JOIN latest_snapshot
            WHERE lines.game_date = '{self.target_date}'
              AND lines.home_team_abbr = '{home_team}'
              AND lines.away_team_abbr = '{away_team}'
              AND lines.market_key = '{market_key}'
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
        
        try:
            opening_df = self.bq_client.query(opening_query).to_dataframe()
            current_df = self.bq_client.query(current_query).to_dataframe()
            
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
            
        except Exception as e:
            logger.warning(f"Error getting {market_key} consensus for {game_id}: {e}")
            prefix = 'spread' if market_key == 'spreads' else 'total'
            return {
                f'opening_{prefix}': None,
                f'game_{prefix}': None,
                f'{prefix}_movement': None,
                f'{prefix}_source': None
            }
    
    def _extract_rosters(self) -> None:
        """Extract current roster data (optional enhancement)."""
        # TODO: Implement roster extraction from nba_raw.espn_team_rosters
        # For now, we'll determine team from recent boxscores
        pass
    
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

        except Exception as e:
            logger.warning(f"Error extracting injury data: {e}. Continuing without injury info.")
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

        except Exception as e:
            logger.warning(f"Registry lookup failed: {e}. Continuing without universal IDs.")
            self.registry = {}

    # ========================================================================
    # CIRCUIT BREAKER METHODS (Week 5 - Completeness Checking)
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
                    except Exception as e:
                        logger.warning(f"Completeness check for {window_name} failed: {e}")
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
        except Exception as e:
            # Issue #3: Fail-closed - raise exception instead of returning fake data
            logger.error(
                f"Completeness checking FAILED ({type(e).__name__}: {e}). "
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
                except Exception as e:
                    logger.error(f"Error processing {player_info['player_lookup']}: {e}")
                    failures.append({
                        'player_lookup': player_info['player_lookup'],
                        'game_id': player_info['game_id'],
                        'reason': str(e),
                        'category': 'PROCESSING_ERROR'
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

        except Exception as e:
            return (False, {
                'player_lookup': player_lookup,
                'game_id': game_id,
                'reason': str(e),
                'category': 'PROCESSING_ERROR'
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

            except Exception as e:
                logger.error(f"Error calculating context for {player_lookup}: {e}")
                self.failed_entities.append({
                    'player_lookup': player_lookup,
                    'game_id': game_id,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR'
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
            'spread_public_betting_pct': None,  # TODO: future
            
            # Game total context
            'game_total': game_lines_info.get('game_total'),
            'opening_total': game_lines_info.get('opening_total'),
            'total_movement': game_lines_info.get('total_movement'),
            'game_total_source': game_lines_info.get('total_source'),
            'total_public_betting_pct': None,  # TODO: future
            
            # Pre-game context
            'pace_differential': pace_differential,
            'opponent_pace_last_10': opponent_pace_last_10,
            'game_start_time_local': self._extract_game_time(game_info),
            'opponent_ft_rate_allowed': opponent_ft_rate_allowed,
            'home_game': (team_abbr == game_info['home_team_abbr']),
            'back_to_back': fatigue_metrics['back_to_back'],
            'season_phase': self._determine_season_phase(self.target_date),
            'projected_usage_rate': None,  # TODO: future
            
            # Fatigue metrics
            **fatigue_metrics,
            
            # Travel context (all TODO: future)
            'travel_miles': None,
            'time_zone_changes': None,
            'consecutive_road_games': None,
            'miles_traveled_last_14_days': None,
            'time_zones_crossed_last_14_days': None,
            
            # Player characteristics
            'player_age': None,  # TODO: from roster
            
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

            # Forward-looking schedule (TODO: future)
            'next_game_days_rest': 0,
            'games_in_next_7_days': 0,
            'next_opponent_win_pct': None,
            'next_game_is_primetime': False,
            
            # Opponent asymmetry (TODO: future)
            'opponent_days_rest': 0,
            'opponent_games_in_next_7_days': 0,
            'opponent_next_game_days_rest': 0,
            
            # Real-time updates
            'player_status': self.injuries.get(player_lookup, {}).get('status'),
            'injury_report': self.injuries.get(player_lookup, {}).get('report'),
            'star_teammates_out': star_teammates_out,  # Session 106
            'questionable_star_teammates': questionable_star_teammates,  # Session 107
            'star_tier_out': star_tier_out,  # Session 107
            'probable_teammates': None,  # TODO: future
            
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
            'avg_usage_rate_last_7_games': None,  # TODO: future (needs play-by-play)
            'fourth_quarter_minutes_last_7': None,  # TODO: future
            'clutch_minutes_last_7_games': None,  # TODO: future
            'back_to_back': back_to_back
        }
    
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
                WHERE team_abbr = '{team_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            ),
            recent_opponent AS (
                SELECT pace
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT
                ROUND((SELECT AVG(pace) FROM recent_team) - (SELECT AVG(pace) FROM recent_opponent), 2) as pace_diff
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.pace_diff if row.pace_diff is not None else 0.0

            logger.warning(f"No pace data found for {team_abbr} vs {opponent_abbr}")
            return 0.0

        except Exception as e:
            logger.error(f"Error calculating pace differential for {team_abbr} vs {opponent_abbr}: {e}")
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
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(pace), 2) as avg_pace
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.avg_pace if row.avg_pace is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent pace for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_ft_rate_allowed(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's defensive FT rate allowed (last 10 games).

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Average opponent FT attempts allowed per game (last 10), rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT opp_ft_attempts
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(opp_ft_attempts), 2) as avg_opp_fta
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.avg_opp_fta if row.avg_opp_fta is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting FT rate allowed for {opponent_abbr}: {e}")
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
                WHERE defending_team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(defensive_rating), 2) as avg_def_rating
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.avg_def_rating if row.avg_def_rating is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent def rating for {opponent_abbr}: {e}")
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
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(offensive_rating), 2) as avg_off_rating
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.avg_off_rating if row.avg_off_rating is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent off rating for {opponent_abbr}: {e}")
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
                SELECT total_rebounds, possessions
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                  AND possessions > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(AVG(total_rebounds) / NULLIF(AVG(possessions), 0), 2) as rebounding_rate
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.rebounding_rate if row.rebounding_rate is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent rebounding rate for {opponent_abbr}: {e}")
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
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(pace), 2) as pace_stddev
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.pace_stddev if row.pace_stddev is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent pace variance for {opponent_abbr}: {e}")
            return 0.0

    def _get_opponent_ft_rate_variance(self, opponent_abbr: str, game_date: date) -> float:
        """
        Get opponent's FT rate variance (consistency) over last 10 games.

        Args:
            opponent_abbr: Opponent team abbreviation
            game_date: Game date to filter historical data

        Returns:
            float: Standard deviation of FT attempts allowed over last 10 games, rounded to 2 decimals
        """
        try:
            query = f"""
            WITH recent_games AS (
                SELECT opp_ft_attempts
                FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
                WHERE defending_team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(opp_ft_attempts), 2) as ft_rate_stddev
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.ft_rate_stddev if row.ft_rate_stddev is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent FT rate variance for {opponent_abbr}: {e}")
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
                WHERE defending_team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(defensive_rating), 2) as def_rating_stddev
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.def_rating_stddev if row.def_rating_stddev is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent def rating variance for {opponent_abbr}: {e}")
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
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(offensive_rating), 2) as off_rating_stddev
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.off_rating_stddev if row.off_rating_stddev is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent off rating variance for {opponent_abbr}: {e}")
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
                    total_rebounds / NULLIF(possessions, 0) as rebounding_rate
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE team_abbr = '{opponent_abbr}'
                  AND game_date < '{game_date}'
                  AND game_date >= '2024-10-01'
                  AND possessions > 0
                ORDER BY game_date DESC
                LIMIT 10
            )
            SELECT ROUND(STDDEV(rebounding_rate), 3) as rebounding_rate_stddev
            FROM recent_games
            """

            result = self.bq_client.query(query).result()
            for row in result:
                return row.rebounding_rate_stddev if row.rebounding_rate_stddev is not None else 0.0

            return 0.0

        except Exception as e:
            logger.error(f"Error getting opponent rebounding rate variance for {opponent_abbr}: {e}")
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
                WHERE team_abbr = '{team_abbr}'
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= '{game_date}'
                        AND team_abbr = '{team_abbr}'
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 10 DAY)
                  AND game_date < '{game_date}'
                  AND team_abbr = '{team_abbr}'
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
                WHERE game_date = '{game_date}'
                  AND team = '{team_abbr}'
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

            result = self.bq_client.query(query).result()
            for row in result:
                return int(row.star_teammates_out) if row.star_teammates_out is not None else 0

            return 0

        except Exception as e:
            logger.error(f"Error getting star teammates out for {team_abbr}: {e}")
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
                WHERE team_abbr = '{team_abbr}'
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= '{game_date}'
                        AND team_abbr = '{team_abbr}'
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 10 DAY)
                  AND game_date < '{game_date}'
                  AND team_abbr = '{team_abbr}'
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
                WHERE game_date = '{game_date}'
                  AND team = '{team_abbr}'
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

            result = self.bq_client.query(query).result()
            for row in result:
                return int(row.questionable_star_teammates) if row.questionable_star_teammates is not None else 0

            return 0

        except Exception as e:
            logger.error(f"Error getting questionable star teammates for {team_abbr}: {e}")
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
                WHERE team_abbr = '{team_abbr}'
                  AND roster_date = (
                      SELECT MAX(roster_date)
                      FROM `{self.project_id}.nba_raw.espn_team_rosters`
                      WHERE roster_date <= '{game_date}'
                        AND team_abbr = '{team_abbr}'
                  )
            ),
            player_recent_stats AS (
                SELECT
                    player_lookup,
                    AVG(points) as avg_points,
                    AVG(minutes_played) as avg_minutes,
                    AVG(usage_rate) as avg_usage
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 10 DAY)
                  AND game_date < '{game_date}'
                  AND team_abbr = '{team_abbr}'
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
                WHERE game_date = '{game_date}'
                  AND team = '{team_abbr}'
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

            result = self.bq_client.query(query).result()
            for row in result:
                return int(row.star_tier_out) if row.star_tier_out is not None else 0

            return 0

        except Exception as e:
            logger.error(f"Error getting star tier out for {team_abbr}: {e}")
            return 0

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

        except Exception as e:
            error_msg = str(e).lower()

            # Handle streaming buffer gracefully
            if "streaming buffer" in error_msg:
                logger.warning(
                    f"⚠️ MERGE blocked by streaming buffer - {len(self.transformed_data)} records skipped. "
                    f"Will succeed on next run."
                )
                return False

            logger.error(f"Error saving to BigQuery: {e}")
            return False

        finally:
            # Always cleanup temp table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.debug(f"Cleaned up temp table {temp_table_id}")
                except Exception as cleanup_e:
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
        """Extract game time in local timezone."""
        # TODO: Implement timezone conversion
        # For now, just return None
        return None
    
    def _determine_season_phase(self, game_date: date) -> str:
        """
        Determine season phase based on date.
        
        Args:
            game_date: Date of game
            
        Returns:
            'early', 'mid', 'late', or 'playoffs'
        """
        # TODO: Implement proper season phase detection
        # For now, use simple month-based logic
        
        month = game_date.month
        
        if month in [10, 11]:
            return 'early'
        elif month in [12, 1, 2]:
            return 'mid'
        elif month in [3, 4]:
            return 'late'
        else:
            return 'playoffs'

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
        except Exception as e:
            logger.warning(f"Props readiness check failed: {e}")
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
        except Exception as e:
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
        except Exception as e:
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