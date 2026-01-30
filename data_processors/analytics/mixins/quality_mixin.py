"""
Quality tracking and validation for analytics processors.

Provides duplicate detection and quality issue logging with notifications
for high-severity issues.

Version: 1.1
Created: 2026-01-25
Updated: 2026-01-30 - Use BigQueryBatchWriter for quality issues (quota efficiency)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict
from google.cloud import bigquery
from shared.utils.notification_system import notify_error, notify_warning
from shared.utils.bigquery_batch_writer import get_batch_writer

logger = logging.getLogger(__name__)


class QualityMixin:
    """
    Quality tracking and validation for analytics processors.

    Provides duplicate detection and quality issue logging.

    Requires from base class:
    - self.bq_client: BigQuery client
    - self.project_id: GCP project ID
    - self.stats: Statistics dictionary
    - self.quality_issues: List to track issues
    - self.run_id: Current run ID
    - self.opts: Processing options dict
    - self.table_name: Target table name
    - self.get_output_dataset(): Method returning output dataset
    - self.__class__.__name__: Processor name
    - self.__class__.PRIMARY_KEY_FIELDS: Optional primary key fields list
    """

    def _check_for_duplicates_post_save(self, start_date: str = None, end_date: str = None) -> None:
        """
        Check for duplicate records after save operation.

        Uses PRIMARY_KEY_FIELDS class variable if defined.
        Logs warnings but does not fail - allows cleanup on next run.
        """
        # Check if processor has PRIMARY_KEY_FIELDS defined
        if not hasattr(self.__class__, 'PRIMARY_KEY_FIELDS'):
            logger.debug(f"PRIMARY_KEY_FIELDS not defined for {self.__class__.__name__} - skipping duplicate check")
            return

        primary_keys = self.__class__.PRIMARY_KEY_FIELDS
        if not primary_keys or len(primary_keys) == 0:
            logger.debug(f"PRIMARY_KEY_FIELDS is empty for {self.__class__.__name__} - skipping duplicate check")
            return

        table_id = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        # Use provided date range or fall back to opts
        date_start = start_date or self.opts.get('start_date')
        date_end = end_date or self.opts.get('end_date')

        if not date_start or not date_end:
            logger.debug("No date range available - skipping duplicate check")
            return

        # Build duplicate detection query
        group_by_clause = ', '.join(primary_keys)

        duplicate_query = f"""
        SELECT
            COUNT(*) as duplicate_groups,
            SUM(cnt - 1) as extra_duplicates
        FROM (
            SELECT
                {group_by_clause},
                COUNT(*) as cnt
            FROM `{table_id}`
            WHERE game_date BETWEEN '{date_start}' AND '{date_end}'
            GROUP BY {group_by_clause}
            HAVING COUNT(*) > 1
        )
        """

        try:
            result = self.bq_client.query(duplicate_query).result()
            for row in result:
                if row.duplicate_groups and row.duplicate_groups > 0:
                    logger.warning(f"⚠️  DUPLICATES DETECTED: {row.duplicate_groups} duplicate groups ({row.extra_duplicates} extra records)")
                    logger.warning(f"   Date range: {date_start} to {date_end}")
                    logger.warning(f"   Primary keys: {', '.join(primary_keys)}")
                    logger.warning(f"   These will be cleaned up on next run or via maintenance script")

                    # Track in stats
                    self.stats['duplicates_detected'] = row.duplicate_groups
                    self.stats['duplicate_records'] = row.extra_duplicates
                else:
                    logger.debug(f"✅ No duplicates found for {date_start} to {date_end}")
        except Exception as e:
            logger.debug(f"Could not check for duplicates: {e}")
            # Don't fail on duplicate check errors - it's optional validation

    def log_quality_issue(self, issue_type: str, severity: str, identifier: str,
                         details: Dict):
        """
        Log data quality issues for review.
        Enhanced with notifications for high-severity issues.

        Uses BigQueryBatchWriter for efficient writes:
        - Bypasses load job quota (1,500/day limit) via streaming inserts
        - Auto-batches for efficiency (flushes on size or timeout)
        - Thread-safe for concurrent writes
        """
        issue_record = {
            'issue_id': str(uuid.uuid4()),
            'processor_name': self.__class__.__name__,
            'run_id': self.run_id,
            'issue_type': issue_type,
            'severity': severity,
            'identifier': identifier,
            'issue_description': json.dumps(details),
            'resolved': False,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        # Track locally
        self.quality_issues.append(issue_record)

        try:
            table_id = "nba_processing.analytics_data_issues"

            # Use BigQueryBatchWriter for efficient writes
            # - Bypasses load job quota via streaming inserts
            # - Auto-batches and flushes on size (100 records) or timeout (30s)
            # - Thread-safe singleton per table
            writer = get_batch_writer(table_id, project_id=self.project_id)
            writer.add_record(issue_record)

            # Send notification for high-severity issues
            if severity in ['CRITICAL', 'HIGH']:
                try:
                    notify_func = notify_error if severity == 'CRITICAL' else notify_warning
                    notify_func(
                        title=f"Analytics Data Quality Issue: {self.__class__.__name__}",
                        message=f"{severity} severity {issue_type} detected for {identifier}",
                        details={
                            'processor': self.__class__.__name__,
                            'run_id': self.run_id,
                            'issue_type': issue_type,
                            'severity': severity,
                            'identifier': identifier,
                            'issue_details': details,
                            'table': self.table_name
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")

        except Exception as e:
            logger.warning(f"Failed to log quality issue: {e}")
