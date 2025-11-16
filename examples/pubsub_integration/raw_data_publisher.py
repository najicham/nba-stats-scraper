"""
Example implementation of RawDataPubSubPublisher for Phase 2 processors.

This is a reference implementation extracted from the architecture documentation.
See docs/architecture/01-phase1-to-phase5-integration-plan.md for context.
"""

from google.cloud import pubsub_v1
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class RawDataPubSubPublisher:
    """Publishes raw data completion events to trigger analytics processors."""

    def __init__(self):
        self.publisher = pubsub_v1.PublisherClient()
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.topic_name = 'nba-raw-data-complete'
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

    def publish_completion_event(
        self,
        source_table: str,
        target_table: str,
        processor_name: str,
        execution_id: str,
        game_date: Optional[str] = None,
        game_ids: Optional[List[str]] = None,
        record_count: int = 0,
        status: str = "success",
        correlation_id: Optional[str] = None,
        source_scraper_execution_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Publish raw data completion event.

        Args:
            source_table: Name of the source table (e.g., "nbac_gamebook_player_stats")
            target_table: Full BigQuery table name (e.g., "nba_raw.nbac_gamebook_player_stats")
            processor_name: Class name of the processor
            execution_id: Unique ID for this processor execution
            game_date: Date of games processed (YYYY-MM-DD)
            game_ids: List of specific game IDs affected
            record_count: Number of records processed
            status: success|failed|no_data
            correlation_id: ID linking entire pipeline run (for end-to-end tracking)
            source_scraper_execution_id: Execution ID from originating scraper
            metadata: Additional metadata (duration, rows_inserted, etc.)

        Returns:
            message_id: Pub/Sub message ID, or None if publishing failed
        """
        message_data = {
            'event_type': 'raw_data_loaded',
            'source_table': source_table,
            'target_table': target_table,
            'processor_name': processor_name,
            'execution_id': execution_id,
            'correlation_id': correlation_id or execution_id,
            'game_date': game_date,
            'game_ids': game_ids or [],
            'record_count': record_count,
            'status': status,
            'timestamp': datetime.utcnow().isoformat(),
            'source_scraper_execution_id': source_scraper_execution_id,
            'metadata': metadata or {}
        }

        # Publish
        message_json = json.dumps(message_data)
        message_bytes = message_json.encode('utf-8')

        try:
            future = self.publisher.publish(self.topic_path, message_bytes)
            message_id = future.result(timeout=10)

            logger.info(
                f"✅ Published raw data event: {source_table} "
                f"(game_date={game_date}, message_id={message_id}, correlation_id={correlation_id})"
            )

            return message_id

        except Exception as e:
            logger.error(f"Failed to publish raw data event: {e}")
            # Don't fail processor if pub/sub publishing fails (graceful degradation)
            return None


# Example usage in a Phase 2 processor:
"""
from examples.pubsub_integration.raw_data_publisher import RawDataPubSubPublisher

class SomeRawProcessor(ProcessorBase):
    def run(self, opts):
        # ... existing processing logic ...

        # After successful load to BigQuery:
        if self.load_success:
            publisher = RawDataPubSubPublisher()
            publisher.publish_completion_event(
                source_table=self.table_name,
                target_table=f"nba_raw.{self.table_name}",
                processor_name=self.__class__.__name__,
                execution_id=self.run_id,
                correlation_id=opts.get('correlation_id'),
                game_date=opts.get('game_date'),
                game_ids=self.get_game_ids_from_data(),
                record_count=len(self.processed_data),
                status="success",
                source_scraper_execution_id=opts.get('execution_id'),
                metadata={
                    'duration_seconds': self.stats.get('total_runtime'),
                    'rows_inserted': self.stats.get('rows_inserted'),
                    'rows_updated': self.stats.get('rows_updated')
                }
            )
"""
