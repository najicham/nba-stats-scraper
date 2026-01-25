# ============================================================================
# FILE: shared/utils/schedule/database_reader.py
# ============================================================================
"""
Schedule Database Reader - Fast queries from BigQuery.

Provides quick checks for schedule data already loaded in BigQuery.
Falls back to GCS if database is not populated.
"""

import logging
from typing import Dict, Optional, Set
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class ScheduleDatabaseReader:
    """
    Fast schedule queries from BigQuery.
    
    Assumes schedule data is loaded in BigQuery table for fast access.
    Returns None when database unavailable (signals fallback to GCS).
    """
    
    def __init__(self, project_id: str = None,
                 table_name: str = 'nba_reference.nba_schedule'):
        """
        Initialize database reader.

        Args:
            project_id: GCP project ID (defaults to centralized config)
            table_name: BigQuery table with schedule data (format: dataset.table)
        """
        from shared.config.gcp_config import get_project_id
        from shared.clients import get_bigquery_client
        self.project_id = project_id or get_project_id()
        self.table_name = table_name
        self.bq_client = get_bigquery_client(self.project_id)
        
        # Cache for exists checks
        self._table_exists: Optional[bool] = None
    
    def table_exists(self) -> bool:
        """Check if schedule table exists in BigQuery."""
        if self._table_exists is not None:
            return self._table_exists
        
        try:
            table_ref = f"{self.project_id}.{self.table_name}"
            self.bq_client.get_table(table_ref)
            self._table_exists = True
            logger.info("Schedule database table found: %s", table_ref)
            return True
        except Exception as e:
            logger.debug("Schedule table not found: %s", e)
            self._table_exists = False
            return False
    
    def has_games_on_date(self, game_date: str, game_types: Optional[list] = None) -> Optional[bool]:
        """
        Check if games exist on a date (fast database query).
        
        Args:
            game_date: Date string in YYYY-MM-DD format
            game_types: Optional list of game types to filter (e.g., ['playoff', 'play_in'])
            
        Returns:
            True if games exist, False if no games, None if table doesn't exist
        """
        if not self.table_exists():
            return None  # Signal to use GCS fallback
        
        try:
            query = f"""
                SELECT COUNT(*) as count
                FROM `{self.project_id}.{self.table_name}`
                WHERE game_date = @game_date
            """
            
            params = [bigquery.ScalarQueryParameter("game_date", "STRING", game_date)]
            
            if game_types:
                placeholders = ','.join([f'@type{i}' for i in range(len(game_types))])
                query += f" AND game_type IN ({placeholders})"
                for i, gt in enumerate(game_types):
                    params.append(bigquery.ScalarQueryParameter(f"type{i}", "STRING", gt))
            
            job_config = bigquery.QueryJobConfig(query_parameters=params)
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
            row = next(result)

            return row.count > 0
            
        except Exception as e:
            logger.warning("Error checking database for %s: %s", game_date, e)
            return None  # Signal to use GCS fallback
    
    def get_game_count(self, game_date: str, game_types: Optional[list] = None) -> Optional[int]:
        """
        Get count of games on a date (fast database query).
        
        Args:
            game_date: Date string in YYYY-MM-DD format
            game_types: Optional list of game types to filter
            
        Returns:
            Game count, or None if table doesn't exist or query fails
        """
        if not self.table_exists():
            return None
        
        try:
            query = f"""
                SELECT COUNT(*) as count
                FROM `{self.project_id}.{self.table_name}`
                WHERE game_date = @game_date
            """
            
            params = [bigquery.ScalarQueryParameter("game_date", "STRING", game_date)]
            
            if game_types:
                placeholders = ','.join([f'@type{i}' for i in range(len(game_types))])
                query += f" AND game_type IN ({placeholders})"
                for i, gt in enumerate(game_types):
                    params.append(bigquery.ScalarQueryParameter(f"type{i}", "STRING", gt))
            
            job_config = bigquery.QueryJobConfig(query_parameters=params)
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
            row = next(result)
            
            return row.count
            
        except Exception as e:
            logger.warning("Error querying database for %s: %s", game_date, e)
            return None
    
    def get_season_date_map(self, season: int, game_types: Optional[list] = None) -> Optional[Dict[str, int]]:
        """
        Get date-to-count map for a season from database.

        Args:
            season: Season year (e.g., 2024 for 2024-25)
            game_types: Optional list of game types to filter

        Returns:
            Dictionary mapping dates to game counts, or None if query fails
        """
        if not self.table_exists():
            return None

        try:
            query = f"""
                SELECT
                    game_date,
                    COUNT(*) as game_count
                FROM `{self.project_id}.{self.table_name}`
                WHERE season_year = @season
            """

            params = [bigquery.ScalarQueryParameter("season", "INT64", season)]

            if game_types:
                placeholders = ','.join([f'@type{i}' for i in range(len(game_types))])
                query += f" AND game_type IN ({placeholders})"
                for i, gt in enumerate(game_types):
                    params.append(bigquery.ScalarQueryParameter(f"type{i}", "STRING", gt))

            query += " GROUP BY game_date ORDER BY game_date"

            job_config = bigquery.QueryJobConfig(query_parameters=params)
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)

            date_map = {}
            for row in result:
                date_map[row.game_date] = row.game_count

            return date_map

        except Exception as e:
            logger.warning("Error querying season %d: %s", season, e)
            return None

    def get_nba_api_season_type(self, game_date: str) -> Optional[str]:
        """
        Get the NBA.com API season_type for a specific date.

        Queries the schedule deduplication view to determine game type flags and maps
        them to the season_type parameter expected by NBA.com stats API.

        Args:
            game_date: Date string in YYYY-MM-DD format

        Returns:
            NBA.com API season_type string:
            - "All Star" for All-Star Weekend games
            - "PlayIn" for Play-In Tournament games
            - "Playoffs" for playoff games (first round through finals)
            - "Pre Season" for preseason games
            - "Regular Season" for regular season (including Emirates Cup)
            - None if no games found or query fails
        """
        try:
            # Use deduplication view to get accurate game status
            # (raw table can have duplicate rows with conflicting statuses)
            query = """
                SELECT
                    is_all_star,
                    is_playoffs,
                    playoff_round,
                    is_regular_season
                FROM `nba-props-platform.nba_raw.v_nbac_schedule_latest`
                WHERE DATE(game_date) = @game_date
                LIMIT 1
            """

            params = [bigquery.ScalarQueryParameter("game_date", "DATE", game_date)]
            job_config = bigquery.QueryJobConfig(query_parameters=params)
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)

            rows = list(result)
            if not rows:
                logger.debug("No games found in schedule for date %s", game_date)
                return None

            row = rows[0]

            # Map game type flags to NBA.com API season_type
            if row.is_all_star:
                return "All Star"
            elif row.is_playoffs and row.playoff_round == 'play_in':
                return "PlayIn"
            elif row.is_playoffs:
                return "Playoffs"
            elif row.is_regular_season:
                return "Regular Season"
            else:
                # Likely preseason
                return "Pre Season"

        except Exception as e:
            logger.warning("Error querying season type for %s: %s", game_date, e)
            return None

    def get_season_start_date(self, season_year: int) -> Optional[str]:
        """
        Get the first regular season game date for a given season.

        Uses the schedule database to find the earliest regular season game.
        This is dynamic and accounts for schedule changes year-to-year.

        Args:
            season_year: Season year (e.g., 2024 for 2024-25 season)

        Returns:
            Date string in YYYY-MM-DD format, or None if not found/query fails

        Example:
            >>> reader = ScheduleDatabaseReader()
            >>> reader.get_season_start_date(2024)
            '2024-10-22'
        """
        try:
            # Query for first regular season game of the season
            # Uses inline deduplication since v_nbac_schedule_latest view
            # only covers 90 days (not enough for historical seasons)
            # Dedup logic: take highest game_status per game_id (Final=3 wins)
            query = """
                WITH dedup AS (
                    SELECT *,
                        ROW_NUMBER() OVER (
                            PARTITION BY game_id
                            ORDER BY game_status DESC, processed_at DESC
                        ) as rn
                    FROM `nba-props-platform.nba_raw.nbac_schedule`
                    WHERE season_year = @season_year
                      AND game_date >= @min_date
                )
                SELECT MIN(DATE(game_date)) as season_start
                FROM dedup
                WHERE rn = 1
                  AND is_regular_season = TRUE
                  AND game_status = 3
            """

            # Use wide date range to satisfy partition filter
            # NBA seasons start in October, so look from July onward
            min_date = f"{season_year}-07-01"

            params = [
                bigquery.ScalarQueryParameter("season_year", "INT64", season_year),
                bigquery.ScalarQueryParameter("min_date", "DATE", min_date)
            ]

            job_config = bigquery.QueryJobConfig(query_parameters=params)
            # Wait for completion with timeout to prevent indefinite hangs
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)

            row = next(result, None)
            if row and row.season_start:
                logger.debug("Season %d starts: %s", season_year, row.season_start)
                return str(row.season_start)

            logger.debug("No season start date found for season %d", season_year)
            return None

        except Exception as e:
            logger.warning("Error querying season start for %d: %s", season_year, e)
            return None