"""
ESPN Source Handler for Roster Registry

Handles fetching and parsing ESPN roster data with date-matching and fallback logic.
"""

import logging
from datetime import date
from typing import Dict, Optional, Set, Tuple

import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)


class ESPNSourceHandler:
    """
    Fetches and parses ESPN roster data.

    Authority Score: 2 (lower than NBA.com, higher than Basketball Reference)
    Fallback Window: 30 days
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize ESPN source handler.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID for queries
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.authority_score = 2

    def get_roster_players(
        self,
        season_year: int,
        data_date: date,
        allow_fallback: bool = False
    ) -> Tuple[Set[str], Optional[date], bool]:
        """
        Get ESPN roster players with strict date matching.

        Args:
            season_year: NBA season starting year
            data_date: Required date for source data
            allow_fallback: If True, use latest available if exact date missing

        Returns:
            Tuple of (player_set, actual_date_used, matched_requested_date)
        """
        # First try exact date match
        query = """
        SELECT DISTINCT player_lookup, roster_date
        FROM `{project}.nba_raw.espn_team_rosters`
        WHERE roster_date = @data_date
        AND season_year = @season_year
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if not results.empty:
                players = set(results['player_lookup'].unique())
                actual_date = results['roster_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.info(f"✓ ESPN exact match: {len(players)} players for {data_date}")
                return players, actual_date, True

            # No exact match found
            if not allow_fallback:
                logger.error(f"✗ ESPN: No data for {data_date} (strict mode)")
                return set(), None, False

            # Fallback: Get latest available within 30 days
            logger.warning(f"⚠️ ESPN: No data for {data_date}, using fallback")

            fallback_query = """
            SELECT DISTINCT player_lookup, roster_date
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE roster_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
            AND roster_date <= @data_date
            AND roster_date = (
                SELECT MAX(roster_date)
                FROM `{project}.nba_raw.espn_team_rosters`
                WHERE season_year = @season_year
                AND roster_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
                AND roster_date <= @data_date
            )
            AND season_year = @season_year
            """.format(project=self.project_id)

            fallback_results = self.bq_client.query(fallback_query, job_config=job_config).to_dataframe()

            if not fallback_results.empty:
                players = set(fallback_results['player_lookup'].unique())
                actual_date = fallback_results['roster_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.warning(f"⚠️ ESPN fallback: {len(players)} players from {actual_date}")
                return players, actual_date, False
            else:
                logger.error(f"✗ ESPN: No fallback data available")
                return set(), None, False

        except GoogleAPIError as e:
            logger.error(f"Error querying ESPN roster data: {e}")
            return set(), None, False

    def get_detailed_data(
        self,
        season_year: int,
        data_date: date,
        allow_fallback: bool = False
    ) -> Dict[str, Dict]:
        """
        Get detailed data from ESPN rosters with strict date matching.

        Returns jersey numbers, positions, and full names that match the exact date
        or uses fallback to latest available within 30 days.

        Args:
            season_year: NBA season starting year
            data_date: Required date for source data
            allow_fallback: If True, use latest available if exact date missing

        Returns:
            Dict mapping player_lookup to player details:
            {
                'player_lookup': {
                    'player_full_name': str,
                    'team_abbr': str,
                    'jersey_number': int | None,
                    'position': str | None
                }
            }
        """
        # Try exact date match first
        query = """
        SELECT
            player_lookup,
            player_full_name,
            team_abbr,
            jersey_number,
            position,
            roster_date
        FROM `{project}.nba_raw.espn_team_rosters`
        WHERE roster_date = @data_date
        AND season_year = @season_year
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if not results.empty:
                detailed_data = self._process_detailed_results(results)
                actual_date = results['roster_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.info(f"✓ ESPN detailed data exact match: {len(detailed_data)} players for {data_date}")
                return detailed_data

            # No exact match
            if not allow_fallback:
                logger.warning(f"✗ ESPN detailed: No data for {data_date} (strict mode)")
                return {}

            # Fallback to latest within 30 days
            logger.warning(f"⚠️ ESPN detailed: No data for {data_date}, using fallback")

            fallback_query = """
            SELECT
                player_lookup,
                player_full_name,
                team_abbr,
                jersey_number,
                position,
                roster_date
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE roster_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
            AND roster_date <= @data_date
            AND roster_date = (
                SELECT MAX(roster_date)
                FROM `{project}.nba_raw.espn_team_rosters`
                WHERE season_year = @season_year
                AND roster_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
                AND roster_date <= @data_date
            )
            AND season_year = @season_year
            """.format(project=self.project_id)

            fallback_results = self.bq_client.query(fallback_query, job_config=job_config).to_dataframe()

            if not fallback_results.empty:
                detailed_data = self._process_detailed_results(fallback_results)
                actual_date = fallback_results['roster_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.warning(f"⚠️ ESPN detailed fallback: {len(detailed_data)} players from {actual_date}")
                return detailed_data
            else:
                logger.error(f"✗ ESPN detailed: No fallback data available")
                return {}

        except Exception as e:
            logger.warning(f"Error getting ESPN detailed data: {e}")
            return {}

    def _process_detailed_results(self, results: pd.DataFrame) -> Dict[str, Dict]:
        """
        Helper to process ESPN results into detailed data dict.

        Args:
            results: DataFrame with ESPN roster data

        Returns:
            Dict mapping player_lookup to player details
        """
        detailed_data = {}

        for _, row in results.iterrows():
            detailed_data[row['player_lookup']] = {
                'player_full_name': row['player_full_name'],
                'team_abbr': row['team_abbr'],
                'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                'position': row['position'] if pd.notna(row['position']) else None
            }

        return detailed_data
