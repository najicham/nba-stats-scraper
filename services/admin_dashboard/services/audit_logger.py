"""
Audit Logging Service for Admin Dashboard

Logs administrative actions to BigQuery for compliance and debugging.
"""

import os
import sys
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud import bigquery

# Add project root to path for shared imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from shared.utils.bigquery_batch_writer import get_batch_writer

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Logs administrative actions to BigQuery audit_logs table.

    Provides audit trail for all administrative actions including:
    - Trigger executions
    - Manual retries
    - Configuration changes
    """

    def __init__(self):
        """Initialize audit logger with BigQuery client."""
        self.project_id = os.environ.get('GCP_PROJECT_ID')
        self.dataset = 'nba_pipeline'
        self.table = 'admin_audit_logs'
        self._client = None

    @property
    def client(self):
        """Lazy-load BigQuery client."""
        if self._client is None:
            self._client = bigquery.Client(project=self.project_id)
        return self._client

    def _get_api_key_hash(self) -> str:
        """
        Get a hash of the API key for logging (not the actual key).

        Uses first 8 chars of SHA256 hash for identification without
        exposing the actual key.
        """
        from flask import request
        api_key = request.headers.get('X-API-Key', '')
        if not api_key:
            api_key = request.args.get('api_key', 'unknown')
        return hashlib.sha256(api_key.encode()).hexdigest()[:8]

    def log_action(
        self,
        action_type: str,
        action_details: dict,
        success: bool,
        error_message: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> bool:
        """
        Log an administrative action to BigQuery using BigQueryBatchWriter.

        Args:
            action_type: Type of action (e.g., 'force_predictions', 'retry_phase')
            action_details: Dictionary with action-specific details
            success: Whether the action succeeded
            error_message: Error message if action failed
            ip_address: Client IP address
            user_agent: Client user agent string

        Returns:
            True if log was written successfully
        """
        try:
            from flask import request
            import json

            table_id = f"{self.dataset}.{self.table}"

            row = {
                'timestamp': datetime.now(ZoneInfo('UTC')).isoformat(),
                'action_type': action_type,
                'action_details': json.dumps(action_details),
                'success': success,
                'error_message': error_message,
                'api_key_hash': self._get_api_key_hash(),
                'ip_address': ip_address or request.remote_addr,
                'user_agent': user_agent or request.headers.get('User-Agent', 'unknown'),
            }

            # Use BigQueryBatchWriter for efficient batched writes
            writer = get_batch_writer(table_id, project_id=self.project_id)
            writer.add_record(row)
            # Flush immediately for audit logs to ensure immediate visibility
            writer.flush()

            logger.info(f"Audit log: {action_type} - success={success}")
            return True

        except Exception as e:
            logger.error(f"Error writing audit log: {e}", exc_info=True)
            return False

    def get_recent_logs(self, limit: int = 50, hours: int = 24) -> list:
        """
        Get recent audit logs.

        Args:
            limit: Maximum number of logs to return
            hours: How many hours back to look

        Returns:
            List of audit log entries
        """
        try:
            since = datetime.now(ZoneInfo('UTC')) - timedelta(hours=hours)

            query = f"""
                SELECT
                    timestamp,
                    action_type,
                    action_details,
                    success,
                    error_message,
                    api_key_hash,
                    ip_address,
                    user_agent
                FROM `{self.project_id}.{self.dataset}.{self.table}`
                WHERE timestamp >= @since
                ORDER BY timestamp DESC
                LIMIT @limit
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("since", "TIMESTAMP", since),
                    bigquery.ScalarQueryParameter("limit", "INT64", limit),
                ]
            )

            results = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"Error fetching audit logs: {e}", exc_info=True)
            return []

    def get_logs_by_action_type(self, action_type: str, limit: int = 50) -> list:
        """
        Get audit logs filtered by action type.

        Args:
            action_type: Type of action to filter for
            limit: Maximum number of logs to return

        Returns:
            List of audit log entries
        """
        try:
            query = f"""
                SELECT
                    timestamp,
                    action_type,
                    action_details,
                    success,
                    error_message,
                    api_key_hash,
                    ip_address,
                    user_agent
                FROM `{self.project_id}.{self.dataset}.{self.table}`
                WHERE action_type = @action_type
                ORDER BY timestamp DESC
                LIMIT @limit
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("action_type", "STRING", action_type),
                    bigquery.ScalarQueryParameter("limit", "INT64", limit),
                ]
            )

            results = self.client.query(query, job_config=job_config).result()
            return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"Error fetching audit logs by type: {e}", exc_info=True)
            return []

    def get_audit_summary(self, hours: int = 24) -> dict:
        """
        Get summary of audit activity.

        Args:
            hours: How many hours back to summarize

        Returns:
            Dictionary with summary statistics
        """
        try:
            since = datetime.now(ZoneInfo('UTC')) - timedelta(hours=hours)

            query = f"""
                SELECT
                    action_type,
                    COUNT(*) as count,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failure_count
                FROM `{self.project_id}.{self.dataset}.{self.table}`
                WHERE timestamp >= @since
                GROUP BY action_type
                ORDER BY count DESC
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("since", "TIMESTAMP", since),
                ]
            )

            results = self.client.query(query, job_config=job_config).result()

            summary = {
                'period_hours': hours,
                'actions': [],
                'total_count': 0,
                'total_success': 0,
                'total_failure': 0,
            }

            for row in results:
                action = {
                    'action_type': row['action_type'],
                    'count': row['count'],
                    'success_count': row['success_count'],
                    'failure_count': row['failure_count'],
                }
                summary['actions'].append(action)
                summary['total_count'] += row['count']
                summary['total_success'] += row['success_count']
                summary['total_failure'] += row['failure_count']

            return summary

        except Exception as e:
            logger.error(f"Error fetching audit summary: {e}", exc_info=True)
            return {
                'period_hours': hours,
                'actions': [],
                'total_count': 0,
                'total_success': 0,
                'total_failure': 0,
                'error': str(e),
            }


# Global audit logger instance
_audit_logger: AuditLogger = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
