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

from ..queries.shared_ctes import (
    games_today_cte,
    teams_playing_cte,
    latest_roster_per_team_cte,
    roster_players_cte,
    roster_players_with_games_cte,
    injuries_cte,
    props_cte,
    schedule_data_cte,
    gamebook_players_with_games_cte,
    daily_mode_final_select,
    backfill_mode_final_select,
)

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
        # Using shared CTEs for consistency with PlayerGameQueryBuilder
        daily_query = f"""
        {games_today_cte(self.project_id)},
        {teams_playing_cte()},
        {latest_roster_per_team_cte(self.project_id)},
        {roster_players_cte(self.project_id)},
        {roster_players_with_games_cte()},
        {injuries_cte(self.project_id)},
        {props_cte(self.project_id)}
        {daily_mode_final_select()}
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
        # Using shared CTEs for consistency with PlayerGameQueryBuilder
        backfill_query = f"""
        {schedule_data_cte(self.project_id)},
        {gamebook_players_with_games_cte(self.project_id)},
        {props_cte(self.project_id)}
        {backfill_mode_final_select()}
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
