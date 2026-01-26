#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/loaders/player_loaders.py

Player Data Loader - Extracted from upcoming_player_game_context_processor.py

This module contains player extraction methods that were moved out of the main
processor to reduce file size and improve maintainability.

Methods extracted:
- _extract_players_with_props() (coordinator method)
- _extract_players_daily_mode() (~191 lines)
- _extract_players_backfill_mode() (~123 lines)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded

logger = logging.getLogger(__name__)


class PlayerDataLoader:
    """
    Handles extraction of player data for upcoming game context processing.

    This class contains methods for extracting player lists from various sources
    (gamebook for backfill, roster/schedule for daily predictions).
    """

    def __init__(self, bq_client, project_id, target_date):
        """
        Initialize the player data loader.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            target_date: Date to process (date object)
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.target_date = target_date

        # Data holders (populated by extraction methods)
        self.players_to_process = []
        self.source_tracking = {
            'props': {'last_updated': None, 'rows_found': 0, 'completeness_pct': None}
        }
        self._props_source = None  # Track which source was used

    def _extract_players_with_props(self, processing_mode: str) -> None:
        """
        Extract ALL players who have games scheduled for target date.

        This is the DRIVER query - determines which players to process.

        ISSUE 1 FIX (v3.3):
        - Detects processing mode (daily vs backfill)
        - DAILY mode: Uses schedule + roster (pre-game data)
        - BACKFILL mode: Uses gamebook (post-game actual players)

        This fixes the critical issue where daily predictions couldn't work
        because gamebook data doesn't exist until AFTER games finish.

        Args:
            processing_mode: Either 'daily' or 'backfill'
        """
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
                ON g.game_id = s.game_id  -- FIXED: Join on generated game_id (YYYYMMDD_AWAY_HOME format)
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
