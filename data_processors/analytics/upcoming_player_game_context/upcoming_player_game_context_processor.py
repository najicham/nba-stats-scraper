#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py

Upcoming Player Game Context Processor - Phase 3 Analytics

Generates comprehensive pre-game context for ALL players with games scheduled.
Combines historical performance, fatigue metrics, prop betting context, and game
situation factors.

REFACTORED: This file has been split into modules for maintainability:
- player_stats.py: Fatigue and performance metrics
- team_context.py: Opponent metrics and variance calculations
- travel_context.py: Travel distance and timezone calculations
- betting_data.py: Prop lines, game lines, and public betting

FIXES IN THIS VERSION:
- Fixed KeyError when handling players with no historical data (empty DataFrame)
- Made error return dict consistent with success return (includes 'players_failed')
- Fixed deprecation warnings (datetime.utcnow() -> datetime.now(timezone.utc))
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

# Extracted modules for maintainability
from .player_stats import (
    calculate_fatigue_metrics,
    calculate_performance_metrics,
    parse_minutes
)
from .team_context import TeamContextCalculator
from .travel_context import TravelContextCalculator
from .betting_data import BettingDataExtractor

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

        # Initialize extracted module helpers
        self._team_context_calculator = None  # Lazy-loaded
        self._travel_context_calculator = None  # Lazy-loaded
        self._betting_data_extractor = None  # Lazy-loaded

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

    def _get_team_context_calculator(self) -> TeamContextCalculator:
        """Lazy-load team context calculator."""
        if self._team_context_calculator is None:
            self._team_context_calculator = TeamContextCalculator(self.bq_client, self.project_id)
        return self._team_context_calculator

    def _get_travel_context_calculator(self) -> TravelContextCalculator:
        """Lazy-load travel context calculator."""
        if self._travel_context_calculator is None:
            self._travel_context_calculator = TravelContextCalculator(self.project_id)
        return self._travel_context_calculator

    def _get_betting_data_extractor(self) -> BettingDataExtractor:
        """Lazy-load betting data extractor."""
        if self._betting_data_extractor is None:
            self._betting_data_extractor = BettingDataExtractor(self.bq_client, self.project_id)
        return self._betting_data_extractor

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
            logger.info(f"SMART REPROCESSING: Skipping processing - {reason}")
            self.players_to_process = []
            return

        logger.info(f"PROCESSING: {reason}")

        # PRE-FLIGHT CHECK: Verify props are available (2026-01-09 timing fix)
        # This prevents 0% prop coverage issues when UPGC runs before props are scraped
        props_check = self._check_props_readiness(self.target_date)
        if not props_check['ready']:
            logger.warning(f"PROPS PRE-FLIGHT: {props_check['message']}")
            # Don't fail - continue processing but log warning
            # The 0% coverage alert at the end will catch actual problems
        else:
            logger.info(f"PROPS PRE-FLIGHT: {props_check['message']}")

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
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
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

            # Store players to process (vectorized)
            players_with_props = df['has_prop_line'].fillna(False).sum()

            # Convert DataFrame to list of dicts efficiently
            self.players_to_process.extend([
                {
                    'player_lookup': row.player_lookup,
                    'game_id': row.game_id,
                    'team_abbr': row.team_abbr if hasattr(row, 'team_abbr') else None,
                    'home_team_abbr': row.home_team_abbr,
                    'away_team_abbr': row.away_team_abbr,
                    'has_prop_line': bool(row.has_prop_line) if hasattr(row, 'has_prop_line') else False,
                    'current_points_line': row.points_line if hasattr(row, 'points_line') else None,
                    'prop_source': row.prop_source if hasattr(row, 'prop_source') else None,
                    'injury_status': row.injury_status if hasattr(row, 'injury_status') else None
                }
                for row in df.itertuples()
            ])

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
                    f"LOW ROSTER COVERAGE: Only {teams_count} teams found for {self.target_date}. "
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
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
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

            # Store players to process (now ALL players, not just those with props) (vectorized)
            players_with_props = df['has_prop_line'].fillna(False).sum()

            # Convert DataFrame to list of dicts efficiently
            self.players_to_process.extend([
                {
                    'player_lookup': row.player_lookup,
                    'game_id': row.game_id,
                    'team_abbr': row.team_abbr if hasattr(row, 'team_abbr') else None,
                    'home_team_abbr': row.home_team_abbr,
                    'away_team_abbr': row.away_team_abbr,
                    'has_prop_line': bool(row.has_prop_line) if hasattr(row, 'has_prop_line') else False,
                    'current_points_line': row.points_line if hasattr(row, 'points_line') else None,
                    'prop_source': row.prop_source if hasattr(row, 'prop_source') else None,
                    'injury_status': row.player_status if hasattr(row, 'player_status') else None  # From gamebook
                }
                for row in df.itertuples()
            ])

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

    def _extract_schedule_data(self) -> None:
        """
        Extract schedule data for all games on target date.

        Used for:
        - Determining home/away
        - Game start times
        - Back-to-back detection (requires looking at surrounding dates)
        """
        game_ids = list(set([p['game_id'] for p in self.players_to_process if p.get('game_id')]))

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
        FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
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

            # Store schedule data by game_id (vectorized)
            # ALSO create lookups using date-based format (YYYYMMDD_AWAY_HOME) to match props table
            for row in df.itertuples():
                row_dict = df.loc[row.Index].to_dict()
                # Store with official NBA game_id
                self.schedule_data[row.game_id] = row_dict

                # Create all variant game_id keys to handle inconsistent abbreviations
                game_date_str = str(row.game_date).replace('-', '')
                away_variants = get_all_abbr_variants(row.away_team_abbr)
                home_variants = get_all_abbr_variants(row.home_team_abbr)

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
                df['minutes_decimal'] = df['minutes'].apply(parse_minutes)
            else:
                df['minutes_decimal'] = 0.0

            # Track source usage
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

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            logger.error(f"BigQuery error extracting historical boxscores: {e}")
            self.source_tracking['boxscore']['rows_found'] = 0
            raise
        except (KeyError, AttributeError, TypeError) as e:
            logger.error(f"Data error extracting historical boxscores: {e}")
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

        betting_extractor = self._get_betting_data_extractor()

        if use_bettingpros:
            logger.info(f"Extracting prop lines from BettingPros for {len(player_game_pairs)} players")
            self.prop_lines = betting_extractor.extract_prop_lines_from_bettingpros(
                player_game_pairs, self.target_date
            )
        else:
            logger.info(f"Extracting prop lines from Odds API for {len(player_game_pairs)} players")
            self.prop_lines = betting_extractor.extract_prop_lines_from_odds_api(
                player_game_pairs, self.target_date
            )

    def _extract_game_lines(self) -> None:
        """
        Extract game lines (spreads and totals) for each game.

        Uses consensus (median) across all bookmakers.
        Opening: Earliest snapshot
        Current: Most recent snapshot
        """
        game_ids = list(set([p['game_id'] for p in self.players_to_process]))
        betting_extractor = self._get_betting_data_extractor()

        for game_id in game_ids:
            try:
                # Get spread consensus
                spread_info = betting_extractor.get_game_line_consensus(
                    game_id, 'spreads', self.target_date, self.schedule_data
                )

                # Get total consensus
                total_info = betting_extractor.get_game_line_consensus(
                    game_id, 'totals', self.target_date, self.schedule_data
                )

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

        self.source_tracking['game_lines']['last_updated'] = datetime.now(timezone.utc)

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
        """
        if not self.players_to_process:
            logger.info("No players to lookup injuries for")
            return

        # Get unique player lookups for matching
        unique_players = list(set(p['player_lookup'] for p in self.players_to_process))

        logger.info(f"Extracting injury data for {len(unique_players)} players")

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
                self.source_tracking['injuries'] = {
                    'last_updated': None,
                    'rows_found': 0,
                    'players_with_status': 0
                }
                return

            # Track latest update time for source tracking
            latest_processed = df['processed_at'].max() if 'processed_at' in df.columns else None

            # Build injuries dict (vectorized with apply)
            def build_report(row):
                """Build meaningful report string from reason fields."""
                reason = row['reason']
                reason_category = row['reason_category']

                if reason and str(reason).lower() not in ('unknown', 'nan', 'none', ''):
                    return reason
                elif reason_category and str(reason_category).lower() not in ('unknown', 'nan', 'none', ''):
                    return reason_category
                return None

            # Create report column
            df['report'] = df.apply(build_report, axis=1)

            # Build injuries dict from DataFrame
            self.injuries = {
                row.player_lookup: {
                    'status': row.injury_status,
                    'report': row.report
                }
                for row in df.itertuples()
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
        config = get_orchestration_config()

        circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
        next_attempt = circuit_status['attempts'] + 1
        circuit_breaker_tripped = next_attempt >= 3
        circuit_breaker_until = None
        if circuit_breaker_tripped:
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
        # DEPENDENCY ROW COUNT VALIDATION
        # NOTE: validate_dependency_row_counts() was called here but never implemented.
        # Removed 2026-01-24 - dependency validation already happens in extract_data().
        # See: analytics_base.py check_dependencies() for actual validation logic.

        if not self.players_to_process:
            logger.warning("No players to process")
            return

        logger.info(f"Calculating context for {len(self.players_to_process)} players")

        # Get all player lookups
        all_players = [p['player_lookup'] for p in self.players_to_process]

        # NEW (Week 5): Batch completeness checking for ALL 5 windows
        logger.info(f"Checking completeness for {len(all_players)} players across 5 windows...")

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
                    dnp_aware=True
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
            logger.error(
                f"Completeness checking FAILED (BigQuery error: {e}). "
                f"Cannot proceed with unreliable data.",
                exc_info=True
            )
            raise
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.error(
                f"Completeness checking FAILED (Data error: {e}). "
                f"Cannot proceed with unreliable data.",
                exc_info=True
            )
            raise

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
            logger.info(f"Registry failures tracked: {len(self.registry_failures)} players with NULL universal_player_id")

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
                success, data = self._process_single_player(
                    player_info, comp_l5, comp_l10, comp_l7d, comp_l14d, comp_l30d,
                    is_bootstrap, is_season_boundary
                )
                if success:
                    self.transformed_data.append(data)
                else:
                    self.failed_entities.append(data)

            except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
                logger.error(f"BigQuery error calculating context for {player_info['player_lookup']}: {e}")
                self.failed_entities.append({
                    'player_lookup': player_info['player_lookup'],
                    'game_id': player_info['game_id'],
                    'reason': str(e),
                    'category': 'BIGQUERY_ERROR'
                })
            except (KeyError, AttributeError, TypeError, ValueError) as e:
                logger.error(f"Data error calculating context for {player_info['player_lookup']}: {e}")
                self.failed_entities.append({
                    'player_lookup': player_info['player_lookup'],
                    'game_id': player_info['game_id'],
                    'reason': str(e),
                    'category': 'DATA_ERROR'
                })

        # Track registry failures for observability
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
            logger.info(f"Registry failures tracked: {len(self.registry_failures)} players with NULL universal_player_id")

    def _calculate_player_context(self, player_info: Dict,
                                   completeness_l5: Dict, completeness_l10: Dict,
                                   completeness_l7d: Dict, completeness_l14d: Dict, completeness_l30d: Dict,
                                   circuit_breaker_status: Dict, is_bootstrap: bool, is_season_boundary: bool) -> Optional[Dict]:
        """
        Calculate complete context for a single player.

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

        # Calculate fatigue metrics (using extracted module)
        fatigue_metrics = calculate_fatigue_metrics(
            player_lookup, team_abbr, historical_data, self.target_date
        )

        # Get prop lines first (needed for performance metrics)
        prop_info = self.prop_lines.get((player_lookup, game_id), {})
        current_points_line = prop_info.get('current_line') or player_info.get('current_points_line')

        # Calculate performance metrics (using extracted module)
        performance_metrics = calculate_performance_metrics(historical_data, current_points_line)

        # Get game lines
        game_lines_info = self.game_lines.get(game_id, {})

        # Calculate data quality
        data_quality = self._calculate_data_quality(historical_data, game_lines_info)

        # Get team context calculator
        team_calc = self._get_team_context_calculator()

        # Calculate pace metrics
        pace_differential = team_calc.calculate_pace_differential(team_abbr, opponent_team_abbr, self.target_date)
        opponent_pace_last_10 = team_calc.get_opponent_pace_last_10(opponent_team_abbr, self.target_date)
        opponent_ft_rate_allowed = team_calc.get_opponent_ft_rate_allowed(opponent_team_abbr, self.target_date)
        opponent_def_rating = team_calc.get_opponent_def_rating_last_10(opponent_team_abbr, self.target_date)
        opponent_off_rating = team_calc.get_opponent_off_rating_last_10(opponent_team_abbr, self.target_date)
        opponent_rebounding_rate = team_calc.get_opponent_rebounding_rate(opponent_team_abbr, self.target_date)
        opponent_pace_variance = team_calc.get_opponent_pace_variance(opponent_team_abbr, self.target_date)
        opponent_ft_rate_variance = team_calc.get_opponent_ft_rate_variance(opponent_team_abbr, self.target_date)
        opponent_def_rating_variance = team_calc.get_opponent_def_rating_variance(opponent_team_abbr, self.target_date)
        opponent_off_rating_variance = team_calc.get_opponent_off_rating_variance(opponent_team_abbr, self.target_date)
        opponent_rebounding_rate_variance = team_calc.get_opponent_rebounding_rate_variance(opponent_team_abbr, self.target_date)

        # Calculate star teammates out
        star_teammates_out = team_calc.get_star_teammates_out(team_abbr, self.target_date)
        questionable_star_teammates = team_calc.get_questionable_star_teammates(team_abbr, self.target_date)
        star_tier_out = team_calc.get_star_tier_out(team_abbr, self.target_date)

        # Calculate travel context
        travel_calc = self._get_travel_context_calculator()
        travel_context = travel_calc.calculate_travel_context(team_abbr, self.target_date, game_info)

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

        # Build context record
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
            'spread_public_betting_pct': self._get_betting_data_extractor().get_spread_public_betting_pct(game_id),

            # Game total context
            'game_total': game_lines_info.get('game_total'),
            'opening_total': game_lines_info.get('opening_total'),
            'total_movement': game_lines_info.get('total_movement'),
            'game_total_source': game_lines_info.get('total_source'),
            'total_public_betting_pct': self._get_betting_data_extractor().get_total_public_betting_pct(game_id),

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

            # Travel context
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
            'opponent_ft_rate_variance': opponent_ft_rate_variance,
            'opponent_def_rating_variance': opponent_def_rating_variance,
            'opponent_off_rating_variance': opponent_off_rating_variance,
            'opponent_rebounding_rate_variance': opponent_rebounding_rate_variance,

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
            'star_teammates_out': star_teammates_out,
            'questionable_star_teammates': questionable_star_teammates,
            'star_tier_out': star_tier_out,
            'probable_teammates': None,  # TODO: future

            # Source tracking
            **self._build_source_tracking_fields(),

            # Data quality
            **data_quality,

            # Completeness Metadata (25 fields)
            'expected_games_count': completeness_l30d['expected_count'],
            'actual_games_count': completeness_l30d['actual_count'],
            'completeness_percentage': completeness_l30d['completeness_pct'],
            'missing_games_count': completeness_l30d['missing_count'],

            # Production Readiness
            'is_production_ready': is_season_boundary or is_bootstrap or (
                completeness_l5['is_production_ready'] and
                completeness_l10['is_production_ready'] and
                completeness_l7d['is_production_ready'] and
                completeness_l14d['is_production_ready'] and
                completeness_l30d['is_production_ready']
            ),
            'data_quality_issues': [],

            # Circuit Breaker
            'last_reprocess_attempt_at': None,
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

            # Update tracking
            'context_version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }

        # Calculate data_hash AFTER all fields are populated
        context['data_hash'] = self._calculate_data_hash(context)

        return context

    def _determine_player_team(self, player_lookup: str, game_info: Dict) -> Optional[str]:
        """Determine which team the player is on."""
        # First check game_info - gamebook already has team_abbr
        if game_info.get('team_abbr'):
            return game_info['team_abbr']

        # Fallback: Use most recent boxscore (for daily mode without gamebook)
        historical_data = self.historical_boxscores.get(player_lookup, pd.DataFrame())
        if not historical_data.empty:
            most_recent = historical_data.iloc[0]
            return most_recent.get('team_abbr')

        return None

    def _get_opponent_team(self, team_abbr: str, game_info: Dict) -> str:
        """Get opponent team abbreviation."""
        if team_abbr == game_info['home_team_abbr']:
            return game_info['away_team_abbr']
        else:
            return game_info['home_team_abbr']

    def _calculate_data_quality(self, historical_data: pd.DataFrame,
                                game_lines_info: Dict) -> Dict:
        """Calculate data quality metrics using centralized helper."""
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

        primary_source = 'bdl_player_boxscores'

        quality_cols = build_quality_columns_with_legacy(
            tier=tier,
            score=score,
            issues=issues,
            sources=[primary_source],
        )

        quality_cols['primary_source_used'] = primary_source
        quality_cols['processed_with_issues'] = len(issues) > 0

        return quality_cols

    def _calculate_data_hash(self, record: Dict) -> str:
        """Calculate SHA256 hash of meaningful analytics fields."""
        hash_data = {field: record.get(field) for field in self.HASH_FIELDS}
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]

    def _build_source_tracking_fields(self) -> Dict:
        """Build source tracking fields for output record."""
        def compute_hash(source_key: str) -> Optional[str]:
            tracking = self.source_tracking.get(source_key, {})
            if not tracking.get('last_updated'):
                return None
            hash_input = f"{tracking.get('last_updated', '')}:{tracking.get('rows_found', 0)}"
            return hashlib.md5(hash_input.encode()).hexdigest()[:16]

        return {
            'source_boxscore_hash': compute_hash('boxscore'),
            'source_schedule_hash': compute_hash('schedule'),
            'source_props_hash': compute_hash('props'),
            'source_game_lines_hash': compute_hash('game_lines'),
        }

    def save_analytics(self) -> bool:
        """
        Save results to BigQuery using atomic MERGE pattern.

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
            import math

            def sanitize_value(v):
                if v is None:
                    return None
                if isinstance(v, float):
                    if math.isnan(v) or math.isinf(v):
                        return None
                if hasattr(v, 'item'):
                    return v.item()
                return v

            current_utc = datetime.now(timezone.utc)
            filtered_data = []
            for record in self.transformed_data:
                out = {k: sanitize_value(v) for k, v in record.items() if k in schema_fields}
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

            timing['total'] = time.time() - overall_start
            logger.info(
                f"Save complete: {len(filtered_data)} records in {timing['total']:.2f}s "
                f"(schema: {timing['get_schema']:.1f}s, load: {timing['load_temp_table']:.1f}s, "
                f"merge: {timing['merge_operation']:.1f}s)"
            )

            return True

        except (GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded) as e:
            error_msg = str(e).lower()

            if "streaming buffer" in error_msg:
                logger.warning(
                    f"MERGE blocked by streaming buffer - {len(self.transformed_data)} records skipped. "
                    f"Will succeed on next run."
                )
                return False

            logger.error(f"BigQuery error saving to BigQuery: {e}")
            return False
        except (KeyError, AttributeError, TypeError, ValueError, json.JSONDecodeError) as e:
            logger.error(f"Data error saving to BigQuery: {e}")
            return False

        finally:
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.debug(f"Cleaned up temp table {temp_table_id}")
                except (GoogleAPIError, NotFound) as cleanup_e:
                    logger.warning(f"Failed to cleanup temp table: {cleanup_e}")

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def _extract_game_time(self, game_info: Dict) -> Optional[str]:
        """Extract game time in local arena timezone."""
        try:
            from zoneinfo import ZoneInfo

            game_dt = game_info.get('game_date_est')
            if not game_dt:
                return None

            if isinstance(game_dt, str):
                game_dt = datetime.fromisoformat(game_dt.replace('Z', '+00:00'))
            elif not isinstance(game_dt, datetime):
                return None

            arena_tz_str = game_info.get('arena_timezone', 'America/New_York')
            if not arena_tz_str:
                arena_tz_str = 'America/New_York'

            try:
                arena_tz = ZoneInfo(arena_tz_str)
            except (KeyError, ValueError):
                arena_tz = ZoneInfo('America/New_York')

            if game_dt.tzinfo is None:
                eastern = ZoneInfo('America/New_York')
                game_dt = game_dt.replace(tzinfo=eastern)

            local_dt = game_dt.astimezone(arena_tz)

            tz_abbrev_map = {
                'America/New_York': 'ET',
                'America/Chicago': 'CT',
                'America/Denver': 'MT',
                'America/Los_Angeles': 'PT',
                'America/Phoenix': 'MST',
            }
            tz_abbr = tz_abbrev_map.get(arena_tz_str, local_dt.strftime('%Z'))

            return f"{local_dt.strftime('%I:%M %p').lstrip('0')} {tz_abbr}"

        except (ValueError, TypeError, AttributeError, KeyError) as e:
            logger.debug(f"Could not extract game time: {e}")
            return None

    def _determine_season_phase(self, game_date: date) -> str:
        """Determine season phase based on date."""
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
    # ============================================================

    def _check_props_readiness(self, target_date: date, min_players: int = 20) -> Dict:
        """Pre-flight check: Are betting props available for this date?"""
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
                'ready': True,
                'player_count': 0,
                'message': f'Props check failed (proceeding anyway): {e}'
            }
        except (KeyError, AttributeError, TypeError, IndexError) as e:
            logger.warning(f"Data error in props readiness check: {e}")
            return {
                'ready': True,
                'player_count': 0,
                'message': f'Props check failed (proceeding anyway): {e}'
            }

    def _send_prop_coverage_alert(self, target_date: date, total_players: int,
                                   players_with_props: int, prop_pct: float) -> None:
        """Send alert when prop coverage is critically low."""
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
                f"ALERT SENT: {prop_pct:.1f}% prop coverage for {target_date} "
                f"({players_with_props}/{total_players})"
            )
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.error(f"Failed to send prop coverage alert: {e}")

    def _send_roster_coverage_alert(self, target_date: date, teams_count: int,
                                     players_count: int) -> None:
        """Send alert when roster/team coverage is critically low."""
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
                f"ALERT SENT: Low roster coverage - only {teams_count} teams for {target_date}"
            )
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.error(f"Failed to send roster coverage alert: {e}")


# Entry point for script execution
if __name__ == '__main__':
    import sys
    import argparse

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

    result = processor.process_date(target_date)

    print(f"\nProcessing Result:")
    print(f"Status: {result['status']}")
    print(f"Players Processed: {result['players_processed']}")
    print(f"Players Failed: {result['players_failed']}")

    if result.get('errors'):
        print(f"\nErrors:")
        for error in result['errors'][:10]:
            print(f"  - {error}")
