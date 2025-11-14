"""
pubsub_utils.py

Pub/Sub utility for Phase 1 → Phase 2 handoff in NBA Props Platform.

File Path: scrapers/utils/pubsub_utils.py

Purpose: 
- Publish scraper completion events to nba-scraper-complete topic
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

This enables Phase 2 processors to automatically process scraped data without polling.
"""

import logging
import json
import os
from datetime import datetime, timezone
from typing import Optional

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)


class ScraperPubSubPublisher:
    """
    Publishes scraper completion events to Pub/Sub for Phase 2 processors.
    
    The critical handoff between Phase 1 (data collection) and Phase 2 (processing).
    Phase 2 processors subscribe to these events and automatically process GCS files.
    """
    
    def __init__(self, project_id: str = None, topic_name: str = 'nba-scraper-complete'):
        """
        Initialize publisher.
        
        Args:
            project_id: GCP project ID (defaults to GCP_PROJECT_ID env var)
            topic_name: Pub/Sub topic name (default: 'nba-scraper-complete')
        """
        self.project_id = project_id or os.getenv('GCP_PROJECT_ID', 'nba-props-platform')
        self.topic_name = topic_name
        
        try:
            self.publisher = pubsub_v1.PublisherClient()
            self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)
            logger.debug(f"Initialized Pub/Sub publisher: {self.topic_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Pub/Sub publisher: {e}")
            raise
    
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
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Publish scraper completion event to Pub/Sub.
        
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
            >>> print(f"Published: {message_id}")

        Note:
            Message payload includes both 'name' and 'scraper_name' fields.
            Processors expect 'name', but 'scraper_name' is kept for backwards compatibility.
        """
        
        # Validate required fields
        if not scraper_name:
            logger.error("Cannot publish event: scraper_name is required")
            return None
        
        if not execution_id:
            logger.error("Cannot publish event: execution_id is required")
            return None
        
        if status not in ['success', 'no_data', 'failed']:
            logger.warning(f"Unexpected status value: {status} (expected: success/no_data/failed)")
        
        # Build message payload
        # NOTE: Processors expect 'name' field, but we also include 'scraper_name' for backwards compatibility
        message_data = {
            'name': scraper_name,  # Processors expect 'name'
            'scraper_name': scraper_name,  # Keep for backwards compatibility
            'execution_id': execution_id,
            'status': status,
            'gcs_path': gcs_path,
            'record_count': record_count,
            'duration_seconds': round(duration_seconds, 2),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'workflow': workflow,
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
                scraper_name=scraper_name,
                status=status,
                execution_id=execution_id,
                workflow=workflow or 'MANUAL'
            )
            
            # Wait for publish to complete (blocking, max 10 seconds)
            message_id = future.result(timeout=10)
            
            logger.info(
                f"✅ Published Pub/Sub event: {scraper_name} "
                f"(status={status}, records={record_count}, message_id={message_id})"
            )
            
            return message_id
            
        except Exception as e:
            # Log error but don't fail the scraper
            logger.error(
                f"Failed to publish Pub/Sub event for {scraper_name}: {e}",
                exc_info=True
            )
            
            # Capture in Sentry if available
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(e)
            except:
                pass
            
            return None
    
    def publish_batch_events(self, events: list[dict]) -> dict:
        """
        Publish multiple scraper events in batch (for backfills or bulk operations).
        
        Args:
            events: List of event dicts (each with same structure as publish_completion_event args)
            
        Returns:
            dict: Summary with 'succeeded', 'failed', 'message_ids'
            
        Example:
            >>> events = [
            ...     {'scraper_name': 'bdl_games', 'execution_id': '001', 'status': 'success', ...},
            ...     {'scraper_name': 'oddsa_events', 'execution_id': '002', 'status': 'success', ...}
            ... ]
            >>> result = publisher.publish_batch_events(events)
            >>> print(f"Published {result['succeeded']} events")
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
        
        summary = {
            'succeeded': succeeded,
            'failed': failed,
            'total': len(events),
            'message_ids': message_ids
        }
        
        logger.info(
            f"Batch publish complete: {succeeded}/{len(events)} succeeded, {failed} failed"
        )
        
        return summary


def test_pubsub_publisher():
    """
    Test function to verify Pub/Sub publishing works.
    
    Run with: python -m scrapers.utils.pubsub_utils
    """
    print("🧪 Testing Pub/Sub Publisher...")
    
    try:
        publisher = ScraperPubSubPublisher()
        print(f"✅ Publisher initialized: {publisher.topic_path}")
        
        # Test event
        message_id = publisher.publish_completion_event(
            scraper_name='test_scraper',
            execution_id='test-123',
            status='success',
            gcs_path='gs://bucket/test/file.json',
            record_count=10,
            duration_seconds=5.5,
            workflow='TEST'
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
    success = test_pubsub_publisher()
    sys.exit(0 if success else 1)
