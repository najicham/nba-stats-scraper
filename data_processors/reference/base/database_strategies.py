#!/usr/bin/env python3
"""
File: data_processors/reference/base/database_strategies.py

Database operation strategies for registry processors.
Provides MERGE and REPLACE strategies with performance optimization and error handling.
Enhanced with processor tracking field support using actual schema field names.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List
from google.cloud import bigquery
from shared.utils.notification_system import notify_error, NotificationLevel, NotificationType, NotificationRouter

logger = logging.getLogger(__name__)


class DatabaseStrategiesMixin:
    """
    Mixin providing database operation strategies for registry processors.
    
    Includes:
    - MERGE mode with temporary table approach
    - REPLACE mode with DELETE + INSERT
    - Performance monitoring and metrics
    - Error handling with graceful degradation
    - Schema enforcement and type safety
    - Enhanced with processor tracking fields using actual schema
    """
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load registry data using configured processing strategy."""
        if not rows:
            logger.info("No records to insert")
            return {'rows_processed': 0, 'errors': []}
        
        if self.processing_strategy.value == "replace":
            return self._load_data_replace_mode(rows, **kwargs)
        elif self.processing_strategy.value == "merge":
            return self._load_data_merge_mode(rows, **kwargs)
        else:
            raise ValueError(f"Unknown processing strategy: {self.processing_strategy}")
    
    def _load_data_replace_mode(self, rows: List[Dict], **kwargs) -> Dict:
        """REPLACE mode: DELETE existing data + INSERT new data."""
        logger.info(f"Using REPLACE mode for {len(rows)} records")
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # Step 1: Delete existing records
            logger.info(f"Step 1: Deleting existing records from {self.table_name}")
            delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
            delete_job = self.bq_client.query(delete_query)
            delete_result = delete_job.result()
            deleted_count = delete_job.num_dml_affected_rows or 0
            logger.info(f"Deleted {deleted_count} existing records")
            
            # Step 2: Insert new records in batches
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
            
            # Send error notification
            try:
                notify_error(
                    title="Database REPLACE Operation Failed",
                    message=f"Registry REPLACE mode failed: {str(e)}",
                    details={
                        'operation': 'REPLACE',
                        'table': self.table_name,
                        'records_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'processing_run_id': getattr(self, 'processing_run_id', 'unknown')
                    },
                    processor_name="Registry Database Operations"
                )
            except Exception as notify_error_ex:
                logger.warning(f"Failed to send error notification: {notify_error_ex}")
            
            return {
                'rows_processed': 0,
                'errors': errors
            }
        
    def _load_data_merge_mode(self, rows: List[Dict], **kwargs) -> Dict:
        """
        MERGE mode: MERGE data atomically using temporary table approach.
        
        This approach:
        1. Creates temporary table with same schema
        2. Loads data to temp table (handles type conversion gracefully)
        3. MERGE from temp table to main table (no STRUCT parameters)
        4. Cleanup temp table
        """
        logger.info(f"Using MERGE mode (temp table approach) for {len(rows)} records")
        
        operation_start = time.time()
        logger.info(f"PERF_METRIC: main_registry_merge_start record_count={len(rows)}")
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        temp_table_id = None
        
        try:
            # Step 1: Create temporary table
            temp_table_suffix = uuid.uuid4().hex[:8]
            temp_table_id = f"{table_id}_temp_{temp_table_suffix}"
            
            logger.info(f"Creating temporary table: {temp_table_id}")
            
            # Get main table schema
            main_table = self.bq_client.get_table(table_id)
            
            # Create temp table with same schema
            temp_table = bigquery.Table(temp_table_id, schema=main_table.schema)
            temp_table = self.bq_client.create_table(temp_table)
            
            logger.info(f"✅ Temporary table created successfully")
            
            # Step 2: Load data to temp table
            logger.info(f"Loading {len(rows)} records to temporary table")
            
            rows_for_loading = [self._convert_pandas_types_for_json(row) for row in rows]
            
            load_job = self.bq_client.load_table_from_json(
                rows_for_loading, 
                temp_table_id,
                job_config=bigquery.LoadJobConfig(
                    autodetect=False,
                    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
                )
            )
            
            load_result = load_job.result()
            logger.info(f"✅ Data loaded to temp table: {load_job.output_rows} rows")
            
            # Step 3: MERGE from temp table to main table
            logger.info("Executing MERGE from temporary table to main table")
            
            merge_query = self._build_merge_query(table_id, temp_table_id)
            
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result()
            
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
            
            errors.append(error_msg)
            
            # Send error notification
            try:
                notify_error(
                    title="Database MERGE Operation Failed",
                    message=f"Registry MERGE mode failed: {str(e)}",
                    details={
                        'operation': 'MERGE',
                        'table': self.table_name,
                        'records_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'temp_table': temp_table_id,
                        'processing_run_id': getattr(self, 'processing_run_id', 'unknown')
                    },
                    processor_name="Registry Database Operations"
                )
            except Exception as notify_error_ex:
                logger.warning(f"Failed to send error notification: {notify_error_ex}")
            
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

    def _build_merge_query(self, table_id: str, temp_table_id: str) -> str:
        """Build MERGE query for registry table with actual schema field names."""
        return f"""
        MERGE `{table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.player_lookup = source.player_lookup 
        AND target.team_abbr = source.team_abbr 
        AND target.season = source.season
        WHEN MATCHED THEN
        UPDATE SET 
            universal_player_id = source.universal_player_id,
            player_name = source.player_name,
            first_game_date = source.first_game_date,
            last_game_date = source.last_game_date,
            games_played = source.games_played,
            total_appearances = source.total_appearances,
            inactive_appearances = source.inactive_appearances,
            dnp_appearances = source.dnp_appearances,
            jersey_number = source.jersey_number,
            position = source.position,
            last_roster_update = CASE 
                WHEN source.last_processor = 'roster' THEN source.last_roster_update
                ELSE target.last_roster_update
            END,
            source_priority = source.source_priority,
            confidence_score = source.confidence_score,
            processed_at = source.processed_at,
            
            -- Processor tracking fields using actual schema names
            last_processor = source.last_processor,
            last_gamebook_update = CASE 
                WHEN source.last_processor = 'gamebook' THEN source.last_gamebook_update
                ELSE target.last_gamebook_update
            END,
            last_roster_update = CASE 
                WHEN source.last_processor = 'roster' THEN source.last_roster_update
                ELSE target.last_roster_update
            END,
            gamebook_update_count = CASE 
                WHEN source.last_processor = 'gamebook' THEN COALESCE(target.gamebook_update_count, 0) + 1
                ELSE COALESCE(target.gamebook_update_count, 0)
            END,
            roster_update_count = CASE 
                WHEN source.last_processor = 'roster' THEN COALESCE(target.roster_update_count, 0) + 1
                ELSE COALESCE(target.roster_update_count, 0)
            END,
            update_sequence_number = source.update_sequence_number
            
        WHEN NOT MATCHED THEN
        INSERT (
            universal_player_id, player_name, player_lookup, team_abbr, season, first_game_date,
            last_game_date, games_played, total_appearances, inactive_appearances,
            dnp_appearances, jersey_number, position, last_roster_update,
            source_priority, confidence_score, created_by, created_at, processed_at,
            
            -- Processor tracking fields using actual schema names
            last_processor, last_gamebook_update, last_roster_update,
            gamebook_update_count, roster_update_count, update_sequence_number
        )
        VALUES (
            source.universal_player_id, source.player_name, source.player_lookup, source.team_abbr, source.season,
            source.first_game_date, source.last_game_date, source.games_played,
            source.total_appearances, source.inactive_appearances, source.dnp_appearances,
            source.jersey_number, source.position, source.last_roster_update,
            source.source_priority, source.confidence_score, source.created_by,
            source.created_at, source.processed_at,
            
            -- Processor tracking fields using actual schema names
            source.last_processor,
            CASE WHEN source.last_processor = 'gamebook' THEN source.last_gamebook_update ELSE NULL END,
            CASE WHEN source.last_processor = 'roster' THEN source.last_roster_update ELSE NULL END,
            CASE WHEN source.last_processor = 'gamebook' THEN 1 ELSE 0 END,
            CASE WHEN source.last_processor = 'roster' THEN 1 ELSE 0 END,
            source.update_sequence_number
        )
        """

    def _insert_unresolved_players(self, unresolved_records: List[Dict]):
        """Insert unresolved player records respecting the processing strategy."""
        if not unresolved_records:
            return
        
        # Deduplicate within this run
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
                dedup_dict[key]['occurrences'] += record.get('occurrences', 1)
        
        deduplicated_records = list(dedup_dict.values())
        
        if len(deduplicated_records) < len(unresolved_records):
            logger.info(f"Within-run deduplication: {len(unresolved_records)} → {len(deduplicated_records)} records")
        
        # Convert types for BigQuery
        processed_records = []
        for record in deduplicated_records:
            processed_record = self._convert_pandas_types_for_json(record)
            processed_records.append(processed_record)
        
        # Use appropriate strategy
        if self.processing_strategy.value == "replace":
            logger.info(f"Using REPLACE strategy for {len(processed_records)} unresolved players")
            self._replace_unresolved_players(processed_records)
        else:
            logger.info(f"Using MERGE strategy for {len(processed_records)} unresolved players") 
            self._merge_unresolved_players(processed_records)

    def _replace_unresolved_players(self, processed_records: List[Dict]):
        """REPLACE mode: DELETE existing unresolved players + INSERT new ones."""
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        
        try:
            # Delete existing records
            logger.info(f"Deleting existing unresolved players from {self.unresolved_table_name}")
            delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
            delete_job = self.bq_client.query(delete_query)
            delete_result = delete_job.result()
            deleted_count = delete_job.num_dml_affected_rows or 0
            logger.info(f"Deleted {deleted_count} existing unresolved player records")
            
            # Insert new records
            if processed_records:
                logger.info(f"Inserting {len(processed_records)} new unresolved player records")
                insert_errors = self.bq_client.insert_rows_json(table_id, processed_records)
                
                if insert_errors:
                    logger.error(f"Unresolved players insertion errors: {insert_errors}")
                else:
                    logger.info(f"Successfully inserted {len(processed_records)} unresolved player records")
                    
        except Exception as e:
            logger.error(f"Error in REPLACE mode for unresolved players: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="Unresolved Players REPLACE Failed",
                    message=f"Failed to replace unresolved players: {str(e)}",
                    details={
                        'operation': 'REPLACE_UNRESOLVED',
                        'table': self.unresolved_table_name,
                        'records_attempted': len(processed_records),
                        'error_type': type(e).__name__,
                        'processing_run_id': getattr(self, 'processing_run_id', 'unknown')
                    },
                    processor_name="Registry Database Operations"
                )
            except Exception as notify_error_ex:
                logger.warning(f"Failed to send error notification: {notify_error_ex}")

    def _merge_unresolved_players(self, processed_records: List[Dict]):
        """MERGE mode for unresolved players with graceful error handling."""
        if not processed_records:
            return
        
        operation_start = time.time()
        table_id = f"{self.project_id}.{self.unresolved_table_name}"
        temp_table_id = None
        
        logger.info(f"PERF_METRIC: unresolved_merge_start record_count={len(processed_records)}")
        
        try:
            # Create temporary table for MERGE operation
            temp_table_suffix = uuid.uuid4().hex[:8]
            temp_table_id = f"{table_id}_temp_{temp_table_suffix}"
            
            # Get main table schema and create temp table
            main_table = self.bq_client.get_table(table_id)
            temp_table = bigquery.Table(temp_table_id, schema=main_table.schema)
            temp_table = self.bq_client.create_table(temp_table)
            
            # Prepare records with schema enforcement
            converted_records = []
            for record in processed_records:
                r = self._convert_pandas_types_for_json(record, for_table_load=True)
                r = self._ensure_required_defaults(r, main_table.schema)
                converted_records.append(r)
            
            # Load to temp table
            job_config = bigquery.LoadJobConfig(
                schema=main_table.schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                autodetect=False,
                ignore_unknown_values=True
            )
            
            load_job = self.bq_client.load_table_from_json(
                converted_records, 
                temp_table_id, 
                job_config=job_config
            )
            load_result = load_job.result()
            
            # Execute MERGE using actual field names
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
            
            num_affected = merge_job.num_dml_affected_rows or 0
            total_duration = time.time() - operation_start
            
            logger.info(f"PERF_METRIC: unresolved_merge_success total_duration={total_duration:.3f}s records_processed={len(processed_records)} rows_affected={num_affected}")
            
        except Exception as e:
            error_duration = time.time() - operation_start
            error_type = type(e).__name__
            
            logger.error(f"PERF_METRIC: unresolved_merge_error duration={error_duration:.3f}s error_type={error_type}")
            
            # Check for streaming buffer conflicts
            if "streaming buffer" in str(e).lower():
                logger.warning(f"MERGE blocked by streaming buffer - {len(processed_records)} unresolved players skipped this run")
                logger.info("Records will be processed on the next run when streaming buffer clears")
            else:
                logger.error(f"MERGE failed with error: {str(e)}")
                
                # Send error notification (only for non-streaming-buffer errors)
                try:
                    notify_error(
                        title="Unresolved Players MERGE Failed",
                        message=f"Failed to merge unresolved players: {str(e)}",
                        details={
                            'operation': 'MERGE_UNRESOLVED',
                            'table': self.unresolved_table_name,
                            'records_attempted': len(processed_records),
                            'error_type': error_type,
                            'duration_seconds': error_duration,
                            'processing_run_id': getattr(self, 'processing_run_id', 'unknown')
                        },
                        processor_name="Registry Database Operations"
                    )
                except Exception as notify_error_ex:
                    logger.warning(f"Failed to send error notification: {notify_error_ex}")
                
                raise e
                
        finally:
            # Always clean up temporary table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp table: {cleanup_error}")

    def _ensure_required_defaults(self, record: dict, schema) -> dict:
        """Ensure all REQUIRED fields have non-null values."""
        out = dict(record)
        current_utc = datetime.now(timezone.utc)
        current_date = current_utc.date()
        
        required_field_names = {f.name for f in schema if f.mode == "REQUIRED"}
        
        # Handle common REQUIRED fields
        if "created_at" in required_field_names and out.get("created_at") is None:
            out["created_at"] = current_utc
            
        if "processed_at" in required_field_names and out.get("processed_at") is None:
            out["processed_at"] = current_utc
            
        if "first_seen_date" in required_field_names and out.get("first_seen_date") is None:
            out["first_seen_date"] = current_date
            
        if "last_seen_date" in required_field_names and out.get("last_seen_date") is None:
            out["last_seen_date"] = current_date
            
        if "occurrences" in required_field_names and out.get("occurrences") is None:
            out["occurrences"] = 1
            
        if "status" in required_field_names and out.get("status") is None:
            out["status"] = "pending"
            
        if "example_games" in required_field_names and out.get("example_games") is None:
            out["example_games"] = []
        
        return out