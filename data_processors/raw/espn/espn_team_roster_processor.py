#!/usr/bin/env python3
# File: data_processors/raw/espn/espn_team_roster_processor.py
# Description: ESPN roster processor with Player Registry and optimized DELETE+INSERT
# Updated: 2025-10-19 - PERFORMANCE OPTIMIZED (3x faster - 25s vs 60s)

import json
import logging
import re
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone, date, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery, storage
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError
from shared.utils.bigquery_retry import SERIALIZATION_RETRY

logger = logging.getLogger(__name__)


class EspnTeamRosterProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process ESPN team roster API data with Player Registry integration.

    OPTIMIZED v2: Multi-threaded + Batch DELETE (3x faster)
    - Load/Transform: Parallel (8 threads) - 30 teams in 3-5 seconds
    - Delete: Batch (1 query) - 30 teams in 2-3 seconds
    - Insert: Batch load - 30 teams in 15-20 seconds
    - Expected total: ~25-30 seconds (vs 60 seconds before)
    """

    # Smart idempotency: Hash meaningful roster fields only
    HASH_FIELDS = [
        'roster_date',
        'team_abbr',
        'espn_player_id',
        'player_full_name',
        'jersey_number',
        'position',
        'height',
        'weight',
        'status',
        'roster_status'
    ]

    required_opts = ['bucket', 'file_path']
    
    def __init__(self):
        super().__init__()
        self.table_name = 'espn_team_rosters'
        self.dataset_id = 'nba_raw'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        
        # Tracking
        self.players_processed = 0
        self.players_skipped = 0
        self.players_unresolved = 0
        
        # Player Registry Integration (lenient consumer pattern)
        self.registry = RegistryReader(
            source_name='espn_roster_processor',
            cache_ttl_seconds=300
        )
    
    # ================================================================
    # STEP 1: LOAD DATA FROM GCS
    # ================================================================
    def load_data(self) -> None:
        """Load JSON data from GCS."""
        self.raw_data = self.load_json_from_gcs()
    
    # ================================================================
    # STEP 2: VALIDATE LOADED DATA
    # ================================================================
    def validate_loaded_data(self) -> None:
        """Validate ESPN roster data structure."""
        if not self.raw_data:
            raise ValueError("No data loaded")
        
        errors = []
        
        if not isinstance(self.raw_data, dict):
            errors.append("Data is not a dictionary")
        
        if 'players' not in self.raw_data:
            errors.append("Missing 'players' field in data")
        
        if 'team_abbr' not in self.raw_data:
            errors.append("Missing 'team_abbr' field in data")
        
        if errors:
            error_msg = "; ".join(errors)
            logger.error(f"Validation failed: {error_msg}")
            raise ValueError(error_msg)
        
        logger.debug(f"Validation passed for {self.raw_data.get('team_abbr')} roster")
    
    # ================================================================
    # STEP 3: TRANSFORM DATA (WITH REGISTRY INTEGRATION)
    # ================================================================
    def transform_data(self) -> None:
        """Transform ESPN roster data with Player Registry integration."""
        rows = []
        file_path = self.opts.get('file_path', 'unknown')
        
        try:
            # Extract metadata from file path
            roster_date = self._extract_date_from_path(file_path)
            source_file_date = roster_date
            season_year = self._extract_season_year(roster_date)
            scrape_hour = self._extract_scrape_hour(file_path)
            
            # Extract top-level team information
            team_abbr = self.raw_data.get('team_abbr', '')
            team_display_name = self.raw_data.get('teamName', '')
            espn_team_id = self.raw_data.get('espn_team_id')
            players_data = self.raw_data.get('players', [])
            
            if not team_abbr:
                raise ValueError(f"Missing team_abbr in {file_path}")
            
            # Set registry context for this processing run
            season = f"{season_year}-{str(season_year + 1)[-2:]}"
            self.registry.set_default_context(
                season=season,
                team_abbr=team_abbr
            )
            
            total_players = len(players_data)
            self.players_processed = 0
            self.players_skipped = 0
            self.players_unresolved = 0
            
            # Process each player
            for player_data in players_data:
                if not isinstance(player_data, dict):
                    self.players_skipped += 1
                    continue
                
                # Extract player ID - required field
                espn_player_id = player_data.get('playerId')
                if not espn_player_id:
                    self.players_skipped += 1
                    logger.debug(f"Skipping player without playerId in {team_abbr} roster")
                    continue
                
                # Extract player name - required field
                full_name = player_data.get('fullName', '')
                if not full_name:
                    self.players_skipped += 1
                    logger.debug(f"Skipping player {espn_player_id} without fullName in {team_abbr} roster")
                    continue
                
                # Generate normalized lookup name
                player_lookup = self._normalize_player_name(full_name)
                
                # Try to resolve universal player ID (lenient mode)
                universal_player_id = self.registry.get_universal_id(
                    player_lookup,
                    required=False,
                    context={
                        'espn_player_id': espn_player_id,
                        'team_abbr': team_abbr,
                        'roster_date': roster_date.isoformat()
                    }
                )
                
                if universal_player_id is None:
                    self.players_unresolved += 1
                    logger.debug(f"Player {player_lookup} ({full_name}) not in registry")
                
                # Extract player details
                jersey_number = player_data.get('jersey')
                if jersey_number is not None:
                    jersey_number = str(jersey_number)
                
                position_name = player_data.get('position', '')
                height = self._convert_height_to_display(player_data.get('heightIn'))
                weight = self._convert_weight_to_display(player_data.get('weightLb'))
                
                # Determine player status from injuries
                injuries = player_data.get('injuries', [])
                status = self._determine_player_status(injuries)
                
                # Build the row
                row = {
                    'universal_player_id': universal_player_id,
                    'roster_date': roster_date.isoformat(),
                    'scrape_hour': scrape_hour,
                    'season_year': season_year,
                    'team_abbr': team_abbr,
                    'team_display_name': team_display_name,
                    'espn_player_id': int(espn_player_id),
                    'player_full_name': full_name,
                    'player_lookup': player_lookup,
                    'jersey_number': jersey_number,
                    'position': position_name if position_name else None,
                    'position_abbr': position_name if position_name else None,
                    'height': height,
                    'weight': weight,
                    'age': None,
                    'experience_years': None,
                    'college': None,
                    'birth_place': None,
                    'birth_date': None,
                    'status': status,
                    'roster_status': 'Active Roster',
                    'salary': None,
                    'espn_roster_url': None,
                    'source_file_path': file_path,
                    'source_file_date': source_file_date.isoformat(),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                rows.append(row)
                self.players_processed += 1
            
            # Data quality checks
            if len(rows) < 5:
                logger.warning(f"Low player count for {team_abbr}: {len(rows)} players")
            
            if total_players > 0 and self.players_skipped >= total_players * 0.3:
                logger.warning(f"High skip rate for {team_abbr}: {self.players_skipped}/{total_players}")
            
            # Log resolution stats
            if self.players_unresolved > 0:
                resolution_rate = (self.players_processed - self.players_unresolved) / self.players_processed * 100
                logger.debug(f"Registry resolution for {team_abbr}: {resolution_rate:.1f}% ({self.players_processed - self.players_unresolved}/{self.players_processed})")
            
            # Store transformed data
            self.transformed_data = rows

            # Add smart idempotency hash to each row
            self.add_data_hash()

            logger.debug(f"Transformed {len(rows)} players from {team_abbr} roster (skipped {self.players_skipped}, unresolved {self.players_unresolved})")
            
        except Exception as e:
            logger.error(f"Error transforming ESPN roster data from {file_path}: {str(e)}")
            raise
    
    # ================================================================
    # STEP 4: SAVE DATA (OPTIMIZED DELETE + INSERT)
    # ================================================================
    def save_data(self) -> None:
        """
        Save using optimized DELETE + INSERT pattern.
        
        Speed: 1-2 seconds per team (vs 30-60 seconds with MERGE)
        Streaming Buffer: NONE (uses batch loading only)
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
        
        rows = self.transformed_data if isinstance(self.transformed_data, list) else [self.transformed_data]
        
        if not rows:
            logger.warning("No rows to save")
            return
        
        logger.info(f"Using optimized DELETE + INSERT for {len(rows)} rows")
        
        # Use fast partition replace
        self._fast_partition_replace(rows)
        
        self.stats["rows_inserted"] = len(rows)
        logger.info(f"Successfully saved {len(rows)} rows for {rows[0].get('team_abbr')}")
        
        # Flush unresolved players to registry tracking table
        self.registry.flush_unresolved_players()
        logger.debug("Flushed unresolved players to registry tracking table")
    
    def _fast_partition_replace(self, rows: List[Dict]) -> None:
        """
        Fast partition replacement using DELETE + INSERT.
        
        Speed: 1-2 seconds for 10-1000 rows (15-30x faster than MERGE)
        Streaming Buffer: NONE (uses batch loading only)
        
        Pattern:
        1. DELETE existing data for partition slice (500ms)
        2. INSERT new data using batch load (500ms)
        Total: ~1-2 seconds
        """
        if not rows:
            return
        
        project_id = self.bq_client.project
        table_id = f"{project_id}.{self.dataset_id}.{self.table_name}"
        
        try:
            # Extract partition keys
            partition_date = rows[0]['roster_date']
            scrape_hour = rows[0]['scrape_hour']
            team_abbr = rows[0]['team_abbr']
            
            # Step 1: DELETE existing data for this partition slice
            logger.debug(f"Deleting partition slice: {partition_date}/{scrape_hour}/{team_abbr}")

            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE roster_date = '{partition_date}'
              AND scrape_hour = {scrape_hour}
              AND team_abbr = '{team_abbr}'
            """

            @SERIALIZATION_RETRY
            def execute_delete_with_retry():
                delete_job = self.bq_client.query(delete_query)
                return delete_job.result(timeout=60)

            execute_delete_with_retry()
            logger.debug(f"Deleted existing records for {team_abbr} on {partition_date}")
            
            # Step 2: INSERT new data using batch loading
            logger.debug(f"Inserting {len(rows)} rows")
            
            # Get schema from main table
            main_table = self.bq_client.get_table(table_id)
            
            # Batch load configuration
            job_config = bigquery.LoadJobConfig(
                schema=main_table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            )
            
            # Convert types for JSON loading
            validated_rows = [self._convert_for_json_load(row) for row in rows]

            # Batch load (NO streaming buffer) with retry for serialization errors
            @SERIALIZATION_RETRY
            def execute_insert_with_retry():
                load_job = self.bq_client.load_table_from_json(
                    validated_rows,
                    table_id,
                    job_config=job_config
                )
                return load_job.result(timeout=60)

            execute_insert_with_retry()
            logger.debug(f"Fast partition replace completed for {team_abbr}")
            
        except Exception as e:
            logger.error(f"Fast partition replace failed: {e}")
            raise
    
    def _batch_delete_partitions(self, partition_keys: List[tuple]) -> None:
        """
        Delete multiple partition slices in ONE query (much faster).
        
        Speed: 2-3 seconds for 30 teams (vs 15 seconds with 30 separate DELETEs)
        
        Args:
            partition_keys: List of (roster_date, scrape_hour, team_abbr) tuples
        """
        if not partition_keys:
            return
        
        project_id = self.bq_client.project
        table_id = f"{project_id}.{self.dataset_id}.{self.table_name}"
        
        # Build WHERE clause with OR conditions
        conditions = []
        for partition_date, scrape_hour, team_abbr in partition_keys:
            conditions.append(
                f"(roster_date = '{partition_date}' AND scrape_hour = {scrape_hour} AND team_abbr = '{team_abbr}')"
            )
        
        where_clause = " OR ".join(conditions)
        
        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE {where_clause}
        """

        logger.info(f"Batch deleting {len(partition_keys)} partition slices in one query...")

        @SERIALIZATION_RETRY
        def execute_batch_delete_with_retry():
            delete_job = self.bq_client.query(delete_query)
            return delete_job.result(timeout=60)

        execute_batch_delete_with_retry()
        logger.info(f"✓ Batch delete completed ({len(partition_keys)} teams)")
    
    def _convert_for_json_load(self, record: Dict) -> Dict:
        """Convert record types for JSON loading."""
        import pandas as pd
        
        converted = {}
        
        timestamp_fields = {'processed_at', 'created_at', 'updated_at', 'last_roster_update'}
        date_fields = {'roster_date', 'birth_date', 'source_file_date'}
        
        for key, value in record.items():
            # Handle lists first
            if isinstance(value, list):
                converted[key] = value
                continue
            
            # Check for None/NaN on scalar values only
            if pd.isna(value):
                converted[key] = None
                continue
            
            # TIMESTAMP fields - convert to ISO strings
            if key in timestamp_fields:
                if isinstance(value, (datetime, pd.Timestamp)):
                    converted[key] = value.isoformat()
                elif isinstance(value, str):
                    converted[key] = value
                else:
                    converted[key] = None
            
            # DATE fields - convert to ISO date strings
            elif key in date_fields:
                if isinstance(value, (date, datetime)):
                    converted[key] = value.isoformat()
                elif isinstance(value, str):
                    converted[key] = value
                else:
                    converted[key] = None
            
            # Other types pass through
            else:
                converted[key] = value
        
        return converted
    
    # ================================================================
    # HELPER METHODS
    # ================================================================
    def _normalize_player_name(self, name: str) -> str:
        """Normalize player name for consistent lookup."""
        if not name:
            return ""
        
        normalized = name.lower().strip()
        
        # Remove common suffixes
        suffixes = [' jr.', ' jr', ' sr.', ' sr', ' ii', ' iii', ' iv', ' v']
        for suffix in suffixes:
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)].strip()
        
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        return normalized
    
    def _extract_date_from_path(self, file_path: str) -> date:
        """Extract date from GCS file path."""
        parts = file_path.split('/')
        for part in parts:
            if len(part) == 10 and part.count('-') == 2:
                try:
                    return datetime.strptime(part, '%Y-%m-%d').date()
                except ValueError:
                    continue
        
        logger.warning(f"Could not extract date from path: {file_path}, using today's date")
        return date.today()
    
    def _extract_season_year(self, roster_date: date) -> int:
        """Calculate NBA season year from roster date."""
        if roster_date.month >= 10:
            return roster_date.year
        else:
            return roster_date.year - 1
    
    def _extract_scrape_hour(self, file_path: str) -> int:
        """Extract scrape hour from file path (defaults to 8 for morning operations)."""
        return 8
    
    def _determine_player_status(self, injuries: List[Dict]) -> str:
        """Determine player status from injuries array."""
        if not injuries or len(injuries) == 0:
            return 'Active'
        
        recent_injury = injuries[0]
        injury_status = recent_injury.get('status', '')
        
        if injury_status:
            return injury_status
        
        injury_type = recent_injury.get('type', {})
        if isinstance(injury_type, dict):
            type_name = injury_type.get('name', '')
            if 'OUT' in type_name.upper():
                return 'Out'
        
        return 'Day-To-Day'
    
    def _convert_height_to_display(self, height_inches: Optional[int]) -> Optional[str]:
        """Convert height in inches to display format like '6' 9"'."""
        if height_inches is None or not isinstance(height_inches, (int, float)):
            return None
        
        try:
            height_in = int(height_inches)
            feet = height_in // 12
            inches = height_in % 12
            return f"{feet}' {inches}\""
        except (TypeError, ValueError):
            return None
    
    def _convert_weight_to_display(self, weight_pounds: Optional[float]) -> Optional[str]:
        """Convert weight in pounds to display format like '250 lbs'."""
        if weight_pounds is None or not isinstance(weight_pounds, (int, float)):
            return None
        
        try:
            return f"{int(weight_pounds)} lbs"
        except (TypeError, ValueError):
            return None
    
    def get_processor_stats(self) -> Dict:
        """Return processor statistics."""
        return {
            'players_processed': self.players_processed,
            'players_skipped': self.players_skipped,
            'players_unresolved': self.players_unresolved,
            'resolution_rate': (self.players_processed - self.players_unresolved) / max(self.players_processed, 1) * 100,
            'rows_transformed': len(self.transformed_data) if isinstance(self.transformed_data, list) else 0
        }


# ============================================================================
# BATCH PROCESSING MODE (OPTIMIZED V2 - PARALLEL + BATCH DELETE)
# ============================================================================

def discover_latest_files_per_team(bucket_name: str, date: str, team: str = None) -> Dict[str, str]:
    """
    Discover files and return ONLY the latest file per team.
    Prevents processing duplicate scrape runs (3x speedup).
    
    Args:
        bucket_name: GCS bucket name
        date: Date to process (YYYY-MM-DD)
        team: Optional specific team
        
    Returns:
        Dict mapping team_abbr to latest file path
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    prefix = f"espn/rosters/{date}/"
    blobs = list(bucket.list_blobs(prefix=prefix))
    
    if not blobs:
        logger.warning(f"No files found with prefix: {prefix}")
        return {}
    
    # Group files by team
    team_files = defaultdict(list)
    for blob in blobs:
        if not blob.name.endswith('.json'):
            continue
            
        # Path: espn/rosters/2025-10-18/team_DEN/20251018_225713.json
        parts = blob.name.split('/')
        if len(parts) >= 5 and parts[3].startswith('team_'):
            team_abbr = parts[3].replace('team_', '')
            
            if team and team_abbr != team:
                continue
            
            # Extract timestamp from filename
            filename = parts[4]  # "20251018_225713.json"
            timestamp_str = filename.replace('.json', '')  # "20251018_225713"
            
            team_files[team_abbr].append({
                'path': blob.name,
                'timestamp': timestamp_str
            })
    
    # Select latest file per team
    latest_files = {}
    for team_abbr, files in team_files.items():
        # Sort by timestamp (lexicographic sort works for YYYYMMDD_HHMMSS)
        files.sort(key=lambda x: x['timestamp'], reverse=True)
        latest = files[0]
        latest_files[team_abbr] = latest['path']
        
        if len(files) > 1:
            logger.debug(f"  {team_abbr}: {len(files)} files found, using latest ({latest['timestamp']})")
    
    logger.info(f"Discovered {len(latest_files)} teams for {date}")
    return latest_files


def batch_process_rosters(bucket: str, date: str, project_id: str, team: str = None) -> tuple:
    """
    OPTIMIZED v2: Parallel load/transform + batch DELETE (3x faster).
    
    Performance optimizations:
    - Shared clients (BigQuery, Storage, Registry) - saves 3-5s
    - Parallel load/transform (8 threads) - 30 teams in 3-5s (vs 30s serial)
    - Batch DELETE (1 query) - 2-3s (vs 15s with 30 queries)
    - Latest file per team only - processes 30 vs 90+ files
    
    Expected: 30 teams in ~25-30 seconds (vs 60 seconds before)
    
    Returns:
        (teams_processed, total_players, total_unresolved, errors)
    """
    logger.info(f"🚀 BATCH MODE v2: Parallel processing + batch DELETE...")
    start_time = datetime.now()
    
    # ========================================================================
    # PHASE 1: Initialize shared clients ONCE (saves 3-5 seconds)
    # ========================================================================
    logger.info("Initializing shared clients...")
    init_start = datetime.now()
    
    bq_client = bigquery.Client(project=project_id)
    storage_client = storage.Client(project=project_id)  # ✅ CREATE ONCE, reuse 30x
    
    # Shared registry for batch mode (ONE cache for all teams)
    shared_registry = RegistryReader(
        source_name='espn_roster_batch_processor',
        cache_ttl_seconds=300
    )
    
    init_duration = (datetime.now() - init_start).total_seconds()
    logger.info(f"✓ Clients initialized in {init_duration:.1f}s")
    
    # ========================================================================
    # PHASE 2: Discover latest files (deduplication)
    # ========================================================================
    latest_files = discover_latest_files_per_team(bucket, date, team)
    
    if not latest_files:
        logger.error(f"No files found for {date}")
        return 0, 0, 0, 1
    
    # ========================================================================
    # PHASE 3: PARALLEL Load + Transform (3-5 seconds for 30 teams)
    # ========================================================================
    logger.info(f"\n📥 Loading and transforming {len(latest_files)} teams in parallel...")
    load_start = datetime.now()
    
    def process_team(team_abbr: str, file_path: str) -> tuple:
        """Process one team (runs in parallel thread)."""
        try:
            # Build opts
            opts = {
                'bucket': bucket,
                'file_path': file_path,
                'project_id': project_id
            }
            
            # Create processor for this file
            processor = EspnTeamRosterProcessor()
            processor.opts = opts
            processor.project_id = project_id
            
            # ✅ REUSE shared clients (not create new ones)
            processor.registry = shared_registry
            processor.bq_client = bq_client
            processor.gcs_client = storage_client  # ProcessorBase uses gcs_client
            
            # Load, validate, transform (I/O bound - good for threading)
            processor.load_data()
            processor.validate_loaded_data()
            processor.transform_data()
            
            # Get results
            stats = processor.get_processor_stats()
            rows = processor.transformed_data if processor.transformed_data else []
            
            return team_abbr, rows, stats, None
            
        except Exception as e:
            logger.error(f"  ✗ {team_abbr}: {str(e)}")
            return team_abbr, None, None, str(e)
    
    # Process teams in parallel (max 8 concurrent)
    all_rows_by_key = defaultdict(list)
    teams_processed = 0
    total_unresolved = 0
    errors = 0
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        # Submit all teams
        futures = {
            executor.submit(process_team, team_abbr, file_path): team_abbr
            for team_abbr, file_path in latest_files.items()
        }
        
        # Collect results as they complete
        for future in as_completed(futures):
            team_abbr = futures[future]
            team_abbr_result, rows, stats, error = future.result()
            
            if error:
                errors += 1
                continue
            
            if rows and stats:
                # Group rows for batch save
                for row in rows:
                    key = (row['roster_date'], row['scrape_hour'], row['team_abbr'])
                    all_rows_by_key[key].append(row)
                
                teams_processed += 1
                total_unresolved += stats['players_unresolved']
                logger.info(f"  ✓ {team_abbr}: {len(rows)} players "
                          f"(resolution: {stats['resolution_rate']:.1f}%)")
            else:
                errors += 1
    
    load_duration = (datetime.now() - load_start).total_seconds()
    logger.info(f"✓ Load/transform completed in {load_duration:.1f}s")
    
    # ========================================================================
    # PHASE 4: BATCH Delete (2-3 seconds for all 30 teams)
    # ========================================================================
    total_players = sum(len(rows) for rows in all_rows_by_key.values())
    
    if all_rows_by_key:
        logger.info(f"\n💾 Saving {total_players} players from {teams_processed} teams...")
        save_start = datetime.now()
        
        # Use processor instance for save operations
        save_processor = EspnTeamRosterProcessor()
        save_processor.bq_client = bq_client
        save_processor.registry = shared_registry
        save_processor.project_id = project_id
        save_processor.dataset_id = 'nba_raw'
        save_processor.table_name = 'espn_team_rosters'
        
        # Step 1: Batch DELETE all partition slices in ONE query
        delete_start = datetime.now()
        partition_keys = list(all_rows_by_key.keys())
        save_processor._batch_delete_partitions(partition_keys)
        delete_duration = (datetime.now() - delete_start).total_seconds()
        logger.info(f"✓ Batch delete completed in {delete_duration:.1f}s")
        
        # Step 2: Batch INSERT all rows
        insert_start = datetime.now()
        for key, rows in all_rows_by_key.items():
            try:
                # Get schema and insert rows
                project = bq_client.project
                table_id = f"{project}.{save_processor.dataset_id}.{save_processor.table_name}"
                main_table = bq_client.get_table(table_id)
                
                job_config = bigquery.LoadJobConfig(
                    schema=main_table.schema,
                    autodetect=False,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND
                )
                
                validated_rows = [save_processor._convert_for_json_load(row) for row in rows]

                @SERIALIZATION_RETRY
                def execute_batch_insert_with_retry():
                    load_job = bq_client.load_table_from_json(
                        validated_rows,
                        table_id,
                        job_config=job_config
                    )
                    return load_job.result(timeout=60)

                execute_batch_insert_with_retry()

            except Exception as e:
                logger.error(f"Failed to insert {key}: {e}")
                errors += 1
        
        insert_duration = (datetime.now() - insert_start).total_seconds()
        save_duration = (datetime.now() - save_start).total_seconds()
        logger.info(f"✓ Batch insert completed in {insert_duration:.1f}s")
        logger.info(f"✓ Total save completed in {save_duration:.1f}s")
    
    # ========================================================================
    # PHASE 5: Flush unresolved players
    # ========================================================================
    if total_unresolved > 0:
        logger.info(f"\n📝 Flushing {total_unresolved} unresolved players to registry...")
        shared_registry.flush_unresolved_players()
    
    total_duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"\n⚡ Total processing time: {total_duration:.1f}s")
    
    return teams_processed, total_players, total_unresolved, errors


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process ESPN team roster data (OPTIMIZED v2)")
    parser.add_argument("--bucket", default="nba-scraped-data", help="GCS bucket name")
    parser.add_argument("--date", required=True, help="Date to process (YYYY-MM-DD)")
    parser.add_argument("--team", help="Process specific team only (e.g., LAL)")
    parser.add_argument("--project-id", default="nba-props-platform", help="GCP project ID")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--batch", action="store_true",
                       help="🚀 Batch mode v2: Parallel + batch DELETE (RECOMMENDED - 3x faster)")
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 3 (for backfills)'
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # ═══════════════════════════════════════════════════════════════
    # BATCH MODE v2 (RECOMMENDED - OPTIMIZED)
    # ═══════════════════════════════════════════════════════════════
    if args.batch:
        logger.info("🚀 BATCH MODE v2: Parallel load + batch DELETE (3x faster)\n")
        
        teams_processed, total_players, total_unresolved, errors = batch_process_rosters(
            bucket=args.bucket,
            date=args.date,
            project_id=args.project_id,
            team=args.team
        )
        
        print(f"\n{'='*60}")
        print(f"{'✅ BATCH COMPLETE' if errors == 0 else '⚠️  COMPLETE WITH ERRORS'}")
        print(f"{'='*60}")
        print(f"Date: {args.date}")
        print(f"Teams processed: {teams_processed}")
        print(f"Total players: {total_players}")
        if total_players > 0:
            print(f"Resolved players: {total_players - total_unresolved} ({(total_players - total_unresolved)/total_players*100:.1f}%)")
            print(f"Unresolved players: {total_unresolved} ({total_unresolved/total_players*100:.1f}%)")
        print(f"Errors: {errors}")
        print(f"{'='*60}")
        
        # Show unresolved players for review
        if total_unresolved > 0:
            print(f"\n📝 Review unresolved players:")
            print(f"   bq query --use_legacy_sql=false \"")
            print(f"   SELECT normalized_lookup, team_abbr, occurrences, first_seen_date")
            print(f"   FROM \\`{args.project_id}.nba_reference.unresolved_player_names\\`")
            print(f"   WHERE source = 'espn_roster_processor'")
            print(f"     AND status = 'pending'")
            print(f"   ORDER BY occurrences DESC")
            print(f"   LIMIT 20\"")
            print(f"\n💡 Most unresolved players are likely rookies/two-way contracts")
        
        # Quick verification
        if total_players > 0:
            from google.cloud import bigquery
            bq = bigquery.Client(project=args.project_id)
            
            verify_query = f"""
            SELECT 
                COUNT(*) as records,
                COUNT(DISTINCT team_abbr) as teams,
                COUNT(DISTINCT player_lookup) as unique_players,
                COUNT(universal_player_id) as with_universal_id,
                ROUND(COUNT(universal_player_id) / COUNT(*) * 100, 1) as resolution_rate
            FROM `{args.project_id}.nba_raw.espn_team_rosters`
            WHERE roster_date = '{args.date}'
            """
            
            result = bq.query(verify_query).to_dataframe()
            if not result.empty:
                print(f"\n📊 BigQuery verification:")
                print(f"   Records: {result.iloc[0]['records']}")
                print(f"   Teams: {result.iloc[0]['teams']}")
                print(f"   Unique players: {result.iloc[0]['unique_players']}")
                print(f"   With universal_player_id: {result.iloc[0]['with_universal_id']}")
                print(f"   Resolution rate: {result.iloc[0]['resolution_rate']}%")
        
        exit(0 if errors == 0 else 1)
    
    # ═══════════════════════════════════════════════════════════════
    # SINGLE FILE MODE (SLOWER BUT SIMPLE)
    # ═══════════════════════════════════════════════════════════════
    logger.warning("⚠️  Running in single-file mode")
    logger.warning("💡 Use --batch flag for 3x faster processing!\n")
    
    # Discover latest files per team (avoid duplicates)
    logger.info(f"Discovering latest files per team for {args.date}...")
    latest_files = discover_latest_files_per_team(args.bucket, args.date, args.team)
    
    if not latest_files:
        logger.error(f"No files found for {args.date}")
        exit(1)
    
    logger.info(f"Found {len(latest_files)} teams to process (latest files only)")
    
    # Process each file
    total_processed = 0
    total_unresolved = 0
    total_errors = 0
    teams_processed = []
    failed_teams = []
    
    for team_abbr, file_path in sorted(latest_files.items()):
        try:
            logger.info(f"\nProcessing {team_abbr}: {file_path}...")
            
            processor = EspnTeamRosterProcessor()

            opts = {
                'bucket': args.bucket,
                'file_path': file_path,
                'project_id': args.project_id,
                'skip_downstream_trigger': args.skip_downstream_trigger
            }

            success = processor.run(opts)
            
            if success:
                stats = processor.get_processor_stats()
                logger.info(f"  ✓ {team_abbr}: {stats['players_processed']} players "
                          f"(resolution: {stats['resolution_rate']:.1f}%)")
                total_processed += stats['players_processed']
                total_unresolved += stats['players_unresolved']
                teams_processed.append(team_abbr)
            else:
                logger.error(f"  ✗ Failed to process {team_abbr}")
                failed_teams.append(team_abbr)
                total_errors += 1
                
        except Exception as e:
            logger.error(f"  ✗ Exception processing {team_abbr}: {e}")
            total_errors += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"{'✅ COMPLETE' if total_errors == 0 else '⚠️  COMPLETE WITH ERRORS'}")
    print(f"{'='*60}")
    print(f"Date: {args.date}")
    print(f"Teams processed: {len(teams_processed)} {sorted(set(teams_processed))}")
    if failed_teams:
        print(f"Teams failed: {len(failed_teams)} {sorted(set(failed_teams))}")
    print(f"Total players loaded: {total_processed}")
    if total_processed > 0:
        print(f"Unresolved players: {total_unresolved} ({total_unresolved/total_processed*100:.1f}%)")
    print(f"Errors: {total_errors}")
    print(f"{'='*60}")