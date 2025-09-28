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
from enum import Enum
from datetime import timezone
import time

# Fixed import path for new structure
from data_processors.raw.processor_base import ProcessorBase
from shared.utils.player_name_normalizer import normalize_name_for_lookup
from shared.utils.universal_player_id_resolver import UniversalPlayerIDResolver
# from shared.utils.nba_team_mapper import nba_team_mapper

logger = logging.getLogger(__name__)


class ProcessingStrategy(Enum):
    REPLACE = "replace"  # DELETE + INSERT (current implementation)  
    MERGE = "merge"      # MERGE statement (new implementation)

class NbaPlayersRegistryProcessor(ProcessorBase):
    """
    Build and maintain the NBA players registry from gamebook data.
    
    This processor creates the authoritative player registry by analyzing
    NBA.com gamebook data to determine:
    - Which players actually played for which teams in which seasons
    - Game participation statistics
    - Jersey numbers and positions (when available)
    """
    
    def __init__(self, test_mode: bool = False, strategy: str = "merge", confirm_full_delete: bool = False):
        super().__init__()
    
        # Configure processing strategy
        self.processing_strategy = ProcessingStrategy(strategy.lower())
        self.confirm_full_delete = confirm_full_delete
        
        # Safety check for REPLACE mode
        if self.processing_strategy == ProcessingStrategy.REPLACE and not confirm_full_delete:
            raise ValueError(
                "REPLACE strategy requires --confirm-full-delete flag to prevent accidental data loss. "
                "This will DELETE entire tables and rebuild from scratch. "
                "Use 'merge' strategy for incremental updates, or add --confirm-full-delete if full rebuild is intended."
            )
        
        if self.processing_strategy == ProcessingStrategy.REPLACE and confirm_full_delete:
            logger.warning("🚨 REPLACE mode with FULL DELETE confirmation - this will rebuild tables from scratch")
            logger.warning("Main registry will be completely rebuilt")
            logger.warning("Unresolved players table will be completely rebuilt") 
        
        logger.info(f"Initialized with processing strategy: {self.processing_strategy.value}")
        
        # Rest of existing initialization code...
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

        self.players_seen_this_run = set()  # Track players seen this run
        self.universal_id_resolver = UniversalPlayerIDResolver(self.bq_client, self.project_id)
        
        # Reset tracking for universal ID assignments
        self.new_players_discovered = set()  # Track new players this run
        
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
        # Add around the main query:
        query_start = time.time()
        logger.info(f"PERF_METRIC: gamebook_query_start season={season_filter} team={team_filter}")
        
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
            query_duration = time.time() - query_start
            logger.info(f"PERF_METRIC: gamebook_query_complete duration={query_duration:.3f}s rows_returned={len(results)}")
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

            # NEW: Use utility to resolve/assign universal ID
            try:
                # Better approach - let the resolver track new players
                universal_id = self.universal_id_resolver.resolve_or_create_universal_id(player_lookup)

                # Check if resolver created a new ID (you'd need to modify the utility to track this)
                # OR simpler: check if this canonical player wasn't seen before in this run
                canonical_name = self.universal_id_resolver.get_canonical_player_name(player_lookup)
                if canonical_name not in self.players_seen_this_run:
                    self.new_players_discovered.add(canonical_name)
                self.players_seen_this_run.add(canonical_name)
                    
            except Exception as e:
                logger.error(f"Error resolving universal ID for {player_lookup}: {e}")
                # Fallback: create simple ID to prevent failure
                universal_id = f"{player_lookup}_001"
            
            # Create registry record with proper timestamp fields
            record = {
                'universal_player_id': universal_id,
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
        """Insert unresolved player records respecting the processing strategy."""
        if not unresolved_records:
            return
        
        # Group by key fields to deduplicate within this run (existing logic)
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
            logger.info(f"Within-run deduplication: {len(unresolved_records)} → {len(deduplicated_records)} records")
        
        # Convert types for BigQuery
        processed_records = []
        for record in deduplicated_records:
            processed_record = self._convert_pandas_types_for_json(record)
            processed_records.append(processed_record)
        
        # Respect the main processing strategy for consistency
        if self.processing_strategy == ProcessingStrategy.REPLACE:
            logger.info(f"Using REPLACE strategy for {len(processed_records)} unresolved players")
            self._replace_unresolved_players(processed_records)
        else:
            logger.info(f"Using MERGE strategy for {len(processed_records)} unresolved players") 
            self._merge_unresolved_players(processed_records)

    def _replace_unresolved_players(self, processed_records: List[Dict]):
        """REPLACE mode: DELETE existing unresolved players + INSERT new ones."""
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        
        try:
            # Step 1: Delete existing records
            logger.info(f"Deleting existing unresolved players from {self.unresolved_table_name}")
            delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
            delete_job = self.bq_client.query(delete_query)
            delete_result = delete_job.result()
            deleted_count = delete_job.num_dml_affected_rows or 0
            logger.info(f"Deleted {deleted_count} existing unresolved player records")
            
            # Step 2: Insert new records
            if processed_records:
                logger.info(f"Inserting {len(processed_records)} new unresolved player records")
                insert_errors = self.bq_client.insert_rows_json(table_id, processed_records)
                
                if insert_errors:
                    logger.error(f"Unresolved players insertion errors: {insert_errors}")
                else:
                    logger.info(f"Successfully inserted {len(processed_records)} unresolved player records")
            else:
                logger.info("No new unresolved players to insert")
                
        except Exception as e:
            logger.error(f"Error in REPLACE mode for unresolved players: {e}")

    def _merge_unresolved_players(self, processed_records: List[Dict]):
        """
        MERGE mode: Schema-enforced approach with graceful streaming buffer failure.
        Enhanced with performance metrics for monitoring and optimization.
        """
        if not processed_records:
            return
        
        # PERF: Overall operation timing
        operation_start = time.time()
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        temp_table_id = None
        
        logger.info(f"PERF_METRIC: unresolved_merge_start record_count={len(processed_records)} operation_id={uuid.uuid4().hex[:8]}")
        
        try:
            # PERF: Table creation timing
            table_creation_start = time.time()
            
            # Create temporary table for MERGE operation
            import uuid
            temp_table_suffix = uuid.uuid4().hex[:8]
            temp_table_id = f"{table_id}_temp_{temp_table_suffix}"
            
            logger.info(f"Creating temporary table: {temp_table_id}")
            
            # Get main table schema
            schema_fetch_start = time.time()
            main_table = self.bq_client.get_table(table_id)
            schema_fetch_duration = time.time() - schema_fetch_start
            
            logger.info(f"PERF_METRIC: schema_fetch_duration={schema_fetch_duration:.3f}s table={table_id}")
            
            # Debug: Log REQUIRED fields to understand schema expectations
            required_fields = [(f.name, f.field_type) for f in main_table.schema if f.mode == "REQUIRED"]
            logger.info(f"Target table REQUIRED fields: {required_fields}")
            
            # Create temp table with identical schema
            temp_table = bigquery.Table(temp_table_id, schema=main_table.schema)
            temp_table = self.bq_client.create_table(temp_table)
            
            table_creation_duration = time.time() - table_creation_start
            logger.info(f"PERF_METRIC: temp_table_creation_duration={table_creation_duration:.3f}s table_id={temp_table_id}")
            
            # Get required field names for validation
            required_field_names = {f.name for f in main_table.schema if f.mode == "REQUIRED"}
            
            def ensure_required_defaults(rec: dict) -> dict:
                """Ensure all REQUIRED fields have non-null values."""
                out = dict(rec)
                current_utc = datetime.now(timezone.utc)
                current_date = current_utc.date()
                
                # Handle common REQUIRED fields based on typical unresolved_players schema
                if "created_at" in required_field_names and out.get("created_at") is None:
                    out["created_at"] = current_utc
                    logger.debug("Set default created_at for REQUIRED field")
                    
                if "processed_at" in required_field_names and out.get("processed_at") is None:
                    out["processed_at"] = current_utc
                    logger.debug("Set default processed_at for REQUIRED field")
                    
                if "first_seen_date" in required_field_names and out.get("first_seen_date") is None:
                    out["first_seen_date"] = current_date
                    logger.debug("Set default first_seen_date for REQUIRED field")
                    
                if "last_seen_date" in required_field_names and out.get("last_seen_date") is None:
                    out["last_seen_date"] = current_date
                    logger.debug("Set default last_seen_date for REQUIRED field")
                    
                if "occurrences" in required_field_names and out.get("occurrences") is None:
                    out["occurrences"] = 1
                    logger.debug("Set default occurrences for REQUIRED field")
                    
                if "status" in required_field_names and out.get("status") is None:
                    out["status"] = "pending"
                    logger.debug("Set default status for REQUIRED field")
                    
                if "example_games" in required_field_names and out.get("example_games") is None:
                    out["example_games"] = []
                    logger.debug("Set default example_games for REQUIRED field")
                
                return out
            
            # PERF: Data preparation timing
            data_prep_start = time.time()
            
            # Prepare records with schema enforcement
            converted_records = []
            for record in processed_records:
                # Convert pandas types but keep native datetime objects
                r = self._convert_pandas_types_for_json(record, for_table_load=True)
                
                # Handle NULLABLE reviewed_at properly (keep as None, don't remove)
                if r.get("reviewed_at") is None:
                    r["reviewed_at"] = None  # Explicit None for NULLABLE field
                
                # Ensure all REQUIRED fields have values
                r = ensure_required_defaults(r)
                
                converted_records.append(r)
            
            data_prep_duration = time.time() - data_prep_start
            logger.info(f"PERF_METRIC: data_preparation_duration={data_prep_duration:.3f}s record_count={len(converted_records)}")
            
            # PERF: Data loading timing
            load_start = time.time()
            
            # Load with enforced schema (ChatGPT's key insight)
            job_config = bigquery.LoadJobConfig(
                schema=main_table.schema,  # Force exact schema match
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                autodetect=False,  # Critical: no schema inference
                ignore_unknown_values=True
            )
            
            logger.info(f"Loading {len(converted_records)} records with enforced schema")
            load_job = self.bq_client.load_table_from_json(
                converted_records, 
                temp_table_id, 
                job_config=job_config
            )
            load_result = load_job.result()
            
            load_duration = time.time() - load_start
            rows_loaded = load_job.output_rows or len(converted_records)
            
            logger.info(f"PERF_METRIC: data_load_duration={load_duration:.3f}s rows_loaded={rows_loaded} bytes_processed={load_job.input_files or 0}")
            
            # PERF: MERGE operation timing
            merge_start = time.time()
            
            # Execute MERGE with REQUIRED field safety
            logger.info("Executing schema-safe MERGE operation")
            merge_query = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON target.normalized_lookup = source.normalized_lookup 
            AND target.team_abbr = source.team_abbr 
            AND target.season = source.season
            AND target.source = source.source
            WHEN MATCHED THEN 
            UPDATE SET 
                occurrences = target.occurrences + source.occurrences,
                last_seen_date = GREATEST(target.last_seen_date, source.last_seen_date),
                notes = CASE 
                    WHEN COALESCE(target.notes, '') != COALESCE(source.notes, '')
                    THEN CONCAT(COALESCE(target.notes, ''), '; ', COALESCE(source.notes, ''))
                    ELSE COALESCE(target.notes, source.notes)
                END,
                processed_at = source.processed_at
            WHEN NOT MATCHED THEN 
            INSERT (
                source, original_name, normalized_lookup, first_seen_date, last_seen_date,
                team_abbr, season, occurrences, example_games, status, resolution_type,
                resolved_to_name, notes, reviewed_by, reviewed_at, created_at, processed_at
            )
            VALUES (
                source.source, source.original_name, source.normalized_lookup, 
                source.first_seen_date, source.last_seen_date, source.team_abbr, source.season,
                source.occurrences, source.example_games, source.status, source.resolution_type,
                source.resolved_to_name, source.notes, source.reviewed_by, source.reviewed_at,
                COALESCE(source.created_at, CURRENT_TIMESTAMP()), source.processed_at
            )
            """
            
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            
            merge_duration = time.time() - merge_start
            num_affected = merge_job.num_dml_affected_rows or 0
            bytes_processed = merge_job.total_bytes_processed or 0
            
            logger.info(f"PERF_METRIC: merge_operation_duration={merge_duration:.3f}s rows_affected={num_affected} bytes_processed={bytes_processed}")
            
            # PERF: Overall success timing
            total_duration = time.time() - operation_start
            
            logger.info(f"PERF_METRIC: unresolved_merge_success total_duration={total_duration:.3f}s records_processed={len(processed_records)} rows_affected={num_affected}")
            logger.info("Schema-enforced MERGE strategy completed successfully")
            
        except Exception as e:
            # PERF: Error timing
            error_duration = time.time() - operation_start
            error_type = type(e).__name__
            
            logger.error(f"PERF_METRIC: unresolved_merge_error duration={error_duration:.3f}s error_type={error_type}")
            logger.error(f"Schema-enforced MERGE strategy failed: {str(e)}")
            
            # Check if this is a streaming buffer issue
            if "streaming buffer" in str(e).lower():
                logger.warning(f"PERF_METRIC: streaming_buffer_conflict duration={error_duration:.3f}s records_skipped={len(processed_records)}")
                logger.warning(f"MERGE blocked by streaming buffer - {len(processed_records)} unresolved players skipped this run")
                logger.info("Records will be processed on the next run when streaming buffer clears")
                logger.info("This is expected behavior and will resolve automatically")
            else:
                # Re-raise non-streaming-buffer errors (genuine problems we need to fix)
                logger.error(f"MERGE failed with non-streaming-buffer error: {str(e)}")
                raise e
                
        finally:
            # PERF: Cleanup timing
            cleanup_start = time.time()
            
            # Always clean up temporary table, regardless of success or failure
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    cleanup_duration = time.time() - cleanup_start
                    logger.info(f"PERF_METRIC: cleanup_duration={cleanup_duration:.3f}s temp_table={temp_table_id}")
                except Exception as cleanup_error:
                    cleanup_duration = time.time() - cleanup_start
                    logger.warning(f"PERF_METRIC: cleanup_error duration={cleanup_duration:.3f}s error={str(cleanup_error)}")
            
            # PERF: Final summary
            final_duration = time.time() - operation_start
            logger.info(f"PERF_METRIC: unresolved_merge_complete total_duration={final_duration:.3f}s input_records={len(processed_records)}")

    def _insert_unresolved_players_temp_table(self, processed_records: List[Dict], table_id: str):
        """Fallback method using temporary table approach for unresolved players."""
        import uuid
        temp_table_suffix = uuid.uuid4().hex[:8]
        temp_table_id = f"{table_id}_temp_{temp_table_suffix}"
        
        try:
            logger.info(f"Using temporary table approach for unresolved players: {temp_table_id}")
            
            # Get main table schema
            main_table = self.bq_client.get_table(table_id)
            
            # Create temp table with same schema
            temp_table = bigquery.Table(temp_table_id, schema=main_table.schema)
            temp_table = self.bq_client.create_table(temp_table)
            
            # Load data to temp table
            load_job = self.bq_client.load_table_from_json(processed_records, temp_table_id)
            load_result = load_job.result()
            
            # MERGE from temp table
            merge_query = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON target.normalized_lookup = source.normalized_lookup 
            AND target.team_abbr = source.team_abbr 
            AND target.season = source.season
            WHEN MATCHED THEN 
            UPDATE SET 
                occurrences = target.occurrences + source.occurrences,
                last_seen_date = GREATEST(target.last_seen_date, source.last_seen_date),
                notes = CASE 
                    WHEN target.notes != source.notes 
                    THEN CONCAT(target.notes, '; ', source.notes)
                    ELSE target.notes 
                END,
                processed_at = source.processed_at
            WHEN NOT MATCHED THEN 
            INSERT (
                source, original_name, normalized_lookup, first_seen_date, last_seen_date,
                team_abbr, season, occurrences, example_games, status, resolution_type,
                resolved_to_name, notes, reviewed_by, reviewed_at, created_at, processed_at
            )
            VALUES (
                source.source, source.original_name, source.normalized_lookup, 
                source.first_seen_date, source.last_seen_date, source.team_abbr, source.season,
                source.occurrences, source.example_games, source.status, source.resolution_type,
                source.resolved_to_name, source.notes, source.reviewed_by, source.reviewed_at,
                source.created_at, source.processed_at
            )
            """
            
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            
            num_affected = merge_job.num_dml_affected_rows or 0
            logger.info(f"Temporary table approach succeeded: {num_affected} rows affected")
            
        except Exception as e:
            logger.error(f"Temporary table approach also failed: {e}")
            # Final fallback to original INSERT method (will create duplicates but won't crash)
            logger.warning("Using original INSERT method - will create duplicates")
            result = self.bq_client.insert_rows_json(table_id, processed_records)
            if result:
                logger.error(f"INSERT fallback errors: {result}")
            else:
                logger.info(f"INSERT fallback succeeded for {len(processed_records)} records")
                
        finally:
            # Cleanup temp table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.info("Temp table cleaned up successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp table: {cleanup_error}")

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
            
            enhancement_start = time.time()
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            enhancement_duration = time.time() - enhancement_start
            logger.info(f"PERF_METRIC: enhancement_data_duration={enhancement_duration:.3f}s rows_returned={len(results)}")
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

    def _convert_pandas_types_for_json(self, record: Dict[str, Any], for_table_load: bool = False) -> Dict[str, Any]:
        """
        Convert pandas/numpy types to BigQuery-compatible types.
        
        Args:
            record: Dictionary with potentially problematic pandas/numpy types
            for_table_load: If True, prepare for load_table_from_json (preserve datetime objects)
                        If False, prepare for insert_rows_json (convert to strings)
        """
        converted_record = {}
        
        # Define fields that should be integers (even if they come as strings)
        integer_fields = {'games_played', 'total_appearances', 'inactive_appearances', 
                'dnp_appearances', 'jersey_number', 'occurrences'}
        
        # Define TIMESTAMP fields that need special handling
        timestamp_fields = {'created_at', 'processed_at', 'reviewed_at'}
        
        for key, value in record.items():
            # Handle NaN/None values first
            if pd.isna(value):
                converted_record[key] = None
            
            # Handle numpy scalars
            elif hasattr(value, 'item'):  
                converted_record[key] = value.item()
            
            # Handle datetime objects - different logic based on usage
            elif isinstance(value, (pd.Timestamp, datetime)):
                if pd.notna(value):
                    if for_table_load and key in timestamp_fields:
                        # For load_table_from_json: keep as datetime object
                        converted_record[key] = value
                    else:
                        # For insert_rows_json: convert to ISO string
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
                converted_record[key] = self._convert_pandas_types_for_json({'temp': scalar_value}, for_table_load)['temp']
            
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
        """Load registry data using configured processing strategy."""
        if not rows:
            logger.info("No records to insert")
            return {'rows_processed': 0, 'errors': []}
        
        if self.processing_strategy == ProcessingStrategy.REPLACE:
            return self._load_data_replace_mode(rows, **kwargs)
        elif self.processing_strategy == ProcessingStrategy.MERGE:
            return self._load_data_merge_mode(rows, **kwargs)
        else:
            raise ValueError(f"Unknown processing strategy: {self.processing_strategy}")
    
    def _load_data_replace_mode(self, rows: List[Dict], **kwargs) -> Dict:
        """REPLACE mode: DELETE existing data + INSERT new data."""
        logger.info(f"Using REPLACE mode for {len(rows)} records")
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Step 1: Delete with better error handling
            logger.info(f"Step 1: Deleting existing records from {self.table_name}")
            delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
            delete_job = self.bq_client.query(delete_query)
            delete_result = delete_job.result()
            deleted_count = delete_job.num_dml_affected_rows or 0
            logger.info(f"Deleted {deleted_count} existing records")
            
            # Step 2: Insert with detailed batch logging
            logger.info(f"Step 2: Inserting {len(rows)} new records")
            rows_to_insert = [self._convert_pandas_types_for_json(row) for row in rows]
            
            batch_size = 1000
            total_inserted = 0
            batch_count = (len(rows_to_insert) + batch_size - 1) // batch_size
            
            for i in range(0, len(rows_to_insert), batch_size):
                batch = rows_to_insert[i:i+batch_size]
                batch_num = i//batch_size + 1
                
                logger.info(f"Inserting batch {batch_num}/{batch_count}: {len(batch)} records")
                insert_errors = self.bq_client.insert_rows_json(table_id, batch)
                
                if insert_errors:
                    error_msg = f"Batch {batch_num} insertion errors: {insert_errors}"
                    logger.error(error_msg)
                    errors.extend(insert_errors)
                else:
                    total_inserted += len(batch)
                    logger.info(f"✅ Batch {batch_num} success: {len(batch)} records")
            
            logger.info(f"REPLACE mode completed: {total_inserted}/{len(rows)} records inserted")
            
            return {
                'rows_processed': total_inserted,
                'errors': errors
            }
            
        except Exception as e:
            error_msg = f"REPLACE mode failed: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            
            return {
                'rows_processed': 0,
                'errors': errors
            }
        
    def _load_data_merge_mode(self, rows: List[Dict], **kwargs) -> Dict:
        """
        MERGE mode: MERGE data atomically using temporary table approach.
        
        This avoids STRUCT parameter complexity by:
        1. Creating temporary table with same schema
        2. Loading data to temp table (handles type conversion gracefully)
        3. MERGE from temp table to main table (no STRUCT parameters)
        4. Cleanup temp table
        
        Used for production operations with potential concurrent access.
        """
        logger.info(f"Using MERGE mode (temp table approach) for {len(rows)} records")
        # Add at start:
        operation_start = time.time()
        logger.info(f"PERF_METRIC: main_registry_merge_start record_count={len(rows)}")
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        temp_table_id = None
        
        try:
            # Step 1: Create temporary table with same schema as main table
            import uuid
            temp_table_suffix = uuid.uuid4().hex[:8]
            temp_table_id = f"{table_id}_temp_{temp_table_suffix}"
            
            logger.info(f"Creating temporary table: {temp_table_id}")
            
            # Get main table schema
            main_table = self.bq_client.get_table(table_id)
            
            # Create temp table with same schema
            temp_table = bigquery.Table(temp_table_id, schema=main_table.schema)
            temp_table = self.bq_client.create_table(temp_table)
            
            logger.info(f"✅ Temporary table created successfully")
            
            # Step 2: Load data to temp table using load_table_from_json
            # This handles type conversion gracefully without STRUCT parameters
            logger.info(f"Loading {len(rows)} records to temporary table")
            
            # Convert rows for BigQuery (this should work fine with load_table_from_json)
            rows_for_loading = [self._convert_pandas_types_for_json(row) for row in rows]
            
            # Load to temp table - this is much more robust than STRUCT parameters
            load_job = self.bq_client.load_table_from_json(
                rows_for_loading, 
                temp_table_id,
                job_config=bigquery.LoadJobConfig(
                    # Let BigQuery auto-detect and handle schema matching
                    autodetect=False,  # We're using the explicit schema from main table
                    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
                )
            )
            
            # Wait for load job to complete
            load_result = load_job.result()
            logger.info(f"✅ Data loaded to temp table: {load_job.output_rows} rows")
            
            # Step 3: MERGE from temp table to main table
            # This avoids all STRUCT parameter issues entirely
            logger.info("Executing MERGE from temporary table to main table")
            
            merge_query = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON target.player_lookup = source.player_lookup 
            AND target.team_abbr = source.team_abbr 
            AND target.season = source.season
            WHEN MATCHED THEN
            UPDATE SET 
                universal_player_id = source.universal_player_id,  -- ADD THIS LINE
                player_name = source.player_name,
                first_game_date = source.first_game_date,
                last_game_date = source.last_game_date,
                games_played = source.games_played,
                total_appearances = source.total_appearances,
                inactive_appearances = source.inactive_appearances,
                dnp_appearances = source.dnp_appearances,
                jersey_number = source.jersey_number,
                position = source.position,
                last_roster_update = source.last_roster_update,
                source_priority = source.source_priority,
                confidence_score = source.confidence_score,
                processed_at = source.processed_at
            WHEN NOT MATCHED THEN
            INSERT (
                universal_player_id, player_name, player_lookup, team_abbr, season, first_game_date,  -- ADD universal_player_id
                last_game_date, games_played, total_appearances, inactive_appearances,
                dnp_appearances, jersey_number, position, last_roster_update,
                source_priority, confidence_score, created_by, created_at, processed_at
            )
            VALUES (
                source.universal_player_id, source.player_name, source.player_lookup, source.team_abbr, source.season,  -- ADD universal_player_id
                source.first_game_date, source.last_game_date, source.games_played,
                source.total_appearances, source.inactive_appearances, source.dnp_appearances,
                source.jersey_number, source.position, source.last_roster_update,
                source.source_priority, source.confidence_score, source.created_by,
                source.created_at, source.processed_at
            )
            """
            
            # Execute MERGE - no query parameters needed!
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            
            # Get merge statistics
            num_dml_affected_rows = merge_job.num_dml_affected_rows or 0
            logger.info(f"✅ MERGE completed successfully: {num_dml_affected_rows} rows affected")
            
            total_duration = time.time() - operation_start
            logger.info(f"PERF_METRIC: main_registry_merge_complete duration={total_duration:.3f}s records_processed={len(rows)}")
            return {
                'rows_processed': num_dml_affected_rows,
                'errors': []
            }
            
        except Exception as e:
            error_msg = f"MERGE mode (temp table) failed: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
            
            # Log more details for debugging
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
            errors.append(error_msg)
            
            return {
                'rows_processed': 0,
                'errors': errors
            }
            
        finally:
            # Step 4: Always cleanup temp table
            if temp_table_id:
                try:
                    logger.info(f"Cleaning up temporary table: {temp_table_id}")
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.info("✅ Temporary table cleaned up successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp table {temp_table_id}: {cleanup_error}")
                    # Don't fail the whole operation for cleanup issues
    
    def _load_data_upsert_mode(self, rows: List[Dict], **kwargs) -> Dict:
        """
        UPSERT mode: MERGE data atomically.
        Used for production operations with potential concurrent access.
        """
        logger.info(f"Using UPSERT mode for {len(rows)} records")
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Prepare data for MERGE operation
            rows_param = [self._convert_pandas_types_for_json(row) for row in rows]
            
            # Build MERGE statement for your table structure
            merge_query = f"""
            MERGE `{table_id}` AS target
            USING UNNEST(@rows) AS source
            ON target.player_lookup = source.player_lookup 
            AND target.team_abbr = source.team_abbr 
            AND target.season = source.season
            WHEN MATCHED THEN
            UPDATE SET 
                player_name = source.player_name,
                first_game_date = source.first_game_date,
                last_game_date = source.last_game_date,
                games_played = source.games_played,
                total_appearances = source.total_appearances,
                inactive_appearances = source.inactive_appearances,
                dnp_appearances = source.dnp_appearances,
                jersey_number = source.jersey_number,
                position = source.position,
                last_roster_update = source.last_roster_update,
                source_priority = source.source_priority,
                confidence_score = source.confidence_score,
                processed_at = source.processed_at
            WHEN NOT MATCHED THEN
            INSERT (
                player_name, player_lookup, team_abbr, season, first_game_date,
                last_game_date, games_played, total_appearances, inactive_appearances,
                dnp_appearances, jersey_number, position, last_roster_update,
                source_priority, confidence_score, created_by, created_at, processed_at
            )
            VALUES (
                source.player_name, source.player_lookup, source.team_abbr, source.season,
                source.first_game_date, source.last_game_date, source.games_played,
                source.total_appearances, source.inactive_appearances, source.dnp_appearances,
                source.jersey_number, source.position, source.last_roster_update,
                source.source_priority, source.confidence_score, source.created_by,
                source.created_at, source.processed_at
            )
            """
            
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("rows", "STRUCT", rows_param)
                ]
            )
            
            query_job = self.bq_client.query(merge_query, job_config=job_config)
            result = query_job.result()
            
            # Get merge statistics
            num_dml_affected_rows = query_job.num_dml_affected_rows or 0
            
            logger.info(f"UPSERT mode completed. Affected rows: {num_dml_affected_rows}")
            
            return {
                'rows_processed': num_dml_affected_rows,
                'errors': []
            }
            
        except Exception as e:
            error_msg = str(e)
            errors.append(error_msg)
            logger.error(f"Error in UPSERT mode: {error_msg}")
            
            return {
                'rows_processed': 0,
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
    
    def get_available_seasons_from_data(self) -> List[str]:
        """Query the database to find available seasons in gamebook data."""
        try:
            # FIXED: Include season_year in SELECT so it can be used in ORDER BY
            query = f"""
            SELECT DISTINCT 
                season_year,
                CONCAT(CAST(season_year AS STRING), '-', LPAD(CAST(season_year + 1 - 2000 AS STRING), 2, '0')) as season
            FROM `{self.processor.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE season_year IS NOT NULL
            ORDER BY season_year DESC
            """
            
            results = self.processor.bq_client.query(query).to_dataframe()
            
            if not results.empty:
                seasons = results['season'].tolist()
                logging.info(f"Found {len(seasons)} seasons in gamebook data: {seasons}")
                return seasons
            else:
                logging.warning("No seasons found in gamebook data, using default list")
                return self.available_seasons
                
        except Exception as e:
            logging.error(f"Error querying available seasons: {e}")
            return self.available_seasons
        
    def build_registry_for_season(self, season: str, team: str = None) -> Dict:
        """Build registry for a specific season."""
        logger.info(f"Building registry for season {season}" + (f", team {team}" if team else ""))
        # Add at start:
        season_start = time.time()
        logger.info(f"PERF_METRIC: season_processing_start season={season} team={team}")
        
        # Reset tracking for this run
        self.new_players_discovered = set()
        self.players_seen_this_run = set()

        # Reset stats for each season to avoid accumulation issues
        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set(),
            'unresolved_players_found': 0,
            'alias_resolutions': 0
        }
        
        # Create filter data
        filter_data = {
            'season_filter': season,
            'team_filter': team
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)

        result['new_players_discovered'] = list(self.new_players_discovered)
        if self.new_players_discovered:
            logger.info(f"Discovered {len(self.new_players_discovered)} new players: {', '.join(self.new_players_discovered)}")
        
        # Log summary with more accurate information
        logger.info(f"Registry build complete for {season}:")
        logger.info(f"  Records created: {len(rows)}")
        logger.info(f"  Records loaded: {result['rows_processed']}")
        logger.info(f"  Load errors: {len(result.get('errors', []))}")
        logger.info(f"  Players processed: {self.stats['players_processed']}")
        logger.info(f"  Teams: {len(self.stats['teams_processed'])}")
        logger.info(f"  Alias resolutions: {self.stats['alias_resolutions']}")
        logger.info(f"  Unresolved found: {self.stats['unresolved_players_found']}")
        
        season_duration = time.time() - season_start
        logger.info(f"PERF_METRIC: season_processing_complete season={season} duration={season_duration:.3f}s records={result['records_processed']}")

        return {
            'season': season,
            'team_filter': team,
            'records_processed': result['rows_processed'],
            'records_created': len(rows),
            'players_processed': self.stats['players_processed'],
            'teams_processed': list(self.stats['teams_processed']),
            'alias_resolutions': self.stats['alias_resolutions'],
            'unresolved_found': self.stats['unresolved_players_found'],
            'errors': result.get('errors', []),
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
        
        self.new_players_discovered = set()

        # Use date range approach for recent games
        filter_data = {
            'season_filter': season,
            'date_range': (game_date, game_date)
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)

        # Enhanced result with universal ID info
        result['new_players_discovered'] = list(self.new_players_discovered)
        if self.new_players_discovered:
            logger.info(f"Discovered {len(self.new_players_discovered)} new players during nightly update")
        
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
    
    def build_registry_for_all_seasons(self) -> Dict:
        """Build registry for all available seasons."""
        logger.info("Starting full registry backfill for all seasons")
        
        seasons = self.get_available_seasons_from_data()
        
        if not seasons:
            logger.error("No seasons available for processing")
            return {'error': 'No seasons found'}
        
        results = {
            'seasons_processed': [],
            'seasons_failed': [],
            'total_records': 0,
            'total_players': 0,
            'errors': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None
        }
        
        for i, season in enumerate(seasons, 1):
            logger.info(f"Processing season {i}/{len(seasons)}: {season}")
            
            try:
                season_result = self.processor.build_registry_for_season(season)
                
                # IMPROVED: Check if season actually loaded data
                if season_result['records_processed'] > 0:
                    results['seasons_processed'].append({
                        'season': season,
                        'records_loaded': season_result['records_processed'],
                        'records_created': season_result.get('records_created', 0),
                        'players_processed': season_result['players_processed'],
                        'teams_processed': len(season_result['teams_processed']),
                        'errors': season_result['errors']
                    })
                    
                    results['total_records'] += season_result['records_processed']
                    results['total_players'] += season_result['players_processed']
                    
                    logger.info(f"✅ {season}: {season_result['records_processed']} records loaded, {season_result['players_processed']} players")
                else:
                    # Season failed to load data
                    results['seasons_failed'].append({
                        'season': season,
                        'error_count': len(season_result['errors']),
                        'errors': season_result['errors']
                    })
                    logger.error(f"❌ {season}: Failed to load data - {len(season_result['errors'])} errors")
                
                if season_result['errors']:
                    results['errors'].extend([f"{season}: {err}" for err in season_result['errors']])
                    
            except Exception as e:
                error_msg = f"Error processing season {season}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)
                results['seasons_failed'].append({
                    'season': season,
                    'error': str(e)
                })
        
        results['end_time'] = datetime.now().isoformat()
        
        # IMPROVED: Accurate final summary
        logger.info("=" * 60)
        logger.info("REGISTRY BACKFILL SUMMARY:")
        logger.info(f"  Seasons successful: {len(results['seasons_processed'])}")
        logger.info(f"  Seasons failed: {len(results['seasons_failed'])}")
        logger.info(f"  Total registry records loaded: {results['total_records']}")
        logger.info(f"  Total players processed: {results['total_players']}")
        logger.info(f"  Total errors: {len(results['errors'])}")
        
        if results['seasons_failed']:
            logger.error("  Failed seasons:")
            for failed in results['seasons_failed']:
                logger.error(f"    - {failed['season']}")
        
        start_time = datetime.fromisoformat(results['start_time'])
        end_time = datetime.fromisoformat(results['end_time'])
        duration = (end_time - start_time).total_seconds() / 60
        logger.info(f"  Duration: {duration:.1f} minutes")
        logger.info("=" * 60)
        
        return results
    
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


def build_historical_registry(seasons: List[str] = None, strategy: str = "replace") -> Dict:
    """Convenience function for 4-year backfill."""
    processor = NbaPlayersRegistryProcessor(strategy=strategy)
    return processor.build_historical_registry(seasons)

def update_registry_from_gamebook(game_date: str, season: str, strategy: str = "merge") -> Dict:
    """Convenience function for nightly updates."""
    processor = NbaPlayersRegistryProcessor(strategy=strategy)
    return processor.update_registry_from_gamebook(game_date, season)

def update_registry_from_rosters(season: str, teams: List[str] = None, strategy: str = "merge") -> Dict:
    """Convenience function for morning roster updates."""
    processor = NbaPlayersRegistryProcessor(strategy=strategy)
    return processor.update_registry_from_rosters(season, teams)

def get_registry_summary() -> Dict:
    """Convenience function to get registry summary."""
    processor = NbaPlayersRegistryProcessor()  # No strategy needed for read-only
    return processor.get_registry_summary()

