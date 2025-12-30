"""
Cloud Logging Service for Admin Dashboard

Queries Cloud Logging for errors and scheduler history.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List
from google.cloud import logging as cloud_logging
from google.cloud.logging_v2 import DESCENDING

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


class LoggingService:
    """Service for querying Cloud Logging."""

    def __init__(self):
        self.client = cloud_logging.Client(project=PROJECT_ID)

    def get_recent_errors(self, limit: int = 20, hours: int = 6) -> List[Dict]:
        """
        Get recent errors from Cloud Run services.

        Returns list of error entries with timestamp, service, and message.
        """
        try:
            # Calculate time filter
            start_time = datetime.utcnow() - timedelta(hours=hours)
            time_filter = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Build filter for Cloud Run errors
            log_filter = (
                f'resource.type="cloud_run_revision" '
                f'AND severity>=ERROR '
                f'AND timestamp>="{time_filter}"'
            )

            entries = []
            for entry in self.client.list_entries(
                filter_=log_filter,
                order_by=DESCENDING,
                max_results=limit
            ):
                # Extract relevant info
                service = 'unknown'
                if entry.resource and entry.resource.labels:
                    service = entry.resource.labels.get('service_name', 'unknown')

                message = ''
                if entry.payload:
                    if isinstance(entry.payload, str):
                        message = entry.payload
                    elif isinstance(entry.payload, dict):
                        message = entry.payload.get('message', str(entry.payload))
                    else:
                        message = str(entry.payload)

                # Truncate long messages
                if len(message) > 500:
                    message = message[:500] + '...'

                entries.append({
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                    'service': service,
                    'severity': entry.severity if entry.severity else 'ERROR',
                    'message': message,
                    'insert_id': entry.insert_id
                })

            return entries

        except Exception as e:
            logger.error(f"Error querying Cloud Logging for errors: {e}")
            return []

    def get_scheduler_history(self, hours: int = 12) -> List[Dict]:
        """
        Get Cloud Scheduler job execution history.

        Returns list of scheduler runs with job name, time, and status.
        """
        try:
            # Calculate time filter
            start_time = datetime.utcnow() - timedelta(hours=hours)
            time_filter = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')

            # Build filter for scheduler jobs
            log_filter = (
                f'resource.type="cloud_scheduler_job" '
                f'AND timestamp>="{time_filter}"'
            )

            entries = []
            seen_jobs = {}  # Track unique job runs

            for entry in self.client.list_entries(
                filter_=log_filter,
                order_by=DESCENDING,
                max_results=100
            ):
                # Extract job info
                job_id = 'unknown'
                if entry.resource and entry.resource.labels:
                    job_id = entry.resource.labels.get('job_id', 'unknown')

                # Skip if we've already seen this job at this time
                key = f"{job_id}_{entry.timestamp.minute if entry.timestamp else 0}"
                if key in seen_jobs:
                    continue
                seen_jobs[key] = True

                # Determine status from message
                status = 'unknown'
                message = str(entry.payload) if entry.payload else ''

                if 'success' in message.lower() or entry.severity == 'INFO':
                    status = 'success'
                elif 'error' in message.lower() or entry.severity in ['ERROR', 'CRITICAL']:
                    status = 'error'
                else:
                    status = 'triggered'

                entries.append({
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                    'job_id': job_id,
                    'status': status,
                    'message': message[:200] if message else ''
                })

            # Sort by timestamp descending and limit
            entries.sort(key=lambda x: x['timestamp'] or '', reverse=True)
            return entries[:50]

        except Exception as e:
            logger.error(f"Error querying Cloud Logging for scheduler history: {e}")
            return []

    def get_function_errors(self, function_name: str, hours: int = 6) -> List[Dict]:
        """Get errors for a specific Cloud Function."""
        try:
            start_time = datetime.utcnow() - timedelta(hours=hours)
            time_filter = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')

            log_filter = (
                f'resource.type="cloud_function" '
                f'AND resource.labels.function_name="{function_name}" '
                f'AND severity>=ERROR '
                f'AND timestamp>="{time_filter}"'
            )

            entries = []
            for entry in self.client.list_entries(
                filter_=log_filter,
                order_by=DESCENDING,
                max_results=20
            ):
                message = str(entry.payload) if entry.payload else ''
                entries.append({
                    'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                    'function': function_name,
                    'message': message[:500] if message else ''
                })

            return entries

        except Exception as e:
            logger.error(f"Error querying function errors: {e}")
            return []
