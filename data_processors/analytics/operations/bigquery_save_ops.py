"""
BigQuery Save Operations Mixin

Extracted from analytics_base.py to separate BigQuery save logic.

This mixin provides BigQuery save operations including:
- save_analytics(): Main save method with MERGE_UPDATE strategy support
- _save_with_proper_merge(): SQL MERGE with comprehensive validation
- _save_with_delete_insert(): DELETE + INSERT fallback strategy
- _delete_existing_data_batch(): Deprecated batch DELETE method

Dependencies from parent class:
- self.bq_client: BigQuery client instance
- self.project_id: GCP project ID
- self.table_name: Target table name
- self.transformed_data: Data to save (list or dict)
- self.opts: Processing options dict (with start_date, end_date)
- self.run_id: Current run ID
- self.stats: Statistics dictionary (rows_processed, rows_skipped)
- self.processing_strategy: Save strategy ('MERGE_UPDATE' or other)
- self.raw_data: Optional raw data reference
- self.get_output_dataset(): Method returning output dataset name
- self._send_notification(): Notification method
- self._sanitize_row_for_json(): Row sanitization method
- self._check_for_duplicates_post_save(): Duplicate check method
- self.__class__.PRIMARY_KEY_FIELDS: Optional primary key fields list
- self.__class__.__name__: Processor name

Created: 2026-01-25 - Extracted from analytics_base.py
"""

import io
import json
import logging
import uuid
from typing import Dict, List

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError, NotFound

from shared.utils.notification_system import notify_error, notify_warning
from shared.utils.bigquery_retry import (
    retry_on_quota_exceeded,
    retry_on_serialization,
)
from shared.validation.pre_write_validator import PreWriteValidator, create_validation_failure_record
from shared.utils.data_quality_logger import get_quality_logger

logger = logging.getLogger(__name__)


class StreamingBufferActiveError(Exception):
    """Raised when streaming buffer prevents safe DELETE operation."""
    pass


class BigQuerySaveOpsMixin:
    """
    Mixin providing BigQuery save operations for analytics processors.

    This mixin requires the parent class to provide specific attributes and methods.
    See module docstring for complete dependency list.
    """

    @retry_on_quota_exceeded
    # NOTE: @retry_on_serialization REMOVED from here (Session 37 fix)
    # The retry is handled inside _save_with_proper_merge() at line 256
    # Having it here caused DOUBLE execution on serialization errors:
    # 1. MERGE succeeds, result() throws error
    # 2. @retry_on_serialization on _save_with_proper_merge retries (expected)
    # 3. @retry_on_serialization HERE retries ENTIRE save_analytics() (BUG)
    # 4. Records get inserted TWICE with different timestamps
    # See: docs/08-projects/current/v8-model-investigation/SESSION-37-INVESTIGATION-REPORT.md
    def save_analytics(self) -> bool:
        """
        Save calculated analytics to BigQuery using batch loading.

        Converts self.transformed_data to NDJSON format and loads to the
        target table specified by self.table_name in the analytics dataset.

        Uses batch loading (load_table_from_file) instead of streaming inserts
        for better reliability and to avoid streaming buffer conflicts.

        The method handles:
        - Schema enforcement from target table
        - Retry logic for serialization conflicts
        - Graceful handling of streaming buffer conflicts
        - Statistics tracking (rows_inserted)

        Returns:
            bool: True if save was successful, False otherwise

        Raises:
            Exception: On BigQuery load failures after retries
        """
        if not self.transformed_data:
            # Check if this was an intentional skip (no data to process is expected)
            # Don't send warnings for intentional skips to reduce noise
            skip_reason = self.stats.get('skipped_reason')
            if skip_reason:
                logger.info(f"⏭️  No data to save (intentional skip: {skip_reason})")
                self.stats['rows_processed'] = 0
                return True  # Return success for intentional skips

            logger.warning("No transformed data to save")
            try:
                self._send_notification(
                    notify_warning,
                    title=f"Analytics Processor No Data to Save: {self.__class__.__name__}",
                    message="No analytics data calculated to save",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'raw_data_exists': self.raw_data is not None,
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return False

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                self._send_notification(
                    notify_error,
                    title=f"Analytics Processor Data Type Error: {self.__class__.__name__}",
                    message=error_msg,
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': self.table_name,
                        'data_type': str(type(self.transformed_data)),
                        'expected_types': ['list', 'dict']
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise ValueError(error_msg)

        if not rows:
            logger.warning("No rows to insert")
            return False

        # Deduplicate before save (prevents duplicates from multiple processing)
        rows = self._deduplicate_records(rows)

        # Pre-write validation: Block records that would corrupt downstream data
        rows = self._validate_before_write(rows, table_id)
        if not rows:
            logger.warning("All rows blocked by pre-write validation")
            return False

        # Get target table schema (needed for both MERGE and INSERT strategies)
        try:
            table = self.bq_client.get_table(table_id)
            table_schema = table.schema
            logger.info(f"Using schema with {len(table_schema)} fields")
        except (GoogleAPIError, NotFound) as schema_e:
            logger.warning(f"Could not get table schema: {schema_e}")
            table_schema = None

        # Apply processing strategy
        if self.processing_strategy == 'MERGE_UPDATE':
            # Use proper SQL MERGE (prevents duplicates, no streaming buffer issues)
            self._save_with_proper_merge(rows, table_id, table_schema)

            # Check for duplicates after successful merge
            self._check_for_duplicates_post_save()
            return True  # MERGE completed successfully

        # For non-MERGE strategies, use batch INSERT via BigQuery load job
        logger.info(f"Inserting {len(rows)} rows to {table_id} using batch INSERT")

        try:
            # Sanitize and convert to NDJSON
            sanitized_rows = []
            for i, row in enumerate(rows):
                try:
                    sanitized = self._sanitize_row_for_json(row)
                    # Validate JSON serialization
                    json.dumps(sanitized)
                    sanitized_rows.append(sanitized)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Skipping row {i} due to JSON error: {e}")
                    continue

            if not sanitized_rows:
                logger.warning("No valid rows after sanitization")
                return False

            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')
            logger.info(f"Sanitized {len(sanitized_rows)}/{len(rows)} rows for JSON")

            # Configure load job
            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=(table_schema is None),  # Auto-detect schema on first run when table doesn't exist
                schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]  # Allow adding new fields (Session 107 metrics)
            )

            # Load to target table
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )

            # Wait for completion
            try:
                load_job.result(timeout=300)
                logger.info(f"✅ Successfully loaded {len(sanitized_rows)} rows")
                self.stats["rows_processed"] = len(sanitized_rows)

                # Check for duplicates after successful save
                self._check_for_duplicates_post_save()

                return True  # Successfully saved data

            except Exception as load_e:
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    self.stats["rows_processed"] = 0
                    return False
                else:
                    # Log detailed error info from BigQuery load job
                    if hasattr(load_job, 'errors') and load_job.errors:
                        logger.error(f"BigQuery load job errors ({len(load_job.errors)} total):")
                        for i, error in enumerate(load_job.errors[:10]):  # Log first 10
                            logger.error(f"  Error {i+1}: {error}")
                    # Log sample of problematic rows
                    if sanitized_rows and len(sanitized_rows) > 0:
                        logger.error(f"Sample row keys: {list(sanitized_rows[0].keys())}")
                        # Log first row for debugging
                        try:
                            sample_row = {k: (v if not isinstance(v, str) or len(str(v)) < 100 else str(v)[:100]+'...') for k, v in sanitized_rows[0].items()}
                            logger.error(f"Sample row (truncated): {json.dumps(sample_row, default=str)}")
                        except Exception as sample_e:
                            logger.error(f"Could not log sample row: {sample_e}")
                    raise load_e

        except Exception as e:
            error_msg = f"Batch insert failed: {str(e)}"
            logger.error(error_msg)
            try:
                self._send_notification(
                    notify_error,
                    title=f"Analytics Processor Batch Insert Failed: {self.__class__.__name__}",
                    message=f"Failed to batch insert {len(rows)} analytics rows",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}"
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    @retry_on_serialization
    def _save_with_proper_merge(self, rows: List[Dict], table_id: str, table_schema) -> None:
        """
        Save data using proper SQL MERGE statement with comprehensive validation.

        This method:
        1. Validates all inputs before proceeding
        2. Loads data into a temporary table
        3. Executes a SQL MERGE statement to upsert records
        4. Falls back to DELETE+INSERT if MERGE fails
        5. Cleans up the temporary table

        Advantages:
        - Single atomic operation (no streaming buffer issues)
        - No duplicates created
        - Proper upsert semantics
        - Automatic fallback on failure

        Updated: 2026-01-15 Session 56 - Added comprehensive validation and auto-fallback
        """

        # ============================================
        # VALIDATION PHASE - Fail fast with clear errors
        # ============================================

        if not rows:
            logger.warning("No rows to merge")
            return

        # Check if PRIMARY_KEY_FIELDS is defined
        if not hasattr(self.__class__, 'PRIMARY_KEY_FIELDS'):
            logger.warning(f"PRIMARY_KEY_FIELDS not defined for {self.__class__.__name__} - using DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        primary_keys = self.__class__.PRIMARY_KEY_FIELDS
        if not primary_keys or len(primary_keys) == 0:
            logger.warning(f"PRIMARY_KEY_FIELDS is empty - using DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # ============================================
        # SANITIZATION PHASE
        # ============================================

        sanitized_rows = []
        for i, row in enumerate(rows):
            try:
                sanitized = self._sanitize_row_for_json(row)
                json.dumps(sanitized)  # Validate JSON serialization
                sanitized_rows.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping row {i} due to JSON error: {e}")
                continue

        if not sanitized_rows:
            logger.warning("No valid rows after sanitization")
            return

        # ============================================
        # FIELD ANALYSIS PHASE
        # ============================================

        # Get all field names from schema or fallback to row keys
        if table_schema and len(table_schema) > 0:
            schema_fields = [field.name for field in table_schema]
            # Also include fields from data that might not be in schema yet (Session 107 metrics)
            data_fields = list(sanitized_rows[0].keys()) if sanitized_rows else []
            # Merge: schema fields first, then any new fields from data
            all_fields = schema_fields + [f for f in data_fields if f not in schema_fields]
            logger.debug(f"Using {len(schema_fields)} schema fields + {len(all_fields) - len(schema_fields)} new data fields = {len(all_fields)} total")
        else:
            # Fallback: use keys from first row
            all_fields = list(sanitized_rows[0].keys()) if sanitized_rows else []
            logger.warning(f"No schema provided, using {len(all_fields)} fields from row keys")

        # CRITICAL VALIDATION: Ensure we have fields
        if not all_fields:
            logger.error("CRITICAL: No fields found in schema or row data - falling back to DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # Validate primary keys exist in all_fields
        missing_pks = [pk for pk in primary_keys if pk not in all_fields]
        if missing_pks:
            logger.error(f"CRITICAL: Primary keys {missing_pks} not in fields - falling back to DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # Fields to update (all except primary keys)
        update_fields = [f for f in all_fields if f not in primary_keys]

        # ============================================
        # QUERY CONSTRUCTION PHASE
        # ============================================

        def quote_identifier(name: str) -> str:
            """Safely quote BigQuery identifier."""
            if name is None:
                return '`NULL`'
            return f"`{str(name).replace('`', '')}`"

        # Build ON clause
        on_clause = ' AND '.join([
            f"target.{quote_identifier(key)} = source.{quote_identifier(key)}"
            for key in primary_keys
        ])

        # CRITICAL: Handle empty update_fields gracefully
        if not update_fields:
            logger.warning("No non-key fields to update - using no-op MERGE")
            update_set = f"{quote_identifier(primary_keys[0])} = source.{quote_identifier(primary_keys[0])}"
        else:
            update_set = ', '.join([
                f"{quote_identifier(f)} = source.{quote_identifier(f)}"
                for f in update_fields
            ])

        # CRITICAL VALIDATION: Ensure update_set is not empty
        if not update_set or len(update_set.strip()) == 0:
            logger.error(f"CRITICAL: update_set is empty! primary_keys={primary_keys}, update_fields={update_fields}")
            logger.error("Falling back to DELETE + INSERT")
            self._save_with_delete_insert(rows, table_id, table_schema)
            return

        # Build INSERT clause
        insert_fields = ', '.join([quote_identifier(f) for f in all_fields])
        insert_values = ', '.join([f"source.{quote_identifier(f)}" for f in all_fields])

        # Partition by clause for deduplication
        primary_keys_partition = ', '.join(primary_keys)

        # Build partition filter for BigQuery optimization
        partition_prefix = ""
        if 'game_date' in all_fields and sanitized_rows:
            game_dates = sorted(set(
                str(row.get('game_date')) for row in sanitized_rows
                if row.get('game_date') is not None
            ))
            if game_dates:
                if len(game_dates) == 1:
                    partition_prefix = f"target.game_date = DATE('{game_dates[0]}') AND "
                else:
                    # Build proper IN clause: DATE('2026-01-13'), DATE('2026-01-14')
                    dates_list = [f"DATE('{d}')" for d in game_dates]
                    partition_prefix = f"target.game_date IN ({', '.join(dates_list)}) AND "
                logger.debug(f"Adding partition filter for {len(game_dates)} dates")

        # ============================================
        # TEMP TABLE PHASE
        # ============================================

        temp_table_name = f"{self.table_name}_temp_{uuid.uuid4().hex[:8]}"
        temp_table_id = f"{self.project_id}.{self.get_output_dataset()}.{temp_table_name}"

        logger.info(f"Using SQL MERGE with temp table: {temp_table_name}")
        logger.info(f"MERGE config: {len(sanitized_rows)} rows, {len(all_fields)} fields, {len(update_fields)} update fields")

        merge_query = None  # Define for error logging

        try:
            # Load data into temp table
            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')

            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=(table_schema is None),
                # Note: schema_update_options not compatible with WRITE_TRUNCATE on non-partitioned tables
                # Temp table doesn't need schema updates - it's recreated each time
            )

            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                temp_table_id,
                job_config=job_config
            )
            load_job.result(timeout=300)
            logger.info(f"✅ Loaded {len(sanitized_rows)} rows into temp table")

            # ============================================
            # MERGE EXECUTION PHASE
            # ============================================

            merge_query = f"""
            MERGE `{table_id}` AS target
            USING (
                SELECT * EXCEPT(__row_num) FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY {primary_keys_partition}
                        ORDER BY processed_at DESC
                    ) as __row_num
                    FROM `{temp_table_id}`
                ) WHERE __row_num = 1
            ) AS source
            ON {partition_prefix}{on_clause}
            WHEN MATCHED THEN
                UPDATE SET {update_set}
            WHEN NOT MATCHED THEN
                INSERT ({insert_fields})
                VALUES ({insert_values})
            """

            # ALWAYS log key details at INFO level for debugging
            logger.info(f"Executing MERGE on primary keys: {', '.join(primary_keys)}")
            logger.info(f"MERGE DEBUG - update_set ({len(update_set)} chars): '{update_set[:100]}...'")

            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result(timeout=300)

            # Get stats
            affected = merge_job.num_dml_affected_rows or 0
            logger.info(f"✅ MERGE completed: {affected} rows affected")
            self.stats["rows_processed"] = len(sanitized_rows)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"MERGE failed: {error_msg}")

            # Log the full query for debugging
            if merge_query:
                logger.error(f"Failed MERGE query:\n{merge_query}")

            # Structured logging for MERGE fallback (added 2026-01-27)
            # Enables post-mortem diagnosis of why MERGEs fail
            fallback_reason = "unknown"
            if "syntax error" in error_msg.lower():
                fallback_reason = "syntax_error"
            elif "400" in error_msg:
                fallback_reason = "bad_request"
            elif "streaming buffer" in error_msg.lower():
                fallback_reason = "streaming_buffer"
            elif "not found" in error_msg.lower():
                fallback_reason = "table_not_found"

            logger.error("merge_fallback", extra={
                "event": "merge_fallback",
                "processor": self.__class__.__name__,
                "table": table_id,
                "reason": fallback_reason,
                "error_message": error_msg[:500],
                "rows_affected": len(rows),
                "primary_keys": primary_keys,
                "update_fields_count": len(update_fields),
                "fallback_strategy": "DELETE_INSERT",
                "will_retry": False
            })

            # Auto-fallback: If syntax error, use DELETE+INSERT
            if "syntax error" in error_msg.lower() or "400" in error_msg:
                logger.warning("MERGE syntax error detected - falling back to DELETE + INSERT")

                # Notify operators about MERGE fallback (added 2026-01-24)
                # This was previously a silent fallback that could mask data issues
                try:
                    notify_warning(
                        title=f"MERGE Fallback: {self.__class__.__name__}",
                        message=f"MERGE failed with syntax error, falling back to DELETE + INSERT",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': getattr(self, 'run_id', 'unknown'),
                            'table': table_id,
                            'error': error_msg[:500],  # Truncate long errors
                            'rows_affected': len(rows),
                            'strategy': 'DELETE + INSERT (fallback)',
                            'remediation': 'Check MERGE query syntax. This is not critical but may indicate schema issues.',
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send MERGE fallback notification: {notify_ex}")

                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                except Exception as cleanup_e:
                    logger.debug(f"Could not delete temp table during fallback: {cleanup_e}")
                self._save_with_delete_insert(rows, table_id, table_schema)
                return

            raise

        finally:
            # Always clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                logger.debug(f"Cleaned up temp table: {temp_table_name}")
            except Exception as cleanup_e:
                logger.warning(f"Could not clean up temp table: {cleanup_e}")

    def _save_with_delete_insert(self, rows: List[Dict], table_id: str, table_schema) -> None:
        """
        Save rows using DELETE + INSERT strategy (simpler, more reliable fallback).

        This method:
        1. Deletes existing records for the game_dates in the data
        2. Inserts new records via batch load

        Benefits:
        - Simpler SQL, fewer edge cases
        - Works reliably when MERGE fails
        - Still prevents duplicates (via DELETE first)

        Drawbacks:
        - Not fully atomic (small window between DELETE and INSERT)
        - Deletes ALL records for the dates, even unchanged ones

        Added: 2026-01-15 Session 56 - Fallback for MERGE failures
        """

        if not rows:
            logger.warning("No rows for DELETE + INSERT")
            return

        logger.info(f"Using DELETE + INSERT strategy for {len(rows)} rows")

        # Sanitize rows
        sanitized_rows = []
        for i, row in enumerate(rows):
            try:
                sanitized = self._sanitize_row_for_json(row)
                json.dumps(sanitized)
                sanitized_rows.append(sanitized)
            except (TypeError, ValueError) as e:
                logger.warning(f"Skipping row {i} due to JSON error: {e}")
                continue

        if not sanitized_rows:
            logger.warning("No valid rows after sanitization")
            return

        # Extract game_dates for DELETE
        game_dates = sorted(set(
            str(row.get('game_date')) for row in sanitized_rows
            if row.get('game_date') is not None
        ))

        if game_dates:
            # Step 1: DELETE existing records for these dates
            # Use parameterized query to prevent SQL injection
            if len(game_dates) == 1:
                delete_query = f"DELETE FROM `{table_id}` WHERE game_date = @game_date"
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_dates[0]),
                    ]
                )
            else:
                delete_query = f"DELETE FROM `{table_id}` WHERE game_date IN UNNEST(@game_dates)"
                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ArrayQueryParameter("game_dates", "DATE", game_dates),
                    ]
                )

            try:
                logger.info(f"Deleting existing records for {len(game_dates)} date(s)")
                delete_job = self.bq_client.query(delete_query, job_config=job_config)
                delete_job.result(timeout=300)
                deleted = delete_job.num_dml_affected_rows or 0
                logger.info(f"✅ Deleted {deleted} existing rows")
            except Exception as e:
                error_str = str(e).lower()
                if "not found" in error_str or "404" in error_str:
                    logger.info("Table doesn't exist yet - will be created on INSERT")
                elif "streaming buffer" in error_str:
                    # Structured logging for streaming buffer conflicts (added 2026-01-27)
                    # Enables diagnosis of why DELETEs fail and when retries will succeed
                    logger.warning("streaming_buffer_active", extra={
                        "event": "streaming_buffer_active",
                        "processor": self.__class__.__name__,
                        "table": table_id,
                        "operation": "DELETE",
                        "game_dates": game_dates,
                        "records_affected": len(rows),
                        "will_retry": True,
                        "retry_behavior": "Next trigger will process after buffer flushes (90 min max)",
                        "resolution": "Wait for streaming buffer to flush or use MERGE strategy instead"
                    })
                    logger.warning(
                        "Delete blocked by streaming buffer. "
                        "Aborting to prevent duplicates. Will retry on next trigger."
                    )
                    raise StreamingBufferActiveError(
                        f"Cannot delete due to streaming buffer for {table_id}. "
                        "Data will be processed on next trigger when buffer flushes."
                    )
                else:
                    logger.error(f"DELETE failed: {e}")
                    raise

        # Step 2: INSERT new records using batch load
        ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
        ndjson_bytes = ndjson_data.encode('utf-8')

        job_config = bigquery.LoadJobConfig(
            schema=table_schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            autodetect=(table_schema is None),
            schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]  # Allow adding new fields (Session 107 metrics)
        )

        try:
            logger.info(f"Inserting {len(sanitized_rows)} rows")
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                table_id,
                job_config=job_config
            )
            load_job.result(timeout=300)
            logger.info(f"✅ INSERT completed: {len(sanitized_rows)} rows inserted")
            self.stats["rows_processed"] = len(sanitized_rows)
        except Exception as e:
            logger.error(f"INSERT failed: {e}")
            raise

    @retry_on_serialization
    def _delete_existing_data_batch(self, rows: List[Dict]) -> None:
        """
        Delete existing data using batch DELETE query.

        DEPRECATED: Use _save_with_proper_merge() instead.
        This method is kept for backwards compatibility.
        """
        if not rows:
            return

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Get date range from opts
        start_date = self.opts.get('start_date')
        end_date = self.opts.get('end_date')

        if start_date and end_date:
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            """

            logger.info(f"Deleting existing data for {start_date} to {end_date}")

            try:
                delete_job = self.bq_client.query(delete_query)
                delete_job.result(timeout=300)

                if delete_job.num_dml_affected_rows is not None:
                    logger.info(f"✅ Deleted {delete_job.num_dml_affected_rows} existing rows")
                else:
                    logger.info(f"✅ Delete completed for date range")

            except Exception as e:
                error_str = str(e).lower()
                if "streaming buffer" in error_str:
                    logger.warning("⚠️ Delete blocked by streaming buffer")
                    logger.info("Duplicates will be cleaned up on next run")
                    return
                elif "not found" in error_str or "404" in error_str:
                    logger.info("✅ Table doesn't exist yet (first run) - will be created during INSERT")
                    return
                else:
                    raise e

    def _validate_before_write(self, rows: List[Dict], table_id: str) -> List[Dict]:
        """
        Validate records against business rules before writing to BigQuery.

        This method blocks records that would corrupt downstream data, such as:
        - DNP players with points=0 (should be NULL)
        - Fatigue scores outside 0-100 range
        - Feature arrays with wrong length

        Args:
            rows: List of records to validate
            table_id: Full BigQuery table ID

        Returns:
            List of valid records (invalid records are logged but not returned)

        Added: 2026-01-30 - Data Quality Self-Healing System
        """
        import os

        # Check if validation is enabled (default: True)
        if os.environ.get('ENABLE_PRE_WRITE_VALIDATION', 'true').lower() != 'true':
            logger.debug("Pre-write validation disabled via environment variable")
            return rows

        if not rows:
            return rows

        # Extract table name from full table_id
        # Format: project.dataset.table_name
        table_name = table_id.split('.')[-1] if '.' in table_id else table_id

        # Create validator for this table
        validator = PreWriteValidator(table_name)

        # If no rules defined for this table, skip validation
        if not validator.rules:
            logger.debug(f"No validation rules for {table_name}, skipping pre-write validation")
            return rows

        # Validate all records
        valid_records, invalid_records = validator.validate(rows)

        # Handle invalid records
        if invalid_records:
            blocked_count = len(invalid_records)
            total_count = len(rows)

            logger.warning(
                f"PRE_WRITE_VALIDATION: Blocked {blocked_count}/{total_count} records "
                f"for {table_name}"
            )

            # Log to quality events table
            try:
                quality_logger = get_quality_logger()
                for record in invalid_records[:5]:  # Log first 5 details
                    violations = record.get('_validation_violations', [])
                    quality_logger.log_validation_blocked(
                        table_name=table_name,
                        game_date=str(record.get('game_date')) if record.get('game_date') else None,
                        player_lookup=record.get('player_lookup'),
                        violations=[v.get('error_message', str(v)) for v in violations],
                        processor_name=self.__class__.__name__
                    )
                quality_logger.flush()
            except Exception as log_e:
                logger.warning(f"Failed to log validation failures: {log_e}")

            # Send notification if significant blocking
            if blocked_count > 10 or blocked_count > total_count * 0.1:
                try:
                    sample_violations = []
                    for record in invalid_records[:3]:
                        violations = record.get('_validation_violations', [])
                        if violations:
                            sample_violations.append(violations[0].get('error_message', 'unknown'))

                    notify_warning(
                        title=f"Pre-Write Validation Blocked Records: {self.__class__.__name__}",
                        message=f"Blocked {blocked_count}/{total_count} records due to validation failures",
                        details={
                            'processor': self.__class__.__name__,
                            'table': table_name,
                            'blocked_count': blocked_count,
                            'total_count': total_count,
                            'sample_violations': sample_violations,
                            'action': 'Records blocked from BigQuery write to prevent data corruption'
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_e:
                    logger.warning(f"Failed to send validation notification: {notify_e}")

        # Return only valid records
        logger.info(
            f"Pre-write validation: {len(valid_records)} valid, "
            f"{len(invalid_records)} blocked for {table_name}"
        )
        return valid_records
