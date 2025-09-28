#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/roster_registry_processor.py

Roster Registry Processor - COMPLETE IMPLEMENTATION

Maintains the NBA players registry from roster assignment data.
This processor creates registry entries when players join rosters (before games played).

Usage Scenarios:
1. Daily roster updates: Triggered after roster scrapers complete
2. Season start processing: Bulk roster processing for new season
3. Trade/transaction handling: Update registry when players change teams
"""

import logging
from datetime import datetime, date
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
        Aggregate roster data into registry records.
        
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
        
        registry_records = []
        season_str = self.calculate_season_string(season_year)
        
        for player_lookup in all_roster_players:
            details = player_details.get(player_lookup, {})
            team_abbr = details.get('team_abbr', 'UNK')
            sources = details.get('sources', [])
            enhancement = details.get('enhancement_data', {})
            
            # Determine source priority based on data sources
            source_priority = self._determine_source_priority(sources)
            confidence_score = self._calculate_roster_confidence(sources, enhancement)
            
            # Resolve universal player ID
            universal_id = self.resolve_universal_player_id(player_lookup)
            
            # Create registry record
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
            
            # Convert types for BigQuery
            record = self._convert_pandas_types_for_json(record)
            registry_records.append(record)
        
        logger.info(f"Created {len(registry_records)} registry records from roster data")
        return registry_records
    
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
    
    def _determine_source_priority(self, sources: List[str]) -> str:
        """Map data sources to priority level for roster data."""
        # Roster sources have lower priority than gamebook data
        # ESPN is typically most reliable for current rosters
        if 'espn_rosters' in sources:
            return 'roster_espn'
        elif 'nba_player_list' in sources:
            return 'roster_nba_com'
        elif 'basketball_reference' in sources:
            return 'roster_br'
        else:
            return 'roster_unknown'
    
    def _calculate_roster_confidence(self, sources: List[str], enhancement: Dict) -> float:
        """Calculate confidence score for roster assignment."""
        score = 0.5  # Base score for roster data
        
        # Multiple sources increase confidence
        if len(sources) >= 2:
            score += 0.3
        elif len(sources) >= 3:
            score += 0.4
        
        # Having detailed info increases confidence
        if enhancement.get('jersey_number'):
            score += 0.1
        if enhancement.get('position'):
            score += 0.1
        
        return min(score, 1.0)
    
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
    
    def investigate_unknown_players(self, unknown_players: Set[str]) -> List[Dict]:
        """
        Investigate unknown players for potential name changes.
        
        Args:
            unknown_players: Set of player_lookup values not in registry
            
        Returns:
            List of investigation records
        """
        investigations = []
        
        for player_lookup in unknown_players:
            if not self._should_investigate_player(player_lookup):
                continue
            
            # Find team assignment for player
            team_abbr = self.get_player_team_assignment(player_lookup)
            
            # Enhanced alias checking
            alias_check_result = self._check_player_aliases_detailed(player_lookup, team_abbr)
            
            if alias_check_result['found']:
                logger.info(f"Player {player_lookup} found via alias mapping for {team_abbr}")
                continue
            
            # Create investigation using inherited methods
            investigation = self._create_enhanced_investigation(
                player_lookup, 
                team_abbr, 
                enhancement={},  # No Basketball Reference enhancement for roster-only players
                alias_check=alias_check_result
            )
            
            if investigation['confidence_score'] > 0.3:
                investigations.append(investigation)
        
        logger.info(f"Created {len(investigations)} investigations for unknown players")
        return investigations
    
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
        
        # Step 4: Detect unknown players
        unknown_players = all_roster_players - existing_players
        logger.info(f"Found {len(unknown_players)} unknown players not in registry")
        
        # Step 5: Investigate unknown players (if name change detection enabled)
        investigations = []
        if self.enable_name_change_detection and unknown_players:
            investigations = self.investigate_unknown_players(unknown_players)
            
            # Save investigation report
            if investigations:
                investigation_report = {
                    'detection_date': date.today().isoformat(),
                    'processor_type': 'roster_registry_processor',
                    'total_roster_players': len(all_roster_players),
                    'existing_registry_players': len(existing_players),
                    'unknown_players_found': len(unknown_players),
                    'investigations': investigations,
                    'total_investigations': len(investigations)
                }
                self._save_investigation_report(investigation_report)
        
        # Step 6: Create registry records for all roster players
        registry_records = self.aggregate_roster_assignments(roster_data, season_year)
        
        logger.info(f"Created {len(registry_records)} registry records from roster data")
        return registry_records
    
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
        
        logger.info(f"Processing daily rosters for {season_year}-{season_year+1} season")
        
        # Reset tracking
        self.new_players_discovered = set()
        self.players_seen_this_run = set()
        
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
        
        logger.info(f"Daily roster processing complete:")
        logger.info(f"  Records processed: {result['rows_processed']}")
        logger.info(f"  Errors: {len(result.get('errors', []))}")
        
        return {
            'scenario': 'daily_roster_processing',
            'season_year': season_year,
            'records_processed': result['rows_processed'],
            'new_players_discovered': result['new_players_discovered'],
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }


# Convenience functions
def process_daily_rosters(season_year: int = None, strategy: str = "merge") -> Dict:
    """Convenience function for daily roster processing."""
    processor = RosterRegistryProcessor(strategy=strategy)
    return processor.process_daily_rosters(season_year)


def detect_roster_name_changes(season_year: int = None) -> Dict:
    """Convenience function for name change detection only."""
    processor = RosterRegistryProcessor(
        strategy="merge",
        enable_name_change_detection=True
    )
    
    # Create filter data
    filter_data = {
        'season_year': season_year or (date.today().year if date.today().month >= 10 else date.today().year - 1)
    }
    
    # Get roster data and find unknowns
    roster_data = processor.get_current_roster_data(filter_data['season_year'])
    season_str = processor.calculate_season_string(filter_data['season_year'])
    existing_players = processor.get_existing_registry_players(season_str)
    
    all_roster_players = set()
    for source, players in roster_data.items():
        all_roster_players.update(players)
    
    unknown_players = all_roster_players - existing_players
    
    # Run investigations only
    investigations = processor.investigate_unknown_players(unknown_players)
    
    # Save investigation report
    if investigations:
        investigation_report = {
            'detection_date': date.today().isoformat(),
            'processor_type': 'roster_registry_processor_detection_only',
            'total_roster_players': len(all_roster_players),
            'existing_registry_players': len(existing_players),
            'unknown_players_found': len(unknown_players),
            'investigations': investigations,
            'total_investigations': len(investigations)
        }
        processor._save_investigation_report(investigation_report)
    
    return {
        'detection_only': True,
        'investigations_generated': len(investigations),
        'total_roster_players': len(all_roster_players),
        'unknown_players_found': len(unknown_players),
        'processing_run_id': processor.processing_run_id
    }