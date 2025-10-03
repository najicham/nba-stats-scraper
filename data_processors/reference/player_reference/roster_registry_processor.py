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
from typing import Dict, List, Set, Tuple
import pandas as pd
from google.cloud import bigquery

from data_processors.reference.base.registry_processor_base import RegistryProcessorBase
from data_processors.reference.base.name_change_detection_mixin import NameChangeDetectionMixin
from data_processors.reference.base.database_strategies import DatabaseStrategiesMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

# Team abbreviation normalization
# Basketball Reference uses legacy codes that need to be mapped to official NBA codes
TEAM_ABBR_NORMALIZATION = {
    'BRK': 'BKN',  # Brooklyn Nets
    'CHO': 'CHA',  # Charlotte Hornets  
    'PHO': 'PHX',  # Phoenix Suns
}

def normalize_team_abbr(team_abbr: str) -> str:
    """
    Normalize team abbreviation to official NBA code.
    
    Basketball Reference uses some legacy team codes that differ from
    official NBA abbreviations. This function maps them to the standard codes.
    
    Args:
        team_abbr: Team abbreviation (may be legacy code)
        
    Returns:
        Normalized NBA team abbreviation
    """
    normalized = TEAM_ABBR_NORMALIZATION.get(team_abbr, team_abbr)
    if normalized != team_abbr:
        logger.debug(f"Normalized team code: {team_abbr} → {normalized}")
    return normalized


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
        total_players = sum(len(players) for players in roster_sources.values())
        for source, players in roster_sources.items():
            logger.info(f"{source}: {len(players)} players")
        
        # Check for concerning data issues
        if total_players == 0:
            try:
                notify_warning(
                    title="No Roster Data Found",
                    message=f"No roster data found for {season_year}-{season_year+1} season from any source",
                    details={
                        'season_year': season_year,
                        'sources_checked': list(roster_sources.keys()),
                        'processor': 'roster_registry'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
        elif total_players < 400:  # NBA typically has 450+ players
            try:
                notify_warning(
                    title="Low Roster Data Count",
                    message=f"Found only {total_players} total players for {season_year}-{season_year+1} season (expected 450+)",
                    details={
                        'season_year': season_year,
                        'total_players': total_players,
                        'source_counts': {k: len(v) for k, v in roster_sources.items()},
                        'processor': 'roster_registry'
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
        
        return roster_sources
    
    def _get_espn_roster_players(self, season_year: int) -> Set[str]:
        """Get current roster players from ESPN team rosters."""
        query = """
        SELECT DISTINCT player_lookup, team_abbr, jersey_number, position
        FROM `{project}.nba_raw.espn_team_rosters`
        WHERE roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)  -- Partition filter
        AND roster_date = (
            SELECT MAX(roster_date) 
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE season_year = @season_year
            AND roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
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
            try:
                notify_error(
                    title="ESPN Roster Query Failed",
                    message=f"Failed to query ESPN roster data: {str(e)}",
                    details={
                        'season_year': season_year,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
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
            try:
                notify_error(
                    title="NBA.com Player List Query Failed",
                    message=f"Failed to query NBA.com player list: {str(e)}",
                    details={
                        'season_year': season_year,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
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
            try:
                notify_error(
                    title="Basketball Reference Query Failed",
                    message=f"Failed to query Basketball Reference roster data: {str(e)}",
                    details={
                        'season_year': season_year,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
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
            try:
                notify_error(
                    title="Registry Query Failed",
                    message=f"Failed to query existing registry players: {str(e)}",
                    details={
                        'season': season,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return set()
    
    def aggregate_roster_assignments(self, roster_data: Dict[str, Set[str]], season_year: int) -> List[Dict]:
        """
        Aggregate roster data into registry records with NBA.com validation.
        Now validates BR/ESPN players against NBA.com canonical (player, team) combinations.
        
        Args:
            roster_data: Dict of roster sources and their players
            season_year: NBA season starting year
            
        Returns:
            List of registry record dictionaries
        """
        logger.info("Aggregating roster assignments into registry records...")
        
        try:
            # Build NBA.com canonical set upfront (now returns player-team tuples)
            nba_canonical_set = self._get_nba_canonical_set(season_year)
            fallback_mode = len(nba_canonical_set) == 0
            
            if fallback_mode:
                logger.warning("⚠️ Running in NO VALIDATION mode - no canonical set available")
            else:
                logger.info(f"Using {len(nba_canonical_set)} NBA.com player-team combinations as canonical set")
            
            # Source mapping for priority
            source_map = {
                'espn_rosters': 'roster_espn',
                'basketball_reference': 'roster_br',
                'nba_player_list': 'roster_nba_com'
            }
            
            # Combine all roster sources and collect detailed data
            all_roster_players = set()
            player_team_details = {}  # (player_lookup, team_abbr) -> {sources, enhancement_data, source_priority}
            unvalidated_players = []  # BR/ESPN players not in canonical set
            
            for source, players in roster_data.items():
                all_roster_players.update(players)
                
                # Get detailed data for each source
                detailed_data = self._get_detailed_roster_data(source, season_year)
                
                for player_lookup, details in detailed_data.items():
                    team_abbr = details['team_abbr']
                    key = (player_lookup, team_abbr)
                    
                    # Validation logic - STRICTER: check player-team combination
                    if source == 'nba_player_list':
                        # NBA.com always goes through with nba_com priority
                        should_create_record = True
                        actual_source_priority = 'roster_nba_com'
                        
                    elif source in ['espn_rosters', 'basketball_reference']:
                        if fallback_mode:
                            # No canonical set - allow through with original source
                            should_create_record = True
                            actual_source_priority = source_map.get(source, 'roster_unknown')
                            logger.debug(f"⚠️ {source}: {player_lookup} on {team_abbr} accepted (fallback mode - no validation)")
                            
                        elif key in nba_canonical_set:  # CHANGED: Check (player, team) tuple
                            # Validated by NBA.com - use NBA.com as source priority
                            should_create_record = True
                            actual_source_priority = 'roster_nba_com'
                            logger.debug(f"✓ {source}: {player_lookup} on {team_abbr} validated against NBA.com canonical set")
                            
                        elif self._check_player_aliases(player_lookup, team_abbr):
                            # Validated via alias - use NBA.com as source priority
                            should_create_record = True
                            actual_source_priority = 'roster_nba_com'
                            logger.debug(f"✓ {source}: {player_lookup} on {team_abbr} validated via alias")
                            
                        else:
                            # Not validated - create unresolved, don't create registry record yet
                            should_create_record = False
                            unvalidated_players.append({
                                'source': source,
                                'player_lookup': player_lookup,
                                'team_abbr': team_abbr,
                                'display_name': details.get('player_full_name', player_lookup.title())
                            })
                            logger.debug(f"✗ {source}: {player_lookup} on {team_abbr} not in canonical set - flagging for review")
                    else:
                        # Unknown source
                        should_create_record = True
                        actual_source_priority = source_map.get(source, 'roster_unknown')
                    
                    # Only add to player_team_details if validated
                    if should_create_record:
                        if key not in player_team_details:
                            player_team_details[key] = {
                                'sources': [],
                                'enhancement_data': {},
                                'source_priority': actual_source_priority
                            }
                        
                        player_team_details[key]['sources'].append(source)
                        
                        # Merge enhancement data (jersey_number, position, etc.)
                        if 'jersey_number' in details and details['jersey_number']:
                            player_team_details[key]['enhancement_data']['jersey_number'] = details['jersey_number']
                        if 'position' in details and details['position']:
                            player_team_details[key]['enhancement_data']['position'] = details['position']
                        if 'player_full_name' in details and details['player_full_name']:
                            player_team_details[key]['enhancement_data']['player_full_name'] = details['player_full_name']
            
            # Create unresolved records for unvalidated players
            if unvalidated_players:
                logger.warning(f"Found {len(unvalidated_players)} player-team combinations not in NBA.com canonical set")
                self._create_unvalidated_records(unvalidated_players, season_year)
            
            # BULK RESOLUTION: Get all universal IDs in one operation
            unique_player_lookups = list({lookup for (lookup, team) in player_team_details.keys()})
            logger.info(f"Performing bulk universal ID resolution for {len(unique_player_lookups)} validated roster players")
            
            universal_id_mappings = self.bulk_resolve_universal_player_ids(unique_player_lookups)
            
            registry_records = []
            season_str = self.calculate_season_string(season_year)
            
            # Auto-detect and create suffix aliases (only for validated players)
            try:
                aliases_created = self._auto_create_suffix_aliases(player_team_details)
                if aliases_created > 0:
                    logger.info(f"Auto-created {aliases_created} suffix aliases for source matching")
            except Exception as e:
                logger.warning(f"Failed to auto-create aliases (non-fatal): {e}")
                
            logger.info(f"Creating records for {len(player_team_details)} validated player-team combinations")
            
            # Iterate over validated players
            for (player_lookup, team_abbr), details in player_team_details.items():
                sources = details.get('sources', [])
                enhancement = details.get('enhancement_data', {})
                source_priority = details.get('source_priority', 'roster_unknown')
                
                # Determine confidence with dynamic logic
                _, confidence_score = self._determine_roster_source_priority_and_confidence(
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
                    'last_roster_update': datetime.now(),
                    
                    # Source metadata - use determined priority (all validated = nba_com)
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
            
            logger.info(f"Created {len(registry_records)} registry records from validated roster data")
            
            # Log if any players appear on multiple teams (trades)
            player_team_counts = {}
            for (player_lookup, team_abbr) in player_team_details.keys():
                player_team_counts[player_lookup] = player_team_counts.get(player_lookup, 0) + 1
            
            traded_players = {p: count for p, count in player_team_counts.items() if count > 1}
            if traded_players:
                logger.info(f"Detected {len(traded_players)} players on multiple teams (trades): {list(traded_players.keys())[:5]}...")
            
            return registry_records
            
        except Exception as e:
            logger.error(f"Failed to aggregate roster assignments: {e}")
            try:
                notify_error(
                    title="Roster Aggregation Failed",
                    message=f"Failed to aggregate roster assignments: {str(e)}",
                    details={
                        'season_year': season_year,
                        'error_type': type(e).__name__,
                        'players_attempted': len(all_roster_players) if 'all_roster_players' in locals() else 0,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
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
        WHERE roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)  -- Partition filter
        AND roster_date = (
            SELECT MAX(roster_date) 
            FROM `{project}.nba_raw.espn_team_rosters`
            WHERE season_year = @season_year
            AND roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
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
                # Normalize Basketball Reference team codes to official NBA codes
                team_abbr = normalize_team_abbr(row['team_abbr'])
                
                detailed_data[row['player_lookup']] = {
                    'player_full_name': row['player_full_name'],
                    'team_abbr': team_abbr,  # Use normalized code
                    'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                    'position': row['position'] if pd.notna(row['position']) else None
                }
            
            return detailed_data
        except Exception as e:
            logger.warning(f"Error getting Basketball Reference detailed data: {e}")
            return {}
        
    def _get_nba_canonical_set(self, season_year: int) -> Set[Tuple[str, str]]:
        """
        Get canonical (player, team) combinations from NBA.com (current + historical registry records).
        Falls back to all registry sources if NBA.com unavailable.
        
        Returns set of tuples: (player_lookup, team_abbr)
        """
        canonical_combos = set()
        season_str = self.calculate_season_string(season_year)
        nba_players_found = False
        
        # 1. Get NBA.com players from current scrape
        nba_query = """
        SELECT DISTINCT 
            player_lookup, 
            team_abbr,
            player_full_name as display_name
        FROM `{project}.nba_raw.nbac_player_list_current`
        WHERE is_active = TRUE
        AND season_year = @season_year
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            nba_current = self.bq_client.query(nba_query, job_config=job_config).to_dataframe()
            if not nba_current.empty:
                for _, row in nba_current.iterrows():
                    canonical_combos.add((row['player_lookup'], row['team_abbr']))
                nba_players_found = True
                logger.info(f"Loaded {len(canonical_combos)} player-team combinations from NBA.com current scrape")
            else:
                logger.warning("NBA.com current scrape returned no players")
        except Exception as e:
            logger.warning(f"Error loading NBA.com current players: {e}")
        
        # 2. Get NBA.com players from existing registry
        registry_nba_query = """
        SELECT DISTINCT 
            player_lookup,
            team_abbr,
            player_name as display_name
        FROM `{project}.{table_name}`
        WHERE season = @season
        AND source_priority = 'roster_nba_com'
        """.format(project=self.project_id, table_name=self.table_name)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season_str)
        ])
        
        try:
            registry_nba = self.bq_client.query(registry_nba_query, job_config=job_config).to_dataframe()
            if not registry_nba.empty:
                original_count = len(canonical_combos)
                for _, row in registry_nba.iterrows():
                    canonical_combos.add((row['player_lookup'], row['team_abbr']))
                nba_players_found = True
                logger.info(f"Added {len(canonical_combos) - original_count} player-team combinations from registry (total: {len(canonical_combos)})")
            else:
                logger.warning("No NBA.com players found in existing registry")
        except Exception as e:
            logger.warning(f"Error loading registry NBA.com players: {e}")
        
        # 3. FALLBACK: If no NBA.com data available, use ALL registry sources
        if not nba_players_found or len(canonical_combos) == 0:
            logger.warning("⚠️ NBA.com data unavailable - falling back to existing registry (all sources)")
            
            fallback_query = """
            SELECT DISTINCT 
                player_lookup,
                team_abbr,
                player_name as display_name,
                source_priority
            FROM `{project}.{table_name}`
            WHERE season = @season
            """.format(project=self.project_id, table_name=self.table_name)
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("season", "STRING", season_str)
            ])
            
            try:
                all_registry = self.bq_client.query(fallback_query, job_config=job_config).to_dataframe()
                if not all_registry.empty:
                    for _, row in all_registry.iterrows():
                        canonical_combos.add((row['player_lookup'], row['team_abbr']))
                    logger.warning(f"Using fallback canonical set: {len(canonical_combos)} player-team combinations from all sources")
                    
                    # Send notification about fallback mode
                    try:
                        notify_warning(
                            title="Roster Processor Using Fallback Mode",
                            message=f"NBA.com data unavailable - using existing registry as canonical set ({len(canonical_combos)} player-team combinations)",
                            details={
                                'season': season_str,
                                'canonical_combos_count': len(canonical_combos),
                                'fallback_mode': True,
                                'processor': 'roster_registry'
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                else:
                    logger.error("⚠️ No canonical set available - first run with no data!")
            except Exception as e:
                logger.error(f"Error loading fallback registry data: {e}")
        
        return canonical_combos
        
    def _auto_create_suffix_aliases(self, player_team_details: Dict[Tuple[str, str], Dict]) -> int:
        """
        Automatically detect and create aliases for suffix mismatches between sources.
        
        IMPORTANT: Only creates aliases when players are on the SAME team.
        Cross-team suffix mismatches are flagged as unresolved (father/son, different people).
        
        Args:
            player_team_details: Dict with (player_lookup, team_abbr) keys
            
        Returns:
            Number of aliases created
        """
        suffixes = ['jr', 'sr', 'ii', 'iii', 'iv', 'v']
        aliases_to_create = []
        unresolved_to_create = []
        
        # Build reverse lookup: base_name -> {full_names_with_suffixes}
        base_to_variants = {}
        for (player_lookup, team_abbr), details in player_team_details.items():
            base = player_lookup
            detected_suffix = None
            
            for suffix in suffixes:
                if player_lookup.endswith(suffix):
                    base = player_lookup[:-len(suffix)]
                    detected_suffix = suffix
                    break
            
            if base not in base_to_variants:
                base_to_variants[base] = []
            base_to_variants[base].append({
                'lookup': player_lookup,
                'suffix': detected_suffix,
                'team': team_abbr,
                'sources': details.get('sources', []),
                'display_name': details.get('enhancement_data', {}).get('player_full_name', player_lookup.title())
            })
        
        # Find bases with multiple variants (suffix mismatches)
        for base, variants in base_to_variants.items():
            if len(variants) > 1:
                # NEW: Check if all variants are on the same team
                teams = set(v['team'] for v in variants)
                
                if len(teams) == 1:
                    # SAME TEAM → Safe to auto-alias
                    canonical = None
                    for variant in variants:
                        if 'nba_player_list' in variant['sources']:
                            canonical = variant
                            break
                    
                    if not canonical:
                        canonical = next((v for v in variants if v['suffix']), variants[0])
                    
                    # Create aliases for all non-canonical variants
                    for variant in variants:
                        if variant['lookup'] != canonical['lookup']:
                            aliases_to_create.append({
                                'alias_lookup': variant['lookup'],
                                'nba_canonical_lookup': canonical['lookup'],
                                'alias_display': variant['display_name'],
                                'nba_canonical_display': canonical['display_name'],
                                'alias_type': 'suffix_difference',
                                'alias_source': 'auto_detected',
                                'is_active': True,
                                'notes': f"Auto-detected suffix mismatch: '{variant['lookup']}' → '{canonical['lookup']}' (same team: {variant['team']})",
                                'created_by': self.processing_run_id,
                                'created_at': datetime.now(),
                                'processed_at': datetime.now()
                            })
                            
                else:
                    # DIFFERENT TEAMS → Flag as unresolved (could be father/son or different people)
                    variant_details = [f"{v['lookup']} ({v['team']})" for v in variants]
                    logger.warning(f"Cross-team suffix mismatch detected for base '{base}': {variant_details}")
                    
                    # Create unresolved record for each variant
                    for variant in variants:
                        # Determine which source this variant came from
                        primary_source = variant['sources'][0] if variant['sources'] else 'unknown'
                        source_map = {
                            'espn_rosters': 'espn',
                            'nba_player_list': 'nba_com',
                            'basketball_reference': 'br'
                        }
                        source_name = source_map.get(primary_source, primary_source)
                        
                        unresolved_to_create.append({
                            'source': source_name,
                            'original_name': variant['display_name'],
                            'normalized_lookup': variant['lookup'],
                            'first_seen_date': date.today(),
                            'last_seen_date': date.today(),
                            'team_abbr': variant['team'],
                            'season': self.calculate_season_string(
                                date.today().year if date.today().month >= 10 else date.today().year - 1
                            ),
                            'occurrences': 1,
                            'example_games': [],  # ✅ Empty array, not None
                            'status': 'pending',
                            'resolution_type': None,
                            'resolved_to_name': None,
                            'notes': f"Cross-team suffix mismatch: base '{base}' appears on multiple teams {list(teams)}. Could be father/son (e.g., Gary Payton vs Gary Payton II) or different people. Needs manual review before creating alias.",
                            'reviewed_by': None,
                            'reviewed_at': None,
                            # ✅ Removed created_by field
                            'created_at': datetime.now(),
                            'processed_at': datetime.now()
                        })
        
        # Insert aliases and unresolved records
        if aliases_to_create:
            self._insert_aliases(aliases_to_create)
            logger.info(f"Auto-created {len(aliases_to_create)} suffix aliases (same-team only)")
        
        if unresolved_to_create:
            self._insert_unresolved_names(unresolved_to_create)
            logger.warning(f"Created {len(unresolved_to_create)} unresolved records for cross-team suffix mismatches (manual review required)")
        
        return len(aliases_to_create)
    
    def _create_unvalidated_records(self, unvalidated_players: List[Dict], season_year: int) -> None:
        """Create unresolved records for players not in NBA.com canonical set."""
        unresolved_records = []
        
        source_map = {
            'espn_rosters': 'espn',
            'basketball_reference': 'br',
            'nba_player_list': 'nba_com'
        }
        
        for player in unvalidated_players:
            source_name = source_map.get(player['source'], player['source'])
            
            unresolved_records.append({
                'source': source_name,
                'original_name': player['display_name'],
                'normalized_lookup': player['player_lookup'],
                'first_seen_date': date.today(),
                'last_seen_date': date.today(),
                'team_abbr': player['team_abbr'],
                'season': self.calculate_season_string(season_year),
                'occurrences': 1,
                'example_games': [],
                'status': 'pending',
                'resolution_type': None,
                'resolved_to_name': None,
                'notes': f"Player found in {player['source']} but not in NBA.com canonical set. Needs validation: could be typo, formatting difference, or legitimate new player not yet in NBA.com data.",
                'reviewed_by': None,
                'reviewed_at': None,
                'created_at': datetime.now(),
                'processed_at': datetime.now()
            })
        
        if unresolved_records:
            try:
                self._insert_unresolved_names(unresolved_records)
                logger.info(f"Created {len(unresolved_records)} unresolved records for unvalidated players")
            except Exception as e:
                logger.error(f"Failed to create unvalidated player records: {e}")

    def _insert_aliases(self, alias_records: List[Dict]) -> None:
        """Insert alias records into player_aliases table."""
        if not alias_records:
            return
        
        table_id = f"{self.project_id}.{self.alias_table_name}"
        
        try:
            # Check for existing aliases to avoid duplicates
            existing_query = f"""
            SELECT alias_lookup, nba_canonical_lookup
            FROM `{table_id}`
            WHERE alias_lookup IN UNNEST(@alias_lookups)
            """
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("alias_lookups", "STRING", 
                    [r['alias_lookup'] for r in alias_records])
            ])
            
            existing_df = self.bq_client.query(existing_query, job_config=job_config).to_dataframe()
            existing_aliases = set(existing_df['alias_lookup']) if not existing_df.empty else set()
            
            # Filter out existing
            new_aliases = [r for r in alias_records if r['alias_lookup'] not in existing_aliases]
            
            if not new_aliases:
                logger.info("All aliases already exist, skipping insertion")
                return
            
            # Convert types for BigQuery
            processed_aliases = []
            for r in new_aliases:
                converted = self._convert_pandas_types_for_json(r)
                # Ensure is_active is a proper boolean
                if 'is_active' in converted:
                    converted['is_active'] = bool(converted['is_active'])
                processed_aliases.append(converted)
            
            # Insert
            errors = self.bq_client.insert_rows_json(table_id, processed_aliases)
            
            if errors:
                logger.error(f"Errors inserting aliases: {errors}")
            else:
                logger.info(f"Successfully inserted {len(new_aliases)} new aliases")
                
        except Exception as e:
            logger.error(f"Failed to insert aliases: {e}")
            # Don't raise - alias creation failure shouldn't block roster processing

    def _insert_unresolved_names(self, unresolved_records: List[Dict]) -> None:
        """Insert unresolved player name records for manual review."""
        if not unresolved_records:
            return
        
        # Convert to list if needed (defensive)
        if not isinstance(unresolved_records, list):
            unresolved_records = list(unresolved_records)
        
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        
        try:
            # Check for existing unresolved records
            existing_query = f"""
            SELECT normalized_lookup, team_abbr, season, occurrences
            FROM `{table_id}`
            WHERE normalized_lookup IN UNNEST(@lookups)
            AND status = 'pending'
            """
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("lookups", "STRING", 
                    [r['normalized_lookup'] for r in unresolved_records])
            ])
            
            existing_df = self.bq_client.query(existing_query, job_config=job_config).to_dataframe()
            
            # Build map of existing records (defensive - check length explicitly)
            existing_map = {}
            if len(existing_df) > 0:  # Changed from: if not existing_df.empty
                for _, row in existing_df.iterrows():
                    key = (row['normalized_lookup'], row['team_abbr'], row['season'])
                    existing_map[key] = row['occurrences']
            
            # Separate into new vs update (use Python lists explicitly)
            new_unresolved = []
            updates_needed = []
            
            for r in unresolved_records:
                key = (r['normalized_lookup'], r['team_abbr'], r['season'])
                
                if key in existing_map:
                    # EXISTS - need to increment occurrences
                    updates_needed.append({
                        'normalized_lookup': r['normalized_lookup'],
                        'team_abbr': r['team_abbr'],
                        'season': r['season'],
                        'new_occurrences': existing_map[key] + 1,
                        'last_seen_date': r['last_seen_date']
                    })
                else:
                    # NEW - insert
                    new_unresolved.append(r)
            
            # Insert new records (check length explicitly)
            if len(new_unresolved) > 0:  # Changed from: if new_unresolved
                processed_unresolved = []
                for r in new_unresolved:
                    converted = self._convert_pandas_types_for_json(r)
                    # Ensure example_games is a plain Python list
                    if 'example_games' in converted:
                        eg = converted['example_games']
                        if eg is None:
                            converted['example_games'] = []
                        elif not isinstance(eg, list):
                            converted['example_games'] = list(eg) if hasattr(eg, '__iter__') else []
                        else:
                            converted['example_games'] = eg
                    processed_unresolved.append(converted)
                
                errors = self.bq_client.insert_rows_json(table_id, processed_unresolved)
                if errors:
                    logger.error(f"Errors inserting unresolved records: {errors}")
                else:
                    logger.info(f"Inserted {len(new_unresolved)} new unresolved records")
            
            # Update existing records (check length explicitly)
            if len(updates_needed) > 0:
                successful_updates = 0
                for update in updates_needed:
                    update_query = f"""
                    UPDATE `{table_id}`
                    SET 
                        occurrences = @new_occurrences,
                        last_seen_date = @last_seen_date,
                        processed_at = CURRENT_TIMESTAMP()
                    WHERE normalized_lookup = @normalized_lookup
                    AND team_abbr = @team_abbr
                    AND season = @season
                    AND status = 'pending'
                    """
                    
                    job_config = bigquery.QueryJobConfig(query_parameters=[
                        bigquery.ScalarQueryParameter("normalized_lookup", "STRING", update['normalized_lookup']),
                        bigquery.ScalarQueryParameter("team_abbr", "STRING", update['team_abbr']),
                        bigquery.ScalarQueryParameter("season", "STRING", update['season']),
                        bigquery.ScalarQueryParameter("new_occurrences", "INT64", update['new_occurrences']),
                        bigquery.ScalarQueryParameter("last_seen_date", "DATE", update['last_seen_date'])
                    ])
                    
                    try:
                        self.bq_client.query(update_query, job_config=job_config).result()
                        successful_updates += 1
                    except Exception as e:
                        error_msg = str(e).lower()
                        if 'streaming buffer' in error_msg:
                            logger.debug(f"Skipping UPDATE for {update['normalized_lookup']} on {update['team_abbr']} - record in streaming buffer (will be updated on next run after ~90 min)")
                        else:
                            logger.warning(f"Failed to update occurrence count for {update['normalized_lookup']} on {update['team_abbr']}: {e}")
                
                if successful_updates > 0:
                    logger.info(f"Updated {successful_updates} existing unresolved records (incremented occurrences)")
                if successful_updates < len(updates_needed):
                    logger.info(f"Skipped {len(updates_needed) - successful_updates} updates due to streaming buffer (expected behavior, will succeed on future runs)")
                
        except Exception as e:
            logger.error(f"Failed to insert/update unresolved records: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")  # Added for debugging
    
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
        try:
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
            
            # Step 4: Detect unknown players and send notification if significant
            unknown_players = all_roster_players - existing_players
            if unknown_players:
                logger.info(f"Found {len(unknown_players)} unknown players not in registry: {list(unknown_players)[:10]}{'...' if len(unknown_players) > 10 else ''}")
                
                # Send notification if many unknown players (might indicate new season or data issue)
                if len(unknown_players) > 50:
                    try:
                        notify_warning(
                            title="High Unknown Player Count in Rosters",
                            message=f"Found {len(unknown_players)} players in rosters not in registry for {season_str}",
                            details={
                                'season': season_str,
                                'unknown_count': len(unknown_players),
                                'total_roster_players': len(all_roster_players),
                                'existing_in_registry': len(existing_players),
                                'sample_unknown': list(unknown_players)[:20],
                                'processor': 'roster_registry'
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
                elif len(unknown_players) > 0:
                    # Info notification for new players (normal operation)
                    try:
                        notify_info(
                            title="New Players Detected in Rosters",
                            message=f"Found {len(unknown_players)} new players in roster data for {season_str}",
                            details={
                                'season': season_str,
                                'new_player_count': len(unknown_players),
                                'sample_players': list(unknown_players)[:10],
                                'processor': 'roster_registry'
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
            
            # Step 5: Create registry records for all roster players
            registry_records = self.aggregate_roster_assignments(roster_data, season_year)
            
            logger.info(f"Created {len(registry_records)} registry records from roster data")
            return registry_records
            
        except Exception as e:
            logger.error(f"Transform data failed: {e}")
            try:
                notify_error(
                    title="Roster Registry Transform Failed",
                    message=f"Failed to transform roster data: {str(e)}",
                    details={
                        'season_year': raw_data.get('season_year') if raw_data else None,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def _build_registry_for_season_impl(self, season: str, team: str = None) -> Dict:
        """Implementation of season building."""
        logger.info(f"Building roster registry for season {season}" + (f", team {team}" if team else ""))
        
        try:
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
            
            # Transform and save
            rows = self.transform_data(filter_data)
            result = self.save_registry_data(rows)
            
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
            
        except Exception as e:
            logger.error(f"Failed to build roster registry for {season}: {e}")
            try:
                notify_error(
                    title="Roster Registry Build Failed",
                    message=f"Failed to build roster registry for season {season}: {str(e)}",
                    details={
                        'season': season,
                        'team_filter': team,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
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
        
        try:
            result = self._build_registry_for_season_impl(season_str)
            
            # Send success notification with summary
            try:
                notify_info(
                    title="Daily Roster Processing Complete",
                    message=f"Successfully processed daily rosters for {season_str} season",
                    details={
                        'season': season_str,
                        'records_processed': result['records_processed'],
                        'players_processed': result['players_processed'],
                        'new_players_discovered': len(result.get('new_players_discovered', [])),
                        'errors': len(result.get('errors', [])),
                        'processor': 'roster_registry',
                        'processing_run_id': self.processing_run_id
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Daily roster processing failed: {e}")
            try:
                notify_error(
                    title="Daily Roster Processing Failed",
                    message=f"Failed to process daily rosters for {season_str}: {str(e)}",
                    details={
                        'season': season_str,
                        'season_year': season_year,
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """Build registry from historical roster data (simplified - current season only)."""
        logger.info("Roster processor handles current data only - building for current season")
        
        try:
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
            
        except Exception as e:
            logger.error(f"Historical registry build failed: {e}")
            try:
                notify_error(
                    title="Historical Roster Registry Build Failed",
                    message=f"Failed to build historical roster registry: {str(e)}",
                    details={
                        'error_type': type(e).__name__,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise


# Convenience functions
def process_daily_rosters(season_year: int = None, strategy: str = "merge") -> Dict:
    """Convenience function for daily roster processing."""
    processor = RosterRegistryProcessor(strategy=strategy)
    return processor.process_daily_rosters(season_year)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process roster registry")
    parser.add_argument("--season-year", type=int, help="NBA season starting year (e.g., 2025 for 2025-26)")
    parser.add_argument("--strategy", default="merge", choices=["merge", "replace", "append"], 
                        help="Database strategy")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Create processor
    processor = RosterRegistryProcessor(strategy=args.strategy)
    
    # Run daily roster processing
    result = processor.process_daily_rosters(season_year=args.season_year)
    
    print(f"\n{'='*60}")
    print(f"✅ SUCCESS")
    print(f"{'='*60}")
    print(f"Season: {result['season']}")
    print(f"Records processed: {result['records_processed']}")
    print(f"Players processed: {result['players_processed']}")
    print(f"New players discovered: {len(result.get('new_players_discovered', []))}")
    print(f"Errors: {len(result.get('errors', []))}")
    print(f"{'='*60}")
    