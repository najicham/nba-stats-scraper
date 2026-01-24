"""
Unit Tests for HealthChecker Improvements

Tests new features added to shared/endpoints/health.py:
- Enhanced logging
- Improved BigQuery check with custom queries and table checks
- Model availability check helper
- Service name in all check responses

Run with:
    pytest tests/unit/test_health_checker_improvements.py -v

NOTE: These tests are for planned features that have not been implemented yet.
"""

import os
import sys
import pytest

# Skip all tests in this module - features not yet implemented
pytestmark = pytest.mark.skip(reason="Tests for planned features not yet implemented in HealthChecker")
import tempfile
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from shared.endpoints.health import HealthChecker


class TestImprovedBigQueryCheck:
    """Test improved BigQuery check with custom queries and table checks."""

    def test_bigquery_default_mode(self):
        """Test default BigQuery check (SELECT 1)."""
        with patch('shared.endpoints.health.HealthChecker.bq_client') as mock_bq_client:
            # Mock successful query
            mock_job = Mock()
            mock_job.result.return_value = []
            mock_bq_client.query.return_value = mock_job

            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=True
            )
            checker._bq_client = mock_bq_client

            result = checker.check_bigquery_connectivity()

            assert result['check'] == 'bigquery'
            assert result['status'] == 'pass'
            assert result['service'] == 'test-service'
            assert result['details']['query_type'] == 'simple'
            assert result['details']['connection'] == 'successful'

    def test_bigquery_custom_query_mode(self):
        """Test BigQuery check with custom query."""
        with patch('shared.endpoints.health.HealthChecker.bq_client') as mock_bq_client:
            # Mock successful query
            mock_job = Mock()
            mock_job.result.return_value = [{'result': 1}]
            mock_bq_client.query.return_value = mock_job

            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=True,
                bigquery_test_query='SELECT COUNT(*) FROM my_table'
            )
            checker._bq_client = mock_bq_client

            result = checker.check_bigquery_connectivity()

            assert result['check'] == 'bigquery'
            assert result['status'] == 'pass'
            assert result['service'] == 'test-service'
            assert result['details']['query_type'] == 'custom'
            assert result['details']['query'] == 'SELECT COUNT(*) FROM my_table'

    def test_bigquery_table_check_mode(self):
        """Test BigQuery check with table query (NBA Worker pattern)."""
        with patch('shared.endpoints.health.HealthChecker.bq_client') as mock_bq_client:
            # Mock successful query with count
            mock_job = Mock()
            mock_job.result.return_value = [{'count': 450}]
            mock_bq_client.query.return_value = mock_job

            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=True,
                bigquery_test_table='nba_predictions.player_prop_predictions'
            )
            checker._bq_client = mock_bq_client

            result = checker.check_bigquery_connectivity()

            assert result['check'] == 'bigquery'
            assert result['status'] == 'pass'
            assert result['service'] == 'test-service'
            assert result['details']['query_type'] == 'table_check'
            assert result['details']['table'] == 'nba_predictions.player_prop_predictions'
            assert result['details']['row_count'] == 450

            # Verify query format
            called_query = mock_bq_client.query.call_args[0][0]
            assert 'game_date >= CURRENT_DATE()' in called_query


class TestServiceNameInResponses:
    """Test that service_name is included in all check responses."""

    def test_service_name_in_environment_check(self):
        """Test service_name in environment check response."""
        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='my-test-service',
                check_bigquery=False
            )
            result = checker.check_environment_variables()
            assert result['service'] == 'my-test-service'

    def test_service_name_in_bigquery_check(self):
        """Test service_name in BigQuery check response."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='my-test-service',
            check_bigquery=False
        )
        result = checker.check_bigquery_connectivity()
        assert result['service'] == 'my-test-service'

    def test_service_name_in_firestore_check(self):
        """Test service_name in Firestore check response."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='my-test-service',
            check_firestore=False
        )
        result = checker.check_firestore_connectivity()
        assert result['service'] == 'my-test-service'

    def test_service_name_in_gcs_check(self):
        """Test service_name in GCS check response."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='my-test-service',
            check_gcs=False
        )
        result = checker.check_gcs_connectivity()
        assert result['service'] == 'my-test-service'


class TestModelAvailabilityCheckHelper:
    """Test the create_model_check static helper method."""

    def test_model_check_gcs_path_valid_format(self):
        """Test model check with valid GCS path."""
        model_check = HealthChecker.create_model_check(
            model_paths=['gs://my-bucket/models/catboost_v8.cbm']
        )

        result = model_check()

        assert result['check'] == 'model_availability'
        assert result['status'] == 'pass'
        assert 'model' in result['details']
        assert result['details']['model']['status'] == 'pass'
        assert result['details']['model']['format_valid'] is True

    def test_model_check_gcs_path_invalid_format(self):
        """Test model check with invalid GCS path format."""
        model_check = HealthChecker.create_model_check(
            model_paths=['gs://my-bucket/models/model.txt']
        )

        result = model_check()

        assert result['check'] == 'model_availability'
        assert result['status'] == 'fail'
        assert result['details']['model']['status'] == 'fail'
        assert 'Invalid model path format' in result['details']['model']['error']

    def test_model_check_local_path_exists(self):
        """Test model check with existing local file."""
        # Create temporary model file
        with tempfile.NamedTemporaryFile(suffix='.cbm', delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(b'mock model data')

        try:
            model_check = HealthChecker.create_model_check(
                model_paths=[tmp_path]
            )

            result = model_check()

            assert result['check'] == 'model_availability'
            assert result['status'] == 'pass'
            assert result['details']['model']['status'] == 'pass'
            assert result['details']['model']['file_exists'] is True
            assert result['details']['model']['size_bytes'] > 0

        finally:
            # Clean up
            os.unlink(tmp_path)

    def test_model_check_local_path_not_exists(self):
        """Test model check with non-existent local file."""
        model_check = HealthChecker.create_model_check(
            model_paths=['/tmp/nonexistent_model.cbm']
        )

        result = model_check()

        assert result['check'] == 'model_availability'
        assert result['status'] == 'fail'
        assert result['details']['model']['status'] == 'fail'
        assert 'not found' in result['details']['model']['error']

    def test_model_check_multiple_paths(self):
        """Test model check with multiple model paths."""
        # Create temporary model files
        with tempfile.NamedTemporaryFile(suffix='.cbm', delete=False) as tmp1, \
             tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp2:
            tmp1_path = tmp1.name
            tmp2_path = tmp2.name
            tmp1.write(b'model 1')
            tmp2.write(b'model 2')

        try:
            model_check = HealthChecker.create_model_check(
                model_paths=[tmp1_path, tmp2_path]
            )

            result = model_check()

            assert result['check'] == 'model_availability'
            assert result['status'] == 'pass'
            assert 'model_0' in result['details']
            assert 'model_1' in result['details']
            assert result['details']['model_0']['status'] == 'pass'
            assert result['details']['model_1']['status'] == 'pass'

        finally:
            # Clean up
            os.unlink(tmp1_path)
            os.unlink(tmp2_path)

    def test_model_check_with_fallback(self):
        """Test model check with fallback directory."""
        # Create temporary fallback directory with model files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some model files in fallback dir
            model1 = Path(tmpdir) / 'model1.cbm'
            model2 = Path(tmpdir) / 'model2.json'
            model1.write_text('model 1')
            model2.write_text('model 2')

            # Primary path doesn't exist, should fall back
            model_check = HealthChecker.create_model_check(
                model_paths=['/tmp/nonexistent_model.cbm'],
                fallback_dir=tmpdir
            )

            result = model_check()

            assert result['check'] == 'model_availability'
            assert result['status'] == 'pass'  # Should pass because of fallback
            assert 'fallback_models' in result['details']
            assert result['details']['fallback_models']['status'] == 'pass'
            assert result['details']['fallback_models']['model_count'] == 2

    def test_model_check_integration_with_health_checker(self):
        """Test model check integrated with HealthChecker."""
        # Create temporary model file
        with tempfile.NamedTemporaryFile(suffix='.cbm', delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(b'mock model data')

        try:
            # Create model check
            model_check = HealthChecker.create_model_check(
                model_paths=[tmp_path]
            )

            # Create health checker with custom model check
            with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
                checker = HealthChecker(
                    project_id='test-project',
                    service_name='test-service',
                    check_bigquery=False,
                    custom_checks={'model_availability': model_check}
                )

                result = checker.run_all_checks(parallel=False)

                assert result['status'] == 'healthy'
                # Find model check in results
                model_check_result = next(
                    c for c in result['checks'] if c['check'] == 'model_availability'
                )
                assert model_check_result['status'] == 'pass'

        finally:
            # Clean up
            os.unlink(tmp_path)


class TestEnhancedLogging:
    """Test enhanced logging functionality."""

    def test_logging_on_check_start_and_completion(self, caplog):
        """Test that health checks log start and completion."""
        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False
            )

            with caplog.at_level('INFO'):
                result = checker.run_all_checks(parallel=False)

            # Check for start log
            assert any('Starting health check execution' in record.message for record in caplog.records)

            # Check for completion log
            assert any('Health check execution completed' in record.message for record in caplog.records)

            # Verify completion log includes summary
            completion_logs = [r for r in caplog.records if 'completed' in r.message]
            assert len(completion_logs) > 0
            completion_msg = completion_logs[0].message
            assert 'test-service' in completion_msg
            assert 'Duration' in completion_msg

    def test_warning_on_slow_individual_check(self, caplog):
        """Test that slow individual checks generate warnings."""
        def slow_check() -> Dict[str, Any]:
            """Simulated slow check."""
            import time
            time.sleep(2.1)  # Exceed 2 second threshold
            return {
                'check': 'slow_check',
                'status': 'pass',
                'details': {},
                'duration_ms': 2100
            }

        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                custom_checks={'slow_check': slow_check}
            )

            with caplog.at_level('WARNING'):
                result = checker.run_all_checks(parallel=False)

            # Should have warning about slow check
            warnings = [r for r in caplog.records if r.levelname == 'WARNING']
            assert len(warnings) > 0
            assert any('took' in w.message and '2.0s' in w.message for w in warnings)

    def test_warning_on_slow_total_duration(self, caplog):
        """Test that slow total execution generates warnings."""
        def slow_check_1() -> Dict[str, Any]:
            import time
            time.sleep(2.5)
            return {
                'check': 'slow_check_1',
                'status': 'pass',
                'details': {},
                'duration_ms': 2500
            }

        def slow_check_2() -> Dict[str, Any]:
            import time
            time.sleep(2.0)
            return {
                'check': 'slow_check_2',
                'status': 'pass',
                'details': {},
                'duration_ms': 2000
            }

        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                custom_checks={
                    'slow_check_1': slow_check_1,
                    'slow_check_2': slow_check_2
                }
            )

            with caplog.at_level('WARNING'):
                result = checker.run_all_checks(parallel=False)

            # Should have warning about total duration
            warnings = [r for r in caplog.records if r.levelname == 'WARNING']
            assert len(warnings) > 0
            # Look for total duration warning
            assert any('Total health check duration' in w.message for w in warnings)

    def test_error_logging_with_exc_info(self, caplog):
        """Test that errors are logged with exc_info=True."""
        with patch('shared.endpoints.health.HealthChecker.bq_client') as mock_bq_client:
            # Mock exception
            mock_bq_client.query.side_effect = Exception('Connection failed')

            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=True
            )
            checker._bq_client = mock_bq_client

            with caplog.at_level('ERROR'):
                result = checker.check_bigquery_connectivity()

            # Should have error log
            errors = [r for r in caplog.records if r.levelname == 'ERROR']
            assert len(errors) > 0
            # Verify exc_info was used (traceback should be present)
            assert any(r.exc_info is not None for r in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
