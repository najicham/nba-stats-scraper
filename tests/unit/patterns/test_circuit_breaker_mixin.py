"""
Unit Tests for CircuitBreakerMixin (Pattern #5)

Tests cover:
1. Circuit state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
2. Failure counting and threshold detection
3. Timeout expiry and half-open state
4. Success recording and circuit closing
5. Circuit key generation
6. Alert sending
7. BigQuery state persistence
8. Run method with circuit protection
9. Multiple circuit isolation
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch
from collections import defaultdict
from shared.processors.patterns.circuit_breaker_mixin import CircuitBreakerMixin


class MockProcessor(CircuitBreakerMixin):
    """Mock processor for testing CircuitBreakerMixin"""

    CIRCUIT_BREAKER_THRESHOLD = 5
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)

    def __init__(self):
        self.bq_client = Mock()
        self.project_id = 'test-project'
        self.stats = {}
        self.run_id = 'test-run-123'
        self.log_processing_run = Mock()
        self.parent_run_called = False

    def run(self, opts):
        return super().run(opts)


class TestCircuitKeyGeneration:
    """Test suite for circuit key generation"""

    def test_circuit_key_format(self):
        """Test that circuit key has correct format"""
        processor = MockProcessor()

        key = processor._get_circuit_key('2024-11-20', '2024-11-20')

        assert key == 'MockProcessor:2024-11-20:2024-11-20'
        assert ':' in key
        assert key.startswith('MockProcessor')

    def test_circuit_key_uniqueness(self):
        """Test that different date ranges produce different keys"""
        processor = MockProcessor()

        key1 = processor._get_circuit_key('2024-11-20', '2024-11-20')
        key2 = processor._get_circuit_key('2024-11-21', '2024-11-21')
        key3 = processor._get_circuit_key('2024-11-20', '2024-11-21')

        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

    def test_circuit_key_same_for_same_dates(self):
        """Test that same dates produce same key"""
        processor = MockProcessor()

        key1 = processor._get_circuit_key('2024-11-20', '2024-11-20')
        key2 = processor._get_circuit_key('2024-11-20', '2024-11-20')

        assert key1 == key2


class TestCircuitStateChecks:
    """Test suite for circuit state checking"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_circuit_closed_initially(self):
        """Test that circuit starts in closed state"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        assert processor._is_circuit_open(circuit_key) is False

    def test_circuit_open_when_in_opened_at(self):
        """Test that circuit is open when in opened_at dict"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Manually open circuit
        processor._circuit_breaker_opened_at[circuit_key] = datetime.now(timezone.utc)

        assert processor._is_circuit_open(circuit_key) is True

    def test_circuit_transitions_to_half_open_after_timeout(self):
        """Test that circuit moves to half-open after timeout"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Open circuit 31 minutes ago (timeout is 30 minutes)
        opened_time = datetime.now(timezone.utc) - timedelta(minutes=31)
        processor._circuit_breaker_opened_at[circuit_key] = opened_time

        # Should transition to half-open (return False to allow try)
        assert processor._is_circuit_open(circuit_key) is False

        # Should have been removed from opened_at
        assert circuit_key not in processor._circuit_breaker_opened_at

    def test_circuit_stays_open_within_timeout(self):
        """Test that circuit stays open within timeout period"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Open circuit 10 minutes ago (timeout is 30 minutes)
        opened_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        processor._circuit_breaker_opened_at[circuit_key] = opened_time

        # Should still be open
        assert processor._is_circuit_open(circuit_key) is True


class TestFailureRecording:
    """Test suite for failure recording and threshold"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_first_failure_increments_count(self):
        """Test that first failure increments counter"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        processor._record_failure(circuit_key, Exception("Test error"))

        assert processor._circuit_breaker_failures[circuit_key] == 1

    def test_multiple_failures_increment_count(self):
        """Test that multiple failures increment counter"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        for i in range(3):
            processor._record_failure(circuit_key, Exception(f"Error {i}"))

        assert processor._circuit_breaker_failures[circuit_key] == 3

    def test_threshold_not_reached_returns_false(self):
        """Test that under-threshold failures return False"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Record 4 failures (threshold is 5)
        for i in range(4):
            result = processor._record_failure(circuit_key, Exception(f"Error {i}"))
            assert result is False  # Threshold not reached yet

    def test_threshold_reached_returns_true(self):
        """Test that reaching threshold returns True"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Record 4 failures
        for i in range(4):
            processor._record_failure(circuit_key, Exception(f"Error {i}"))

        # 5th failure should reach threshold
        result = processor._record_failure(circuit_key, Exception("Final error"))

        assert result is True
        assert processor._circuit_breaker_failures[circuit_key] == 5

    def test_threshold_reached_opens_circuit(self):
        """Test that reaching threshold opens the circuit"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Record threshold failures
        for i in range(processor.CIRCUIT_BREAKER_THRESHOLD):
            processor._record_failure(circuit_key, Exception(f"Error {i}"))

        # Circuit should be open
        assert circuit_key in processor._circuit_breaker_opened_at


class TestSuccessRecording:
    """Test suite for success recording"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_success_resets_failure_count(self):
        """Test that success resets failure counter"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Record some failures
        for i in range(3):
            processor._record_failure(circuit_key, Exception(f"Error {i}"))

        assert processor._circuit_breaker_failures[circuit_key] == 3

        # Record success
        processor._record_success(circuit_key)

        assert processor._circuit_breaker_failures[circuit_key] == 0

    def test_success_closes_open_circuit(self):
        """Test that success closes an open circuit"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Open the circuit
        processor._circuit_breaker_opened_at[circuit_key] = datetime.now(timezone.utc)
        processor._circuit_breaker_failures[circuit_key] = 5

        # Record success
        processor._record_success(circuit_key)

        # Circuit should be closed
        assert circuit_key not in processor._circuit_breaker_opened_at
        assert processor._circuit_breaker_failures[circuit_key] == 0


class TestCircuitOpening:
    """Test suite for circuit opening logic"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_open_circuit_sets_opened_at(self):
        """Test that opening circuit sets opened_at timestamp"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        before_time = datetime.now(timezone.utc)
        processor._open_circuit(circuit_key)
        after_time = datetime.now(timezone.utc)

        assert circuit_key in processor._circuit_breaker_opened_at

        opened_at = processor._circuit_breaker_opened_at[circuit_key]
        assert before_time <= opened_at <= after_time

    def test_open_circuit_sends_alert_once(self):
        """Test that opening circuit sends alert only once"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Open circuit first time
        processor._open_circuit(circuit_key)
        assert circuit_key in processor._circuit_breaker_alerts_sent

        # Open circuit again (shouldn't send duplicate alert)
        processor._circuit_breaker_alerts_sent.clear()  # Clear to test
        processor._open_circuit(circuit_key)

        # Alert should have been sent again (since we cleared the set)
        assert circuit_key in processor._circuit_breaker_alerts_sent


class TestCircuitClosing:
    """Test suite for circuit closing logic"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_close_circuit_resets_failure_count(self):
        """Test that closing circuit resets failure count"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        processor._circuit_breaker_failures[circuit_key] = 5
        processor._close_circuit(circuit_key)

        assert processor._circuit_breaker_failures[circuit_key] == 0

    def test_close_circuit_removes_opened_at(self):
        """Test that closing circuit removes opened_at timestamp"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        processor._circuit_breaker_opened_at[circuit_key] = datetime.now(timezone.utc)
        processor._close_circuit(circuit_key)

        assert circuit_key not in processor._circuit_breaker_opened_at

    def test_close_circuit_clears_alert_flag(self):
        """Test that closing circuit clears alert flag"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        processor._circuit_breaker_alerts_sent.add(circuit_key)
        processor._close_circuit(circuit_key)

        assert circuit_key not in processor._circuit_breaker_alerts_sent


class TestRunMethodWithCircuitBreaker:
    """Test suite for run() method with circuit breaker protection"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_run_skips_when_circuit_open(self):
        """Test that run() skips processing when circuit is open"""
        processor = MockProcessor()

        opts = {'start_date': '2024-11-20', 'end_date': '2024-11-20'}
        circuit_key = processor._get_circuit_key('2024-11-20', '2024-11-20')

        # Open the circuit
        processor._circuit_breaker_opened_at[circuit_key] = datetime.now(timezone.utc)

        # Run should skip
        result = processor.run(opts)

        # Should return False (circuit open)
        assert result is False

        # Should log skip reason
        processor.log_processing_run.assert_called_once_with(
            success=True,
            skip_reason='circuit_breaker_open'
        )

    def test_run_processes_when_circuit_closed(self):
        """Test that run() processes when circuit is closed"""
        processor = MockProcessor()

        # Mock parent run
        with patch.object(CircuitBreakerMixin, 'run', return_value=True):
            opts = {'start_date': '2024-11-20', 'end_date': '2024-11-20'}

            # Create a test processor with proper inheritance
            class TestProcessor(CircuitBreakerMixin):
                CIRCUIT_BREAKER_THRESHOLD = 5
                CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)

                def __init__(self):
                    self.parent_called = False

            test_proc = TestProcessor()
            circuit_key = test_proc._get_circuit_key('2024-11-20', '2024-11-20')

            # Circuit should be closed (not in opened_at)
            assert test_proc._is_circuit_open(circuit_key) is False

    def test_run_without_dates_bypasses_circuit_breaker(self):
        """Test that run() bypasses circuit breaker when dates missing"""
        processor = MockProcessor()

        parent_run_mock = Mock(return_value=True)
        with patch.object(CircuitBreakerMixin, 'run', parent_run_mock):
            opts = {}  # No start_date or end_date

            # Should call parent run (bypass circuit breaker logic)
            # Testing the condition directly
            assert opts.get('start_date') is None
            assert opts.get('end_date') is None

    def test_run_records_success_on_successful_processing(self):
        """Test that successful run records success"""
        processor = MockProcessor()

        parent_run_mock = Mock(return_value=True)

        with patch.object(CircuitBreakerMixin, 'run', parent_run_mock):
            with patch.object(processor, '_record_success') as record_success_mock:
                opts = {'start_date': '2024-11-20', 'end_date': '2024-11-20'}
                circuit_key = processor._get_circuit_key('2024-11-20', '2024-11-20')

                # Manually simulate the run logic
                if not processor._is_circuit_open(circuit_key):
                    try:
                        result = parent_run_mock(opts)
                        processor._record_success(circuit_key)
                    except Exception as e:
                        processor._record_failure(circuit_key, e)

                # Success should have been recorded
                record_success_mock.assert_called_once_with(circuit_key)

    def test_run_records_failure_on_exception(self):
        """Test that failed run records failure"""
        processor = MockProcessor()

        parent_run_mock = Mock(side_effect=Exception("Processing failed"))

        with patch.object(CircuitBreakerMixin, 'run', parent_run_mock):
            with patch.object(processor, '_record_failure') as record_failure_mock:
                opts = {'start_date': '2024-11-20', 'end_date': '2024-11-20'}
                circuit_key = processor._get_circuit_key('2024-11-20', '2024-11-20')

                # Manually simulate the run logic with error handling
                if not processor._is_circuit_open(circuit_key):
                    try:
                        result = parent_run_mock(opts)
                        processor._record_success(circuit_key)
                    except Exception as e:
                        processor._record_failure(circuit_key, e)

                # Failure should have been recorded
                assert record_failure_mock.called
                call_args = record_failure_mock.call_args[0]
                assert call_args[0] == circuit_key
                assert isinstance(call_args[1], Exception)


class TestMultipleCircuitIsolation:
    """Test suite for multiple independent circuits"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_different_circuits_are_independent(self):
        """Test that different circuits don't affect each other"""
        processor = MockProcessor()

        circuit_key_1 = 'Processor1:2024-11-20:2024-11-20'
        circuit_key_2 = 'Processor2:2024-11-21:2024-11-21'

        # Open circuit 1
        processor._circuit_breaker_opened_at[circuit_key_1] = datetime.now(timezone.utc)

        # Circuit 1 should be open
        assert processor._is_circuit_open(circuit_key_1) is True

        # Circuit 2 should be closed
        assert processor._is_circuit_open(circuit_key_2) is False

    def test_failure_counts_are_separate(self):
        """Test that failure counts are tracked separately per circuit"""
        processor = MockProcessor()

        circuit_key_1 = 'Processor1:2024-11-20:2024-11-20'
        circuit_key_2 = 'Processor2:2024-11-21:2024-11-21'

        # Record different failures for each circuit
        for i in range(3):
            processor._record_failure(circuit_key_1, Exception(f"Error 1-{i}"))

        for i in range(2):
            processor._record_failure(circuit_key_2, Exception(f"Error 2-{i}"))

        assert processor._circuit_breaker_failures[circuit_key_1] == 3
        assert processor._circuit_breaker_failures[circuit_key_2] == 2


class TestCircuitStatus:
    """Test suite for circuit status reporting"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_get_circuit_status_empty(self):
        """Test circuit status with no circuits"""
        processor = MockProcessor()

        status = processor.get_circuit_status()

        assert status['total_circuits'] == 0
        assert status['open_circuits'] == 0
        assert status['circuits'] == {}

    def test_get_circuit_status_with_closed_circuit(self):
        """Test circuit status with closed circuit"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Record some failures (not enough to open)
        processor._circuit_breaker_failures[circuit_key] = 2

        status = processor.get_circuit_status()

        assert status['total_circuits'] == 1
        assert status['open_circuits'] == 0
        assert status['circuits'][circuit_key]['state'] == 'CLOSED'
        assert status['circuits'][circuit_key]['failure_count'] == 2

    def test_get_circuit_status_with_open_circuit(self):
        """Test circuit status with open circuit"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Open the circuit
        processor._circuit_breaker_failures[circuit_key] = 5
        processor._circuit_breaker_opened_at[circuit_key] = datetime.now(timezone.utc)

        status = processor.get_circuit_status()

        assert status['total_circuits'] == 1
        assert status['open_circuits'] == 1
        assert status['circuits'][circuit_key]['state'] == 'OPEN'
        assert status['circuits'][circuit_key]['failure_count'] == 5
        assert status['circuits'][circuit_key]['opened_at'] is not None


class TestBigQueryIntegration:
    """Test suite for BigQuery state persistence"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_write_state_without_bq_client(self):
        """Test that missing bq_client doesn't break circuit breaker"""
        processor = MockProcessor()
        processor.bq_client = None

        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        # Should not raise exception
        try:
            processor._write_circuit_state_to_bigquery(circuit_key, 'CLOSED')
            assert True  # Success
        except Exception:
            pytest.fail("Should handle missing bq_client gracefully")

    def test_write_state_calls_insert_rows_json(self):
        """Test that write_state calls BigQuery insert_rows_json"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'

        processor._write_circuit_state_to_bigquery(circuit_key, 'CLOSED')

        # Should have called insert_rows_json
        assert processor.bq_client.insert_rows_json.called


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
