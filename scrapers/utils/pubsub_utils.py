"""
pubsub_utils.py

Pub/Sub utility for Phase 1 → Phase 2 handoff in NBA Props Platform.

File Path: scrapers/utils/pubsub_utils.py

Purpose:
- Publish scraper completion events using unified message format
- Enable event-driven Phase 2 processor triggering
- Track execution metadata for orchestration

Usage:
    from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

    publisher = ScraperPubSubPublisher()
    message_id = publisher.publish_completion_event(
        scraper_name='bdl_games',
        execution_id='abc-123',
        status='success',
        gcs_path='gs://bucket/path/file.json',
        record_count=150
    )

Status Values:
    - 'success': Got data (record_count > 0)
    - 'no_data': Tried but empty (record_count = 0)
    - 'failed': Error occurred

Version: 2.0 (uses UnifiedPubSubPublisher)
Updated: 2025-11-28
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

# NEW: Use unified publisher
from shared.publishers import UnifiedPubSubPublisher
from shared.config.pubsub_topics import TOPICS

logger = logging.getLogger(__name__)


class ScraperPubSubPublisher:
    """
    Publishes scraper completion events to Pub/Sub for Phase 2 processors.

    The critical handoff between Phase 1 (data collection) and Phase 2 (processing).
    Phase 2 processors subscribe to these events and automatically process GCS files.

    Version: 2.0 - Uses UnifiedPubSubPublisher for standardized message format.
    """

    def __init__(
        self,
        project_id: str = None,
        dual_publish: bool = False  # Disabled by default - v1.0 uses unified format only
    ):
        """
        Initialize publisher.

        Args:
            project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
            dual_publish: DEPRECATED - kept for backwards compatibility but ignored
        """
        self.project_id = project_id or os.getenv('GCP_PROJECT_ID', 'nba-props-platform')

        # Use unified publisher
        self.publisher = UnifiedPubSubPublisher(project_id=self.project_id)

        # Topic from centralized config
        self.topic_name = TOPICS.PHASE1_SCRAPERS_COMPLETE

        if dual_publish:
            logger.warning(
                "dual_publish parameter is deprecated - v1.0 uses unified format only"
            )

        logger.info(f"ScraperPubSubPublisher initialized: {self.topic_name}")
    
    def publish_completion_event(
        self,
        scraper_name: str,
        execution_id: str,
        status: str,
        gcs_path: Optional[str] = None,
        record_count: int = 0,
        duration_seconds: float = 0,
        error_message: Optional[str] = None,
        workflow: Optional[str] = None,
        metadata: Optional[dict] = None,
        game_date: Optional[str] = None  # NEW: for unified format
    ) -> Optional[str]:
        """
        Publish scraper completion event using unified message format.

        Args:
            scraper_name: Name of scraper (e.g., 'bdl_games', 'oddsa_events')
            execution_id: Unique execution ID (run_id from scraper)
            status: Execution status ('success', 'no_data', or 'failed')
            gcs_path: Path to output file in GCS (if any)
            record_count: Number of records processed
            duration_seconds: Execution duration in seconds
            error_message: Error message if status is 'failed'
            workflow: Workflow name if triggered by orchestration
            metadata: Additional metadata to include in event
            game_date: Game date being processed (extracted from workflow if not provided)

        Returns:
            message_id: Pub/Sub message ID (or None if publish failed)

        Example:
            >>> publisher = ScraperPubSubPublisher()
            >>> message_id = publisher.publish_completion_event(
            ...     scraper_name='bdl_games',
            ...     execution_id='abc-123',
            ...     status='success',
            ...     gcs_path='gs://bucket/bdl/2024-25/2025-11-12/games.json',
            ...     record_count=150,
            ...     duration_seconds=28.5
            ... )
        """

        # Validate
        if not scraper_name:
            logger.error("Cannot publish: scraper_name required")
            return None

        if not execution_id:
            logger.error("Cannot publish: execution_id required")
            return None

        if status not in ['success', 'no_data', 'failed']:
            logger.warning(f"Unexpected status: {status}")

        # Extract game_date from GCS path if not provided
        if not game_date and gcs_path:
            # Try to extract from path like: gs://bucket/bdl/2024-25/2025-11-28/file.json
            import re
            match = re.search(r'/(\d{4}-\d{2}-\d{2})/', gcs_path)
            if match:
                game_date = match.group(1)

        # Fallback to today
        if not game_date:
            game_date = datetime.now().strftime('%Y-%m-%d')

        # Build metadata with scraper-specific info
        scraper_metadata = metadata or {}
        scraper_metadata.update({
            'gcs_path': gcs_path,
            'workflow': workflow or 'MANUAL',
            'scraper_type': 'api'  # Could be enhanced to detect type
        })

        # Use unified publisher
        try:
            message_id = self.publisher.publish_completion(
                topic=self.topic_name,
                processor_name=scraper_name,
                phase='phase_1_scrapers',
                execution_id=execution_id,
                correlation_id=execution_id,  # For scrapers, execution_id = correlation_id
                game_date=game_date,
                output_table=scraper_name.replace('_', ''),  # Approximate - Phase 2 has actual table
                output_dataset='nba_raw',
                status=status,
                record_count=record_count,
                records_failed=0,
                duration_seconds=duration_seconds,
                error_message=error_message,
                error_type=type(Exception).__name__ if error_message else None,
                metadata=scraper_metadata,
                trigger_source='scheduler' if workflow else 'manual',
                skip_downstream=False  # Never skip for production scrapers
            )

            if message_id:
                logger.info(
                    f"✅ Published {scraper_name}: {game_date} - {status} "
                    f"({record_count} records, message_id={message_id})"
                )
            else:
                logger.warning(
                    f"⚠️  Publish returned None for {scraper_name} (non-fatal)"
                )

            return message_id

        except Exception as e:
            # Non-blocking - log but don't fail scraper
            logger.error(f"Failed to publish for {scraper_name}: {e}", exc_info=True)

            # Capture in Sentry
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except ImportError:
                logger.debug("Sentry SDK not installed, skipping exception capture")
            except Exception as sentry_error:
                logger.debug(f"Sentry capture failed (non-critical): {sentry_error}")

            return None
    
    def publish_batch_events(self, events: list[dict]) -> dict:
        """
        Publish multiple scraper events in batch.

        Args:
            events: List of event dicts (kwargs for publish_completion_event)

        Returns:
            dict: Summary with 'succeeded', 'failed', 'message_ids'

        Example:
            >>> events = [
            ...     {'scraper_name': 'bdl_games', 'execution_id': '001', 'status': 'success', ...},
            ...     {'scraper_name': 'oddsa_events', 'execution_id': '002', 'status': 'success', ...}
            ... ]
            >>> result = publisher.publish_batch_events(events)
        """
        succeeded = 0
        failed = 0
        message_ids = []

        for event in events:
            message_id = self.publish_completion_event(**event)
            if message_id:
                succeeded += 1
                message_ids.append(message_id)
            else:
                failed += 1

        logger.info(f"Batch publish: {succeeded}/{len(events)} succeeded, {failed} failed")

        return {
            'succeeded': succeeded,
            'failed': failed,
            'total': len(events),
            'message_ids': message_ids
        }


def test_pubsub_publisher():
    """
    Test function to verify Pub/Sub publishing works.

    Run with: python -m scrapers.utils.pubsub_utils
    """
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing ScraperPubSubPublisher (v2.0 - UnifiedPubSubPublisher)")

    try:
        publisher = ScraperPubSubPublisher()
        logger.info(f"Publisher initialized: {publisher.topic_name}")

        # Test event
        message_id = publisher.publish_completion_event(
            scraper_name='test_scraper',
            execution_id='test-123',
            status='success',
            gcs_path='gs://bucket/test/2025-11-28/file.json',
            record_count=10,
            duration_seconds=5.5,
            workflow='TEST',
            game_date='2025-11-28'
        )

        if message_id:
            logger.info(f"Test event published: {message_id}")
            logger.info("Message format: unified (phase_1_scrapers)")
            return True
        else:
            logger.error("Test event failed to publish")
            return False

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return False


if __name__ == '__main__':
    # Run test when executed directly
    import sys
    success = test_pubsub_publisher()
    sys.exit(0 if success else 1)
