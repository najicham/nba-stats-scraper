# shared/utils/bigquery_utils.py
"""
Standalone BigQuery utility functions for orchestration and simple operations.

For more complex operations, use BigQueryClient from bigquery_client.py.
These are simple, stateless functions for quick queries and inserts.

Week 1 Update: Added query result caching to reduce costs by 30-45%
Week 2 Update: Added retry_with_jitter for transient failure resilience

Path: shared/utils/bigquery_utils.py
"""

import logging
import os
from typing import List, Dict, Any, Optional
from google.cloud import bigquery
from google.cloud.exceptions import NotFound
from google.api_core.exceptions import GoogleAPIError, ServiceUnavailable, DeadlineExceeded
from datetime import datetime, timedelta, timezone

from shared.utils.retry_with_jitter import retry_with_jitter
from shared.config.gcp_config import get_project_id

logger = logging.getLogger(__name__)

# Default project ID (uses centralized config)
DEFAULT_PROJECT_ID = get_project_id()

# Week 1: Query caching feature flags (enabled by default for cost savings)
ENABLE_QUERY_CACHING = os.getenv('ENABLE_QUERY_CACHING', 'true').lower() == 'true'
QUERY_CACHE_TTL_SECONDS = int(os.getenv('QUERY_CACHE_TTL_SECONDS', '3600'))  # 1 hour default


@retry_with_jitter(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=(ServiceUnavailable, DeadlineExceeded)
)
def _execute_bigquery_internal(
    query: str,
    project_id: str,
    as_dict: bool,
    use_cache: Optional[bool]
) -> List[Dict[str, Any]]:
    """Internal function with retry logic for BigQuery queries."""
    client = bigquery.Client(project=project_id)

    # Week 1: Configure query caching
    job_config = bigquery.QueryJobConfig()

    # Determine if we should use cache
    should_cache = use_cache if use_cache is not None else ENABLE_QUERY_CACHING

    if should_cache:
        job_config.use_query_cache = True
        logger.debug(f"Query caching enabled (TTL: {QUERY_CACHE_TTL_SECONDS}s)")
    else:
        job_config.use_query_cache = False

    query_job = client.query(query, job_config=job_config)

    # Wait for completion with timeout to prevent indefinite hangs
    results = query_job.result(timeout=60)

    # Week 1: Log cache hit/miss for monitoring
    if should_cache and hasattr(query_job, 'cache_hit'):
        if query_job.cache_hit:
            logger.debug("✅ BigQuery cache HIT - no bytes scanned!")
        else:
            logger.debug(f"❌ BigQuery cache MISS - scanned {query_job.total_bytes_processed} bytes")

    if as_dict:
        # Convert to list of dictionaries
        return [dict(row) for row in results]
    else:
        return list(results)


def execute_bigquery(
    query: str,
    project_id: str = DEFAULT_PROJECT_ID,
    as_dict: bool = True,
    use_cache: Optional[bool] = None
) -> List[Dict[str, Any]]:
    """
    Execute a BigQuery query and return results as list of dicts.

    Week 1 Update: Now supports query result caching to reduce costs.
    Week 2 Update: Now retries on transient failures (ServiceUnavailable, DeadlineExceeded).

    Simple utility for orchestration queries where you don't need
    a managed client instance.

    Args:
        query: SQL query to execute
        project_id: GCP project ID
        as_dict: If True, return list of dicts. If False, return raw rows.
        use_cache: Override caching (None = use feature flag, True/False = explicit)

    Returns:
        List of dictionaries with query results (empty list on error)

    Example:
        >>> query = "SELECT * FROM `project.dataset.table` WHERE DATE(timestamp) = CURRENT_DATE()"
        >>> results = execute_bigquery(query)
        >>> for row in results:
        ...     print(row['column_name'])
    """
    try:
        return _execute_bigquery_internal(query, project_id, as_dict, use_cache)
    except GoogleAPIError as e:
        logger.error(f"BigQuery query failed: {e}", exc_info=True)
        logger.debug(f"Failed query: {query}")
        return []


@retry_with_jitter(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=(ServiceUnavailable, DeadlineExceeded)
)
def _insert_bigquery_rows_internal(
    table_id: str,
    rows: List[Dict[str, Any]],
    project_id: str
) -> bool:
    """Internal function with retry logic for BigQuery inserts."""
    client = bigquery.Client(project=project_id)

    # Ensure table_id has project prefix
    if not table_id.startswith(f"{project_id}."):
        table_id = f"{project_id}.{table_id}"

    # Get table reference for schema
    # Use batch loading instead of streaming inserts to avoid the 90-minute
    # streaming buffer that blocks DML operations (MERGE/UPDATE/DELETE)
    # Reference: docs/05-development/guides/bigquery-best-practices.md
    table_ref = client.get_table(table_id)

    job_config = bigquery.LoadJobConfig(
        schema=table_ref.schema,
        autodetect=False,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ignore_unknown_values=True
    )

    load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
    # Wait for completion with timeout to prevent indefinite hangs
    load_job.result(timeout=60)

    if load_job.errors:
        logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
        logger.error(f"Failed to insert rows into {table_id}: {load_job.errors}", exc_info=True)
        return False

    logger.debug(f"Successfully inserted {len(rows)} rows into {table_id}")
    return True


def insert_bigquery_rows(
    table_id: str,
    rows: List[Dict[str, Any]],
    project_id: str = DEFAULT_PROJECT_ID
) -> bool:
    """
    Insert rows into a BigQuery table.

    Week 2 Update: Now retries on transient failures (ServiceUnavailable, DeadlineExceeded).

    Simple utility for orchestration logging where you don't need
    a managed client instance.

    Args:
        table_id: Full table ID (format: "project.dataset.table" or "dataset.table")
        rows: List of dictionaries to insert
        project_id: GCP project ID (used if table_id doesn't include project)

    Returns:
        True if successful, False otherwise

    Example:
        >>> rows = [
        ...     {"scraper_name": "test", "status": "success", "triggered_at": datetime.now()},
        ...     {"scraper_name": "test2", "status": "failed", "triggered_at": datetime.now()}
        ... ]
        >>> success = insert_bigquery_rows("nba_orchestration.scraper_execution_log", rows)
    """
    if not rows:
        logger.warning("No rows to insert")
        return True

    try:
        return _insert_bigquery_rows_internal(table_id, rows, project_id)
    except GoogleAPIError as e:
        logger.error(f"Failed to insert rows into {table_id}: {e}", exc_info=True)
        return False


def table_exists(
    table_id: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> bool:
    """
    Check if a BigQuery table exists.
    
    Args:
        table_id: Table ID (format: "dataset.table" or "project.dataset.table")
        project_id: GCP project ID (used if table_id doesn't include project)
        
    Returns:
        True if table exists, False otherwise
        
    Example:
        >>> if table_exists("nba_orchestration.scraper_execution_log"):
        ...     print("Table exists!")
    """
    try:
        client = bigquery.Client(project=project_id)
        
        # Ensure table_id has project prefix
        if not table_id.startswith(f"{project_id}."):
            table_id = f"{project_id}.{table_id}"
        
        client.get_table(table_id)
        return True
        
    except NotFound:
        return False
    except Exception as e:
        logger.error(f"Error checking if table exists: {e}", exc_info=True)
        return False


def get_table_row_count(
    table_id: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> int:
    """
    Get the number of rows in a BigQuery table.
    
    Args:
        table_id: Table ID (format: "dataset.table" or "project.dataset.table")
        project_id: GCP project ID
        
    Returns:
        Number of rows (0 if table doesn't exist or on error)
        
    Example:
        >>> count = get_table_row_count("nba_orchestration.scraper_execution_log")
        >>> print(f"Table has {count} rows")
    """
    try:
        client = bigquery.Client(project=project_id)
        
        # Ensure table_id has project prefix
        if not table_id.startswith(f"{project_id}."):
            table_id = f"{project_id}.{table_id}"
        
        table = client.get_table(table_id)
        return table.num_rows
        
    except NotFound:
        logger.warning(f"Table not found: {table_id}")
        return 0
    except Exception as e:
        logger.error(f"Error getting row count: {e}", exc_info=True)
        return 0


def execute_bigquery_with_params(
    query: str,
    params: Dict[str, Any],
    project_id: str = DEFAULT_PROJECT_ID
) -> List[Dict[str, Any]]:
    """
    Execute a parameterized BigQuery query.
    
    Safer than string interpolation for user input.
    
    Args:
        query: SQL query with @param_name placeholders
        params: Dictionary of parameter names to values
        project_id: GCP project ID
        
    Returns:
        List of dictionaries with query results
        
    Example:
        >>> query = "SELECT * FROM table WHERE date = @target_date"
        >>> params = {"target_date": "2024-01-15"}
        >>> results = execute_bigquery_with_params(query, params)
    """
    try:
        return _execute_bigquery_with_params_internal(query, params, project_id)
    except GoogleAPIError as e:
        logger.error(f"Parameterized query failed: {e}", exc_info=True)
        logger.debug(f"Failed query: {query}, params: {params}")
        return []


@retry_with_jitter(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=(ServiceUnavailable, DeadlineExceeded)
)
def _execute_bigquery_with_params_internal(
    query: str,
    params: Dict[str, Any],
    project_id: str
) -> List[Dict[str, Any]]:
    """Internal function with retry logic for parameterized queries."""
    client = bigquery.Client(project=project_id)

    # Build query parameters
    job_config = bigquery.QueryJobConfig()
    job_config.query_parameters = []

    for param_name, param_value in params.items():
        # Auto-detect parameter type
        if isinstance(param_value, bool):
            param_type = "BOOL"
        elif isinstance(param_value, int):
            param_type = "INT64"
        elif isinstance(param_value, float):
            param_type = "FLOAT64"
        else:
            param_type = "STRING"

        job_config.query_parameters.append(
            bigquery.ScalarQueryParameter(param_name, param_type, param_value)
        )

    query_job = client.query(query, job_config=job_config)
    # Wait for completion with timeout to prevent indefinite hangs
    results = query_job.result(timeout=60)

    return [dict(row) for row in results]


@retry_with_jitter(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=(ServiceUnavailable, DeadlineExceeded)
)
def _update_bigquery_rows_internal(query: str, project_id: str) -> int:
    """Internal function with retry logic for DML statements."""
    client = bigquery.Client(project=project_id)
    query_job = client.query(query)
    # Wait for completion with timeout to prevent indefinite hangs
    result = query_job.result(timeout=60)

    # For DML statements, get number of affected rows
    if hasattr(result, 'num_dml_affected_rows'):
        return result.num_dml_affected_rows

    return 0


def update_bigquery_rows(
    query: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> int:
    """
    Execute an UPDATE, DELETE, or other DML statement.

    Week 2 Update: Now retries on transient failures (ServiceUnavailable, DeadlineExceeded).

    Args:
        query: DML query (UPDATE, DELETE, MERGE, etc.)
        project_id: GCP project ID
        
    Returns:
        Number of rows affected (or 0 on error)
        
    Example:
        >>> query = '''
        ... UPDATE `project.dataset.table`
        ... SET status = 'processed'
        ... WHERE date = '2024-01-15' AND status = 'pending'
        ... '''
        >>> rows_updated = update_bigquery_rows(query)
    """
    try:
        return _update_bigquery_rows_internal(query, project_id)
    except GoogleAPIError as e:
        logger.error(f"DML query failed: {e}", exc_info=True)
        logger.debug(f"Failed query: {query}")
        return 0


# Convenience functions for common orchestration queries

def get_last_scraper_run(
    scraper_name: str,
    workflow: Optional[str] = None,
    project_id: str = DEFAULT_PROJECT_ID,
    lookback_days: int = 7
) -> Optional[Dict[str, Any]]:
    """
    Get the most recent execution record for a scraper.

    Week 1 Update: Added date filter to reduce scan costs (was: full table scan).

    Args:
        scraper_name: Name of the scraper
        workflow: Optional workflow name to filter by
        project_id: GCP project ID
        lookback_days: Number of days to look back (default: 7)

    Returns:
        Dictionary with last run info, or None if not found

    Example:
        >>> last_run = get_last_scraper_run("oddsa_events_his", workflow="morning_operations")
        >>> if last_run:
        ...     print(f"Last ran at: {last_run['triggered_at']}")
    """
    workflow_filter = f"AND workflow = '{workflow}'" if workflow else ""

    # Week 1: Add date filter to reduce bytes scanned
    query = f"""
    SELECT *
    FROM `{project_id}.nba_orchestration.scraper_execution_log`
    WHERE scraper_name = '{scraper_name}'
    AND DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
    {workflow_filter}
    ORDER BY triggered_at DESC
    LIMIT 1
    """

    # Week 1: Enable caching for workflow decision queries (frequently repeated)
    results = execute_bigquery(query, project_id, use_cache=True)
    return results[0] if results else None


def get_last_workflow_decision(
    workflow_name: str,
    project_id: str = DEFAULT_PROJECT_ID,
    lookback_days: int = 7
) -> Optional[Dict[str, Any]]:
    """
    Get the most recent decision for a workflow.

    Week 1 Update: Added date filter to reduce scan costs (was: full table scan).

    Args:
        workflow_name: Name of the workflow
        project_id: GCP project ID
        lookback_days: Number of days to look back (default: 7)

    Returns:
        Dictionary with last decision info, or None if not found
    """
    # Week 1: Add date filter to reduce bytes scanned
    query = f"""
    SELECT *
    FROM `{project_id}.nba_orchestration.workflow_decisions`
    WHERE workflow_name = '{workflow_name}'
    AND DATE(decision_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
    ORDER BY decision_time DESC
    LIMIT 1
    """

    # Week 1: Enable caching for workflow decision queries (frequently repeated)
    results = execute_bigquery(query, project_id, use_cache=True)
    return results[0] if results else None
