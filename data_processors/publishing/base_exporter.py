"""
Base Exporter for Phase 6 Publishing

Provides common functionality for exporting BigQuery data to GCS as JSON.

Circuit Breaker Protection:
- GCS uploads are protected by circuit breaker to prevent cascading failures
- If GCS becomes unavailable, circuit opens and exports fail fast
- Circuit auto-recovers after timeout period
- Slack alerts are sent when circuit breaker opens or fails to recover

Version: 1.2
Updated: 2026-01-30 - Added Slack alerting for circuit breaker failures
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from google.cloud import bigquery
from google.cloud import storage
from google.api_core.exceptions import (
    Conflict,
    ServiceUnavailable,
    DeadlineExceeded,
    InternalServerError,
)
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.retry_with_jitter import retry_with_jitter

# Circuit breaker for GCS operations
from shared.utils.external_service_circuit_breaker import (
    get_service_circuit_breaker,
    CircuitBreakerError,
    CircuitState,
)

logger = logging.getLogger(__name__)

from shared.config.gcp_config import get_project_id, Buckets

PROJECT_ID = get_project_id()
BUCKET_NAME = Buckets.API
API_VERSION = 'v1'

# Circuit breaker service name for GCS uploads
GCS_CIRCUIT_BREAKER_SERVICE = "gcs_api_export"


def send_circuit_breaker_alert(
    service_name: str,
    failure_count: int,
    last_error: Optional[str] = None,
    event_type: str = "opened"
) -> None:
    """
    Send Slack alert when circuit breaker opens or fails to recover.

    This is non-blocking - failures to send alerts will not affect operations.

    Args:
        service_name: Name of the service/exporter with the circuit breaker
        failure_count: Number of consecutive failures that triggered the break
        last_error: The most recent error message (optional)
        event_type: Type of event ("opened" or "recovery_failed")
    """
    import requests
    import time

    try:
        from google.cloud import secretmanager

        # Get Slack webhook from Secret Manager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        webhook_url = response.payload.data.decode("UTF-8")

        # Format timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Build alert message based on event type
        if event_type == "opened":
            emoji = "🔴"
            title = "Circuit Breaker OPENED"
            status_msg = f"Circuit breaker opened after {failure_count} consecutive failures"
            action_msg = "GCS uploads will fail fast until circuit recovers"
        else:  # recovery_failed
            emoji = "🟠"
            title = "Circuit Breaker Recovery FAILED"
            status_msg = f"Circuit breaker failed to recover and re-opened"
            action_msg = "Service may have persistent issues - investigate GCS connectivity"

        # Truncate error message if too long
        error_text = last_error[:200] if last_error else "N/A"
        if last_error and len(last_error) > 200:
            error_text += "..."

        message = {
            "text": f"{emoji} *{title}*\n\n"
                   f"*Service:* {service_name}\n"
                   f"*Timestamp:* {timestamp}\n"
                   f"*Failure Count:* {failure_count}\n"
                   f"*Last Error:* {error_text}\n"
                   f"*Status:* {status_msg}\n"
                   f"*Impact:* {action_msg}"
        }

        # Retry logic for transient failures (same pattern as grading/main.py)
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(webhook_url, json=message, timeout=10)
                if resp.status_code == 200:
                    logger.info(
                        f"Sent circuit breaker alert: service={service_name}, "
                        f"event={event_type}, failures={failure_count}"
                    )
                    return
                elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
                    continue
                else:
                    logger.warning(
                        f"Slack circuit breaker alert failed: {resp.status_code} - {resp.text}"
                    )
                    return
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                logger.warning(f"Slack circuit breaker alert request failed: {e}")
                return

    except Exception as e:
        # Don't fail the operation if alert fails
        logger.warning(f"Failed to send circuit breaker alert: {e}")


def check_and_alert_circuit_breaker_state(
    cb,
    service_name: str,
    previous_state: CircuitState,
    error: Optional[Exception] = None
) -> None:
    """
    Check if circuit breaker state changed and send alert if needed.

    Args:
        cb: The circuit breaker instance
        service_name: Name of the service
        previous_state: State before the operation
        error: The error that caused the failure (optional)
    """
    current_state = cb.state
    status = cb.get_status()

    # Alert when circuit opens (CLOSED -> OPEN)
    if previous_state == CircuitState.CLOSED and current_state == CircuitState.OPEN:
        send_circuit_breaker_alert(
            service_name=service_name,
            failure_count=status.get('consecutive_failures', 0),
            last_error=str(error) if error else status.get('last_failure_error'),
            event_type="opened"
        )

    # Alert when circuit fails to recover (HALF_OPEN -> OPEN)
    elif previous_state == CircuitState.HALF_OPEN and current_state == CircuitState.OPEN:
        send_circuit_breaker_alert(
            service_name=service_name,
            failure_count=status.get('total_failures', 0),
            last_error=str(error) if error else status.get('last_failure_error'),
            event_type="recovery_failed"
        )


class BaseExporter(ABC):
    """
    Abstract base class for JSON exporters.

    Subclasses implement generate_json() to produce data,
    then call export() to upload to GCS.
    """

    def __init__(self, project_id: str = PROJECT_ID, bucket_name: str = BUCKET_NAME):
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.bq_client = get_bigquery_client(project_id=project_id)
        from shared.clients import get_storage_client
        self.gcs_client = get_storage_client(project_id)

    @abstractmethod
    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """Generate JSON content for export. Implemented by subclasses."""
        pass

    def query_to_list(self, query: str, params: Optional[List] = None) -> List[Dict]:
        """
        Execute BigQuery query and return results as list of dicts.

        Args:
            query: SQL query string with @param placeholders
            params: List of bigquery.ScalarQueryParameter objects

        Returns:
            List of dictionaries, one per row
        """
        job_config = None
        if params:
            job_config = bigquery.QueryJobConfig(query_parameters=params)

        try:
            result = self.bq_client.query(query, job_config=job_config).result(timeout=60)
            return [dict(row) for row in result]
        except Exception as e:
            logger.error(f"Query failed: {e}", exc_info=True)
            raise

    def upload_to_gcs(
        self,
        json_data: Dict[str, Any],
        path: str,
        cache_control: str = 'public, max-age=300'
    ) -> str:
        """
        Upload JSON data to GCS with cache headers.

        Protected by circuit breaker to prevent cascading failures when
        GCS is unavailable. If circuit is open, raises CircuitBreakerError.

        Sends Slack alerts when:
        - Circuit breaker opens (after threshold failures)
        - Circuit breaker fails to recover from half-open state

        Args:
            json_data: Dictionary to serialize as JSON
            path: Path within bucket (e.g., 'results/2021-11-10.json')
            cache_control: HTTP cache-control header value

        Returns:
            Full GCS path (gs://bucket/v1/path)

        Raises:
            CircuitBreakerError: If GCS circuit breaker is open
            Exception: Any GCS upload error after retries
        """
        # Get circuit breaker for GCS operations
        cb = get_service_circuit_breaker(GCS_CIRCUIT_BREAKER_SERVICE)

        # Check if circuit is available before doing work
        if not cb.is_available():
            status = cb.get_status()
            logger.error(
                f"GCS circuit breaker OPEN - skipping upload to {path}. "
                f"Timeout remaining: {status.get('timeout_remaining', 0):.1f}s"
            )
            raise CircuitBreakerError(
                GCS_CIRCUIT_BREAKER_SERVICE,
                datetime.now(timezone.utc),
                status.get('timeout_remaining', 0)
            )

        # Capture state before operation for alert detection
        state_before = cb.state

        bucket = self.gcs_client.bucket(self.bucket_name)
        full_path = f'{API_VERSION}/{path}'
        blob = bucket.blob(full_path)

        # Serialize with proper handling of dates/decimals
        json_str = json.dumps(
            json_data,
            indent=2,
            default=self._json_serializer,
            ensure_ascii=False
        )

        # Upload with retry, protected by circuit breaker
        try:
            self._upload_blob_with_retry(blob, json_str, cache_control)
            # Record success with circuit breaker
            cb._record_success()
        except (ServiceUnavailable, DeadlineExceeded, InternalServerError, Conflict) as e:
            # Record failure with circuit breaker for GCS-specific errors
            cb._record_failure(e)

            # Check if circuit breaker state changed and send alert if needed
            check_and_alert_circuit_breaker_state(
                cb=cb,
                service_name=GCS_CIRCUIT_BREAKER_SERVICE,
                previous_state=state_before,
                error=e
            )
            raise

        gcs_path = f'gs://{self.bucket_name}/{full_path}'
        logger.info(f"Uploaded {len(json_str)} bytes to {gcs_path}")
        return gcs_path

    @retry_with_jitter(
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        exceptions=(ServiceUnavailable, DeadlineExceeded, InternalServerError, Conflict)
    )
    def _upload_blob_with_retry(self, blob, json_str: str, cache_control: str) -> None:
        """Upload blob with retry on transient GCS errors.

        Sets cache_control BEFORE upload so metadata is included in the single
        upload request. This avoids 409 Conflict errors from a separate patch()
        call racing with concurrent writers.
        """
        blob.cache_control = cache_control
        blob.upload_from_string(
            json_str,
            content_type='application/json'
        )

    def _json_serializer(self, obj: Any) -> Any:
        """Custom JSON serializer for types not handled by default."""
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        if hasattr(obj, '__float__'):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def get_generated_at(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()
