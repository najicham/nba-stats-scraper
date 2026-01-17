"""
UnifiedPubSubPublisher - Standardized Pub/Sub publishing across all phases.

Provides consistent message format and publishing behavior for:
- Phase 1: Scrapers
- Phase 2: Raw processors
- Phase 3: Analytics processors
- Phase 4: Precompute processors
- Phase 5: Prediction coordinator

Features:
- Unified message envelope with standard fields
- Backfill mode support (skip_downstream_trigger)
- Non-blocking error handling (don't fail processor on publish failure)
- Correlation ID tracking (traces scraper → prediction)
- Message validation
- Automatic retry on transient failures

Version: 1.0
Created: 2025-11-28
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)


class UnifiedPubSubPublisher:
    """
    Unified Pub/Sub publisher with standard message format.

    Usage:
        publisher = UnifiedPubSubPublisher(project_id='nba-props-platform')

        publisher.publish_completion(
            topic='nba-phase2-raw-complete',
            processor_name='BdlGamesProcessor',
            phase='phase_2_raw',
            execution_id='abc-123',
            correlation_id='abc-123',
            game_date='2025-11-28',
            output_table='bdl_games',
            output_dataset='nba_raw',
            status='success',
            record_count=150,
            skip_downstream=False
        )
    """

    def __init__(self, project_id: str = None):
        """
        Initialize publisher.

        Args:
            project_id: GCP project ID (defaults to environment)
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT', 'nba-props-platform')
        self._client = None

    @property
    def client(self) -> pubsub_v1.PublisherClient:
        """Lazy-load Pub/Sub client."""
        if self._client is None:
            self._client = pubsub_v1.PublisherClient()
        return self._client

    def publish_completion(
        self,
        topic: str,
        processor_name: str,
        phase: str,
        execution_id: str,
        game_date: str,
        output_table: str,
        output_dataset: str,
        status: str,
        record_count: int = 0,
        records_failed: int = 0,
        correlation_id: Optional[str] = None,
        parent_processor: Optional[str] = None,
        trigger_source: str = 'pubsub',
        trigger_message_id: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        metadata: Optional[Dict] = None,
        skip_downstream: bool = False
    ) -> Optional[str]:
        """
        Publish standardized completion event.

        Args:
            topic: Pub/Sub topic name (e.g., 'nba-phase2-raw-complete')
            processor_name: Name of processor (e.g., 'BdlGamesProcessor')
            phase: Processing phase (e.g., 'phase_2_raw')
            execution_id: Unique ID for this run
            game_date: Date being processed (ISO format YYYY-MM-DD)
            output_table: BigQuery table name
            output_dataset: BigQuery dataset name
            status: Status ('success', 'partial', 'no_data', 'failed')
            record_count: Records successfully processed
            records_failed: Records that failed (for partial status)
            correlation_id: UUID from original trigger (traces full pipeline)
            parent_processor: Upstream processor that triggered this
            trigger_source: What triggered this ('pubsub', 'scheduler', 'manual')
            trigger_message_id: Pub/Sub message ID that triggered this
            duration_seconds: How long processing took
            error_message: Error message if failed
            error_type: Error type if failed
            metadata: Phase-specific additional data
            skip_downstream: If True, skip publishing (backfill mode)

        Returns:
            Message ID if published successfully, None if skipped or failed
        """
        # Check backfill mode
        if skip_downstream:
            logger.info(f"Backfill mode: skipping downstream publish for {processor_name}")
            return None

        # Build unified message envelope
        message = self._build_message(
            processor_name=processor_name,
            phase=phase,
            execution_id=execution_id,
            correlation_id=correlation_id or execution_id,
            game_date=game_date,
            output_table=output_table,
            output_dataset=output_dataset,
            status=status,
            record_count=record_count,
            records_failed=records_failed,
            parent_processor=parent_processor,
            trigger_source=trigger_source,
            trigger_message_id=trigger_message_id,
            duration_seconds=duration_seconds,
            error_message=error_message,
            error_type=error_type,
            metadata=metadata
        )

        # Validate message
        if not self._validate_message(message):
            logger.error(f"Message validation failed for {processor_name}")
            return None

        # Publish
        return self._publish(topic, message)

    def _build_message(
        self,
        processor_name: str,
        phase: str,
        execution_id: str,
        correlation_id: str,
        game_date: str,
        output_table: str,
        output_dataset: str,
        status: str,
        record_count: int,
        records_failed: int,
        parent_processor: Optional[str],
        trigger_source: str,
        trigger_message_id: Optional[str],
        duration_seconds: Optional[float],
        error_message: Optional[str],
        error_type: Optional[str],
        metadata: Optional[Dict]
    ) -> Dict:
        """
        Build standardized message envelope.

        Returns:
            Message dictionary with all standard fields
        """
        message = {
            # === Identity ===
            "processor_name": processor_name,
            "phase": phase,
            "execution_id": execution_id,
            "correlation_id": correlation_id,

            # === Data Reference ===
            "game_date": game_date,
            "output_table": output_table,
            "output_dataset": output_dataset,

            # === Status ===
            "status": status,
            "record_count": record_count,
            "records_failed": records_failed,

            # === Timing ===
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration_seconds,

            # === Tracing ===
            "parent_processor": parent_processor,
            "trigger_source": trigger_source,
            "trigger_message_id": trigger_message_id,

            # === Error Info ===
            "error_message": error_message,
            "error_type": error_type,

            # === Phase-Specific ===
            "metadata": metadata or {}
        }

        # Remove None values
        return {k: v for k, v in message.items() if v is not None}

    def _validate_message(self, message: Dict) -> bool:
        """
        Validate message has required fields.

        Args:
            message: Message to validate

        Returns:
            True if valid, False otherwise
        """
        required_fields = [
            'processor_name',
            'phase',
            'execution_id',
            'correlation_id',
            'game_date',
            'status',
            'timestamp'
        ]

        for field in required_fields:
            if field not in message:
                logger.error(f"Missing required field: {field}")
                return False

        # Validate status
        valid_statuses = ['success', 'partial', 'no_data', 'failed']
        if message['status'] not in valid_statuses:
            logger.error(f"Invalid status: {message['status']}")
            return False

        return True

    def _publish(self, topic: str, message: Dict) -> Optional[str]:
        """
        Publish message to Pub/Sub topic.

        CRITICAL: Non-blocking - failures are logged but don't raise exceptions.
        This ensures processors don't fail if Pub/Sub is unavailable.

        Args:
            topic: Topic name (not full path)
            message: Message dictionary

        Returns:
            Message ID if successful, None if failed
        """
        try:
            # Build topic path
            topic_path = self.client.topic_path(self.project_id, topic)

            # Serialize message
            message_json = json.dumps(message, default=str)
            message_bytes = message_json.encode('utf-8')

            # Publish
            future = self.client.publish(topic_path, message_bytes)
            message_id = future.result(timeout=10.0)  # 10 second timeout

            logger.info(
                f"Published to {topic}: {message['processor_name']} "
                f"{message['game_date']} - {message['status']} "
                f"(message_id: {message_id})"
            )

            return message_id

        except Exception as e:
            # Log but don't raise - downstream has scheduler backup
            logger.error(
                f"Failed to publish to {topic} (non-fatal): {e}\n"
                f"Processor: {message.get('processor_name')}, "
                f"Date: {message.get('game_date')}"
            )

            # Send alert that event-driven trigger is broken
            # (AlertManager will handle this in production)
            self._alert_publish_failure(topic, message, e)

            return None

    def _alert_publish_failure(self, topic: str, message: Dict, error: Exception) -> None:
        """
        Alert on publish failure (placeholder - will integrate with AlertManager).

        Args:
            topic: Topic that failed
            message: Message that failed to publish
            error: Exception that occurred
        """
        # TODO: Integrate with AlertManager in next step
        logger.warning(
            f"Pub/Sub publishing failed for {message.get('processor_name')}. "
            f"Downstream will use scheduler backup."
        )

    def publish_batch(
        self,
        topic: str,
        messages: List[Dict],
        skip_downstream: bool = False
    ) -> List[Optional[str]]:
        """
        Publish multiple messages (for batch processing).

        Args:
            topic: Pub/Sub topic name
            messages: List of message dictionaries (already formatted)
            skip_downstream: If True, skip publishing (backfill mode)

        Returns:
            List of message IDs (None for failures)
        """
        if skip_downstream:
            logger.info(f"Backfill mode: skipping batch publish of {len(messages)} messages")
            return [None] * len(messages)

        message_ids = []
        for message in messages:
            message_id = self._publish(topic, message)
            message_ids.append(message_id)

        success_count = sum(1 for mid in message_ids if mid is not None)
        logger.info(
            f"Batch publish to {topic}: {success_count}/{len(messages)} successful"
        )

        return message_ids
