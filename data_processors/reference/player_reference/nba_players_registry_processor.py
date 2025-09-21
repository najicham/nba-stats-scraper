#!/usr/bin/env python3
"""
File: processors/nba_reference/nba_players_registry_processor.py

NBA Players Registry Backfill Processor

Builds the NBA players registry from existing NBA.com gamebook data.
This processor reads from the processed gamebook table and creates the
authoritative player registry for name resolution.

Key Features:
- Processes historical gamebook data to build player registry
- Calculates game participation statistics
- Handles multi-team seasons (trades)
- Integrates with existing roster data for jersey numbers/positions
- Provides comprehensive audit trail

Usage:
- Backfill: Use the backfill job to process all historical data
- Incremental: Triggered after gamebook processing to update registry
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import pandas as pd
from google.cloud import bigquery

# Support both module execution and direct execution
try:
    from ..processor_base import ProcessorBase
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from processors.processor_base import ProcessorBase

from shared.utils.player_name_normalizer import normalize_name_for_lookup

logger = logging.getLogger(__name__)


class NbaPlayersRegistryProcessor(ProcessorBase):
    """
    Build and maintain the NBA players registry from gamebook data.
    
    This processor creates the authoritative player registry by analyzing
    NBA.com gamebook data to determine:
    - Which players actually played for which teams in which seasons
    - Game participation statistics
    - Jersey numbers and positions (when available)
    """
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_reference.nba_players_registry'
        self.processing_strategy = 'MERGE_UPDATE'  # Replace existing season data
        
        # Initialize BigQuery client
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Processing tracking
        self.processing_run_id = f"registry_build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set()
        }
        
        logger.info(f"Initialized registry processor with run ID: {self.processing_run_id}")
    
    def get_gamebook_player_data(self, season_filter: str = None, 
                               team_filter: str = None, 
                               date_range: Tuple[str, str] = None) -> pd.DataFrame:
        """
        Extract player data from processed gamebook table.
        
        Args:
            season_filter: Optional season filter ("2023-24")
            team_filter: Optional team filter ("LAL")
            date_range: Optional date range tuple (start_date, end_date)
            
        Returns:
            DataFrame with player participation data
        """
        logger.info("Querying gamebook data for registry building...")
        
        # Build the query
        query = """
        SELECT 
            player_name,
            player_lookup,
            team_abbr,
            season_year,
            game_date,
            game_id,
            player_status,
            name_resolution_status,
            COUNT(*) as game_appearances
        FROM `{project}.nba_raw.nbac_gamebook_player_stats`
        WHERE player_name IS NOT NULL 
        AND team_abbr IS NOT NULL
        AND season_year IS NOT NULL
        """.format(project=self.project_id)
        
        query_params = []
        
        # Add filters
        if season_filter:
            # Convert season string like "2023-24" to season_year int
            season_year = int(season_filter.split('-')[0])
            query += " AND season_year = @season_year"
            query_params.append(bigquery.ScalarQueryParameter("season_year", "INT64", season_year))
        
        if team_filter:
            query += " AND team_abbr = @team_abbr"
            query_params.append(bigquery.ScalarQueryParameter("team_abbr", "STRING", team_filter))
            
        if date_range:
            query += " AND game_date BETWEEN @start_date AND @end_date"
            query_params.extend([
                bigquery.ScalarQueryParameter("start_date", "DATE", date_range[0]),
                bigquery.ScalarQueryParameter("end_date", "DATE", date_range[1])
            ])
        
        query += """
        GROUP BY 
            player_name, player_lookup, team_abbr, season_year, 
            game_date, game_id, player_status, name_resolution_status
        ORDER BY season_year, team_abbr, player_name
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            logger.info(f"Retrieved {len(results)} player-game records from gamebook data")
            return results
            
        except Exception as e:
            logger.error(f"Error querying gamebook data: {e}")
            raise e
    
    def get_roster_enhancement_data(self, season_filter: str = None) -> Dict[Tuple[str, str], Dict]:
        """
        Get jersey numbers and positions from roster data to enhance registry.
        
        Args:
            season_filter: Optional season filter
            
        Returns:
            Dict mapping (team, player_lookup) -> {jersey_number, position}
        """
        logger.info("Loading roster enhancement data...")
        
        try:
            # Query Basketball Reference roster data for jersey/position info
            query = """
            SELECT DISTINCT
                team_abbrev as team_abbr,
                player_lookup,
                jersey_number,
                position,
                season_year
            FROM `{project}.nba_raw.br_rosters_current`
            WHERE player_lookup IS NOT NULL
            AND team_abbrev IS NOT NULL
            """.format(project=self.project_id)
            
            query_params = []
            
            if season_filter:
                season_year = int(season_filter.split('-')[0])
                query += " AND season_year = @season_year"
                query_params.append(bigquery.ScalarQueryParameter("season_year", "INT64", season_year))
            
            job_config = bigquery.QueryJobConfig(query_parameters=query_params)
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            # Build lookup dict
            enhancement_data = {}
            for _, row in results.iterrows():
                key = (row['team_abbr'], row['player_lookup'])
                enhancement_data[key] = {
                    'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                    'position': row['position'] if pd.notna(row['position']) else None,
                    'season_year': row['season_year']
                }
            
            logger.info(f"Loaded enhancement data for {len(enhancement_data)} player-team combinations")
            return enhancement_data
            
        except Exception as e:
            logger.warning(f"Could not load roster enhancement data: {e}")
            return {}
    
    def calculate_season_string(self, season_year: int) -> str:
        """Convert season year to standard season string format."""
        return f"{season_year}-{str(season_year + 1)[-2:]}"
    
    def aggregate_player_stats(self, gamebook_df: pd.DataFrame) -> List[Dict]:
        """
        Aggregate gamebook data into registry records.
        
        Args:
            gamebook_df: Raw gamebook data
            
        Returns:
            List of registry records ready for BigQuery
        """
        logger.info("Aggregating player statistics for registry...")
        
        # Get roster enhancement data
        enhancement_data = self.get_roster_enhancement_data()
        
        registry_records = []
        
        # Group by player-team-season combinations
        groupby_cols = ['player_name', 'player_lookup', 'team_abbr', 'season_year']
        grouped = gamebook_df.groupby(groupby_cols)
        
        for (player_name, player_lookup, team_abbr, season_year), group in grouped:
            # Calculate season string
            season_str = self.calculate_season_string(season_year)
            
            # Calculate game participation stats
            total_appearances = len(group)
            unique_games = group['game_id'].nunique()
            
            # Get date range
            game_dates = pd.to_datetime(group['game_date'])
            first_game = game_dates.min().date()
            last_game = game_dates.max().date()
            
            # Count games by status
            status_counts = group['player_status'].value_counts()
            active_games = status_counts.get('active', 0)
            inactive_games = status_counts.get('inactive', 0)
            dnp_games = status_counts.get('dnp', 0)
            
            # Determine source priority and confidence
            resolution_statuses = group['name_resolution_status'].value_counts()
            if 'original' in resolution_statuses:
                source_priority = 'nba_gamebook'
                confidence_score = 1.0
            elif 'resolved' in resolution_statuses:
                source_priority = 'nba_gamebook_resolved'
                confidence_score = 0.9
            else:
                source_priority = 'nba_gamebook_uncertain'
                confidence_score = 0.7
            
            # Look up enhancement data
            enhancement_key = (team_abbr, player_lookup)
            enhancement = enhancement_data.get(enhancement_key, {})
            
            # Create registry record
            record = {
                'player_name': player_name,
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,
                'season': season_str,
                'first_game_date': first_game.isoformat(),
                'last_game_date': last_game.isoformat(),
                'games_played': active_games,  # Only count active games
                'total_appearances': total_appearances,  # All appearances including inactive/dnp
                'inactive_appearances': inactive_games,
                'dnp_appearances': dnp_games,
                'jersey_number': enhancement.get('jersey_number'),
                'position': enhancement.get('position'),
                'last_roster_update': date.today().isoformat() if enhancement else None,
                'source_priority': source_priority,
                'confidence_score': confidence_score,
                'created_date': date.today().isoformat(),
                'updated_date': date.today().isoformat(),
                'created_by': self.processing_run_id
            }
            
            registry_records.append(record)
            
            # Update stats
            self.stats['players_processed'] += 1
            self.stats['seasons_processed'].add(season_str)
            self.stats['teams_processed'].add(team_abbr)
        
        logger.info(f"Created {len(registry_records)} registry records")
        return registry_records
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate registry data structure."""
        errors = []
        
        if not isinstance(data, dict):
            errors.append("Data must be a dictionary")
            return errors
        
        # For this processor, data is coming from our own aggregation
        # so validation is minimal
        return errors
    
    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """
        Transform data for this processor.
        
        For the registry processor, the 'raw_data' parameter contains filters
        and the actual data comes from querying the gamebook table.
        """
        # Extract filters from raw_data
        season_filter = raw_data.get('season_filter')
        team_filter = raw_data.get('team_filter') 
        date_range = raw_data.get('date_range')
        
        logger.info(f"Building registry with filters: season={season_filter}, team={team_filter}, date_range={date_range}")
        
        # Get gamebook data
        gamebook_df = self.get_gamebook_player_data(
            season_filter=season_filter,
            team_filter=team_filter, 
            date_range=date_range
        )
        
        if gamebook_df.empty:
            logger.warning("No gamebook data found for specified filters")
            return []
        
        # Aggregate into registry records
        registry_records = self.aggregate_player_stats(gamebook_df)
        
        return registry_records
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load registry data to BigQuery."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # For registry updates, we typically replace data for specific seasons
                seasons_to_update = set(row['season'] for row in rows)
                teams_to_update = set(row['team_abbr'] for row in rows)
                
                logger.info(f"Updating registry for seasons: {seasons_to_update}")
                logger.info(f"Updating registry for teams: {teams_to_update}")
                
                # Delete existing data for these seasons/teams
                for season in seasons_to_update:
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE season = '{season}'
                    """
                    
                    # If we're updating specific teams, be more targeted
                    if len(teams_to_update) < 30:  # Assume full season update if many teams
                        team_list = "', '".join(teams_to_update)
                        delete_query += f" AND team_abbr IN ('{team_list}')"
                    
                    self.bq_client.query(delete_query).result()
                    logger.info(f"Deleted existing registry data for season {season}")
            
            # Insert new data
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logger.error(f"BigQuery insert errors: {errors}")
            else:
                logger.info(f"Successfully inserted {len(rows)} registry records")
                self.stats['records_created'] = len(rows)
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading registry data: {error_msg}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }
    
    def build_registry_for_season(self, season: str, team: str = None) -> Dict:
        """
        Build registry for a specific season.
        
        Args:
            season: Season string ("2023-24")
            team: Optional team filter
            
        Returns:
            Processing result summary
        """
        logger.info(f"Building registry for season {season}" + (f", team {team}" if team else ""))
        
        # Create filter data
        filter_data = {
            'season_filter': season,
            'team_filter': team
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)
        
        # Log summary
        logger.info(f"Registry build complete for {season}:")
        logger.info(f"  Records processed: {result['rows_processed']}")
        logger.info(f"  Players: {self.stats['players_processed']}")
        logger.info(f"  Teams: {len(self.stats['teams_processed'])}")
        logger.info(f"  Errors: {len(result.get('errors', []))}")
        
        return {
            'season': season,
            'team_filter': team,
            'records_processed': result['rows_processed'],
            'players_processed': self.stats['players_processed'],
            'teams_processed': list(self.stats['teams_processed']),
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }
    
    def build_registry_for_date_range(self, start_date: str, end_date: str) -> Dict:
        """
        Build registry for a specific date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            Processing result summary
        """
        logger.info(f"Building registry for date range {start_date} to {end_date}")
        
        # Create filter data
        filter_data = {
            'date_range': (start_date, end_date)
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)
        
        # Log summary
        logger.info(f"Registry build complete for {start_date} to {end_date}:")
        logger.info(f"  Records processed: {result['rows_processed']}")
        logger.info(f"  Players: {self.stats['players_processed']}")
        logger.info(f"  Seasons: {len(self.stats['seasons_processed'])}")
        logger.info(f"  Teams: {len(self.stats['teams_processed'])}")
        
        return {
            'date_range': (start_date, end_date),
            'records_processed': result['rows_processed'],
            'players_processed': self.stats['players_processed'],
            'seasons_processed': list(self.stats['seasons_processed']),
            'teams_processed': list(self.stats['teams_processed']),
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }
    
    def get_registry_summary(self) -> Dict:
        """Get summary statistics of the current registry."""
        try:
            query = f"""
            SELECT 
                COUNT(*) as total_records,
                COUNT(DISTINCT player_lookup) as unique_players,
                COUNT(DISTINCT season) as seasons_covered,
                COUNT(DISTINCT team_abbr) as teams_covered,
                SUM(games_played) as total_games_played,
                AVG(games_played) as avg_games_per_record,
                MAX(updated_date) as last_updated
            FROM `{self.project_id}.{self.table_name}`
            """
            
            result = self.bq_client.query(query).to_dataframe()
            
            if result.empty:
                return {'error': 'No data in registry'}
            
            summary = result.iloc[0].to_dict()
            
            # Get season breakdown
            season_query = f"""
            SELECT 
                season,
                COUNT(*) as records,
                COUNT(DISTINCT player_lookup) as players,
                COUNT(DISTINCT team_abbr) as teams
            FROM `{self.project_id}.{self.table_name}`
            GROUP BY season
            ORDER BY season DESC
            """
            
            seasons = self.bq_client.query(season_query).to_dataframe()
            summary['seasons_breakdown'] = seasons.to_dict('records')
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting registry summary: {e}")
            return {'error': str(e)}


# Convenience functions for direct usage
def build_registry_for_season(season: str, team: str = None) -> Dict:
    """Convenience function to build registry for a season."""
    processor = NbaPlayersRegistryProcessor()
    return processor.build_registry_for_season(season, team)


def build_registry_for_date_range(start_date: str, end_date: str) -> Dict:
    """Convenience function to build registry for date range."""
    processor = NbaPlayersRegistryProcessor()
    return processor.build_registry_for_date_range(start_date, end_date)


def get_registry_summary() -> Dict:
    """Convenience function to get registry summary."""
    processor = NbaPlayersRegistryProcessor()
    return processor.get_registry_summary()