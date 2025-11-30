# predictions/coordinator/run_history.py

"""
Run History Logger for Phase 5 Prediction Coordinator

Logs coordinator runs to processor_run_history table for unified monitoring.
This enables Grafana to show all phases (2-5) in a single dashboard.

Usage:
    run_history = CoordinatorRunHistory(project_id='nba-props-platform')

    # At batch start
    run_id = run_history.start_batch(
        batch_id='batch_2025-11-30_123456',
        game_date=date(2025, 11, 30),
        correlation_id='abc-123',
        parent_processor='MLFeatureStoreProcessor'
    )

    # At batch completion
    run_history.complete_batch(
        status='success',
        records_processed=450,
        duration_seconds=120.5,
        summary={'completed': 450, 'failed': 0}
    )

Version: 1.0
Created: 2025-11-30
"""

import json
import logging
import os
import uuid
from datetime import datetime, date, timezone
from typing import Dict, Optional, Any

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class CoordinatorRunHistory:
    """
    Logs Phase 5 Prediction Coordinator runs to processor_run_history.

    Provides unified monitoring across all pipeline phases (2-5) by logging
    to the same table used by Phase 2-4 processors.
    """

    # Phase 5 constants
    PHASE = 'phase_5_predictions'
    PROCESSOR_NAME = 'PredictionCoordinator'
    OUTPUT_TABLE = 'player_prop_predictions'
    OUTPUT_DATASET = 'nba_predictions'
    RUN_HISTORY_TABLE = 'nba_reference.processor_run_history'

    def __init__(self, project_id: str = 'nba-props-platform'):
        """
        Initialize run history logger.

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        self._bq_client = None

        # Run state
        self._run_id: Optional[str] = None
        self._batch_id: Optional[str] = None
        self._start_time: Optional[datetime] = None
        self._game_date: Optional[date] = None
        self._correlation_id: Optional[str] = None
        self._parent_processor: Optional[str] = None
        self._trigger_source: str = 'scheduler'
        self._trigger_message_id: Optional[str] = None

        # Cloud Run metadata
        self._cloud_run_service = os.environ.get('K_SERVICE')
        self._cloud_run_revision = os.environ.get('K_REVISION')

        logger.info(f"Initialized CoordinatorRunHistory for {self.RUN_HISTORY_TABLE}")

    @property
    def bq_client(self) -> bigquery.Client:
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    def start_batch(
        self,
        batch_id: str,
        game_date: date,
        correlation_id: Optional[str] = None,
        parent_processor: Optional[str] = None,
        trigger_source: str = 'scheduler',
        trigger_message_id: Optional[str] = None,
        expected_players: int = 0
    ) -> str:
        """
        Record batch start to processor_run_history.

        Writes a 'running' status record immediately to support:
        - Deduplication (detect if batch already running)
        - Real-time monitoring (Grafana sees batch started)

        Args:
            batch_id: Unique batch identifier
            game_date: Game date being processed
            correlation_id: Pipeline correlation ID for tracing
            parent_processor: Upstream processor that triggered this
            trigger_source: What triggered the batch (scheduler, api, pubsub)
            trigger_message_id: Pub/Sub message ID if triggered by Pub/Sub
            expected_players: Number of players to process

        Returns:
            run_id: Unique run identifier
        """
        # Store state
        self._batch_id = batch_id
        self._game_date = game_date
        self._correlation_id = correlation_id
        self._parent_processor = parent_processor
        self._trigger_source = trigger_source
        self._trigger_message_id = trigger_message_id
        self._start_time = datetime.now(timezone.utc)

        # Generate unique run ID
        self._run_id = f"{self.PROCESSOR_NAME}_{game_date.isoformat()}_{uuid.uuid4().hex[:8]}"

        # Build record
        record = {
            'processor_name': self.PROCESSOR_NAME,
            'run_id': self._run_id,
            'status': 'running',
            'data_date': str(game_date),
            'started_at': self._start_time.isoformat(),

            # Phase 5 identification
            'phase': self.PHASE,
            'output_table': self.OUTPUT_TABLE,
            'output_dataset': self.OUTPUT_DATASET,

            # Trigger tracking
            'trigger_source': trigger_source,
            'trigger_message_id': trigger_message_id,
            'parent_processor': parent_processor,

            # Cloud Run metadata
            'cloud_run_service': self._cloud_run_service,
            'cloud_run_revision': self._cloud_run_revision,
            'execution_host': self._cloud_run_service or 'local',
            'triggered_by': trigger_source,

            # Summary with initial state
            'summary': json.dumps({
                'batch_id': batch_id,
                'correlation_id': correlation_id,
                'expected_players': expected_players,
                'status': 'starting'
            })
        }

        # Write to BigQuery
        self._insert_record(record)

        logger.info(
            f"Started batch tracking: {self._run_id} "
            f"(game_date={game_date}, correlation_id={correlation_id})"
        )

        return self._run_id

    def complete_batch(
        self,
        status: str,
        records_processed: int = 0,
        records_failed: int = 0,
        duration_seconds: float = None,
        summary: Optional[Dict] = None,
        error: Optional[Exception] = None
    ) -> None:
        """
        Record batch completion to processor_run_history.

        Args:
            status: Final status (success, failed, partial)
            records_processed: Number of predictions generated
            records_failed: Number of predictions that failed
            duration_seconds: Total batch duration (calculated if not provided)
            summary: Additional summary data
            error: Exception if failed
        """
        if not self._start_time:
            logger.warning("complete_batch called without start_batch - skipping")
            return

        processed_at = datetime.now(timezone.utc)

        # Calculate duration if not provided
        if duration_seconds is None:
            duration_seconds = (processed_at - self._start_time).total_seconds()

        # Build errors JSON if failed
        errors_json = None
        if error:
            errors_json = json.dumps([{
                'error_type': type(error).__name__,
                'error_message': str(error),
                'timestamp': processed_at.isoformat()
            }])

        # Build summary JSON
        summary_data = summary or {}
        summary_data.update({
            'batch_id': self._batch_id,
            'correlation_id': self._correlation_id,
            'records_processed': records_processed,
            'records_failed': records_failed,
            'duration_seconds': duration_seconds
        })

        # Build record
        record = {
            'processor_name': self.PROCESSOR_NAME,
            'run_id': self._run_id,
            'status': status,
            'data_date': str(self._game_date),
            'started_at': self._start_time.isoformat(),
            'processed_at': processed_at.isoformat(),

            # Metrics
            'duration_seconds': duration_seconds,
            'records_processed': records_processed,
            'records_skipped': records_failed,  # Using skipped for failed count

            # Phase 5 identification
            'phase': self.PHASE,
            'output_table': self.OUTPUT_TABLE,
            'output_dataset': self.OUTPUT_DATASET,

            # Trigger tracking
            'trigger_source': self._trigger_source,
            'trigger_message_id': self._trigger_message_id,
            'parent_processor': self._parent_processor,

            # Cloud Run metadata
            'cloud_run_service': self._cloud_run_service,
            'cloud_run_revision': self._cloud_run_revision,
            'execution_host': self._cloud_run_service or 'local',
            'triggered_by': self._trigger_source,

            # Results
            'errors': errors_json,
            'summary': json.dumps(summary_data, default=str)
        }

        # Write to BigQuery
        self._insert_record(record)

        logger.info(
            f"Completed batch tracking: {self._run_id} "
            f"(status={status}, records={records_processed}, duration={duration_seconds:.1f}s)"
        )

        # Clear state
        self._run_id = None
        self._start_time = None

    def _insert_record(self, record: Dict) -> None:
        """
        Insert record to processor_run_history.

        Args:
            record: Record dictionary to insert
        """
        try:
            table_id = f"{self.project_id}.{self.RUN_HISTORY_TABLE}"

            # Get table schema to filter out fields not in schema
            try:
                table = self.bq_client.get_table(table_id)
                valid_fields = {field.name for field in table.schema}
                filtered_record = {k: v for k, v in record.items() if k in valid_fields and v is not None}
            except Exception:
                # If we can't get schema, use record as-is
                filtered_record = {k: v for k, v in record.items() if v is not None}

            # Insert using streaming insert
            errors = self.bq_client.insert_rows_json(table_id, [filtered_record])

            if errors:
                logger.warning(f"Errors inserting run history: {errors}")
            else:
                logger.debug(f"Inserted run history: {record.get('run_id')} - {record.get('status')}")

        except Exception as e:
            # Don't fail the batch if logging fails
            logger.error(f"Failed to insert run history (non-fatal): {e}")

    def check_already_running(self, game_date: date, stale_threshold_hours: int = 2) -> bool:
        """
        Check if a batch is already running for this game date.

        Args:
            game_date: Game date to check
            stale_threshold_hours: Hours after which 'running' is considered stale

        Returns:
            True if batch already running (skip this batch)
            False if no batch running or stale (proceed with batch)
        """
        try:
            query = f"""
            SELECT status, started_at, run_id
            FROM `{self.project_id}.{self.RUN_HISTORY_TABLE}`
            WHERE processor_name = @processor_name
              AND data_date = @data_date
              AND status IN ('running', 'success', 'partial')
            ORDER BY started_at DESC
            LIMIT 1
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("processor_name", "STRING", self.PROCESSOR_NAME),
                    bigquery.ScalarQueryParameter("data_date", "DATE", str(game_date))
                ]
            )

            results = list(self.bq_client.query(query, job_config=job_config).result())

            if not results:
                return False  # No previous runs

            row = results[0]

            if row.status == 'running':
                # Check if stale
                age = datetime.now(timezone.utc) - row.started_at
                if age.total_seconds() > stale_threshold_hours * 3600:
                    logger.warning(f"Found stale 'running' batch for {game_date} - allowing new batch")
                    return False
                else:
                    logger.info(f"Batch already running for {game_date} (run_id={row.run_id})")
                    return True
            else:
                # Already completed successfully
                logger.info(f"Batch already completed for {game_date} (status={row.status})")
                return True

        except Exception as e:
            logger.warning(f"Failed to check running status (non-fatal): {e}")
            return False  # Allow batch if check fails
