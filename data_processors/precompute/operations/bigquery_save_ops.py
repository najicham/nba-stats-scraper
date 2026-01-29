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

logger = logging.getLogger(__name__)


class BigQuerySaveOpsMixin:
    """
    Mixin providing BigQuery save operations for precompute processors.

    This mixin requires the parent class to provide specific attributes and methods.
    See module docstring for complete dependency list.
    """

    @retry_on_quota_exceeded
    @retry_on_serialization
    def save_precompute(self) -> None:
        """
        Save to precompute BigQuery table using batch INSERT.
        Uses NDJSON load job with schema enforcement.
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
            return

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
            return

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
            return  # MERGE handles everything, we're done

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

                # Check for duplicates after successful save (if method exists)
                # Fixed 2026-01-29: Some processors don't have QualityMixin
                if hasattr(self, '_check_for_duplicates_post_save'):
                    self._check_for_duplicates_post_save()

            except Exception as load_e:
                if "streaming buffer" in str(load_e).lower():
                    logger.warning(f"⚠️ Load blocked by streaming buffer - {len(rows)} rows skipped")
                    logger.info("Records will be processed on next run")
                    self.stats["rows_skipped"] = len(rows)
                    self.stats["rows_processed"] = 0
                    # R-004: Mark write as failed to prevent incorrect success completion message
                    self.write_success = False
                    return
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
