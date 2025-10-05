#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/roster_registry_processor.py

Roster Registry Processor - With Complete Data Protection

Maintains the NBA players registry from roster assignment data.
Enhanced with:
- Temporal ordering protection
- Season protection (current season only)
- Staleness detection
- Activity date tracking
- Team assignment authority rules
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Set, Tuple
import pandas as pd
from google.cloud import bigquery
import uuid

from data_processors.reference.base.registry_processor_base import RegistryProcessorBase, TemporalOrderingError
from data_processors.reference.base.name_change_detection_mixin import NameChangeDetectionMixin
from data_processors.reference.base.database_strategies import DatabaseStrategiesMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

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
        """Get current roster players from all roster sources."""
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:
                season_year = date.today().year
            else:
                season_year = date.today().year - 1
        
        logger.info(f"Getting current roster data for {season_year}-{season_year+1} season")
        
        roster_sources = {
            'espn_rosters': self._get_espn_roster_players(season_year),
            'nba_player_list': self._get_nba_official_players(season_year), 
            'basketball_reference': self._get_basketball_reference_players(season_year)
        }
        
        total_players = sum(len(players) for players in roster_sources.values())
        for source, players in roster_sources.items():
            logger.info(f"{source}: {len(players)} players")
        
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
        elif total_players < 400:
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
        WHERE roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
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
    
    def aggregate_roster_assignments(self, roster_data: Dict[str, Set[str]], season_year: int, 
                                    data_date: date, allow_backfill: bool = False) -> Tuple[List[Dict], Dict]:
        """
        Aggregate roster data into registry records with NBA.com validation and staleness checking.
        Now includes freshness and authority checks.
        
        Args:
            roster_data: Dict of roster sources and their players
            season_year: NBA season starting year
            data_date: Date this roster data represents
            allow_backfill: If True, skip freshness checks for historical data
        
        Returns:
            Tuple of (registry records, validation info dict)
        """
        import time
        start_time = time.time()
        logger.info("Aggregating roster assignments into registry records...")
        
        try:
            # Build NBA.com canonical set with freshness check
            canonical_start = time.time()
            nba_canonical_set, validation_info = self._get_nba_canonical_set(season_year, data_date)
            canonical_duration = time.time() - canonical_start
            logger.info(f"Built NBA.com canonical set in {canonical_duration:.2f}s")
            
            fallback_mode = len(nba_canonical_set) == 0
            
            if validation_info['validation_mode'] == 'none':
                logger.warning(f"⚠️ Running in NO VALIDATION mode - {validation_info.get('validation_skipped_reason')}")
            else:
                logger.info(f"Using {len(nba_canonical_set)} NBA.com player-team combinations as canonical set")
            
            # Source mapping
            source_map = {
                'espn_rosters': 'roster_espn',
                'basketball_reference': 'roster_br',
                'nba_player_list': 'roster_nba_com'
            }
            
            # Combine all roster sources and collect detailed data
            all_roster_players = set()
            player_team_details = {}
            unvalidated_players = []
            
            for source, players in roster_data.items():
                all_roster_players.update(players)
                detailed_data = self._get_detailed_roster_data(source, season_year)
                
                for player_lookup, details in detailed_data.items():
                    team_abbr = details['team_abbr']
                    key = (player_lookup, team_abbr)
                    
                    # Validation logic
                    if source == 'nba_player_list':
                        should_create_record = True
                        actual_source_priority = 'roster_nba_com'
                    elif source in ['espn_rosters', 'basketball_reference']:
                        if validation_info['validation_mode'] == 'none':
                            should_create_record = True
                            actual_source_priority = source_map.get(source, 'roster_unknown')
                            logger.debug(f"⚠️ {source}: {player_lookup} on {team_abbr} accepted (no validation mode)")
                        elif key in nba_canonical_set:
                            should_create_record = True
                            actual_source_priority = 'roster_nba_com'
                            logger.debug(f"✓ {source}: {player_lookup} on {team_abbr} validated")
                        elif self._check_player_aliases(player_lookup, team_abbr):
                            should_create_record = True
                            actual_source_priority = 'roster_nba_com'
                            logger.debug(f"✓ {source}: {player_lookup} on {team_abbr} validated via alias")
                        else:
                            should_create_record = False
                            unvalidated_players.append({
                                'source': source,
                                'player_lookup': player_lookup,
                                'team_abbr': team_abbr,
                                'display_name': details.get('player_full_name', player_lookup.title())
                            })
                            logger.debug(f"✗ {source}: {player_lookup} on {team_abbr} not in canonical set")
                    else:
                        should_create_record = True
                        actual_source_priority = source_map.get(source, 'roster_unknown')
                    
                    if should_create_record:
                        if key not in player_team_details:
                            player_team_details[key] = {
                                'sources': [],
                                'enhancement_data': {},
                                'source_priority': actual_source_priority
                            }
                        
                        player_team_details[key]['sources'].append(source)
                        
                        if 'jersey_number' in details and details['jersey_number']:
                            player_team_details[key]['enhancement_data']['jersey_number'] = details['jersey_number']
                        if 'position' in details and details['position']:
                            player_team_details[key]['enhancement_data']['position'] = details['position']
                        if 'player_full_name' in details and details['player_full_name']:
                            player_team_details[key]['enhancement_data']['player_full_name'] = details['player_full_name']
            
            # Create unresolved records
            if unvalidated_players:
                logger.warning(f"Found {len(unvalidated_players)} player-team combinations not in NBA.com canonical set")
                self._create_unvalidated_records(unvalidated_players, season_year)
            
            # BULK RESOLUTION
            unique_player_lookups = list({lookup for (lookup, team) in player_team_details.keys()})
            logger.info(f"Performing bulk universal ID resolution for {len(unique_player_lookups)} validated roster players")
            
            universal_id_mappings = self.bulk_resolve_universal_player_ids(unique_player_lookups)
            
            registry_records = []
            season_str = self.calculate_season_string(season_year)
            
            # Auto-create suffix aliases
            try:
                aliases_created = self._auto_create_suffix_aliases(player_team_details)
                if aliases_created > 0:
                    logger.info(f"Auto-created {aliases_created} suffix aliases for source matching")
            except Exception as e:
                logger.warning(f"Failed to auto-create aliases (non-fatal): {e}")
                
            logger.info(f"Creating records for {len(player_team_details)} validated player-team combinations")
            
            # ===================================================================
            # OPTIMIZATION: Batch fetch all existing records for this season
            # ===================================================================
            batch_fetch_start = time.time()
            existing_records_query = f"""
            SELECT 
                player_lookup,
                team_abbr,
                games_played,
                last_processor,
                last_gamebook_activity_date,
                last_roster_activity_date,
                jersey_number,
                position,
                source_priority,
                processed_at
            FROM `{self.project_id}.{self.table_name}`
            WHERE season = @season
            """
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("season", "STRING", season_str)
            ])
            
            try:
                existing_records_df = self.bq_client.query(existing_records_query, job_config=job_config).to_dataframe()
                
                # Build lookup dictionary for O(1) access
                existing_records_lookup = {}
                for _, row in existing_records_df.iterrows():
                    key = (row['player_lookup'], row['team_abbr'])
                    # Convert to dict and handle NaN values
                    record_dict = {}
                    for col, value in row.items():
                        if pd.isna(value):
                            record_dict[col] = None
                        elif isinstance(value, pd.Timestamp):
                            record_dict[col] = value.to_pydatetime()
                        elif hasattr(value, 'date'):
                            record_dict[col] = value.date()
                        else:
                            record_dict[col] = value
                    existing_records_lookup[key] = record_dict
                
                batch_fetch_duration = time.time() - batch_fetch_start
                logger.info(f"Batch fetched {len(existing_records_lookup)} existing records in {batch_fetch_duration:.2f}s")
                
            except Exception as e:
                logger.warning(f"Error batch fetching existing records: {e}, falling back to individual queries")
                existing_records_lookup = None
            
            # Track skipped records for reporting
            skipped_count = 0
            record_creation_start = time.time()
            records_checked = 0
            
            # Create registry records with PROTECTION CHECKS
            for (player_lookup, team_abbr), details in player_team_details.items():
                records_checked += 1
                
                # Log progress every 100 records
                if records_checked % 100 == 0:
                    elapsed = time.time() - record_creation_start
                    logger.info(f"Progress: {records_checked}/{len(player_team_details)} records checked in {elapsed:.1f}s")
                
                sources = details.get('sources', [])
                enhancement = details.get('enhancement_data', {})
                source_priority = details.get('source_priority', 'roster_unknown')
                
                # ===================================================================
                # PROTECTION 1: Get existing record (optimized batch lookup)
                # ===================================================================
                if existing_records_lookup is not None:
                    # Fast O(1) lookup from batch-fetched data
                    existing_record = existing_records_lookup.get((player_lookup, team_abbr))
                else:
                    # Fallback to individual query if batch fetch failed
                    existing_record = self.get_existing_record(player_lookup, team_abbr, season_str)
                
                # PROTECTION 2: Freshness check (skip when backfilling historical data)
                if not allow_backfill:
                    should_update, freshness_reason = self.should_update_record(
                        existing_record, data_date, self.processor_type
                    )
                    
                    if not should_update:
                        logger.debug(f"Skipping {player_lookup} on {team_abbr}: {freshness_reason}")
                        skipped_count += 1
                        continue  # Skip this record - data is stale
                elif existing_record and allow_backfill:
                    logger.debug(f"Backfill mode: allowing update for {player_lookup} on {team_abbr} (skipping freshness check)")
                
                # PROTECTION 3: Team authority check
                has_team_authority, authority_reason = self.check_team_authority(
                    existing_record, self.processor_type
                )
                
                # Determine confidence
                _, confidence_score = self._determine_roster_source_priority_and_confidence(
                    sources, enhancement, season_year
                )
                
                # Get universal player ID
                universal_id = universal_id_mappings.get(player_lookup, f"{player_lookup}_001")
                
                # Create base registry record
                record = {
                    'universal_player_id': universal_id,
                    'player_name': enhancement.get('player_full_name', player_lookup.title()),
                    'player_lookup': player_lookup,
                    'season': season_str,
                    
                    # No game data yet
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
                    
                    # Source metadata
                    'source_priority': source_priority,
                    'confidence_score': confidence_score,
                    'created_by': self.processing_run_id,
                    'created_at': datetime.now(),
                    'processed_at': datetime.now()
                }
                
                # PROTECTION 4: Only set team_abbr if we have authority
                if has_team_authority:
                    record['team_abbr'] = team_abbr
                    logger.debug(f"Setting team for {player_lookup}: {authority_reason}")
                else:
                    # Don't include team_abbr in record - MERGE will preserve existing value
                    # But we still need it for other operations, so log it
                    logger.debug(f"Skipping team update for {player_lookup}: {authority_reason}")
                    # Still need to include team_abbr for new records or we'll fail
                    # The check is: if existing_record has games > 0, don't update team
                    # But if it's a new record, we must set team
                    if existing_record is None:
                        record['team_abbr'] = team_abbr
                
                # PROTECTION 5: Update activity date
                record = self.update_activity_date(record, self.processor_type, data_date)
                
                # Enhance with source tracking
                enhanced_record = self.enhance_record_with_source_tracking(record, self.processor_type)
                
                # Convert types
                enhanced_record = self._convert_pandas_types_for_json(enhanced_record)
                registry_records.append(enhanced_record)
            
            if skipped_count > 0:
                logger.info(f"Skipped {skipped_count} records due to stale data")
            
            record_creation_duration = time.time() - record_creation_start
            logger.info(f"Created {len(registry_records)} registry records from validated roster data in {record_creation_duration:.2f}s")
            
            total_duration = time.time() - start_time
            logger.info(f"Total aggregation time: {total_duration:.2f}s")
            
            # Add counts to validation info
            validation_info['records_created'] = len(registry_records)
            validation_info['unvalidated_count'] = len(unvalidated_players)
            validation_info['records_skipped'] = skipped_count
            
            return registry_records, validation_info
            
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
        
        if len(sources) >= 3:
            confidence_score = min(confidence_score + 0.15, 1.0)
        elif len(sources) >= 2:
            confidence_score = min(confidence_score + 0.1, 1.0)
        
        if enhancement.get('jersey_number'):
            confidence_score = min(confidence_score + 0.05, 1.0)
        if enhancement.get('position'):
            confidence_score = min(confidence_score + 0.05, 1.0)
        
        if data_recency_days < 30:
            confidence_score = min(confidence_score + 0.1, 1.0)
        elif data_recency_days > 365:
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
        WHERE roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
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
        """Get detailed data from Basketball Reference rosters with staleness checking."""
        query = """
        SELECT 
            player_lookup,
            player_full_name,
            team_abbrev as team_abbr,
            jersey_number,
            position,
            MAX(last_scraped_date) as latest_scrape_date
        FROM `{project}.nba_raw.br_rosters_current`
        WHERE season_year = @season_year
        GROUP BY player_lookup, player_full_name, team_abbrev, jersey_number, position
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            if results.empty:
                logger.warning(f"No Basketball Reference roster data found for season {season_year}")
                return {}
            
            # Check staleness
            latest_scrape = pd.to_datetime(results['latest_scrape_date']).max()
            if isinstance(latest_scrape, pd.Timestamp):
                latest_scrape_date = latest_scrape.date()
            else:
                latest_scrape_date = latest_scrape
            
            staleness_days = (date.today() - latest_scrape_date).days
            
            logger.info(f"Basketball Reference data latest scrape: {latest_scrape_date} ({staleness_days} days old)")
            
            if staleness_days > 30:
                logger.warning(
                    f"⚠️ Basketball Reference data is {staleness_days} days stale "
                    f"(last scraped: {latest_scrape_date}). "
                    f"Jersey numbers and positions may be outdated."
                )
                try:
                    notify_warning(
                        title="Stale Basketball Reference Data",
                        message=f"BR roster data is {staleness_days} days old",
                        details={
                            'latest_scrape_date': str(latest_scrape_date),
                            'staleness_days': staleness_days,
                            'season_year': season_year,
                            'threshold_days': 30,
                            'impact': 'Jersey numbers and positions may be outdated',
                            'processor': 'roster_registry'
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
            
            detailed_data = {}
            
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
            
        except Exception as e:
            logger.warning(f"Error getting Basketball Reference detailed data: {e}")
            return {}
        
    def _get_nba_canonical_set(self, season_year: int, data_date: date) -> Tuple[Set[Tuple[str, str]], Dict]:
        """
        Get canonical (player, team) combinations from NBA.com with staleness checking.
        
        Returns:
            Tuple of (canonical set, validation info dict)
        """
        canonical_combos = set()
        season_str = self.calculate_season_string(season_year)
        nba_players_found = False
        
        # Get NBA.com players with freshness check
        nba_query = """
        SELECT DISTINCT 
            player_lookup, 
            team_abbr,
            player_full_name as display_name,
            MAX(source_file_date) as latest_scrape_date
        FROM `{project}.nba_raw.nbac_player_list_current`
        WHERE is_active = TRUE
        AND season_year = @season_year
        GROUP BY player_lookup, team_abbr, player_full_name
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        latest_scrape_date = None
        staleness_days = None
        
        try:
            nba_current = self.bq_client.query(nba_query, job_config=job_config).to_dataframe()
            
            if not nba_current.empty:
                latest_scrape_date = pd.to_datetime(nba_current['latest_scrape_date']).max()
                if isinstance(latest_scrape_date, pd.Timestamp):
                    latest_scrape_date = latest_scrape_date.date()
                
                staleness_days = (data_date - latest_scrape_date).days
                
                logger.info(f"NBA.com data latest scrape: {latest_scrape_date} ({staleness_days} days old)")
                
                # STALENESS CHECK: Threshold is 1 day
                if staleness_days > 1:
                    logger.warning(f"⚠️ NBA.com data is {staleness_days} days stale - SKIPPING VALIDATION")
                    
                    try:
                        notify_warning(
                            title="Stale NBA.com Canonical Data",
                            message=f"NBA.com data is {staleness_days} days old ({latest_scrape_date})",
                            details={
                                'latest_scrape_date': str(latest_scrape_date),
                                'data_date': str(data_date),
                                'staleness_days': staleness_days,
                                'threshold_days': 1,
                                'action': 'Skipping validation - processing ESPN-only',
                                'recommendation': 'Check NBA.com scraper status',
                                'processor': 'roster_registry'
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
                    
                    return set(), {
                        'validation_mode': 'none',
                        'validation_skipped_reason': 'nbacom_stale',
                        'source_data_freshness_days': staleness_days
                    }
                
                # Fresh data
                for _, row in nba_current.iterrows():
                    canonical_combos.add((row['player_lookup'], row['team_abbr']))
                nba_players_found = True
                logger.info(f"Loaded {len(canonical_combos)} player-team combinations from NBA.com (fresh data)")
                
            else:
                logger.warning("NBA.com current scrape returned no players")
                
        except Exception as e:
            logger.warning(f"Error loading NBA.com current players: {e}")
        
        # Get from existing registry
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
                logger.info(f"Added {len(canonical_combos) - original_count} from registry (total: {len(canonical_combos)})")
        except Exception as e:
            logger.warning(f"Error loading registry NBA.com players: {e}")
        
        # FALLBACK
        if not nba_players_found or len(canonical_combos) == 0:
            logger.warning("⚠️ NBA.com data unavailable - falling back to existing registry (all sources)")
            
            fallback_query = """
            SELECT DISTINCT 
                player_lookup,
                team_abbr
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
                    logger.warning(f"Using fallback: {len(canonical_combos)} player-team combinations from all sources")
                    
                    try:
                        notify_warning(
                            title="Roster Processor Using Fallback Mode",
                            message=f"NBA.com unavailable - using registry as canonical ({len(canonical_combos)} combinations)",
                            details={
                                'season': season_str,
                                'canonical_combos_count': len(canonical_combos),
                                'fallback_mode': True,
                                'processor': 'roster_registry'
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
                        
                    return canonical_combos, {
                        'validation_mode': 'partial',
                        'validation_skipped_reason': 'nbacom_unavailable',
                        'source_data_freshness_days': None
                    }
            except Exception as e:
                logger.error(f"Error loading fallback registry data: {e}")
        
        return canonical_combos, {
            'validation_mode': 'full',
            'validation_skipped_reason': None,
            'source_data_freshness_days': staleness_days
        }
        
    def _auto_create_suffix_aliases(self, player_team_details: Dict[Tuple[str, str], Dict]) -> int:
        """Auto-detect and create aliases for suffix mismatches (same team only)."""
        suffixes = ['jr', 'sr', 'ii', 'iii', 'iv', 'v']
        aliases_to_create = []
        unresolved_to_create = []
        
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
        
        for base, variants in base_to_variants.items():
            if len(variants) > 1:
                teams = set(v['team'] for v in variants)
                
                if len(teams) == 1:
                    canonical = None
                    for variant in variants:
                        if 'nba_player_list' in variant['sources']:
                            canonical = variant
                            break
                    
                    if not canonical:
                        canonical = next((v for v in variants if v['suffix']), variants[0])
                    
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
                                'notes': f"Auto-detected suffix mismatch (same team: {variant['team']})",
                                'created_by': self.processing_run_id,
                                'created_at': datetime.now(),
                                'processed_at': datetime.now()
                            })
                else:
                    for variant in variants:
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
                            'example_games': [],
                            'status': 'pending',
                            'resolution_type': None,
                            'resolved_to_name': None,
                            'notes': f"Cross-team suffix mismatch: base '{base}' on teams {list(teams)} - needs review",
                            'reviewed_by': None,
                            'reviewed_at': None,
                            'created_at': datetime.now(),
                            'processed_at': datetime.now()
                        })
        
        if aliases_to_create:
            self._insert_aliases(aliases_to_create)
            logger.info(f"Auto-created {len(aliases_to_create)} suffix aliases")
        
        if unresolved_to_create:
            self._insert_unresolved_names(unresolved_to_create)
            logger.warning(f"Created {len(unresolved_to_create)} unresolved records for cross-team mismatches")
        
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
                'notes': f"Found in {player['source']} but not in NBA.com canonical set",
                'reviewed_by': None,
                'reviewed_at': None,
                'created_at': datetime.now(),
                'processed_at': datetime.now()
            })
        
        if unresolved_records:
            try:
                self._insert_unresolved_names(unresolved_records)
                logger.info(f"Created {len(unresolved_records)} unresolved records")
            except Exception as e:
                logger.error(f"Failed to create unvalidated player records: {e}")

    def _insert_aliases(self, alias_records: List[Dict]) -> None:
        """Insert alias records into player_aliases table."""
        if not alias_records:
            return
        
        table_id = f"{self.project_id}.{self.alias_table_name}"
        
        try:
            existing_query = f"""
            SELECT alias_lookup
            FROM `{table_id}`
            WHERE alias_lookup IN UNNEST(@alias_lookups)
            """
            
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("alias_lookups", "STRING", 
                    [r['alias_lookup'] for r in alias_records])
            ])
            
            existing_df = self.bq_client.query(existing_query, job_config=job_config).to_dataframe()
            existing_aliases = set(existing_df['alias_lookup']) if not existing_df.empty else set()
            
            new_aliases = [r for r in alias_records if r['alias_lookup'] not in existing_aliases]
            
            if not new_aliases:
                return
            
            processed_aliases = []
            for r in new_aliases:
                converted = self._convert_pandas_types_for_json(r)
                if 'is_active' in converted:
                    converted['is_active'] = bool(converted['is_active'])
                processed_aliases.append(converted)
            
            errors = self.bq_client.insert_rows_json(table_id, processed_aliases)
            
            if errors:
                logger.error(f"Errors inserting aliases: {errors}")
            else:
                logger.info(f"Successfully inserted {len(new_aliases)} new aliases")
                
        except Exception as e:
            logger.error(f"Failed to insert aliases: {e}")

    def _insert_unresolved_names(self, unresolved_records: List[Dict]) -> None:
        """Insert unresolved player name records."""
        if not unresolved_records:
            return
        
        if not isinstance(unresolved_records, list):
            unresolved_records = list(unresolved_records)
        
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        
        try:
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
            
            existing_map = {}
            if len(existing_df) > 0:
                for _, row in existing_df.iterrows():
                    key = (row['normalized_lookup'], row['team_abbr'], row['season'])
                    existing_map[key] = row['occurrences']
            
            new_unresolved = []
            updates_needed = []
            
            for r in unresolved_records:
                key = (r['normalized_lookup'], r['team_abbr'], r['season'])
                
                if key in existing_map:
                    updates_needed.append({
                        'normalized_lookup': r['normalized_lookup'],
                        'team_abbr': r['team_abbr'],
                        'season': r['season'],
                        'new_occurrences': existing_map[key] + 1,
                        'last_seen_date': r['last_seen_date']
                    })
                else:
                    new_unresolved.append(r)
            
            if len(new_unresolved) > 0:
                processed_unresolved = []
                for r in new_unresolved:
                    converted = self._convert_pandas_types_for_json(r)
                    if 'example_games' in converted:
                        eg = converted['example_games']
                        if eg is None:
                            converted['example_games'] = []
                        elif not isinstance(eg, list):
                            converted['example_games'] = list(eg) if hasattr(eg, '__iter__') else []
                    processed_unresolved.append(converted)
                
                errors = self.bq_client.insert_rows_json(table_id, processed_unresolved)
                if errors:
                    logger.error(f"Errors inserting unresolved: {errors}")
                else:
                    logger.info(f"Inserted {len(new_unresolved)} new unresolved records")
            
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
                        if 'streaming buffer' in str(e).lower():
                            logger.debug(f"Skipping UPDATE for {update['normalized_lookup']} - streaming buffer")
                        else:
                            logger.warning(f"Failed to update {update['normalized_lookup']}: {e}")
                
                if successful_updates > 0:
                    logger.info(f"Updated {successful_updates} existing unresolved records")
                    
        except Exception as e:
            logger.error(f"Failed to insert/update unresolved: {e}")
    
    def get_player_team_assignment(self, player_lookup: str, roster_data: Dict[str, Set[str]] = None) -> str:
        """Find team assignment for a player."""
        if not roster_data:
            season_year = date.today().year if date.today().month >= 10 else date.today().year - 1
            
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
                logger.warning(f"Error finding team assignment: {e}")
        
        return 'UNK'
    
    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """Transform roster data into registry records."""
        try:
            season_year = raw_data.get('season_year', date.today().year)
            data_date = raw_data.get('data_date', date.today())
            allow_backfill = raw_data.get('allow_backfill', False)
            
            logger.info(f"Processing roster data for season {season_year}, date {data_date}")
            
            roster_data = self.get_current_roster_data(season_year)
            season_str = self.calculate_season_string(season_year)
            existing_players = self.get_existing_registry_players(season_str)
            
            all_roster_players = set()
            for source, players in roster_data.items():
                all_roster_players.update(players)
            
            logger.info(f"Found {len(all_roster_players)} total players")
            
            unknown_players = all_roster_players - existing_players
            if unknown_players:
                logger.info(f"Found {len(unknown_players)} unknown players")
                
                if len(unknown_players) > 50:
                    try:
                        notify_warning(
                            title="High Unknown Player Count",
                            message=f"Found {len(unknown_players)} new players",
                            details={
                                'season': season_str,
                                'unknown_count': len(unknown_players),
                                'sample': list(unknown_players)[:20]
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send notification: {e}")
            
            registry_records, validation_info = self.aggregate_roster_assignments(
                roster_data, season_year, data_date, allow_backfill=allow_backfill
            )
            
            logger.info(f"Created {len(registry_records)} registry records")
            
            self.validation_info = validation_info
            
            return registry_records
            
        except Exception as e:
            logger.error(f"Transform data failed: {e}")
            try:
                notify_error(
                    title="Roster Registry Transform Failed",
                    message=f"Failed to transform: {str(e)}",
                    details={
                        'season_year': raw_data.get('season_year'),
                        'error_type': type(e).__name__
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def _build_registry_for_season_impl(self, season: str, team: str = None, 
                                       data_date: date = None, allow_backfill: bool = False) -> Dict:
        """Implementation of season building."""
        logger.info(f"Building roster registry for season {season}")
        
        try:
            self.new_players_discovered = set()
            self.players_seen_this_run = set()
            
            self.stats = {
                'players_processed': 0,
                'records_created': 0,
                'records_updated': 0,
                'seasons_processed': set(),
                'teams_processed': set(),
                'unresolved_players_found': 0,
                'alias_resolutions': 0
            }
            
            season_year = int(season.split('-')[0])
            data_date = data_date or date.today()
            
            filter_data = {
                'season_year': season_year,
                'data_date': data_date,
                'allow_backfill': allow_backfill
            }
            
            rows = self.transform_data(filter_data)
            result = self.save_registry_data(rows)
            
            if hasattr(self, 'validation_info'):
                result.update(self.validation_info)
            
            result['new_players_discovered'] = list(self.new_players_discovered)
            if self.new_players_discovered:
                logger.info(f"Discovered {len(self.new_players_discovered)} new players")
            
            logger.info(f"Roster registry build complete for {season}")
            logger.info(f"  Records processed: {result['rows_processed']}")
            logger.info(f"  Records created: {len(rows)}")
            
            return {
                'season': season,
                'team_filter': team,
                'records_processed': result['rows_processed'],
                'records_created': len(rows),
                'players_processed': len(rows),
                'teams_processed': list(set(row['team_abbr'] for row in rows)) if rows else [],
                'new_players_discovered': result['new_players_discovered'],
                'validation_mode': result.get('validation_mode'),
                'validation_skipped_reason': result.get('validation_skipped_reason'),
                'source_data_freshness_days': result.get('source_data_freshness_days'),
                'errors': result.get('errors', []),
                'processing_run_id': self.processing_run_id
            }
            
        except Exception as e:
            logger.error(f"Failed to build roster registry: {e}")
            try:
                notify_error(
                    title="Roster Registry Build Failed",
                    message=f"Failed to build: {str(e)}",
                    details={
                        'season': season,
                        'error_type': type(e).__name__
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    def process_daily_rosters(self, season_year: int = None, data_date: date = None,
                            allow_backfill: bool = False) -> Dict:
        """
        Process daily roster updates with complete protection.
        
        Main entry point for daily processing after roster scrapers complete.
        """
        if not season_year:
            current_month = date.today().month
            if current_month >= 10:
                season_year = date.today().year
            else:
                season_year = date.today().year - 1
        
        if not data_date:
            data_date = date.today()

        season_str = self.calculate_season_string(season_year)
        logger.info(f"Processing daily rosters for {season_str}, date {data_date}")
        
        # =======================================================================
        # PROTECTION 1: Season Protection - Don't process historical seasons
        # =======================================================================
        current_season_year = date.today().year if date.today().month >= 10 else date.today().year - 1
        if season_year < current_season_year and not allow_backfill:
            error_msg = (
                f"Cannot process historical season {season_year}-{season_year+1}. "
                f"Current season is {current_season_year}-{current_season_year+1}. "
                f"Roster processor is for current season only. "
                f"Use --allow-backfill flag only if you need to fix historical roster data."
            )
            logger.error(error_msg)
            return {
                'status': 'blocked',
                'reason': error_msg,
                'season': season_str,
                'protection_layer': 'season_protection'
            }
        
        # =======================================================================
        # PROTECTION 2: Gamebook Precedence - Don't override gamebook data
        # =======================================================================
        is_blocked, block_reason = self.check_gamebook_precedence(data_date, season_year)
        if is_blocked:
            logger.error(f"Roster processing blocked by gamebook precedence: {block_reason}")
            return {
                'status': 'blocked',
                'reason': block_reason,
                'season': season_str,
                'data_date': str(data_date),
                'protection_layer': 'gamebook_precedence',
                'message': (
                    'Gamebook has already processed this date. Gamebook data represents '
                    'verified game participation and is the authoritative source. '
                    'Roster data should not override it.'
                )
            }
        
        # =======================================================================
        # PROTECTION 3: Temporal Ordering Protection
        # =======================================================================
        try:
            self.validate_temporal_ordering(
                data_date=data_date,
                season_year=season_year,
                allow_backfill=allow_backfill
            )
        except TemporalOrderingError as e:
            logger.error(f"Temporal ordering error: {e}")
            return {
                'status': 'skipped',
                'reason': str(e),
                'season': season_str,
                'data_date': str(data_date),
                'protection_layer': 'temporal_ordering'
            }
        
        # =======================================================================
        # TRACK RUN START (in memory only)
        # =======================================================================
        from datetime import timezone
        import uuid
        
        self.run_start_time = datetime.now(timezone.utc)
        self.current_run_id = f"{self.processor_type}_{data_date.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}_{str(uuid.uuid4())[:8]}"
        self.current_season_year = season_year
        
        logger.info(f"Starting run: {self.current_run_id}")
        
        # Determine validation mode and freshness (will be filled in during processing)
        validation_mode = None
        source_data_freshness_days = None
        
        try:
            result = self._build_registry_for_season_impl(
                season_str, 
                data_date=data_date, 
                allow_backfill=allow_backfill
            )
            
            # Extract validation info from result
            validation_mode = result.get('validation_mode')
            source_data_freshness_days = result.get('source_data_freshness_days')
            
            # Record successful completion
            self.record_run_complete(
                data_date=data_date,
                season_year=season_year,
                status='success',
                result=result,
                data_source_primary='espn_roster',
                data_source_enhancement='nbacom_roster',
                validation_mode=validation_mode,
                source_data_freshness_days=source_data_freshness_days,
                backfill_mode=allow_backfill
            )
            
            try:
                from shared.utils.notification_system import notify_info
                notify_info(
                    title="Daily Roster Processing Complete",
                    message=f"Successfully processed {season_str}",
                    details={
                        'season': season_str,
                        'data_date': str(data_date),
                        'records_processed': result['records_processed'],
                        'new_players': len(result.get('new_players_discovered', [])),
                        'validation_mode': validation_mode,
                        'run_id': self.current_run_id
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Daily roster processing failed: {e}")
            
            # Record failed completion
            self.record_run_complete(
                data_date=data_date,
                season_year=season_year,
                status='failed',
                error=e,
                data_source_primary='espn_roster',
                data_source_enhancement='nbacom_roster',
                validation_mode=validation_mode,
                source_data_freshness_days=source_data_freshness_days,
                backfill_mode=allow_backfill
            )
            
            try:
                notify_error(
                    title="Daily Roster Processing Failed",
                    message=f"Failed: {str(e)}",
                    details={
                        'season': season_str,
                        'data_date': str(data_date),
                        'error_type': type(e).__name__
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def check_gamebook_precedence(self, data_date: date, season_year: int) -> Tuple[bool, str]:
        """
        Check if gamebook processor has processed this date or any later date in the season.
        
        This is a TEMPORAL cross-processor check, not just an exact-date check.
        
        Gamebook data is authoritative for historical dates because it represents
        actual game participation. Roster data should not override it.
        
        Business Rule:
        - If gamebook has successfully processed ANY date >= data_date in this season,
        roster CANNOT process data_date
        - This prevents roster from going backwards relative to gamebook's progress
        - Works like temporal ordering but across processors
        
        Example:
        Gamebook processed: Oct 5, 2024
        Roster tries: Oct 1, 2024
        Result: BLOCKED (gamebook is ahead, roster can't go backwards)
        
        Args:
            data_date: The date being processed
            season_year: The season year being processed
            
        Returns:
            Tuple of (is_blocked: bool, reason: str)
            - is_blocked=True: Processing should be blocked
            - is_blocked=False: Safe to proceed
            - reason: Explanation for the decision
        """
        query = f"""
        SELECT 
            MAX(data_date) as latest_gamebook_date,
            MAX(processed_at) as last_gamebook_run,
            COUNT(*) as total_gamebook_runs,
            SUM(records_processed) as total_records
        FROM `{self.project_id}.{self.run_history_table}`
        WHERE processor_name = 'gamebook'
        AND season_year = @season_year
        AND status = 'success'
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season_year", "INT64", season_year)
        ])
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            # Check if gamebook has processed anything for this season
            if results.empty or pd.isna(results.iloc[0]['latest_gamebook_date']):
                logger.info(f"No gamebook data found for season {season_year} - roster can proceed")
                return False, "no_gamebook_data"
            
            # Get latest date gamebook has processed
            latest_gamebook_date = results.iloc[0]['latest_gamebook_date']
            
            # Convert to date if timestamp
            if isinstance(latest_gamebook_date, pd.Timestamp):
                latest_gamebook_date = latest_gamebook_date.date()
            
            # TEMPORAL CHECK: Is roster trying to process a date <= gamebook's progress?
            if data_date <= latest_gamebook_date:
                last_run = results.iloc[0]['last_gamebook_run']
                total_runs = results.iloc[0]['total_gamebook_runs']
                total_records = results.iloc[0]['total_records']
                
                error_msg = (
                    f"Gamebook processor has already processed through {latest_gamebook_date} "
                    f"for season {season_year}. Cannot process {data_date} - roster must not "
                    f"go backwards relative to gamebook's progress. "
                    f"Last gamebook run: {last_run} ({total_runs} total runs, "
                    f"{total_records} total records processed)."
                )
                
                logger.error(error_msg)
                
                try:
                    notify_error(
                        title="Roster Processing Blocked by Gamebook Precedence",
                        message=f"Cannot process {data_date} - gamebook already at {latest_gamebook_date}",
                        details={
                            'data_date': str(data_date),
                            'latest_gamebook_date': str(latest_gamebook_date),
                            'season_year': season_year,
                            'total_gamebook_runs': int(total_runs) if pd.notna(total_runs) else 0,
                            'last_gamebook_run': str(last_run),
                            'total_records': int(total_records) if pd.notna(total_records) else 0,
                            'reason': 'gamebook_data_is_authoritative',
                            'action': 'Roster cannot go backwards relative to gamebook progress'
                        },
                        processor_name="Roster Registry Processor"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
                
                return True, error_msg
            
            # Roster is ahead of gamebook - safe to proceed
            logger.info(
                f"Gamebook at {latest_gamebook_date}, roster processing {data_date} - "
                f"roster is ahead, safe to proceed"
            )
            return False, "roster_ahead_of_gamebook"
            
        except Exception as e:
            logger.warning(f"Error checking gamebook precedence (proceeding with caution): {e}")
            # On error, fail open but log warning - don't block processing
            return False, f"check_failed: {str(e)}"

    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """Build registry from historical roster data."""
        logger.info("Roster processor handles current data only")
        
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
                'processing_run_id': self.processing_run_id
            }
            
        except Exception as e:
            logger.error(f"Historical registry build failed: {e}")
            try:
                notify_error(
                    title="Historical Roster Build Failed",
                    message=f"Failed: {str(e)}",
                    details={'error_type': type(e).__name__},
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise


def process_daily_rosters(season_year: int = None, data_date: date = None, 
                         strategy: str = "merge", allow_backfill: bool = False) -> Dict:
    """Convenience function for daily roster processing."""
    processor = RosterRegistryProcessor(strategy=strategy)
    return processor.process_daily_rosters(season_year, data_date, allow_backfill)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process roster registry")
    parser.add_argument("--season-year", type=int, help="NBA season starting year")
    parser.add_argument("--data-date", type=str, help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--allow-backfill", action="store_true", help="Allow processing earlier dates")
    parser.add_argument("--strategy", default="merge", choices=["merge", "replace", "append"])
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    data_date = None
    if args.data_date:
        from datetime import datetime
        data_date = datetime.strptime(args.data_date, '%Y-%m-%d').date()
    
    processor = RosterRegistryProcessor(strategy=args.strategy)
    result = processor.process_daily_rosters(
        season_year=args.season_year,
        data_date=data_date,
        allow_backfill=args.allow_backfill
    )
    
    print(f"\n{'='*60}")
    
    # Handle different result types
    if result.get('status') == 'blocked':
        protection_layer = result.get('protection_layer', 'unknown')
        print(f"🚫 BLOCKED by {protection_layer}")
        print(f"{'='*60}")
        print(f"Season: {result['season']}")
        if 'data_date' in result:
            print(f"Data Date: {result['data_date']}")
        print(f"\nReason: {result['reason']}")
        if 'message' in result:
            print(f"\nDetails: {result['message']}")
    elif result.get('status') == 'skipped':
        print(f"⚠️  SKIPPED")
        print(f"{'='*60}")
        print(f"Season: {result['season']}")
        print(f"Reason: {result['reason']}")
    else:
        print(f"✅ SUCCESS")
        print(f"{'='*60}")
        print(f"Season: {result['season']}")
        print(f"Data Date: {result.get('data_date', 'today')}")
        print(f"Records processed: {result.get('records_processed', 0)}")
        print(f"Validation mode: {result.get('validation_mode', 'N/A')}")
        if result.get('source_data_freshness_days') is not None:
            print(f"Source freshness: {result['source_data_freshness_days']} days")
    
    print(f"{'='*60}")