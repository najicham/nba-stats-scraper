# orchestration/shared/utils/pubsub_client.py
"""
Pub/Sub client utilities for NBA platform
"""

import json
import logging
from typing import Dict, Any, Callable, Optional
from datetime import datetime, timezone
import base64

from google.cloud import pubsub_v1
from google.api_core import exceptions

logger = logging.getLogger(__name__)


class PubSubClient:
    """Centralized Pub/Sub operations for NBA platform"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.publisher = pubsub_v1.PublisherClient()
        self.subscriber = pubsub_v1.SubscriberClient()

    def publish_message(self, topic_name: str, data: Dict[str, Any],
                       attributes: Optional[Dict[str, str]] = None) -> bool:
        """
        Publish message to Pub/Sub topic

        Args:
            topic_name: Name of the topic (not full path)
            data: Message data as dictionary
            attributes: Optional message attributes

        Returns:
            True if successful
        """
        topic_path = self.publisher.topic_path(self.project_id, topic_name)

        # Add standard attributes
        if attributes is None:
            attributes = {}

        attributes.update({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'service': data.get('service', 'unknown'),
            'event_type': data.get('event_type', 'unknown')
        })

        # Serialize data
        message_json = json.dumps(data, ensure_ascii=False)
        message_bytes = message_json.encode('utf-8')

        try:
            future = self.publisher.publish(topic_path, message_bytes, **attributes)
            message_id = future.result()

            logger.info(f"Published message {message_id} to {topic_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to publish to {topic_name}: {e}", exc_info=True)
            return False

    def publish_scraper_completed(self, scraper_name: str, run_id: str,
                                 records_count: int, gcs_path: str) -> bool:
        """
        Publish standard scraper completion message

        Args:
            scraper_name: Name of the scraper that completed
            run_id: Unique run identifier
            records_count: Number of records scraped
            gcs_path: Path to stored data in GCS

        Returns:
            True if successful
        """
        message_data = {
            'event_type': 'data_scraped',
            'service': 'scrapers',
            'scraper': scraper_name,
            'run_id': run_id,
            'records_count': records_count,
            'gcs_path': gcs_path,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'next_action': 'process_data'
        }

        return self.publish_message('nba-data-events', message_data)

    def publish_processing_completed(self, processor_name: str, run_id: str,
                                   table_name: str, records_count: int) -> bool:
        """
        Publish standard processor completion message

        Args:
            processor_name: Name of the processor that completed
            run_id: Unique run identifier
            table_name: BigQuery table where data was loaded
            records_count: Number of records processed

        Returns:
            True if successful
        """
        message_data = {
            'event_type': 'data_processed',
            'service': 'processors',
            'processor': processor_name,
            'run_id': run_id,
            'table_name': table_name,
            'records_count': records_count,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'next_action': 'generate_reports'
        }

        return self.publish_message('nba-processing-events', message_data)

    def subscribe_to_messages(self, subscription_name: str,
                            callback: Callable[[Dict[str, Any]], None],
                            max_messages: int = 10) -> None:
        """
        Subscribe to messages and process with callback

        Args:
            subscription_name: Name of the subscription
            callback: Function to process each message
            max_messages: Max messages to process concurrently
        """
        subscription_path = self.subscriber.subscription_path(
            self.project_id, subscription_name
        )

        flow_control = pubsub_v1.types.FlowControlSettings(max_messages=max_messages)

        def message_handler(message):
            try:
                # Decode message data
                data = json.loads(message.data.decode('utf-8'))

                # Add message attributes to data
                data['_attributes'] = dict(message.attributes)
                data['_message_id'] = message.message_id
                data['_publish_time'] = message.publish_time

                # Process with callback
                callback(data)

                # Acknowledge successful processing
                message.ack()
                logger.info(f"Processed message {message.message_id}")

            except Exception as e:
                logger.error(f"Failed to process message {message.message_id}: {e}", exc_info=True)
                message.nack()  # Negative acknowledgment for retry

        try:
            streaming_pull_future = self.subscriber.subscribe(
                subscription_path,
                callback=message_handler,
                flow_control=flow_control
            )

            logger.info(f"Listening for messages on {subscription_name}")

            # Keep the main thread running
            with self.subscriber:
                try:
                    streaming_pull_future.result()
                except KeyboardInterrupt:
                    streaming_pull_future.cancel()
                    logger.info("Subscription cancelled")

        except Exception as e:
            logger.error(f"Error in subscription {subscription_name}: {e}", exc_info=True)

    def create_subscription(self, topic_name: str, subscription_name: str,
                          push_endpoint: Optional[str] = None) -> bool:
        """
        Create a Pub/Sub subscription

        Args:
            topic_name: Name of the topic
            subscription_name: Name of the subscription to create
            push_endpoint: Optional HTTP endpoint for push delivery

        Returns:
            True if successful
        """
        topic_path = self.publisher.topic_path(self.project_id, topic_name)
        subscription_path = self.subscriber.subscription_path(
            self.project_id, subscription_name
        )

        try:
            if push_endpoint:
                push_config = pubsub_v1.PushConfig(push_endpoint=push_endpoint)
                subscription = self.subscriber.create_subscription(
                    request={
                        "name": subscription_path,
                        "topic": topic_path,
                        "push_config": push_config
                    }
                )
            else:
                subscription = self.subscriber.create_subscription(
                    request={"name": subscription_path, "topic": topic_path}
                )

            logger.info(f"Created subscription {subscription_name}")
            return True

        except exceptions.AlreadyExists:
            logger.info(f"Subscription {subscription_name} already exists")
            return True
        except Exception as e:
            logger.error(f"Failed to create subscription {subscription_name}: {e}", exc_info=True)
            return False
