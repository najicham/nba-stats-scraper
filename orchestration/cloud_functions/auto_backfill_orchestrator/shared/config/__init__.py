"""
Shared configuration.

This module provides centralized configuration for the NBA Props Platform.

GCP Project ID:
    from shared.config import GCP_PROJECT_ID
    # or
    from shared.config import get_project_id
    project = get_project_id()

Note: GCP_PROJECT_ID reads from environment variables with fallback:
    1. GCP_PROJECT_ID (canonical/preferred)
    2. GCP_PROJECT (legacy, for backwards compatibility)
    3. 'nba-props-platform' (default)
"""

from .pubsub_topics import TOPICS, PubSubTopics
from .gcp_config import GCP_PROJECT_ID, get_project_id, DEFAULT_PROJECT_ID

__all__ = [
    'TOPICS',
    'PubSubTopics',
    'GCP_PROJECT_ID',
    'get_project_id',
    'DEFAULT_PROJECT_ID',
]
