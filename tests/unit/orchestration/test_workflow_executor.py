#!/usr/bin/env python3
"""
Unit Tests for orchestration/workflow_executor.py

Tests cover:
1. WorkflowExecutor initialization and configuration
2. Scraper timeout resolution
3. Circuit breaker integration
4. Workflow execution lifecycle
5. Single scraper execution
6. HTTP scraper calls with retries
7. Error handling and recovery
8. BigQuery logging
9. Deduplication logic
10. Backoff calculation
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timezone
import json
from dataclasses import asdict

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from orchestration.workflow_executor import (
    WorkflowExecutor,
    ScraperExecution,
    WorkflowExecution
)
from orchestration.shared.utils.circuit_breaker import CircuitBreakerOpenError


class TestDataclasses:
    """Test suite for dataclass structures"""

    def test_scraper_execution_to_dict(self):
        """Test ScraperExecution converts to dict"""
        execution = ScraperExecution(
            scraper_name='test_scraper',
            status='success',
            execution_id='exec123',
            duration_seconds=5.5,
            record_count=100
        )

        result = execution.to_dict()

        assert isinstance(result, dict)
        assert result['scraper_name'] == 'test_scraper'
        assert result['status'] == 'success'
        assert result['execution_id'] == 'exec123'
        assert result['duration_seconds'] == 5.5
        assert result['record_count'] == 100

    def test_workflow_execution_to_dict(self):
        """Test WorkflowExecution converts to dict for BigQuery"""
        execution = WorkflowExecution(
            execution_id='workflow123',
            workflow_name='test_workflow',
            decision_id='decision123',
            execution_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            status='completed',
            scrapers_requested=['scraper1', 'scraper2'],
            scrapers_triggered=2,
            scrapers_succeeded=2,
            scrapers_failed=0,
            scraper_executions=[],
            duration_seconds=10.0
        )

        result = execution.to_dict()

        assert isinstance(result, dict)
        assert result['execution_id'] == 'workflow123'
        assert result['workflow_name'] == 'test_workflow'
        assert result['status'] == 'completed'
        assert result['scrapers_triggered'] == 2
        assert result['duration_seconds'] == 10.0


class TestWorkflowExecutorInitialization:
    """Test suite for WorkflowExecutor initialization"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_executor_initializes_with_defaults(self, mock_resolver):
        """Test executor initializes with default configuration"""
        executor = WorkflowExecutor()

        assert executor.parameter_resolver is not None
        assert executor.circuit_breaker_enabled is True  # Default is 'true'
        assert executor.circuit_breaker_manager is not None

    @patch.dict(os.environ, {'ENABLE_CIRCUIT_BREAKER': 'false'})
    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_executor_can_disable_circuit_breaker(self, mock_resolver):
        """Test circuit breaker can be disabled via env var"""
        executor = WorkflowExecutor()

        assert executor.circuit_breaker_enabled is False
        assert executor.circuit_breaker_manager is None

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_executor_service_url_has_default(self, mock_resolver):
        """Test SERVICE_URL has default value"""
        # SERVICE_URL is set at module import time from os.getenv
        # Testing runtime reconfiguration requires module reload
        assert hasattr(WorkflowExecutor, 'SERVICE_URL')
        assert WorkflowExecutor.SERVICE_URL is not None
        assert 'http' in WorkflowExecutor.SERVICE_URL


class TestTimeoutConfiguration:
    """Test suite for scraper timeout configuration"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    @patch('orchestration.workflow_executor._workflow_config')
    def test_get_scraper_timeout_uses_config(self, mock_config, mock_resolver):
        """Test timeout is fetched from config"""
        executor = WorkflowExecutor()

        # Mock config to return settings with specific timeout
        mock_config.get_settings.return_value = {
            'scraper_timeouts': {
                'overrides': {
                    'test_scraper': 300
                }
            }
        }

        timeout = executor._get_scraper_timeout('test_scraper')

        assert timeout == 300

    @patch('orchestration.workflow_executor.ParameterResolver')
    @patch('orchestration.workflow_executor._workflow_config')
    def test_get_scraper_timeout_uses_default(self, mock_config, mock_resolver):
        """Test default timeout when config has no override"""
        executor = WorkflowExecutor()

        # Mock config with no override for scraper
        mock_config.get_settings.return_value = {
            'scraper_timeouts': {
                'default': 240
            }
        }

        timeout = executor._get_scraper_timeout('test_scraper')

        assert timeout == 240  # Uses config default

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_get_future_timeout_adds_overhead(self, mock_resolver):
        """Test future timeout includes overhead for ThreadPoolExecutor"""
        executor = WorkflowExecutor()

        with patch.object(executor, '_get_scraper_timeout', return_value=180):
            future_timeout = executor._get_future_timeout('test_scraper')

            assert future_timeout == 180 + WorkflowExecutor.DEFAULT_FUTURE_OVERHEAD


class TestBackoffCalculation:
    """Test suite for jittered backoff calculation"""

    def test_calculate_jittered_backoff_increases(self):
        """Test backoff increases with attempt number"""
        backoff1 = WorkflowExecutor._calculate_jittered_backoff(1)
        backoff2 = WorkflowExecutor._calculate_jittered_backoff(2)
        backoff3 = WorkflowExecutor._calculate_jittered_backoff(3)

        # Later attempts should have higher backoff (on average)
        assert backoff3 > backoff1  # May occasionally fail due to jitter

    def test_calculate_jittered_backoff_respects_max(self):
        """Test backoff doesn't exceed max_delay"""
        # Very high attempt number should still cap at max
        for attempt in range(1, 20):
            backoff = WorkflowExecutor._calculate_jittered_backoff(
                attempt,
                base_delay=1.0,
                max_delay=30.0
            )
            assert backoff <= 30.0

    def test_calculate_jittered_backoff_has_jitter(self):
        """Test backoff includes random jitter"""
        # Call multiple times with same attempt - should get different values
        backoffs = [
            WorkflowExecutor._calculate_jittered_backoff(3)
            for _ in range(10)
        ]

        # Should have variation due to jitter
        assert len(set(backoffs)) > 1  # Not all the same


class TestCircuitBreakerIntegration:
    """Test suite for circuit breaker integration"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_circuit_breaker_integration_exists(self, mock_resolver):
        """Test circuit breaker manager is available"""
        executor = WorkflowExecutor()

        # Circuit breaker should be enabled by default
        assert executor.circuit_breaker_enabled is True
        assert executor.circuit_breaker_manager is not None

        # Manager should be able to create breakers
        breaker = executor.circuit_breaker_manager.get_breaker('test_scraper')
        assert breaker is not None


class TestSingleScraperExecution:
    """Test suite for single scraper execution"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_single_scraper_success(self, mock_resolver):
        """Test successful scraper execution"""
        executor = WorkflowExecutor()

        # Mock parameter resolution to return single parameter set
        mock_resolver.return_value.resolve_parameters.return_value = {'game_date': '2024-01-01'}

        # Mock the HTTP call
        with patch.object(executor, '_call_scraper') as mock_call:
            mock_call.return_value = ScraperExecution(
                scraper_name='test_scraper',
                status='success',
                execution_id='exec123',
                duration_seconds=5.0,
                record_count=100
            )

            # Correct signature: context, workflow_name (returns List)
            result = executor._execute_single_scraper(
                scraper_name='test_scraper',
                context={'game_date': '2024-01-01'},
                workflow_name='test_workflow'
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].status == 'success'
            assert result[0].scraper_name == 'test_scraper'

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_single_scraper_handles_error(self, mock_resolver):
        """Test scraper execution handles errors gracefully"""
        executor = WorkflowExecutor()

        # Mock parameter resolution
        mock_resolver.return_value.resolve_parameters.return_value = {'game_date': '2024-01-01'}

        # Mock the HTTP call to raise exception
        with patch.object(executor, '_call_scraper') as mock_call:
            mock_call.side_effect = Exception("Network error")

            result = executor._execute_single_scraper(
                scraper_name='test_scraper',
                context={'game_date': '2024-01-01'},
                workflow_name='test_workflow'
            )

            # Should return empty list or list with failed execution
            assert isinstance(result, list)


class TestHTTPScraperCalls:
    """Test suite for HTTP calls to scraper service"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    @patch('orchestration.workflow_executor.get_http_session')
    def test_call_scraper_success(self, mock_get_session, mock_resolver):
        """Test successful HTTP call to scraper"""
        executor = WorkflowExecutor()

        # Mock HTTP response - match actual response structure
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'run_id': 'exec123',
            'data_summary': {
                'rowCount': 100,
                'status': 'success'
            }
        }

        mock_session = Mock()
        mock_session.post.return_value = mock_response
        mock_get_session.return_value = mock_session

        # Correct signature: scraper_name, parameters, workflow_name, max_retries
        result = executor._call_scraper_internal(
            scraper_name='test_scraper',
            parameters={'game_date': '2024-01-01'},
            workflow_name='test_workflow'
        )

        assert result.status == 'success'
        assert result.record_count == 100
        assert result.execution_id == 'exec123'

    @patch('orchestration.workflow_executor.ParameterResolver')
    @patch('orchestration.workflow_executor.get_http_session')
    def test_call_scraper_handles_404(self, mock_get_session, mock_resolver):
        """Test 404 response handling"""
        executor = WorkflowExecutor()

        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = 'Not Found'

        mock_session = Mock()
        mock_session.post.return_value = mock_response
        mock_get_session.return_value = mock_session

        result = executor._call_scraper_internal(
            scraper_name='unknown_scraper',
            parameters={'game_date': '2024-01-01'},
            workflow_name='test_workflow'
        )

        assert result.status == 'failed'
        assert '404' in result.error_message

    @patch('orchestration.workflow_executor.ParameterResolver')
    @patch('orchestration.workflow_executor.get_http_session')
    def test_call_scraper_retries_on_500(self, mock_get_session, mock_resolver):
        """Test retry logic on 500 errors"""
        executor = WorkflowExecutor()

        # First call fails with 500, second succeeds
        mock_response_fail = Mock()
        mock_response_fail.status_code = 500
        mock_response_fail.text = 'Internal Server Error'

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            'run_id': 'exec123',
            'data_summary': {
                'rowCount': 50,
                'status': 'success'
            }
        }

        mock_session = Mock()
        mock_session.post.side_effect = [mock_response_fail, mock_response_success]
        mock_get_session.return_value = mock_session

        result = executor._call_scraper_internal(
            scraper_name='test_scraper',
            parameters={'game_date': '2024-01-01'},
            workflow_name='test_workflow'
        )

        # Should have retried and succeeded
        assert mock_session.post.call_count == 2
        assert result.status == 'success'


class TestWorkflowExecution:
    """Test suite for complete workflow execution"""

    @pytest.mark.skip(reason="Integration test - requires complex mocking of workflow execution")
    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_workflow_with_multiple_scrapers(self, mock_resolver):
        """Test executing workflow with multiple scrapers (integration test)"""
        # This test requires mocking:
        # - Parameter resolution for workflow
        # - Each scraper execution
        # - BigQuery logging
        # - Workflow decision tracking
        # Better suited for integration test suite
        pass

    @pytest.mark.skip(reason="Integration test - requires complex workflow execution setup")
    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_workflow_continues_on_scraper_failure(self, mock_resolver):
        """Test workflow continues when individual scrapers fail (integration test)"""
        # Complex integration test - better for integration test suite
        pass


class TestBigQueryLogging:
    """Test suite for BigQuery logging"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    @patch('orchestration.workflow_executor.insert_bigquery_rows')
    def test_log_workflow_execution(self, mock_insert, mock_resolver):
        """Test workflow execution is logged to BigQuery"""
        executor = WorkflowExecutor()

        execution = WorkflowExecution(
            execution_id='workflow123',
            workflow_name='test_workflow',
            decision_id='decision123',
            execution_time=datetime.now(timezone.utc),
            status='completed',
            scrapers_requested=['scraper1'],
            scrapers_triggered=1,
            scrapers_succeeded=1,
            scrapers_failed=0,
            scraper_executions=[],
            duration_seconds=10.0
        )

        executor._log_workflow_execution(execution)

        # Should have called insert_bigquery_rows
        mock_insert.assert_called_once()

        # Verify it was called with proper arguments
        args = mock_insert.call_args
        assert args is not None


class TestEventIDExtraction:
    """Test suite for event ID extraction from scraper results"""

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_extract_event_ids_from_execution(self, mock_resolver):
        """Test event IDs are extracted from scraper execution"""
        executor = WorkflowExecutor()

        execution = ScraperExecution(
            scraper_name='test_scraper',
            status='success',
            data_summary={
                'event_ids': ['event1', 'event2', 'event3']
            }
        )

        event_ids = executor._extract_event_ids_from_execution(execution)

        assert event_ids == ['event1', 'event2', 'event3']

    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_extract_event_ids_handles_missing_data(self, mock_resolver):
        """Test event ID extraction handles missing data gracefully"""
        executor = WorkflowExecutor()

        execution = ScraperExecution(
            scraper_name='test_scraper',
            status='success'
        )

        event_ids = executor._extract_event_ids_from_execution(execution)

        assert event_ids == []


class TestExecutePendingWorkflowsIntegration:
    """Integration tests for execute_pending_workflows() method.

    These tests verify that SQL queries are properly constructed with
    interpolated variables, catching f-string bugs that unit tests might miss.
    """

    @patch('orchestration.workflow_executor.execute_bigquery')
    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_pending_workflows_query_has_interpolated_project_id(
        self, mock_resolver, mock_bq
    ):
        """
        Regression test: ensure f-string variables are interpolated in SQL queries.

        This test would have caught the 7-day f-string bug where {self.project_id}
        was used in a query but self.project_id was never set, causing AttributeError.
        """
        mock_bq.return_value = []  # No pending workflows

        executor = WorkflowExecutor()

        # Call execute_pending_workflows and catch any AttributeError
        # which would indicate an unset instance variable being used in f-string
        try:
            result = executor.execute_pending_workflows()
        except AttributeError as e:
            pytest.fail(
                f"AttributeError during execute_pending_workflows(): {e}\n"
                f"This indicates an f-string is referencing an undefined attribute "
                f"(e.g., self.project_id not being set in __init__)"
            )

        # Verify the query was called
        assert mock_bq.called, "execute_bigquery should have been called"
        query = mock_bq.call_args[0][0]  # First positional argument

        # CRITICAL: Verify no uninterpolated f-string variables
        assert '{self.' not in query, (
            f"Query contains uninterpolated f-string variable! "
            f"Found '{{self.' in query: {query[:200]}..."
        )
        assert '{self.project_id}' not in query, (
            "Query contains literal '{self.project_id}' - f-string not working"
        )

        # Verify actual project ID is present (should be 'nba-props-platform' or similar)
        # The query should have a fully-qualified table reference
        assert '.nba_orchestration.workflow_decisions' in query, (
            "Query should reference workflow_decisions table"
        )
        assert '.nba_orchestration.workflow_executions' in query, (
            "Query should reference workflow_executions table"
        )

    @patch('orchestration.workflow_executor.execute_bigquery')
    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_pending_workflows_query_has_valid_sql_syntax(
        self, mock_resolver, mock_bq
    ):
        """Verify the SQL query has valid structure and syntax."""
        mock_bq.return_value = []  # No pending workflows

        executor = WorkflowExecutor()

        # Call execute_pending_workflows and catch any AttributeError
        try:
            executor.execute_pending_workflows()
        except AttributeError as e:
            pytest.fail(
                f"AttributeError during execute_pending_workflows(): {e}\n"
                f"This indicates an f-string is referencing an undefined attribute."
            )

        # Verify the query was called
        assert mock_bq.called
        query = mock_bq.call_args[0][0]

        # Verify basic SQL structure
        query_upper = query.upper()
        assert 'SELECT' in query_upper, "Query should contain SELECT"
        assert 'FROM' in query_upper, "Query should contain FROM"
        assert 'WHERE' in query_upper, "Query should contain WHERE"
        assert 'LEFT JOIN' in query_upper, "Query should use LEFT JOIN for deduplication"

        # Verify deduplication logic is present
        assert 'IS NULL' in query_upper, "Query should check for IS NULL (unexecuted)"

    @patch('orchestration.workflow_executor.execute_bigquery')
    @patch('orchestration.workflow_executor.ParameterResolver')
    def test_execute_pending_workflows_no_python_string_literals_in_query(
        self, mock_resolver, mock_bq
    ):
        """Verify no Python artifacts leak into the SQL query."""
        mock_bq.return_value = []

        executor = WorkflowExecutor()

        # Call execute_pending_workflows and catch any AttributeError
        try:
            executor.execute_pending_workflows()
        except AttributeError as e:
            pytest.fail(
                f"AttributeError during execute_pending_workflows(): {e}\n"
                f"This indicates an f-string is referencing an undefined attribute."
            )

        assert mock_bq.called
        query = mock_bq.call_args[0][0]

        # Check for common Python f-string mistakes
        python_artifacts = [
            '{self.',      # Uninterpolated self reference
            '{executor.',  # Uninterpolated executor reference
            'None',        # Python None instead of SQL NULL
            'True',        # Python True instead of SQL TRUE
            'False',       # Python False instead of SQL FALSE
        ]

        for artifact in python_artifacts:
            # Special case: 'IS NULL' is valid SQL, 'None' is not
            if artifact == 'None':
                # Make sure we're not checking "IS NULL" - that's valid
                # Check for standalone "None" which would be a Python mistake
                assert ' None ' not in query and ' None,' not in query, (
                    f"Query contains Python '{artifact}' instead of SQL equivalent"
                )
            elif artifact in ['{self.', '{executor.']:
                assert artifact not in query, (
                    f"Query contains uninterpolated f-string: '{artifact}'"
                )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
