#!/usr/bin/env python3
"""
Path: analytics_processors/team_offense_game_summary/team_offense_game_summary_processor.py

Team Offense Game Summary Processor for NBA Props Platform Analytics.
Aggregates team box score statistics into comprehensive offensive analytics.

Phase 3 Analytics Processor with full dependency tracking (v4.0 pattern).

Dependencies (Phase 2):
  - nba_raw.nbac_team_boxscore (PRIMARY - CRITICAL)
  - nba_raw.nbac_play_by_play (ENHANCEMENT - OPTIONAL for shot zones)

Output: nba_analytics.team_offense_game_summary

Processing Strategy: MERGE_UPDATE
  - Allows re-processing to add shot zones when play-by-play arrives
  - Updates existing records rather than creating duplicates

Key Features:
  - Full dependency checking before extraction
  - Source tracking per v4.0 dependency guide
  - Advanced metric calculations (ORtg, pace, possessions, TS%)
  - OT period parsing from minutes string
  - Win/loss determination via self-join
  - Optional shot zone extraction from play-by-play
  - Comprehensive data quality validation

Version: 2.0 (updated for AnalyticsProcessorBase v2.0)
Updated: January 2025
"""

import hashlib
import json
import logging
import os
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

# Fallback and quality patterns (Data Fallback System)
from shared.processors.patterns.fallback_source_mixin import FallbackSourceMixin
from shared.processors.patterns.quality_mixin import QualityMixin
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

logger = logging.getLogger(__name__)

# Feature flag for team-level parallelization
ENABLE_TEAM_PARALLELIZATION = os.environ.get('ENABLE_TEAM_PARALLELIZATION', 'true').lower() == 'true'


def safe_int(value, default=None):
    """
    Safely convert value to int, handling NaN, None, and empty strings.

    Args:
        value: Value to convert to int
        default: Default value to return if conversion fails (default: None)

    Returns:
        int or default value

    Examples:
        >>> safe_int(123)
        123
        >>> safe_int("456")
        456
        >>> safe_int("")
        None
        >>> safe_int("  ")
        None
        >>> safe_int(None)
        None
        >>> safe_int(float('nan'))
        None
        >>> safe_int("", default=0)
        0
    """
    # Handle pandas NaN, None, and numpy NaN
    if pd.isna(value):
        return default

    # Handle string values - strip whitespace and check if empty
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default

    # Try conversion
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class TeamOffenseGameSummaryProcessor(
    FallbackSourceMixin,
    QualityMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Process team offensive game summary analytics from team box scores.

    Aggregates team-level statistics with optional shot zone enhancement.
    Includes full dependency tracking and source metadata.
    """

    # ============================================================
    # Pattern #3: Smart Reprocessing - Data Hash Fields
    # ============================================================
    # Fields included in data_hash calculation (34 fields total)
    # EXCLUDES: Metadata (source_*, data_quality_*, created_at, processed_at, data_hash)
    HASH_FIELDS = [
        # Core identifiers (6 fields)
        'game_id', 'nba_game_id', 'game_date', 'team_abbr',
        'opponent_team_abbr', 'season_year',

        # Basic offensive stats (11 fields)
        'points_scored', 'fg_attempts', 'fg_makes', 'three_pt_attempts',
        'three_pt_makes', 'ft_attempts', 'ft_makes', 'rebounds',
        'assists', 'turnovers', 'personal_fouls',

        # Team shot zone performance (6 fields)
        'team_paint_attempts', 'team_paint_makes', 'team_mid_range_attempts',
        'team_mid_range_makes', 'points_in_paint_scored',
        'second_chance_points_scored',

        # Advanced offensive metrics (4 fields)
        'offensive_rating', 'pace', 'possessions', 'ts_pct',

        # Game context (4 fields)
        'home_game', 'win_flag', 'margin_of_victory', 'overtime_periods',

        # Team situation context (2 fields)
        'players_inactive', 'starters_inactive',

        # Referee integration (1 field)
        'referee_crew_id'
    ]

    # Primary key fields for duplicate detection and MERGE operations
    # Session 103: Changed from ['game_id', 'team_abbr'] to ['game_date', 'team_abbr']
    # This prevents duplicates caused by different game_id formats (AWAY_HOME vs HOME_AWAY)
    # Business logic: One team plays at most one game per day (doubleheaders are extremely rare in NBA)
    PRIMARY_KEY_FIELDS = ['game_date', 'team_abbr']

    def __init__(self):
        super().__init__()
        self.table_name = 'team_offense_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

        # Source metadata tracking (populated by track_source_usage)
        self.source_metadata = {}

        # Per-source attributes (for build_source_tracking_fields)
        self.source_nbac_boxscore_last_updated = None
        self.source_nbac_boxscore_rows_found = None
        self.source_nbac_boxscore_completeness_pct = None

        self.source_play_by_play_last_updated = None
        self.source_play_by_play_rows_found = None
        self.source_play_by_play_completeness_pct = None

        # Shot zone tracking
        self.shot_zones_available = False
        self.shot_zones_source = None
        self.shot_zone_data = {}  # Keyed by (game_id, team_abbr)

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Team boxscore sources - RELEVANT (core offensive data)
        'nbac_team_boxscore': True,
        'bdl_team_boxscores': True,
        'espn_team_stats': True,

        # Player boxscore sources - RELEVANT (for aggregation)
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': False,  # DISABLED - BDL intentionally disabled (Sessions 41, 94, 197)
        'nbac_player_boxscores': True,

        # Play-by-play sources - RELEVANT (shot zones)
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Player prop sources - NOT RELEVANT
        'odds_api_player_points_props': False,
        'bettingpros_player_points_props': False,
        'odds_api_player_rebounds_props': False,
        'odds_api_player_assists_props': False,

        # Game odds/spreads - NOT RELEVANT
        'odds_api_spreads': False,
        'odds_api_totals': False,
        'odds_game_lines': False,

        # Injury/roster sources - NOT RELEVANT
        'nbac_injury_report': False,
        'nbacom_roster': False,

        # Schedule sources - NOT RELEVANT
        'nbacom_schedule': False,
        'espn_scoreboard': False
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

    # =========================================================================
    # Dependency System (Phase 3 - Date Range Pattern)
    # =========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define required upstream Phase 2 tables and their constraints.
        
        Returns:
            dict: Dependency configuration per v4.0 spec
        """
        return {
            'nba_raw.nbac_team_boxscore': {
                'field_prefix': 'source_nbac_boxscore',
                'description': 'Team box score statistics',
                'date_field': 'game_date',
                'check_type': 'date_range',  # ✅ FIXED: was 'date_match', now 'date_range'
                'expected_count_min': 20,  # ~10 games × 2 teams per game
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                # NOT critical: has fallback to reconstruct from player boxscores
                'critical': False
            },
            'nba_raw.nbac_play_by_play': {
                'field_prefix': 'source_play_by_play',
                'description': 'Play-by-play for shot zones',
                'date_field': 'game_date',
                'check_type': 'date_range',  # ✅ FIXED: was 'lookback', now 'date_range'
                'expected_count_min': 1000,  # Many events per game day
                'max_age_hours_warn': 48,
                'max_age_hours_fail': 168,
                'critical': False  # Can proceed without shot zones
            }
        }

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Prevents retry storms by verifying:
        1. Games are finished (not scheduled/in-progress)
        2. Team boxscore data exists for those games

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

    # =========================================================================
    # Data Extraction (Phase 2 Raw Tables)
    # =========================================================================

    def extract_raw_data(self) -> None:
        """
        Extract team offensive data from Phase 2 raw tables.

        Primary source: nba_raw.nbac_team_boxscore (v2.0)
        Enhancement: nba_raw.nbac_play_by_play (for shot zones)

        Note: Dependency checking happens in base class run() before this is called.

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(start_date)
        if skip:
            logger.info(f"✅ SMART REPROCESSING: Skipping processing - {reason}")
            self.raw_data = pd.DataFrame()
            return

        logger.info(f"🔄 PROCESSING: {reason}")

        # FIX #3: EMERGENCY OVERRIDE - Force reconstruction (bypasses nbac_team_boxscore entirely)
        # Use case: When nbac_team_boxscore is known to be unreliable
        # Set environment variable: export FORCE_TEAM_RECONSTRUCTION=true
        if os.environ.get('FORCE_TEAM_RECONSTRUCTION', 'false').lower() == 'true':
            logger.info(
                "🔧 FORCE_TEAM_RECONSTRUCTION enabled - bypassing nbac_team_boxscore entirely. "
                "Using reconstruction from player boxscores only."
            )
            self.raw_data = self._reconstruct_team_from_players(start_date, end_date)

            if self.raw_data is not None and not self.raw_data.empty:
                self._source_used = 'reconstructed_team_from_players (forced by env var)'
                logger.info(f"✅ Reconstructed {len(self.raw_data)} team-game records from players")
                # Set quality tracking for reconstruction
                self._fallback_quality_tier = 'silver'
                self._fallback_quality_score = 85
                self._fallback_quality_issues = ['forced_reconstruction']
                self._fallback_handled = False
                return  # Skip fallback chain entirely
            else:
                logger.warning(
                    "⚠️  FORCE_TEAM_RECONSTRUCTION enabled but reconstruction returned no data. "
                    "Falling back to normal fallback chain."
                )
                # Fall through to normal logic

        # Use fallback chain for team boxscore data
        fallback_result = self.try_fallback_chain(
            chain_name='team_boxscores',
            extractors={
                'nbac_team_boxscore': lambda: self._extract_from_nbac_team_boxscore(start_date, end_date),
                'reconstructed_team_from_players': lambda: self._reconstruct_team_from_players(start_date, end_date),
            },
            context={
                'game_date': start_date,
                'processor': 'team_offense_game_summary',
            },
        )

        # Handle fallback result
        if fallback_result.should_skip:
            logger.warning(f"Skipping date range {start_date}-{end_date}: no team data available")
            self.raw_data = pd.DataFrame()
            self._fallback_handled = True
            return

        if fallback_result.is_placeholder:
            logger.warning(f"No team data for {start_date}-{end_date}, will skip")
            self.raw_data = pd.DataFrame()
            self._fallback_handled = True
            return

        self.raw_data = fallback_result.data

        # FIX #2: COMPLETENESS VALIDATION - Reject partial data from nbac_team_boxscore
        # Investigation 2026-01-04: Fallback chain accepts partial data as "success"
        # Example: 2 teams out of 18 considered success, reconstruction never tried
        if fallback_result.source_used == 'nbac_team_boxscore':
            team_count = len(self.raw_data)

            # Reasonable threshold: 10+ teams (5+ games)
            # Normal game day: 20-30 teams (10-15 games)
            MIN_TEAMS_THRESHOLD = 10

            if team_count < MIN_TEAMS_THRESHOLD:
                logger.warning(
                    f"⚠️  COMPLETENESS CHECK FAILED: nbac_team_boxscore returned only {team_count} teams "
                    f"(threshold: {MIN_TEAMS_THRESHOLD}). This is likely incomplete data. "
                    f"Forcing reconstruction from player boxscores..."
                )

                # Try reconstruction instead
                reconstructed_data = self._reconstruct_team_from_players(start_date, end_date)

                if reconstructed_data is not None and not reconstructed_data.empty:
                    reconstructed_count = len(reconstructed_data)
                    logger.info(
                        f"✅ Reconstruction successful: {reconstructed_count} teams "
                        f"(+{reconstructed_count - team_count} more than nbac_team_boxscore)"
                    )
                    self.raw_data = reconstructed_data
                    self._source_used = 'reconstructed_team_from_players (forced by completeness check)'
                    # Update quality tracking
                    self._fallback_quality_tier = 'silver'  # Reconstructed data quality
                    self._fallback_quality_score = 85
                else:
                    logger.warning(
                        f"⚠️  Reconstruction also failed/empty. Keeping nbac_team_boxscore data "
                        f"({team_count} teams) despite incompleteness."
                    )

        # Track quality from fallback
        self._fallback_quality_tier = fallback_result.quality_tier
        self._fallback_quality_score = fallback_result.quality_score
        self._fallback_quality_issues = fallback_result.quality_issues
        self._source_used = fallback_result.source_used

        logger.info(
            f"Extracted {len(self.raw_data)} team-game records "
            f"(source: {fallback_result.source_used}, quality: {fallback_result.quality_tier})"
        )

        if not self.raw_data.empty:
            # Extract shot zones if play-by-play available
            self._extract_shot_zones(start_date, end_date)

    def _extract_from_nbac_team_boxscore(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Extract team offensive data from nbac_team_boxscore (PRIMARY source)."""
        query = f"""
        WITH team_boxscores_raw AS (
            -- Deduplicate source data (may have duplicates from bulk loads)
            SELECT
                game_id,
                nba_game_id,
                game_date,
                season_year,
                team_abbr,
                team_name,
                is_home,
                points,
                fg_made,
                fg_attempted,
                fg_percentage,
                three_pt_made,
                three_pt_attempted,
                three_pt_percentage,
                ft_made,
                ft_attempted,
                ft_percentage,
                offensive_rebounds,
                defensive_rebounds,
                total_rebounds,
                assists,
                steals,
                blocks,
                turnovers,
                personal_fouls,
                plus_minus,
                minutes,
                processed_at,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, team_abbr
                    ORDER BY processed_at DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.nbac_team_boxscore`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),

        team_boxscores_dedup AS (
            -- Keep only most recent record per game-team
            SELECT * EXCEPT(rn) FROM team_boxscores_raw WHERE rn = 1
        ),

        team_boxscores AS (
            SELECT
                -- FIX: Standardize game_id to AWAY_HOME format for consistent JOINs
                -- Player analytics uses AWAY_HOME format, so team analytics must match
                CASE
                    WHEN tb.is_home THEN CONCAT(
                        FORMAT_DATE('%Y%m%d', tb.game_date),
                        '_',
                        t2.team_abbr,  -- away team (opponent when we're home)
                        '_',
                        tb.team_abbr   -- home team (us)
                    )
                    ELSE CONCAT(
                        FORMAT_DATE('%Y%m%d', tb.game_date),
                        '_',
                        tb.team_abbr,  -- away team (us)
                        '_',
                        t2.team_abbr   -- home team (opponent when we're away)
                    )
                END as game_id,
                -- tb.game_id as original_game_id,  -- Original from source (not in schema)
                tb.nba_game_id,
                tb.game_date,
                tb.season_year,
                tb.team_abbr,
                tb.team_name,
                tb.is_home,

                -- Opponent via self-join (simplified with v2.0 is_home)
                t2.team_abbr as opponent_team_abbr,
                t2.points as opponent_points,

                -- Basic stats
                tb.points,
                tb.fg_made,
                tb.fg_attempted,
                tb.fg_percentage,
                tb.three_pt_made,
                tb.three_pt_attempted,
                tb.three_pt_percentage,
                tb.ft_made,
                tb.ft_attempted,
                tb.ft_percentage,
                tb.offensive_rebounds,
                tb.defensive_rebounds,
                tb.total_rebounds,
                tb.assists,
                tb.steals,
                tb.blocks,
                tb.turnovers,
                tb.personal_fouls,
                tb.plus_minus,

                -- Minutes for OT calculation
                tb.minutes,

                -- Source tracking
                tb.processed_at as source_last_updated

            FROM team_boxscores_dedup tb

            -- Self-join for opponent context (v2.0: simplified with is_home)
            JOIN team_boxscores_dedup t2
                ON tb.game_id = t2.game_id
                AND tb.game_date = t2.game_date
                AND tb.is_home != t2.is_home  -- Get OTHER team
        )
        SELECT * FROM team_boxscores
        ORDER BY game_date DESC, game_id, team_abbr
        """

        try:
            df = self.bq_client.query(query).to_dataframe()

            # ===== Quality validation (Session 117) =====
            if df is None or df.empty:
                logger.info("No data returned from nbac_team_boxscore")
                return pd.DataFrame()

            # Filter out invalid rows (0 values = placeholder/incomplete data from in-progress games)
            # Session 302: Changed from reject-all to filter-invalid. Previously, ANY team with
            # zeros caused ALL teams to be rejected, blocking the entire pipeline on nights with
            # late games still in progress. Now we keep valid teams and drop only the bad ones.
            valid_mask = (df['points'] > 0) & (df['fg_attempted'] > 0)
            invalid_rows = df[~valid_mask]

            if len(invalid_rows) > 0:
                invalid_teams = invalid_rows['team_abbr'].tolist()
                valid_count = len(df) - len(invalid_rows)
                logger.warning(
                    f"⚠️  QUALITY CHECK: Filtering {len(invalid_rows)} teams with invalid data "
                    f"(0 points or 0 FGA): {invalid_teams}. "
                    f"Keeping {valid_count} valid teams."
                )
                # Send Slack alert for visibility — partial processing needs follow-up
                notify_warning(
                    title="Team Offense: Partial Data — Some Teams Filtered",
                    message=(
                        f"Filtered {len(invalid_rows)} teams with 0 points/FGA "
                        f"(likely in-progress games). {valid_count} valid teams kept. "
                        f"Re-run Phase 3 after remaining games finish."
                    ),
                    details={
                        'processor': 'team_offense_game_summary',
                        'start_date': start_date,
                        'end_date': end_date,
                        'filtered_teams': invalid_teams,
                        'valid_teams_kept': valid_count,
                        'total_teams_received': len(df),
                        'action_needed': 'Re-trigger Phase 3 after all games are final',
                    },
                    processor_name=self.__class__.__name__
                )
                df = df[valid_mask].copy()

            if df.empty:
                logger.warning("All teams had invalid data after filtering — triggering fallback")
                return pd.DataFrame()
            # ===== END quality validation =====

            logger.info(f"✅ Extracted {len(df)} valid team-game records from nbac_team_boxscore")
            return df
        except Exception as e:
            logger.error(f"Failed to extract from nbac_team_boxscore: {e}")
            return pd.DataFrame()

    def _reconstruct_team_from_players(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Reconstruct team boxscore stats by aggregating player boxscores.

        FALLBACK method when nbac_team_boxscore is unavailable.
        Verified 100% accurate (GSW 121=121, LAL 114=114).
        """
        logger.info(f"FALLBACK: Reconstructing team stats from player boxscores for {start_date} to {end_date}")

        query = f"""
        WITH player_stats AS (
            SELECT
                game_id, game_date, season_year, team_abbr,
                COALESCE(points, 0) as points,
                COALESCE(field_goals_made, 0) as fg_made,
                COALESCE(field_goals_attempted, 0) as fg_attempted,
                COALESCE(three_pointers_made, 0) as three_pt_made,
                COALESCE(three_pointers_attempted, 0) as three_pt_attempted,
                COALESCE(free_throws_made, 0) as ft_made,
                COALESCE(free_throws_attempted, 0) as ft_attempted,
                COALESCE(total_rebounds, 0) as rebounds,
                COALESCE(offensive_rebounds, 0) as offensive_rebounds,
                COALESCE(defensive_rebounds, 0) as defensive_rebounds,
                COALESCE(assists, 0) as assists,
                COALESCE(turnovers, 0) as turnovers,
                COALESCE(steals, 0) as steals,
                COALESCE(blocks, 0) as blocks,
                COALESCE(personal_fouls, 0) as personal_fouls,
                processed_at
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND player_status = 'active'

            UNION ALL

            SELECT
                game_id, game_date, season_year, team_abbr,
                COALESCE(points, 0), COALESCE(field_goals_made, 0), COALESCE(field_goals_attempted, 0),
                COALESCE(three_pointers_made, 0), COALESCE(three_pointers_attempted, 0),
                COALESCE(free_throws_made, 0), COALESCE(free_throws_attempted, 0),
                COALESCE(rebounds, 0), COALESCE(offensive_rebounds, 0), COALESCE(defensive_rebounds, 0),
                COALESCE(assists, 0), COALESCE(turnovers, 0), COALESCE(steals, 0),
                COALESCE(blocks, 0), COALESCE(personal_fouls, 0), processed_at
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND game_id NOT IN (
                  SELECT DISTINCT game_id FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
                  WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              )
        ),

        team_totals AS (
            SELECT
                game_id, game_date, MAX(season_year) as season_year, team_abbr,
                SUM(points) as points, SUM(fg_made) as fg_made, SUM(fg_attempted) as fg_attempted,
                SUM(three_pt_made) as three_pt_made, SUM(three_pt_attempted) as three_pt_attempted,
                SUM(ft_made) as ft_made, SUM(ft_attempted) as ft_attempted,
                SUM(rebounds) as total_rebounds, SUM(offensive_rebounds) as offensive_rebounds,
                SUM(defensive_rebounds) as defensive_rebounds, SUM(assists) as assists,
                SUM(turnovers) as turnovers, SUM(steals) as steals, SUM(blocks) as blocks,
                SUM(personal_fouls) as personal_fouls, MAX(processed_at) as processed_at,
                COUNT(*) as player_count
            FROM player_stats
            GROUP BY game_id, game_date, team_abbr
            HAVING player_count >= 5
        ),

        game_context AS (
            SELECT DISTINCT game_id,
                SPLIT(game_id, '_')[SAFE_OFFSET(2)] as home_team_abbr
            FROM team_totals
        ),

        team_with_context AS (
            SELECT t.*,
                CASE WHEN t.team_abbr = g.home_team_abbr THEN TRUE ELSE FALSE END as is_home,
                t.game_id as nba_game_id,
                CAST(NULL AS STRING) as team_name,
                SAFE_DIVIDE(t.fg_made, t.fg_attempted) as fg_percentage,
                SAFE_DIVIDE(t.three_pt_made, t.three_pt_attempted) as three_pt_percentage,
                SAFE_DIVIDE(t.ft_made, t.ft_attempted) as ft_percentage,
                CAST(NULL AS STRING) as minutes,
                CAST(NULL AS INT64) as plus_minus
            FROM team_totals t
            LEFT JOIN game_context g ON t.game_id = g.game_id
        ),

        with_opponent AS (
            SELECT
                t1.game_id, t1.nba_game_id, t1.game_date, t1.season_year,
                t1.team_abbr, t1.team_name, t1.is_home,
                t2.team_abbr as opponent_team_abbr,
                t2.points as opponent_points,
                t1.points, t1.fg_made, t1.fg_attempted, t1.fg_percentage,
                t1.three_pt_made, t1.three_pt_attempted, t1.three_pt_percentage,
                t1.ft_made, t1.ft_attempted, t1.ft_percentage,
                t1.offensive_rebounds, t1.defensive_rebounds, t1.total_rebounds,
                t1.assists, t1.steals, t1.blocks, t1.turnovers, t1.personal_fouls,
                t1.plus_minus, t1.minutes,
                t1.processed_at as source_last_updated
            FROM team_with_context t1
            JOIN team_with_context t2
                ON t1.game_id = t2.game_id AND t1.team_abbr != t2.team_abbr
        )

        SELECT * FROM with_opponent
        ORDER BY game_date DESC, game_id, team_abbr
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            logger.info(f"Reconstructed {len(df)} team offense records from player boxscores")
            return df
        except Exception as e:
            logger.error(f"Failed to reconstruct team stats: {e}")
            return pd.DataFrame()

    def _extract_shot_zones(self, start_date: str, end_date: str) -> None:
        """
        Extract shot zone data from play-by-play (optional enhancement).
        
        Gracefully handles missing play-by-play data.
        """
        # Check if play-by-play is available
        if self.source_play_by_play_rows_found is None or self.source_play_by_play_rows_found == 0:
            logger.info("Play-by-play not available, shot zones will be NULL")
            self.shot_zones_available = False
            self.shot_zones_source = None
            return
        
        try:
            query = f"""
            WITH team_shots AS (
                SELECT 
                    game_id,
                    player_1_team_abbr as team_abbr,
                    -- Classify shot zone
                    CASE 
                        WHEN shot_type = '2PT' AND shot_distance <= 8.0 THEN 'paint'
                        WHEN shot_type = '2PT' AND shot_distance > 8.0 THEN 'mid_range'
                        WHEN shot_type = '3PT' THEN 'three'
                        ELSE NULL
                    END as zone,
                    shot_made,
                    CASE 
                        WHEN shot_type = '2PT' THEN 2
                        WHEN shot_type = '3PT' THEN 3
                        ELSE 0
                    END as points_value
                FROM `{self.project_id}.nba_raw.nbac_play_by_play`
                WHERE event_type = 'fieldgoal'
                    AND shot_made IS NOT NULL
                    AND game_date BETWEEN '{start_date}' AND '{end_date}'
            )
            SELECT 
                game_id,
                team_abbr,
                -- Paint
                COUNT(CASE WHEN zone = 'paint' THEN 1 END) as paint_attempts,
                COUNT(CASE WHEN zone = 'paint' AND shot_made = TRUE THEN 1 END) as paint_makes,
                SUM(CASE WHEN zone = 'paint' AND shot_made = TRUE THEN points_value ELSE 0 END) as points_in_paint,
                -- Mid-range
                COUNT(CASE WHEN zone = 'mid_range' THEN 1 END) as mid_range_attempts,
                COUNT(CASE WHEN zone = 'mid_range' AND shot_made = TRUE THEN 1 END) as mid_range_makes,
                -- Three (for validation)
                COUNT(CASE WHEN zone = 'three' THEN 1 END) as three_attempts_pbp,
                COUNT(CASE WHEN zone = 'three' AND shot_made = TRUE THEN 1 END) as three_makes_pbp
            FROM team_shots
            GROUP BY game_id, team_abbr
            """
            
            shot_zones_df = self.bq_client.query(query).to_dataframe()
            
            if not shot_zones_df.empty:
                # Convert to dict keyed by (game_id, team_abbr)
                for _, row in shot_zones_df.iterrows():
                    key = (row['game_id'], row['team_abbr'])
                    self.shot_zone_data[key] = {
                        'paint_attempts': safe_int(row['paint_attempts']),
                        'paint_makes': safe_int(row['paint_makes']),
                        'mid_range_attempts': safe_int(row['mid_range_attempts']),
                        'mid_range_makes': safe_int(row['mid_range_makes']),
                        'points_in_paint': safe_int(row['points_in_paint']),
                        'three_attempts_pbp': safe_int(row['three_attempts_pbp']),
                        'three_makes_pbp': safe_int(row['three_makes_pbp']),
                    }
                
                self.shot_zones_available = True
                self.shot_zones_source = 'nbac_pbp'
                logger.info(f"Extracted shot zones for {len(self.shot_zone_data)} team-games from play-by-play")
            else:
                logger.warning("Play-by-play query returned no shot zones")
                self.shot_zones_available = False
                self.shot_zones_source = None
                
        except Exception as e:
            logger.warning(f"Failed to extract shot zones (non-critical): {e}")
            self.shot_zones_available = False
            self.shot_zones_source = None
    
    # =========================================================================
    # Data Validation
    # =========================================================================
    
    def validate_extracted_data(self) -> None:
        """Enhanced validation for team offensive data."""
        # Check for graceful empty handling FIRST (before calling super)
        # Base class raises ValueError("No data extracted") which prevents
        # graceful handling, so we must check _fallback_handled before super()
        if self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            if hasattr(self, '_fallback_handled') and self._fallback_handled:
                logger.info("Validation passed: fallback already handled empty data gracefully")
                return

            # Log warning instead of raising - let transform handle gracefully
            error_msg = "No team offensive data extracted for date range"
            logger.warning(error_msg)
            notify_warning(
                title="Team Offense: No Data Available",
                message=error_msg,
                details={
                    'processor': 'team_offense_game_summary',
                    'start_date': self.opts['start_date'],
                    'end_date': self.opts['end_date'],
                    'handling': 'graceful_skip'
                },
                processor_name=self.__class__.__name__
            )
            # Mark as handled - transform will check this
            self._no_data_available = True
            return

        # Have data - call parent for standard validation
        super().validate_extracted_data()

        # Validate points calculation
        for _, row in self.raw_data.iterrows():
            fg_made = safe_int(row['fg_made'], default=0)
            three_pt_made = safe_int(row['three_pt_made'], default=0)
            ft_made = safe_int(row['ft_made'], default=0)
            points = safe_int(row['points'], default=0)

            two_pt_makes = fg_made - three_pt_made
            calculated_points = (two_pt_makes * 2) + (three_pt_made * 3) + ft_made

            if calculated_points != points:
                self.log_quality_issue(
                    issue_type='points_calculation_mismatch',
                    severity='high',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details={
                        'reported_points': points,
                        'calculated_points': calculated_points,
                        'difference': points - calculated_points
                    }
                )
        
        # Check for unrealistic team scores
        unrealistic_scores = self.raw_data[
            (self.raw_data['points'].notna()) & 
            ((self.raw_data['points'] < 50) | (self.raw_data['points'] > 200))
        ]
        
        if not unrealistic_scores.empty:
            for _, row in unrealistic_scores.iterrows():
                self.log_quality_issue(
                    issue_type='unrealistic_team_score',
                    severity='high',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details={
                        'points_scored': int(row['points'])
                    }
                )
    
    # =========================================================================
    # Analytics Calculation
    # =========================================================================
    
    def calculate_analytics(self) -> None:
        """Transform team aggregates to final analytics format."""
        records = []
        processing_errors = []

        # Get quality from fallback result (stored during extract_raw_data)
        fallback_tier = getattr(self, '_fallback_quality_tier', 'bronze')
        fallback_score = getattr(self, '_fallback_quality_score', 50.0)
        fallback_issues = getattr(self, '_fallback_quality_issues', [])
        source_used = getattr(self, '_source_used', None)

        # Deduplicate records by (game_date, team_abbr) to handle potential duplicate loads
        # Both _reconstruct_team_from_players() and _extract_from_nbac_team_boxscore()
        # use standardized AWAY_HOME format (raw tables write YYYYMMDD_AWAY_HOME).
        # Duplicates may occur from bulk load operations or multiple source queries.
        # Keep the record with more fg_attempted (indicates more complete data)
        if not self.raw_data.empty and 'game_date' in self.raw_data.columns and 'team_abbr' in self.raw_data.columns:
            original_count = len(self.raw_data)
            self.raw_data = self.raw_data.sort_values('fg_attempted', ascending=False)
            self.raw_data = self.raw_data.drop_duplicates(subset=['game_date', 'team_abbr'], keep='first')
            deduped_count = len(self.raw_data)
            if original_count != deduped_count:
                logger.warning(
                    f"⚠️ Deduplicated {original_count - deduped_count} duplicate team-game records "
                    f"(kept records with highest fg_attempted). {deduped_count} records remaining."
                )

        for _, row in self.raw_data.iterrows():
            try:
                # Parse overtime periods
                overtime_periods = self._parse_overtime_periods(row['minutes'])
                
                # Calculate possessions
                possessions = self._calculate_possessions(
                    row['fg_attempted'],
                    row['ft_attempted'],
                    row['turnovers'],
                    row['offensive_rebounds']
                )
                
                # minutes field is cumulative player-minutes (5 players × game time)
                # Convert to actual game minutes by dividing by 5
                minutes_str = row['minutes'] if pd.notna(row['minutes']) else ''
                total_player_minutes = safe_int(minutes_str.split(':')[0] if ':' in minutes_str else '', default=240)
                actual_game_minutes = total_player_minutes / 5  # Convert to real game time
                offensive_rating = (row['points'] / possessions) * 100 if possessions and possessions > 0 else None
                pace = possessions * (48 / actual_game_minutes) if possessions and actual_game_minutes > 0 else None
                ts_pct = self._calculate_true_shooting_pct(
                    row['points'],
                    row['fg_attempted'],
                    row['ft_attempted']
                )
                
                # Determine win/loss (handle None/empty values)
                points = safe_int(row['points'])
                opponent_points = safe_int(row['opponent_points'])
                win_flag = (points or 0) > (opponent_points or 0)
                margin_of_victory = (points - opponent_points) if (points is not None and opponent_points is not None) else None
                
                # Get shot zones (if available)
                shot_zone_key = (row['game_id'], row['team_abbr'])
                shot_zones = self.shot_zone_data.get(shot_zone_key, {})

                # Build quality columns using centralized helper
                row_issues = list(fallback_issues)
                if not shot_zones:
                    row_issues.append('shot_zones_unavailable')

                quality_columns = build_quality_columns_with_legacy(
                    tier=fallback_tier,
                    score=fallback_score,
                    issues=row_issues,
                    sources=[source_used] if source_used else [],
                )

                # Build record with all fields
                record = {
                    # Core identifiers
                    'game_id': row['game_id'],
                    'nba_game_id': row['nba_game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'team_abbr': row['team_abbr'],
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': safe_int(row['season_year']),

                    # Basic offensive stats
                    'points_scored': safe_int(row['points']),
                    'fg_attempts': safe_int(row['fg_attempted']),
                    'fg_makes': safe_int(row['fg_made']),
                    'three_pt_attempts': safe_int(row['three_pt_attempted']),
                    'three_pt_makes': safe_int(row['three_pt_made']),
                    'ft_attempts': safe_int(row['ft_attempted']),
                    'ft_makes': safe_int(row['ft_made']),
                    'rebounds': safe_int(row['total_rebounds']),
                    'assists': safe_int(row['assists']),
                    'turnovers': safe_int(row['turnovers']),
                    'personal_fouls': safe_int(row['personal_fouls']),
                    
                    # Shot zones (from play-by-play if available)
                    'team_paint_attempts': shot_zones.get('paint_attempts'),
                    'team_paint_makes': shot_zones.get('paint_makes'),
                    'team_mid_range_attempts': shot_zones.get('mid_range_attempts'),
                    'team_mid_range_makes': shot_zones.get('mid_range_makes'),
                    'points_in_paint_scored': shot_zones.get('points_in_paint'),
                    'second_chance_points_scored': None,  # TODO: Complex calculation, defer
                    
                    # Advanced offensive metrics
                    'offensive_rating': round(offensive_rating, 2) if offensive_rating else None,
                    'pace': round(pace, 1) if pace else None,
                    'possessions': int(possessions) if possessions else None,
                    'ts_pct': round(ts_pct, 3) if ts_pct else None,
                    
                    # Game context
                    'home_game': bool(row['is_home']) if pd.notna(row['is_home']) else False,
                    'win_flag': bool(win_flag),
                    'margin_of_victory': int(margin_of_victory) if pd.notna(margin_of_victory) else None,
                    'overtime_periods': int(overtime_periods),
                    
                    # Team situation context (placeholders)
                    'players_inactive': None,
                    'starters_inactive': None,
                    
                    # Referee integration (placeholder)
                    'referee_crew_id': None,
                    
                    # Source tracking (one-liner using base class method!)
                    **self.build_source_tracking_fields(),

                    # Standard quality columns (from centralized helper)
                    **quality_columns,

                    # Additional source tracking
                    'shot_zones_available': self.shot_zones_available,
                    'shot_zones_source': self.shot_zones_source,
                    'primary_source_used': source_used or 'nbac_team_boxscore',
                    'processed_with_issues': len(row_issues) > len(fallback_issues),

                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                # Calculate data hash AFTER all analytics fields are populated
                record['data_hash'] = self._calculate_data_hash(record)

                records.append(record)
                
            except Exception as e:
                error_info = {
                    'game_id': row['game_id'],
                    'team': row['team_abbr'],
                    'error': str(e),
                    'error_type': type(e).__name__
                }
                processing_errors.append(error_info)

                logger.error(f"Error processing team record {row['game_id']}_{row['team_abbr']}: {e}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details=error_info
                )

                # Record failure for unified failure tracking
                self.record_failure(
                    entity_id=row['team_abbr'],
                    entity_type='TEAM',
                    category='PROCESSING_ERROR',
                    reason=f"Error processing team record: {str(e)[:200]}",
                    can_retry=True,
                    missing_game_ids=[row['game_id']] if row.get('game_id') else None
                )
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated team offensive analytics for {len(records)} team-game records")
        
        # Notify if high error rate
        if len(processing_errors) > 0:
            error_rate = len(processing_errors) / len(self.raw_data) * 100
            
            if error_rate > 5:
                notify_warning(
                    title="Team Offense: High Processing Error Rate",
                    message=f"Failed to process {len(processing_errors)} records ({error_rate:.1f}% error rate)",
                    details={
                        'processor': 'team_offense_game_summary',
                        'total_input_records': len(self.raw_data),
                        'processing_errors': len(processing_errors),
                        'error_rate_pct': round(error_rate, 2),
                        'successful_records': len(records),
                        'sample_errors': processing_errors[:5]
                    },
                    processor_name=self.__class__.__name__
                )
    
    def _process_teams_parallel(
        self,
        fallback_tier: str,
        fallback_score: float,
        fallback_issues: List,
        source_used: str
    ) -> tuple:
        """Process all team offensive records using ThreadPoolExecutor."""
        # Determine worker count
        DEFAULT_WORKERS = 4
        max_workers = int(os.environ.get(
            'TOGS_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        logger.info(f"Processing {len(self.raw_data)} team-game records with {max_workers} workers (parallel mode)")

        # Performance timing
        loop_start = time.time()
        processed_count = 0

        # Thread-safe result collection
        records = []
        processing_errors = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all team tasks
            futures = {
                executor.submit(
                    self._process_single_team_offense,
                    row,
                    fallback_tier,
                    fallback_score,
                    fallback_issues,
                    source_used
                ): idx
                for idx, row in self.raw_data.iterrows()
            }

            # Collect results as they complete
            for future in as_completed(futures):
                idx = futures[future]
                processed_count += 1

                try:
                    success, data = future.result()
                    if success:
                        records.append(data)
                    else:
                        processing_errors.append(data)

                except Exception as e:
                    processing_errors.append({
                        'index': idx,
                        'error': str(e),
                        'error_type': type(e).__name__
                    })
                    logger.error(f"Exception processing team offense record: {e}")

                # Progress logging every 10 records
                if processed_count % 10 == 0 or processed_count == len(self.raw_data):
                    elapsed = time.time() - loop_start
                    rate = processed_count / elapsed if elapsed > 0 else 0
                    eta = (len(self.raw_data) - processed_count) / rate if rate > 0 else 0
                    logger.info(
                        f"Progress: {processed_count}/{len(self.raw_data)} records | "
                        f"Rate: {rate:.1f} records/sec | "
                        f"ETA: {eta:.1f}s | "
                        f"Success: {len(records)} | "
                        f"Errors: {len(processing_errors)}"
                    )

        elapsed_total = time.time() - loop_start
        rate_final = len(self.raw_data) / elapsed_total if elapsed_total > 0 else 0
        logger.info(
            f"Parallel processing complete: {len(self.raw_data)} records in {elapsed_total:.1f}s "
            f"({rate_final:.1f} records/sec, {max_workers} workers)"
        )

        return records, processing_errors

    def _process_single_team_offense(
        self,
        row: pd.Series,
        fallback_tier: str,
        fallback_score: float,
        fallback_issues: List,
        source_used: str
    ) -> tuple:
        """
        Process a single team offensive record.

        Returns:
            (True, record_dict) on success
            (False, error_dict) on failure
        """
        try:
            # Parse overtime periods
            overtime_periods = self._parse_overtime_periods(row['minutes'])

            # Calculate possessions
            possessions = self._calculate_possessions(
                row['fg_attempted'],
                row['ft_attempted'],
                row['turnovers'],
                row['offensive_rebounds']
            )

            # minutes field is cumulative player-minutes (5 players × game time)
            # Convert to actual game minutes by dividing by 5
            minutes_str = row['minutes'] if pd.notna(row['minutes']) else ''
            total_player_minutes = safe_int(minutes_str.split(':')[0] if ':' in minutes_str else '', default=240)
            actual_game_minutes = total_player_minutes / 5  # Convert to real game time
            offensive_rating = (row['points'] / possessions) * 100 if possessions and possessions > 0 else None
            pace = possessions * (48 / actual_game_minutes) if possessions and actual_game_minutes > 0 else None
            ts_pct = self._calculate_true_shooting_pct(
                row['points'],
                row['fg_attempted'],
                row['ft_attempted']
            )

            # Determine win/loss (handle None/empty values)
            points = safe_int(row['points'])
            opponent_points = safe_int(row['opponent_points'])
            win_flag = (points or 0) > (opponent_points or 0)
            margin_of_victory = (points - opponent_points) if (points is not None and opponent_points is not None) else None

            # Get shot zones (if available)
            shot_zone_key = (row['game_id'], row['team_abbr'])
            shot_zones = self.shot_zone_data.get(shot_zone_key, {})

            # Build quality columns using centralized helper
            row_issues = list(fallback_issues)
            if not shot_zones:
                row_issues.append('shot_zones_unavailable')

            quality_columns = build_quality_columns_with_legacy(
                tier=fallback_tier,
                score=fallback_score,
                issues=row_issues,
                sources=[source_used] if source_used else [],
            )

            # Build record with all fields
            record = {
                # Core identifiers
                'game_id': row['game_id'],
                'nba_game_id': row['nba_game_id'],
                'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                'team_abbr': row['team_abbr'],
                'opponent_team_abbr': row['opponent_team_abbr'],
                'season_year': safe_int(row['season_year']),

                # Basic offensive stats
                'points_scored': safe_int(row['points']),
                'fg_attempts': safe_int(row['fg_attempted']),
                'fg_makes': safe_int(row['fg_made']),
                'three_pt_attempts': safe_int(row['three_pt_attempted']),
                'three_pt_makes': safe_int(row['three_pt_made']),
                'ft_attempts': safe_int(row['ft_attempted']),
                'ft_makes': safe_int(row['ft_made']),
                'rebounds': safe_int(row['total_rebounds']),
                'assists': safe_int(row['assists']),
                'turnovers': safe_int(row['turnovers']),
                'personal_fouls': safe_int(row['personal_fouls']),

                # Shot zones (from play-by-play if available)
                'team_paint_attempts': shot_zones.get('paint_attempts'),
                'team_paint_makes': shot_zones.get('paint_makes'),
                'team_mid_range_attempts': shot_zones.get('mid_range_attempts'),
                'team_mid_range_makes': shot_zones.get('mid_range_makes'),
                'points_in_paint_scored': shot_zones.get('points_in_paint'),
                'second_chance_points_scored': None,  # TODO: Complex calculation, defer

                # Advanced offensive metrics
                'offensive_rating': round(offensive_rating, 2) if offensive_rating else None,
                'pace': round(pace, 1) if pace else None,
                'possessions': int(possessions) if possessions else None,
                'ts_pct': round(ts_pct, 3) if ts_pct else None,

                # Game context
                'home_game': bool(row['is_home']) if pd.notna(row['is_home']) else False,
                'win_flag': bool(win_flag),
                'margin_of_victory': int(margin_of_victory) if pd.notna(margin_of_victory) else None,
                'overtime_periods': int(overtime_periods),

                # Team situation context (placeholders)
                'players_inactive': None,
                'starters_inactive': None,

                # Referee integration (placeholder)
                'referee_crew_id': None,

                # Source tracking (one-liner using base class method!)
                **self.build_source_tracking_fields(),

                # Standard quality columns (from centralized helper)
                **quality_columns,

                # Additional source tracking
                'shot_zones_available': self.shot_zones_available,
                'shot_zones_source': self.shot_zones_source,
                'primary_source_used': source_used or 'nbac_team_boxscore',
                'processed_with_issues': len(row_issues) > len(fallback_issues),

                # Processing metadata
                'created_at': datetime.now(timezone.utc).isoformat(),
                'processed_at': datetime.now(timezone.utc).isoformat()
            }

            # Calculate data hash AFTER all analytics fields are populated
            record['data_hash'] = self._calculate_data_hash(record)

            return (True, record)

        except Exception as e:
            return (False, {
                'game_id': row.get('game_id'),
                'team': row.get('team_abbr'),
                'error': str(e),
                'error_type': type(e).__name__
            })

    def _process_teams_serial(
        self,
        fallback_tier: str,
        fallback_score: float,
        fallback_issues: List,
        source_used: str
    ) -> tuple:
        """Process all team offensive records in serial mode (original logic)."""
        logger.info(f"Processing {len(self.raw_data)} team-game records in serial mode")

        records = []
        processing_errors = []

        for _, row in self.raw_data.iterrows():
            success, data = self._process_single_team_offense(
                row, fallback_tier, fallback_score, fallback_issues, source_used
            )

            if success:
                records.append(data)
            else:
                processing_errors.append(data)
                logger.error(f"Error processing record {data.get('game_id')}_{data.get('team')}: {data.get('error')}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{data.get('game_id')}_{data.get('team')}",
                    details=data
                )

        return records, processing_errors

    # =========================================================================
    # Helper Calculation Methods
    # =========================================================================

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

    def _parse_overtime_periods(self, minutes_str: str) -> int:
        """
        Parse overtime periods from minutes string.

        Examples:
          "240:00" = 0 OT (regulation)
          "265:00" = 1 OT (240 + 25)
          "290:00" = 2 OT (240 + 50)
        """
        if not minutes_str or minutes_str == '':
            return 0

        try:
            # Parse total minutes (before colon)
            if ':' not in minutes_str:
                return 0

            minutes_part = minutes_str.split(':')[0]
            total_minutes = safe_int(minutes_part, default=240)

            if total_minutes <= 240:
                return 0

            # Calculate OT periods
            overtime_minutes = total_minutes - 240
            return overtime_minutes // 25

        except Exception as e:
            logger.warning(f"Failed to parse OT periods from '{minutes_str}': {e}")
            return 0
    
    def _calculate_possessions(self, fg_attempts: int, ft_attempts: int,
                               turnovers: int, offensive_rebounds: int) -> float:
        """
        Calculate estimated possessions.
        
        Formula: FGA + 0.44×FTA + TO - OREB
        """
        try:
            possessions = (
                fg_attempts + 
                (0.44 * ft_attempts) + 
                turnovers - 
                offensive_rebounds
            )
            return round(possessions, 1)
        except (TypeError, ValueError, ZeroDivisionError) as e:
            logger.debug(f"Failed to calculate possessions: {e}")
            return None
    
    def _calculate_true_shooting_pct(self, points: int, fg_attempts: int,
                                    ft_attempts: int) -> float:
        """
        Calculate true shooting percentage.
        
        Formula: PTS / (2 × (FGA + 0.44×FTA))
        """
        try:
            total_shooting_possessions = 2 * (fg_attempts + 0.44 * ft_attempts)
            
            if total_shooting_possessions <= 0:
                return None

            ts_pct = points / total_shooting_possessions
            return round(ts_pct, 3)
        except (TypeError, ValueError, ZeroDivisionError) as e:
            logger.debug(f"Failed to calculate true shooting percentage: {e}")
            return None
    
    def _calculate_quality_tier(self, shot_zones: dict) -> str:
        """
        Determine data quality tier based on source availability.
        
        HIGH: Team boxscore complete (100%) + shot zones
        MEDIUM: Team boxscore complete (100%) only
        LOW: Incomplete data or missing source
        """
        # Check if boxscore source is missing (None) OR incomplete (< 100)
        if self.source_nbac_boxscore_completeness_pct is None or self.source_nbac_boxscore_completeness_pct < 100:
            return 'low'
        
        # Boxscore is complete (100%), check if shot zones available
        if shot_zones:
            return 'high'
        else:
            return 'medium'
    
    # =========================================================================
    # Stats & Monitoring
    # =========================================================================
    
    def get_analytics_stats(self) -> Dict:
        """Return team offensive analytics stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'records_processed': len(self.transformed_data),
            'shot_zones_available': self.shot_zones_available,
            'shot_zones_source': self.shot_zones_source,
            'avg_team_points': round(sum(r['points_scored'] for r in self.transformed_data if r['points_scored']) / 
                                   len([r for r in self.transformed_data if r['points_scored']]), 1) if any(r['points_scored'] for r in self.transformed_data) else 0,
            'total_assists': sum(r['assists'] for r in self.transformed_data if r['assists']),
            'total_turnovers': sum(r['turnovers'] for r in self.transformed_data if r['turnovers']),
            'home_games': sum(1 for r in self.transformed_data if r['home_game']),
            'road_games': sum(1 for r in self.transformed_data if not r['home_game']),
            'gold_quality_records': sum(1 for r in self.transformed_data if r.get('quality_tier') == 'gold'),
            'silver_quality_records': sum(1 for r in self.transformed_data if r.get('quality_tier') == 'silver'),
            'bronze_quality_records': sum(1 for r in self.transformed_data if r.get('quality_tier') == 'bronze'),
            'production_ready_records': sum(1 for r in self.transformed_data if r.get('is_production_ready', False)),
            'source_completeness': {
                'nbac_boxscore': self.source_nbac_boxscore_completeness_pct,
                'play_by_play': self.source_play_by_play_completeness_pct
            }
        }
        
        return stats
    
    def post_process(self) -> None:
        """Post-processing - send success notification with stats."""
        super().post_process()
        
        # Send success notification
        analytics_stats = self.get_analytics_stats()
        
        try:
            notify_info(
                title="Team Offense: Processing Complete",
                message=f"Successfully processed {analytics_stats.get('records_processed', 0)} team offensive records",
                details={
                    'processor': 'team_offense_game_summary',
                    'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                    'records_processed': analytics_stats.get('records_processed', 0),
                    'avg_team_points': analytics_stats.get('avg_team_points', 0),
                    'offensive_stats': {
                        'total_assists': analytics_stats.get('total_assists', 0),
                        'total_turnovers': analytics_stats.get('total_turnovers', 0)
                    },
                    'game_splits': {
                        'home_games': analytics_stats.get('home_games', 0),
                        'road_games': analytics_stats.get('road_games', 0)
                    },
                    'shot_zones': {
                        'available': analytics_stats.get('shot_zones_available', False),
                        'source': analytics_stats.get('shot_zones_source')
                    },
                    'data_quality': {
                        'gold_quality_records': analytics_stats.get('gold_quality_records', 0),
                        'silver_quality_records': analytics_stats.get('silver_quality_records', 0),
                        'bronze_quality_records': analytics_stats.get('bronze_quality_records', 0),
                        'production_ready_records': analytics_stats.get('production_ready_records', 0),
                        'source_completeness': analytics_stats.get('source_completeness', {})
                    }
                },
                processor_name=self.__class__.__name__
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send success notification: {notify_ex}")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Process team offense game summary analytics")
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 4 (for backfills)'
    )
    parser.add_argument(
        '--backfill-mode',
        action='store_true',
        help='Enable backfill mode: bypass stale data checks and suppress alerts'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        processor = TeamOffenseGameSummaryProcessor()

        # Call run() with options dict
        success = processor.run({
            'start_date': args.start_date,
            'end_date': args.end_date,
            'skip_downstream_trigger': args.skip_downstream_trigger,
            'backfill_mode': args.backfill_mode
        })

        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)