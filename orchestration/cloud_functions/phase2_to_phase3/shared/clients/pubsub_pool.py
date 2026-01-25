"""
Pub/Sub Client Connection Pool

Provides thread-safe singleton pattern for Pub/Sub publisher and subscriber client
reuse across the application. Reduces connection overhead and resource usage.

Usage:
    from shared.clients.pubsub_pool import get_pubsub_publisher, get_pubsub_subscriber

    # Get cached publisher (or create if first time)
    publisher = get_pubsub_publisher()

    # Publish a message
    topic_path = publisher.topic_path(project_id, topic_name)
    future = publisher.publish(topic_path, data=b"message")

    # Get cached subscriber (or create if first time)
    subscriber = get_pubsub_subscriber()

Features:
- Thread-safe singleton pattern
- Lazy initialization (clients created on first use)
- Per-project client caching
- Automatic cleanup on application shutdown
- Compatible with all existing Pub/Sub code
"""

import threading
import atexit
import logging
from typing import Dict, Optional

from google.cloud import pubsub_v1

from shared.config.gcp_config import get_project_id as _get_default_project_id

logger = logging.getLogger(__name__)

# Global client caches (thread-safe)
_publisher_cache: Dict[str, pubsub_v1.PublisherClient] = {}
_subscriber_cache: Dict[str, pubsub_v1.SubscriberClient] = {}
_publisher_lock = threading.Lock()
_subscriber_lock = threading.Lock()


def get_pubsub_publisher(project_id: str = None) -> pubsub_v1.PublisherClient:
    """
    Get a cached Pub/Sub PublisherClient for the specified project.

    Creates a new client on first call for a given project, then reuses it
    for all subsequent calls. Thread-safe for concurrent access.

    Args:
        project_id: GCP project ID (defaults to value from shared.config.gcp_config)

    Returns:
        pubsub_v1.PublisherClient: Cached or newly created publisher client

    Example:
        publisher = get_pubsub_publisher()
        topic_path = publisher.topic_path("my-project", "my-topic")
        future = publisher.publish(topic_path, data=b"Hello, World!")

    Thread Safety:
        Multiple threads can safely call this function concurrently.
        Each will receive the same client instance for a given project.

    Performance:
        - First call: ~100-300ms (creates client, authenticates)
        - Subsequent calls: <1ms (returns cached client)
    """
    if project_id is None:
        project_id = _get_default_project_id()

    # Fast path: client already exists (no lock needed for read)
    if project_id in _publisher_cache:
        return _publisher_cache[project_id]

    # Slow path: need to create client (acquire lock)
    with _publisher_lock:
        # Double-check: another thread may have created it while we waited
        if project_id in _publisher_cache:
            return _publisher_cache[project_id]

        # Create new client
        logger.info(f"Creating new Pub/Sub PublisherClient for project: {project_id}")

        client = pubsub_v1.PublisherClient()
        _publisher_cache[project_id] = client

        logger.info(
            f"Pub/Sub PublisherClient created and cached. "
            f"Total cached publishers: {len(_publisher_cache)}"
        )

        return client


def get_pubsub_subscriber(project_id: str = None) -> pubsub_v1.SubscriberClient:
    """
    Get a cached Pub/Sub SubscriberClient for the specified project.

    Creates a new client on first call for a given project, then reuses it
    for all subsequent calls. Thread-safe for concurrent access.

    Args:
        project_id: GCP project ID (defaults to value from shared.config.gcp_config)

    Returns:
        pubsub_v1.SubscriberClient: Cached or newly created subscriber client

    Example:
        subscriber = get_pubsub_subscriber()
        subscription_path = subscriber.subscription_path("my-project", "my-subscription")
        subscriber.pull(subscription=subscription_path, max_messages=10)

    Thread Safety:
        Multiple threads can safely call this function concurrently.
        Each will receive the same client instance for a given project.
    """
    if project_id is None:
        project_id = _get_default_project_id()

    # Fast path: client already exists (no lock needed for read)
    if project_id in _subscriber_cache:
        return _subscriber_cache[project_id]

    # Slow path: need to create client (acquire lock)
    with _subscriber_lock:
        # Double-check: another thread may have created it while we waited
        if project_id in _subscriber_cache:
            return _subscriber_cache[project_id]

        # Create new client
        logger.info(f"Creating new Pub/Sub SubscriberClient for project: {project_id}")

        client = pubsub_v1.SubscriberClient()
        _subscriber_cache[project_id] = client

        logger.info(
            f"Pub/Sub SubscriberClient created and cached. "
            f"Total cached subscribers: {len(_subscriber_cache)}"
        )

        return client


def close_all_clients():
    """
    Close all cached Pub/Sub clients.

    Called automatically on application shutdown via atexit.
    Can also be called manually for cleanup (e.g., in tests).

    Note: After calling this, the next get_pubsub_publisher/subscriber() call
    will create a new client.
    """
    with _publisher_lock:
        publisher_count = len(_publisher_cache)

        if publisher_count > 0:
            logger.info(f"Closing {publisher_count} cached Pub/Sub publisher(s)...")

            for cache_key, client in _publisher_cache.items():
                try:
                    # PublisherClient doesn't have a close() method in older versions
                    # Use shutdown if available
                    if hasattr(client, 'stop'):
                        client.stop()
                    logger.debug(f"Closed Pub/Sub publisher: {cache_key}")
                except Exception as e:
                    logger.warning(f"Error closing Pub/Sub publisher {cache_key}: {e}")

            _publisher_cache.clear()

    with _subscriber_lock:
        subscriber_count = len(_subscriber_cache)

        if subscriber_count > 0:
            logger.info(f"Closing {subscriber_count} cached Pub/Sub subscriber(s)...")

            for cache_key, client in _subscriber_cache.items():
                try:
                    client.close()
                    logger.debug(f"Closed Pub/Sub subscriber: {cache_key}")
                except Exception as e:
                    logger.warning(f"Error closing Pub/Sub subscriber {cache_key}: {e}")

            _subscriber_cache.clear()

    if publisher_count > 0 or subscriber_count > 0:
        logger.info("All Pub/Sub clients closed")


def get_publisher_count() -> int:
    """Get the number of cached Pub/Sub publisher clients."""
    return len(_publisher_cache)


def get_subscriber_count() -> int:
    """Get the number of cached Pub/Sub subscriber clients."""
    return len(_subscriber_cache)


def clear_cache():
    """
    Clear the client cache without closing clients.

    Warning: This leaves clients open but unreferenced. Only use in tests
    or when you know what you're doing. Prefer close_all_clients() instead.
    """
    with _publisher_lock:
        _publisher_cache.clear()
    with _subscriber_lock:
        _subscriber_cache.clear()


# Register cleanup on application shutdown
atexit.register(close_all_clients)


# Backward compatibility: Allow direct Client creation
PublisherClient = pubsub_v1.PublisherClient
SubscriberClient = pubsub_v1.SubscriberClient
