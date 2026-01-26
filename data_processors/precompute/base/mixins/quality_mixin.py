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

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json([failure_record], table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"Error recording date-level failure: {load_job.errors}")
            else:
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
