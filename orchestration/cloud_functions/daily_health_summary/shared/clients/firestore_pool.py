"""
Firestore Client Connection Pool

Provides thread-safe singleton pattern for Firestore client reuse across the application.
Reduces connection overhead and resource usage.

Usage:
    from shared.clients.firestore_pool import get_firestore_client

    # Get cached client (or create if first time)
    client = get_firestore_client()

    # Use client normally
    doc_ref = client.collection("users").document("user123")
    doc = doc_ref.get()

Features:
- Thread-safe singleton pattern
- Lazy initialization (client created on first use)
- Per-project client caching
- Automatic cleanup on application shutdown
- Compatible with all existing Firestore code
"""

import threading
import atexit
import logging
from typing import Dict, Optional

from google.cloud import firestore

from shared.config.gcp_config import get_project_id as _get_default_project_id

logger = logging.getLogger(__name__)

# Global client cache (thread-safe)
_client_cache: Dict[str, firestore.Client] = {}
_cache_lock = threading.Lock()


def get_firestore_client(project_id: str = None, database: str = None) -> firestore.Client:
    """
    Get a cached Firestore client for the specified project.

    Creates a new client on first call for a given project/database, then reuses it
    for all subsequent calls. Thread-safe for concurrent access.

    Args:
        project_id: GCP project ID (defaults to value from shared.config.gcp_config)
        database: Firestore database ID (defaults to "(default)")

    Returns:
        firestore.Client: Cached or newly created Firestore client

    Example:
        client = get_firestore_client()
        doc_ref = client.collection("users").document("user123")
        doc = doc_ref.get()

    Thread Safety:
        Multiple threads can safely call this function concurrently.
        Each will receive the same client instance for a given project/database.

    Performance:
        - First call: ~100-300ms (creates client, authenticates)
        - Subsequent calls: <1ms (returns cached client)
    """
    if project_id is None:
        project_id = _get_default_project_id()

    cache_key = f"{project_id}:{database}" if database else project_id

    # Fast path: client already exists (no lock needed for read)
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    # Slow path: need to create client (acquire lock)
    with _cache_lock:
        # Double-check: another thread may have created it while we waited
        if cache_key in _client_cache:
            return _client_cache[cache_key]

        # Create new client
        logger.info(f"Creating new Firestore client for project: {project_id}")

        kwargs = {"project": project_id}
        if database:
            kwargs["database"] = database

        client = firestore.Client(**kwargs)
        _client_cache[cache_key] = client

        logger.info(
            f"Firestore client created and cached. "
            f"Total cached clients: {len(_client_cache)}"
        )

        return client


def close_all_clients():
    """
    Close all cached Firestore clients.

    Called automatically on application shutdown via atexit.
    Can also be called manually for cleanup (e.g., in tests).

    Note: After calling this, the next get_firestore_client() call
    will create a new client.
    """
    with _cache_lock:
        client_count = len(_client_cache)

        if client_count == 0:
            return

        logger.info(f"Closing {client_count} cached Firestore client(s)...")

        for cache_key, client in _client_cache.items():
            try:
                client.close()
                logger.debug(f"Closed Firestore client: {cache_key}")
            except Exception as e:
                logger.warning(f"Error closing Firestore client {cache_key}: {e}")

        _client_cache.clear()
        logger.info("All Firestore clients closed")


def get_client_count() -> int:
    """
    Get the number of cached Firestore clients.

    Useful for monitoring and debugging.

    Returns:
        int: Number of clients currently in the cache
    """
    return len(_client_cache)


def clear_cache():
    """
    Clear the client cache without closing clients.

    Warning: This leaves clients open but unreferenced. Only use in tests
    or when you know what you're doing. Prefer close_all_clients() instead.
    """
    with _cache_lock:
        _client_cache.clear()


# Register cleanup on application shutdown
atexit.register(close_all_clients)


# Backward compatibility: Allow direct Client creation
Client = firestore.Client
