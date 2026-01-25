"""
Shared Database Client Pool

Reuses BigQuery and Firestore clients across the admin dashboard
to avoid repeated initialization overhead.

Usage:
    from services.admin_dashboard.services.client_pool import get_bigquery_client, get_firestore_client

    bq_client = get_bigquery_client()
    fs_client = get_firestore_client()
"""

import os
import logging
from typing import Optional
from google.cloud import bigquery, firestore

logger = logging.getLogger(__name__)

# Module-level singleton clients
_bigquery_client: Optional[bigquery.Client] = None
_firestore_client: Optional[firestore.Client] = None

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


def get_bigquery_client(project_id: Optional[str] = None) -> bigquery.Client:
    """
    Get or create a shared BigQuery client.

    Reuses the same client instance across requests to avoid
    repeated initialization overhead.

    Args:
        project_id: Optional project ID (defaults to GCP_PROJECT_ID env var)

    Returns:
        bigquery.Client instance
    """
    global _bigquery_client

    if _bigquery_client is None:
        pid = project_id or PROJECT_ID
        _bigquery_client = bigquery.Client(project=pid)
        logger.info(f"Initialized shared BigQuery client for project: {pid}")

    return _bigquery_client


def get_firestore_client(project_id: Optional[str] = None) -> firestore.Client:
    """
    Get or create a shared Firestore client.

    Reuses the same client instance across requests to avoid
    repeated initialization overhead.

    Args:
        project_id: Optional project ID (defaults to GCP_PROJECT_ID env var)

    Returns:
        firestore.Client instance
    """
    global _firestore_client

    if _firestore_client is None:
        pid = project_id or PROJECT_ID
        _firestore_client = firestore.Client(project=pid)
        logger.info(f"Initialized shared Firestore client for project: {pid}")

    return _firestore_client


def reset_clients():
    """
    Reset client instances (for testing or manual refresh).

    Closes existing clients and creates new ones on next access.
    """
    global _bigquery_client, _firestore_client

    if _bigquery_client:
        _bigquery_client.close()
        _bigquery_client = None

    # Firestore client doesn't have explicit close method
    _firestore_client = None

    logger.info("Reset all shared database clients")
