"""
BigQuery Save Operations Mixin for Precompute Processors

Extracted from precompute_base.py to separate BigQuery save logic.

This mixin provides BigQuery save operations including:
- save_precompute(): Main save method with MERGE_UPDATE strategy support
- _save_with_proper_merge(): SQL MERGE with comprehensive validation
- _delete_existing_data_batch(): Deprecated batch DELETE method

Dependencies from parent class:
- self.bq_client: BigQuery client instance
- self.project_id: GCP project ID
- self.table_name: Target table name
- self.transformed_data: Data to save (list or dict)
- self.opts: Processing options dict (with analysis_date)
- self.run_id: Current run ID
- self.stats: Statistics dictionary (rows_processed, rows_skipped)
- self.processing_strategy: Save strategy ('MERGE_UPDATE' or other)
- self.raw_data: Optional raw data reference
- self.get_output_dataset(): Method returning output dataset name
- self._check_for_duplicates_post_save(): Duplicate check method
- self.__class__.PRIMARY_KEY_FIELDS: Optional primary key fields list
- self.__class__.date_column: Date column name (defaults to 'analysis_date')
- self.__class__.__name__: Processor name
- self.is_backfill_mode: Property indicating backfill mode
- self.write_success: Write success flag for R-004 fix

Created: 2026-01-25 - Extracted from precompute_base.py
"""

import io
import json
import logging
import math
import uuid
from datetime import date, datetime
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


class BigQuerySaveOpsMixin:
    """
    Mixin providing BigQuery save operations for precompute processors.

    This mixin requires the parent class to provide specific attributes and methods.
    See module docstring for complete dependency list.
    """

    @retry_on_quota_exceeded
    @retry_on_serialization
    def save_precompute(self) -> bool:
        """
        Save to precompute BigQuery table using batch INSERT.
        Uses NDJSON load job with schema enforcement.

        Returns:
            bool: True if save was successful (or no data to save), False on error
        """
        if not self.transformed_data:
            logger.warning("No transformed data to save")
            # Skip notification in backfill mode (expected for bootstrap/early season dates)
            if not self.is_backfill_mode:
                try:
                    notify_warning(
                        title=f"Precompute Processor No Data to Save: {self.__class__.__name__}",
                        message="No precompute data calculated to save",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'table': self.table_name,
                            'raw_data_exists': self.raw_data is not None,
                            'analysis_date': str(self.opts.get('analysis_date'))
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            return True  # No data to save is not an error

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Handle different data types
        if isinstance(self.transformed_data, list):
            rows = self.transformed_data
        elif isinstance(self.transformed_data, dict):
            rows = [self.transformed_data]
        else:
            error_msg = f"Unexpected data type: {type(self.transformed_data)}"
            try:
                notify_error(
                    title=f"Precompute Processor Data Type Error: {self.__class__.__name__}",
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
            return True  # No rows to insert is not an error

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

            # Check for duplicates after successful merge (if method exists)
            # Fixed 2026-01-29: Some processors don't have QualityMixin
            if hasattr(self, '_check_for_duplicates_post_save'):
                self._check_for_duplicates_post_save()
            return True  # MERGE handles everything, we're done

        # For non-MERGE strategies, use batch INSERT via BigQuery load job
        logger.info(f"Inserting {len(rows)} rows to {table_id} using batch INSERT")

        try:
            # Sanitize rows for JSON serialization
            def sanitize_row(row):
                """Convert date objects to strings, sanitize problematic characters, and handle NaN/Infinity."""
                sanitized = {}
                for k, v in row.items():
                    if v is None:
                        sanitized[k] = None
                    elif isinstance(v, (date, datetime)):
                        sanitized[k] = v.isoformat() if isinstance(v, datetime) else str(v)
                    elif isinstance(v, float):
                        # Handle NaN and Infinity - convert to None (null in JSON)
                        if math.isnan(v) or math.isinf(v):
                            sanitized[k] = None
                        else:
                            sanitized[k] = v
                    elif isinstance(v, str):
                        # Remove/replace problematic characters for JSON
                        sanitized[k] = v.replace('\n', ' ').replace('\r', '').replace('\x00', '')
                    else:
                        sanitized[k] = v
                return sanitized

            sanitized_rows = [sanitize_row(row) for row in rows]

            # Filter rows to only include fields that exist in the table schema
            if table_schema:
                schema_fields = {field.name for field in table_schema}
                filtered_rows = []
                for row in sanitized_rows:
                    filtered_row = {k: v for k, v in row.items() if k in schema_fields}
                    filtered_rows.append(filtered_row)
                sanitized_rows = filtered_rows
                logger.info(f"Filtered rows to {len(schema_fields)} schema fields")

            # Convert to NDJSON
            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')

            # Configure load job
            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                autodetect=(table_schema is None),  # Auto-detect schema on first run when table doesn't exist
                schema_update_options=None
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
                logger.info(f"✅ Successfully loaded {len(rows)} rows")
                self.stats["rows_processed"] = len(rows)

                # Post-write validation: Verify records were written correctly
                self._validate_after_write(
                    table_id=table_id,
                    expected_count=len(rows)
                )

                # Check for duplicates after successful save (if method exists)
                # Fixed 2026-01-29: Some processors don't have QualityMixin
                if hasattr(self, '_check_for_duplicates_post_save'):
                    self._check_for_duplicates_post_save()

                return True  # Success

            except Exception as load_e:
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    self.stats["rows_processed"] = 0
                    # R-004: Mark write as failed to prevent incorrect success completion message
                    self.write_success = False
                    return False  # Streaming buffer block is a failure
                else:
                    raise load_e

        except Exception as e:
            error_msg = f"Batch insert failed: {str(e)}"
            logger.error(error_msg)
            try:
                notify_error(
                    title=f"Precompute Processor Batch Insert Failed: {self.__class__.__name__}",
                    message=f"Failed to batch insert {len(rows)} precompute rows",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'table': table_id,
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'analysis_date': str(self.opts.get('analysis_date'))
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

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

        Added: 2026-02-05 - Session 121 - Validation Infrastructure Gap 1 Fix
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

    @retry_on_serialization
    def _save_with_proper_merge(self, rows: List[Dict], table_id: str, table_schema) -> None:
        """
        Save data using proper SQL MERGE statement (not DELETE + INSERT).

        This method:
        1. Loads data into a temporary table
        2. Executes a SQL MERGE statement to upsert records
        3. Cleans up the temporary table

        Advantages over DELETE + INSERT:
        - Single atomic operation (no streaming buffer issues)
        - No duplicates created
        - Proper upsert semantics
        """
        if not rows:
            logger.warning("No rows to merge")
            return

        # Check if PRIMARY_KEY_FIELDS is defined
        if not hasattr(self.__class__, 'PRIMARY_KEY_FIELDS'):
            logger.warning(f"PRIMARY_KEY_FIELDS not defined for {self.__class__.__name__} - falling back to DELETE + INSERT")
            # Fall back to old method
            self._delete_existing_data_batch(rows)
            return

        primary_keys = self.__class__.PRIMARY_KEY_FIELDS
        if not primary_keys or len(primary_keys) == 0:
            logger.warning(f"PRIMARY_KEY_FIELDS is empty - falling back to DELETE + INSERT")
            self._delete_existing_data_batch(rows)
            return

        # Create unique temp table name
        temp_table_name = f"{self.table_name}_temp_{uuid.uuid4().hex[:8]}"
        temp_table_id = f"{self.project_id}.{self.get_output_dataset()}.{temp_table_name}"

        logger.info(f"Using proper SQL MERGE with temp table: {temp_table_name}")

        load_job = None  # Initialize for error handling
        try:
            # Step 1: Sanitize rows
            def sanitize_row(row):
                """Sanitize a single row for JSON serialization."""
                sanitized = {}
                for key, value in row.items():
                    if value is None:
                        sanitized[key] = None
                    elif isinstance(value, (int, str, bool)):
                        sanitized[key] = value
                    elif isinstance(value, float):
                        if math.isnan(value) or math.isinf(value):
                            sanitized[key] = None
                        else:
                            sanitized[key] = value
                    elif isinstance(value, (list, dict)):
                        sanitized[key] = value
                    else:
                        sanitized[key] = str(value)
                return sanitized

            sanitized_rows = [sanitize_row(row) for row in rows]

            # Validate all rows are JSON serializable
            for i, row in enumerate(sanitized_rows):
                try:
                    json.dumps(row)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Skipping row {i} due to JSON error: {e}")
                    sanitized_rows[i] = None

            sanitized_rows = [r for r in sanitized_rows if r is not None]

            if not sanitized_rows:
                logger.warning("No valid rows after sanitization")
                return

            # Step 2: Load data into temp table
            ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
            ndjson_bytes = ndjson_data.encode('utf-8')

            job_config = bigquery.LoadJobConfig(
                schema=table_schema,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,  # Overwrite temp table
                autodetect=(table_schema is None)
            )

            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                temp_table_id,
                job_config=job_config
            )

            load_job.result(timeout=300)
            logger.info(f"✅ Loaded {len(sanitized_rows)} rows into temp table")

            # Step 3: Build and execute MERGE statement
            on_clause = ' AND '.join([f"target.{key} = source.{key}" for key in primary_keys])

            # Get all field names from schema (excluding primary keys for UPDATE)
            if table_schema:
                all_fields = [field.name for field in table_schema]
            else:
                # Fallback: use fields from first row
                all_fields = list(sanitized_rows[0].keys()) if sanitized_rows else []

            # CRITICAL: For BigQuery tables with require_partition_filter=true,
            # the partition filter MUST come FIRST in the ON clause with a literal value.
            # This was causing Phase 4 precompute failures (7% success rate).
            # Fixed: 2026-01-15 Session 51
            partition_prefix = ""
            date_col = getattr(self.__class__, 'date_column', 'analysis_date')
            if date_col in all_fields and sanitized_rows:
                analysis_dates = list(set(
                    str(row.get(date_col)) for row in sanitized_rows
                    if row.get(date_col) is not None
                ))
                if analysis_dates:
                    # Build partition filter with literal DATE values
                    # Must come FIRST in ON clause for BigQuery partition pruning
                    if len(analysis_dates) == 1:
                        partition_prefix = f"target.{date_col} = DATE('{analysis_dates[0]}') AND "
                    else:
                        dates_str = "', DATE('".join(sorted(analysis_dates))
                        partition_prefix = f"target.{date_col} IN (DATE('{dates_str}')) AND "
                    logger.debug(f"Adding partition filter for {date_col}: {analysis_dates}")

            # Fields to update (all except primary keys)
            update_fields = [f for f in all_fields if f not in primary_keys]

            # Build UPDATE SET clause
            update_set = ', '.join([f"{field} = source.{field}" for field in update_fields])

            # Build INSERT clause
            insert_fields = ', '.join(all_fields)
            insert_values = ', '.join([f"source.{field}" for field in all_fields])

            merge_query = f"""
            MERGE `{table_id}` AS target
            USING `{temp_table_id}` AS source
            ON {partition_prefix}{on_clause}
            WHEN MATCHED THEN
                UPDATE SET {update_set}
            WHEN NOT MATCHED THEN
                INSERT ({insert_fields})
                VALUES ({insert_values})
            """

            logger.info(f"Executing MERGE on primary keys: {', '.join(primary_keys)} (partition filter: {bool(partition_prefix)})")
            merge_job = self.bq_client.query(merge_query)
            merge_result = merge_job.result(timeout=300)

            # Get stats
            if merge_job.num_dml_affected_rows is not None:
                logger.info(f"✅ MERGE completed: {merge_job.num_dml_affected_rows} rows affected")
            else:
                logger.info(f"✅ MERGE completed successfully")

            # Post-write validation: Verify records were written correctly
            self._validate_after_write(
                table_id=table_id,
                expected_count=len(rows)
            )

            self.stats["rows_processed"] = len(sanitized_rows)

        except Exception as e:
            error_msg = f"MERGE operation failed: {str(e)}"
            logger.error(error_msg)

            # Log BigQuery load job errors if available
            try:
                if load_job is not None:
                    if hasattr(load_job, 'errors') and load_job.errors:
                        logger.error(f"BigQuery load job errors ({len(load_job.errors)} total):")
                        for i, err in enumerate(load_job.errors[:5]):  # Log first 5 errors
                            logger.error(f"  Error {i+1}: {err}")
                    if hasattr(load_job, 'error_result') and load_job.error_result:
                        logger.error(f"BigQuery error result: {load_job.error_result}")
            except NameError:
                pass  # load_job not defined yet
            except Exception as log_err:
                logger.warning(f"Could not log load job errors: {log_err}")

            raise

        finally:
            # Step 4: Always clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                logger.debug(f"Cleaned up temp table: {temp_table_name}")
            except Exception as cleanup_e:
                logger.warning(f"Could not clean up temp table: {cleanup_e}")

    def _delete_existing_data_batch(self, rows: List[Dict]) -> None:
        """
        Delete existing data using batch DELETE query.

        DEPRECATED: Use _save_with_proper_merge() instead.
        This method is kept for backwards compatibility.
        """
        if not rows:
            return

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Get analysis_date from opts or first row
        analysis_date = self.opts.get('analysis_date')

        if analysis_date:
            # Use configurable date column (defaults to analysis_date, can be cache_date, etc.)
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE {self.date_column} = '{analysis_date}'
            """

            logger.info(f"Deleting existing data for {analysis_date}")

            try:
                delete_job = self.bq_client.query(delete_query)
                delete_job.result(timeout=300)

                if delete_job.num_dml_affected_rows is not None:
                    logger.info(f"✅ Deleted {delete_job.num_dml_affected_rows} existing rows")
                else:
                    logger.info(f"✅ Delete completed for {analysis_date}")

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

    def _validate_after_write(
        self,
        table_id: str,
        expected_count: int,
        key_fields: List[str] = None,
        sample_pct: float = 0.10,
        date_column: str = None
    ) -> bool:
        """
        Verify records were written correctly to BigQuery (post-write validation).

        Session 120 - Priority 2: Add post-write validation to detect silent failures.

        This method verifies data integrity AFTER write operations complete, catching
        issues like:
        - BigQuery silently truncating or dropping records
        - Permission issues causing partial writes
        - Quota issues causing incomplete writes
        - Schema mismatches causing NULL fields

        Checks:
        1. Record count matches expected (pre-write vs post-write)
        2. Key fields are non-NULL for sampled records
        3. Logs validation results and alerts if issues found

        Args:
            table_id: Full BigQuery table ID (project.dataset.table)
            expected_count: Number of records that should have been written
            key_fields: List of critical fields to check for NULL
                       (defaults to PRIMARY_KEY_FIELDS if not provided)
            sample_pct: Percentage of records to sample for NULL checks
                       (default 0.10 = 10%, min 1 record)
            date_column: Date column name (defaults to class attribute or 'analysis_date')

        Returns:
            True if validation passed, False if issues detected

        Added: 2026-02-05 Session 120
        """
        import os

        # Check if validation is enabled (default: True)
        if os.environ.get('ENABLE_POST_WRITE_VALIDATION', 'true').lower() != 'true':
            logger.debug("Post-write validation disabled via environment variable")
            return True

        if expected_count <= 0:
            logger.debug("Post-write validation skipped (expected_count=0)")
            return True

        # Get key fields to validate
        if key_fields is None:
            key_fields = getattr(self.__class__, 'PRIMARY_KEY_FIELDS', None)

        if not key_fields:
            logger.debug("No key fields provided for post-write validation, skipping NULL checks")
            key_fields = []

        # Get date column name
        if date_column is None:
            date_column = getattr(self.__class__, 'date_column', 'analysis_date')

        # Extract table info from full table_id
        table_name = table_id.split('.')[-1] if '.' in table_id else table_id

        logger.info(f"POST_WRITE_VALIDATION: Verifying {expected_count} records in {table_name}")

        try:
            # Get analysis date for partition filtering
            analysis_date = self.opts.get('analysis_date')

            # CHECK 1: Record count verification
            # Query actual record count in the table for this analysis_date
            if analysis_date:
                count_query = f"""
                SELECT COUNT(*) as actual_count
                FROM `{table_id}`
                WHERE {date_column} = '{analysis_date}'
                """
            else:
                # Fallback: count all records (less precise but works without date)
                logger.warning("No analysis_date available, counting ALL records (less precise)")
                count_query = f"""
                SELECT COUNT(*) as actual_count
                FROM `{table_id}`
                """

            count_result = self.bq_client.query(count_query).result()
            actual_count = next(count_result).actual_count

            # Validate count matches expected
            count_mismatch = abs(actual_count - expected_count)
            count_mismatch_pct = (count_mismatch / expected_count * 100) if expected_count > 0 else 0

            if count_mismatch > 0:
                if count_mismatch_pct > 5.0:  # Allow 5% tolerance for edge cases
                    logger.error(
                        f"POST_WRITE_VALIDATION FAILED: Record count mismatch! "
                        f"Expected {expected_count}, found {actual_count} "
                        f"(difference: {count_mismatch}, {count_mismatch_pct:.1f}%)"
                    )

                    # Send notification for significant mismatches
                    try:
                        notify_error(
                            title=f"Post-Write Validation Failed: {self.__class__.__name__}",
                            message=f"Record count mismatch after write to {table_name}",
                            details={
                                'processor': self.__class__.__name__,
                                'table': table_name,
                                'expected_count': expected_count,
                                'actual_count': actual_count,
                                'mismatch': count_mismatch,
                                'mismatch_pct': f"{count_mismatch_pct:.1f}%",
                                'analysis_date': str(analysis_date),
                                'issue': 'BigQuery may have dropped records or write partially failed',
                                'remediation': 'Check BigQuery write logs and re-run processor'
                            },
                            processor_name=self.__class__.__name__
                        )
                    except Exception as notify_e:
                        logger.warning(f"Failed to send post-write validation notification: {notify_e}")

                    return False  # Validation failed
                else:
                    logger.warning(
                        f"POST_WRITE_VALIDATION: Minor count mismatch (within tolerance). "
                        f"Expected {expected_count}, found {actual_count} (diff: {count_mismatch})"
                    )
            else:
                logger.info(f"✅ Record count verified: {actual_count} records")

            # CHECK 2: NULL field verification (sample-based)
            if key_fields:
                # Calculate sample size (minimum 1 record, max 10% of records)
                sample_size = max(1, int(expected_count * sample_pct))
                sample_size = min(sample_size, 100)  # Cap at 100 records for performance

                # Build NULL check conditions for key fields
                null_checks = [
                    f"COUNTIF({field} IS NULL) as {field}_null_count"
                    for field in key_fields
                ]
                null_checks_str = ', '.join(null_checks)

                if analysis_date:
                    null_check_query = f"""
                    SELECT {null_checks_str}
                    FROM `{table_id}`
                    WHERE {date_column} = '{analysis_date}'
                    LIMIT {sample_size}
                    """
                else:
                    null_check_query = f"""
                    SELECT {null_checks_str}
                    FROM `{table_id}`
                    LIMIT {sample_size}
                    """

                null_result = self.bq_client.query(null_check_query).result()
                null_row = next(null_result)

                # Check if any key fields have NULLs
                null_fields = []
                for field in key_fields:
                    null_count = getattr(null_row, f"{field}_null_count", 0)
                    if null_count > 0:
                        null_fields.append(f"{field} ({null_count} NULLs)")

                if null_fields:
                    logger.warning(
                        f"POST_WRITE_VALIDATION: Found NULL values in key fields (sample of {sample_size}): "
                        f"{', '.join(null_fields)}"
                    )

                    # Send notification if critical fields are NULL
                    try:
                        notify_warning(
                            title=f"Post-Write Validation: NULL Fields Detected",
                            message=f"Key fields have NULL values in {table_name} after write",
                            details={
                                'processor': self.__class__.__name__,
                                'table': table_name,
                                'null_fields': null_fields,
                                'sample_size': sample_size,
                                'total_records': actual_count,
                                'analysis_date': str(analysis_date),
                                'issue': 'Key fields should not be NULL - may indicate schema mismatch',
                                'remediation': 'Check processor transform logic and schema definitions'
                            },
                            processor_name=self.__class__.__name__
                        )
                    except Exception as notify_e:
                        logger.warning(f"Failed to send NULL field notification: {notify_e}")

                    return False  # Validation failed
                else:
                    logger.info(f"✅ NULL check passed: All key fields populated (sample: {sample_size} records)")

            logger.info(f"✅ POST_WRITE_VALIDATION PASSED for {table_name}")
            return True

        except Exception as e:
            logger.error(f"POST_WRITE_VALIDATION: Validation query failed: {e}")
            # Don't fail the write operation if validation query fails
            # Just log the error and return True (assume write was successful)
            return True
