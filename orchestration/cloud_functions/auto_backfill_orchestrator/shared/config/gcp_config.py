"""
GCP Configuration
=================
Centralized configuration for Google Cloud Platform settings.

Provides consistent access to project IDs, dataset names, and other
GCP-specific configuration across the platform.

Usage:
    # Option 1: Import the constant directly (recommended for module-level)
    from shared.config.gcp_config import GCP_PROJECT_ID

    # Option 2: Use the function (recommended when late evaluation needed)
    from shared.config.gcp_config import get_project_id
    project = get_project_id()

    # Option 3: Import from shared.config package
    from shared.config import GCP_PROJECT_ID

Version: 1.1
Created: 2026-01-24
Updated: 2026-01-23 - Added GCP_PROJECT_ID constant for direct import
"""

import os
from typing import Optional


# Default project ID (can be overridden via environment variables)
DEFAULT_PROJECT_ID = 'nba-props-platform'


def get_project_id() -> str:
    """
    Get the GCP project ID.

    Checks environment variables in order:
    1. GCP_PROJECT_ID (preferred/canonical)
    2. GCP_PROJECT (legacy, for backwards compatibility)
    3. Falls back to DEFAULT_PROJECT_ID

    Returns:
        GCP project ID string
    """
    return (
        os.environ.get('GCP_PROJECT_ID') or
        os.environ.get('GCP_PROJECT') or
        DEFAULT_PROJECT_ID
    )


# Canonical project ID constant - use this for direct imports
# This evaluates once at module load time.
# For dynamic evaluation (e.g., in tests that modify env vars), use get_project_id()
GCP_PROJECT_ID = get_project_id()


def get_dataset_id(dataset_name: str, project_id: Optional[str] = None) -> str:
    """
    Get fully qualified BigQuery dataset ID.

    Args:
        dataset_name: Dataset name (e.g., 'nba_raw', 'nba_analytics')
        project_id: Optional project ID override

    Returns:
        Fully qualified dataset ID (e.g., 'nba-props-platform.nba_raw')
    """
    project = project_id or get_project_id()
    return f"{project}.{dataset_name}"


def get_table_id(dataset_name: str, table_name: str, project_id: Optional[str] = None) -> str:
    """
    Get fully qualified BigQuery table ID.

    Args:
        dataset_name: Dataset name (e.g., 'nba_raw')
        table_name: Table name (e.g., 'nbac_schedule')
        project_id: Optional project ID override

    Returns:
        Fully qualified table ID (e.g., 'nba-props-platform.nba_raw.nbac_schedule')
    """
    project = project_id or get_project_id()
    return f"{project}.{dataset_name}.{table_name}"


# Common dataset names
class Datasets:
    """Standard dataset names used across the platform."""
    RAW = 'nba_raw'
    ANALYTICS = 'nba_analytics'
    PRECOMPUTE = 'nba_precompute'
    PREDICTIONS = 'nba_predictions'
    REFERENCE = 'nba_reference'
    ORCHESTRATION = 'nba_orchestration'
    ENRICHED = 'nba_enriched'
    GRADING = 'nba_grading'

    # MLB datasets
    MLB_RAW = 'mlb_raw'
    MLB_ANALYTICS = 'mlb_analytics'
    MLB_PRECOMPUTE = 'mlb_precompute'
    MLB_PREDICTIONS = 'mlb_predictions'


# Common GCS bucket names
class Buckets:
    """Standard GCS bucket names."""
    API = 'nba-props-platform-api'
    DATA = 'nba-props-platform-data'
    BACKUPS = 'nba-props-platform-backups'
    EXPORTS = 'nba-props-platform-exports'


# Cloud Run/Function regions
class Regions:
    """Standard GCP regions."""
    PRIMARY = 'us-west2'
    SECONDARY = 'us-central1'
    FUNCTIONS = 'us-west2'


def get_gcs_bucket(bucket_type: str = 'api') -> str:
    """
    Get GCS bucket name.

    Args:
        bucket_type: One of 'api', 'data', 'backups', 'exports'

    Returns:
        Bucket name
    """
    bucket_map = {
        'api': Buckets.API,
        'data': Buckets.DATA,
        'backups': Buckets.BACKUPS,
        'exports': Buckets.EXPORTS,
    }
    return os.environ.get('GCS_BUCKET', bucket_map.get(bucket_type, Buckets.API))


def get_region() -> str:
    """Get the primary GCP region."""
    return os.environ.get('GCP_REGION', Regions.PRIMARY)
