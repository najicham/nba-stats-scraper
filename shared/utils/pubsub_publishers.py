"""
pubsub_publishers.py

Pub/Sub publishers for Phase 2+ completion events in NBA Props Platform.

File Path: shared/utils/pubsub_publishers.py

Purpose:
- Publish Phase 2 (raw data) completion events to trigger Phase 3 (analytics)
- Publish Phase 3 (analytics) completion events to trigger Phase 4 (precompute)
- Enable event-driven processing across pipeline phases

Usage:
    from shared.utils.pubsub_publishers import RawDataPubSubPublisher

    publisher = RawDataPubSubPublisher(project_id='nba-props-platform')
    message_id = publisher.publish_raw_data_loaded(
        source_table='nbac_gamebook_player_stats',
        game_date='2024-11-14',
        record_count=450,
        execution_id='abc-123'
    )

Event Types:
    - 'raw_data_loaded': Phase 2 completed, triggers Phase 3
    - 'analytics_complete': Phase 3 completed, triggers Phase 4

This enables automatic pipeline progression without polling or manual triggers.
"""

import logging
import json
import os
from datetime import datetime, timezone
from typing import Optional

from google.cloud import pubsub_v1
from shared.config.pubsub_topics import TOPICS

logger = logging.getLogger(__name__)


class RawDataPubSubPublisher:
    """
    Publishes Phase 2 (raw data) completion events to trigger Phase 3 (analytics).

    When raw data is successfully loaded to BigQuery, this publisher notifies
    Phase 3 analytics processors that new data is available for processing.
    """

    def __init__(self, project_id: str = None):
        """
        Initialize Phase 2 completion event publisher.

        Args:
            project_id: GCP project ID (defaults to centralized config)
        """
        if project_id:
            self.project_id = project_id
        else:
            from shared.config.gcp_config import get_project_id
            self.project_id = get_project_id()

        # Use centralized topic config
        self.topic_name = TOPICS.PHASE2_RAW_COMPLETE

        try:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)
            logger.info(f"Initialized Phase 2 publisher: {self.topic_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Phase 2 publisher: {e}")
            raise

    def publish_raw_data_loaded(
        self,
        source_table: str,
        game_date: str,
        record_count: int,
        execution_id: str,
        correlation_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Publish Phase 2 completion event to trigger Phase 3 analytics.

        Args:
            source_table: BigQuery table name where data was loaded
            game_date: Game date of the data (YYYY-MM-DD format)
            record_count: Number of records loaded
            execution_id: Unique execution ID from Phase 2 processor
            correlation_id: Optional correlation ID (traces back to scraper)
            success: Whether processing succeeded (default: True)
            error_message: Error message if success=False
            metadata: Additional metadata to include in event

        Returns:
            message_id: Pub/Sub message ID (or None if publish failed)

        Example:
            >>> publisher = RawDataPubSubPublisher()
            >>> message_id = publisher.publish_raw_data_loaded(
            ...     source_table='nbac_gamebook_player_stats',
            ...     game_date='2024-11-14',
            ...     record_count=450,
            ...     execution_id='proc-abc-123',
            ...     correlation_id='scrape-xyz-456'
            ... )
            >>> print(f"Published: {message_id}")
        """

        # Validate required fields
        if not source_table:
            logger.error("Cannot publish event: source_table is required")
            return None

        if not game_date:
            logger.error("Cannot publish event: game_date is required")
            return None

        if not execution_id:
            logger.error("Cannot publish event: execution_id is required")
            return None

        # Build message payload
        message_data = {
            'event_type': 'raw_data_loaded',
            'source_table': source_table,
            'game_date': game_date,
            'record_count': record_count,
            'execution_id': execution_id,
            'correlation_id': correlation_id or execution_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'phase': 2,
            'success': success,
            'error_message': error_message
        }

        # Add optional metadata
        if metadata:
            message_data['metadata'] = metadata

        try:
            # Publish with message attributes for subscription filtering
            future = self.publisher.publish(
                self.topic_path,
                data=json.dumps(message_data).encode('utf-8'),
                # Message attributes for Pub/Sub filtering
                source_table=source_table,
                game_date=game_date,
                execution_id=execution_id,
                phase='2',
                success=str(success).lower()
            )

            # Wait for publish to complete (blocking, max 10 seconds)
            message_id = future.result(timeout=10)

            logger.info(
                f"✅ Published Phase 2 completion: {source_table} for {game_date} "
                f"(records={record_count}, message_id={message_id})"
            )

            return message_id

        except Exception as e:
            # Log error but don't fail the processor
            logger.error(
                f"Failed to publish Phase 2 completion for {source_table}: {e}",
                exc_info=True
            )

            # Capture in Sentry if available
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except (ImportError, Exception):
                # Sentry not available or failed to capture
                pass

            return None


class AnalyticsPubSubPublisher:
    """
    Publishes Phase 3 (analytics) completion events to trigger Phase 4 (precompute).

    When analytics data is successfully computed and loaded to BigQuery, this publisher
    notifies Phase 4 precompute processors that new analytics are available.
    """

    def __init__(self, project_id: str = None):
        """
        Initialize Phase 3 completion event publisher.

        Args:
            project_id: GCP project ID (defaults to centralized config)
        """
        if project_id:
            self.project_id = project_id
        else:
            from shared.config.gcp_config import get_project_id
            self.project_id = get_project_id()

        # Use centralized topic config
        self.topic_name = TOPICS.PHASE3_ANALYTICS_COMPLETE

        try:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)
            logger.info(f"Initialized Phase 3 publisher: {self.topic_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Phase 3 publisher: {e}")
            raise

    def publish_analytics_complete(
        self,
        analytics_table: str,
        game_date: str,
        record_count: int,
        execution_id: str,
        correlation_id: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Publish Phase 3 completion event to trigger Phase 4 precompute.

        Args:
            analytics_table: BigQuery analytics table name
            game_date: Game date of the analytics (YYYY-MM-DD format)
            record_count: Number of analytics records computed
            execution_id: Unique execution ID from Phase 3 processor
            correlation_id: Optional correlation ID (traces back to Phase 2)
            success: Whether processing succeeded (default: True)
            error_message: Error message if success=False
            metadata: Additional metadata to include in event

        Returns:
            message_id: Pub/Sub message ID (or None if publish failed)
        """

        # Validate required fields
        if not analytics_table:
            logger.error("Cannot publish event: analytics_table is required")
            return None

        if not game_date:
            logger.error("Cannot publish event: game_date is required")
            return None

        if not execution_id:
            logger.error("Cannot publish event: execution_id is required")
            return None

        # Build message payload
        message_data = {
            'event_type': 'analytics_complete',
            'analytics_table': analytics_table,
            'game_date': game_date,
            'record_count': record_count,
            'execution_id': execution_id,
            'correlation_id': correlation_id or execution_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'phase': 3,
            'success': success,
            'error_message': error_message
        }

        # Add optional metadata
        if metadata:
            message_data['metadata'] = metadata

        try:
            # Publish with message attributes for subscription filtering
            future = self.publisher.publish(
                self.topic_path,
                data=json.dumps(message_data).encode('utf-8'),
                # Message attributes for Pub/Sub filtering
                analytics_table=analytics_table,
                game_date=game_date,
                execution_id=execution_id,
                phase='3',
                success=str(success).lower()
            )

            # Wait for publish to complete (blocking, max 10 seconds)
            message_id = future.result(timeout=10)

            logger.info(
                f"✅ Published Phase 3 completion: {analytics_table} for {game_date} "
                f"(records={record_count}, message_id={message_id})"
            )

            return message_id

        except Exception as e:
            # Log error but don't fail the processor
            logger.error(
                f"Failed to publish Phase 3 completion for {analytics_table}: {e}",
                exc_info=True
            )

            # Capture in Sentry if available
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except (ImportError, Exception):
                # Sentry not available or failed to capture
                pass

            return None


def test_phase2_publisher():
    """
    Test function to verify Phase 2 publisher works.

    Run with: python -m shared.utils.pubsub_publishers
    """
    print("🧪 Testing Phase 2 Publisher...")

    try:
        publisher = RawDataPubSubPublisher()
        print(f"✅ Publisher initialized: {publisher.topic_path}")

        # Test event
        message_id = publisher.publish_raw_data_loaded(
            source_table='test_table',
            game_date='2024-11-16',
            record_count=100,
            execution_id='test-phase2-123',
            correlation_id='test-scraper-456'
        )

        if message_id:
            print(f"✅ Test event published successfully: {message_id}")
            return True
        else:
            print("❌ Test event failed to publish")
            return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    # Run test when executed directly
    import sys
    success = test_phase2_publisher()
    sys.exit(0 if success else 1)
