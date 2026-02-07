"""
BigQuery Client Connection Pool

Provides thread-safe singleton pattern for BigQuery client reuse across the application.
Reduces connection overhead and resource usage by up to 40%+.

Usage:
    from shared.clients.bigquery_pool import get_bigquery_client

    # Get cached client (or create if first time)
    client = get_bigquery_client()  # Uses default from shared.config.gcp_config

    # Use client normally
    query = "SELECT * FROM dataset.table LIMIT 10"
    results = client.query(query).result()

Features:
- Thread-safe singleton pattern
- Lazy initialization (clients created on first use)
- Per-project client caching
- Automatic cleanup on application shutdown
- Compatible with all existing BigQuery code

Reference:
- Design: docs/08-projects/current/pipeline-reliability-improvements/
         COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md (lines 775-849)
"""

import threading
import atexit
import logging
from typing import Dict, Optional
from google.cloud import bigquery

from shared.config.gcp_config import get_project_id as _get_default_project_id

logger = logging.getLogger(__name__)

# Global client cache (thread-safe)
_client_cache: Dict[str, bigquery.Client] = {}
_cache_lock = threading.Lock()


def get_bigquery_client(project_id: str = None, location: Optional[str] = None) -> bigquery.Client:
    """
    Get a cached BigQuery client for the specified project.

    Creates a new client on first call for a given project, then reuses it
    for all subsequent calls. Thread-safe for concurrent access.

    Args:
        project_id: GCP project ID (defaults to value from shared.config.gcp_config)
        location: Optional default location for datasets/jobs (e.g., "US", "us-west2")

    Returns:
        bigquery.Client: Cached or newly created BigQuery client

    Example:
        # In any module:
        client = get_bigquery_client()  # Uses default project

        # Same client instance will be returned on subsequent calls
        same_client = get_bigquery_client()
        assert client is same_client  # True!

    Thread Safety:
        Multiple threads can safely call this function concurrently.
        Each will receive the same client instance for a given project.

    Performance:
        - First call: ~200-500ms (creates client, authenticates)
        - Subsequent calls: <1ms (returns cached client)
        - Reduces per-query overhead from ~100ms to ~0ms
    """
    if project_id is None:
        project_id = _get_default_project_id()
    cache_key = f"{project_id}:{location}" if location else project_id

    # Fast path: client already exists (no lock needed for read)
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    # Slow path: need to create client (acquire lock)
    with _cache_lock:
        # Double-check: another thread may have created it while we waited
        if cache_key in _client_cache:
            return _client_cache[cache_key]

        # Create new client
        logger.info(f"Creating new BigQuery client for project: {project_id}")

        kwargs = {"project": project_id}
        if location:
            kwargs["location"] = location

        client = bigquery.Client(**kwargs)

        # Session 143: Increase HTTP connection pool for parallel queries.
        # Default urllib3 pool_maxsize=10 causes connection starvation when
        # running 11+ concurrent BigQuery queries (e.g., ML Feature Store).
        try:
            from requests.adapters import HTTPAdapter
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            if hasattr(client, '_connection') and hasattr(client._connection, 'http'):
                client._connection.http.mount("https://", adapter)
                logger.debug("Increased BQ client HTTP pool to 20 connections")
        except Exception as e:
            logger.debug(f"Could not increase HTTP pool size: {e}")

        _client_cache[cache_key] = client

        logger.info(
            f"BigQuery client created and cached. "
            f"Total cached clients: {len(_client_cache)}"
        )

        return client


def close_all_clients():
    """
    Close all cached BigQuery clients.

    Called automatically on application shutdown via atexit.
    Can also be called manually for cleanup (e.g., in tests).

    Note: After calling this, the next get_bigquery_client() call
    will create a new client.
    """
    with _cache_lock:
        client_count = len(_client_cache)

        if client_count == 0:
            return

        logger.info(f"Closing {client_count} cached BigQuery client(s)...")

        for cache_key, client in _client_cache.items():
            try:
                client.close()
                logger.debug(f"Closed BigQuery client: {cache_key}")
            except Exception as e:
                logger.warning(f"Error closing BigQuery client {cache_key}: {e}")

        _client_cache.clear()
        logger.info("All BigQuery clients closed")


def get_client_count() -> int:
    """
    Get the number of cached BigQuery clients.

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
# (for code that already does `from shared.clients.bigquery_pool import Client`)
Client = bigquery.Client


# Legacy function aliases (for gradual migration)
def get_client(project_id: str, location: Optional[str] = None) -> bigquery.Client:
    """
    Alias for get_bigquery_client() for backward compatibility.

    Deprecated: Use get_bigquery_client() instead.
    """
    import warnings
    warnings.warn(
        "get_client() is deprecated, use get_bigquery_client() instead",
        DeprecationWarning,
        stacklevel=2
    )
    return get_bigquery_client(project_id, location)


if __name__ == "__main__":
    # Demo: Show connection pooling behavior
    import time

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Demo: BigQuery Connection Pooling\n")
    print("=" * 60)

    # First call - creates client
    print("\nFirst call to get_bigquery_client()...")
    start = time.time()
    client1 = get_bigquery_client()  # Uses default from shared.config
    elapsed1 = (time.time() - start) * 1000
    print(f"Created client in {elapsed1:.2f}ms")

    # Second call - returns cached client
    print("\nSecond call to get_bigquery_client()...")
    start = time.time()
    client2 = get_bigquery_client()  # Uses default from shared.config
    elapsed2 = (time.time() - start) * 1000
    print(f"Retrieved cached client in {elapsed2:.2f}ms")

    # Verify same instance
    print(f"\nSame client instance? {client1 is client2}")
    print(f"Speedup: {elapsed1 / elapsed2:.0f}x faster")

    # Show cache stats
    print(f"\nCached clients: {get_client_count()}")

    # Cleanup
    print("\nClosing all clients...")
    close_all_clients()
    print(f"Cached clients after close: {get_client_count()}")
