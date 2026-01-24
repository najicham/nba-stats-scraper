"""
Output writing components for the composable processor framework.

Writers handle saving data to various destinations:
- BigQuery tables (INSERT, MERGE)
- GCS files
- Other destinations

Version: 1.0
Created: 2026-01-23
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from .base import OutputWriter, ComponentContext

logger = logging.getLogger(__name__)


class BigQueryWriter(OutputWriter):
    """
    Write records to BigQuery using batch load.

    Uses NDJSON file upload for efficient batch loading.
    Supports INSERT (append) mode.

    Example:
        writer = BigQueryWriter(
            table_id='project.dataset.table',
            write_disposition='WRITE_APPEND',
        )
    """

    def __init__(
        self,
        table_id: Optional[str] = None,
        dataset_id: str = 'nba_analytics',
        table_name: str = '',
        write_disposition: str = 'WRITE_APPEND',
        timeout_seconds: int = 120,
        name: Optional[str] = None,
    ):
        """
        Initialize BigQuery writer.

        Args:
            table_id: Full table ID (project.dataset.table)
            dataset_id: Dataset ID (used if table_id not provided)
            table_name: Table name (used if table_id not provided)
            write_disposition: WRITE_APPEND, WRITE_TRUNCATE, or WRITE_EMPTY
            timeout_seconds: Write operation timeout
            name: Optional component name
        """
        super().__init__(name=name)
        self.table_id = table_id
        self.dataset_id = dataset_id
        self.table_name = table_name
        self.write_disposition = write_disposition
        self.timeout_seconds = timeout_seconds

    def write(
        self,
        records: List[Dict],
        context: ComponentContext
    ) -> Dict[str, int]:
        """
        Write records to BigQuery.

        Args:
            records: List of record dictionaries
            context: Processing context

        Returns:
            Statistics dict with records_written count
        """
        if not records:
            logger.info("No records to write")
            return {'records_written': 0}

        # Build table ID
        table_id = self._get_table_id(context)
        logger.info(f"Writing {len(records)} records to {table_id}")

        # Sanitize records for JSON serialization
        sanitized_records = [
            self._sanitize_record(record)
            for record in records
        ]

        # Write using NDJSON file upload
        try:
            # Write to temp file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.json',
                delete=False
            ) as f:
                for record in sanitized_records:
                    f.write(json.dumps(record) + '\n')
                temp_path = f.name

            # Load from file
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=getattr(
                    bigquery.WriteDisposition,
                    self.write_disposition
                ),
                ignore_unknown_values=True,
            )

            with open(temp_path, 'rb') as f:
                load_job = context.bq_client.load_table_from_file(
                    f,
                    table_id,
                    job_config=job_config,
                )

            # Wait for completion
            load_job.result(timeout=self.timeout_seconds)

            if load_job.errors:
                logger.warning(f"BigQuery load errors: {load_job.errors}")

            logger.info(f"Successfully wrote {len(records)} records to {table_id}")

            return {
                'records_written': len(records),
                'table': table_id,
            }

        except Exception as e:
            logger.error(f"Failed to write to BigQuery: {e}", exc_info=True)
            raise

        finally:
            # Clean up temp file
            if 'temp_path' in locals():
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.debug(f"Failed to cleanup temp file {temp_path}: {e}")

    def _get_table_id(self, context: ComponentContext) -> str:
        """Get full table ID."""
        if self.table_id:
            return self.table_id

        return f"{context.project_id}.{self.dataset_id}.{self.table_name}"

    def _sanitize_record(self, record: Dict) -> Dict:
        """Sanitize record for JSON serialization."""
        import math
        import re

        sanitized = {}
        for key, value in record.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    sanitized[key] = None
                else:
                    sanitized[key] = value
            elif isinstance(value, str):
                # Remove control characters
                cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
                sanitized[key] = cleaned
            elif isinstance(value, datetime):
                sanitized[key] = value.isoformat()
            elif isinstance(value, (int, bool)):
                sanitized[key] = value
            elif isinstance(value, (list, dict)):
                try:
                    json.dumps(value)
                    sanitized[key] = value
                except (TypeError, ValueError):
                    sanitized[key] = str(value)
            else:
                sanitized[key] = str(value)

        return sanitized

    def validate_config(self) -> List[str]:
        """Validate writer configuration."""
        errors = []
        if not self.table_id and not self.table_name:
            errors.append(f"{self.name}: Either table_id or table_name is required")
        return errors


class BigQueryMergeWriter(OutputWriter):
    """
    Write records to BigQuery using MERGE (upsert) operation.

    Uses primary key fields to determine whether to INSERT or UPDATE.
    Ideal for analytics tables that need to be reprocessed.

    Example:
        writer = BigQueryMergeWriter(
            table_id='project.dataset.table',
            primary_key_fields=['game_id', 'player_id'],
        )
    """

    def __init__(
        self,
        table_id: Optional[str] = None,
        dataset_id: str = 'nba_analytics',
        table_name: str = '',
        primary_key_fields: List[str] = None,
        timeout_seconds: int = 300,
        batch_size: int = 10000,
        name: Optional[str] = None,
    ):
        """
        Initialize BigQuery merge writer.

        Args:
            table_id: Full table ID
            dataset_id: Dataset ID (used if table_id not provided)
            table_name: Table name (used if table_id not provided)
            primary_key_fields: Fields that form the primary key
            timeout_seconds: Merge operation timeout
            batch_size: Records per MERGE statement
            name: Optional component name
        """
        super().__init__(name=name)
        self.table_id = table_id
        self.dataset_id = dataset_id
        self.table_name = table_name
        self.primary_key_fields = primary_key_fields or ['game_id']
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size

    def write(
        self,
        records: List[Dict],
        context: ComponentContext
    ) -> Dict[str, int]:
        """
        Write records using MERGE operation.

        Args:
            records: List of record dictionaries
            context: Processing context

        Returns:
            Statistics dict
        """
        if not records:
            logger.info("No records to write")
            return {'records_written': 0, 'records_updated': 0}

        table_id = self._get_table_id(context)
        logger.info(
            f"MERGE writing {len(records)} records to {table_id} "
            f"(key: {self.primary_key_fields})"
        )

        # Process in batches
        total_written = 0
        total_updated = 0

        for i in range(0, len(records), self.batch_size):
            batch = records[i:i + self.batch_size]
            stats = self._merge_batch(batch, table_id, context)
            total_written += stats.get('written', 0)
            total_updated += stats.get('updated', 0)

        return {
            'records_written': total_written,
            'records_updated': total_updated,
            'table': table_id,
        }

    def _merge_batch(
        self,
        records: List[Dict],
        table_id: str,
        context: ComponentContext
    ) -> Dict[str, int]:
        """
        Merge a batch of records.

        Uses a staging table approach:
        1. Load records to temp table
        2. MERGE from temp to target
        3. Delete temp table
        """
        # Create staging table name
        staging_table = f"{table_id}_staging_{context.run_id}"

        try:
            # Load to staging table
            self._load_to_staging(records, staging_table, context)

            # Perform MERGE
            merge_query = self._build_merge_query(
                staging_table,
                table_id,
                list(records[0].keys())
            )

            job = context.bq_client.query(merge_query)
            result = job.result(timeout=self.timeout_seconds)

            # Get stats from DML result
            stats = {
                'written': job.num_dml_affected_rows or len(records),
                'updated': 0,  # BigQuery doesn't distinguish inserts vs updates
            }

            logger.info(f"Merged {stats['written']} records")
            return stats

        finally:
            # Clean up staging table
            self._delete_staging_table(staging_table, context)

    def _load_to_staging(
        self,
        records: List[Dict],
        staging_table: str,
        context: ComponentContext
    ) -> None:
        """Load records to staging table."""
        # Sanitize records
        sanitized = [
            self._sanitize_record(r)
            for r in records
        ]

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.json',
            delete=False
        ) as f:
            for record in sanitized:
                f.write(json.dumps(record) + '\n')
            temp_path = f.name

        try:
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=True,
            )

            with open(temp_path, 'rb') as f:
                load_job = context.bq_client.load_table_from_file(
                    f,
                    staging_table,
                    job_config=job_config,
                )

            load_job.result(timeout=120)

        finally:
            os.unlink(temp_path)

    def _build_merge_query(
        self,
        staging_table: str,
        target_table: str,
        all_fields: List[str],
    ) -> str:
        """Build MERGE SQL statement."""
        # Build join condition
        join_conditions = [
            f"T.{field} = S.{field}"
            for field in self.primary_key_fields
        ]
        join_clause = " AND ".join(join_conditions)

        # Build update assignments (exclude primary keys)
        update_fields = [
            f for f in all_fields
            if f not in self.primary_key_fields
        ]
        update_clause = ", ".join([
            f"T.{field} = S.{field}"
            for field in update_fields
        ])

        # Build insert lists
        insert_fields = ", ".join(all_fields)
        insert_values = ", ".join([f"S.{field}" for field in all_fields])

        query = f"""
        MERGE `{target_table}` T
        USING `{staging_table}` S
        ON {join_clause}
        WHEN MATCHED THEN
            UPDATE SET {update_clause}
        WHEN NOT MATCHED THEN
            INSERT ({insert_fields})
            VALUES ({insert_values})
        """

        return query

    def _delete_staging_table(
        self,
        staging_table: str,
        context: ComponentContext
    ) -> None:
        """Delete staging table."""
        try:
            context.bq_client.delete_table(staging_table, not_found_ok=True)
        except Exception as e:
            logger.warning(f"Failed to delete staging table: {e}")

    def _sanitize_record(self, record: Dict) -> Dict:
        """Sanitize record for JSON serialization."""
        import math
        import re

        sanitized = {}
        for key, value in record.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    sanitized[key] = None
                else:
                    sanitized[key] = value
            elif isinstance(value, str):
                cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
                sanitized[key] = cleaned
            elif isinstance(value, datetime):
                sanitized[key] = value.isoformat()
            elif isinstance(value, (int, bool)):
                sanitized[key] = value
            elif isinstance(value, (list, dict)):
                try:
                    json.dumps(value)
                    sanitized[key] = value
                except:
                    sanitized[key] = str(value)
            else:
                sanitized[key] = str(value)

        return sanitized

    def _get_table_id(self, context: ComponentContext) -> str:
        """Get full table ID."""
        if self.table_id:
            return self.table_id
        return f"{context.project_id}.{self.dataset_id}.{self.table_name}"

    def validate_config(self) -> List[str]:
        """Validate writer configuration."""
        errors = []
        if not self.table_id and not self.table_name:
            errors.append(f"{self.name}: Either table_id or table_name is required")
        if not self.primary_key_fields:
            errors.append(f"{self.name}: primary_key_fields is required for MERGE")
        return errors
