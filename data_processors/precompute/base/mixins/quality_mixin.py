"""
Quality tracking and validation for precompute processors.

Provides date-level failure tracking and quality issue logging specific to
Phase 4 precompute processors.

Version: 1.0
Created: 2026-01-25
"""

import logging
from datetime import datetime, timezone
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError
from typing import Optional

from shared.utils.bigquery_batch_writer import get_batch_writer

logger = logging.getLogger(__name__)


class QualityMixin:
    """
    Quality tracking and validation for precompute processors.

    Provides date-level failure tracking to the precompute_failures table,
    enabling visibility into why no records exist for a given date.

    Requires from base class:
    - self.bq_client: BigQuery client
    - self.project_id: GCP project ID
    - self.run_id: Current run ID
    - self.opts: Processing options dict with 'analysis_date'
    - self.__class__.__name__: Processor name
    """

    def _record_date_level_failure(self, category: str, reason: str, can_retry: bool = True) -> None:
        """
        Record a date-level failure to the precompute_failures table.

        Use this when an entire date fails (e.g., missing dependencies),
        rather than individual player failures.

        This enables visibility into WHY no records exist for a date:
        - MISSING_DEPENDENCY: Upstream data not available (standardized singular form)
        - MINIMUM_THRESHOLD_NOT_MET: Too few upstream records (expected during early season)
        - PROCESSING_ERROR: Actual error during processing (needs investigation)

        Args:
            category: Failure category (MISSING_DEPENDENCY, MINIMUM_THRESHOLD_NOT_MET, etc.)
            reason: Detailed reason string
            can_retry: Whether reprocessing might succeed (True if deps will be populated)
        """
        try:
            table_id = f"{self.project_id}.nba_processing.precompute_failures"
            analysis_date = self.opts.get('analysis_date')

            # Convert date to string for BQ DATE type
            if hasattr(analysis_date, 'isoformat'):
                date_str = analysis_date.isoformat()
            else:
                date_str = str(analysis_date)

            # Standardize category naming (singular form)
            if category == 'MISSING_DEPENDENCIES':
                category = 'MISSING_DEPENDENCY'

            failure_record = {
                'processor_name': self.__class__.__name__,
                'run_id': self.run_id,
                'analysis_date': date_str,
                'entity_id': 'DATE_LEVEL',  # Special marker for date-level failures
                'failure_category': category,
                'failure_reason': str(reason)[:1000],
                'can_retry': can_retry,
                'created_at': datetime.now(timezone.utc).isoformat()
            }

            # Use BigQueryBatchWriter for quota-efficient writes
            # This uses streaming inserts to bypass load job quota limits
            # See docs/05-development/guides/bigquery-best-practices.md
            writer = get_batch_writer(table_id)
            writer.add_record(failure_record)

            logger.info(f"Recorded date-level failure: {category} - {reason[:50]}...")

        except GoogleAPIError as e:
            logger.warning(f"Failed to record date-level failure: {e}")

    def _format_missing_deps(self) -> Optional[str]:
        """
        Format missing dependencies for database storage.

        Returns:
            Comma-separated string of missing dependencies, or None if empty.
        """
        if not hasattr(self, 'missing_dependencies_list') or not self.missing_dependencies_list:
            return None
        return ", ".join(self.missing_dependencies_list)

    def _check_for_duplicates_post_save(self) -> None:
        """
        Check for duplicate records after save operation.

        Uses PRIMARY_KEY_FIELDS class variable if defined.
        Logs warnings but does not fail - allows cleanup on next run.

        Note: Precompute processors use analysis_date instead of start_date/end_date.
        """
        # Check if processor has PRIMARY_KEY_FIELDS defined
        if not hasattr(self.__class__, 'PRIMARY_KEY_FIELDS'):
            logger.debug(f"PRIMARY_KEY_FIELDS not defined for {self.__class__.__name__} - skipping duplicate check")
            return

        primary_keys = self.__class__.PRIMARY_KEY_FIELDS
        if not primary_keys or len(primary_keys) == 0:
            logger.debug(f"PRIMARY_KEY_FIELDS is empty for {self.__class__.__name__} - skipping duplicate check")
            return

        # Get table info - precompute processors use different attributes
        if not hasattr(self, 'output_table') or not self.output_table:
            logger.debug(f"No output_table defined for {self.__class__.__name__} - skipping duplicate check")
            return

        table_id = f"{self.project_id}.{self.output_table}"

        # Get analysis_date from opts (precompute pattern)
        analysis_date = self.opts.get('analysis_date')
        if not analysis_date:
            logger.debug("No analysis_date available - skipping duplicate check")
            return

        # Convert to string if needed
        if hasattr(analysis_date, 'isoformat'):
            date_str = analysis_date.isoformat()
        else:
            date_str = str(analysis_date)

        # Determine the date column name (varies by processor)
        date_column = 'analysis_date' if 'analysis_date' in primary_keys else 'cache_date'

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
            WHERE {date_column} = '{date_str}'
            GROUP BY {group_by_clause}
            HAVING COUNT(*) > 1
        )
        """

        try:
            result = self.bq_client.query(duplicate_query).result()
            for row in result:
                if row.duplicate_groups and row.duplicate_groups > 0:
                    logger.warning(f"⚠️  DUPLICATES DETECTED: {row.duplicate_groups} duplicate groups ({row.extra_duplicates} extra records)")
                    logger.warning(f"   Date: {date_str}")
                    logger.warning(f"   Primary keys: {', '.join(primary_keys)}")
                    logger.warning(f"   These will be cleaned up on next run or via maintenance script")

                    # Track in stats if available
                    if hasattr(self, 'stats'):
                        self.stats['duplicates_detected'] = row.duplicate_groups
                        self.stats['duplicate_records'] = row.extra_duplicates
                else:
                    logger.debug(f"✅ No duplicates found for {date_str}")
        except Exception as e:
            logger.debug(f"Could not check for duplicates: {e}")
            # Don't fail on duplicate check errors - it's optional validation
