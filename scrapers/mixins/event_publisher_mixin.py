"""
EventPublisherMixin

A mixin that handles Pub/Sub event publishing for scraper completion and failure events.
This enables asynchronous notification of Phase 2 processors for data processing workflows.
"""

import logging
import sentry_sdk

# Initialize logger for this module
logger = logging.getLogger(__name__)


class EventPublisherMixin:
    """
    Mixin that provides Pub/Sub event publishing capabilities for scrapers.

    This mixin handles the critical handoff between Phase 1 (data collection) and
    Phase 2 (data processing) by publishing completion and failure events to Pub/Sub.
    Phase 2 processors listen for these events and automatically process the GCS files.
    """

    def _publish_completion_event_to_pubsub(self):
        """
        Publish scraper completion event to Pub/Sub for Phase 2 processors.

        This is the critical handoff between Phase 1 (data collection) and
        Phase 2 (data processing). Phase 2 processors listen for these events
        and automatically process the GCS files.

        Never fails the scraper - logs errors but continues.
        """
        try:
            from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

            publisher = ScraperPubSubPublisher()

            # Get status and record count from execution
            status, record_count = self._determine_execution_status()

            # Publish event
            message_id = publisher.publish_completion_event(
                scraper_name=self._get_scraper_name(),
                execution_id=self.run_id,
                status=status,
                gcs_path=self.opts.get('gcs_output_path'),
                record_count=record_count,
                duration_seconds=self.stats.get('total_runtime', 0),
                workflow=self.opts.get('workflow', 'MANUAL'),
                error_message=None,
                metadata={
                    'scraper_class': self.__class__.__name__,
                    'opts': {k: v for k, v in self.opts.items()
                            if k not in ['password', 'api_key', 'token', 'proxyUrl']}
                }
            )

            if message_id:
                logger.info(f"✅ Phase 2 notified via Pub/Sub (message_id: {message_id})")
            else:
                logger.warning("⚠️ Failed to notify Phase 2 (Pub/Sub publish failed)")

        except ImportError as e:
            # google-cloud-pubsub not installed
            logger.warning(f"Pub/Sub not available (install google-cloud-pubsub): {e}")
        except Exception as e:
            # Don't fail the scraper if Pub/Sub publishing fails
            logger.error(f"Failed to publish Pub/Sub event: {e}")
            # Still capture in Sentry for alerting
            try:
                sentry_sdk.capture_exception(e)
            except ImportError:
                logger.debug("Sentry SDK not installed, skipping exception capture")
            except Exception as sentry_error:
                logger.debug(f"Sentry capture failed (non-critical): {sentry_error}")

    def _publish_failed_event_to_pubsub(self, error: Exception):
        """
        Publish failed scraper event to Pub/Sub.

        Even failures are published so Phase 2 can track missing data
        and potentially retry or alert.
        """
        try:
            from scrapers.utils.pubsub_utils import ScraperPubSubPublisher

            publisher = ScraperPubSubPublisher()

            message_id = publisher.publish_completion_event(
                scraper_name=self._get_scraper_name(),
                execution_id=self.run_id,
                status='failed',
                gcs_path=None,
                record_count=0,
                duration_seconds=self.stats.get('total_runtime', 0),
                workflow=self.opts.get('workflow', 'MANUAL'),
                error_message=str(error)[:1000],  # Truncate long errors
                metadata={
                    'scraper_class': self.__class__.__name__,
                    'error_type': error.__class__.__name__
                }
            )

            if message_id:
                logger.info(f"✅ Phase 2 notified of failure (message_id: {message_id})")

        except ImportError:
            # google-cloud-pubsub not installed - this is expected in some environments
            logger.debug("google-cloud-pubsub not installed, skipping failure event publication")
        except Exception as e:
            logger.error(f"Failed to publish failure event to Pub/Sub: {e}")
