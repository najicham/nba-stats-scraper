# File: data_processors/precompute/ml_feature_store/batch_writer.py
"""
Batch Writer - Write Features to BigQuery

OPTIMIZED: Uses MERGE pattern instead of DELETE + INSERT.
This follows BigQuery best practices and eliminates streaming buffer issues.

Strategy (per bigquery-best-practices.md):
1. Create temporary table with target schema
2. Load all rows to temp table in one batch
3. MERGE from temp to target (handles upserts)
4. Cleanup temp table

Performance improvement: ~600-900 seconds saved vs DELETE + sequential batch writes.
"""

import logging
import time
import io
import json
import uuid
from datetime import datetime, date, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery
from shared.utils.bigquery_retry import SERIALIZATION_RETRY, QUOTA_RETRY

logger = logging.getLogger(__name__)


class BatchWriter:
    """Write features to BigQuery using MERGE pattern."""

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize batch writer.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self._timing = {}  # Timing instrumentation

    def write_batch(self, rows: List[Dict], dataset_id: str, table_name: str,
                   game_date: date) -> Dict:
        """
        Write feature rows to BigQuery using MERGE pattern.

        OPTIMIZED: Single temp table load + MERGE instead of DELETE + batch INSERTs.

        Args:
            rows: List of feature records
            dataset_id: Target dataset (nba_predictions)
            table_name: Target table (ml_feature_store_v2)
            game_date: Game date (for MERGE filtering)

        Returns:
            Dict with write stats and timing information
        """
        self._timing = {}
        overall_start = time.time()

        if not rows:
            logger.warning("No rows to write")
            return {
                'rows_processed': 0,
                'rows_failed': 0,
                'batches_written': 0,
                'batches_failed': 0,
                'errors': [],
                'timing': self._timing
            }

        table_id = f"{self.project_id}.{dataset_id}.{table_name}"
        temp_table_id = None

        try:
            # Step 1: Get target table schema
            step_start = time.time()
            target_table = self.bq_client.get_table(table_id)
            target_schema = target_table.schema
            required_fields = {f.name for f in target_schema if f.mode == "REQUIRED"}
            self._timing['get_schema'] = time.time() - step_start
            logger.info(f"Got target schema ({self._timing['get_schema']:.2f}s)")

            # Step 2: Create temporary table
            step_start = time.time()
            temp_table_id = f"{table_id}_temp_{uuid.uuid4().hex[:8]}"
            temp_table = bigquery.Table(temp_table_id, schema=target_schema)
            self.bq_client.create_table(temp_table)
            self._timing['create_temp_table'] = time.time() - step_start
            logger.info(f"Created temp table ({self._timing['create_temp_table']:.2f}s)")

            # Step 3: Validate required fields and prepare data
            step_start = time.time()
            validated_rows = self._ensure_required_defaults(rows, required_fields)
            self._timing['validate_rows'] = time.time() - step_start

            # Step 4: Load all rows to temp table in single batch
            step_start = time.time()
            load_success = self._load_to_temp_table(temp_table_id, validated_rows, target_schema)
            self._timing['load_temp_table'] = time.time() - step_start

            if not load_success:
                raise RuntimeError("Failed to load data to temp table")

            logger.info(f"Loaded {len(rows)} rows to temp table ({self._timing['load_temp_table']:.2f}s)")

            # Step 5: MERGE from temp to target
            step_start = time.time()
            merge_success = self._merge_to_target(table_id, temp_table_id, game_date)
            self._timing['merge_operation'] = time.time() - step_start

            if not merge_success:
                raise RuntimeError("MERGE operation failed")

            logger.info(f"MERGE completed ({self._timing['merge_operation']:.2f}s)")

            # Calculate total time
            self._timing['total'] = time.time() - overall_start

            logger.info(
                f"✅ Write complete: {len(rows)} rows in {self._timing['total']:.2f}s "
                f"(schema: {self._timing['get_schema']:.1f}s, "
                f"load: {self._timing['load_temp_table']:.1f}s, "
                f"merge: {self._timing['merge_operation']:.1f}s)"
            )

            return {
                'rows_processed': len(rows),
                'rows_failed': 0,
                'batches_written': 1,
                'batches_failed': 0,
                'errors': [],
                'timing': self._timing
            }

        except Exception as e:
            self._timing['total'] = time.time() - overall_start
            error_msg = str(e).lower()

            # Handle streaming buffer gracefully
            if "streaming buffer" in error_msg:
                logger.warning(
                    f"⚠️ MERGE blocked by streaming buffer - {len(rows)} records skipped. "
                    f"Will succeed on next run."
                )
                return {
                    'rows_processed': 0,
                    'rows_failed': len(rows),
                    'batches_written': 0,
                    'batches_failed': 1,
                    'errors': ['Streaming buffer conflict - graceful skip'],
                    'timing': self._timing
                }

            logger.error(f"Write failed after {self._timing['total']:.2f}s: {e}")
            return {
                'rows_processed': 0,
                'rows_failed': len(rows),
                'batches_written': 0,
                'batches_failed': 1,
                'errors': [str(e)],
                'timing': self._timing
            }

        finally:
            # Always cleanup temp table
            if temp_table_id:
                try:
                    self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                    logger.debug(f"Cleaned up temp table {temp_table_id}")
                except Exception as cleanup_e:
                    logger.warning(f"Failed to cleanup temp table: {cleanup_e}")

    def _ensure_required_defaults(self, rows: List[Dict], required_fields: set) -> List[Dict]:
        """
        Ensure all REQUIRED fields have non-null values.

        Args:
            rows: List of row dicts
            required_fields: Set of field names that are REQUIRED

        Returns:
            List of validated row dicts
        """
        validated = []
        current_utc = datetime.now(timezone.utc)

        for row in rows:
            out = dict(row)

            # Handle common timestamp fields
            if "created_at" in required_fields and out.get("created_at") is None:
                out["created_at"] = current_utc.isoformat()
            if "processed_at" in required_fields and out.get("processed_at") is None:
                out["processed_at"] = current_utc.isoformat()

            # Handle features field - must never be null for BigQuery
            if "features" in required_fields and out.get("features") is None:
                out["features"] = []

            validated.append(out)

        return validated

    def _sanitize_row(self, row: Dict) -> Dict:
        """
        Sanitize row data to ensure valid JSON serialization.

        Handles:
        - Control characters in strings
        - datetime.date objects -> ISO format strings
        - Decimal objects -> floats
        - NaN/Inf float values -> None (BigQuery rejects these)
        - Other non-serializable types

        Args:
            row: Row dict to sanitize

        Returns:
            Sanitized row dict
        """
        import re
        import math
        from decimal import Decimal
        from datetime import date as date_type, datetime as datetime_type

        # Try to import numpy for handling numpy types
        try:
            import numpy as np
            HAS_NUMPY = True
        except ImportError:
            HAS_NUMPY = False
            np = None

        # Pattern to match control characters except newline, tab, carriage return
        control_chars = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

        def sanitize_value(value):
            """Recursively sanitize a single value."""
            if value is None:
                return None
            # Handle numpy arrays first (convert to list)
            elif HAS_NUMPY and isinstance(value, np.ndarray):
                return [sanitize_value(item) for item in value.tolist()]
            # Handle numpy floating point types
            elif HAS_NUMPY and isinstance(value, (np.floating, np.integer)):
                f = float(value)
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            elif isinstance(value, str):
                return control_chars.sub('', value)
            elif isinstance(value, float):
                # Handle NaN and Inf which are not valid JSON
                if math.isnan(value) or math.isinf(value):
                    return None
                return value
            elif isinstance(value, date_type) and not isinstance(value, datetime_type):
                return value.isoformat()
            elif isinstance(value, datetime_type):
                return value.isoformat()
            elif isinstance(value, Decimal):
                f = float(value)
                if math.isnan(f) or math.isinf(f):
                    return None
                return f
            elif isinstance(value, dict):
                return {k: sanitize_value(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                return [sanitize_value(item) for item in value]
            else:
                return value

        sanitized = {key: sanitize_value(value) for key, value in row.items()}

        # Ensure 'features' field is never null (BigQuery schema requires it)
        if 'features' in sanitized and sanitized['features'] is None:
            sanitized['features'] = []

        # For REPEATED FLOAT fields like 'features', replace None with 0.0
        # (BigQuery doesn't allow NULL inside REPEATED arrays)
        if 'features' in sanitized and isinstance(sanitized['features'], list):
            sanitized['features'] = [0.0 if v is None else v for v in sanitized['features']]

        return sanitized

    def _load_to_temp_table(self, temp_table_id: str, rows: List[Dict],
                           schema: List) -> bool:
        """
        Load all rows to temp table using batch load job.

        Args:
            temp_table_id: Full temp table ID
            rows: List of row dicts
            schema: Target table schema

        Returns:
            bool: True if successful
        """
        # Sanitize rows to prevent JSON parsing errors
        sanitized_rows = [self._sanitize_row(row) for row in rows]

        # Convert to NDJSON
        ndjson_data = "\n".join(json.dumps(row) for row in sanitized_rows)
        ndjson_bytes = ndjson_data.encode('utf-8')

        # Configure load job with schema enforcement
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            autodetect=False  # Critical: never autodetect
        )

        # Execute load with automatic retry on serialization conflicts
        @SERIALIZATION_RETRY
        def execute_load():
            """Load data to temp table with automatic retry on serialization conflicts."""
            load_job = self.bq_client.load_table_from_file(
                io.BytesIO(ndjson_bytes),
                temp_table_id,
                job_config=job_config
            )
            # Wait for completion (with timeout to prevent infinite hangs)
            return load_job.result(timeout=300)  # 5 minutes max

        execute_load()
        return True

    def _merge_to_target(self, target_table_id: str, temp_table_id: str,
                        game_date: date) -> bool:
        """
        MERGE data from temp table to target.

        Uses player_lookup + game_date as merge key.

        Args:
            target_table_id: Full target table ID
            temp_table_id: Full temp table ID
            game_date: Game date for the merge

        Returns:
            bool: True if successful
        """
        # Build MERGE query
        # Match on player_lookup + game_date
        # Use ROW_NUMBER to deduplicate source rows (same player may appear twice if reprocessed)
        merge_query = f"""
        MERGE `{target_table_id}` AS target
        USING (
            SELECT * EXCEPT(row_num) FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, game_date
                    ORDER BY created_at DESC
                ) as row_num
                FROM `{temp_table_id}`
            ) WHERE row_num = 1
        ) AS source
        ON target.player_lookup = source.player_lookup
           AND target.game_date = source.game_date
        WHEN MATCHED THEN
            UPDATE SET
                universal_player_id = source.universal_player_id,
                game_id = source.game_id,
                features = source.features,
                feature_names = source.feature_names,
                feature_count = source.feature_count,
                feature_version = source.feature_version,
                opponent_team_abbr = source.opponent_team_abbr,
                is_home = source.is_home,
                days_rest = source.days_rest,
                quality_tier = source.quality_tier,
                feature_quality_score = source.feature_quality_score,
                feature_generation_time_ms = source.feature_generation_time_ms,
                data_source = source.data_source,
                early_season_flag = source.early_season_flag,
                insufficient_data_reason = source.insufficient_data_reason,
                source_daily_cache_hash = source.source_daily_cache_hash,
                source_composite_hash = source.source_composite_hash,
                source_shot_zones_hash = source.source_shot_zones_hash,
                source_team_defense_hash = source.source_team_defense_hash,
                expected_games_count = source.expected_games_count,
                actual_games_count = source.actual_games_count,
                completeness_percentage = source.completeness_percentage,
                missing_games_count = source.missing_games_count,
                is_production_ready = source.is_production_ready,
                data_quality_issues = source.data_quality_issues,
                last_reprocess_attempt_at = source.last_reprocess_attempt_at,
                reprocess_attempt_count = source.reprocess_attempt_count,
                circuit_breaker_active = source.circuit_breaker_active,
                circuit_breaker_until = source.circuit_breaker_until,
                manual_override_required = source.manual_override_required,
                season_boundary_detected = source.season_boundary_detected,
                backfill_bootstrap_mode = source.backfill_bootstrap_mode,
                processing_decision_reason = source.processing_decision_reason,
                historical_completeness = source.historical_completeness,
                data_hash = source.data_hash,
                updated_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT ROW
        """

        # Execute MERGE with automatic retry on serialization and quota errors
        @QUOTA_RETRY          # Outer: Handle quota exceeded (sustained load)
        @SERIALIZATION_RETRY  # Inner: Handle concurrent updates (transient)
        def execute_merge():
            """Execute MERGE with automatic retry on serialization and quota errors."""
            merge_job = self.bq_client.query(merge_query)
            result = merge_job.result(timeout=300)  # 5 minutes max

            # Log merge stats
            if merge_job.num_dml_affected_rows is not None:
                logger.info(f"MERGE affected {merge_job.num_dml_affected_rows} rows")

            return True

        try:
            return execute_merge()
        except Exception as e:
            error_msg = str(e).lower()

            # Streaming buffer errors are non-retriable - re-raise
            if "streaming buffer" in error_msg:
                logger.warning("MERGE blocked by streaming buffer - will succeed on next run")
                raise

            # All other errors already retried by decorators
            logger.error(f"MERGE failed after retries: {e}")
            raise

    # =========================================================================
    # LEGACY METHOD (kept for backward compatibility if needed)
    # =========================================================================

    def write_batch_legacy(self, rows: List[Dict], dataset_id: str, table_name: str,
                          game_date: date) -> Dict:
        """
        Legacy write method using DELETE + batch INSERT.

        DEPRECATED: Use write_batch() which uses MERGE pattern.
        Kept for rollback if needed.
        """
        logger.warning("Using legacy DELETE+INSERT pattern - consider using write_batch() with MERGE")

        if not rows:
            return {'rows_processed': 0, 'rows_failed': 0, 'batches_written': 0,
                    'batches_failed': 0, 'errors': []}

        table_id = f"{self.project_id}.{dataset_id}.{table_name}"

        # Step 1: Delete existing records for game_date
        delete_success = self._delete_existing_data_legacy(table_id, game_date)
        if not delete_success:
            logger.warning("DELETE failed (likely streaming buffer), continuing with INSERT")

        # Step 2: Split into batches and write
        BATCH_SIZE = 100
        batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]

        results = {
            'rows_processed': 0,
            'rows_failed': 0,
            'batches_written': 0,
            'batches_failed': 0,
            'errors': []
        }

        for batch_idx, batch_rows in enumerate(batches):
            try:
                table = self.bq_client.get_table(table_id)
                ndjson_data = "\n".join(json.dumps(row) for row in batch_rows)

                job_config = bigquery.LoadJobConfig(
                    schema=table.schema,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    autodetect=False
                )

                load_job = self.bq_client.load_table_from_file(
                    io.BytesIO(ndjson_data.encode('utf-8')),
                    table_id,
                    job_config=job_config
                )
                load_job.result(timeout=300)  # 5 minutes max

                results['rows_processed'] += len(batch_rows)
                results['batches_written'] += 1

            except Exception as e:
                results['rows_failed'] += len(batch_rows)
                results['batches_failed'] += 1
                results['errors'].append(f"Batch {batch_idx + 1}: {e}")

        return results

    def _delete_existing_data_legacy(self, table_id: str, game_date: date) -> bool:
        """Legacy DELETE operation."""
        try:
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date = '{game_date}'
            """
            delete_job = self.bq_client.query(delete_query)
            delete_job.result(timeout=300)  # 5 minutes max
            return True
        except Exception as e:
            if "streaming buffer" in str(e).lower():
                return False
            raise
