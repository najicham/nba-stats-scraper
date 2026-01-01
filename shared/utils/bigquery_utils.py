# shared/utils/bigquery_utils.py
"""
Standalone BigQuery utility functions for orchestration and simple operations.

For more complex operations, use BigQueryClient from bigquery_client.py.
These are simple, stateless functions for quick queries and inserts.

Path: shared/utils/bigquery_utils.py
"""

import logging
from typing import List, Dict, Any, Optional
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

logger = logging.getLogger(__name__)

# Default project ID (can be overridden)
DEFAULT_PROJECT_ID = "nba-props-platform"


def execute_bigquery(
    query: str,
    project_id: str = DEFAULT_PROJECT_ID,
    as_dict: bool = True
) -> List[Dict[str, Any]]:
    """
    Execute a BigQuery query and return results as list of dicts.
    
    Simple utility for orchestration queries where you don't need
    a managed client instance.
    
    Args:
        query: SQL query to execute
        project_id: GCP project ID
        as_dict: If True, return list of dicts. If False, return raw rows.
        
    Returns:
        List of dictionaries with query results (empty list on error)
        
    Example:
        >>> query = "SELECT * FROM `project.dataset.table` WHERE date = '2024-01-15'"
        >>> results = execute_bigquery(query)
        >>> for row in results:
        ...     print(row['column_name'])
    """
    try:
        client = bigquery.Client(project=project_id)
        query_job = client.query(query)
        # Wait for completion with timeout to prevent indefinite hangs
        results = query_job.result(timeout=60)

        if as_dict:
            # Convert to list of dictionaries
            return [dict(row) for row in results]
        else:
            return list(results)
            
    except Exception as e:
        logger.error(f"BigQuery query failed: {e}")
        logger.debug(f"Failed query: {query}")
        return []


def insert_bigquery_rows(
    table_id: str,
    rows: List[Dict[str, Any]],
    project_id: str = DEFAULT_PROJECT_ID
) -> bool:
    """
    Insert rows into a BigQuery table.
    
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
            logger.error(f"Failed to insert rows into {table_id}: {load_job.errors}")
            return False

        logger.debug(f"Successfully inserted {len(rows)} rows into {table_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to insert rows into {table_id}: {e}")
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
        logger.error(f"Error checking if table exists: {e}")
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
        logger.error(f"Error getting row count: {e}")
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
        
    except Exception as e:
        logger.error(f"Parameterized query failed: {e}")
        logger.debug(f"Failed query: {query}, params: {params}")
        return []


def update_bigquery_rows(
    query: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> int:
    """
    Execute an UPDATE, DELETE, or other DML statement.
    
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
        client = bigquery.Client(project=project_id)
        query_job = client.query(query)
        # Wait for completion with timeout to prevent indefinite hangs
        result = query_job.result(timeout=60)

        # For DML statements, get number of affected rows
        if hasattr(result, 'num_dml_affected_rows'):
            return result.num_dml_affected_rows
        
        return 0
        
    except Exception as e:
        logger.error(f"DML query failed: {e}")
        logger.debug(f"Failed query: {query}")
        return 0


# Convenience functions for common orchestration queries

def get_last_scraper_run(
    scraper_name: str,
    workflow: Optional[str] = None,
    project_id: str = DEFAULT_PROJECT_ID
) -> Optional[Dict[str, Any]]:
    """
    Get the most recent execution record for a scraper.
    
    Args:
        scraper_name: Name of the scraper
        workflow: Optional workflow name to filter by
        project_id: GCP project ID
        
    Returns:
        Dictionary with last run info, or None if not found
        
    Example:
        >>> last_run = get_last_scraper_run("oddsa_events_his", workflow="morning_operations")
        >>> if last_run:
        ...     print(f"Last ran at: {last_run['triggered_at']}")
    """
    workflow_filter = f"AND workflow = '{workflow}'" if workflow else ""
    
    query = f"""
    SELECT *
    FROM `{project_id}.nba_orchestration.scraper_execution_log`
    WHERE scraper_name = '{scraper_name}'
    {workflow_filter}
    ORDER BY triggered_at DESC
    LIMIT 1
    """
    
    results = execute_bigquery(query, project_id)
    return results[0] if results else None


def get_last_workflow_decision(
    workflow_name: str,
    project_id: str = DEFAULT_PROJECT_ID
) -> Optional[Dict[str, Any]]:
    """
    Get the most recent decision for a workflow.
    
    Args:
        workflow_name: Name of the workflow
        project_id: GCP project ID
        
    Returns:
        Dictionary with last decision info, or None if not found
    """
    query = f"""
    SELECT *
    FROM `{project_id}.nba_orchestration.workflow_decisions`
    WHERE workflow_name = '{workflow_name}'
    ORDER BY decision_time DESC
    LIMIT 1
    """
    
    results = execute_bigquery(query, project_id)
    return results[0] if results else None
