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
    
    def __init__(self, project_id: str = 'nba-props-platform', 
                 table_name: str = 'nba_reference.nba_schedule'):
        """
        Initialize database reader.
        
        Args:
            project_id: GCP project ID
            table_name: BigQuery table with schedule data (format: dataset.table)
        """
        self.project_id = project_id
        self.table_name = table_name
        self.bq_client = bigquery.Client(project=project_id)
        
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
            result = self.bq_client.query(query, job_config=job_config).result()
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
            result = self.bq_client.query(query, job_config=job_config).result()
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
            result = self.bq_client.query(query, job_config=job_config).result()
            
            date_map = {}
            for row in result:
                date_map[row.game_date] = row.game_count
            
            return date_map
            
        except Exception as e:
            logger.warning("Error querying season %d: %s", season, e)
            return None