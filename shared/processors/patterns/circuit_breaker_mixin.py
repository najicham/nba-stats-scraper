"""
Pattern #5: Circuit Breaker Mixin

Prevents infinite retry loops by tracking failures and opening circuit after threshold.

Example:
    class PlayerGameSummaryProcessor(CircuitBreakerMixin, AnalyticsProcessorBase):
        # Uses centralized defaults, or override:
        CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 failures
        CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 min

Circuit States:
- CLOSED: Normal operation
- OPEN: Too many failures, rejecting all requests
- HALF_OPEN: Timeout expired, testing if issue resolved

Configuration:
    Defaults can be set via environment variables:
    - CIRCUIT_BREAKER_THRESHOLD: Number of failures (default: 5)
    - CIRCUIT_BREAKER_TIMEOUT_MINUTES: Timeout in minutes (default: 30)

    See: shared/config/circuit_breaker_config.py
"""

from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import logging

from google.cloud import bigquery

# Import centralized config for defaults
try:
    from shared.config.circuit_breaker_config import (
        CIRCUIT_BREAKER_THRESHOLD as DEFAULT_THRESHOLD,
        CIRCUIT_BREAKER_TIMEOUT as DEFAULT_TIMEOUT,
    )
except ImportError:
    # Fallback if config not available
    DEFAULT_THRESHOLD = 5
    DEFAULT_TIMEOUT = timedelta(minutes=30)

logger = logging.getLogger(__name__)


class CircuitBreakerMixin:
    """
    Mixin to add circuit breaker pattern to processors.

    Prevents infinite retry loops by tracking consecutive failures and
    "opening the circuit" after threshold is reached.
    """

    # Class-level state (shared across all instances)
    _circuit_breaker_failures = defaultdict(int)
    _circuit_breaker_opened_at = {}
    _circuit_breaker_alerts_sent = set()

    # Configuration (uses centralized defaults, override in subclass if needed)
    # Defaults come from shared/config/circuit_breaker_config.py
    # Can be set via env vars: CIRCUIT_BREAKER_THRESHOLD, CIRCUIT_BREAKER_TIMEOUT_MINUTES
    CIRCUIT_BREAKER_THRESHOLD = DEFAULT_THRESHOLD  # Open after N failures
    CIRCUIT_BREAKER_TIMEOUT = DEFAULT_TIMEOUT  # Stay open for this long

    def _get_circuit_key(self, start_date: str, end_date: str) -> str:
        """
        Generate circuit breaker key.

        Uses date range instead of single game_date to match our architecture.
        """
        return f"{self.__class__.__name__}:{start_date}:{end_date}"

    def _is_circuit_open(self, circuit_key: str) -> bool:
        """
        Check if circuit is open.

        Enhanced with auto-reset: checks if upstream data is now available
        and automatically closes circuit if so.

        Returns:
            True if circuit is open (should not process)
            False if circuit is closed or half-open (should try processing)
        """
        if circuit_key not in self._circuit_breaker_opened_at:
            return False

        opened_at = self._circuit_breaker_opened_at[circuit_key]
        time_open = datetime.now(timezone.utc) - opened_at

        # Check if timeout expired
        if time_open > self.CIRCUIT_BREAKER_TIMEOUT:
            # Try half-open state (test if issue resolved)
            logger.info(
                f"Circuit breaker timeout expired for {circuit_key}, "
                f"trying half-open state"
            )

            # Remove from opened_at (but keep failure count for now)
            del self._circuit_breaker_opened_at[circuit_key]

            return False

        # AUTO-RESET LOGIC: Check if upstream data is now available
        if self._should_auto_reset_circuit(circuit_key):
            logger.info(
                f"🔄 Auto-resetting circuit breaker for {circuit_key}: "
                f"upstream data now available"
            )
            self._close_circuit(circuit_key)
            return False

        # Circuit still open
        remaining = self.CIRCUIT_BREAKER_TIMEOUT - time_open
        logger.warning(
            f"Circuit breaker OPEN for {circuit_key}, "
            f"remaining: {int(remaining.total_seconds() // 60)} minutes"
        )

        return True

    def _should_auto_reset_circuit(self, circuit_key: str) -> bool:
        """
        Check if circuit breaker should be automatically reset.

        Calls get_upstream_data_check_query() to verify if upstream data
        that caused the circuit to open is now available.

        Returns:
            True if upstream data is available and circuit should reset
            False if data still unavailable or check not implemented
        """
        # Check if processor implements upstream data check
        if not hasattr(self, 'get_upstream_data_check_query'):
            # No check implemented - can't auto-reset
            return False

        # Check if we have BigQuery client
        if not hasattr(self, 'bq_client') or self.bq_client is None:
            return False

        try:
            # Extract date range from circuit key
            # Format: ProcessorName:start_date:end_date
            parts = circuit_key.split(':')
            if len(parts) < 3:
                return False

            start_date = parts[1]
            end_date = parts[2]

            # Get upstream data check query from processor
            check_query = self.get_upstream_data_check_query(start_date, end_date)

            if not check_query:
                return False

            # Execute query to check if data is available
            query_job = self.bq_client.query(check_query)
            results = list(query_job.result())

            if not results:
                return False

            # Expect query to return row with 'data_available' column (boolean)
            # or 'cnt' column (int > 0 means available)
            row = results[0]

            if 'data_available' in row.keys():
                data_available = row['data_available']
            elif 'cnt' in row.keys():
                data_available = row['cnt'] > 0
            else:
                # Unknown format - can't determine
                logger.warning(
                    f"Upstream check query returned unexpected format for {circuit_key}"
                )
                return False

            if data_available:
                logger.info(
                    f"✅ Upstream data now available for {circuit_key} "
                    f"(date range: {start_date} to {end_date})"
                )
                return True
            else:
                logger.debug(
                    f"Upstream data still unavailable for {circuit_key}"
                )
                return False

        except Exception as e:
            # Don't fail if check fails - just log and keep circuit open
            logger.warning(
                f"Failed to check upstream data availability for {circuit_key}: {e}"
            )
            return False

    def _open_circuit(self, circuit_key: str):
        """
        Open the circuit breaker.

        Called after threshold failures reached.
        """
        self._circuit_breaker_opened_at[circuit_key] = datetime.now(timezone.utc)

        logger.critical(
            f"Circuit breaker OPENED: {circuit_key} "
            f"(after {self.CIRCUIT_BREAKER_THRESHOLD} failures)"
        )

        # Send alert (only once per circuit key)
        if circuit_key not in self._circuit_breaker_alerts_sent:
            self._send_circuit_breaker_alert(circuit_key, 'opened')
            self._circuit_breaker_alerts_sent.add(circuit_key)

        # Write to circuit_breaker_state table
        self._write_circuit_state_to_bigquery(circuit_key, 'OPEN')

    def _close_circuit(self, circuit_key: str):
        """
        Close the circuit breaker.

        Called after successful processing in half-open state.
        """
        # Reset all state
        self._circuit_breaker_failures[circuit_key] = 0

        if circuit_key in self._circuit_breaker_opened_at:
            del self._circuit_breaker_opened_at[circuit_key]

        if circuit_key in self._circuit_breaker_alerts_sent:
            self._circuit_breaker_alerts_sent.remove(circuit_key)

        logger.info(f"Circuit breaker CLOSED: {circuit_key} (recovered)")

        # Send recovery alert
        self._send_circuit_breaker_alert(circuit_key, 'closed')

        # Write to circuit_breaker_state table
        self._write_circuit_state_to_bigquery(circuit_key, 'CLOSED')

    def _record_failure(self, circuit_key: str, error: Exception) -> bool:
        """
        Record a failure and check if threshold reached.

        Returns:
            True if threshold reached (circuit opened)
            False if still under threshold
        """
        self._circuit_breaker_failures[circuit_key] += 1
        failure_count = self._circuit_breaker_failures[circuit_key]

        logger.error(
            f"Failure recorded for {circuit_key}: "
            f"{failure_count}/{self.CIRCUIT_BREAKER_THRESHOLD}"
        )

        # Update BigQuery state
        self._write_circuit_state_to_bigquery(
            circuit_key,
            'CLOSED',
            last_error=str(error)
        )

        # Check if threshold reached
        if failure_count >= self.CIRCUIT_BREAKER_THRESHOLD:
            self._open_circuit(circuit_key)
            return True

        return False

    def _record_success(self, circuit_key: str):
        """
        Record a success and close circuit if it was open.
        """
        was_open = circuit_key in self._circuit_breaker_opened_at

        # Reset failure count
        self._circuit_breaker_failures[circuit_key] = 0

        # Close circuit if it was open
        if was_open:
            self._close_circuit(circuit_key)
        else:
            # Just update state
            self._write_circuit_state_to_bigquery(circuit_key, 'CLOSED')

    def run(self, opts: Optional[Dict] = None) -> bool:
        """
        Enhanced run method with circuit breaker protection.

        This wraps the parent run() method with circuit breaker logic.
        """
        if opts is None:
            opts = {}

        start_date = opts.get('start_date')
        end_date = opts.get('end_date')

        if not start_date or not end_date:
            # No date range - can't apply circuit breaker
            return super().run(opts)

        circuit_key = self._get_circuit_key(start_date, end_date)

        # Check circuit state BEFORE any processing
        if self._is_circuit_open(circuit_key):
            logger.error(f"Circuit breaker OPEN for {circuit_key}, skipping")

            # Update stats for logging
            if hasattr(self, 'stats'):
                self.stats['skip_reason'] = 'circuit_breaker_open'

            # Log the skip
            if hasattr(self, 'log_processing_run'):
                self.log_processing_run(success=True, skip_reason='circuit_breaker_open')

            # Return False to signal Pub/Sub to retry later
            return False

        try:
            # Normal processing
            result = super().run(opts)

            # SUCCESS - reset circuit breaker
            self._record_success(circuit_key)

            return result

        except Exception as e:
            # FAILURE - record and check threshold
            threshold_reached = self._record_failure(circuit_key, e)

            if threshold_reached:
                logger.critical(
                    f"Circuit breaker threshold reached for {circuit_key}, "
                    f"no more retries for {self.CIRCUIT_BREAKER_TIMEOUT}"
                )

            # Re-raise exception so Pub/Sub knows it failed
            raise

    def _write_circuit_state_to_bigquery(
        self,
        circuit_key: str,
        state: str,
        last_error: str = None
    ):
        """
        Write circuit breaker state to BigQuery for monitoring.

        Args:
            circuit_key: Circuit identifier (processor:start_date:end_date)
            state: 'CLOSED', 'OPEN', 'HALF_OPEN'
            last_error: Most recent error message (optional)
        """
        if not hasattr(self, 'bq_client') or not hasattr(self, 'project_id'):
            return  # Skip if no BigQuery client

        processor_name = circuit_key.split(':')[0]
        failure_count = self._circuit_breaker_failures.get(circuit_key, 0)

        # Build state record
        state_record = {
            'processor_name': processor_name,
            'state': state,
            'failure_count': failure_count,
            'success_count': 0 if state != 'CLOSED' else 1,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'threshold': self.CIRCUIT_BREAKER_THRESHOLD,
            'timeout_seconds': int(self.CIRCUIT_BREAKER_TIMEOUT.total_seconds()),
            'half_open_max_calls': 1
        }

        # Add timestamps based on state
        if state == 'OPEN' and circuit_key in self._circuit_breaker_opened_at:
            state_record['opened_at'] = self._circuit_breaker_opened_at[circuit_key].isoformat()

        if state == 'CLOSED':
            state_record['last_success'] = datetime.now(timezone.utc).isoformat()
        else:
            state_record['last_failure'] = datetime.now(timezone.utc).isoformat()

        if last_error:
            state_record['last_error_message'] = last_error[:500]  # Truncate
            state_record['last_error_type'] = type(last_error).__name__

        try:
            # Use batch loading instead of streaming inserts to avoid the 90-minute
            # streaming buffer that blocks DML operations (MERGE/UPDATE/DELETE)
            # Reference: docs/05-development/guides/bigquery-best-practices.md
            table_id = f"{self.project_id}.nba_orchestration.circuit_breaker_state"

            # Get table reference for schema
            table_ref = self.bq_client.get_table(table_id)

            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = self.bq_client.load_table_from_json([state_record], table_id, job_config=job_config)
            load_job.result(timeout=60)

            if load_job.errors:
                logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")

        except Exception as e:
            logger.warning(f"Failed to write circuit state to BigQuery: {e}")

    def _send_circuit_breaker_alert(self, circuit_key: str, action: str):
        """
        Send alert about circuit breaker state change.

        Args:
            circuit_key: Circuit identifier
            action: 'opened' or 'closed'
        """
        processor_name = circuit_key.split(':')[0]
        date_range = ':'.join(circuit_key.split(':')[1:])

        if action == 'opened':
            severity = 'critical'
            title = f'Circuit Breaker OPENED: {processor_name}'
            message = f"""
Circuit breaker opened after {self.CIRCUIT_BREAKER_THRESHOLD} consecutive failures.

Processor: {processor_name}
Date Range: {date_range}

Impact:
- Processing halted for {int(self.CIRCUIT_BREAKER_TIMEOUT.total_seconds() // 60)} minutes
- Pub/Sub retries will be rejected
- Manual intervention may be required

Next Steps:
1. Check logs for root cause (BigQuery quota, data quality, bugs)
2. Fix underlying issue
3. Wait for timeout or manually reset
4. Monitor for recovery

Circuit will automatically retry in half-open state after timeout.
            """.strip()
        else:  # closed
            severity = 'info'
            title = f'Circuit Breaker CLOSED: {processor_name}'
            message = f"""
Circuit breaker closed - system recovered.

Processor: {processor_name}
Date Range: {date_range}

Status: Processing resumed successfully
            """.strip()

        # Log the alert (in production, integrate with alerting system)
        if severity == 'critical':
            logger.critical(f"{title}\n{message}")
        else:
            logger.info(f"{title}\n{message}")

    def get_circuit_status(self) -> Dict:
        """
        Get current circuit breaker status.

        Returns dict with circuit state information.
        """
        status = {
            'total_circuits': len(self._circuit_breaker_failures),
            'open_circuits': len(self._circuit_breaker_opened_at),
            'circuits': {}
        }

        for circuit_key, failure_count in self._circuit_breaker_failures.items():
            is_open = circuit_key in self._circuit_breaker_opened_at

            status['circuits'][circuit_key] = {
                'state': 'OPEN' if is_open else 'CLOSED',
                'failure_count': failure_count,
                'opened_at': self._circuit_breaker_opened_at.get(circuit_key),
                'threshold': self.CIRCUIT_BREAKER_THRESHOLD
            }

        return status
