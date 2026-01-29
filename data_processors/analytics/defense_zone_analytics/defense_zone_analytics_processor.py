#!/usr/bin/env python3
"""
Path: data_processors/analytics/defense_zone_analytics/defense_zone_analytics_processor.py

Defense Zone Analytics Processor - Phase 3 Analytics

Calculates comprehensive defensive zone metrics for NBA teams including:
- Points allowed in paint
- 3PT defense rating
- Rim protection stats
- Perimeter contest rate

This processor follows the patterns from upcoming_player_game_context_processor.py:
- Uses AnalyticsProcessorBase for Phase 3 processing
- Implements SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin patterns
- Tracks source dependencies for data lineage
- Handles multi-source fallback for data completeness

Input: Phase 2 raw tables
  - nba_raw.bigdataball_play_by_play (PRIMARY - shot zone data)
  - nba_raw.nbac_play_by_play (FALLBACK - shot zone data)
  - nba_raw.nbac_team_boxscore (team defensive stats)
  - nba_raw.nbac_gamebook_player_stats (player defensive actions)

Output: nba_analytics.defense_zone_analytics
Strategy: MERGE_UPDATE (update existing or insert new)
Frequency: Daily after games complete

Key Features:
- Points allowed in paint calculation
- 3PT defense rating (opponent 3PT% allowed)
- Rim protection stats (blocks at rim, contests)
- Perimeter contest rate
- Rolling averages (L5, L10, L15 games)
- Comparison to league averages
"""

import logging
import os
import hashlib
import json
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

# Team mapping utility
from shared.utils.nba_team_mapper import get_nba_team_mapper, NBATeamMapper

logger = logging.getLogger(__name__)

# Feature flag for team-level parallelization
ENABLE_TEAM_PARALLELIZATION = os.environ.get('ENABLE_TEAM_PARALLELIZATION', 'true').lower() == 'true'


class DefenseZoneAnalyticsProcessor(
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Process defense zone analytics from Phase 2 raw data.

    Calculates comprehensive defensive zone metrics:
    - Points allowed in paint (rim protection effectiveness)
    - 3PT defense rating (perimeter defense quality)
    - Rim protection stats (blocks, contests at rim)
    - Perimeter contest rate (3PT contest frequency)

    Phase 3 Analytics Processor - depends only on Phase 2 raw tables.
    """

    # Primary key fields for duplicate detection and MERGE operations
    PRIMARY_KEY_FIELDS = ['game_date', 'team_abbr']

    def __init__(self):
        super().__init__()
        # Note: Use just the table name without dataset prefix for consistency
        # with other Phase 3 processors. The dataset is set via dataset_id.
        self.table_name = 'defense_zone_analytics'
        self.processing_strategy = 'MERGE_UPDATE'
        self.entity_type = 'team'
        self.entity_field = 'team_abbr'

        # Initialize target dates (set later in extract_raw_data)
        self.start_date = None
        self.end_date = None

        # BigQuery client already initialized by AnalyticsProcessorBase with pooling
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)

        # Initialize team mapper
        self.team_mapper = NBATeamMapper(use_database=False)

        # Configuration
        self.lookback_days = 30  # Historical data window
        self.min_games_for_high_quality = 15
        self.min_games_for_medium_quality = 10
        self.min_games_for_low_quality = 5

        # Data holders
        self.teams_to_process = []  # List of team_abbr
        self.play_by_play_data = {}  # game_id -> DataFrame
        self.team_boxscore_data = {}  # (game_id, team_abbr) -> dict
        self.player_defensive_actions = {}  # (game_id, team_abbr) -> dict
        self.league_averages = {}  # metric -> value

        # Source tracking (for dependency tracking pattern)
        self.source_tracking = {
            'play_by_play': {'last_updated': None, 'rows_found': 0, 'source_used': None},
            'team_boxscore': {'last_updated': None, 'rows_found': 0},
            'player_actions': {'last_updated': None, 'rows_found': 0}
        }

        # Processing results
        self.transformed_data = []
        self.failed_entities = []

        logger.info(f"Initialized {self.__class__.__name__}")

    # ============================================================
    # Pattern #3: Smart Reprocessing - Data Hash Fields
    # ============================================================
    HASH_FIELDS = [
        # Core identifiers
        'game_date',
        'team_abbr',
        'opponent_team_abbr',
        'game_id',

        # Points allowed in paint metrics
        'points_in_paint_allowed',
        'paint_fg_allowed',
        'paint_fga_allowed',
        'paint_fg_pct_allowed',
        'paint_fg_pct_vs_league_avg',

        # 3PT defense rating metrics
        'three_pt_fg_allowed',
        'three_pt_fga_allowed',
        'three_pt_pct_allowed',
        'three_pt_pct_vs_league_avg',
        'three_pt_defense_rating',

        # Rim protection stats
        'blocks_at_rim',
        'rim_contests',
        'rim_contest_rate',
        'rim_fg_pct_allowed',
        'rim_protection_rating',

        # Perimeter contest rate
        'perimeter_contests',
        'perimeter_shots_faced',
        'perimeter_contest_rate',
        'contested_three_pt_pct',

        # Rolling averages
        'paint_pts_allowed_l5',
        'paint_pts_allowed_l10',
        'three_pt_pct_allowed_l5',
        'three_pt_pct_allowed_l10',
        'rim_protection_rating_l5',
        'perimeter_contest_rate_l5',

        # Game context
        'home_game',
        'games_in_sample',
    ]

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Play-by-play sources - RELEVANT (primary source for shot zones)
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Team boxscore sources - RELEVANT (defensive stats)
        'nbac_team_boxscore': True,
        'bdl_team_boxscores': True,

        # Player boxscore sources - RELEVANT (defensive actions)
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,

        # Player prop sources - NOT RELEVANT
        'odds_api_player_points_props': False,
        'bettingpros_player_points_props': False,

        # Game odds sources - NOT RELEVANT
        'odds_api_game_lines': False,

        # Schedule sources - NOT RELEVANT
        'nbacom_schedule': False,
        'espn_scoreboard': False,
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = True       # Skip if no games scheduled
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = True  # Skip dates >90 days old

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    def get_dependencies(self) -> dict:
        """
        Define Phase 2 raw table dependencies.

        Returns:
            dict: Configuration for each Phase 2 dependency
        """
        return {
            'nba_raw.bigdataball_play_by_play': {
                'field_prefix': 'source_pbp',
                'description': 'Play-by-play data for shot zone analysis (PRIMARY)',
                'critical': False,  # Can fall back to nbac_play_by_play
                'check_type': 'date_range'
            },
            'nba_raw.nbac_play_by_play': {
                'field_prefix': 'source_nbac_pbp',
                'description': 'Play-by-play data for shot zone analysis (FALLBACK)',
                'critical': False,
                'check_type': 'date_range'
            },
            'nba_raw.nbac_team_boxscore': {
                'field_prefix': 'source_team_boxscore',
                'description': 'Team defensive stats from boxscores',
                'critical': True,
                'check_type': 'date_range'
            },
            'nba_raw.nbac_gamebook_player_stats': {
                'field_prefix': 'source_player_stats',
                'description': 'Player defensive actions (blocks, steals)',
                'critical': False,
                'check_type': 'date_range'
            }
        }

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Verifies:
        1. Games are finished (game_status >= 3)
        2. Team boxscore data exists

        Args:
            start_date: Start of date range (YYYY-MM-DD)
            end_date: End of date range (YYYY-MM-DD)

        Returns:
            SQL query that returns {data_available: boolean}
        """
        return f"""
        SELECT
            COUNTIF(
                schedule.game_status >= 3  -- Final only
                AND team_box.game_id IS NOT NULL
            ) > 0 AS data_available
        FROM `nba_raw.v_nbac_schedule_latest` AS schedule
        LEFT JOIN `nba_raw.nbac_team_boxscore` AS team_box
            ON schedule.game_id = team_box.game_id
        WHERE schedule.game_date BETWEEN '{start_date}' AND '{end_date}'
        """

    def extract_raw_data(self) -> None:
        """
        Extract data from all Phase 2 raw sources.

        Order of operations:
        1. Get teams with games in date range
        2. Extract play-by-play data (shot zones)
        3. Extract team boxscore data
        4. Extract player defensive actions
        5. Calculate league averages
        """
        # Set dates from opts
        self.start_date = self.opts.get('start_date')
        self.end_date = self.opts.get('end_date')

        if isinstance(self.start_date, str):
            self.start_date = date.fromisoformat(self.start_date)
        if isinstance(self.end_date, str):
            self.end_date = date.fromisoformat(self.end_date)

        logger.info(f"Extracting raw data for {self.start_date} to {self.end_date}")

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(self.start_date)
        if skip:
            logger.info(f"SMART REPROCESSING: Skipping processing - {reason}")
            self.teams_to_process = []
            return

        logger.info(f"PROCESSING: {reason}")

        # Step 1: Get all teams with games in date range
        self._extract_teams_with_games()

        if not self.teams_to_process:
            logger.warning(f"No teams with games found for {self.start_date} to {self.end_date}")
            return

        logger.info(f"Found games for {len(self.teams_to_process)} team-game combinations")

        # Step 2: Extract play-by-play data (shot zones)
        self._extract_play_by_play_data()

        # Step 3: Extract team boxscore data
        self._extract_team_boxscore_data()

        # Step 4: Extract player defensive actions
        self._extract_player_defensive_actions()

        # Step 5: Calculate league averages for comparison
        self._calculate_league_averages()

        logger.info("Data extraction complete")

    def _extract_teams_with_games(self) -> None:
        """
        Extract all teams that played games in the date range.
        """
        query = f"""
        SELECT DISTINCT
            game_id,
            game_date,
            team_abbr,
            CASE
                WHEN team_abbr = SPLIT(game_id, '_')[SAFE_OFFSET(2)] THEN TRUE
                ELSE FALSE
            END as home_game,
            CASE
                WHEN team_abbr = SPLIT(game_id, '_')[SAFE_OFFSET(1)] THEN SPLIT(game_id, '_')[SAFE_OFFSET(2)]
                ELSE SPLIT(game_id, '_')[SAFE_OFFSET(1)]
            END as opponent_team_abbr
        FROM `{self.project_id}.nba_raw.nbac_team_boxscore`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        ORDER BY game_date DESC, game_id, team_abbr
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            self.teams_to_process = df.to_dict('records')
            logger.info(f"Found {len(self.teams_to_process)} team-game records")
        except Exception as e:
            logger.error(f"Failed to extract teams with games: {e}")
            raise

    def _extract_play_by_play_data(self) -> None:
        """
        Extract play-by-play data for shot zone analysis.

        Uses bigdataball_play_by_play as PRIMARY source with nbac_play_by_play as FALLBACK.
        Classifies shots into zones:
        - Rim: shot_distance <= 4 feet
        - Paint (non-rim): 4 < shot_distance <= 8 feet
        - Mid-range: 8 < shot_distance AND shot_type = '2PT'
        - Three-point: shot_type = '3PT'

        NOTE: NBA.com fallback handling (data_source = 'nbacom_fallback')
        When BigDataBall is unavailable, PBP data comes from NBA.com with these limitations:
        - Lineup fields are NULL (away_player_1_lookup through home_player_5_lookup)
        - Contest tracking may be less accurate (player_2_role availability varies)

        This query does NOT use lineup fields - only action event fields (player_1_team_abbr,
        player_2_role, etc.) which ARE populated for both data sources. The query handles
        NULL player_2_role gracefully by treating NULL as not contested/blocked.
        """
        # Try bigdataball first (better shot_distance data)
        # NOTE: Query works for both 'bigdataball' and 'nbacom_fallback' data sources
        query = f"""
        WITH shot_events AS (
            SELECT
                game_id,
                game_date,
                player_1_team_abbr as shooting_team,
                shot_type,
                shot_distance,
                shot_made,
                data_source,  -- Track source for quality metadata
                -- Classify zone with rim separation
                CASE
                    WHEN shot_type = '3PT' THEN 'three_pt'
                    WHEN shot_distance <= 4 THEN 'rim'
                    WHEN shot_distance <= 8 THEN 'paint_non_rim'
                    ELSE 'mid_range'
                END as shot_zone,
                -- Track if shot was contested (if player_2_role exists)
                -- COALESCE handles NULL player_2_role gracefully (treats as not contested)
                CASE
                    WHEN COALESCE(player_2_role, '') IN ('contest', 'block') THEN TRUE
                    ELSE FALSE
                END as was_contested,
                -- Track blocks (COALESCE for NULL-safety)
                CASE
                    WHEN COALESCE(player_2_role, '') = 'block' THEN TRUE
                    ELSE FALSE
                END as was_blocked,
                home_team_abbr,
                away_team_abbr,
                processed_at
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
              AND shot_type IN ('2PT', '3PT')
              AND player_1_team_abbr IS NOT NULL
        ),

        -- Aggregate by game and defending team
        defense_stats AS (
            SELECT
                game_id,
                game_date,
                -- Defending team is opposite of shooting team
                CASE
                    WHEN shooting_team = home_team_abbr THEN away_team_abbr
                    ELSE home_team_abbr
                END as defending_team_abbr,
                shooting_team as opponent_team_abbr,

                -- Rim stats (distance <= 4 feet)
                SUM(CASE WHEN shot_zone = 'rim' THEN 1 ELSE 0 END) as rim_fga_allowed,
                SUM(CASE WHEN shot_zone = 'rim' AND shot_made THEN 1 ELSE 0 END) as rim_fg_allowed,
                SUM(CASE WHEN shot_zone = 'rim' AND was_blocked THEN 1 ELSE 0 END) as blocks_at_rim,
                SUM(CASE WHEN shot_zone = 'rim' AND was_contested THEN 1 ELSE 0 END) as rim_contests,

                -- Paint stats (4 < distance <= 8 feet)
                SUM(CASE WHEN shot_zone IN ('rim', 'paint_non_rim') THEN 1 ELSE 0 END) as paint_fga_allowed,
                SUM(CASE WHEN shot_zone IN ('rim', 'paint_non_rim') AND shot_made THEN 1 ELSE 0 END) as paint_fg_allowed,

                -- Three-point stats
                SUM(CASE WHEN shot_zone = 'three_pt' THEN 1 ELSE 0 END) as three_pt_fga_allowed,
                SUM(CASE WHEN shot_zone = 'three_pt' AND shot_made THEN 1 ELSE 0 END) as three_pt_fg_allowed,
                SUM(CASE WHEN shot_zone = 'three_pt' AND was_contested THEN 1 ELSE 0 END) as perimeter_contests,
                SUM(CASE WHEN shot_zone = 'three_pt' AND was_contested AND shot_made THEN 1 ELSE 0 END) as contested_three_pt_made,

                -- Mid-range stats
                SUM(CASE WHEN shot_zone = 'mid_range' THEN 1 ELSE 0 END) as mid_range_fga_allowed,
                SUM(CASE WHEN shot_zone = 'mid_range' AND shot_made THEN 1 ELSE 0 END) as mid_range_fg_allowed,

                -- Data source quality tracking
                -- Count how many events came from fallback vs primary source
                SUM(CASE WHEN data_source = 'nbacom_fallback' THEN 1 ELSE 0 END) as fallback_event_count,
                COUNT(*) as total_event_count,

                MAX(processed_at) as processed_at

            FROM shot_events
            GROUP BY game_id, game_date, defending_team_abbr, opponent_team_abbr
        )

        SELECT *,
            -- If ANY events came from fallback, note the mixed source
            CASE
                WHEN fallback_event_count > 0 AND fallback_event_count < total_event_count
                    THEN 'mixed_bigdataball_nbacom'
                WHEN fallback_event_count = total_event_count
                    THEN 'nbacom_fallback'
                ELSE 'bigdataball'
            END as data_source,
            -- Calculate fallback percentage for quality scoring
            SAFE_DIVIDE(fallback_event_count, total_event_count) as fallback_pct
        FROM defense_stats
        ORDER BY game_date DESC, game_id
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            if not df.empty:
                self.play_by_play_data = df
                self.source_tracking['play_by_play']['source_used'] = 'bigdataball_play_by_play'
                self.source_tracking['play_by_play']['rows_found'] = len(df)
                if 'processed_at' in df.columns and not df['processed_at'].isna().all():
                    self.source_tracking['play_by_play']['last_updated'] = df['processed_at'].max()

                # Track NBA.com fallback usage for quality monitoring
                if 'fallback_pct' in df.columns:
                    fallback_records = (df['data_source'] == 'nbacom_fallback').sum()
                    mixed_records = (df['data_source'] == 'mixed_bigdataball_nbacom').sum()
                    if fallback_records > 0 or mixed_records > 0:
                        logger.warning(
                            f"NBA.com fallback detected: {fallback_records} full fallback, "
                            f"{mixed_records} mixed source records. "
                            f"Lineup fields (away_player_1-5, home_player_1-5) are NULL for fallback data."
                        )
                        self.source_tracking['play_by_play']['has_fallback_data'] = True
                        self.source_tracking['play_by_play']['fallback_count'] = fallback_records + mixed_records

                logger.info(f"Extracted {len(df)} play-by-play records from bigdataball")
                return
        except Exception as e:
            logger.warning(f"Failed to extract from bigdataball_play_by_play: {e}")

        # Fallback to nbac_play_by_play
        logger.info("Falling back to nbac_play_by_play")
        self._extract_play_by_play_fallback()

    def _extract_play_by_play_fallback(self) -> None:
        """
        Fallback extraction from nbac_play_by_play.

        TODO: Implement full fallback query similar to bigdataball.
        For now, creates placeholder with NULL values.
        """
        # TODO: Implement nbac_play_by_play extraction
        # The nbac_play_by_play table may have different column names
        # and requires different parsing logic

        logger.warning("nbac_play_by_play fallback not fully implemented - using placeholder data")
        self.play_by_play_data = pd.DataFrame()
        self.source_tracking['play_by_play']['source_used'] = 'placeholder'
        self.source_tracking['play_by_play']['rows_found'] = 0

    def _extract_team_boxscore_data(self) -> None:
        """
        Extract team boxscore data for defensive stats.
        """
        query = f"""
        SELECT
            game_id,
            game_date,
            team_abbr,
            -- Defensive stats (these are the team's own defensive actions)
            COALESCE(blocks, 0) as team_blocks,
            COALESCE(steals, 0) as team_steals,
            COALESCE(defensive_rebounds, 0) as defensive_rebounds,
            -- Opponent's scoring (points allowed)
            -- We need to join with opponent's row for this
            processed_at
        FROM `{self.project_id}.nba_raw.nbac_team_boxscore`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
        ORDER BY game_date DESC, game_id
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            self.team_boxscore_data = df
            self.source_tracking['team_boxscore']['rows_found'] = len(df)
            if 'processed_at' in df.columns and not df['processed_at'].isna().all():
                self.source_tracking['team_boxscore']['last_updated'] = df['processed_at'].max()
            logger.info(f"Extracted {len(df)} team boxscore records")
        except Exception as e:
            logger.error(f"Failed to extract team boxscore data: {e}")
            self.team_boxscore_data = pd.DataFrame()

    def _extract_player_defensive_actions(self) -> None:
        """
        Extract player defensive actions (blocks by zone if available).

        TODO: If play-by-play has block zone data, use that instead.
        For now, extracts aggregate blocks from player boxscores.
        """
        query = f"""
        SELECT
            game_id,
            game_date,
            team_abbr,
            SUM(COALESCE(blocks, 0)) as total_blocks,
            SUM(COALESCE(steals, 0)) as total_steals,
            COUNT(*) as players_count,
            MAX(processed_at) as processed_at
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND player_status = 'active'
        GROUP BY game_id, game_date, team_abbr
        ORDER BY game_date DESC, game_id
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            self.player_defensive_actions = df
            self.source_tracking['player_actions']['rows_found'] = len(df)
            if 'processed_at' in df.columns and not df['processed_at'].isna().all():
                self.source_tracking['player_actions']['last_updated'] = df['processed_at'].max()
            logger.info(f"Extracted {len(df)} player defensive action records")
        except Exception as e:
            logger.warning(f"Failed to extract player defensive actions: {e}")
            self.player_defensive_actions = pd.DataFrame()

    def _calculate_league_averages(self) -> None:
        """
        Calculate league-wide defensive averages for comparison.

        Uses last 30 days of data to get representative sample.
        """
        lookback_date = self.end_date - timedelta(days=30)

        # TODO: Calculate actual league averages from play-by-play data
        # For now, use historical NBA averages as placeholders

        self.league_averages = {
            'paint_fg_pct': 0.580,  # ~58% FG% in paint
            'rim_fg_pct': 0.620,   # ~62% FG% at rim
            'three_pt_pct': 0.355,  # ~35.5% 3PT%
            'rim_contest_rate': 0.45,  # ~45% of rim shots contested
            'perimeter_contest_rate': 0.40,  # ~40% of 3PT shots contested
        }

        logger.info(f"Using league averages: {self.league_averages}")

    def calculate_analytics(self) -> None:
        """
        Calculate defense zone analytics for all teams.

        For each team-game:
        - Calculate points in paint allowed
        - Calculate 3PT defense rating
        - Calculate rim protection stats
        - Calculate perimeter contest rate
        - Compare to league averages
        """
        if not self.teams_to_process:
            logger.warning("No teams to process")
            self.transformed_data = []
            return

        logger.info(f"Calculating defense zone analytics for {len(self.teams_to_process)} team-games")

        if ENABLE_TEAM_PARALLELIZATION:
            records, failed = self._process_teams_parallel()
        else:
            records, failed = self._process_teams_serial()

        self.transformed_data = records
        self.failed_entities = failed

        logger.info(f"Processed {len(records)} team-game records, {len(failed)} failed")

    def _process_teams_parallel(self) -> Tuple[List[Dict], List[Dict]]:
        """Process all team-games using ThreadPoolExecutor."""
        DEFAULT_WORKERS = 4
        max_workers = int(os.environ.get(
            'DZA_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        logger.info(f"Processing {len(self.teams_to_process)} team-games with {max_workers} workers")

        loop_start = time.time()
        processed_count = 0

        records = []
        failed = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._process_single_team_game, team_game): team_game
                for team_game in self.teams_to_process
            }

            for future in as_completed(futures):
                team_game = futures[future]
                processed_count += 1

                try:
                    success, data = future.result()
                    if success:
                        records.append(data)
                    else:
                        failed.append(data)

                    if processed_count % 20 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed if elapsed > 0 else 0
                        logger.info(f"Progress: {processed_count}/{len(self.teams_to_process)} ({rate:.1f}/sec)")

                except Exception as e:
                    logger.error(f"Error processing {team_game}: {e}")
                    failed.append({
                        'entity_id': f"{team_game.get('game_id')}_{team_game.get('team_abbr')}",
                        'reason': str(e),
                        'category': 'PROCESSING_ERROR'
                    })

        return records, failed

    def _process_teams_serial(self) -> Tuple[List[Dict], List[Dict]]:
        """Process all team-games serially."""
        records = []
        failed = []

        for team_game in self.teams_to_process:
            success, data = self._process_single_team_game(team_game)
            if success:
                records.append(data)
            else:
                failed.append(data)

        return records, failed

    def _process_single_team_game(self, team_game: Dict) -> Tuple[bool, Dict]:
        """
        Process a single team-game record.

        Returns:
            (True, record_dict) on success
            (False, error_dict) on failure
        """
        try:
            game_id = team_game['game_id']
            game_date = team_game['game_date']
            team_abbr = team_game['team_abbr']
            opponent_abbr = team_game.get('opponent_team_abbr')
            home_game = team_game.get('home_game', False)

            # Get play-by-play data for this game and team
            pbp_data = self._get_pbp_for_team_game(game_id, team_abbr)

            # Get team boxscore data
            boxscore_data = self._get_boxscore_for_team_game(game_id, team_abbr)

            # Calculate metrics
            metrics = self._calculate_defense_metrics(pbp_data, boxscore_data)

            # Get rolling averages
            rolling = self._get_rolling_averages(team_abbr, game_date)

            # Determine data quality
            quality_tier, quality_score, quality_issues = self._assess_data_quality(
                pbp_data, boxscore_data, metrics
            )

            # Build quality columns
            quality_columns = build_quality_columns_with_legacy(
                tier=quality_tier,
                score=quality_score,
                issues=quality_issues,
                sources=[self.source_tracking['play_by_play'].get('source_used', 'unknown')]
            )

            record = {
                # Core identifiers
                'game_date': game_date.isoformat() if isinstance(game_date, date) else str(game_date),
                'game_id': game_id,
                'team_abbr': team_abbr,
                'opponent_team_abbr': opponent_abbr,
                'home_game': home_game,

                # Points allowed in paint metrics
                'points_in_paint_allowed': metrics.get('points_in_paint_allowed'),
                'paint_fg_allowed': metrics.get('paint_fg_allowed'),
                'paint_fga_allowed': metrics.get('paint_fga_allowed'),
                'paint_fg_pct_allowed': metrics.get('paint_fg_pct_allowed'),
                'paint_fg_pct_vs_league_avg': self._calc_vs_league_avg(
                    metrics.get('paint_fg_pct_allowed'),
                    self.league_averages.get('paint_fg_pct')
                ),

                # 3PT defense rating metrics
                'three_pt_fg_allowed': metrics.get('three_pt_fg_allowed'),
                'three_pt_fga_allowed': metrics.get('three_pt_fga_allowed'),
                'three_pt_pct_allowed': metrics.get('three_pt_pct_allowed'),
                'three_pt_pct_vs_league_avg': self._calc_vs_league_avg(
                    metrics.get('three_pt_pct_allowed'),
                    self.league_averages.get('three_pt_pct')
                ),
                'three_pt_defense_rating': self._calc_three_pt_defense_rating(metrics),

                # Rim protection stats
                'blocks_at_rim': metrics.get('blocks_at_rim'),
                'rim_contests': metrics.get('rim_contests'),
                'rim_fg_allowed': metrics.get('rim_fg_allowed'),
                'rim_fga_allowed': metrics.get('rim_fga_allowed'),
                'rim_fg_pct_allowed': metrics.get('rim_fg_pct_allowed'),
                'rim_contest_rate': metrics.get('rim_contest_rate'),
                'rim_protection_rating': self._calc_rim_protection_rating(metrics),

                # Perimeter contest rate
                'perimeter_contests': metrics.get('perimeter_contests'),
                'perimeter_shots_faced': metrics.get('three_pt_fga_allowed'),
                'perimeter_contest_rate': metrics.get('perimeter_contest_rate'),
                'contested_three_pt_made': metrics.get('contested_three_pt_made'),
                'contested_three_pt_pct': self._safe_divide(
                    metrics.get('contested_three_pt_made'),
                    metrics.get('perimeter_contests')
                ),

                # Rolling averages
                'paint_pts_allowed_l5': rolling.get('paint_pts_allowed_l5'),
                'paint_pts_allowed_l10': rolling.get('paint_pts_allowed_l10'),
                'three_pt_pct_allowed_l5': rolling.get('three_pt_pct_allowed_l5'),
                'three_pt_pct_allowed_l10': rolling.get('three_pt_pct_allowed_l10'),
                'rim_protection_rating_l5': rolling.get('rim_protection_rating_l5'),
                'perimeter_contest_rate_l5': rolling.get('perimeter_contest_rate_l5'),

                # Context
                'games_in_sample': 1,  # This is single-game data

                # Quality columns
                **quality_columns,

                # Source tracking
                **self.build_source_tracking_fields(),

                # Processing metadata
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'created_at': datetime.now(timezone.utc).isoformat()
            }

            # Calculate data hash
            record['data_hash'] = self._calculate_data_hash(record)

            return (True, record)

        except Exception as e:
            logger.error(f"Failed to process {team_game}: {e}", exc_info=True)
            return (False, {
                'entity_id': f"{team_game.get('game_id')}_{team_game.get('team_abbr')}",
                'reason': str(e),
                'category': 'PROCESSING_ERROR'
            })

    def _get_pbp_for_team_game(self, game_id: str, team_abbr: str) -> Dict:
        """Get play-by-play data for a specific team-game."""
        if isinstance(self.play_by_play_data, pd.DataFrame) and not self.play_by_play_data.empty:
            mask = (
                (self.play_by_play_data['game_id'] == game_id) &
                (self.play_by_play_data['defending_team_abbr'] == team_abbr)
            )
            matches = self.play_by_play_data[mask]
            if not matches.empty:
                return matches.iloc[0].to_dict()
        return {}

    def _get_boxscore_for_team_game(self, game_id: str, team_abbr: str) -> Dict:
        """Get boxscore data for a specific team-game."""
        if isinstance(self.team_boxscore_data, pd.DataFrame) and not self.team_boxscore_data.empty:
            mask = (
                (self.team_boxscore_data['game_id'] == game_id) &
                (self.team_boxscore_data['team_abbr'] == team_abbr)
            )
            matches = self.team_boxscore_data[mask]
            if not matches.empty:
                return matches.iloc[0].to_dict()
        return {}

    def _calculate_defense_metrics(self, pbp_data: Dict, boxscore_data: Dict) -> Dict:
        """
        Calculate defensive metrics from play-by-play and boxscore data.
        """
        metrics = {}

        # Paint metrics
        paint_fg = pbp_data.get('paint_fg_allowed', 0) or 0
        paint_fga = pbp_data.get('paint_fga_allowed', 0) or 0
        metrics['paint_fg_allowed'] = paint_fg
        metrics['paint_fga_allowed'] = paint_fga
        metrics['paint_fg_pct_allowed'] = self._safe_divide(paint_fg, paint_fga)
        metrics['points_in_paint_allowed'] = paint_fg * 2  # All paint shots are 2PT

        # Rim metrics
        rim_fg = pbp_data.get('rim_fg_allowed', 0) or 0
        rim_fga = pbp_data.get('rim_fga_allowed', 0) or 0
        rim_contests = pbp_data.get('rim_contests', 0) or 0
        blocks_at_rim = pbp_data.get('blocks_at_rim', 0) or 0
        metrics['rim_fg_allowed'] = rim_fg
        metrics['rim_fga_allowed'] = rim_fga
        metrics['rim_fg_pct_allowed'] = self._safe_divide(rim_fg, rim_fga)
        metrics['rim_contests'] = rim_contests
        metrics['blocks_at_rim'] = blocks_at_rim
        metrics['rim_contest_rate'] = self._safe_divide(rim_contests, rim_fga)

        # 3PT metrics
        three_fg = pbp_data.get('three_pt_fg_allowed', 0) or 0
        three_fga = pbp_data.get('three_pt_fga_allowed', 0) or 0
        perimeter_contests = pbp_data.get('perimeter_contests', 0) or 0
        contested_made = pbp_data.get('contested_three_pt_made', 0) or 0
        metrics['three_pt_fg_allowed'] = three_fg
        metrics['three_pt_fga_allowed'] = three_fga
        metrics['three_pt_pct_allowed'] = self._safe_divide(three_fg, three_fga)
        metrics['perimeter_contests'] = perimeter_contests
        metrics['contested_three_pt_made'] = contested_made
        metrics['perimeter_contest_rate'] = self._safe_divide(perimeter_contests, three_fga)

        return metrics

    def _get_rolling_averages(self, team_abbr: str, game_date: date) -> Dict:
        """
        Get rolling averages for a team.

        TODO: Implement actual rolling average calculation from historical data.
        For now, returns placeholder values.
        """
        # TODO: Query historical defense_zone_analytics for rolling averages
        # This requires the table to already have historical data

        return {
            'paint_pts_allowed_l5': None,
            'paint_pts_allowed_l10': None,
            'three_pt_pct_allowed_l5': None,
            'three_pt_pct_allowed_l10': None,
            'rim_protection_rating_l5': None,
            'perimeter_contest_rate_l5': None,
        }

    def _calc_vs_league_avg(self, value: Optional[float], league_avg: Optional[float]) -> Optional[float]:
        """Calculate difference from league average in percentage points."""
        if value is None or league_avg is None:
            return None
        return round((value - league_avg) * 100, 2)

    def _calc_three_pt_defense_rating(self, metrics: Dict) -> Optional[float]:
        """
        Calculate 3PT defense rating.

        Rating combines:
        - 3PT% allowed (lower is better)
        - Perimeter contest rate (higher is better)

        Scale: 0-100, higher is better defense
        """
        three_pct = metrics.get('three_pt_pct_allowed')
        contest_rate = metrics.get('perimeter_contest_rate')

        if three_pct is None and contest_rate is None:
            return None

        # Normalize 3PT% (league avg ~35.5%, range 30-42%)
        three_score = 0
        if three_pct is not None:
            # Lower is better, so invert
            three_score = max(0, min(100, (0.42 - three_pct) / 0.12 * 50))

        # Normalize contest rate (league avg ~40%, range 30-60%)
        contest_score = 0
        if contest_rate is not None:
            contest_score = max(0, min(100, (contest_rate - 0.30) / 0.30 * 50))

        return round(three_score + contest_score, 1)

    def _calc_rim_protection_rating(self, metrics: Dict) -> Optional[float]:
        """
        Calculate rim protection rating.

        Rating combines:
        - Rim FG% allowed (lower is better)
        - Rim contest rate (higher is better)
        - Blocks at rim (higher is better)

        Scale: 0-100, higher is better defense
        """
        rim_pct = metrics.get('rim_fg_pct_allowed')
        contest_rate = metrics.get('rim_contest_rate')
        blocks = metrics.get('blocks_at_rim', 0)

        if rim_pct is None and contest_rate is None:
            return None

        # Normalize rim FG% (league avg ~62%, range 55-70%)
        rim_score = 0
        if rim_pct is not None:
            rim_score = max(0, min(40, (0.70 - rim_pct) / 0.15 * 40))

        # Normalize contest rate (league avg ~45%, range 35-60%)
        contest_score = 0
        if contest_rate is not None:
            contest_score = max(0, min(40, (contest_rate - 0.35) / 0.25 * 40))

        # Blocks bonus (0-5 blocks = 0-20 points)
        block_score = min(20, (blocks or 0) * 4)

        return round(rim_score + contest_score + block_score, 1)

    def _safe_divide(self, numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
        """Safe division that returns None if denominator is 0 or None."""
        if numerator is None or denominator is None or denominator == 0:
            return None
        return round(numerator / denominator, 4)

    def _assess_data_quality(
        self,
        pbp_data: Dict,
        boxscore_data: Dict,
        metrics: Dict
    ) -> Tuple[str, float, List[str]]:
        """
        Assess data quality based on available data.

        Handles NBA.com fallback data gracefully:
        - When data_source = 'nbacom_fallback', lineup fields are NULL
        - Contest/block tracking may be less accurate with fallback data
        - Slight quality penalty applied but data is still usable

        Returns:
            (tier, score, issues) tuple
        """
        issues = []
        score = 100.0

        # Check if we have play-by-play data
        if not pbp_data:
            issues.append('no_pbp_data')
            score -= 40
        else:
            # Check for NBA.com fallback data (lineup fields are NULL)
            data_source = pbp_data.get('data_source', 'bigdataball')
            if data_source == 'nbacom_fallback':
                issues.append('nbacom_fallback_no_lineups')
                score -= 5  # Minor penalty - core stats still accurate
            elif data_source == 'mixed_bigdataball_nbacom':
                issues.append('mixed_source_data')
                score -= 3  # Very minor penalty for mixed sources

            # Check fallback percentage if available
            fallback_pct = pbp_data.get('fallback_pct', 0)
            if fallback_pct and fallback_pct > 0.5:
                issues.append('high_fallback_ratio')
                score -= 5  # Additional penalty if >50% is fallback

        # Check if we have boxscore data
        if not boxscore_data:
            issues.append('no_boxscore_data')
            score -= 20

        # Check for missing key metrics
        if metrics.get('paint_fg_pct_allowed') is None:
            issues.append('missing_paint_pct')
            score -= 10
        if metrics.get('three_pt_pct_allowed') is None:
            issues.append('missing_three_pt_pct')
            score -= 10
        if metrics.get('rim_contest_rate') is None:
            issues.append('missing_rim_contests')
            score -= 10

        # Determine tier
        if score >= 80:
            tier = 'gold'
        elif score >= 60:
            tier = 'silver'
        else:
            tier = 'bronze'

        return tier, max(0, score), issues

    def _calculate_data_hash(self, record: Dict) -> str:
        """Calculate SHA256 hash of meaningful analytics fields."""
        hash_data = {field: record.get(field) for field in self.HASH_FIELDS}
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]

    def get_analytics_stats(self) -> Dict:
        """Return defense zone analytics stats."""
        if not self.transformed_data:
            return {}

        total_records = len(self.transformed_data)

        # Quality distribution
        gold = sum(1 for r in self.transformed_data if r.get('quality_tier') == 'gold')
        silver = sum(1 for r in self.transformed_data if r.get('quality_tier') == 'silver')
        bronze = sum(1 for r in self.transformed_data if r.get('quality_tier') == 'bronze')

        # Average metrics
        paint_pcts = [r['paint_fg_pct_allowed'] for r in self.transformed_data
                     if r.get('paint_fg_pct_allowed') is not None]
        three_pcts = [r['three_pt_pct_allowed'] for r in self.transformed_data
                     if r.get('three_pt_pct_allowed') is not None]

        return {
            'records_processed': total_records,
            'records_failed': len(self.failed_entities),
            'gold_quality': gold,
            'silver_quality': silver,
            'bronze_quality': bronze,
            'avg_paint_fg_pct_allowed': round(sum(paint_pcts) / len(paint_pcts), 3) if paint_pcts else None,
            'avg_three_pt_pct_allowed': round(sum(three_pcts) / len(three_pcts), 3) if three_pcts else None,
            'source_used': self.source_tracking['play_by_play'].get('source_used'),
        }


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Process defense zone analytics")
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        processor = DefenseZoneAnalyticsProcessor()

        success = processor.run({
            'start_date': args.start_date,
            'end_date': args.end_date
        })

        # Print stats
        stats = processor.get_analytics_stats()
        print(f"\nProcessing Results:")
        print(f"  Records processed: {stats.get('records_processed', 0)}")
        print(f"  Records failed: {stats.get('records_failed', 0)}")
        print(f"  Quality distribution: Gold={stats.get('gold_quality', 0)}, "
              f"Silver={stats.get('silver_quality', 0)}, Bronze={stats.get('bronze_quality', 0)}")

        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
