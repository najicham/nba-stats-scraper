#!/usr/bin/env python3
"""
File: processors/nba_com/nbac_player_list_processor.py

Process NBA.com Player List data for current player-team assignments.
Uses MERGE strategy to prevent duplicate accumulation from multiple daily runs.
"""

import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from google.cloud import storage
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

class NbacPlayerListProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process NBA.com Player List for current roster assignments.

    Processing Strategy: MERGE_UPDATE
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: player_lookup, team_abbr, position, jersey_number, is_active
        Expected Skip Rate: 20% when rosters unchanged
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'player_lookup',
        'team_abbr',
        'position',
        'jersey_number',
        'is_active'
    ]

    # Configure for ProcessorBase
    required_opts = ['bucket']  # file_path OR date required

    def __init__(self):
        super().__init__()
        self.table_name = 'nbac_player_list_current'
        self.dataset_id = 'nba_raw'
        
        # Tracking counters
        self.players_processed = 0
        self.players_failed = 0
        self.duplicate_count = 0
    
    def set_additional_opts(self) -> None:
        """Validate that we have either file_path or date."""
        super().set_additional_opts()
        
        # Validate inputs - file discovery happens later in load_data()
        if not self.opts.get('file_path') and not self.opts.get('date'):
            raise ValueError("Must provide either 'file_path' or 'date'")
    
    def _find_latest_file(self, bucket_name: str, prefix: str) -> Optional[str]:
        """
        Find latest JSON file in GCS for given prefix.
        
        Args:
            bucket_name: GCS bucket name
            prefix: Path prefix (e.g., 'nba-com/player-list/2025-10-02/')
            
        Returns:
            Full file path or None if no files found
        """
        try:
            bucket = self.gcs_client.bucket(bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            if not blobs:
                logger.warning(f"No blobs found with prefix: {prefix}")
                return None
            
            # Filter to JSON files
            json_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not json_blobs:
                logger.warning(f"No JSON files found with prefix: {prefix}")
                return None
            
            # Sort by creation time, take latest
            json_blobs.sort(key=lambda b: b.time_created, reverse=True)
            latest_blob = json_blobs[0]
            
            logger.info(f"Found {len(json_blobs)} files, using latest: {latest_blob.name}")
            return latest_blob.name
            
        except Exception as e:
            logger.error(f"Error finding latest file: {e}")
            return None
    
    # ================================================================
    # STEP 1: LOAD DATA FROM GCS
    # ================================================================
    def load_data(self) -> None:
        """Load JSON data from GCS bucket (implements ProcessorBase interface)."""
        bucket_name = self.opts.get('bucket')
        file_path = self.opts.get('file_path')
        
        # If date provided but no file_path, discover now (after gcs_client initialized)
        if not file_path and self.opts.get('date'):
            date_str = self.opts['date']
            logger.info(f"No file_path provided, discovering latest file for {date_str}")
            
            prefix = f"nba-com/player-list/{date_str}/"
            file_path = self._find_latest_file(bucket_name, prefix)
            
            if not file_path:
                raise FileNotFoundError(f"No files found in gs://{bucket_name}/{prefix}")
            
            # Store discovered path to opts so transform_data can access it
            self.opts['file_path'] = file_path
            logger.info(f"Discovered file: {file_path}")
        
        if not bucket_name or not file_path:
            raise ValueError("Missing 'bucket' or 'file_path' in opts")
        
        logger.info(f"Loading data from gs://{bucket_name}/{file_path}")
        
        try:
            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            if not blob.exists():
                raise FileNotFoundError(f"File not found: gs://{bucket_name}/{file_path}")
            
            # Download and parse JSON
            json_string = blob.download_as_string()
            self.raw_data = json.loads(json_string)
            
            logger.info(f"Successfully loaded {len(json_string)} bytes from GCS")
            
        except Exception as e:
            logger.error(f"Failed to load data from GCS: {e}")
            try:
                notify_error(
                    title="Failed to Load Player List from GCS",
                    message=f"Could not load gs://{bucket_name}/{file_path}",
                    details={
                        'bucket': bucket_name,
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="NBA.com Player List Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    # ================================================================
    # STEP 2: VALIDATE LOADED DATA
    # ================================================================
    def validate_loaded_data(self) -> None:
        """Validate the JSON data structure (overrides ProcessorBase)."""
        if not self.raw_data:
            raise ValueError("No data loaded")
        
        errors = []
        
        if 'resultSets' not in self.raw_data:
            errors.append("Missing 'resultSets' in data")
        else:
            # Find PlayerIndex result set
            player_result = None
            for result_set in self.raw_data.get('resultSets', []):
                if result_set.get('name') == 'PlayerIndex':
                    player_result = result_set
                    break
            
            if not player_result:
                errors.append("No 'PlayerIndex' result set found")
                try:
                    notify_error(
                        title="Player List Missing PlayerIndex",
                        message="No 'PlayerIndex' result set found in player list data",
                        details={
                            'result_sets_found': [rs.get('name') for rs in self.raw_data.get('resultSets', [])],
                            'result_sets_count': len(self.raw_data.get('resultSets', []))
                        },
                        processor_name="NBA.com Player List Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            elif 'headers' not in player_result or 'rowSet' not in player_result:
                errors.append("Missing headers or rowSet in player data")
        
        if errors:
            error_msg = "; ".join(errors)
            try:
                notify_warning(
                    title="Player List Data Validation Failed",
                    message=f"Found {len(errors)} validation errors",
                    details={'errors': errors}
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError(error_msg)
        
        logger.info("Data validation passed")
    
    # ================================================================
    # STEP 3: TRANSFORM DATA
    # ================================================================
    def transform_data(self) -> None:
        """Transform NBA.com player list to BigQuery rows (implements ProcessorBase interface)."""
        rows = []
        
        try:
            # Find PlayerIndex result set
            player_result = None
            for result_set in self.raw_data.get('resultSets', []):
                if result_set.get('name') == 'PlayerIndex':
                    player_result = result_set
                    break
            
            if not player_result:
                logger.error("No PlayerIndex result set found")
                self.transformed_data = []
                return
            
            headers = player_result['headers']
            header_map = {h: i for i, h in enumerate(headers)}
            
            # Get current season year
            current_date = datetime.now()
            season_year = current_date.year if current_date.month >= 10 else current_date.year - 1
            
            # Track duplicates
            seen_lookups = {}
            self.players_processed = 0
            self.players_failed = 0
            self.duplicate_count = 0
            
            file_path = self.opts.get('file_path', 'unknown')
            
            # Extract source_file_date from file path
            # Path format: nba-com/player-list/2025-10-01/20251001_220717.json
            source_file_date = None
            try:
                path_parts = file_path.split('/')
                if len(path_parts) >= 3:
                    date_str = path_parts[2]  # "2025-10-01"
                    source_file_date = date.fromisoformat(date_str)
                    logger.info(f"Extracted source_file_date: {source_file_date}")
            except (IndexError, ValueError) as e:
                logger.warning(f"Could not extract source_file_date from path '{file_path}': {e}")
                source_file_date = date.today()  # Fallback to today
            
            for player_row in player_result['rowSet']:
                try:
                    # Extract fields
                    player_id = player_row[header_map.get('PERSON_ID', 0)]
                    first_name = player_row[header_map.get('PLAYER_FIRST_NAME', 2)]
                    last_name = player_row[header_map.get('PLAYER_LAST_NAME', 1)]
                    full_name = f"{first_name} {last_name}"
                    team_id = player_row[header_map.get('TEAM_ID', 4)]
                    team_abbr = player_row[header_map.get('TEAM_ABBREVIATION', 9)] or ""
                    
                    # Generate player_lookup
                    player_lookup = self._normalize_player_name(full_name)
                    
                    # Check for duplicates
                    if player_lookup in seen_lookups:
                        self.duplicate_count += 1
                        logger.warning(f"Duplicate player_lookup '{player_lookup}': {full_name} ({team_abbr}) vs {seen_lookups[player_lookup]}")
                        
                        if self.duplicate_count == 1:
                            try:
                                notify_warning(
                                    title="Duplicate Player Lookup Detected",
                                    message=f"Found duplicate player_lookup: {player_lookup}",
                                    details={
                                        'player_lookup': player_lookup,
                                        'player_1': f"{full_name} ({team_abbr})",
                                        'player_2': seen_lookups[player_lookup],
                                        'season_year': season_year
                                    }
                                )
                            except Exception as notify_ex:
                                logger.warning(f"Failed to send notification: {notify_ex}")
                    
                    seen_lookups[player_lookup] = f"{full_name} ({team_abbr})"
                    
                    # Determine roster status
                    roster_status_code = player_row[header_map.get('ROSTER_STATUS', 19)]
                    is_active = roster_status_code == 1
                    roster_status = 'active' if is_active else 'inactive'
                    
                    row = {
                        'player_lookup': player_lookup,
                        'player_id': player_id,
                        'player_full_name': full_name,
                        'team_id': team_id,
                        'team_abbr': team_abbr,
                        'jersey_number': player_row[header_map.get('JERSEY_NUMBER', 10)],
                        'position': player_row[header_map.get('POSITION', 11)],
                        'height': player_row[header_map.get('HEIGHT', 12)],
                        'weight': player_row[header_map.get('WEIGHT', 13)],
                        'birth_date': None,
                        'age': None,
                        'draft_year': player_row[header_map.get('DRAFT_YEAR', 16)],
                        'draft_round': player_row[header_map.get('DRAFT_ROUND', 17)],
                        'draft_pick': player_row[header_map.get('DRAFT_NUMBER', 18)],
                        'years_pro': None,
                        'college': player_row[header_map.get('COLLEGE', 14)],
                        'country': player_row[header_map.get('COUNTRY', 15)],
                        'is_active': is_active,
                        'roster_status': roster_status,
                        'season_year': season_year,
                        'source_file_date': source_file_date.isoformat() if source_file_date else None,
                        'last_seen_date': date.today().isoformat(),
                        'source_file_path': file_path,
                        'processed_at': datetime.utcnow().isoformat()
                    }
                    
                    rows.append(row)
                    self.players_processed += 1
                    
                except Exception as e:
                    self.players_failed += 1
                    logger.error(f"Error processing player row: {e}")
                    
                    if self.players_failed == 1:
                        try:
                            notify_error(
                                title="Player List Row Processing Failed",
                                message=f"Failed to process player row: {str(e)}",
                                details={
                                    'error_type': type(e).__name__,
                                    'player_row': str(player_row)[:200],
                                    'season_year': season_year
                                },
                                processor_name="NBA.com Player List Processor"
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                    continue
            
            # Store transformed data
            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()

            # Check for high duplicate rate
            total_players = len(player_result['rowSet'])
            if total_players > 0 and self.duplicate_count > 5:
                try:
                    notify_warning(
                        title="High Player Lookup Duplicate Count",
                        message=f"Found {self.duplicate_count} duplicate player lookups",
                        details={
                            'duplicate_count': self.duplicate_count,
                            'total_players': total_players,
                            'unique_players': len(seen_lookups),
                            'season_year': season_year
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Check for high failure rate
            if total_players > 0:
                failure_rate = self.players_failed / total_players
                if failure_rate > 0.05:
                    try:
                        notify_warning(
                            title="High Player List Failure Rate",
                            message=f"Failed to process {failure_rate:.1%} of players",
                            details={
                                'total_players': total_players,
                                'players_failed': self.players_failed,
                                'players_processed': self.players_processed,
                                'failure_rate': f"{failure_rate:.1%}",
                                'season_year': season_year
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info(f"Transformed {len(rows)} players (failed: {self.players_failed}, duplicates: {self.duplicate_count})")
            
        except Exception as e:
            logger.error(f"Critical error in transform_data: {e}")
            try:
                notify_error(
                    title="Player List Transformation Failed",
                    message=f"Critical error transforming player list data: {str(e)}",
                    details={
                        'file_path': self.opts.get('file_path'),
                        'error_type': type(e).__name__,
                        'players_processed': self.players_processed,
                        'players_failed': self.players_failed
                    },
                    processor_name="NBA.com Player List Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise
    
    # ================================================================
    # STEP 4: SAVE DATA (OVERRIDE WITH MERGE STRATEGY)
    # ================================================================
    def save_data(self) -> None:
        """
        Override to use MERGE instead of APPEND.
        
        Uses staging table approach from lessons learned doc.
        Prevents duplicate accumulation from multiple daily runs.
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            return
        
        rows = self.transformed_data if isinstance(self.transformed_data, list) else [self.transformed_data]
        
        if not rows:
            logger.warning("No rows to save")
            return
        
        logger.info(f"Using MERGE strategy for {len(rows)} rows")
        
        # Use staging table MERGE
        self._merge_via_staging_table(
            rows=rows,
            merge_keys=['player_lookup', 'team_abbr', 'season_year']
        )
        
        self.stats["rows_inserted"] = len(rows)
        logger.info(f"Successfully merged {len(rows)} rows")
    
    def _merge_via_staging_table(self, rows: List[Dict], merge_keys: List[str]) -> None:
        """
        MERGE records using staging table approach (from lessons learned).
        
        Args:
            rows: List of record dictionaries
            merge_keys: Keys to match on for MERGE (e.g., ['player_lookup', 'team_abbr', 'season_year'])
        """
        if not rows:
            return
        
        project_id = self.bq_client.project
        table_id = f"{project_id}.{self.dataset_id}.{self.table_name}"
        staging_table_name = f"{self.table_name}_staging_{self.run_id}"
        staging_table_id = f"{project_id}.{self.dataset_id}.{staging_table_name}"
        
        try:
            # 1. Create staging table
            logger.info(f"Creating staging table: {staging_table_id}")
            
            # Get main table schema
            main_table = self.bq_client.get_table(table_id)
            
            # Create staging table with same schema and 30 min expiration
            staging_table = bigquery.Table(staging_table_id, schema=main_table.schema)
            staging_table.expires = datetime.utcnow() + timedelta(minutes=30)
            self.bq_client.create_table(staging_table)
            
            # 2. Load data to staging table
            logger.info(f"Loading {len(rows)} rows to staging table")
            
            # Convert types for JSON loading
            processed_rows = []
            for row in rows:
                converted = self._convert_for_json_load(row)
                processed_rows.append(converted)
            
            job_config = bigquery.LoadJobConfig(
                schema=main_table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
            )
            
            load_job = self.bq_client.load_table_from_json(
                processed_rows,
                staging_table_id,
                job_config=job_config
            )
            load_job.result()  # Wait for completion
            
            # 3. Execute MERGE from staging to main
            logger.info("Executing MERGE from staging to main table")
            
            # Build ON clause
            on_conditions = " AND ".join([f"T.{key} = S.{key}" for key in merge_keys])
            
            # Build UPDATE SET clause (all fields except merge keys)
            all_fields = [field.name for field in main_table.schema]
            update_fields = [f for f in all_fields if f not in merge_keys]
            update_set = ", ".join([f"{field} = S.{field}" for field in update_fields])
            
            # Build INSERT clause
            insert_fields = ", ".join(all_fields)
            insert_values = ", ".join([f"S.{field}" for field in all_fields])
            
            merge_query = f"""
            MERGE `{table_id}` T
            USING `{staging_table_id}` S
            ON {on_conditions}
            WHEN MATCHED THEN
                UPDATE SET {update_set}
            WHEN NOT MATCHED THEN
                INSERT ({insert_fields})
                VALUES ({insert_values})
            """
            
            merge_job = self.bq_client.query(merge_query)
            merge_job.result()  # Wait for completion
            
            logger.info("MERGE completed successfully")
            
        except Exception as e:
            logger.error(f"MERGE operation failed: {e}")
            raise
            
        finally:
            # Cleanup staging table
            try:
                self.bq_client.delete_table(staging_table_id, not_found_ok=True)
                logger.debug(f"Cleaned up staging table: {staging_table_id}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup staging table: {cleanup_error}")
    
    def _convert_for_json_load(self, record: Dict) -> Dict:
        """
        Convert record types for JSON loading (from lessons learned).
        
        Args:
            record: Dictionary with potentially problematic types
            
        Returns:
            Dictionary with JSON-safe types
        """
        import pandas as pd
        
        converted = {}
        
        timestamp_fields = {'processed_at', 'created_at', 'updated_at'}
        date_fields = {'last_seen_date', 'birth_date'}
        
        for key, value in record.items():
            # Handle lists first (never call pd.isna on arrays)
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
    def _normalize_player_name(self, full_name: str) -> str:
        """Create normalized player lookup key - preserves suffixes, removes special chars."""
        import unicodedata
        
        if not full_name:
            return ""
        
        # Remove accents/diacritics (ñ → n, é → e, etc)
        normalized = unicodedata.normalize('NFD', full_name)
        normalized = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
        
        # Lowercase
        normalized = normalized.lower()
        
        # Remove punctuation and spaces (but keep suffixes like jr, sr, ii, iii)
        for char in [' ', "'", '.', '-', ',']:
            normalized = normalized.replace(char, '')
        
        return normalized
    
    def get_processor_stats(self) -> Dict:
        """Return processor statistics."""
        return {
            'players_processed': self.players_processed,
            'players_failed': self.players_failed,
            'duplicate_count': self.duplicate_count,
            'rows_transformed': len(self.transformed_data) if isinstance(self.transformed_data, list) else 0
        }


# CLI entry point
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process NBA.com player list")
    parser.add_argument("--bucket", default="nba-scraped-data", help="GCS bucket name")
    parser.add_argument("--file-path", help="Path to file in bucket")
    parser.add_argument("--date", help="Date to process (YYYY-MM-DD), discovers latest file automatically")
    parser.add_argument("--project-id", default="nba-props-platform", help="GCP project ID")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Require either file-path or date
    if not args.file_path and not args.date:
        parser.error("Must provide either --file-path or --date")
    
    # Build opts dict
    opts = {
        'bucket': args.bucket,
        'project_id': args.project_id
    }
    
    if args.file_path:
        opts['file_path'] = args.file_path
    
    if args.date:
        opts['date'] = args.date
    
    # Run processor
    processor = NbacPlayerListProcessor()
    success = processor.run(opts)
    
    print(f"\n{'='*60}")
    print(f"{'✅ SUCCESS' if success else '❌ FAILED'}")
    print(f"{'='*60}")
    print(f"Stats: {processor.get_processor_stats()}")
    print(f"{'='*60}")