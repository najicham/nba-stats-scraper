# tests/unit/conftest.py
"""
Shared pytest configuration for unit tests.

This file ensures the project root is at the front of sys.path
to avoid namespace conflicts with test directories (e.g., tests/unit/predictions
conflicting with the predictions package).
"""
import sys
import os

import pytest

# Add project root to path FIRST to ensure proper import resolution
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root in sys.path:
    sys.path.remove(project_root)
sys.path.insert(0, project_root)


@pytest.fixture(autouse=True)
def _reset_global_caches():
    """Reset process-global caches between unit tests to prevent cross-test
    pollution.

    `shared.clients.bigquery_pool._client_cache` caches one BigQuery client per
    project_id for the life of the process. Exporter tests patch
    `bigquery.Client` and rely on their own mock being constructed — but the
    FIRST test to build an exporter caches its mock, and every later test then
    reuses that stale client instead of its own (returning empty results and
    failing). Clearing the cache before each test forces each test's fresh mock
    to be used. Same rationale for the champion-model cache.

    Safe in production terms: real code simply re-creates the client on the next
    call. Guarded so tests still run if these modules are unavailable.
    """
    try:
        from shared.clients import bigquery_pool
        bigquery_pool._client_cache.clear()
    except Exception:
        pass
    try:
        from shared.config import model_selection
        model_selection._champion_cache.update({'model_id': None, 'expires': 0})
    except Exception:
        pass
    yield
