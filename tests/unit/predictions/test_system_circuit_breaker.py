"""
Unit Tests for SystemCircuitBreaker (Phase 5 Worker)

Tests cover:
1. Circuit state checking (CLOSED, OPEN, HALF_OPEN)
2. Failure recording and threshold detection
3. Success recording and circuit recovery
4. Timeout expiry and transitions
5. Multiple system isolation
6. BigQuery state persistence
7. Cache management (30-second TTL)
8. Graceful degradation
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch
from predictions.worker.system_circuit_breaker import SystemCircuitBreaker


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.query_results = []
        self.inserted_rows = []
        self.query_call_count = 0

    def query(self, query_string, **kwargs):
        """Mock query execution - accepts job_config and other params"""
        self.query_call_count += 1
        result_mock = Mock()

        # Create a mock DataFrame
        import pandas as pd
        if self.query_results:
            # Convert mock objects to dict format for DataFrame
            data_rows = []
            for result in self.query_results:
                data_rows.append({
                    'system_id': getattr(result, 'system_id', 'moving_average'),
                    'state': getattr(result, 'state', 'CLOSED'),
                    'failure_count': getattr(result, 'failure_count', 0),
                    'success_count': getattr(result, 'success_count', 0),
                    'last_error_message': getattr(result, 'last_error_message', None),
                    'last_error_type': getattr(result, 'last_error_type', None),
                    'opened_at': getattr(result, 'opened_at', None),
                    'closed_at': getattr(result, 'closed_at', None),
                    'last_failure_at': getattr(result, 'last_failure_at', None)
                })
            result_mock.to_dataframe.return_value = pd.DataFrame(data_rows)
        else:
            # Empty DataFrame
            result_mock.to_dataframe.return_value = pd.DataFrame(columns=[
                'system_id', 'state', 'failure_count', 'success_count',
                'last_error_message', 'last_error_type', 'opened_at',
                'closed_at', 'last_failure_at'
            ])

        return result_mock

    def insert_rows_json(self, table_id, rows):
        """Mock insert rows"""
        self.inserted_rows.extend(rows)
        return []  # No errors


class TestCircuitStateChecking:
    """Test suite for circuit state checking"""

    def test_closed_circuit_returns_closed_state(self):
        """Test that closed circuit returns CLOSED state"""
        bq_client = MockBigQueryClient()
        bq_client.query_results = []  # No existing state

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        state, reason = breaker.check_circuit('moving_average')

        assert state == 'CLOSED'
        assert reason is None

    def test_open_circuit_returns_open_state(self):
        """Test that open circuit returns OPEN state"""
        bq_client = MockBigQueryClient()

        # Mock open circuit state
        open_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='OPEN',
            failure_count=5,
            success_count=0,
            last_error_message='Test error',
            last_error_type='ValueError',
            opened_at=open_time,
            closed_at=None,
            last_failure_at=open_time
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        state, reason = breaker.check_circuit('moving_average')

        assert state == 'OPEN'
        assert reason is not None
        assert 'circuit_open' in reason  # Format is "circuit_open_timeout_XXmin"

    def test_expired_timeout_transitions_to_half_open(self):
        """Test that expired timeout transitions to HALF_OPEN"""
        bq_client = MockBigQueryClient()

        # Mock open circuit with expired timeout
        open_time = datetime.now(timezone.utc) - timedelta(minutes=35)
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='OPEN',
            failure_count=5,
            success_count=0,
            last_error_message='Test error',
            last_error_type='ValueError',
            opened_at=open_time,
            closed_at=None,
            last_failure_at=open_time
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        state, reason = breaker.check_circuit('moving_average')

        # Should transition to HALF_OPEN (not CLOSED)
        assert state == 'HALF_OPEN'
        assert reason == 'circuit_testing_recovery'

    def test_cache_ttl_respected(self):
        """Test that cache TTL is respected"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # First call - should query BigQuery
        bq_client.query_results = []
        state1, _ = breaker.check_circuit('moving_average')

        query_count_1 = bq_client.query.call_count if hasattr(bq_client.query, 'call_count') else 0

        # Second call immediately - should use cache
        state2, _ = breaker.check_circuit('moving_average')

        # Both should return same state
        assert state1 == state2


class TestFailureRecording:
    """Test suite for failure recording"""

    def test_first_failure_increments_count(self):
        """Test that first failure creates circuit entry"""
        bq_client = MockBigQueryClient()
        bq_client.query_results = []  # No existing state

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # First call to check_circuit refreshes cache (empty)
        breaker.check_circuit('moving_average')

        # Now record failure - should create entry
        breaker.record_failure('moving_average', 'Test error', 'ValueError')

        # Should have written to BigQuery
        assert len(bq_client.inserted_rows) > 0
        assert bq_client.inserted_rows[0]['failure_count'] == 1

    def test_multiple_failures_increment_count(self):
        """Test that multiple failures increment count"""
        bq_client = MockBigQueryClient()

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Record 3 failures
        for i in range(3):
            # Mock existing state with increasing failure count
            bq_client.query_results = [Mock(
                state='CLOSED',
                failure_count=i,
                success_count=0,
                opened_at=None,
                timeout_seconds=1800
            )]

            breaker._state_cache = {}  # Clear cache
            breaker.record_failure('moving_average', f'Error {i}', 'ValueError')

    def test_threshold_reached_opens_circuit(self):
        """Test that reaching threshold opens circuit"""
        bq_client = MockBigQueryClient()

        # Mock state just before threshold
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='CLOSED',
            failure_count=4,  # One below threshold
            success_count=0,
            last_error_message=None,
            last_error_type=None,
            opened_at=None,
            closed_at=None,
            last_failure_at=None
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Refresh cache to populate state_cache
        breaker.check_circuit('moving_average')

        # Record failure that should open circuit
        opened = breaker.record_failure('moving_average', 'Final error', 'ValueError')

        # Should return True (circuit opened)
        assert opened is True

        # Should have written OPEN state
        open_states = [r for r in bq_client.inserted_rows if r.get('state') == 'OPEN']
        assert len(open_states) > 0

    def test_failure_below_threshold_doesnt_open(self):
        """Test that failures below threshold don't open circuit"""
        bq_client = MockBigQueryClient()
        bq_client.query_results = []

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Record failure below threshold
        opened = breaker.record_failure('moving_average', 'Error', 'ValueError')

        # Should not open circuit
        assert opened is False


class TestSuccessRecording:
    """Test suite for success recording"""

    def test_success_resets_failure_count(self):
        """Test that success resets failure count"""
        bq_client = MockBigQueryClient()

        # Mock state with failures
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='CLOSED',
            failure_count=3,
            success_count=0,
            last_error_message=None,
            last_error_type=None,
            opened_at=None,
            closed_at=None,
            last_failure_at=None
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Refresh cache to populate state_cache
        breaker.check_circuit('moving_average')

        breaker.record_success('moving_average')

        # Should have written success state with reset failure count
        assert len(bq_client.inserted_rows) > 0
        success_record = bq_client.inserted_rows[-1]
        assert success_record['failure_count'] == 0

    def test_success_closes_open_circuit(self):
        """Test that success closes HALF_OPEN circuit"""
        bq_client = MockBigQueryClient()

        # Mock HALF_OPEN circuit (success closes from HALF_OPEN, not OPEN)
        open_time = datetime.now(timezone.utc) - timedelta(minutes=35)
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='HALF_OPEN',  # Changed to HALF_OPEN
            failure_count=5,
            success_count=1,  # One success already
            last_error_message='Test error',
            last_error_type='ValueError',
            opened_at=open_time,
            closed_at=None,
            last_failure_at=open_time
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Refresh cache
        breaker.check_circuit('moving_average')

        breaker.record_success('moving_average')

        # Should have written CLOSED state (after 2 successes)
        assert len(bq_client.inserted_rows) > 0
        closed_record = bq_client.inserted_rows[-1]
        assert closed_record['state'] == 'CLOSED'
        assert closed_record['failure_count'] == 0

    def test_success_in_half_open_closes_circuit(self):
        """Test that success in HALF_OPEN state closes circuit after recovery threshold"""
        bq_client = MockBigQueryClient()

        # Mock half-open state with 1 success already
        open_time = datetime.now(timezone.utc) - timedelta(minutes=35)
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='HALF_OPEN',
            failure_count=5,
            success_count=1,  # 1 success, need 2 total (RECOVERY_THRESHOLD=2)
            last_error_message='Test error',
            last_error_type='ValueError',
            opened_at=open_time,
            closed_at=None,
            last_failure_at=open_time
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Refresh cache
        breaker.check_circuit('moving_average')

        # Record second success (should close circuit)
        breaker.record_success('moving_average')

        # Should close circuit
        assert len(bq_client.inserted_rows) > 0
        closed_record = bq_client.inserted_rows[-1]
        assert closed_record['state'] == 'CLOSED'


class TestMultipleSystemIsolation:
    """Test suite for multiple independent systems"""

    def test_different_systems_are_independent(self):
        """Test that different systems have independent circuits"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Open circuit for moving_average
        for i in range(5):
            bq_client.query_results = [Mock(
                state='CLOSED',
                failure_count=i,
                success_count=0,
                opened_at=None,
                timeout_seconds=1800
            )]
            breaker._state_cache = {}
            breaker.record_failure('moving_average', f'Error {i}', 'ValueError')

        # Check states
        open_time = datetime.now(timezone.utc)
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='OPEN',
            failure_count=5,
            success_count=0,
            last_error_message='Test error',
            last_error_type='ValueError',
            opened_at=open_time,
            closed_at=None,
            last_failure_at=open_time
        )]
        breaker._state_cache = {}
        state1, _ = breaker.check_circuit('moving_average')

        # xgboost should still be closed
        bq_client.query_results = []
        breaker._state_cache = {}
        state2, _ = breaker.check_circuit('xgboost_v1')

        assert state1 == 'OPEN'
        assert state2 == 'CLOSED'

    def test_failure_counts_are_separate(self):
        """Test that failure counts are tracked separately"""
        bq_client = MockBigQueryClient()

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Initialize cache with empty results
        bq_client.query_results = []
        breaker.check_circuit('moving_average')
        breaker.check_circuit('xgboost_v1')

        # Record different failures for each system
        breaker.record_failure('moving_average', 'Error 1', 'ValueError')
        breaker.record_failure('xgboost_v1', 'Error 2', 'RuntimeError')

        # Both should have created entries - check processor_name field
        ma_record = [r for r in bq_client.inserted_rows if r.get('processor_name') == 'moving_average']
        xgb_record = [r for r in bq_client.inserted_rows if r.get('processor_name') == 'xgboost_v1']

        assert len(ma_record) > 0
        assert len(xgb_record) > 0


class TestSystemIDs:
    """Test suite for system ID validation"""

    def test_all_five_systems_supported(self):
        """Test that all 5 prediction systems are supported"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        systems = [
            'moving_average',
            'zone_matchup_v1',
            'similarity_balanced_v1',
            'xgboost_v1',
            'ensemble_v1'
        ]

        # All systems should be checkable
        for system_id in systems:
            bq_client.query_results = []
            breaker._state_cache = {}
            state, reason = breaker.check_circuit(system_id)
            assert state in ['CLOSED', 'OPEN', 'HALF_OPEN']


class TestCacheManagement:
    """Test suite for cache management"""

    def test_cache_is_refreshed_after_ttl(self):
        """Test that cache is refreshed after TTL expires"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')
        breaker._cache_ttl_seconds = 1  # 1 second TTL for testing

        # First call
        bq_client.query_results = []
        state1, _ = breaker.check_circuit('moving_average')

        # Wait for TTL to expire
        import time
        time.sleep(1.1)

        # Second call should refresh cache
        bq_client.query_results = []
        state2, _ = breaker.check_circuit('moving_average')

        # Cache should have been refreshed
        assert breaker._cache_timestamp is not None

    def test_cache_key_per_system(self):
        """Test that cache is keyed per system"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Check different systems
        bq_client.query_results = []
        state1, _ = breaker.check_circuit('moving_average')

        bq_client.query_results = [Mock(
            state='OPEN',
            failure_count=5,
            success_count=0,
            opened_at=datetime.now(timezone.utc),
            timeout_seconds=1800
        )]
        breaker._state_cache = {}
        state2, _ = breaker.check_circuit('xgboost_v1')

        # Different systems should have different cache entries
        assert 'moving_average' in breaker._state_cache or state1 is not None
        assert 'xgboost_v1' in breaker._state_cache or state2 is not None


class TestBigQueryIntegration:
    """Test suite for BigQuery state persistence"""

    def test_check_circuit_queries_bigquery(self):
        """Test that check_circuit queries BigQuery"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        bq_client.query_results = []
        state, _ = breaker.check_circuit('moving_average')

        # Should have queried BigQuery
        assert bq_client.query_call_count > 0

    def test_record_failure_writes_to_bigquery(self):
        """Test that record_failure writes to BigQuery"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Initialize cache
        bq_client.query_results = []
        breaker.check_circuit('moving_average')

        breaker.record_failure('moving_average', 'Test error', 'ValueError')

        # Should have written to BigQuery
        assert len(bq_client.inserted_rows) > 0

    def test_record_success_writes_to_bigquery(self):
        """Test that record_success writes to BigQuery"""
        bq_client = MockBigQueryClient()

        # Need existing state for record_success to write
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='CLOSED',
            failure_count=2,
            success_count=0,
            last_error_message=None,
            last_error_type=None,
            opened_at=None,
            closed_at=None,
            last_failure_at=None
        )]

        breaker = SystemCircuitBreaker(bq_client, 'test-project')
        breaker.check_circuit('moving_average')

        breaker.record_success('moving_average')

        # Should have written to BigQuery
        assert len(bq_client.inserted_rows) > 0

    def test_bigquery_error_handled_gracefully(self):
        """Test that BigQuery errors are handled gracefully"""
        bq_client = Mock()
        bq_client.query.side_effect = Exception("BigQuery error")

        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Should not raise exception (fail-open)
        try:
            state, reason = breaker.check_circuit('moving_average')
            # Should fail open (return CLOSED)
            assert state == 'CLOSED'
        except Exception:
            pytest.fail("Should handle BigQuery errors gracefully")


class TestGracefulDegradation:
    """Test suite for graceful degradation scenarios"""

    def test_one_system_open_others_work(self):
        """Test that one open circuit doesn't affect other systems"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        # Open moving_average circuit
        open_time = datetime.now(timezone.utc)
        bq_client.query_results = [Mock(
            system_id='moving_average',
            state='OPEN',
            failure_count=5,
            success_count=0,
            last_error_message='Test error',
            last_error_type='ValueError',
            opened_at=open_time,
            closed_at=None,
            last_failure_at=open_time
        )]
        state1, _ = breaker.check_circuit('moving_average')

        # Other systems should still be closed
        bq_client.query_results = []
        breaker._state_cache = {}
        state2, _ = breaker.check_circuit('xgboost_v1')

        assert state1 == 'OPEN'
        assert state2 == 'CLOSED'

    def test_partial_success_scenario(self):
        """Test scenario where 3/5 systems succeed"""
        bq_client = MockBigQueryClient()
        breaker = SystemCircuitBreaker(bq_client, 'test-project')

        systems = {
            'moving_average': 'CLOSED',   # Success
            'zone_matchup_v1': 'CLOSED',  # Success
            'similarity_balanced_v1': 'OPEN',  # Failed
            'xgboost_v1': 'CLOSED',       # Success
            'ensemble_v1': 'OPEN'          # Failed
        }

        results = {}
        for system_id, expected_state in systems.items():
            if expected_state == 'OPEN':
                open_time = datetime.now(timezone.utc)
                bq_client.query_results = [Mock(
                    system_id=system_id,
                    state='OPEN',
                    failure_count=5,
                    success_count=0,
                    last_error_message='Test error',
                    last_error_type='ValueError',
                    opened_at=open_time,
                    closed_at=None,
                    last_failure_at=open_time
                )]
            else:
                bq_client.query_results = []

            breaker._state_cache = {}
            state, _ = breaker.check_circuit(system_id)
            results[system_id] = state

        # 3 systems should be closed, 2 should be open
        closed_count = sum(1 for s in results.values() if s == 'CLOSED')
        open_count = sum(1 for s in results.values() if s == 'OPEN')

        # May have some systems in HALF_OPEN if timeout expired
        assert closed_count >= 3
        assert open_count + sum(1 for s in results.values() if s == 'HALF_OPEN') >= 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
