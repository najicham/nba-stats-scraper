# predictions/worker/write_metrics.py
"""
BigQuery Write Metrics for Prediction Worker

Tracks metrics related to BigQuery write operations in the prediction worker,
including write attempts, DML rate limits, and batch consolidations.

Metrics are sent to Google Cloud Monitoring with the 'prediction_' prefix.

Self-Healing: This module also implements alerting and self-healing for DML
rate limit errors. When DML errors occur repeatedly, it can trigger alerts
and suggest concurrency reduction.
"""

import logging
import os
import time
import random
from typing import Optional, Callable, TypeVar
from collections import deque
from datetime import datetime, timedelta

from shared.utils.metrics_utils import send_metric, get_metrics_client

logger = logging.getLogger(__name__)

# Initialize metrics client with project ID
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# DML error tracking for self-healing
_dml_error_timestamps: deque = deque(maxlen=100)

T = TypeVar('T')


class PredictionWriteMetrics:
    """
    Static methods for tracking BigQuery write metrics in the prediction worker.

    All metrics are prefixed with 'prediction_' and sent to Cloud Monitoring.
    """

    @staticmethod
    def _ensure_client() -> bool:
        """
        Ensure the metrics client is initialized.

        Returns:
            True if client is available, False otherwise
        """
        client = get_metrics_client(PROJECT_ID)
        if client is None:
            logger.warning("Metrics client not available - metrics will not be sent")
            return False
        return True

    @staticmethod
    def track_write_attempt(
        player_lookup: str,
        records_count: int,
        success: bool,
        duration_seconds: float,
        error_type: Optional[str] = None
    ) -> bool:
        """
        Track a BigQuery write attempt for predictions.

        Sends metrics for:
        - prediction_write_attempts_total: Counter of write attempts
        - prediction_write_records_count: Number of records in the write
        - prediction_write_duration_seconds: Time taken for the write operation
        - prediction_write_errors_total: Counter of write errors (if failed)

        Args:
            player_lookup: Player identifier for labeling
            records_count: Number of prediction records being written
            success: Whether the write succeeded
            duration_seconds: Time taken for the write operation
            error_type: Type of error if the write failed (e.g., 'DMLRateLimitError')

        Returns:
            True if all metrics were sent successfully
        """
        if not PredictionWriteMetrics._ensure_client():
            return False

        all_success = True
        status = 'success' if success else 'failure'

        # Base labels for all metrics
        labels = {
            'player_lookup': player_lookup,
            'status': status
        }

        try:
            # Track write attempt count
            if not send_metric('prediction_write_attempts_total', 1, labels):
                logger.error(f"Failed to send prediction_write_attempts_total metric for {player_lookup}", exc_info=True)
                all_success = False

            # Track records count
            if not send_metric('prediction_write_records_count', records_count, labels):
                logger.error(f"Failed to send prediction_write_records_count metric for {player_lookup}", exc_info=True)
                all_success = False

            # Track duration
            if not send_metric('prediction_write_duration_seconds', duration_seconds, labels):
                logger.error(f"Failed to send prediction_write_duration_seconds metric for {player_lookup}", exc_info=True)
                all_success = False

            # Track errors if write failed
            if not success:
                error_labels = {
                    'player_lookup': player_lookup,
                    'error_type': error_type or 'UnknownError'
                }
                if not send_metric('prediction_write_errors_total', 1, error_labels):
                    logger.error(f"Failed to send prediction_write_errors_total metric for {player_lookup}", exc_info=True)
                    all_success = False

                logger.warning(
                    f"BigQuery write failed for {player_lookup}: "
                    f"error_type={error_type}, records={records_count}, duration={duration_seconds:.3f}s"
                )
            else:
                logger.debug(
                    f"BigQuery write succeeded for {player_lookup}: "
                    f"records={records_count}, duration={duration_seconds:.3f}s"
                )

        except Exception as e:
            logger.error(f"Error sending write attempt metrics for {player_lookup}: {e}", exc_info=True)
            return False

        return all_success

    @staticmethod
    def track_dml_rate_limit(send_alert: bool = True) -> bool:
        """
        Track a BigQuery DML rate limit error and optionally send alerts.

        BigQuery has DML rate limits (e.g., 1500 DML statements per table per day,
        and 20 concurrent DML operations per table). This metric helps monitor
        and alert on rate limit hits.

        Self-Healing: Tracks error frequency and can trigger alerts when threshold
        is exceeded. Uses config from orchestration_config.py.

        Sends metrics:
        - prediction_dml_rate_limit_total: Counter of DML rate limit errors
        - prediction_dml_rate_limit_alert: When threshold exceeded

        Returns:
            True if metric was sent successfully
        """
        global _dml_error_timestamps

        if not PredictionWriteMetrics._ensure_client():
            return False

        # Track the error timestamp
        _dml_error_timestamps.append(datetime.now())

        labels = {
            'error_type': 'DMLRateLimitError',
            'service': 'prediction_worker'
        }

        try:
            # Send the metric
            success = send_metric('prediction_dml_rate_limit_total', 1, labels)

            if not success:
                logger.error("Failed to send prediction_dml_rate_limit_total metric", exc_info=True)
            else:
                logger.warning(
                    "🚨 BigQuery DML rate limit hit - "
                    "consider batch consolidation or reducing write frequency"
                )

            # Check if we should alert (threshold exceeded)
            if send_alert:
                PredictionWriteMetrics._check_and_send_dml_alert()

            return success

        except Exception as e:
            logger.error(f"Error sending DML rate limit metric: {e}", exc_info=True)
            return False

    @staticmethod
    def _check_and_send_dml_alert() -> bool:
        """
        Check if DML error rate exceeds threshold and send alert.

        Uses configuration from SelfHealingConfig:
        - dml_error_threshold: Number of errors in window to trigger alert
        - dml_error_window_seconds: Time window for counting errors

        Returns:
            True if alert was sent, False otherwise
        """
        global _dml_error_timestamps

        try:
            # Get config (import here to avoid circular deps)
            from shared.config.orchestration_config import get_orchestration_config
            config = get_orchestration_config()

            threshold = config.self_healing.dml_error_threshold
            window_seconds = config.self_healing.dml_error_window_seconds

            # Count errors in window
            cutoff_time = datetime.now() - timedelta(seconds=window_seconds)
            recent_errors = sum(1 for ts in _dml_error_timestamps if ts > cutoff_time)

            if recent_errors >= threshold:
                logger.error(
                    f"⚠️ DML RATE LIMIT THRESHOLD EXCEEDED: "
                    f"{recent_errors} errors in last {window_seconds}s (threshold: {threshold})"
                )

                # Send alert metric
                send_metric('prediction_dml_rate_limit_alert', 1, {
                    'severity': 'critical',
                    'error_count': str(recent_errors),
                    'window_seconds': str(window_seconds)
                })

                # Send alert via notification channels
                if config.self_healing.alert_on_dml_limit:
                    PredictionWriteMetrics._send_dml_alert_notification(
                        recent_errors, window_seconds, threshold
                    )

                return True

        except Exception as e:
            logger.error(f"Error checking DML alert threshold: {e}", exc_info=True)

        return False

    @staticmethod
    def _send_dml_alert_notification(error_count: int, window_seconds: int, threshold: int):
        """Send DML rate limit alert via notification channels."""
        try:
            from shared.utils.slack_channels import send_alert_to_slack
            message = (
                f"🚨 *BigQuery DML Rate Limit Alert*\n"
                f"• Errors: {error_count} in {window_seconds}s (threshold: {threshold})\n"
                f"• Action: Consider enabling batch consolidation or reducing concurrency\n"
                f"• Command: `gcloud run services update prediction-worker "
                f"--max-instances=4 --concurrency=3 --region=us-west2`"
            )
            send_alert_to_slack(message, channel='#nba-alerts')
        except ImportError:
            logger.debug("Slack notification skipped - module not available")
        except Exception as e:
            logger.error(f"Failed to send DML alert notification: {e}", exc_info=True)

    @staticmethod
    def with_exponential_backoff(
        func: Callable[..., T],
        *args,
        max_retries: int = 3,
        base_backoff: float = 5.0,
        max_backoff: float = 120.0,
        **kwargs
    ) -> T:
        """
        Execute a function with exponential backoff on DML rate limit errors.

        Self-Healing: When a DML rate limit is hit, waits with exponential backoff
        before retrying. Adds jitter to prevent thundering herd.

        Args:
            func: Function to execute
            *args: Positional arguments for the function
            max_retries: Maximum number of retries (default: 3)
            base_backoff: Base backoff in seconds (default: 5.0)
            max_backoff: Maximum backoff in seconds (default: 120.0)
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the function

        Raises:
            The last exception if all retries fail
        """
        from google.api_core import exceptions as gcp_exceptions

        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except gcp_exceptions.Conflict as e:
                # DML rate limit is typically returned as Conflict (409)
                last_exception = e

                if attempt < max_retries:
                    # Track the error
                    PredictionWriteMetrics.track_dml_rate_limit(send_alert=True)

                    # Calculate backoff with exponential increase and jitter
                    backoff = min(
                        base_backoff * (2 ** attempt),
                        max_backoff
                    )
                    jitter = random.uniform(0, backoff * 0.1)
                    sleep_time = backoff + jitter

                    logger.warning(
                        f"DML rate limit hit, retrying in {sleep_time:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        f"DML rate limit hit - all {max_retries} retries exhausted"
                    )
                    raise
            except Exception as e:
                # Non-DML errors should be raised immediately
                raise

        raise last_exception

    @staticmethod
    def track_batch_consolidation(
        batch_id: str,
        rows_affected: int,
        duration_seconds: float
    ) -> bool:
        """
        Track a batch consolidation operation.

        Batch consolidation combines multiple small writes into larger batches
        to avoid DML rate limits and improve efficiency.

        Sends metrics:
        - prediction_batch_consolidation_total: Counter of batch consolidations
        - prediction_batch_rows_affected: Number of rows in the consolidated batch
        - prediction_batch_duration_seconds: Time taken for the batch operation

        Args:
            batch_id: Unique identifier for the batch operation
            rows_affected: Total number of rows affected by the batch
            duration_seconds: Time taken for the batch consolidation

        Returns:
            True if all metrics were sent successfully
        """
        if not PredictionWriteMetrics._ensure_client():
            return False

        all_success = True

        labels = {
            'batch_id': batch_id,
            'service': 'prediction_worker'
        }

        try:
            # Track batch consolidation count
            if not send_metric('prediction_batch_consolidation_total', 1, labels):
                logger.error(f"Failed to send prediction_batch_consolidation_total metric for batch {batch_id}", exc_info=True)
                all_success = False

            # Track rows affected
            if not send_metric('prediction_batch_rows_affected', rows_affected, labels):
                logger.error(f"Failed to send prediction_batch_rows_affected metric for batch {batch_id}", exc_info=True)
                all_success = False

            # Track duration
            if not send_metric('prediction_batch_duration_seconds', duration_seconds, labels):
                logger.error(f"Failed to send prediction_batch_duration_seconds metric for batch {batch_id}", exc_info=True)
                all_success = False

            logger.info(
                f"Batch consolidation complete: batch_id={batch_id}, "
                f"rows_affected={rows_affected}, duration={duration_seconds:.3f}s"
            )

        except Exception as e:
            logger.error(f"Error sending batch consolidation metrics for batch {batch_id}: {e}", exc_info=True)
            return False

        return all_success
