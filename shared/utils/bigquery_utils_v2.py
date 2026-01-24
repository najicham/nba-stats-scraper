"""
BigQuery utility functions with Result pattern (v2).

This module provides Result-based versions of bigquery_utils functions,
eliminating silent failures and providing structured error information.

Migration Guide:
    # Old (silent failure):
    from shared.utils.bigquery_utils import execute_bigquery
    results = execute_bigquery(query)  # Returns [] on error
    if not results:  # Can't tell: no data vs error?
        ...

    # New (structured errors):
    from shared.utils.bigquery_utils_v2 import execute_bigquery_v2
    result = execute_bigquery_v2(query)
    if result.is_success:
        process_data(result.data)
    elif result.is_retryable:
        retry_later()
    else:
        alert(result.error.message)

Week 1 P0-1: Fixes 19 silent failure patterns across codebase
Week 2 Update: Added retry_with_jitter for transient failure resilience
Path: shared/utils/bigquery_utils_v2.py
"""

import logging
import os
from typing import List, Dict, Any, Optional
from google.cloud import bigquery
from google.cloud.exceptions import NotFound, Forbidden, BadRequest
from google.api_core.exceptions import ServiceUnavailable, DeadlineExceeded

from shared.utils.result import Result, ErrorType, classify_exception
from shared.utils.retry_with_jitter import retry_with_jitter
from shared.config.gcp_config import get_project_id

logger = logging.getLogger(__name__)

# Default project ID (uses centralized config)
DEFAULT_PROJECT_ID = get_project_id()

# Query caching feature flags (enabled by default for cost savings)
ENABLE_QUERY_CACHING = os.getenv('ENABLE_QUERY_CACHING', 'true').lower() == 'true'
QUERY_CACHE_TTL_SECONDS = int(os.getenv('QUERY_CACHE_TTL_SECONDS', '3600'))


@retry_with_jitter(
    max_attempts=3,
    base_delay=1.0,
    max_delay=15.0,
    exceptions=(ServiceUnavailable, DeadlineExceeded)
)
def _execute_bigquery_v2_internal(
    query: str,
    project_id: str,
    as_dict: bool,
    use_cache: Optional[bool]
) -> List[Dict[str, Any]]:
    """Internal function with retry logic for BigQuery queries."""
    from shared.clients import get_bigquery_client
    client = get_bigquery_client(project_id)

    # Configure query caching
    job_config = bigquery.QueryJobConfig()
    should_cache = use_cache if use_cache is not None else ENABLE_QUERY_CACHING

    if should_cache:
        job_config.use_query_cache = True
        logger.debug(f"Query caching enabled (TTL: {QUERY_CACHE_TTL_SECONDS}s)")
    else:
        job_config.use_query_cache = False

    query_job = client.query(query, job_config=job_config)
    results = query_job.result(timeout=60)

    # Log cache hit/miss for monitoring
    if should_cache and hasattr(query_job, 'cache_hit'):
        if query_job.cache_hit:
            logger.debug("✅ BigQuery cache HIT")
        else:
            logger.debug(f"❌ BigQuery cache MISS - {query_job.total_bytes_processed} bytes")

    return [dict(row) for row in results] if as_dict else list(results)


def execute_bigquery_v2(
    query: str,
    project_id: str = DEFAULT_PROJECT_ID,
    as_dict: bool = True,
    use_cache: Optional[bool] = None
) -> Result[List[Dict[str, Any]]]:
    """
    Execute a BigQuery query and return results with structured error handling.

    Week 2 Update: Now retries on transient failures (ServiceUnavailable, DeadlineExceeded).

    Args:
        query: SQL query to execute
        project_id: GCP project ID
        as_dict: If True, return list of dicts. If False, return raw rows.
        use_cache: Override caching (None = use feature flag)

    Returns:
        Result[List[Dict]]: Success with data or failure with error details

    Examples:
        >>> result = execute_bigquery_v2("SELECT * FROM table WHERE date = CURRENT_DATE()")
        >>> if result.is_success:
        ...     for row in result.data:
        ...         print(row['column_name'])
        >>> elif result.is_retryable:
        ...     # Transient error, retry later
        ...     schedule_retry()
        >>> else:
        ...     # Permanent error, alert
        ...     send_alert(f"Query failed: {result.error.message}")
    """
    try:
        data = _execute_bigquery_v2_internal(query, project_id, as_dict, use_cache)
        return Result.success(data)
    except NotFound as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Table or dataset not found",
            exception=e,
            details={"query": query[:200], "project_id": project_id}
        )
    except Forbidden as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Permission denied",
            exception=e,
            details={"query": query[:200], "project_id": project_id}
        )
    except BadRequest as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Invalid query syntax",
            exception=e,
            details={"query": query[:200]}
        )
    except Exception as e:
        error_type = classify_exception(e)
        return Result.failure(
            error_type=error_type,
            message=f"BigQuery query execution failed: {str(e)[:100]}",
            exception=e,
            details={"query": query[:200], "project_id": project_id}
        )


def insert_bigquery_rows_v2(
    table_id: str,
    rows: List[Dict[str, Any]],
    project_id: str = DEFAULT_PROJECT_ID
) -> Result[int]:
    """
    Insert rows into a BigQuery table with structured error handling.

    Args:
        table_id: Full table ID (format: "project.dataset.table" or "dataset.table")
        rows: List of dictionaries to insert
        project_id: GCP project ID

    Returns:
        Result[int]: Success with row count or failure with error details

    Examples:
        >>> rows = [{"name": "test", "value": 123}]
        >>> result = insert_bigquery_rows_v2("dataset.table", rows)
        >>> if result.is_success:
        ...     print(f"Inserted {result.data} rows")
        >>> else:
        ...     logger.error(f"Insert failed: {result.error.message}", exc_info=True)
    """
    if not rows:
        logger.warning("No rows to insert")
        return Result.success(0)

    try:
        from shared.clients import get_bigquery_client
    client = get_bigquery_client(project_id)

        # Ensure table_id has project prefix
        if not table_id.startswith(f"{project_id}."):
            table_id = f"{project_id}.{table_id}"

        # Get table reference for schema
        table_ref = client.get_table(table_id)

        job_config = bigquery.LoadJobConfig(
            schema=table_ref.schema,
            autodetect=False,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            ignore_unknown_values=True
        )

        load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
        load_job.result(timeout=60)

        if load_job.errors:
            logger.error(f"BigQuery load errors: {load_job.errors[:3]}", exc_info=True)
            return Result.failure(
                error_type=ErrorType.PERMANENT,
                message=f"Failed to insert rows: {len(load_job.errors)} errors",
                details={
                    "table_id": table_id,
                    "row_count": len(rows),
                    "errors": load_job.errors[:5]
                }
            )

        logger.debug(f"Successfully inserted {len(rows)} rows into {table_id}")
        return Result.success(len(rows))

    except NotFound as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message=f"Table not found: {table_id}",
            exception=e,
            details={"table_id": table_id, "row_count": len(rows)}
        )
    except BadRequest as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Invalid row data or schema mismatch",
            exception=e,
            details={"table_id": table_id, "sample_row": rows[0] if rows else None}
        )
    except Exception as e:
        error_type = classify_exception(e)
        return Result.failure(
            error_type=error_type,
            message=f"Failed to insert rows: {str(e)[:100]}",
            exception=e,
            details={"table_id": table_id, "row_count": len(rows)}
        )


def get_table_row_count_v2(
    table_id: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> Result[int]:
    """
    Get the number of rows in a BigQuery table with structured error handling.

    Args:
        table_id: Table ID (format: "dataset.table" or "project.dataset.table")
        project_id: GCP project ID

    Returns:
        Result[int]: Success with row count or failure with error details

    Examples:
        >>> result = get_table_row_count_v2("dataset.table")
        >>> if result.is_success:
        ...     print(f"Table has {result.data} rows")
        >>> elif result.error.type == ErrorType.PERMANENT:
        ...     print("Table doesn't exist or no access")
    """
    try:
        from shared.clients import get_bigquery_client
    client = get_bigquery_client(project_id)

        # Ensure table_id has project prefix
        if not table_id.startswith(f"{project_id}."):
            table_id = f"{project_id}.{table_id}"

        table = client.get_table(table_id)
        return Result.success(table.num_rows)

    except NotFound as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message=f"Table not found: {table_id}",
            exception=e,
            details={"table_id": table_id}
        )
    except Forbidden as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message=f"Permission denied for table: {table_id}",
            exception=e,
            details={"table_id": table_id}
        )
    except Exception as e:
        error_type = classify_exception(e)
        return Result.failure(
            error_type=error_type,
            message=f"Failed to get row count: {str(e)[:100]}",
            exception=e,
            details={"table_id": table_id}
        )


def execute_bigquery_with_params_v2(
    query: str,
    params: Dict[str, Any],
    project_id: str = DEFAULT_PROJECT_ID
) -> Result[List[Dict[str, Any]]]:
    """
    Execute a parameterized BigQuery query with structured error handling.

    Args:
        query: SQL query with @param_name placeholders
        params: Dictionary of parameter names to values
        project_id: GCP project ID

    Returns:
        Result[List[Dict]]: Success with data or failure with error details

    Examples:
        >>> query = "SELECT * FROM table WHERE date = @target_date"
        >>> params = {"target_date": "2024-01-15"}
        >>> result = execute_bigquery_with_params_v2(query, params)
        >>> if result.is_success:
        ...     process(result.data)
    """
    try:
        from shared.clients import get_bigquery_client
    client = get_bigquery_client(project_id)

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
        results = query_job.result(timeout=60)

        data = [dict(row) for row in results]
        return Result.success(data)

    except BadRequest as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Invalid query or parameter type mismatch",
            exception=e,
            details={"query": query[:200], "params": params}
        )
    except Exception as e:
        error_type = classify_exception(e)
        return Result.failure(
            error_type=error_type,
            message=f"Parameterized query failed: {str(e)[:100]}",
            exception=e,
            details={"query": query[:200], "param_names": list(params.keys())}
        )


def update_bigquery_rows_v2(
    query: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> Result[int]:
    """
    Execute a DML statement (UPDATE/DELETE/MERGE) with structured error handling.

    Args:
        query: DML query (UPDATE, DELETE, MERGE, etc.)
        project_id: GCP project ID

    Returns:
        Result[int]: Success with affected row count or failure with error details

    Examples:
        >>> query = "UPDATE dataset.table SET status = 'done' WHERE id = 123"
        >>> result = update_bigquery_rows_v2(query)
        >>> if result.is_success:
        ...     print(f"Updated {result.data} rows")
        >>> else:
        ...     logger.error(f"DML failed: {result.error.message}", exc_info=True)
    """
    try:
        from shared.clients import get_bigquery_client
    client = get_bigquery_client(project_id)
        query_job = client.query(query)
        result = query_job.result(timeout=60)

        # For DML statements, get number of affected rows
        affected_rows = 0
        if hasattr(result, 'num_dml_affected_rows'):
            affected_rows = result.num_dml_affected_rows

        return Result.success(affected_rows)

    except BadRequest as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Invalid DML syntax",
            exception=e,
            details={"query": query[:200]}
        )
    except Exception as e:
        error_type = classify_exception(e)
        return Result.failure(
            error_type=error_type,
            message=f"DML query failed: {str(e)[:100]}",
            exception=e,
            details={"query": query[:200]}
        )


def table_exists_v2(
    table_id: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> Result[bool]:
    """
    Check if a BigQuery table exists with structured error handling.

    Args:
        table_id: Table ID (format: "dataset.table" or "project.dataset.table")
        project_id: GCP project ID

    Returns:
        Result[bool]: Success with existence boolean or failure with error details

    Examples:
        >>> result = table_exists_v2("dataset.table")
        >>> if result.is_success:
        ...     if result.data:
        ...         print("Table exists")
        ...     else:
        ...         print("Table doesn't exist")
        >>> else:
        ...     print(f"Error checking: {result.error.message}")
    """
    try:
        from shared.clients import get_bigquery_client
    client = get_bigquery_client(project_id)

        # Ensure table_id has project prefix
        if not table_id.startswith(f"{project_id}."):
            table_id = f"{project_id}.{table_id}"

        client.get_table(table_id)
        return Result.success(True)

    except NotFound:
        # NotFound is not an error, it's a valid answer (table doesn't exist)
        return Result.success(False)

    except Forbidden as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message=f"Permission denied for table: {table_id}",
            exception=e,
            details={"table_id": table_id}
        )
    except Exception as e:
        error_type = classify_exception(e)
        return Result.failure(
            error_type=error_type,
            message=f"Failed to check table existence: {str(e)[:100]}",
            exception=e,
            details={"table_id": table_id}
        )
