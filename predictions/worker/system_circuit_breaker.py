# predictions/worker/system_circuit_breaker.py

"""
System-Level Circuit Breaker for Phase 5 Prediction Systems

Pattern #5: Circuit Breakers - adapted for Phase 5 worker architecture

Unlike Phase 3/4 processors which have processor-level circuit breakers,
Phase 5 has SYSTEM-LEVEL circuit breakers (one per prediction system).

Architecture:
- 5 independent circuit breakers (one per system: moving_average, zone_matchup, similarity, xgboost, ensemble)
- If xgboost circuit opens, disable it but keep other 4 systems running
- Enables graceful degradation (partial success is acceptable)

Circuit Breaker States:
- CLOSED: Normal operation, system is healthy
- OPEN: Too many failures, rejecting all requests for timeout period
- HALF_OPEN: Testing if system has recovered

Configuration:
- Threshold: 5 consecutive failures opens circuit
- Timeout: 30 minutes circuit stays open before testing
- Recovery: 2 consecutive successes closes circuit from half-open

Version: 1.0
Date: 2025-11-20
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class SystemCircuitBreaker:
    """
    Manages circuit breaker state for Phase 5 prediction systems.

    Each prediction system (moving_average, zone_matchup, similarity, xgboost, ensemble)
    has its own circuit breaker that opens independently based on failure count.
    """

    # Configuration
    FAILURE_THRESHOLD = 5  # Open circuit after 5 consecutive failures
    TIMEOUT_MINUTES = 30   # Stay open for 30 minutes
    RECOVERY_THRESHOLD = 2  # Need 2 successes to close from half-open

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize circuit breaker manager.

        Args:
            bq_client: BigQuery client
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.circuit_breaker_table = f'{project_id}.nba_orchestration.circuit_breaker_state'

        # Cache circuit states in memory (refreshed every 30 seconds)
        self._state_cache = {}
        self._cache_timestamp = None
        self._cache_ttl_seconds = 30

        logger.info(f"Initialized SystemCircuitBreaker with threshold={self.FAILURE_THRESHOLD}, timeout={self.TIMEOUT_MINUTES}min")

    def check_circuit(self, system_id: str) -> Tuple[str, Optional[str]]:
        """
        Check if circuit is open for a prediction system.

        Args:
            system_id: System identifier (e.g., 'moving_average', 'xgboost_v1')

        Returns:
            Tuple of (state, skip_reason)
            - state: 'CLOSED', 'OPEN', or 'HALF_OPEN'
            - skip_reason: None if CLOSED, reason string if OPEN/HALF_OPEN
        """
        try:
            # Refresh cache if expired
            if self._should_refresh_cache():
                self._refresh_cache()

            # Check cached state
            state_info = self._state_cache.get(system_id)

            if not state_info:
                # No circuit breaker entry = CLOSED (healthy)
                return ('CLOSED', None)

            state = state_info['state']

            if state == 'OPEN':
                # Check if timeout has expired
                opened_at = state_info['opened_at']
                timeout_expiry = opened_at + timedelta(minutes=self.TIMEOUT_MINUTES)

                if datetime.now(timezone.utc) >= timeout_expiry:
                    # Timeout expired, transition to HALF_OPEN
                    self._transition_to_half_open(system_id)
                    return ('HALF_OPEN', 'circuit_testing_recovery')
                else:
                    # Still in timeout period
                    minutes_remaining = (timeout_expiry - datetime.now(timezone.utc)).total_seconds() / 60
                    skip_reason = f'circuit_open_timeout_{int(minutes_remaining)}min'
                    return ('OPEN', skip_reason)

            elif state == 'HALF_OPEN':
                return ('HALF_OPEN', 'circuit_testing_recovery')

            else:  # CLOSED
                return ('CLOSED', None)

        except Exception as e:
            logger.error(f"Error checking circuit for {system_id}: {e}")
            # Fail open - don't block on circuit breaker errors
            return ('CLOSED', None)

    def record_success(self, system_id: str) -> None:
        """
        Record successful system execution.

        If circuit is HALF_OPEN and we have enough successes, close it.
        If circuit is CLOSED, reset failure count.

        Args:
            system_id: System identifier
        """
        try:
            state_info = self._state_cache.get(system_id)

            if not state_info:
                # No circuit breaker entry = first success, nothing to record
                return

            state = state_info['state']

            if state == 'CLOSED':
                # Reset failure count on success
                self._reset_failure_count(system_id)

            elif state == 'HALF_OPEN':
                # Increment success count
                success_count = state_info.get('success_count', 0) + 1

                if success_count >= self.RECOVERY_THRESHOLD:
                    # Recovered! Close circuit
                    self._close_circuit(system_id)
                    logger.info(f"Circuit breaker CLOSED for {system_id} after {success_count} successes")
                else:
                    # Still testing, update success count
                    self._update_success_count(system_id, success_count)
                    logger.info(f"Circuit breaker HALF_OPEN for {system_id}: {success_count}/{self.RECOVERY_THRESHOLD} successes")

        except Exception as e:
            logger.error(f"Error recording success for {system_id}: {e}")

    def record_failure(self, system_id: str, error_message: str, error_type: str) -> bool:
        """
        Record failed system execution.

        If failure count reaches threshold, open circuit.

        Args:
            system_id: System identifier
            error_message: Error description
            error_type: Error classification

        Returns:
            True if circuit was opened, False otherwise
        """
        try:
            state_info = self._state_cache.get(system_id)

            if not state_info:
                # First failure, create circuit breaker entry
                self._create_circuit_entry(system_id, error_message, error_type)
                return False

            state = state_info['state']
            failure_count = state_info.get('failure_count', 0) + 1

            if state == 'HALF_OPEN':
                # Failure during recovery, re-open circuit
                self._open_circuit(system_id, failure_count, error_message, error_type)
                logger.warning(f"Circuit breaker RE-OPENED for {system_id} (failed during recovery)")
                return True

            elif state == 'CLOSED':
                # Increment failure count
                if failure_count >= self.FAILURE_THRESHOLD:
                    # Threshold reached, open circuit
                    self._open_circuit(system_id, failure_count, error_message, error_type)
                    logger.error(f"Circuit breaker OPENED for {system_id} after {failure_count} failures")
                    return True
                else:
                    # Update failure count
                    self._update_failure_count(system_id, failure_count, error_message, error_type)
                    logger.warning(f"Circuit breaker failure {failure_count}/{self.FAILURE_THRESHOLD} for {system_id}")
                    return False

            return False

        except Exception as e:
            logger.error(f"Error recording failure for {system_id}: {e}")
            return False

    # ========================================================================
    # Cache Management
    # ========================================================================

    def _should_refresh_cache(self) -> bool:
        """Check if cache needs refresh."""
        if self._cache_timestamp is None:
            return True

        age_seconds = (datetime.now(timezone.utc) - self._cache_timestamp).total_seconds()
        return age_seconds >= self._cache_ttl_seconds

    def _refresh_cache(self) -> None:
        """Refresh circuit breaker state cache from BigQuery."""
        try:
            # Schema: processor_name, state, failure_count, success_count,
            # last_failure, last_success, opened_at, half_opened_at, updated_at,
            # last_error_message, last_error_type, failure_history, threshold, timeout_seconds, half_open_max_calls
            query = f"""
            SELECT
                processor_name as system_id,
                state,
                failure_count,
                success_count,
                last_error_message,
                last_error_type,
                opened_at,
                last_success as closed_at,
                last_failure as last_failure_at
            FROM `{self.circuit_breaker_table}`
            WHERE processor_name IN ('moving_average', 'zone_matchup_v1', 'similarity_balanced_v1', 'xgboost_v1', 'ensemble_v1')
            """

            result = self.bq_client.query(query).to_dataframe()

            # Update cache
            self._state_cache = {}
            for _, row in result.iterrows():
                self._state_cache[row['system_id']] = {
                    'state': row['state'],
                    'failure_count': int(row['failure_count']) if row['failure_count'] is not None else 0,
                    'success_count': int(row['success_count']) if row['success_count'] is not None else 0,
                    'last_error_message': row['last_error_message'],
                    'last_error_type': row['last_error_type'],
                    'opened_at': row['opened_at'],
                    'closed_at': row['closed_at'],
                    'last_failure_at': row['last_failure_at']
                }

            self._cache_timestamp = datetime.now(timezone.utc)
            logger.debug(f"Refreshed circuit breaker cache: {len(self._state_cache)} entries")

        except Exception as e:
            logger.error(f"Error refreshing circuit breaker cache: {e}")
            # Keep stale cache on error

    # ========================================================================
    # State Transitions
    # ========================================================================

    def _create_circuit_entry(self, system_id: str, error_message: str, error_type: str) -> None:
        """Create initial circuit breaker entry."""
        query = f"""
        INSERT INTO `{self.circuit_breaker_table}`
        (processor_name, state, failure_count, success_count, last_error_message, last_error_type, last_failure, updated_at)
        VALUES
        (@system_id, 'CLOSED', 1, 0, @error_message, @error_type, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
                bigquery.ScalarQueryParameter('error_message', 'STRING', error_message),
                bigquery.ScalarQueryParameter('error_type', 'STRING', error_type)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache

    def _open_circuit(self, system_id: str, failure_count: int, error_message: str, error_type: str) -> None:
        """Transition circuit to OPEN state."""
        query = f"""
        UPDATE `{self.circuit_breaker_table}`
        SET
            state = 'OPEN',
            failure_count = @failure_count,
            last_error_message = @error_message,
            last_error_type = @error_type,
            opened_at = CURRENT_TIMESTAMP(),
            last_failure = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHERE processor_name = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
                bigquery.ScalarQueryParameter('failure_count', 'INT64', failure_count),
                bigquery.ScalarQueryParameter('error_message', 'STRING', error_message),
                bigquery.ScalarQueryParameter('error_type', 'STRING', error_type)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache

    def _transition_to_half_open(self, system_id: str) -> None:
        """Transition circuit from OPEN to HALF_OPEN."""
        query = f"""
        UPDATE `{self.circuit_breaker_table}`
        SET
            state = 'HALF_OPEN',
            success_count = 0,
            half_opened_at = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHERE processor_name = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache

    def _close_circuit(self, system_id: str) -> None:
        """Transition circuit to CLOSED state (recovered)."""
        query = f"""
        UPDATE `{self.circuit_breaker_table}`
        SET
            state = 'CLOSED',
            failure_count = 0,
            success_count = 0,
            last_success = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHERE processor_name = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache

    def _reset_failure_count(self, system_id: str) -> None:
        """Reset failure count on success."""
        query = f"""
        UPDATE `{self.circuit_breaker_table}`
        SET
            failure_count = 0,
            last_success = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHERE processor_name = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache

    def _update_failure_count(self, system_id: str, failure_count: int, error_message: str, error_type: str) -> None:
        """Update failure count."""
        query = f"""
        UPDATE `{self.circuit_breaker_table}`
        SET
            failure_count = @failure_count,
            last_error_message = @error_message,
            last_error_type = @error_type,
            last_failure = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHERE processor_name = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
                bigquery.ScalarQueryParameter('failure_count', 'INT64', failure_count),
                bigquery.ScalarQueryParameter('error_message', 'STRING', error_message),
                bigquery.ScalarQueryParameter('error_type', 'STRING', error_type)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache

    def _update_success_count(self, system_id: str, success_count: int) -> None:
        """Update success count during HALF_OPEN recovery."""
        query = f"""
        UPDATE `{self.circuit_breaker_table}`
        SET
            success_count = @success_count,
            last_success = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
        WHERE processor_name = @system_id
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('system_id', 'STRING', system_id),
                bigquery.ScalarQueryParameter('success_count', 'INT64', success_count)
            ]
        )

        self.bq_client.query(query, job_config=job_config).result()
        self._cache_timestamp = None  # Invalidate cache
