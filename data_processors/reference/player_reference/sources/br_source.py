"""
Basketball Reference Source Handler for Roster Registry

Handles fetching and parsing Basketball Reference roster data
with date-matching, fallback logic, and staleness detection.
"""

import logging
from datetime import date
from typing import Dict, Optional, Set, Tuple

import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)

# Team abbreviation normalization
TEAM_ABBR_NORMALIZATION = {
    'BRK': 'BKN',
    'CHO': 'CHA',
    'PHO': 'PHX',
}


def normalize_team_abbr(team_abbr: str) -> str:
    """Normalize team abbreviation to official NBA code."""
    normalized = TEAM_ABBR_NORMALIZATION.get(team_abbr, team_abbr)
    if normalized != team_abbr:
        logger.debug(f"Normalized team code: {team_abbr} → {normalized}")
    return normalized


class BRSourceHandler:
    """
    Fetches and parses Basketball Reference roster data.

    Authority Score: 1 (lowest - unofficial source, slowest updates)
    Fallback Window: 30 days
    Staleness Threshold: >30 days triggers warnings
    """

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize Basketball Reference source handler.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID for queries
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.authority_score = 1

    def get_roster_players(
        self,
        season_year: int,
        data_date: date,
        allow_fallback: bool = False
    ) -> Tuple[Set[str], Optional[date], bool]:
        """
        Get BR players with strict date matching.

        Args:
            season_year: NBA season starting year
            data_date: Required date for source data
            allow_fallback: If True, use latest available if exact date missing

        Returns:
            Tuple of (player_set, actual_date_used, matched_requested_date)
        """
        # Try exact date match
        query = """
        SELECT DISTINCT player_lookup, last_scraped_date
        FROM `{project}.nba_raw.br_rosters_current`
        WHERE last_scraped_date = @data_date
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
                actual_date = results['last_scraped_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.info(f"✓ BR exact match: {len(players)} players for {data_date}")
                return players, actual_date, True

            # No exact match
            if not allow_fallback:
                logger.error(f"✗ BR: No data for {data_date} (strict mode)")
                return set(), None, False

            # Fallback: Get latest within 30 days
            logger.warning(f"⚠️ BR: No data for {data_date}, using fallback")

            fallback_query = """
            SELECT DISTINCT player_lookup, last_scraped_date
            FROM `{project}.nba_raw.br_rosters_current`
            WHERE last_scraped_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
            AND last_scraped_date <= @data_date
            AND last_scraped_date = (
                SELECT MAX(last_scraped_date)
                FROM `{project}.nba_raw.br_rosters_current`
                WHERE season_year = @season_year
                AND last_scraped_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
                AND last_scraped_date <= @data_date
            )
            AND season_year = @season_year
            """.format(project=self.project_id)

            fallback_results = self.bq_client.query(fallback_query, job_config=job_config).to_dataframe()

            if not fallback_results.empty:
                # Fixed bug: was using 'last_scraped_date' instead of 'player_lookup'
                players = set(fallback_results['player_lookup'].unique())
                actual_date = fallback_results['last_scraped_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.warning(f"⚠️ BR fallback: {len(players)} players from {actual_date}")
                return players, actual_date, False
            else:
                logger.error(f"✗ BR: No fallback data available")
                return set(), None, False

        except GoogleAPIError as e:
            logger.error(f"Error querying BR roster data: {e}")
            return set(), None, False

    def get_detailed_data(
        self,
        season_year: int,
        data_date: date,
        allow_fallback: bool = False
    ) -> Dict[str, Dict]:
        """
        Get detailed data from Basketball Reference rosters with strict date matching and staleness checking.

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
                    'position': str | None,
                    'data_staleness_days': int
                }
            }
        """
        # Try exact date match first
        query = """
        SELECT
            player_lookup,
            player_full_name,
            team_abbrev as team_abbr,
            jersey_number,
            position,
            last_scraped_date
        FROM `{project}.nba_raw.br_rosters_current`
        WHERE last_scraped_date = @data_date
        AND season_year = @season_year
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("data_date", "DATE", data_date),
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])

        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if not results.empty:
                detailed_data = self._process_detailed_results(results, data_date)
                actual_date = results['last_scraped_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                logger.info(f"✓ BR detailed data exact match: {len(detailed_data)} players for {data_date}")
                return detailed_data

            # No exact match
            if not allow_fallback:
                logger.warning(f"✗ BR detailed: No data for {data_date} (strict mode)")
                return {}

            # Fallback to latest within 30 days
            logger.warning(f"⚠️ BR detailed: No data for {data_date}, using fallback")

            fallback_query = """
            SELECT
                player_lookup,
                player_full_name,
                team_abbrev as team_abbr,
                jersey_number,
                position,
                last_scraped_date
            FROM `{project}.nba_raw.br_rosters_current`
            WHERE last_scraped_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
            AND last_scraped_date <= @data_date
            AND last_scraped_date = (
                SELECT MAX(last_scraped_date)
                FROM `{project}.nba_raw.br_rosters_current`
                WHERE season_year = @season_year
                AND last_scraped_date >= DATE_SUB(@data_date, INTERVAL 30 DAY)
                AND last_scraped_date <= @data_date
            )
            AND season_year = @season_year
            """.format(project=self.project_id)

            fallback_results = self.bq_client.query(fallback_query, job_config=job_config).to_dataframe()

            if not fallback_results.empty:
                detailed_data = self._process_detailed_results(fallback_results, data_date)
                actual_date = fallback_results['last_scraped_date'].iloc[0]
                if isinstance(actual_date, pd.Timestamp):
                    actual_date = actual_date.date()

                # Check staleness
                staleness_days = (data_date - actual_date).days
                if staleness_days > 30:
                    logger.warning(
                        f"⚠️ BR detailed fallback data is {staleness_days} days stale "
                        f"(from {actual_date}). Jersey numbers and positions may be outdated."
                    )
                else:
                    logger.warning(f"⚠️ BR detailed fallback: {len(detailed_data)} players from {actual_date}")

                return detailed_data
            else:
                logger.error(f"✗ BR detailed: No fallback data available")
                return {}

        except Exception as e:
            logger.warning(f"Error getting Basketball Reference detailed data: {e}")
            return {}

    def _process_detailed_results(self, results: pd.DataFrame, data_date: date) -> Dict[str, Dict]:
        """
        Helper to process BR results into detailed data dict with staleness warning.

        Args:
            results: DataFrame with BR roster data
            data_date: Date being processed (for staleness calculation)

        Returns:
            Dict mapping player_lookup to player details
        """
        detailed_data = {}

        if results.empty:
            return detailed_data

        # Check staleness for warning
        latest_scrape = pd.to_datetime(results['last_scraped_date']).max()
        if isinstance(latest_scrape, pd.Timestamp):
            latest_scrape_date = latest_scrape.date()
        else:
            latest_scrape_date = latest_scrape

        staleness_days = (data_date - latest_scrape_date).days

        if staleness_days > 30:
            logger.warning(
                f"⚠️ Basketball Reference data is {staleness_days} days stale "
                f"(last scraped: {latest_scrape_date}). "
                f"Jersey numbers and positions may be outdated."
            )

        for _, row in results.iterrows():
            team_abbr = normalize_team_abbr(row['team_abbr'])

            detailed_data[row['player_lookup']] = {
                'player_full_name': row['player_full_name'],
                'team_abbr': team_abbr,
                'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                'position': row['position'] if pd.notna(row['position']) else None,
                'data_staleness_days': staleness_days
            }

        return detailed_data
