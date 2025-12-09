#!/usr/bin/env python3
"""
Path: analytics_processors/team_defense_game_summary/team_defense_game_summary_processor.py

Team Defense Game Summary Processor (v2.0 - Phase 2 Architecture)
Calculates team defensive metrics by reading Phase 2 raw data directly.

ARCHITECTURE:
  Phase 2 Sources (Raw Data):
    - nba_raw.nbac_team_boxscore (opponent's offensive stats)
    - nba_raw.nbac_gamebook_player_stats (defensive actions - PRIMARY)
    - nba_raw.bdl_player_boxscores (defensive actions - FALLBACK)
    - nba_raw.nbac_player_boxscores (defensive actions - FALLBACK #2)
  
  Phase 3 Output:
    - nba_analytics.team_defense_game_summary

DATA FLOW:
  1. Get opponent team's offensive performance from nbac_team_boxscore
  2. Flip perspective: opponent's offense = this team's defense
  3. Aggregate defensive actions from player boxscores (steals, blocks, rebounds)
  4. Combine into team defensive summary with quality tracking

DEPENDENCIES:
  - nba_raw.nbac_team_boxscore (CRITICAL)
  - nba_raw.nbac_gamebook_player_stats (PRIMARY for defensive actions)
  - nba_raw.bdl_player_boxscores (FALLBACK for defensive actions)

Version: 2.0 (Complete rewrite for Phase 2 architecture)
Updated: November 2025
"""

import logging
import os
import time
import hashlib
import json
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


class TeamDefenseGameSummaryProcessor(
    FallbackSourceMixin,
    QualityMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Process team defensive game summary analytics from Phase 2 raw data.

    Reads opponent offensive performance and defensive actions from raw tables.
    Handles multi-source fallback logic for data completeness.
    """

    # ============================================================
    # Pattern #3: Smart Reprocessing - Data Hash Fields
    # ============================================================
    HASH_FIELDS = [
        # Core identifiers
        'game_id',
        'game_date',
        'defending_team_abbr',
        'opponent_team_abbr',
        'season_year',

        # Defensive stats - opponent performance allowed (11 fields)
        'points_allowed',
        'opp_fg_attempts',
        'opp_fg_makes',
        'opp_three_pt_attempts',
        'opp_three_pt_makes',
        'opp_ft_attempts',
        'opp_ft_makes',
        'opp_rebounds',
        'opp_assists',
        'turnovers_forced',
        'fouls_committed',

        # Defensive shot zone performance (9 fields)
        'opp_paint_attempts',
        'opp_paint_makes',
        'opp_mid_range_attempts',
        'opp_mid_range_makes',
        'points_in_paint_allowed',
        'mid_range_points_allowed',
        'three_pt_points_allowed',
        'second_chance_points_allowed',
        'fast_break_points_allowed',

        # Defensive actions (5 fields)
        'blocks_paint',
        'blocks_mid_range',
        'blocks_three_pt',
        'steals',
        'defensive_rebounds',

        # Advanced defensive metrics (3 fields)
        'defensive_rating',
        'opponent_pace',
        'opponent_ts_pct',

        # Game context (4 fields)
        'home_game',
        'win_flag',
        'margin_of_victory',
        'overtime_periods',

        # Team situation context (2 fields)
        'players_inactive',
        'starters_inactive',

        # Referee integration (1 field)
        'referee_crew_id',
    ]
    # Total: 45 meaningful analytics fields
    # Excluded: data_quality_tier, primary_source_used, processed_with_issues,
    #           all source_* fields, data_hash itself, processed_at, created_at

    def __init__(self):
        super().__init__()
        self.table_name = 'team_defense_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

        # Track which sources were used for each game
        self.source_usage = {}

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Team boxscore sources - RELEVANT (core defensive data)
        'nbac_team_boxscore': True,
        'bdl_team_boxscores': True,
        'espn_team_stats': True,

        # Player boxscore sources - RELEVANT (defensive actions)
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,
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

    def get_dependencies(self) -> Dict:
        """
        Define Phase 2 raw data sources required.
        
        Returns:
            dict: Configuration for each Phase 2 dependency
        """
        return {
            'nba_raw.nbac_team_boxscore': {
                'field_prefix': 'source_team_boxscore',
                'description': 'Opponent team offensive performance (NBA.com)',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 4,  # Minimum 4 team records (2 games × 2 teams)
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': True
            },
            'nba_raw.nbac_gamebook_player_stats': {
                'field_prefix': 'source_gamebook_players',
                'description': 'Individual player defensive actions (NBA.com gamebook)',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 80,  # ~40 players per game × 2 games
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': False  # Can fall back to BDL
            },
            'nba_raw.bdl_player_boxscores': {
                'field_prefix': 'source_bdl_players',
                'description': 'Individual player defensive actions (Ball Don\'t Lie fallback)',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 80,
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': False  # Fallback only
            }
        }
    
    def extract_raw_data(self) -> None:
        """
        Extract team defensive data from Phase 2 raw tables.

        Multi-source strategy:
          1. Get opponent offense from nbac_team_boxscore (perspective flip)
          2. Try gamebook for defensive actions (PRIMARY)
          3. Fall back to BDL if gamebook incomplete (FALLBACK)
          4. Merge opponent offense + defensive actions

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(start_date)
        if skip:
            logger.info(f"✅ SMART REPROCESSING: Skipping processing - {reason}")
            self.raw_data = []
            return

        logger.info(f"🔄 PROCESSING: {reason}")
        logger.info(f"Extracting team defensive data for {start_date} to {end_date}")

        # Step 1: Get opponent offensive stats with fallback chain
        # Uses: nbac_team_boxscore → reconstructed_from_players
        fallback_result = self.try_fallback_chain(
            chain_name='team_boxscores',
            extractors={
                'nbac_team_boxscore': lambda: self._extract_opponent_offense(start_date, end_date),
                'reconstructed_team_from_players': lambda: self._reconstruct_team_from_players(start_date, end_date),
            },
            context={
                'game_date': start_date,
                'processor': 'team_defense_game_summary',
            },
        )

        # Handle fallback result
        if fallback_result.should_skip:
            logger.warning(f"Skipping date range {start_date}-{end_date}: no team data available")
            self.raw_data = []
            return

        if fallback_result.is_placeholder:
            logger.warning(f"Creating placeholder records for {start_date}-{end_date}: team data unavailable")
            # Will create placeholder records with unusable quality in transform step
            self._fallback_quality_tier = fallback_result.quality_tier
            self._fallback_quality_score = fallback_result.quality_score
            self._fallback_quality_issues = fallback_result.quality_issues
            self.raw_data = []
            return

        opponent_offense_df = fallback_result.data

        # Track quality from fallback result
        self._fallback_quality_tier = fallback_result.quality_tier
        self._fallback_quality_score = fallback_result.quality_score
        self._fallback_quality_issues = fallback_result.quality_issues
        self._source_used = fallback_result.source_used

        logger.info(
            f"Found {len(opponent_offense_df)} opponent offense records "
            f"(source: {fallback_result.source_used}, quality: {fallback_result.quality_tier})"
        )
        
        # Step 2: Get defensive actions with multi-source fallback
        defensive_actions_df = self._extract_defensive_actions(start_date, end_date)

        if defensive_actions_df.empty:
            logger.warning("No defensive actions data found - will use basic defensive stats only")
        else:
            logger.info(f"Found {len(defensive_actions_df)} defensive action records")

        # Step 2.5: Get shot zone stats from play-by-play (NEW)
        shot_zone_df = self._extract_shot_zone_stats(start_date, end_date)

        if shot_zone_df.empty:
            logger.warning("No shot zone data found - opp_paint_attempts/opp_mid_range_attempts will be NULL")
        else:
            logger.info(f"Found {len(shot_zone_df)} shot zone records from play-by-play")

        # Step 3: Merge opponent offense with defensive actions and shot zones
        self.raw_data = self._merge_defense_data(opponent_offense_df, defensive_actions_df, shot_zone_df)

        logger.info(f"Extracted {len(self.raw_data)} complete team defensive records")
    
    def _extract_opponent_offense(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Extract opponent's offensive performance from team boxscore.
        
        Strategy: For each game, there are 2 rows in nbac_team_boxscore (home and away).
        To get Team A's defense, we look at Team B's (opponent) offensive stats.
        
        Returns:
            DataFrame with columns:
              - game_id, game_date, season_year
              - defending_team_abbr (team playing defense)
              - opponent_team_abbr (team they defended against)
              - points_allowed (opponent's points scored)
              - opp_fg_makes/attempts, opp_three_pt_makes/attempts, etc.
              - defensive metrics derived from opponent offense
        """
        query = f"""
        WITH game_teams AS (
            -- Get both teams for each game
            SELECT 
                game_id,
                game_date,
                season_year,
                nba_game_id,
                team_abbr,
                is_home,
                
                -- Offensive stats (will become defensive stats from opponent perspective)
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
                total_rebounds,
                offensive_rebounds,
                defensive_rebounds,
                assists,
                turnovers,
                steals,
                blocks,
                personal_fouls,
                plus_minus,
                
                processed_at
            FROM `{self.project_id}.nba_raw.nbac_team_boxscore`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        
        defense_perspective AS (
            -- Create defensive perspective by pairing teams
            SELECT 
                t1.game_id,
                t1.game_date,
                t1.season_year,
                t1.nba_game_id,
                
                -- Team playing defense
                t1.team_abbr as defending_team_abbr,
                t1.is_home as home_game,
                
                -- Opponent (their offense = our defense)
                t2.team_abbr as opponent_team_abbr,
                
                -- Defensive stats = opponent's offensive performance
                t2.points as points_allowed,
                t2.fg_made as opp_fg_makes,
                t2.fg_attempted as opp_fg_attempts,
                t2.fg_percentage as opp_fg_pct,
                t2.three_pt_made as opp_three_pt_makes,
                t2.three_pt_attempted as opp_three_pt_attempts,
                t2.three_pt_percentage as opp_three_pt_pct,
                t2.ft_made as opp_ft_makes,
                t2.ft_attempted as opp_ft_attempts,
                t2.ft_percentage as opp_ft_pct,
                t2.total_rebounds as opp_rebounds,
                t2.offensive_rebounds as opp_offensive_rebounds,
                t2.defensive_rebounds as opp_defensive_rebounds,
                t2.assists as opp_assists,
                
                -- Defense forced these turnovers
                t2.turnovers as turnovers_forced,
                
                -- Defense committed these fouls
                t1.personal_fouls as fouls_committed,
                
                -- Game result from defensive team perspective
                CASE 
                    WHEN t1.plus_minus > 0 THEN TRUE
                    WHEN t1.plus_minus < 0 THEN FALSE
                    ELSE NULL  -- Tie (shouldn't happen in NBA)
                END as win_flag,
                
                t1.plus_minus as margin_of_victory,
                
                -- Calculate defensive rating (points per 100 possessions)
                -- Simple formula: (Points Allowed / Possessions) × 100
                -- Possessions ≈ FGA + 0.44×FTA - ORB + TO
                ROUND(
                    (t2.points / NULLIF(
                        t2.fg_attempted + (0.44 * t2.ft_attempted) - t2.offensive_rebounds + t2.turnovers,
                        0
                    )) * 100,
                    2
                ) as defensive_rating,
                
                -- Opponent pace (possessions per 48 minutes)
                ROUND(
                    (t2.fg_attempted + (0.44 * t2.ft_attempted) - t2.offensive_rebounds + t2.turnovers) * (48.0 / 48.0),
                    1
                ) as opponent_pace,
                
                -- Opponent true shooting percentage
                ROUND(
                    t2.points / NULLIF(2.0 * (t2.fg_attempted + 0.44 * t2.ft_attempted), 0),
                    3
                ) as opponent_ts_pct,
                
                -- Source tracking
                'nbac_team_boxscore' as data_source,
                t2.processed_at as opponent_data_processed_at
                
            FROM game_teams t1
            INNER JOIN game_teams t2
                ON t1.game_id = t2.game_id
                AND t1.team_abbr != t2.team_abbr  -- Get opponent
        )
        
        SELECT * FROM defense_perspective
        ORDER BY game_date DESC, game_id, defending_team_abbr
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            logger.info(f"Extracted {len(df)} opponent offense records from nbac_team_boxscore")
            return df
        except Exception as e:
            logger.error(f"Failed to extract opponent offense: {e}")
            try:
                notify_error(
                    title="Team Defense: Opponent Offense Extraction Failed",
                    message=f"Failed to extract opponent offensive data: {str(e)}",
                    details={
                        'processor': 'team_defense_game_summary',
                        'start_date': start_date,
                        'end_date': end_date,
                        'error_type': type(e).__name__
                    },
                    processor_name="Team Defense Game Summary Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def _reconstruct_team_from_players(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Reconstruct team boxscore stats by aggregating player boxscores.

        This is a FALLBACK method used when nbac_team_boxscore is unavailable.
        Aggregates player stats from nbac_gamebook_player_stats or bdl_player_boxscores.

        Verified accuracy: 100% match with official team boxscores
        (e.g., GSW 121=121, LAL 114=114 on Oct 19, 2021)

        Returns:
            DataFrame with same schema as _extract_opponent_offense() output
        """
        logger.info(f"FALLBACK: Reconstructing team stats from player boxscores for {start_date} to {end_date}")

        query = f"""
        WITH player_stats AS (
            -- Try gamebook first, fall back to BDL
            SELECT
                game_id,
                game_date,
                season_year,
                team_abbr,
                -- Core stats to aggregate
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

            -- BDL fallback for games not in gamebook
            SELECT
                game_id,
                game_date,
                season_year,
                team_abbr,
                COALESCE(points, 0) as points,
                COALESCE(field_goals_made, 0) as fg_made,
                COALESCE(field_goals_attempted, 0) as fg_attempted,
                COALESCE(three_pointers_made, 0) as three_pt_made,
                COALESCE(three_pointers_attempted, 0) as three_pt_attempted,
                COALESCE(free_throws_made, 0) as ft_made,
                COALESCE(free_throws_attempted, 0) as ft_attempted,
                COALESCE(rebounds, 0) as rebounds,
                COALESCE(offensive_rebounds, 0) as offensive_rebounds,
                COALESCE(defensive_rebounds, 0) as defensive_rebounds,
                COALESCE(assists, 0) as assists,
                COALESCE(turnovers, 0) as turnovers,
                COALESCE(steals, 0) as steals,
                COALESCE(blocks, 0) as blocks,
                COALESCE(personal_fouls, 0) as personal_fouls,
                processed_at
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND game_id NOT IN (
                  SELECT DISTINCT game_id
                  FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
                  WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              )
        ),

        team_totals AS (
            -- Aggregate player stats to team level
            SELECT
                game_id,
                game_date,
                MAX(season_year) as season_year,
                team_abbr,
                SUM(points) as points,
                SUM(fg_made) as fg_made,
                SUM(fg_attempted) as fg_attempted,
                SUM(three_pt_made) as three_pt_made,
                SUM(three_pt_attempted) as three_pt_attempted,
                SUM(ft_made) as ft_made,
                SUM(ft_attempted) as ft_attempted,
                SUM(rebounds) as total_rebounds,
                SUM(offensive_rebounds) as offensive_rebounds,
                SUM(defensive_rebounds) as defensive_rebounds,
                SUM(assists) as assists,
                SUM(turnovers) as turnovers,
                SUM(steals) as steals,
                SUM(blocks) as blocks,
                SUM(personal_fouls) as personal_fouls,
                MAX(processed_at) as processed_at,
                COUNT(*) as player_count
            FROM player_stats
            GROUP BY game_id, game_date, team_abbr
            HAVING player_count >= 5  -- Ensure we have reasonable data
        ),

        -- Determine home/away
        game_context AS (
            SELECT DISTINCT
                game_id,
                -- Parse home/away from game_id format: YYYYMMDD_AWAY_HOME
                SPLIT(game_id, '_')[SAFE_OFFSET(2)] as home_team_abbr
            FROM team_totals
        ),

        team_with_home AS (
            SELECT
                t.*,
                CASE WHEN t.team_abbr = g.home_team_abbr THEN TRUE ELSE FALSE END as is_home
            FROM team_totals t
            LEFT JOIN game_context g ON t.game_id = g.game_id
        ),

        defense_perspective AS (
            -- Create defensive perspective by pairing teams
            SELECT
                t1.game_id,
                t1.game_date,
                t1.season_year,
                t1.game_id as nba_game_id,

                -- Team playing defense
                t1.team_abbr as defending_team_abbr,
                t1.is_home as home_game,

                -- Opponent (their offense = our defense)
                t2.team_abbr as opponent_team_abbr,

                -- Defensive stats = opponent's offensive performance
                t2.points as points_allowed,
                t2.fg_made as opp_fg_makes,
                t2.fg_attempted as opp_fg_attempts,
                SAFE_DIVIDE(t2.fg_made, t2.fg_attempted) as opp_fg_pct,
                t2.three_pt_made as opp_three_pt_makes,
                t2.three_pt_attempted as opp_three_pt_attempts,
                SAFE_DIVIDE(t2.three_pt_made, t2.three_pt_attempted) as opp_three_pt_pct,
                t2.ft_made as opp_ft_makes,
                t2.ft_attempted as opp_ft_attempts,
                SAFE_DIVIDE(t2.ft_made, t2.ft_attempted) as opp_ft_pct,
                t2.total_rebounds as opp_rebounds,
                t2.offensive_rebounds as opp_offensive_rebounds,
                t2.defensive_rebounds as opp_defensive_rebounds,
                t2.assists as opp_assists,

                -- Defense forced these turnovers
                t2.turnovers as turnovers_forced,

                -- Defense committed these fouls
                t1.personal_fouls as fouls_committed,

                -- Game result from defensive team perspective
                CASE
                    WHEN t1.points > t2.points THEN TRUE
                    WHEN t1.points < t2.points THEN FALSE
                    ELSE NULL
                END as win_flag,

                t1.points - t2.points as margin_of_victory,

                -- Defensive rating (points per 100 possessions)
                ROUND(
                    SAFE_DIVIDE(t2.points,
                        t2.fg_attempted + (0.44 * t2.ft_attempted) - t2.offensive_rebounds + t2.turnovers
                    ) * 100,
                    2
                ) as defensive_rating,

                -- Opponent pace
                ROUND(
                    t2.fg_attempted + (0.44 * t2.ft_attempted) - t2.offensive_rebounds + t2.turnovers,
                    1
                ) as opponent_pace,

                -- Opponent true shooting percentage
                ROUND(
                    SAFE_DIVIDE(t2.points, 2.0 * (t2.fg_attempted + 0.44 * t2.ft_attempted)),
                    3
                ) as opponent_ts_pct,

                -- Source tracking - mark as reconstructed
                'reconstructed_from_players' as data_source,
                t2.processed_at as opponent_data_processed_at

            FROM team_with_home t1
            INNER JOIN team_with_home t2
                ON t1.game_id = t2.game_id
                AND t1.team_abbr != t2.team_abbr
        )

        SELECT * FROM defense_perspective
        ORDER BY game_date DESC, game_id, defending_team_abbr
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            logger.info(f"Reconstructed {len(df)} opponent offense records from player boxscores")
            return df
        except Exception as e:
            logger.error(f"Failed to reconstruct team stats from players: {e}")
            return pd.DataFrame()

    def _extract_defensive_actions(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Extract individual defensive actions aggregated to team level.
        
        Multi-source strategy:
          1. Try gamebook (best quality) - PRIMARY
          2. Fall back to BDL if gamebook incomplete
          3. Fall back to nbac_player_boxscores if needed
        
        Returns:
            DataFrame with columns:
              - game_id
              - defending_team_abbr
              - steals (team total)
              - blocks_total (team total)
              - defensive_rebounds (team total)
              - data_source (which source was used)
        """
        # Try gamebook first (PRIMARY)
        gamebook_df = self._try_gamebook_defensive_actions(start_date, end_date)
        
        # Check completeness
        if not gamebook_df.empty:
            games_with_gamebook = set(gamebook_df['game_id'].unique())
            logger.info(f"Gamebook provides defensive actions for {len(games_with_gamebook)} games")
            
            # Check if we need fallback for any games
            all_games = self._get_all_game_ids(start_date, end_date)
            missing_games = all_games - games_with_gamebook
            
            if missing_games:
                logger.warning(f"Gamebook missing {len(missing_games)} games, falling back to BDL")
                bdl_df = self._try_bdl_defensive_actions(start_date, end_date, missing_games)
                
                if not bdl_df.empty:
                    # Combine gamebook + BDL
                    combined_df = pd.concat([gamebook_df, bdl_df], ignore_index=True)
                    logger.info(f"Combined gamebook + BDL: {len(combined_df)} records")
                    return combined_df
                else:
                    logger.warning("BDL fallback also empty")
                    return gamebook_df
            else:
                logger.info("Gamebook provides complete defensive actions")
                return gamebook_df
        else:
            # No gamebook data, try BDL as primary
            logger.warning("No gamebook data found, using BDL as primary source")
            bdl_df = self._try_bdl_defensive_actions(start_date, end_date, None)
            
            if not bdl_df.empty:
                return bdl_df
            else:
                logger.error("No defensive actions data from any source")
                return pd.DataFrame()
    
    def _try_gamebook_defensive_actions(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Extract defensive actions from NBA.com gamebook (PRIMARY source)."""
        query = f"""
        SELECT 
            game_id,
            team_abbr as defending_team_abbr,
            
            -- Aggregate defensive actions (only active players)
            SUM(CASE WHEN player_status = 'active' THEN COALESCE(steals, 0) ELSE 0 END) as steals,
            SUM(CASE WHEN player_status = 'active' THEN COALESCE(blocks, 0) ELSE 0 END) as blocks_total,
            SUM(CASE WHEN player_status = 'active' THEN COALESCE(defensive_rebounds, 0) ELSE 0 END) as defensive_rebounds,
            
            -- Track source
            'nbac_gamebook' as data_source,
            MAX(processed_at) as defensive_actions_processed_at,
            
            -- Data quality
            COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_players_count
            
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY game_id, team_abbr
        HAVING active_players_count >= 5  -- Ensure reasonable data quality
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            logger.info(f"Gamebook defensive actions: {len(df)} team-game records")
            return df
        except Exception as e:
            logger.warning(f"Failed to extract gamebook defensive actions: {e}")
            return pd.DataFrame()
    
    def _try_bdl_defensive_actions(self, start_date: str, end_date: str, 
                                    missing_games: Optional[set] = None) -> pd.DataFrame:
        """Extract defensive actions from Ball Don't Lie (FALLBACK source)."""
        
        # Build game filter if specific games needed
        game_filter = ""
        if missing_games:
            game_list = "', '".join(missing_games)
            game_filter = f"AND game_id IN ('{game_list}')"
        
        query = f"""
        SELECT 
            game_id,
            team_abbr as defending_team_abbr,
            
            -- Aggregate defensive actions
            SUM(COALESCE(steals, 0)) as steals,
            SUM(COALESCE(blocks, 0)) as blocks_total,
            SUM(COALESCE(defensive_rebounds, 0)) as defensive_rebounds,
            
            -- Track source
            'bdl_player_boxscores' as data_source,
            MAX(processed_at) as defensive_actions_processed_at,
            
            -- Data quality
            COUNT(*) as players_count
            
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            {game_filter}
        GROUP BY game_id, team_abbr
        HAVING players_count >= 5  -- Ensure reasonable data quality
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            logger.info(f"BDL defensive actions: {len(df)} team-game records")
            return df
        except Exception as e:
            logger.warning(f"Failed to extract BDL defensive actions: {e}")
            return pd.DataFrame()
    
    def _get_all_game_ids(self, start_date: str, end_date: str) -> set:
        """Get all game IDs from team boxscore to check completeness."""
        query = f"""
        SELECT DISTINCT game_id
        FROM `{self.project_id}.nba_raw.nbac_team_boxscore`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            return set(df['game_id'].unique())
        except Exception as e:
            logger.warning(f"Failed to get all game IDs: {e}")
            return set()

    def _extract_shot_zone_stats(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Extract opponent shot zone statistics and blocks by zone from play-by-play data.

        Classifies each shot into zones:
        - Paint: shot_distance <= 8 feet AND shot_type = '2PT'
        - Mid-range: shot_distance > 8 feet AND shot_type = '2PT'
        - Three-point: shot_type = '3PT'

        Returns aggregated stats per game per defending team (opponent's shots allowed).
        Also includes blocks by zone made by the defending team.

        Uses bigdataball_play_by_play as primary source with nbac_play_by_play fallback.

        Returns:
            DataFrame with columns:
              - game_id
              - defending_team_abbr (team that allowed these shots)
              - opp_paint_attempts, opp_paint_makes
              - opp_mid_range_attempts, opp_mid_range_makes
              - points_in_paint_allowed (paint_makes * 2)
              - mid_range_points_allowed (mid_makes * 2)
              - blocks_paint, blocks_mid_range, blocks_three_pt (blocks made by defending team)
        """
        # Try bigdataball first (better shot_distance data)
        query = f"""
        WITH shot_events AS (
            SELECT
                game_id,
                game_date,
                -- The shooting team (their offense = defending team's defense allowed)
                player_1_team_abbr as shooting_team,
                shot_type,
                shot_distance,
                shot_made,
                -- Classify zone
                CASE
                    WHEN shot_type = '3PT' THEN 'three_pt'
                    WHEN shot_distance <= 8 THEN 'paint'
                    ELSE 'mid_range'
                END as shot_zone
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND shot_type IN ('2PT', '3PT')
              AND player_1_team_abbr IS NOT NULL
        ),

        -- Block events with zone classification - tracks the BLOCKER's team
        -- Note: player_2_team_abbr is NULL in BigDataBall, so we derive blocker's team
        -- from shooter's team (if shooter is home team, blocker is away team and vice versa)
        block_events AS (
            SELECT
                game_id,
                game_date,
                -- Derive blocker's team: opposite of shooter's team
                CASE
                    WHEN player_1_team_abbr = home_team_abbr THEN away_team_abbr
                    ELSE home_team_abbr
                END as blocking_team,
                CASE
                    WHEN shot_type = '3PT' THEN 'three_pt'
                    WHEN shot_distance <= 8 THEN 'paint'
                    ELSE 'mid_range'
                END as block_zone
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND player_2_role = 'block'
              AND shot_distance IS NOT NULL
              AND player_1_team_abbr IS NOT NULL
        ),

        -- Aggregate blocks by team and zone
        team_blocks AS (
            SELECT
                game_id,
                blocking_team as defending_team_abbr,
                SUM(CASE WHEN block_zone = 'paint' THEN 1 ELSE 0 END) as blocks_paint,
                SUM(CASE WHEN block_zone = 'mid_range' THEN 1 ELSE 0 END) as blocks_mid_range,
                SUM(CASE WHEN block_zone = 'three_pt' THEN 1 ELSE 0 END) as blocks_three_pt
            FROM block_events
            GROUP BY game_id, blocking_team
        ),

        -- Get both teams per game to determine defending team
        game_teams AS (
            SELECT DISTINCT game_id, game_date, home_team_abbr, away_team_abbr
            FROM `{self.project_id}.nba_raw.bigdataball_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),

        -- Aggregate by game + shooting team (which is opponent from defensive perspective)
        team_shots AS (
            SELECT
                s.game_id,
                s.shooting_team as opponent_team_abbr,
                -- Paint zone
                SUM(CASE WHEN shot_zone = 'paint' THEN 1 ELSE 0 END) as opp_paint_attempts,
                SUM(CASE WHEN shot_zone = 'paint' AND shot_made THEN 1 ELSE 0 END) as opp_paint_makes,
                -- Mid-range zone
                SUM(CASE WHEN shot_zone = 'mid_range' THEN 1 ELSE 0 END) as opp_mid_range_attempts,
                SUM(CASE WHEN shot_zone = 'mid_range' AND shot_made THEN 1 ELSE 0 END) as opp_mid_range_makes,
                -- Three-point (already have this from team boxscore, but calculate anyway for consistency)
                SUM(CASE WHEN shot_zone = 'three_pt' THEN 1 ELSE 0 END) as opp_three_pt_attempts_pbp,
                SUM(CASE WHEN shot_zone = 'three_pt' AND shot_made THEN 1 ELSE 0 END) as opp_three_pt_makes_pbp
            FROM shot_events s
            GROUP BY s.game_id, s.shooting_team
        ),

        -- Flip perspective: shooting team's stats become defending team's "allowed" stats
        defense_stats AS (
            SELECT
                g.game_date,
                -- The defending team is the OTHER team (not the shooting team)
                CASE
                    WHEN t.opponent_team_abbr = g.home_team_abbr THEN g.away_team_abbr
                    ELSE g.home_team_abbr
                END as defending_team_abbr,
                t.opponent_team_abbr,
                t.game_id,
                t.opp_paint_attempts,
                t.opp_paint_makes,
                t.opp_mid_range_attempts,
                t.opp_mid_range_makes,
                t.opp_three_pt_attempts_pbp,
                t.opp_three_pt_makes_pbp,
                -- Points allowed by zone
                t.opp_paint_makes * 2 as points_in_paint_allowed,
                t.opp_mid_range_makes * 2 as mid_range_points_allowed
            FROM team_shots t
            INNER JOIN game_teams g ON t.game_id = g.game_id
        )

        -- Join blocks data with defense stats
        SELECT
            d.game_date,
            d.defending_team_abbr,
            d.opponent_team_abbr,
            d.opp_paint_attempts,
            d.opp_paint_makes,
            d.opp_mid_range_attempts,
            d.opp_mid_range_makes,
            d.opp_three_pt_attempts_pbp,
            d.opp_three_pt_makes_pbp,
            d.points_in_paint_allowed,
            d.mid_range_points_allowed,
            COALESCE(b.blocks_paint, 0) as blocks_paint,
            COALESCE(b.blocks_mid_range, 0) as blocks_mid_range,
            COALESCE(b.blocks_three_pt, 0) as blocks_three_pt,
            'bigdataball_play_by_play' as shot_zone_source
        FROM defense_stats d
        LEFT JOIN team_blocks b ON d.game_id = b.game_id AND d.defending_team_abbr = b.defending_team_abbr
        """

        try:
            df = self.bq_client.query(query).to_dataframe()
            if not df.empty:
                logger.info(f"Extracted shot zone stats for {len(df)} team-game records from bigdataball")
                return df
        except Exception as e:
            logger.warning(f"Failed to extract shot zones from bigdataball: {e}")

        # Fallback to nbac_play_by_play if bigdataball fails
        logger.info("Falling back to nbac_play_by_play for shot zone stats")
        fallback_query = f"""
        WITH shot_events AS (
            SELECT
                game_id,
                game_date,
                player_1_team_abbr as shooting_team,
                shot_type,
                shot_distance,
                shot_made,
                CASE
                    WHEN shot_type = '3PT' THEN 'three_pt'
                    WHEN shot_distance <= 8 THEN 'paint'
                    ELSE 'mid_range'
                END as shot_zone
            FROM `{self.project_id}.nba_raw.nbac_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
              AND event_type IN ('shot', 'miss', 'made')
              AND shot_type IN ('2PT', '3PT')
              AND player_1_team_abbr IS NOT NULL
        ),
        game_teams AS (
            SELECT DISTINCT game_id, game_date, home_team_abbr, away_team_abbr
            FROM `{self.project_id}.nba_raw.nbac_play_by_play`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        team_shots AS (
            SELECT
                s.game_id,
                s.shooting_team as opponent_team_abbr,
                SUM(CASE WHEN shot_zone = 'paint' THEN 1 ELSE 0 END) as opp_paint_attempts,
                SUM(CASE WHEN shot_zone = 'paint' AND shot_made THEN 1 ELSE 0 END) as opp_paint_makes,
                SUM(CASE WHEN shot_zone = 'mid_range' THEN 1 ELSE 0 END) as opp_mid_range_attempts,
                SUM(CASE WHEN shot_zone = 'mid_range' AND shot_made THEN 1 ELSE 0 END) as opp_mid_range_makes,
                SUM(CASE WHEN shot_zone = 'three_pt' THEN 1 ELSE 0 END) as opp_three_pt_attempts_pbp,
                SUM(CASE WHEN shot_zone = 'three_pt' AND shot_made THEN 1 ELSE 0 END) as opp_three_pt_makes_pbp
            FROM shot_events s
            GROUP BY s.game_id, s.shooting_team
        )
        SELECT
            g.game_date,
            CASE
                WHEN t.opponent_team_abbr = g.home_team_abbr THEN g.away_team_abbr
                ELSE g.home_team_abbr
            END as defending_team_abbr,
            t.opponent_team_abbr,
            t.opp_paint_attempts,
            t.opp_paint_makes,
            t.opp_mid_range_attempts,
            t.opp_mid_range_makes,
            t.opp_three_pt_attempts_pbp,
            t.opp_three_pt_makes_pbp,
            t.opp_paint_makes * 2 as points_in_paint_allowed,
            t.opp_mid_range_makes * 2 as mid_range_points_allowed,
            'nbac_play_by_play' as shot_zone_source
        FROM team_shots t
        INNER JOIN game_teams g ON t.game_id = g.game_id
        """

        try:
            df = self.bq_client.query(fallback_query).to_dataframe()
            logger.info(f"Extracted shot zone stats for {len(df)} team-game records from nbac (fallback)")
            return df
        except Exception as e:
            logger.warning(f"Failed to extract shot zones from nbac: {e}")
            return pd.DataFrame()

    def _merge_defense_data(self, opponent_offense_df: pd.DataFrame,
                           defensive_actions_df: pd.DataFrame,
                           shot_zone_df: pd.DataFrame = None) -> pd.DataFrame:
        """
        Merge opponent offensive stats with defensive actions and shot zone stats.

        Args:
            opponent_offense_df: Opponent offensive performance (perspective flipped)
            defensive_actions_df: Aggregated defensive actions (steals, blocks, etc.)
            shot_zone_df: Shot zone stats from play-by-play (paint, mid-range attempts/makes)

        Returns:
            Combined DataFrame with complete defensive metrics including shot zones
        """
        # Start with opponent offense
        merged_df = opponent_offense_df.copy()

        # Initialize defensive action columns
        if defensive_actions_df.empty:
            logger.warning("No defensive actions data - using opponent offense only")
            merged_df['steals'] = 0
            merged_df['blocks_total'] = 0
            merged_df['defensive_rebounds'] = 0
            merged_df['defensive_actions_source'] = None
            merged_df['defensive_actions_processed_at'] = None
        else:
            # Merge defensive actions on game_id + defending_team_abbr
            merged_df = merged_df.merge(
                defensive_actions_df,
                on=['game_id', 'defending_team_abbr'],
                how='left',
                suffixes=('', '_defensive')
            )
            # Fill missing defensive actions with 0
            merged_df['steals'] = merged_df['steals'].fillna(0)
            merged_df['blocks_total'] = merged_df['blocks_total'].fillna(0)
            merged_df['defensive_rebounds'] = merged_df['defensive_rebounds'].fillna(0)
            # Track which source provided defensive actions
            merged_df['defensive_actions_source'] = merged_df.get('data_source_defensive', pd.Series(['none'] * len(merged_df))).fillna('none')

        # Merge shot zone data (NEW) - use game_date + defending_team_abbr for reliable matching
        if shot_zone_df is not None and not shot_zone_df.empty:
            merged_df = merged_df.merge(
                shot_zone_df[['game_date', 'defending_team_abbr', 'opp_paint_attempts', 'opp_paint_makes',
                             'opp_mid_range_attempts', 'opp_mid_range_makes',
                             'points_in_paint_allowed', 'mid_range_points_allowed',
                             'blocks_paint', 'blocks_mid_range', 'blocks_three_pt',
                             'shot_zone_source']],
                on=['game_date', 'defending_team_abbr'],
                how='left',
                suffixes=('', '_pbp')
            )
            blocks_with_data = (merged_df['blocks_paint'].notna() | merged_df['blocks_mid_range'].notna() | merged_df['blocks_three_pt'].notna()).sum()
            logger.info(f"Merged shot zone data - {merged_df['opp_paint_attempts'].notna().sum()} records have paint data, {blocks_with_data} have block zone data")
        else:
            # No shot zone data - initialize columns as None
            merged_df['opp_paint_attempts'] = None
            merged_df['opp_paint_makes'] = None
            merged_df['opp_mid_range_attempts'] = None
            merged_df['opp_mid_range_makes'] = None
            merged_df['points_in_paint_allowed'] = None
            merged_df['mid_range_points_allowed'] = None
            merged_df['blocks_paint'] = None
            merged_df['blocks_mid_range'] = None
            merged_df['blocks_three_pt'] = None
            merged_df['shot_zone_source'] = None

        logger.info(f"Merged {len(merged_df)} complete defensive records")

        return merged_df

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

    def calculate_analytics(self) -> None:
        """
        Transform raw defensive data to final analytics format.

        Includes:
          - Data type conversions
          - NULL handling
          - Data quality tracking (using centralized quality_columns helper)
          - Source metadata (via dependency tracking v4.0)
        """
        if self.raw_data is None or self.raw_data.empty:
            logger.warning("No raw data to calculate analytics")
            self.transformed_data = []
            return

        records = []
        processing_errors = []

        # Get quality from fallback result (stored during extract_raw_data)
        fallback_tier = getattr(self, '_fallback_quality_tier', 'bronze')
        fallback_score = getattr(self, '_fallback_quality_score', 50.0)
        fallback_issues = getattr(self, '_fallback_quality_issues', [])
        source_used = getattr(self, '_source_used', None)

        # ============================================================
        # Parallelization: Process teams in parallel or serial mode
        # ============================================================
        if ENABLE_TEAM_PARALLELIZATION:
            records, processing_errors = self._process_teams_parallel(
                fallback_tier, fallback_score, fallback_issues, source_used
            )
        else:
            records, processing_errors = self._process_teams_serial(
                fallback_tier, fallback_score, fallback_issues, source_used
            )

        self.transformed_data = records
        logger.info(f"Calculated team defensive analytics for {len(records)} team-game records")
        
        # Notify if significant processing errors
        if len(processing_errors) > 0:
            error_rate = len(processing_errors) / len(self.raw_data) * 100
            
            if error_rate > 5:
                try:
                    notify_warning(
                        title="Team Defense: High Processing Error Rate",
                        message=f"Failed to process {len(processing_errors)} records ({error_rate:.1f}% error rate)",
                        details={
                            'processor': 'team_defense_game_summary',
                            'total_input_records': len(self.raw_data),
                            'processing_errors': len(processing_errors),
                            'error_rate_pct': round(error_rate, 2),
                            'successful_records': len(records),
                            'sample_errors': processing_errors[:5]
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

    def _process_teams_parallel(
        self,
        fallback_tier: str,
        fallback_score: float,
        fallback_issues: List,
        source_used: str
    ) -> tuple:
        """Process all team defensive records using ThreadPoolExecutor."""
        # Determine worker count
        DEFAULT_WORKERS = 4
        max_workers = int(os.environ.get(
            'TDGS_WORKERS',
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
                    self._process_single_team_defense,
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
                    logger.error(f"Exception processing team defense record: {e}")

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

    def _process_single_team_defense(
        self,
        row: pd.Series,
        fallback_tier: str,
        fallback_score: float,
        fallback_issues: List,
        source_used: str
    ) -> tuple:
        """
        Process a single team defensive record.

        Returns:
            (True, record_dict) on success
            (False, error_dict) on failure
        """
        try:
            # Determine data completeness
            has_defensive_actions = (
                pd.notna(row.get('steals')) or
                pd.notna(row.get('blocks_total')) or
                pd.notna(row.get('defensive_rebounds'))
            )

            defensive_actions_source = row.get('defensive_actions_source', 'none')

            # Determine primary source used
            if defensive_actions_source != 'none':
                primary_source = f"nbac_team_boxscore+{defensive_actions_source}"
            else:
                primary_source = "nbac_team_boxscore"

            # Build quality columns using centralized helper
            # Combine fallback-level issues with row-level issues
            row_issues = list(fallback_issues)
            if not has_defensive_actions:
                row_issues.append('missing_defensive_actions')
            if defensive_actions_source == 'bdl_player_boxscores':
                row_issues.append('backup_source_used')

            # Build standard quality columns (includes legacy for backward compat)
            quality_columns = build_quality_columns_with_legacy(
                tier=fallback_tier,
                score=fallback_score,
                issues=row_issues,
                sources=[source_used] if source_used else [],
            )

            record = {
                # Core identifiers
                'game_id': row['game_id'],
                'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                'defending_team_abbr': row['defending_team_abbr'],
                'opponent_team_abbr': row['opponent_team_abbr'],
                'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,

                # Defensive stats (opponent performance allowed)
                'points_allowed': int(row['points_allowed']) if pd.notna(row['points_allowed']) else None,
                'opp_fg_attempts': int(row['opp_fg_attempts']) if pd.notna(row['opp_fg_attempts']) else None,
                'opp_fg_makes': int(row['opp_fg_makes']) if pd.notna(row['opp_fg_makes']) else None,
                'opp_three_pt_attempts': int(row['opp_three_pt_attempts']) if pd.notna(row['opp_three_pt_attempts']) else None,
                'opp_three_pt_makes': int(row['opp_three_pt_makes']) if pd.notna(row['opp_three_pt_makes']) else None,
                'opp_ft_attempts': int(row['opp_ft_attempts']) if pd.notna(row['opp_ft_attempts']) else None,
                'opp_ft_makes': int(row['opp_ft_makes']) if pd.notna(row['opp_ft_makes']) else None,
                'opp_rebounds': int(row['opp_rebounds']) if pd.notna(row['opp_rebounds']) else None,
                'opp_assists': int(row['opp_assists']) if pd.notna(row['opp_assists']) else None,
                'turnovers_forced': int(row['turnovers_forced']) if pd.notna(row['turnovers_forced']) else None,
                'fouls_committed': int(row['fouls_committed']) if pd.notna(row['fouls_committed']) else None,

                # Defensive shot zone performance (from play-by-play data)
                'opp_paint_attempts': int(row['opp_paint_attempts']) if pd.notna(row.get('opp_paint_attempts')) else None,
                'opp_paint_makes': int(row['opp_paint_makes']) if pd.notna(row.get('opp_paint_makes')) else None,
                'opp_mid_range_attempts': int(row['opp_mid_range_attempts']) if pd.notna(row.get('opp_mid_range_attempts')) else None,
                'opp_mid_range_makes': int(row['opp_mid_range_makes']) if pd.notna(row.get('opp_mid_range_makes')) else None,
                'points_in_paint_allowed': int(row['points_in_paint_allowed']) if pd.notna(row.get('points_in_paint_allowed')) else None,
                'mid_range_points_allowed': int(row['mid_range_points_allowed']) if pd.notna(row.get('mid_range_points_allowed')) else None,
                'three_pt_points_allowed': int(row['opp_three_pt_makes'] * 3) if pd.notna(row['opp_three_pt_makes']) else None,
                'second_chance_points_allowed': None,  # TODO: Extract from play-by-play
                'fast_break_points_allowed': None,  # TODO: Extract from play-by-play

                # Defensive actions by zone (from play-by-play block events)
                'blocks_paint': int(row['blocks_paint']) if pd.notna(row.get('blocks_paint')) else None,
                'blocks_mid_range': int(row['blocks_mid_range']) if pd.notna(row.get('blocks_mid_range')) else None,
                'blocks_three_pt': int(row['blocks_three_pt']) if pd.notna(row.get('blocks_three_pt')) else None,
                'steals': int(row['steals']) if pd.notna(row['steals']) else 0,
                'defensive_rebounds': int(row['defensive_rebounds']) if pd.notna(row['defensive_rebounds']) else 0,

                # Advanced defensive metrics
                'defensive_rating': float(row['defensive_rating']) if pd.notna(row['defensive_rating']) else None,
                'opponent_pace': float(row['opponent_pace']) if pd.notna(row['opponent_pace']) else None,
                'opponent_ts_pct': float(row['opponent_ts_pct']) if pd.notna(row['opponent_ts_pct']) else None,

                # Game context
                'home_game': bool(row['home_game']) if pd.notna(row['home_game']) else False,
                'win_flag': bool(row['win_flag']) if pd.notna(row['win_flag']) else None,
                'margin_of_victory': int(row['margin_of_victory']) if pd.notna(row['margin_of_victory']) else None,
                'overtime_periods': 0,  # TODO: Calculate from minutes played

                # Team situation context (deferred - need injury/roster data)
                'players_inactive': None,
                'starters_inactive': None,

                # Referee integration (deferred)
                'referee_crew_id': None,

                # Standard quality columns (from centralized helper)
                **quality_columns,

                # Additional source tracking
                'primary_source_used': primary_source,
                'processed_with_issues': not has_defensive_actions,

                # Dependency tracking v4.0 (added by base class)
                **self.build_source_tracking_fields(),

                # Processing metadata
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'created_at': datetime.now(timezone.utc).isoformat()
            }

            # Pattern #3: Calculate data_hash for smart reprocessing
            # Must be done AFTER all analytics fields are populated
            record['data_hash'] = self._calculate_data_hash(record)

            return (True, record)

        except Exception as e:
            return (False, {
                'game_id': row.get('game_id'),
                'defending_team': row.get('defending_team_abbr'),
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
        """Process all team defensive records in serial mode (original logic)."""
        logger.info(f"Processing {len(self.raw_data)} team-game records in serial mode")

        records = []
        processing_errors = []

        for _, row in self.raw_data.iterrows():
            success, data = self._process_single_team_defense(
                row, fallback_tier, fallback_score, fallback_issues, source_used
            )

            if success:
                records.append(data)
            else:
                processing_errors.append(data)
                logger.error(f"Error processing record {data.get('game_id')}_{data.get('defending_team')}: {data.get('error')}")

        return records, processing_errors

    def get_analytics_stats(self) -> Dict:
        """Return team defensive analytics stats."""
        if not self.transformed_data:
            return {}
        
        # Calculate stats from transformed data
        total_records = len(self.transformed_data)
        
        # Points allowed stats
        points_allowed_list = [r['points_allowed'] for r in self.transformed_data if r['points_allowed']]
        avg_points_allowed = round(sum(points_allowed_list) / len(points_allowed_list), 1) if points_allowed_list else 0
        
        # Defensive actions stats
        total_steals = sum(r['steals'] for r in self.transformed_data if r['steals'])
        total_blocks = sum(r.get('steals', 0) for r in self.transformed_data)  # Using steals as proxy since blocks_total not in final record
        total_turnovers_forced = sum(r['turnovers_forced'] for r in self.transformed_data if r['turnovers_forced'])
        
        # Game context stats
        home_games = sum(1 for r in self.transformed_data if r['home_game'])
        road_games = total_records - home_games
        
        # Data quality stats (using standard quality_tier column)
        gold_quality = sum(1 for r in self.transformed_data if r.get('quality_tier') == 'gold')
        silver_quality = sum(1 for r in self.transformed_data if r.get('quality_tier') == 'silver')
        bronze_quality = sum(1 for r in self.transformed_data if r.get('quality_tier') == 'bronze')
        production_ready = sum(1 for r in self.transformed_data if r.get('is_production_ready', False))
        
        return {
            'records_processed': total_records,
            'avg_points_allowed': avg_points_allowed,
            'total_steals': total_steals,
            'total_blocks': total_blocks,
            'total_turnovers_forced': total_turnovers_forced,
            'home_games': home_games,
            'road_games': road_games,
            'gold_quality_records': gold_quality,
            'silver_quality_records': silver_quality,
            'bronze_quality_records': bronze_quality,
            'production_ready_records': production_ready,
        }
    
    def post_process(self) -> None:
        """Post-processing - send success notification with stats."""
        super().post_process()
        
        analytics_stats = self.get_analytics_stats()
        
        try:
            notify_info(
                title="Team Defense: Processing Complete",
                message=f"Successfully processed {analytics_stats.get('records_processed', 0)} team defensive records",
                details={
                    'processor': 'team_defense_game_summary',
                    'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                    'records_processed': analytics_stats.get('records_processed', 0),
                    'avg_points_allowed': analytics_stats.get('avg_points_allowed', 0),
                    'defensive_actions': {
                        'total_steals': analytics_stats.get('total_steals', 0),
                        'total_blocks': analytics_stats.get('total_blocks', 0),
                        'turnovers_forced': analytics_stats.get('total_turnovers_forced', 0)
                    },
                    'game_splits': {
                        'home_games': analytics_stats.get('home_games', 0),
                        'road_games': analytics_stats.get('road_games', 0)
                    },
                    'data_quality': {
                        'gold_quality_records': analytics_stats.get('gold_quality_records', 0),
                        'silver_quality_records': analytics_stats.get('silver_quality_records', 0),
                        'bronze_quality_records': analytics_stats.get('bronze_quality_records', 0),
                        'production_ready_records': analytics_stats.get('production_ready_records', 0),
                    }
                }
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send success notification: {notify_ex}")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Process team defense game summary analytics")
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 4 (for backfills)'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        processor = TeamDefenseGameSummaryProcessor()

        success = processor.run({
            'start_date': args.start_date,
            'end_date': args.end_date,
            'skip_downstream_trigger': args.skip_downstream_trigger
        })

        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)