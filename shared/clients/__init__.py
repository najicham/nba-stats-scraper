# shared/clients/__init__.py

"""
Shared Client Connection Pools

This module provides thread-safe singleton patterns for GCP client reuse across
the application. Using these pools instead of direct client instantiation reduces
connection overhead and resource usage by 40%+.

Available pools:
- BigQuery: get_bigquery_client()
- Firestore: get_firestore_client()
- Pub/Sub: get_pubsub_publisher(), get_pubsub_subscriber()
- Storage: get_storage_client()
- HTTP: get_http_session()

Usage:
    from shared.clients import get_bigquery_client, get_firestore_client

    # Get cached clients
    bq_client = get_bigquery_client()
    fs_client = get_firestore_client()

    # Use normally - clients are reused across all calls
    results = bq_client.query("SELECT * FROM table LIMIT 10").result()
    doc = fs_client.collection("users").document("123").get()
"""

# BigQuery pool (always available — core dependency for all services)
from shared.clients.bigquery_pool import (
    get_bigquery_client,
    close_all_clients as close_all_bigquery_clients,
    get_client_count as get_bigquery_client_count,
)

# Firestore pool (optional — not all services need google-cloud-firestore)
try:
    from shared.clients.firestore_pool import (
        get_firestore_client,
        close_all_clients as close_all_firestore_clients,
        get_client_count as get_firestore_client_count,
    )
except ImportError:
    def get_firestore_client(**kwargs):
        raise ImportError("google-cloud-firestore is not installed. Add it to requirements.txt if this service needs Firestore.")
    def close_all_firestore_clients(): pass
    def get_firestore_client_count(): return 0

# Pub/Sub pool (optional — not all services need google-cloud-pubsub)
try:
    from shared.clients.pubsub_pool import (
        get_pubsub_publisher,
        get_pubsub_subscriber,
        close_all_clients as close_all_pubsub_clients,
        get_publisher_count as get_pubsub_publisher_count,
        get_subscriber_count as get_pubsub_subscriber_count,
    )
except ImportError:
    def get_pubsub_publisher(**kwargs):
        raise ImportError("google-cloud-pubsub is not installed. Add it to requirements.txt if this service needs Pub/Sub.")
    def get_pubsub_subscriber(**kwargs):
        raise ImportError("google-cloud-pubsub is not installed. Add it to requirements.txt if this service needs Pub/Sub.")
    def close_all_pubsub_clients(): pass
    def get_pubsub_publisher_count(): return 0
    def get_pubsub_subscriber_count(): return 0

# Storage pool (optional — not all services need google-cloud-storage)
try:
    from shared.clients.storage_pool import (
        get_storage_client,
        close_all_clients as close_all_storage_clients,
        get_client_count as get_storage_client_count,
    )
except ImportError:
    def get_storage_client(**kwargs):
        raise ImportError("google-cloud-storage is not installed. Add it to requirements.txt if this service needs Storage.")
    def close_all_storage_clients(): pass
    def get_storage_client_count(): return 0

# HTTP pool (always available — uses stdlib/requests)
from shared.clients.http_pool import (
    get_http_session,
    close_all_sessions as close_all_http_sessions,
)


__all__ = [
    # BigQuery
    'get_bigquery_client',
    'close_all_bigquery_clients',
    'get_bigquery_client_count',

    # Firestore
    'get_firestore_client',
    'close_all_firestore_clients',
    'get_firestore_client_count',

    # Pub/Sub
    'get_pubsub_publisher',
    'get_pubsub_subscriber',
    'close_all_pubsub_clients',
    'get_pubsub_publisher_count',
    'get_pubsub_subscriber_count',

    # Storage
    'get_storage_client',
    'close_all_storage_clients',
    'get_storage_client_count',

    # HTTP
    'get_http_session',
    'close_all_http_sessions',
]


def close_all_clients():
    """Close all cached clients across all pools."""
    close_all_bigquery_clients()
    close_all_firestore_clients()
    close_all_pubsub_clients()
    close_all_storage_clients()
    close_all_http_sessions()
