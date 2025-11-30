"""
RunHistoryMixin - Unified processor run history logging

Provides run history logging for all processor phases:
- Phase 2: Raw processors (ProcessorBase)
- Phase 3: Analytics processors (AnalyticsProcessorBase)
- Phase 4: Precompute processors (PrecomputeProcessorBase)
- Reference: Registry processors (already has its own implementation)

Usage:
    class MyProcessor(RunHistoryMixin, ProcessorBase):
        PHASE = 'phase_2_raw'
        OUTPUT_TABLE = 'my_table'
        OUTPUT_DATASET = 'nba_raw'

        def run(self, opts):
            self.start_run_tracking(data_date=opts.get('game_date'))
            try:
                # ... processing logic ...
                self.record_run_complete(status='success')
            except Exception as e:
                self.record_run_complete(status='failed', error=e)
                raise

Features:
- Auto-captures Cloud Run metadata (service, revision)
- Tracks Pub/Sub trigger information
- Records dependency check results
- Logs alerts sent during processing
- Handles schema differences gracefully

Version: 1.0
Created: 2025-11-27
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional, Any, Union

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class RunHistoryMixin:
    """
    Mixin for logging processor runs to processor_run_history table.

    Attributes to set in child class:
        PHASE: str - Processing phase (phase_2_raw, phase_3_analytics, phase_4_precompute)
        OUTPUT_TABLE: str - Target table name
        OUTPUT_DATASET: str - Target dataset name
    """

    # Override in child classes
    PHASE: str = 'unknown'
    OUTPUT_TABLE: str = ''
    OUTPUT_DATASET: str = ''

    # Run history table
    RUN_HISTORY_TABLE: str = 'nba_reference.processor_run_history'

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def _init_run_history(self):
        """Initialize run history tracking state. Call in __init__ or start_run_tracking."""
        # Run tracking
        self._run_history_id: Optional[str] = None
        self._run_start_time: Optional[datetime] = None
        self._run_data_date: Optional[date] = None

        # Trigger info
        self._trigger_source: str = 'manual'
        self._trigger_message_id: Optional[str] = None
        self._trigger_message_data: Optional[Dict] = None
        self._parent_processor: Optional[str] = None

        # Dependency tracking
        self._upstream_dependencies: List[Dict] = []
        self._dependency_check_passed: bool = True
        self._missing_dependencies: List[str] = []
        self._stale_dependencies: List[str] = []

        # Alert tracking
        self._alert_sent: bool = False
        self._alert_type: Optional[str] = None

        # Skip tracking
        self._skipped: bool = False
        self._skip_reason: Optional[str] = None

        # Retry tracking
        self._retry_attempt: int = 1

    # =========================================================================
    # RUN LIFECYCLE
    # =========================================================================

    def start_run_tracking(
        self,
        data_date: Optional[Union[date, str]] = None,
        trigger_source: str = 'manual',
        trigger_message_id: Optional[str] = None,
        trigger_message_data: Optional[Dict] = None,
        parent_processor: Optional[str] = None,
        retry_attempt: int = 1
    ) -> str:
        """
        Start tracking a processor run. Call at the beginning of run().

        Args:
            data_date: The date being processed
            trigger_source: What triggered this run (pubsub, scheduler, manual, api)
            trigger_message_id: Pub/Sub message ID for correlation
            trigger_message_data: Raw trigger message data
            parent_processor: Upstream processor that triggered this
            retry_attempt: Which retry attempt (1, 2, 3...)

        Returns:
            run_history_id: Unique ID for this run
        """
        self._init_run_history()

        # Generate unique run ID
        self._run_history_id = f"{self.__class__.__name__}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self._run_start_time = datetime.now(timezone.utc)

        # Parse data_date
        if isinstance(data_date, str):
            try:
                self._run_data_date = datetime.strptime(data_date, '%Y-%m-%d').date()
            except ValueError:
                self._run_data_date = date.today()
        elif isinstance(data_date, date):
            self._run_data_date = data_date
        else:
            self._run_data_date = date.today()

        # Store trigger info
        self._trigger_source = trigger_source
        self._trigger_message_id = trigger_message_id
        self._trigger_message_data = trigger_message_data
        self._parent_processor = parent_processor
        self._retry_attempt = retry_attempt

        logger.info(f"Started run tracking: {self._run_history_id} (phase={self.PHASE}, trigger={trigger_source})")

        # CRITICAL: Write 'running' status immediately to prevent duplicate processing
        # If Pub/Sub redelivers message, deduplication check will see this 'running' status
        self._write_running_status()

        return self._run_history_id

    def set_trigger_from_pubsub(self, envelope: Dict) -> None:
        """
        Extract and set trigger info from Pub/Sub envelope.

        Args:
            envelope: The Pub/Sub message envelope from Flask request
        """
        try:
            message = envelope.get('message', {})
            self._trigger_source = 'pubsub'
            self._trigger_message_id = message.get('messageId') or message.get('message_id')

            # Decode message data
            if 'data' in message:
                import base64
                data = base64.b64decode(message['data']).decode('utf-8')
                self._trigger_message_data = json.loads(data)

                # Extract parent processor if available
                self._parent_processor = self._trigger_message_data.get('processor_name')
        except Exception as e:
            logger.warning(f"Failed to parse Pub/Sub envelope: {e}")

    def set_dependency_results(
        self,
        dependencies: List[Dict],
        all_passed: bool,
        missing: List[str] = None,
        stale: List[str] = None
    ) -> None:
        """
        Record dependency check results.

        Args:
            dependencies: List of dependency check results [{table, status, age_hours, row_count}]
            all_passed: Whether all critical dependencies passed
            missing: List of missing dependency table names
            stale: List of stale dependency table names
        """
        self._upstream_dependencies = dependencies or []
        self._dependency_check_passed = all_passed
        self._missing_dependencies = missing or []
        self._stale_dependencies = stale or []

    def set_alert_sent(self, alert_type: str) -> None:
        """
        Record that an alert was sent.

        Args:
            alert_type: Type of alert (error, warning, info)
        """
        self._alert_sent = True
        self._alert_type = alert_type

    def set_skipped(self, reason: str) -> None:
        """
        Record that processing was skipped.

        Args:
            reason: Why processing was skipped (smart_skip, early_exit, already_processed, no_data)
        """
        self._skipped = True
        self._skip_reason = reason

    def record_run_complete(
        self,
        status: str,
        records_processed: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        records_skipped: int = 0,
        error: Optional[Exception] = None,
        summary: Optional[Dict] = None,
        warnings: Optional[List[str]] = None
    ) -> None:
        """
        Record completed processor run to BigQuery.

        Note: This creates a second row with final status (success/failed/etc).
        The first row (status='running') was created by start_run_tracking().
        Deduplication queries use ORDER BY started_at DESC LIMIT 1 to get the latest.

        Args:
            status: Final status (success, failed, partial, skipped)
            records_processed: Total records processed
            records_created: New records created
            records_updated: Existing records updated
            records_skipped: Records skipped
            error: Exception if failed
            summary: Additional summary data
            warnings: List of warning messages
        """
        if not self._run_start_time:
            logger.warning("No run start time - call start_run_tracking() first")
            return

        processed_at = datetime.now(timezone.utc)
        duration_seconds = (processed_at - self._run_start_time).total_seconds()

        # Build errors JSON
        errors_json = None
        if error:
            errors_json = json.dumps([{
                'error_type': type(error).__name__,
                'error_message': str(error),
                'timestamp': processed_at.isoformat()
            }])

        # Build warnings JSON
        warnings_json = None
        if warnings:
            warnings_json = json.dumps(warnings)

        # Build summary JSON
        summary_json = None
        if summary:
            summary_json = json.dumps(summary, default=str)

        # Build upstream dependencies JSON
        upstream_deps_json = None
        if self._upstream_dependencies:
            upstream_deps_json = json.dumps(self._upstream_dependencies, default=str)

        # Build missing/stale dependencies JSON
        missing_deps_json = json.dumps(self._missing_dependencies) if self._missing_dependencies else None
        stale_deps_json = json.dumps(self._stale_dependencies) if self._stale_dependencies else None

        # Build trigger message data JSON
        trigger_data_json = None
        if self._trigger_message_data:
            trigger_data_json = json.dumps(self._trigger_message_data, default=str)

        # Get Cloud Run metadata from environment
        cloud_run_service = os.environ.get('K_SERVICE')
        cloud_run_revision = os.environ.get('K_REVISION')
        execution_host = cloud_run_service or os.environ.get('HOSTNAME', 'local')
        triggered_by = os.environ.get('TRIGGERED_BY', self._trigger_source)

        # Get processor name - prefer class attribute, fall back to class name
        processor_name = getattr(self, 'processor_type', None) or self.__class__.__name__

        # Get output table info
        output_table = getattr(self, 'OUTPUT_TABLE', '') or getattr(self, 'table_name', '')
        output_dataset = getattr(self, 'OUTPUT_DATASET', '') or getattr(self, 'dataset_id', '')

        # Build record with all fields (new fields will be ignored if not in schema yet)
        record = {
            # Required fields (existing schema)
            'processor_name': processor_name,
            'run_id': self._run_history_id,
            'status': status,
            'data_date': str(self._run_data_date),
            'started_at': self._run_start_time.isoformat(),
            'processed_at': processed_at.isoformat(),

            # Existing optional fields
            'duration_seconds': duration_seconds,
            'records_processed': records_processed,
            'records_created': records_created,
            'records_updated': records_updated,
            'records_skipped': records_skipped,
            'execution_host': execution_host,
            'triggered_by': triggered_by,
            'errors': errors_json,
            'warnings': warnings_json,
            'summary': summary_json,
            'backfill_mode': getattr(self, 'backfill_mode', False),
            'force_reprocess': getattr(self, 'force_reprocess', False),
            'test_mode': getattr(self, 'test_mode', False),

            # NEW: Phase and output tracking
            'phase': self.PHASE,
            'output_table': output_table,
            'output_dataset': output_dataset,

            # NEW: Trigger tracking
            'trigger_source': self._trigger_source,
            'trigger_message_id': self._trigger_message_id,
            'trigger_message_data': trigger_data_json,
            'parent_processor': self._parent_processor,

            # NEW: Dependency tracking
            'upstream_dependencies': upstream_deps_json,
            'dependency_check_passed': self._dependency_check_passed,
            'missing_dependencies': missing_deps_json,
            'stale_dependencies': stale_deps_json,

            # NEW: Alert tracking
            'alert_sent': self._alert_sent,
            'alert_type': self._alert_type,

            # NEW: Cloud Run metadata
            'cloud_run_service': cloud_run_service,
            'cloud_run_revision': cloud_run_revision,

            # NEW: Retry and skip tracking
            'retry_attempt': self._retry_attempt,
            'skipped': self._skipped,
            'skip_reason': self._skip_reason,
        }

        # Remove None values and new fields if schema doesn't have them yet
        # This allows gradual rollout
        record = {k: v for k, v in record.items() if v is not None}

        # Insert to BigQuery
        self._insert_run_history(record)

        # Clear tracking state
        self._run_history_id = None
        self._run_start_time = None

    def _write_running_status(self) -> None:
        """
        Write 'running' status immediately to prevent duplicate processing.

        This is called at the START of processing to create a deduplication marker.
        Subsequent calls to _already_processed() will see this and skip duplicate runs.
        """
        # Get processor name and output info
        processor_name = getattr(self, 'processor_type', None) or self.__class__.__name__
        output_table = getattr(self, 'OUTPUT_TABLE', '') or getattr(self, 'table_name', '')
        output_dataset = getattr(self, 'OUTPUT_DATASET', '') or getattr(self, 'dataset_id', '')

        # Get Cloud Run metadata
        cloud_run_service = os.environ.get('K_SERVICE')
        cloud_run_revision = os.environ.get('K_REVISION')

        # Build minimal record for 'running' status
        record = {
            'processor_name': processor_name,
            'run_id': self._run_history_id,
            'phase': self.PHASE,
            'status': 'running',  # Key field for deduplication
            'data_date': str(self._run_data_date),
            'started_at': self._run_start_time.isoformat(),
            'trigger_source': self._trigger_source,
            'trigger_message_id': self._trigger_message_id,
            'parent_processor': self._parent_processor,
            'output_table': output_table,
            'output_dataset': output_dataset,
            'cloud_run_service': cloud_run_service,
            'cloud_run_revision': cloud_run_revision,
            'retry_attempt': self._retry_attempt,
        }

        # Remove None values
        record = {k: v for k, v in record.items() if v is not None}

        # Write immediately (non-blocking - don't fail processor if this fails)
        try:
            self._insert_run_history(record)
            logger.debug(f"Wrote 'running' status for deduplication: {self._run_history_id}")
        except Exception as e:
            # Log but don't fail - deduplication is nice-to-have, not critical
            logger.warning(f"Failed to write 'running' status (non-fatal): {e}")

    def _insert_run_history(self, record: Dict) -> None:
        """
        Insert run history record to BigQuery.

        Args:
            record: Record dictionary to insert
        """
        try:
            # Get BigQuery client - check various attribute names
            bq_client = getattr(self, 'bq_client', None)
            if bq_client is None:
                bq_client = bigquery.Client()

            project_id = getattr(self, 'project_id', None) or bq_client.project
            table_id = f"{project_id}.{self.RUN_HISTORY_TABLE}"

            # Get table schema to filter out fields not yet added
            try:
                table = bq_client.get_table(table_id)
                valid_fields = {field.name for field in table.schema}
                filtered_record = {k: v for k, v in record.items() if k in valid_fields}
            except Exception:
                # If we can't get schema, try with all fields
                filtered_record = record

            # Insert using streaming insert
            errors = bq_client.insert_rows_json(table_id, [filtered_record])

            if errors:
                logger.warning(f"Errors inserting run history: {errors}")
            else:
                logger.info(f"Recorded run history: {record.get('run_id')} - {record.get('status')} ({record.get('duration_seconds', 0):.1f}s)")

        except Exception as e:
            # Don't fail the processor if logging fails
            logger.error(f"Failed to insert run history (non-fatal): {e}")

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    def record_success(
        self,
        records_processed: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        summary: Optional[Dict] = None
    ) -> None:
        """Convenience method to record successful run."""
        self.record_run_complete(
            status='success',
            records_processed=records_processed,
            records_created=records_created,
            records_updated=records_updated,
            summary=summary
        )

    def record_failure(self, error: Exception, summary: Optional[Dict] = None) -> None:
        """Convenience method to record failed run."""
        self.record_run_complete(
            status='failed',
            error=error,
            summary=summary
        )

    def record_skipped(self, reason: str) -> None:
        """Convenience method to record skipped run."""
        self.set_skipped(reason)
        self.record_run_complete(status='skipped')

    def check_already_processed(
        self,
        processor_name: str,
        data_date: Union[date, str],
        stale_threshold_hours: int = 2
    ) -> bool:
        """
        Check if this processor already processed this date (deduplication).

        Checks processor_run_history for existing runs with:
        - status IN ('running', 'success', 'partial')
        - If status='running', checks if stale (> threshold hours)

        Args:
            processor_name: Name of processor to check
            data_date: Date to check
            stale_threshold_hours: Hours after which 'running' status is considered stale

        Returns:
            True if already processed (skip this run)
            False if not processed or stale (proceed with this run)
        """
        try:
            # Get BigQuery client
            bq_client = getattr(self, 'bq_client', None)
            if bq_client is None:
                bq_client = bigquery.Client()

            project_id = getattr(self, 'project_id', None) or bq_client.project

            # Convert date if string
            if isinstance(data_date, str):
                check_date = data_date
            else:
                check_date = str(data_date)

            # Query for existing runs
            query = f"""
            SELECT
                status,
                started_at,
                processed_at,
                run_id
            FROM `{project_id}.{self.RUN_HISTORY_TABLE}`
            WHERE processor_name = @processor_name
              AND data_date = @data_date
              AND status IN ('running', 'success', 'partial')
            ORDER BY started_at DESC
            LIMIT 1
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("processor_name", "STRING", processor_name),
                    bigquery.ScalarQueryParameter("data_date", "DATE", check_date)
                ]
            )

            results = list(bq_client.query(query, job_config=job_config).result())

            if not results:
                return False  # No previous runs found

            row = results[0]

            if row.status == 'running':
                # Check if stale
                age = datetime.now(timezone.utc) - row.started_at
                if age > timedelta(hours=stale_threshold_hours):
                    logger.warning(
                        f"Found stale 'running' status for {processor_name} on {check_date} "
                        f"(age: {age}, run_id: {row.run_id}). Allowing retry."
                    )
                    return False  # Stale - allow retry
                else:
                    logger.info(
                        f"Processor {processor_name} is currently running for {check_date} "
                        f"(started {age} ago, run_id: {row.run_id}). Skipping duplicate."
                    )
                    return True  # Currently running - skip

            else:  # status is 'success' or 'partial'
                logger.info(
                    f"Processor {processor_name} already processed {check_date} "
                    f"with status '{row.status}' (run_id: {row.run_id}). Skipping duplicate."
                )
                return True  # Already completed successfully

        except Exception as e:
            # On error, log but don't block processing
            logger.warning(f"Failed to check deduplication (non-fatal): {e}")
            return False  # Allow processing if check fails
