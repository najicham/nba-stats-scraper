"""
Base class for Phase 4 precompute processors
Provides common functionality for pre-aggregation processors
"""
from google.cloud import bigquery
from datetime import date
import logging

logger = logging.getLogger(__name__)

class PrecomputeProcessorBase:
    """Base class for precompute processors"""
    
    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.dataset_id = "nba_analytics"
    
    def process_date(self, game_date: date) -> dict:
        """
        Process precompute aggregations for a given date
        
        Args:
            game_date: Date to process
            
        Returns:
            dict with processing stats
        """
        raise NotImplementedError("Subclasses must implement process_date()")
    
    def get_games_for_date(self, game_date: date) -> list:
        """Get all games scheduled for the date"""
        query = f"""
        SELECT DISTINCT game_id, home_team_abbr, away_team_abbr
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date = '{game_date}'
          AND (is_regular_season = TRUE OR is_playoffs = TRUE)
          AND is_all_star = FALSE
        ORDER BY game_id
        """
        return list(self.bq_client.query(query).result())
    
    def get_teams_playing_tonight(self, game_date: date) -> list:
        """Get all teams with games tonight"""
        query = f"""
        SELECT DISTINCT team_abbr
        FROM (
            SELECT home_team_abbr as team_abbr
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = '{game_date}'
              AND (is_regular_season = TRUE OR is_playoffs = TRUE)
              AND is_all_star = FALSE
            UNION DISTINCT
            SELECT away_team_abbr
            FROM `{self.project_id}.nba_raw.nbac_schedule`
            WHERE game_date = '{game_date}'
              AND (is_regular_season = TRUE OR is_playoffs = TRUE)
              AND is_all_star = FALSE
        )
        ORDER BY team_abbr
        """
        result = self.bq_client.query(query).result()
        return [row.team_abbr for row in result]
