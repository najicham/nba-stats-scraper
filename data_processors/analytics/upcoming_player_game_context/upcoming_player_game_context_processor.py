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
- calculators/: Quality flags and context builders
- loaders/: Data extraction modules (player and game data)

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

# Calculator modules (Week 6 - Maintainability Refactor, R5 extraction)
from .calculators import (
    QualityFlagsCalculator,
    ContextBuilder,
    MatchupCalculator,
    UsageCalculator,
    GameUtils,
    CompletenessCheckerHelper
)

# Loader modules (Week 7 - Reduce file size)
from .loaders import PlayerDataLoader, GameDataLoader

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
        self.table_name = 'upcoming_player_game_context'
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
        self._quality_calculator = None  # Lazy-loaded (Week 6)
        self._context_builder = None  # Lazy-loaded (Week 6)
        self._matchup_calculator = None  # Lazy-loaded (R5 refactor)
        self._usage_calculator = None  # Lazy-loaded (R5 refactor)
        self._completeness_helper = None  # Lazy-loaded (R5 refactor)
        self._player_loader = None  # Lazy-loaded (Week 7)
        self._game_data_loader = None  # Lazy-loaded (Week 7)

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

    def _get_quality_calculator(self) -> QualityFlagsCalculator:
        """Lazy-load quality flags calculator."""
        if self._quality_calculator is None:
            self._quality_calculator = QualityFlagsCalculator(
                min_games_for_high_quality=self.min_games_for_high_quality,
                min_games_for_medium_quality=self.min_games_for_medium_quality
            )
        return self._quality_calculator

    def _get_context_builder(self) -> ContextBuilder:
        """Lazy-load context builder."""
        if self._context_builder is None:
            roster_ages = getattr(self, 'roster_ages', {})
            self._context_builder = ContextBuilder(roster_ages=roster_ages)
        return self._context_builder

    def _get_matchup_calculator(self) -> MatchupCalculator:
        """Lazy-load matchup calculator."""
        if self._matchup_calculator is None:
            self._matchup_calculator = MatchupCalculator(self.bq_client, self.project_id)
        return self._matchup_calculator

    def _get_usage_calculator(self) -> UsageCalculator:
        """Lazy-load usage calculator."""
        if self._usage_calculator is None:
            self._usage_calculator = UsageCalculator(self.bq_client, self.project_id)
        return self._usage_calculator

    def _get_completeness_helper(self) -> CompletenessCheckerHelper:
        """Lazy-load completeness checker helper."""
        if self._completeness_helper is None:
            self._completeness_helper = CompletenessCheckerHelper(self.completeness_checker)
        return self._completeness_helper

    def _get_player_loader(self) -> PlayerDataLoader:
        """Lazy-load player data loader."""
        if self._player_loader is None:
            if self.target_date is None:
                raise ValueError("target_date must be set before creating player loader")
            self._player_loader = PlayerDataLoader(self.bq_client, self.project_id, self.target_date)
        return self._player_loader

    def _get_game_data_loader(self) -> GameDataLoader:
        """Lazy-load game data loader."""
        if self._game_data_loader is None:
            if self.target_date is None:
                raise ValueError("target_date must be set before creating game data loader")
            self._game_data_loader = GameDataLoader(
                self.bq_client, self.project_id, self.target_date, self.lookback_days
            )
        return self._game_data_loader

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
    # HASH_FIELDS moved to calculators/context_builder.py (Week 6 Refactor)

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
        'bdl_player_boxscores': False,  # DISABLED 2026-02-01 - unreliable quality, use player_game_summary instead
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

            # Session 52: Feature completeness validation
            # Check critical features aren't all NULL (prevents silent data quality issues)
            critical_features = [
                ('avg_usage_rate_last_7_games', 'Usage rate needed for composite factors'),
                ('games_in_last_7_days', 'Games count needed for fatigue calculation'),
                ('back_to_back', 'Back-to-back flag needed for ML features'),
            ]
            for feature_name, feature_desc in critical_features:
                non_null_count = sum(1 for p in self.transformed_data if p.get(feature_name) is not None)
                feature_pct = (non_null_count / total_players * 100) if total_players > 0 else 0
                if total_players >= 50 and feature_pct < 10:
                    logger.warning(
                        f"FEATURE QUALITY ALERT: {feature_name} is {feature_pct:.1f}% populated "
                        f"({non_null_count}/{total_players}). {feature_desc}"
                    )

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
        # Session 218: Made BLOCKING for future dates (not backfill). Returns 500 → Pub/Sub retry.
        props_check = self._check_props_readiness(self.target_date)
        if not props_check['ready']:
            is_future_date = self.target_date >= date.today()
            if is_future_date and not getattr(self, '_backfill_mode', False):
                logger.error(
                    f"PROPS PRE-FLIGHT BLOCKED: {props_check['message']}. "
                    f"Raising error to trigger Pub/Sub retry (props not yet available)."
                )
                raise ValueError(
                    f"Props not ready for {self.target_date}: {props_check['message']}. "
                    f"Will retry when BettingPros lines arrive."
                )
            else:
                logger.warning(f"PROPS PRE-FLIGHT: {props_check['message']} (backfill/historical - continuing)")
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

        # Delegate to player loader
        player_loader = self._get_player_loader()
        player_loader._extract_players_with_props(processing_mode)

        # Copy results back to processor
        self.players_to_process = player_loader.players_to_process
        self.source_tracking['props'] = player_loader.source_tracking['props']
        self._props_source = player_loader._props_source


    def _extract_schedule_data(self) -> None:
        """
        Extract schedule data for all games on target date.

        Used for:
        - Determining home/away
        - Game start times
        - Back-to-back detection (requires looking at surrounding dates)
        """
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader._extract_schedule_data(self.players_to_process)

        # Copy results back to processor
        self.schedule_data = game_loader.schedule_data
        self.source_tracking['schedule'] = game_loader.source_tracking['schedule']

    def _extract_historical_boxscores(self) -> None:
        """
        Extract historical boxscores for all players (last 30 days).

        Priority:
        1. nba_raw.bdl_player_boxscores (PRIMARY)
        2. nba_raw.nbac_player_boxscores (fallback)
        3. nba_raw.nbac_gamebook_player_stats (last resort)
        """
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader._extract_historical_boxscores(self.players_to_process)

        # Copy results back to processor
        self.historical_boxscores = game_loader.historical_boxscores
        self.source_tracking['boxscore'] = game_loader.source_tracking['boxscore']

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
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader._props_source = getattr(self, '_props_source', 'odds_api')
        betting_extractor = self._get_betting_data_extractor()
        game_loader._extract_prop_lines(self.players_to_process, betting_extractor)

        # Copy results back to processor
        self.prop_lines = game_loader.prop_lines

    def _extract_game_lines(self) -> None:
        """
        Extract game lines (spreads and totals) for each game.

        Uses consensus (median) across all bookmakers.
        Opening: Earliest snapshot
        Current: Most recent snapshot
        """
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader.schedule_data = self.schedule_data  # Pass schedule data
        betting_extractor = self._get_betting_data_extractor()
        game_loader._extract_game_lines(self.players_to_process, betting_extractor)

        # Copy results back to processor
        self.game_lines = game_loader.game_lines
        self.source_tracking['game_lines'] = game_loader.source_tracking['game_lines']

    def _extract_rosters(self) -> None:
        """
        Extract current roster data including player age.

        Loads the latest roster data from espn_team_rosters for player demographics.
        Stores in self.roster_ages as {player_lookup: age}.
        """
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader._extract_rosters(self.players_to_process)

        # Copy results back to processor
        self.roster_ages = game_loader.roster_ages

    def _extract_injuries(self) -> None:
        """
        Extract injury report data from NBA.com injury report.

        Gets the latest injury status for each player for the target game date.
        Stores results in self.injuries as {player_lookup: {'status': ..., 'report': ...}}.
        """
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader._extract_injuries(self.players_to_process)

        # Copy results back to processor
        self.injuries = game_loader.injuries
        self.source_tracking['injuries'] = game_loader.source_tracking['injuries']

    def _extract_registry(self) -> None:
        """
        Extract universal player IDs from registry using batch lookup.

        Populates self.registry dict with {player_lookup: universal_player_id}.
        Uses RegistryReader for efficient batch lookups with caching.
        """
        # Delegate to game data loader
        game_loader = self._get_game_data_loader()
        game_loader._extract_registry(self.players_to_process)

        # Copy results back to processor
        self.registry = game_loader.registry
        self.registry_stats = game_loader.registry_stats

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

        # Batch completeness checking for ALL 5 windows (using helper)
        try:
            completeness_helper = self._get_completeness_helper()
            comp_l5, comp_l10, comp_l7d, comp_l14d, comp_l30d, is_bootstrap, is_season_boundary = \
                completeness_helper.run_batch_completeness_checks(
                    all_players, self.target_date, self.season_start_date
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

        # Pre-compute opponent team metrics in a single batch query
        # This reduces BigQuery calls from O(players * metrics) to O(1)
        try:
            unique_opponents = set()
            for player_info in self.players_to_process:
                game_id = player_info.get('game_id')
                if game_id and game_id in self.schedule_data:
                    game_info = self.schedule_data[game_id]
                    team_abbr = player_info.get('team_abbr')
                    if team_abbr:
                        opponent = self._get_opponent_team(team_abbr, game_info)
                        if opponent:
                            unique_opponents.add(opponent)

            if unique_opponents:
                team_calc = self._get_team_context_calculator()
                team_calc.precompute_opponent_metrics(list(unique_opponents), self.target_date)
        except Exception as e:
            logger.warning(f"Failed to pre-compute opponent metrics, will use individual queries: {e}")

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

        # Final timing summary with failure category breakdown
        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(results)} players in {total_time:.1f}s "
            f"(avg {total_time/len(results) if results else 0:.2f}s/player) "
            f"| {len(failures)} failed"
        )

        if failures:
            # Log failure breakdown by category
            from collections import Counter
            category_counts = Counter(f.get('category', 'UNKNOWN') for f in failures)
            logger.warning(f"Failure breakdown: {dict(category_counts)}")
            # Log first 5 failures with details
            for f in failures[:5]:
                logger.warning(
                    f"  FAILED: {f.get('player_lookup')} | category={f.get('category')} | reason={f.get('reason')}"
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

            # Check if ALL windows are production-ready
            all_windows_ready = (
                completeness_l5['is_production_ready'] and
                completeness_l10['is_production_ready'] and
                completeness_l7d['is_production_ready'] and
                completeness_l14d['is_production_ready'] and
                completeness_l30d['is_production_ready']
            )

            # Completeness is LOG-ONLY for upcoming player context (non-blocking).
            # Rationale: Pre-game context naturally has gaps (missed games, delayed data).
            # The real quality gate is Phase 5 (zero tolerance on feature defaults).
            # Blocking here just trips circuit breakers and reduces coverage.
            if not all_windows_ready and not is_bootstrap and not is_season_boundary:
                avg_completeness = (
                    completeness_l5['completeness_pct'] +
                    completeness_l10['completeness_pct'] +
                    completeness_l7d['completeness_pct'] +
                    completeness_l14d['completeness_pct'] +
                    completeness_l30d['completeness_pct']
                ) / 5.0
                logger.debug(
                    f"{player_lookup}: completeness {avg_completeness:.1f}% (non-blocking)"
                )

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
            logger.warning(f"No schedule data for game {game_id} (player={player_lookup}, schedule_keys_sample={list(self.schedule_data.keys())[:3]})")
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

        # Prepare prop_info with fallbacks from player_info
        prepared_prop_info = {
            'current_line': prop_info.get('current_line') or player_info.get('current_points_line'),
            'opening_line': prop_info.get('opening_line'),
            'line_movement': prop_info.get('line_movement'),
            'current_source': prop_info.get('current_source') or player_info.get('prop_source'),
            'opening_source': prop_info.get('opening_source'),
        }

        # Build context record using context builder
        context_builder = self._get_context_builder()
        context = context_builder.build_context_record(
            player_lookup=player_lookup,
            universal_player_id=universal_player_id,
            game_id=game_id,
            target_date=self.target_date,
            team_abbr=team_abbr,
            opponent_team_abbr=opponent_team_abbr,
            game_info=game_info,
            has_prop_line=has_prop_line,
            prop_info=prepared_prop_info,
            game_lines_info=game_lines_info,
            fatigue_metrics=fatigue_metrics,
            performance_metrics=performance_metrics,
            pace_differential=pace_differential,
            opponent_pace_last_10=opponent_pace_last_10,
            opponent_ft_rate_allowed=opponent_ft_rate_allowed,
            opponent_def_rating=opponent_def_rating,
            opponent_off_rating=opponent_off_rating,
            opponent_rebounding_rate=opponent_rebounding_rate,
            opponent_pace_variance=opponent_pace_variance,
            opponent_ft_rate_variance=opponent_ft_rate_variance,
            opponent_def_rating_variance=opponent_def_rating_variance,
            opponent_off_rating_variance=opponent_off_rating_variance,
            opponent_rebounding_rate_variance=opponent_rebounding_rate_variance,
            star_teammates_out=star_teammates_out,
            questionable_star_teammates=questionable_star_teammates,
            star_tier_out=star_tier_out,
            travel_context=travel_context,
            injury_info=self.injuries.get(player_lookup, {}),
            source_tracking_fields=self._build_source_tracking_fields(),
            data_quality=data_quality,
            completeness_l5=completeness_l5,
            completeness_l10=completeness_l10,
            completeness_l7d=completeness_l7d,
            completeness_l14d=completeness_l14d,
            completeness_l30d=completeness_l30d,
            circuit_breaker_status=circuit_breaker_status,
            is_bootstrap=is_bootstrap,
            is_season_boundary=is_season_boundary,
            season_phase=self._determine_season_phase(self.target_date),
            game_start_time_local=self._extract_game_time(game_info),
            spread_public_betting_pct=self._get_betting_data_extractor().get_spread_public_betting_pct(game_id),
            total_public_betting_pct=self._get_betting_data_extractor().get_total_public_betting_pct(game_id)
        )

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
        """Calculate data quality metrics using quality calculator."""
        quality_calc = self._get_quality_calculator()
        return quality_calc.calculate_data_quality(historical_data, game_lines_info)

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
