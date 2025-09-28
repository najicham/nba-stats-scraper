#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/roster_registry_processor.py

Roster Registry Processor - Simplified Implementation

Maintains the NBA players registry from roster assignment data.
Simplified version with conflict prevention removed and bulk universal ID resolution.

Usage Scenarios:
1. Daily roster updates: Triggered after roster scrapers complete
2. Season start processing: Bulk roster processing for new season
3. Trade/transaction handling: Update registry when players change teams
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Set
import pandas as pd
from google.cloud import bigquery

from data_processors.reference.base.registry_processor_base import RegistryProcessorBase
from data_processors.reference.base.name_change_detection_mixin import NameChangeDetectionMixin
from data_processors.reference.base.database_strategies import DatabaseStrategiesMixin

logger = logging.getLogger(__name__)


class RosterRegistryProcessor(RegistryProcessorBase, NameChangeDetectionMixin, DatabaseStrategiesMixin):
    """
    Registry processor for roster assignment data.
    
    Creates registry records from roster data sources:
    - ESPN team rosters
    - NBA.com player list  
    - Basketball Reference season rosters
    
    Provides early registry population before game participation.
    """
    
    def __init__(self, test_mode: bool = False, strategy: str = "merge", 
                 confirm_full_delete: bool = False,
                 enable_name_change_detection: bool = True):
        super().__init__(test_mode, strategy, confirm_full_delete, enable_name_change_detection)
        
        # Set processor type for source tracking
        self.processor_type = 'roster'
        
        logger.info("Initialized Roster Registry Processor")
    
    def get_current_roster_data(self, season_year: int = None) -> Dict[str, Set[str]]:
        """
        Get current roster players from all roster sources.
        
        Args:
            season_year: NBA season starting year (e.g., 2024 for 2024-25 season)
        
        Returns:
            Dict mapping source names to sets of player_lookup values
        """
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:  # Oct-Dec = new season starting
                season_year = date.today().year
            else:  # Jan-Sep = season ending
                season_year = date.today().year - 1
        
        logger.info(f"Getting current roster data for {season_year}-{season_year+1} season")
        
        roster_sources = {
            'espn_rosters': self._get_espn_roster_players(season_year),
            'nba_player_list': self._get_nba_official_players(season_year), 
            'basketball_reference': self._get_basketball_reference_players(season_year)
        }
        
        # Log summary
        for source, players in roster_sources.items():
            logger.info(f"{source}: {len(players)} players")
        
        return roster_sources
    
    def _get_espn_roster_players(self, season_year: int) -> Set[str]:
        """Get current roster players from ESPN team rosters."""
        query = """
        SELECT DISTINCT player_lookup, team_abbr, jersey_number, position
        FROM `{project}.nba_raw.espn_team_rosters`
        WHERE roster_date = (
            SELECT MAX(roster_date) 
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE season_year = @season_year
        )
        AND season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            players = set(results['player_lookup'].unique()) if not results.empty else set()
            logger.info(f"ESPN rosters: {len(players)} players found")
            return players
        except Exception as e:
            logger.warning(f"Error querying ESPN roster data: {e}")
            return set()
    
    def _get_nba_official_players(self, season_year: int) -> Set[str]:
        """Get active players from NBA.com official player list."""
        query = """
        SELECT DISTINCT player_lookup, team_abbr
        FROM `{project}.nba_raw.nbac_player_list_current`
        WHERE is_active = TRUE
        AND season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            players = set(results['player_lookup'].unique()) if not results.empty else set()
            logger.info(f"NBA.com player list: {len(players)} players found")
            return players
        except Exception as e:
            logger.warning(f"Error querying NBA.com player list: {e}")
            return set()
    
    def _get_basketball_reference_players(self, season_year: int) -> Set[str]:
        """Get players from Basketball Reference season rosters."""
        query = """
        SELECT DISTINCT player_lookup, team_abbrev as team_abbr
        FROM `{project}.nba_raw.br_rosters_current`
        WHERE season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            players = set(results['player_lookup'].unique()) if not results.empty else set()
            logger.info(f"Basketball Reference rosters: {len(players)} players found")
            return players
        except Exception as e:
            logger.warning(f"Error querying Basketball Reference roster data: {e}")
            return set()
    
    def get_existing_registry_players(self, season: str) -> Set[str]:
        """Get players already in registry for current season."""
        query = """
        SELECT DISTINCT player_lookup
        FROM `{project}.{table_name}`
        WHERE season = @season
        """.format(project=self.project_id, table_name=self.table_name)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            existing_players = set(results['player_lookup'].unique()) if not results.empty else set()
            logger.info(f"Found {len(existing_players)} existing players in registry for {season}")
            return existing_players
        except Exception as e:
            logger.warning(f"Error querying existing registry players: {e}")
            return set()
    
    def aggregate_roster_assignments(self, roster_data: Dict[str, Set[str]], season_year: int) -> List[Dict]:
        """
        Aggregate roster data into registry records with bulk universal ID resolution.
        
        Args:
            roster_data: Dict of roster sources and their players
            season_year: NBA season starting year
            
        Returns:
            List of registry record dictionaries
        """
        logger.info("Aggregating roster assignments into registry records...")
        
        # Combine all roster sources and collect detailed data
        all_roster_players = set()
        player_details = {}  # player_lookup -> {team_abbr, sources, enhancement_data}
        
        for source, players in roster_data.items():
            all_roster_players.update(players)
            
            # Get detailed data for each source
            detailed_data = self._get_detailed_roster_data(source, season_year)
            
            for player_lookup, details in detailed_data.items():
                if player_lookup not in player_details:
                    player_details[player_lookup] = {
                        'team_abbr': details['team_abbr'],
                        'sources': [],
                        'enhancement_data': {}
                    }
                
                player_details[player_lookup]['sources'].append(source)
                
                # Merge enhancement data (jersey_number, position, etc.)
                if 'jersey_number' in details and details['jersey_number']:
                    player_details[player_lookup]['enhancement_data']['jersey_number'] = details['jersey_number']
                if 'position' in details and details['position']:
                    player_details[player_lookup]['enhancement_data']['position'] = details['position']
                if 'player_full_name' in details and details['player_full_name']:
                    player_details[player_lookup]['enhancement_data']['player_full_name'] = details['player_full_name']
        
        # BULK RESOLUTION: Get all universal IDs in one operation
        unique_player_lookups = list(all_roster_players)
        logger.info(f"Performing bulk universal ID resolution for {len(unique_player_lookups)} roster players")
        
        universal_id_mappings = self.bulk_resolve_universal_player_ids(unique_player_lookups)
        
        registry_records = []
        season_str = self.calculate_season_string(season_year)
        
        for player_lookup in all_roster_players:
            details = player_details.get(player_lookup, {})
            team_abbr = details.get('team_abbr', 'UNK')
            sources = details.get('sources', [])
            enhancement = details.get('enhancement_data', {})
            
            # Determine source priority and confidence with dynamic logic
            source_priority, confidence_score = self._determine_roster_source_priority_and_confidence(
                sources, enhancement, season_year
            )
            
            # Get universal player ID from bulk resolution
            universal_id = universal_id_mappings.get(player_lookup, f"{player_lookup}_001")
            
            # Create base registry record
            record = {
                'universal_player_id': universal_id,
                'player_name': enhancement.get('player_full_name', player_lookup.title()),
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,
                'season': season_str,
                
                # No game data yet (roster processor runs pre-game)
                'first_game_date': None,
                'last_game_date': None,
                'games_played': 0,
                'total_appearances': 0,
                'inactive_appearances': 0,
                'dnp_appearances': 0,
                
                # Roster-specific fields
                'jersey_number': enhancement.get('jersey_number'),
                'position': enhancement.get('position'),
                'last_roster_update': date.today(),
                
                # Source metadata
                'source_priority': source_priority,
                'confidence_score': confidence_score,
                'created_by': self.processing_run_id,
                'created_at': datetime.now(),
                'processed_at': datetime.now()
            }
            
            # Enhance record with source tracking
            enhanced_record = self.enhance_record_with_source_tracking(record, self.processor_type)
            
            # Convert types for BigQuery
            enhanced_record = self._convert_pandas_types_for_json(enhanced_record)
            registry_records.append(enhanced_record)
        
        logger.info(f"Created {len(registry_records)} registry records from roster data")
        return registry_records
    
    def _determine_roster_source_priority_and_confidence(self, sources: List[str], 
                                                       enhancement: Dict, season_year: int) -> Tuple[str, float]:
        """Determine source priority and confidence with dynamic logic for roster data."""
        current_year = date.today().year
        data_recency_days = (date.today() - date(season_year, 10, 1)).days
        
        # Base source priority (ESPN is most reliable for current rosters)
        if 'espn_rosters' in sources:
            source_priority = 'roster_espn'
            base_confidence = 0.8
        elif 'nba_player_list' in sources:
            source_priority = 'roster_nba_com'
            base_confidence = 0.7
        elif 'basketball_reference' in sources:
            source_priority = 'roster_br'
            base_confidence = 0.6
        else:
            source_priority = 'roster_unknown'
            base_confidence = 0.3
        
        confidence_score = base_confidence
        
        # Multiple sources increase confidence
        if len(sources) >= 3:
            confidence_score = min(confidence_score + 0.15, 1.0)
        elif len(sources) >= 2:
            confidence_score = min(confidence_score + 0.1, 1.0)
        
        # Having detailed roster info increases confidence
        if enhancement.get('jersey_number'):
            confidence_score = min(confidence_score + 0.05, 1.0)
        if enhancement.get('position'):
            confidence_score = min(confidence_score + 0.05, 1.0)
        
        # Recent data is more reliable during current season
        if data_recency_days < 30:  # Very recent data
            confidence_score = min(confidence_score + 0.1, 1.0)
        elif data_recency_days > 365:  # Old data
            confidence_score = max(confidence_score - 0.1, 0.1)
        
        return source_priority, confidence_score
    
    def _get_detailed_roster_data(self, source: str, season_year: int) -> Dict[str, Dict]:
        """Get detailed roster data for a specific source."""
        if source == 'espn_rosters':
            return self._get_espn_detailed_data(season_year)
        elif source == 'nba_player_list':
            return self._get_nba_detailed_data(season_year)
        elif source == 'basketball_reference':
            return self._get_br_detailed_data(season_year)
        else:
            logger.warning(f"Unknown roster source: {source}")
            return {}
    
    def _get_espn_detailed_data(self, season_year: int) -> Dict[str, Dict]:
        """Get detailed data from ESPN rosters."""
        query = """
        SELECT 
            player_lookup,
            player_full_name,
            team_abbr,
            jersey_number,
            position
        FROM `{project}.nba_raw.espn_team_rosters`
        WHERE roster_date = (
            SELECT MAX(roster_date) 
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE season_year = @season_year
        )
        AND season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            detailed_data = {}
            
            for _, row in results.iterrows():
                detailed_data[row['player_lookup']] = {
                    'player_full_name': row['player_full_name'],
                    'team_abbr': row['team_abbr'],
                    'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                    'position': row['position'] if pd.notna(row['position']) else None
                }
            
            return detailed_data
        except Exception as e:
            logger.warning(f"Error getting ESPN detailed data: {e}")
            return {}
    
    def _get_nba_detailed_data(self, season_year: int) -> Dict[str, Dict]:
        """Get detailed data from NBA.com player list."""
        query = """
        SELECT 
            player_lookup,
            player_full_name,
            team_abbr,
            jersey_number,
            position
        FROM `{project}.nba_raw.nbac_player_list_current`
        WHERE is_active = TRUE
        AND season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            detailed_data = {}
            
            for _, row in results.iterrows():
                detailed_data[row['player_lookup']] = {
                    'player_full_name': row['player_full_name'],
                    'team_abbr': row['team_abbr'],
                    'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                    'position': row['position'] if pd.notna(row['position']) else None
                }
            
            return detailed_data
        except Exception as e:
            logger.warning(f"Error getting NBA.com detailed data: {e}")
            return {}
    
    def _get_br_detailed_data(self, season_year: int) -> Dict[str, Dict]:
        """Get detailed data from Basketball Reference rosters."""
        query = """
        SELECT 
            player_lookup,
            player_full_name,
            team_abbrev as team_abbr,
            jersey_number,
            position
        FROM `{project}.nba_raw.br_rosters_current`
        WHERE season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            detailed_data = {}
            
            for _, row in results.iterrows():
                detailed_data[row['player_lookup']] = {
                    'player_full_name': row['player_full_name'],
                    'team_abbr': row['team_abbr'],
                    'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                    'position': row['position'] if pd.notna(row['position']) else None
                }
            
            return detailed_data
        except Exception as e:
            logger.warning(f"Error getting Basketball Reference detailed data: {e}")
            return {}
    
    def get_player_team_assignment(self, player_lookup: str, roster_data: Dict[str, Set[str]] = None) -> str:
        """Find team assignment for a player from roster data."""
        if not roster_data:
            # Query all sources to find team assignment
            season_year = date.today().year if date.today().month >= 10 else date.today().year - 1
            
            # Try ESPN first (most reliable)
            query = """
            SELECT team_abbr
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE player_lookup = @player_lookup
            AND roster_date = (
                SELECT MAX(roster_date) 
                FROM `{project}.nba_raw.espn_team_rosters`
                WHERE season_year = @season_year
            )
            LIMIT 1
            """.format(project=self.project_id)
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
            ])
            
            try:
                results = self.bq_client.query(query, job_config=job_config).to_dataframe()
                if not results.empty:
                    return results.iloc[0]['team_abbr']
            except Exception as e:
                logger.warning(f"Error finding team assignment for {player_lookup}: {e}")
        
        return 'UNK'  # Unknown team
    
    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """Transform roster data into registry records."""
        # Extract filters from raw_data
        season_year = raw_data.get('season_year', date.today().year)
        
        logger.info(f"Processing roster data for season {season_year}")
        
        # Step 1: Get current roster data from all sources
        roster_data = self.get_current_roster_data(season_year)
        
        # Step 2: Get existing registry players
        season_str = self.calculate_season_string(season_year)
        existing_players = self.get_existing_registry_players(season_str)
        
        # Step 3: Find all roster players
        all_roster_players = set()
        for source, players in roster_data.items():
            all_roster_players.update(players)
        
        logger.info(f"Found {len(all_roster_players)} total players across all roster sources")
        
        # Step 4: Detect unknown players (simplified - just log them)
        unknown_players = all_roster_players - existing_players
        if unknown_players:
            logger.info(f"Found {len(unknown_players)} unknown players not in registry: {list(unknown_players)[:10]}{'...' if len(unknown_players) > 10 else ''}")
        
        # Step 5: Create registry records for all roster players
        registry_records = self.aggregate_roster_assignments(roster_data, season_year)
        
        logger.info(f"Created {len(registry_records)} registry records from roster data")
        return registry_records
    
    def _build_registry_for_season_impl(self, season: str, team: str = None) -> Dict:
        """Implementation of season building."""
        logger.info(f"Building roster registry for season {season}" + (f", team {team}" if team else ""))
        
        # Reset tracking for this run
        self.new_players_discovered = set()
        self.players_seen_this_run = set()
        
        # Reset stats
        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set(),
            'unresolved_players_found': 0,
            'alias_resolutions': 0
        }
        
        # Parse season year
        season_year = int(season.split('-')[0])
        
        # Create filter data
        filter_data = {
            'season_year': season_year
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)
        
        result['new_players_discovered'] = list(self.new_players_discovered)
        if self.new_players_discovered:
            logger.info(f"Discovered {len(self.new_players_discovered)} new players from rosters")
        
        logger.info(f"Roster registry build complete for {season}:")
        logger.info(f"  Records processed: {result['rows_processed']}")
        logger.info(f"  Records created: {len(rows)}")
        logger.info(f"  Errors: {len(result.get('errors', []))}")
        
        return {
            'season': season,
            'team_filter': team,
            'records_processed': result['rows_processed'],
            'records_created': len(rows),
            'players_processed': len(rows),  # For roster, each record is one player
            'teams_processed': list(set(row['team_abbr'] for row in rows)) if rows else [],
            'new_players_discovered': result['new_players_discovered'],
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }
    
    def process_daily_rosters(self, season_year: int = None) -> Dict:
        """
        Process daily roster updates.
        
        Main entry point for daily processing after roster scrapers complete.
        """
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:  # Oct-Dec = new season starting
                season_year = date.today().year
            else:  # Jan-Sep = season ending
                season_year = date.today().year - 1
        
        season_str = self.calculate_season_string(season_year)
        logger.info(f"Processing daily rosters for {season_str} season")
        
        return self._build_registry_for_season_impl(season_str)

    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """Build registry from historical roster data (simplified - current season only)."""
        logger.info("Roster processor handles current data only - building for current season")
        
        current_season_year = date.today().year if date.today().month >= 10 else date.today().year - 1
        current_season = self.calculate_season_string(current_season_year)
        
        result = self._build_registry_for_season_impl(current_season)
        
        return {
            'scenario': 'current_roster_processing',
            'seasons_processed': [current_season],
            'total_records_processed': result['records_processed'],
            'total_errors': len(result.get('errors', [])),
            'individual_results': [result],
            'processing_run_id': self.processing_run_id,
            'note': 'Roster processor handles current data only'
        }


# Convenience functions
def process_daily_rosters(season_year: int = None, strategy: str = "merge") -> Dict:
    """Convenience function for daily roster processing."""
    processor = RosterRegistryProcessor(strategy=strategy)
    return processor.process_daily_rosters(season_year)