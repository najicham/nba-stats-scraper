#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/nba_players_registry_processor.py

NBA Players Registry Processor

Builds the NBA players registry from existing NBA.com gamebook data.
This processor reads from the processed gamebook table and creates the
authoritative player registry for name resolution.

Three Usage Scenarios:
1. Historical backfill: Process 4 years of gamebook data
2. Nightly updates: Triggered after gamebook processing completes
3. Roster updates: Triggered after morning roster scraping
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
import pandas as pd
import numpy as np
from typing import Dict, Any

# Fixed import path for new structure
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.player_name_normalizer import normalize_name_for_lookup
# from shared.utils.nba_team_mapper import nba_team_mapper

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
    
    def __init__(self, test_mode: bool = False):
        super().__init__()
        
        self.processing_strategy = 'MERGE_UPDATE'  # Replace existing season data
        
        # Initialize BigQuery client
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Processing tracking
        self.processing_run_id = f"registry_build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Configure test mode and table names
        self.test_mode = test_mode
        if test_mode:
            # Use fixed timestamp for predictable table names during testing
            timestamp_suffix = "FIXED2"  # Or use date without time: datetime.now().strftime('%Y%m%d')
            self.table_name = f'nba_reference.nba_players_registry_test_{timestamp_suffix}'
            self.unresolved_table_name = f'nba_reference.unresolved_player_names_test_{timestamp_suffix}'
            self.alias_table_name = f'nba_reference.player_aliases_test_{timestamp_suffix}'
            self.processing_run_id += f"_TEST_{timestamp_suffix}"
            logger.info(f"Running in TEST MODE with fixed table suffix: {timestamp_suffix}")
        else:
            self.table_name = 'nba_reference.nba_players_registry'
            self.unresolved_table_name = 'nba_reference.unresolved_player_names'
            self.alias_table_name = 'nba_reference.player_aliases'
            logger.info("Running in PRODUCTION MODE")
        
        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set(),
            'unresolved_players_found': 0,
            'alias_resolutions': 0
        }
        
        logger.info(f"Initialized registry processor with run ID: {self.processing_run_id}")
    
    def date_to_nba_season_years(self, date_range: Tuple[str, str]) -> Tuple[int, int]:
        """
        Convert date range to NBA season years.
        
        NBA season runs from October to June:
        - 2022-02-01 is in 2021-22 season (season_year=2021)
        - 2022-10-15 is in 2022-23 season (season_year=2022)
        
        Args:
            date_range: Tuple of (start_date, end_date) in 'YYYY-MM-DD' format
            
        Returns:
            Tuple of (start_season_year, end_season_year)
        """
        start_date = datetime.strptime(date_range[0], '%Y-%m-%d')
        end_date = datetime.strptime(date_range[1], '%Y-%m-%d')
        
        def get_season_year(date_obj):
            """Convert a date to NBA season year."""
            if date_obj.month >= 10:  # October-December
                return date_obj.year
            else:  # January-September (next calendar year)
                return date_obj.year - 1
        
        start_season_year = get_season_year(start_date)
        end_season_year = get_season_year(end_date)
        
        logger.info(f"Date range {date_range} maps to NBA season years: {start_season_year} to {end_season_year}")
        
        return (start_season_year, end_season_year)
    
    def get_gamebook_player_data(self, season_filter: str = None, 
                               team_filter: str = None, 
                               date_range: Tuple[str, str] = None) -> pd.DataFrame:
        """Extract player data from processed gamebook table."""
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
    
    def calculate_season_string(self, season_year: int) -> str:
        """Convert season year to standard season string format."""
        return f"{season_year}-{str(season_year + 1)[-2:]}"
    
    def _check_player_aliases(self, player_lookup: str, team_abbr: str) -> bool:
        """Check if player exists under an alias in the registry."""
        alias_query = f"""
        SELECT r.player_lookup, r.team_abbr, r.games_played
        FROM `{self.project_id}.{self.alias_table_name}` a
        JOIN `{self.project_id}.{self.table_name}` r
        ON a.nba_canonical_lookup = r.player_lookup
        WHERE a.alias_lookup = @alias_lookup
        AND r.team_abbr = @team_abbr
        AND a.is_active = TRUE
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("alias_lookup", "STRING", player_lookup),
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr)
        ])
        
        try:
            results = self.bq_client.query(alias_query, job_config=job_config).to_dataframe()
            found = not results.empty
            
            if found:
                self.stats['alias_resolutions'] += 1
                # Add this enhanced logging:
                logger.info(f"ALIAS RESOLUTION SUCCESS: {player_lookup} for {team_abbr} found via alias mapping")
                
                # Debug logging for our specific case
                if player_lookup == 'kjmartin' and team_abbr == 'HOU':
                    logger.info(f"DEBUG: kjmartin alias check SUCCESS - found {len(results)} registry records")
            else:
                # Debug logging for failed alias checks
                if player_lookup == 'kjmartin':
                    logger.info(f"DEBUG: kjmartin alias check FAILED for {team_abbr}")
            
            return found
            
        except Exception as e:
            logger.warning(f"Error checking player aliases: {e}")
            return False
    
    def aggregate_player_stats(self, gamebook_df: pd.DataFrame, date_range: Tuple[str, str] = None) -> List[Dict]:
        """Aggregate gamebook data into registry records and handle unresolved names."""
        logger.info("Aggregating player statistics for registry...")
        
        # Determine season years for Basketball Reference filtering
        season_years_filter = None
        if date_range:
            start_season_year, end_season_year = self.date_to_nba_season_years(date_range)
            season_years_filter = (start_season_year, end_season_year)
        else:
            # Use seasons present in gamebook data
            seasons_in_data = gamebook_df['season_year'].unique()
            if len(seasons_in_data) > 0:
                season_years_filter = (int(seasons_in_data.min()), int(seasons_in_data.max()))
                logger.info(f"Using season years from gamebook data: {seasons_in_data.min()} to {seasons_in_data.max()}")
        
        # Get roster enhancement data with season constraint
        enhancement_data = self.get_roster_enhancement_data(season_years_filter=season_years_filter)
        
        registry_records = []
        
        # FIXED: Group by logical business key only (removed player_name)
        groupby_cols = ['player_lookup', 'team_abbr', 'season_year']
        grouped = gamebook_df.groupby(groupby_cols)
        
        # Track which Basketball Reference players we found in gamebook
        found_br_players = set()
        
        for (player_lookup, team_abbr, season_year), group in grouped:
            # Calculate season string
            season_str = self.calculate_season_string(season_year)
            
            # FIXED: Pick the most common player name variant
            name_counts = group['player_name'].value_counts()
            player_name = name_counts.index[0]  # Most frequent name
            
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
            
            # Look up enhancement data (with alias resolution)
            enhancement, resolved_via_alias = self._resolve_enhancement_via_alias(
                player_lookup, team_abbr, enhancement_data
            )

            # Add debug logging
            if team_abbr in ['BKN', 'CHA', 'PHX']:
                logger.info(f"Looking up enhancement for ({team_abbr}, {player_lookup})")
                if enhancement:
                    resolution_method = "via alias" if resolved_via_alias else "direct"
                    logger.info(f"Found enhancement {resolution_method}: jersey={enhancement.get('jersey_number')}")
                else:
                    logger.info(f"No enhancement found for ({team_abbr}, {player_lookup})")
                    # Show what keys ARE available for this team
                    available_keys = [k for k in enhancement_data.keys() if k[0] == team_abbr]
                    logger.info(f"Available {team_abbr} keys: {available_keys[:5]}")

            # Track that we found this BR player (handle both direct and alias cases)
            if enhancement:
                if resolved_via_alias:
                    # For alias resolution, find the original BR key that matched
                    for br_key, br_data in enhancement_data.items():
                        if br_key[0] == team_abbr and br_data == enhancement:
                            found_br_players.add(br_key)
                            break
                else:
                    found_br_players.add((team_abbr, player_lookup))

            # Convert to dict format for compatibility (if it's None)
            if enhancement is None:
                enhancement = {}
            
            # Create registry record with proper timestamp fields
            record = {
                'player_name': player_name,  # Use most common name variant
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,
                'season': season_str,
                'first_game_date': first_game,
                'last_game_date': last_game,
                'games_played': active_games,
                'total_appearances': total_appearances,
                'inactive_appearances': inactive_games,
                'dnp_appearances': dnp_games,
                'jersey_number': enhancement.get('jersey_number'),
                'position': enhancement.get('position'),
                'last_roster_update': date.today() if enhancement else None,
                'source_priority': source_priority,
                'confidence_score': confidence_score,
                'created_by': self.processing_run_id,
                'created_at': datetime.now(),  # TIMESTAMP field
                'processed_at': datetime.now()  # TIMESTAMP field
            }
            
            # Convert types for BigQuery
            record = self._convert_pandas_types_for_json(record)
            registry_records.append(record)
            
            # Update stats
            self.stats['players_processed'] += 1
            self.stats['seasons_processed'].add(season_str)
            self.stats['teams_processed'].add(team_abbr)
        
        # UPDATED: Handle unresolved Basketball Reference players with alias checking
        self._handle_unresolved_br_players(enhancement_data, found_br_players)
        
        logger.info(f"Created {len(registry_records)} registry records")
        logger.info(f"Resolved {self.stats['alias_resolutions']} players via alias system")
        return registry_records

    def _resolve_enhancement_via_alias(self, player_lookup: str, team_abbr: str, enhancement_data: Dict) -> Tuple[Optional[Dict], bool]:
        """
        Attempt to resolve enhancement data via alias lookup.
        """
        # Add debug logging
        logger.info(f"ALIAS DEBUG: Checking enhancement for {player_lookup} at {team_abbr}")
        
        # Direct lookup first
        direct_key = (team_abbr, player_lookup)
        if direct_key in enhancement_data:
            logger.info(f"ALIAS DEBUG: Found direct enhancement for {direct_key}")
            return enhancement_data[direct_key], False
        
        logger.info(f"ALIAS DEBUG: No direct enhancement, trying alias resolution for {player_lookup}")
        
        # Find Basketball Reference aliases that resolve to this canonical player
        alias_query = f"""
        SELECT a.alias_lookup as br_alias_lookup
        FROM `{self.project_id}.{self.alias_table_name}` a
        WHERE a.nba_canonical_lookup = @canonical_lookup
        AND a.is_active = TRUE
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("canonical_lookup", "STRING", player_lookup),
        ])
        
        try:
            results = self.bq_client.query(alias_query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                # Get the Basketball Reference alias name
                br_alias_lookup = results.iloc[0]['br_alias_lookup']  # Fixed column name
                br_key = (team_abbr, br_alias_lookup)  # Fixed enhancement key
                
                logger.info(f"ALIAS DEBUG: Found alias {br_alias_lookup} for canonical {player_lookup}")
                
                if br_key in enhancement_data:
                    logger.info(f"ALIAS DEBUG: Enhancement resolved via alias: {player_lookup} → {br_alias_lookup} for {team_abbr}")
                    self.stats['alias_resolutions'] += 1
                    return enhancement_data[br_key], True  # Use Basketball Reference key
                else:
                    logger.info(f"ALIAS DEBUG: No enhancement data found for alias key {br_key}")
                    
            return None, False
            
        except Exception as e:
            logger.warning(f"Error resolving enhancement via alias for {player_lookup}: {e}")
            return None, False
        
    def _handle_unresolved_br_players(self, enhancement_data: Dict, found_players: set):
        """Find Basketball Reference players not in gamebook and add to unresolved table."""
        unresolved_players = []
        current_datetime = datetime.now()
        current_date = current_datetime.date()
        
        for (team_abbr, player_lookup), enhancement in enhancement_data.items():
            if (team_abbr, player_lookup) not in found_players:
                # NEW: Check aliases before marking as unresolved
                if self._check_player_aliases(player_lookup, team_abbr):
                    logger.info(f"Player {player_lookup} found via alias mapping for {team_abbr}")
                    continue  # Skip - found via alias
                
                # Only mark as unresolved if no alias found
                unresolved_record = {
                    'source': 'basketball_reference',
                    'original_name': enhancement.get('original_name', 'Unknown'),
                    'normalized_lookup': player_lookup,
                    'first_seen_date': current_date,
                    'last_seen_date': current_date,
                    'team_abbr': team_abbr,
                    'season': self.calculate_season_string(enhancement.get('season_year', 2024)),
                    'occurrences': 1,
                    'example_games': [],  # No games since not in gamebook
                    'status': 'pending',
                    'resolution_type': None,
                    'resolved_to_name': None,
                    'notes': f"Found in Basketball Reference roster but no NBA.com gamebook entries",
                    'reviewed_by': None,
                    'reviewed_at': None,
                    'created_at': current_datetime,  # TIMESTAMP field
                    'processed_at': current_datetime  # TIMESTAMP field
                }
                
                unresolved_players.append(unresolved_record)
        
        # Insert unresolved players if any found
        if unresolved_players:
            self._insert_unresolved_players(unresolved_players)
            self.stats['unresolved_players_found'] = len(unresolved_players)
            logger.info(f"Added {len(unresolved_players)} Basketball Reference players to unresolved queue")
        else:
            logger.info("No unresolved Basketball Reference players found (all resolved via aliases or gamebook)")

    def _insert_unresolved_players(self, unresolved_records: List[Dict]):
        """Insert unresolved player records with deduplication."""
        if not unresolved_records:
            return
        
        # Group by key fields to deduplicate
        dedup_dict = {}
        for record in unresolved_records:
            key = (
                record['source'],
                record['normalized_lookup'], 
                record['team_abbr'],
                record['season']
            )
            if key not in dedup_dict:
                dedup_dict[key] = record
            else:
                # Update occurrence count if duplicate found
                dedup_dict[key]['occurrences'] += record.get('occurrences', 1)
        
        # Use deduplicated records
        deduplicated_records = list(dedup_dict.values())
        
        if len(deduplicated_records) < len(unresolved_records):
            logger.info(f"Deduplicated {len(unresolved_records)} → {len(deduplicated_records)} unresolved records")
        
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        
        try:
            # Convert types for BigQuery
            processed_records = []
            for record in deduplicated_records:
                processed_record = self._convert_pandas_types_for_json(record)
                processed_records.append(processed_record)
            
            # Insert deduplicated records
            result = self.bq_client.insert_rows_json(table_id, processed_records)
            
            if result:
                logger.error(f"Error inserting unresolved players: {result}")
            else:
                logger.info(f"Successfully inserted {len(processed_records)} deduplicated unresolved players")
                
        except Exception as e:
            logger.error(f"Error inserting unresolved players: {e}")

    # Replace the existing season filtering logic in get_roster_enhancement_data()
    def get_roster_enhancement_data(self, season_filter: str = None, season_years_filter: Tuple[int, int] = None) -> Dict[Tuple[str, str], Dict]:
        """Get jersey numbers and positions from roster data with team mapping."""
        logger.info("Loading roster enhancement data...")
        
        try:
            # Import team mapper (local import to avoid deployment issues)
            try:
                from shared.utils.nba_team_mapper import nba_team_mapper
                logger.info("Successfully imported nba_team_mapper")
            except ImportError as e:
                logger.warning(f"Could not import nba_team_mapper: {e}")
                # Fallback to hardcoded mapping
                BR_TO_NBA_MAPPING = {
                    'BRK': 'BKN',  # Brooklyn
                    'CHO': 'CHA',  # Charlotte  
                    'PHO': 'PHX'   # Phoenix
                }
                nba_team_mapper = None
                logger.info("Using fallback hardcoded team mapping")
            
            # Query Basketball Reference with BR team codes
            query = """
            SELECT DISTINCT
                team_abbrev as br_team_abbr,
                player_lookup,
                player_full_name as original_name,
                jersey_number,
                position,
                season_year
            FROM `{project}.nba_raw.br_rosters_current`
            WHERE player_lookup IS NOT NULL
            AND team_abbrev IS NOT NULL
            """.format(project=self.project_id)
            
            query_params = []
            
            # FIXED: Prioritize single season filter over range filter
            if season_filter:
                season_year = int(season_filter.split('-')[0])  # "2021-22" → 2021
                query += " AND season_year = @season_year"
                query_params.append(bigquery.ScalarQueryParameter("season_year", "INT64", season_year))
                logger.info(f"Filtering Basketball Reference data for single season: {season_filter} (season_year: {season_year})")
                
            elif season_years_filter:
                # Only use range filter if no single season specified
                start_year, end_year = season_years_filter
                query += " AND season_year BETWEEN @start_season_year AND @end_season_year"
                query_params.extend([
                    bigquery.ScalarQueryParameter("start_season_year", "INT64", start_year),
                    bigquery.ScalarQueryParameter("end_season_year", "INT64", end_year)
                ])
                logger.info(f"Filtering Basketball Reference data to season years: {start_year}-{end_year}")
            
            # FIXED: Add ORDER BY to ensure consistent data loading
            query += " ORDER BY season_year, team_abbrev, player_lookup"
            
            job_config = bigquery.QueryJobConfig(query_parameters=query_params)
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            
            logger.info(f"Retrieved {len(results)} roster records from Basketball Reference")
            
            # DEBUG: Log season years in the data
            if not results.empty:
                season_years = results['season_year'].unique()
                logger.info(f"Basketball Reference data contains season years: {sorted(season_years)}")
            
            # Build lookup dict with NBA team code mapping
            enhancement_data = {}
            mapped_count = 0
            unmapped_teams = set()
            team_mapping_log = {}
            
            for _, row in results.iterrows():
                br_team_abbr = row['br_team_abbr']
                nba_team_abbr = None
                
                # Try team mapping
                if nba_team_mapper:
                    # Use the team mapper utility
                    for team in nba_team_mapper.teams_data:
                        if team.br_tricode == br_team_abbr:
                            nba_team_abbr = team.nba_tricode
                            if br_team_abbr != nba_team_abbr:
                                if br_team_abbr not in team_mapping_log:
                                    logger.info(f"Team mapping: {br_team_abbr} → {nba_team_abbr}")
                                    team_mapping_log[br_team_abbr] = nba_team_abbr
                                mapped_count += 1
                            break
                else:
                    # Use hardcoded fallback mapping
                    nba_team_abbr = BR_TO_NBA_MAPPING.get(br_team_abbr, br_team_abbr)
                    if br_team_abbr != nba_team_abbr:
                        if br_team_abbr not in team_mapping_log:
                            logger.info(f"Fallback team mapping: {br_team_abbr} → {nba_team_abbr}")
                            team_mapping_log[br_team_abbr] = nba_team_abbr
                        mapped_count += 1
                
                if nba_team_abbr:  # Successfully mapped or no mapping needed
                    key = (nba_team_abbr, row['player_lookup'])  # Use NBA team code
                    
                    # FIXED: Warn about overwrites (this should not happen with proper season filtering)
                    if key in enhancement_data:
                        logger.warning(f"Overwriting enhancement data for {key}: season {enhancement_data[key]['season_year']} → {row['season_year']}")
                    
                    enhancement_data[key] = {
                        'original_name': row['original_name'],
                        'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                        'position': row['position'] if pd.notna(row['position']) else None,
                        'season_year': row['season_year']
                    }
                    
                    # DEBUG: Log our problem case
                    if key == ('HOU', 'kjmartin'):
                        logger.info(f"DEBUG: Added HOU kjmartin enhancement: season_year={row['season_year']}, jersey={row['jersey_number']}")
                    
                else:  # Failed to map
                    unmapped_teams.add(br_team_abbr)
                    logger.warning(f"Could not map team code: {br_team_abbr}")
            
            # Summary logging
            logger.info(f"Loaded enhancement data for {len(enhancement_data)} player-team combinations")
            logger.info(f"Applied team mapping to {mapped_count} records")
            
            # DEBUG: Verify our problem case
            hou_kjmartin_key = ('HOU', 'kjmartin')
            if hou_kjmartin_key in enhancement_data:
                logger.info(f"DEBUG: ✅ Final enhancement data contains {hou_kjmartin_key}: {enhancement_data[hou_kjmartin_key]}")
            else:
                logger.info(f"DEBUG: ❌ Final enhancement data missing {hou_kjmartin_key}")
            
            if team_mapping_log:
                logger.info(f"Team mappings applied: {team_mapping_log}")
            
            if unmapped_teams:
                logger.warning(f"Unmapped team codes: {sorted(unmapped_teams)}")
            
            return enhancement_data
            
        except Exception as e:
            logger.error(f"Error loading roster enhancement data: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {}

    def _convert_pandas_types_for_json(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert pandas/numpy types to BigQuery-compatible types.
        """
        converted_record = {}
        
        # Define fields that should be integers (even if they come as strings)
        integer_fields = {'games_played', 'total_appearances', 'inactive_appearances', 
                'dnp_appearances', 'jersey_number', 'occurrences'}
        
        for key, value in record.items():
            # Handle NaN/None values first
            if pd.isna(value):
                converted_record[key] = None
            
            # Handle numpy scalars
            elif hasattr(value, 'item'):  
                converted_record[key] = value.item()
            
            # Handle datetime objects - convert to strings for BigQuery TIMESTAMP
            elif isinstance(value, (pd.Timestamp, datetime)):
                if pd.notna(value):
                    converted_record[key] = value.isoformat()
                else:
                    converted_record[key] = None
            
            # Handle date objects - convert to strings for BigQuery DATE
            elif isinstance(value, date):
                converted_record[key] = value.isoformat()
            
            # Handle string values that should be integers (like jersey_number)
            elif key in integer_fields and isinstance(value, str):
                try:
                    # Convert string numbers to integers
                    converted_record[key] = int(value) if value.strip() else None
                except (ValueError, AttributeError):
                    converted_record[key] = None
            
            # Handle numpy/pandas integer types
            elif isinstance(value, (np.integer, int)) or (hasattr(value, 'dtype') and np.issubdtype(value.dtype, np.integer)):
                converted_record[key] = int(value)
            
            # Handle numpy/pandas float types  
            elif isinstance(value, (np.floating, float)) or (hasattr(value, 'dtype') and np.issubdtype(value.dtype, np.floating)):
                converted_record[key] = float(value)
            
            # Handle numpy/pandas boolean types
            elif isinstance(value, (np.bool_, bool)) or (hasattr(value, 'dtype') and np.issubdtype(value.dtype, np.bool_)):
                converted_record[key] = bool(value)
            
            # Handle pandas Series scalars (common with .get() operations)
            elif isinstance(value, pd.Series) and len(value) == 1:
                scalar_value = value.iloc[0]
                converted_record[key] = self._convert_pandas_types_for_json({'temp': scalar_value})['temp']
            
            # Handle regular Python types (pass through)
            else:
                converted_record[key] = value
        
        return converted_record
    
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
        
        # Aggregate into registry records, passing date_range for BR filtering
        registry_records = self.aggregate_player_stats(gamebook_df, date_range=date_range)
        
        return registry_records
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load registry data to BigQuery with proper deduplication logic."""
        if not rows:
            logger.info("No records to insert")
            return {'rows_processed': 0, 'errors': []}
        
        # Debug: Log the first record to see exact format
        logger.info(f"Sample record being sent to BigQuery:")
        logger.info(f"Record keys: {list(rows[0].keys())}")
        logger.info(f"Sample record: {json.dumps(rows[0], indent=2, default=str)}")
        
        # Validate required fields
        required_fields = ['player_name', 'player_lookup', 'team_abbr', 'season', 'created_at', 'processed_at', 'created_by']
        for field in required_fields:
            if field not in rows[0]:
                logger.error(f"Missing required field: {field}")
                return {'rows_processed': 0, 'errors': [f'Missing required field: {field}']}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        total_inserted = 0
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # FIXED: Delete based on player-team-season combinations, not date ranges
                combinations_to_update = set()
                for row in rows:
                    combination = (row['player_lookup'], row['team_abbr'], row['season'])
                    combinations_to_update.add(combination)
                
                if combinations_to_update:
                    # Build WHERE clause for each combination
                    where_conditions = []
                    for player_lookup, team_abbr, season in combinations_to_update:
                        where_conditions.append(
                            f"(player_lookup = '{player_lookup}' AND team_abbr = '{team_abbr}' AND season = '{season}')"
                        )
                    
                    where_clause = " OR ".join(where_conditions)
                    
                    delete_query = f"""
                    DELETE FROM `{table_id}`
                    WHERE {where_clause}
                    """
                    
                    self.bq_client.query(delete_query).result()
                    logger.info(f"Deleted existing registry data for {len(combinations_to_update)} player-team-season combinations")
            
            # Insert in smaller batches to isolate issues
            batch_size = 10  # Start small
            total_errors = 0
            
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i + batch_size]
                logger.info(f"Inserting batch {i//batch_size + 1}: records {i+1}-{min(i+batch_size, len(rows))}")
                
                result = self.bq_client.insert_rows_json(table_id, batch)
                
                if result:
                    logger.error(f"Batch {i//batch_size + 1} errors: {result}")
                    total_errors += len(result)
                    errors.extend([str(e) for e in result])
                    
                    # Log the first few problematic records
                    for j, error in enumerate(result[:3]):
                        if j < len(batch):
                            logger.error(f"Problematic record {i+j+1}: {json.dumps(batch[j], indent=2, default=str)}")
                else:
                    logger.info(f"Batch {i//batch_size + 1} inserted successfully")
                    total_inserted += len(batch)
            
            logger.info(f"Insertion complete. Success: {total_inserted}, Errors: {total_errors}, Total: {len(rows)}")
            
            if total_inserted > 0:
                self.stats['records_created'] = total_inserted
                
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error loading registry data: {error_msg}")
            logger.error(f"Sample record that failed: {json.dumps(rows[0], indent=2, default=str)}")
        
        return {
            'rows_processed': total_inserted,
            'errors': errors
        }
    
    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """
        Scenario 1: Build registry from 4 years of historical data.
        
        Args:
            seasons: Optional list of seasons to process, defaults to all available
            
        Returns:
            Processing result summary
        """
        logger.info("Starting historical registry build")
        
        if not seasons:
            # Debug environment and query construction
            logger.info("=== DEBUGGING SEASONS QUERY ===")
            logger.info(f"os.environ.get('GCP_PROJECT_ID'): {os.environ.get('GCP_PROJECT_ID')}")
            logger.info(f"self.bq_client.project: {self.bq_client.project}")
            logger.info(f"self.project_id: {self.project_id}")
            
            # Get all available seasons from gamebook data
            seasons_query = f"""
                SELECT DISTINCT season_year
                FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
                WHERE season_year IS NOT NULL
                ORDER BY season_year DESC
            """
            
            # Debug the constructed query
            logger.info(f"Raw seasons_query: {repr(seasons_query)}")
            logger.info(f"Seasons query:\n{seasons_query}")
            logger.info(f"Query length: {len(seasons_query)}")
            logger.info("=== END DEBUGGING ===")
            
            try:
                seasons_df = self.bq_client.query(seasons_query).to_dataframe()
                logger.info(f"Query successful, got {len(seasons_df)} seasons")
            except Exception as e:
                logger.error(f"Query failed with error: {e}")
                logger.error(f"Error type: {type(e)}")
                # Fallback to hardcoded seasons
                logger.info("Falling back to hardcoded seasons")
                seasons = ["2021-22", "2022-23", "2023-24", "2024-25"]
                return self._run_hardcoded_seasons(seasons)
            
            seasons = [f"{int(row['season_year'])}-{str(int(row['season_year']) + 1)[-2:]}" 
                    for _, row in seasons_df.iterrows()]
        
        logger.info(f"Building historical registry for seasons: {seasons}")
        
        total_results = []
        for season in seasons:
            logger.info(f"Processing season {season}")
            result = self.build_registry_for_season(season)
            total_results.append(result)
        
        # Summary
        total_records = sum(r.get('records_processed', 0) for r in total_results)
        total_errors = sum(len(r.get('errors', [])) for r in total_results)
        
        return {
            'scenario': 'historical_backfill',
            'seasons_processed': seasons,
            'total_records_processed': total_records,
            'total_errors': total_errors,
            'individual_results': total_results,
            'processing_run_id': self.processing_run_id
        }
    
    def update_registry_from_gamebook(self, game_date: str, season: str) -> Dict:
        """
        Scenario 2: Nightly update after gamebook processing.
        
        Args:
            game_date: Date of games processed (YYYY-MM-DD)
            season: Season string ("2024-25")
            
        Returns:
            Processing result summary
        """
        logger.info(f"Updating registry from gamebook data for {game_date}, season {season}")
        
        # Use date range approach for recent games
        filter_data = {
            'season_filter': season,
            'date_range': (game_date, game_date)
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)
        
        return {
            'scenario': 'nightly_gamebook_update',
            'game_date': game_date,
            'season': season,
            'records_processed': result['rows_processed'],
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }
    
    def update_registry_from_rosters(self, season: str, teams: List[str] = None) -> Dict:
        """
        Scenario 3: Morning update after roster scraping.
        
        Args:
            season: Current season ("2024-25")
            teams: Optional list of teams to update, defaults to all
            
        Returns:
            Processing result summary
        """
        logger.info(f"Updating registry from roster data for season {season}")
        
        if teams:
            # Update specific teams
            total_results = []
            for team in teams:
                filter_data = {
                    'season_filter': season,
                    'team_filter': team
                }
                rows = self.transform_data(filter_data)
                result = self.load_data(rows)
                total_results.append({
                    'team': team,
                    'records_processed': result['rows_processed'],
                    'errors': result.get('errors', [])
                })
            
            total_records = sum(r['records_processed'] for r in total_results)
            total_errors = sum(len(r['errors']) for r in total_results)
            
            return {
                'scenario': 'morning_roster_update',
                'season': season,
                'teams_updated': teams,
                'total_records_processed': total_records,
                'total_errors': total_errors,
                'team_results': total_results,
                'processing_run_id': self.processing_run_id
            }
        else:
            # Update entire season
            result = self.build_registry_for_season(season)
            result['scenario'] = 'morning_roster_update'
            return result
    
    def build_registry_for_season(self, season: str, team: str = None) -> Dict:
        """Build registry for a specific season."""
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
        logger.info(f"  Alias resolutions: {self.stats['alias_resolutions']}")
        logger.info(f"  Unresolved found: {self.stats['unresolved_players_found']}")
        logger.info(f"  Errors: {len(result.get('errors', []))}")
        
        return {
            'season': season,
            'team_filter': team,
            'records_processed': result['rows_processed'],
            'players_processed': self.stats['players_processed'],
            'teams_processed': list(self.stats['teams_processed']),
            'alias_resolutions': self.stats['alias_resolutions'],
            'unresolved_found': self.stats['unresolved_players_found'],
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }
    
    def build_registry_for_date_range(self, start_date: str, end_date: str) -> Dict:
        """Build registry for a specific date range across seasons."""
        logger.info(f"Building registry for date range {start_date} to {end_date}")
        
        # Create filter data
        filter_data = {
            'date_range': (start_date, end_date)
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)
        
        # Determine which seasons were covered
        seasons_processed = set()
        if rows:
            for row in rows:
                seasons_processed.add(row['season'])
        
        # Log summary
        logger.info(f"Registry build complete for {start_date} to {end_date}:")
        logger.info(f"  Records processed: {result['rows_processed']}")
        logger.info(f"  Players: {self.stats['players_processed']}")
        logger.info(f"  Seasons covered: {len(seasons_processed)}")
        logger.info(f"  Teams: {len(self.stats['teams_processed'])}")
        logger.info(f"  Alias resolutions: {self.stats['alias_resolutions']}")
        logger.info(f"  Unresolved found: {self.stats['unresolved_players_found']}")
        logger.info(f"  Errors: {len(result.get('errors', []))}")
        
        return {
            'date_range': (start_date, end_date),
            'records_processed': result['rows_processed'],
            'players_processed': self.stats['players_processed'],
            'seasons_processed': list(seasons_processed),
            'teams_processed': list(self.stats['teams_processed']),
            'alias_resolutions': self.stats['alias_resolutions'],
            'unresolved_found': self.stats['unresolved_players_found'],
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
                MAX(processed_at) as last_updated
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
def build_historical_registry(seasons: List[str] = None) -> Dict:
    """Convenience function for 4-year backfill."""
    processor = NbaPlayersRegistryProcessor()
    return processor.build_historical_registry(seasons)


def update_registry_from_gamebook(game_date: str, season: str) -> Dict:
    """Convenience function for nightly updates."""
    processor = NbaPlayersRegistryProcessor()
    return processor.update_registry_from_gamebook(game_date, season)


def update_registry_from_rosters(season: str, teams: List[str] = None) -> Dict:
    """Convenience function for morning roster updates."""
    processor = NbaPlayersRegistryProcessor()
    return processor.update_registry_from_rosters(season, teams)


def get_registry_summary() -> Dict:
    """Convenience function to get registry summary."""
    processor = NbaPlayersRegistryProcessor()
    return processor.get_registry_summary()