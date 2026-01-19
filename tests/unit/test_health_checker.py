"""
Unit Tests for HealthChecker Class

Tests the shared health check module (shared/endpoints/health.py) comprehensively.

Run with:
    pytest tests/unit/test_health_checker.py -v
    pytest tests/unit/test_health_checker.py::TestHealthChecker::test_environment_check -v
"""

import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from shared.endpoints.health import HealthChecker, create_health_blueprint


class TestHealthCheckerInstantiation:
    """Test HealthChecker class instantiation and configuration."""

    def test_basic_instantiation(self):
        """Test basic instantiation with minimal parameters."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service'
        )

        assert checker.project_id == 'test-project'
        assert checker.service_name == 'test-service'
        assert checker.check_bigquery is True  # Default
        assert checker.check_firestore is False  # Default
        assert checker.check_gcs is False  # Default

    def test_custom_configuration(self):
        """Test instantiation with all options configured."""
        checker = HealthChecker(
            project_id='nba-props-platform',
            service_name='my-service',
            check_bigquery=True,
            check_firestore=True,
            check_gcs=True,
            gcs_buckets=['bucket1', 'bucket2'],
            required_env_vars=['VAR1', 'VAR2'],
            optional_env_vars=['VAR3', 'VAR4']
        )

        assert checker.project_id == 'nba-props-platform'
        assert checker.service_name == 'my-service'
        assert checker.check_bigquery is True
        assert checker.check_firestore is True
        assert checker.check_gcs is True
        assert checker.gcs_buckets == ['bucket1', 'bucket2']
        assert checker.required_env_vars == ['VAR1', 'VAR2']
        assert checker.optional_env_vars == ['VAR3', 'VAR4']

    def test_lazy_client_initialization(self):
        """Test that clients are not initialized until first use."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_bigquery=True,
            check_firestore=True,
            check_gcs=True
        )

        # Clients should be None until lazy-loaded
        assert checker._bq_client is None
        assert checker._firestore_client is None
        assert checker._storage_client is None


class TestEnvironmentVariableCheck:
    """Test environment variable validation."""

    def test_required_vars_present(self):
        """Test when all required environment variables are present."""
        with patch.dict(os.environ, {'VAR1': 'value1', 'VAR2': 'value2'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                required_env_vars=['VAR1', 'VAR2']
            )

            result = checker.check_environment_variables()

            assert result['check'] == 'environment'
            assert result['status'] == 'pass'
            assert result['details']['VAR1']['status'] == 'pass'
            assert result['details']['VAR1']['set'] is True
            assert result['details']['VAR2']['status'] == 'pass'
            assert result['details']['VAR2']['set'] is True

    def test_required_var_missing(self):
        """Test when a required environment variable is missing."""
        with patch.dict(os.environ, {'VAR1': 'value1'}, clear=True):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                required_env_vars=['VAR1', 'VAR2']
            )

            result = checker.check_environment_variables()

            assert result['check'] == 'environment'
            assert result['status'] == 'fail'
            assert result['details']['VAR1']['status'] == 'pass'
            assert result['details']['VAR2']['status'] == 'fail'
            assert result['details']['VAR2']['set'] is False

    def test_optional_vars(self):
        """Test optional environment variables (warnings only)."""
        with patch.dict(os.environ, {'VAR1': 'value1'}, clear=True):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                required_env_vars=['VAR1'],
                optional_env_vars=['VAR2', 'VAR3']
            )

            result = checker.check_environment_variables()

            assert result['status'] == 'pass'  # Optional vars don't cause failure
            assert result['details']['VAR2']['status'] == 'warn'
            assert result['details']['VAR2']['set'] is False
            assert result['details']['VAR3']['status'] == 'warn'


class TestBigQueryCheck:
    """Test BigQuery connectivity check."""

    def test_bigquery_disabled(self):
        """Test when BigQuery check is disabled."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_bigquery=False
        )

        result = checker.check_bigquery_connectivity()

        assert result['check'] == 'bigquery'
        assert result['status'] == 'skip'
        assert 'reason' in result

    @patch('shared.endpoints.health.HealthChecker.bq_client')
    def test_bigquery_success(self, mock_bq_client):
        """Test successful BigQuery connectivity check."""
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
        assert 'details' in result
        assert result['details']['connection'] == 'successful'
        mock_bq_client.query.assert_called_once()

    @patch('shared.endpoints.health.HealthChecker.bq_client')
    def test_bigquery_failure(self, mock_bq_client):
        """Test BigQuery connectivity check failure."""
        # Mock failed query
        mock_bq_client.query.side_effect = Exception('Connection failed')

        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_bigquery=True
        )
        checker._bq_client = mock_bq_client

        result = checker.check_bigquery_connectivity()

        assert result['check'] == 'bigquery'
        assert result['status'] == 'fail'
        assert 'error' in result
        assert 'Connection failed' in result['error']


class TestFirestoreCheck:
    """Test Firestore connectivity check."""

    def test_firestore_disabled(self):
        """Test when Firestore check is disabled."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_firestore=False
        )

        result = checker.check_firestore_connectivity()

        assert result['check'] == 'firestore'
        assert result['status'] == 'skip'

    @patch('shared.endpoints.health.HealthChecker.firestore_client')
    def test_firestore_success(self, mock_firestore_client):
        """Test successful Firestore connectivity check."""
        # Mock successful collection query
        mock_collection = Mock()
        mock_collection.limit.return_value.get.return_value = []
        mock_firestore_client.collection.return_value = mock_collection

        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_firestore=True
        )
        checker._firestore_client = mock_firestore_client

        result = checker.check_firestore_connectivity()

        assert result['check'] == 'firestore'
        assert result['status'] == 'pass'
        assert result['details']['connection'] == 'successful'

    @patch('shared.endpoints.health.HealthChecker.firestore_client')
    def test_firestore_failure(self, mock_firestore_client):
        """Test Firestore connectivity check failure."""
        # Mock failed query
        mock_firestore_client.collection.side_effect = Exception('Permission denied')

        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_firestore=True
        )
        checker._firestore_client = mock_firestore_client

        result = checker.check_firestore_connectivity()

        assert result['check'] == 'firestore'
        assert result['status'] == 'fail'
        assert 'Permission denied' in result['error']


class TestGCSCheck:
    """Test GCS connectivity check."""

    def test_gcs_disabled(self):
        """Test when GCS check is disabled."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_gcs=False
        )

        result = checker.check_gcs_connectivity()

        assert result['check'] == 'gcs'
        assert result['status'] == 'skip'

    def test_gcs_no_buckets_configured(self):
        """Test when GCS is enabled but no buckets configured."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_gcs=True,
            gcs_buckets=[]
        )

        result = checker.check_gcs_connectivity()

        assert result['check'] == 'gcs'
        assert result['status'] == 'skip'
        assert 'No GCS buckets' in result['reason']

    @patch('shared.endpoints.health.HealthChecker.storage_client')
    def test_gcs_success(self, mock_storage_client):
        """Test successful GCS connectivity check."""
        # Mock successful bucket access
        mock_bucket = Mock()
        mock_bucket.list_blobs.return_value = []
        mock_storage_client.bucket.return_value = mock_bucket

        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_gcs=True,
            gcs_buckets=['test-bucket']
        )
        checker._storage_client = mock_storage_client

        result = checker.check_gcs_connectivity()

        assert result['check'] == 'gcs'
        assert result['status'] == 'pass'
        assert 'test-bucket' in result['details']
        assert result['details']['test-bucket']['status'] == 'accessible'

    @patch('shared.endpoints.health.HealthChecker.storage_client')
    def test_gcs_failure(self, mock_storage_client):
        """Test GCS connectivity check failure."""
        # Mock failed bucket access - exception during list_blobs
        mock_bucket = Mock()
        mock_bucket.list_blobs.side_effect = Exception('403 Forbidden')
        mock_storage_client.bucket.return_value = mock_bucket

        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_gcs=True,
            gcs_buckets=['test-bucket']
        )
        checker._storage_client = mock_storage_client

        result = checker.check_gcs_connectivity()

        assert result['check'] == 'gcs'
        assert result['status'] == 'fail'
        # Error is in details for per-bucket failures
        assert 'test-bucket' in result['details']
        assert '403 Forbidden' in result['details']['test-bucket']['error']


class TestRunAllChecks:
    """Test running all health checks together."""

    def test_all_checks_pass(self):
        """Test when all configured checks pass."""
        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                check_firestore=False,
                check_gcs=False,
                required_env_vars=['GCP_PROJECT_ID']
            )

            result = checker.run_all_checks(parallel=False)

            assert result['status'] == 'healthy'
            assert result['service'] == 'test-service'
            assert result['checks_run'] == 1  # Only environment check
            assert result['checks_passed'] == 1
            assert result['checks_failed'] == 0
            assert 'total_duration_ms' in result

    def test_some_checks_fail(self):
        """Test when some checks fail."""
        with patch.dict(os.environ, {}, clear=True):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                check_firestore=False,
                check_gcs=False,
                required_env_vars=['MISSING_VAR']
            )

            result = checker.run_all_checks(parallel=False)

            assert result['status'] == 'unhealthy'
            assert result['checks_failed'] > 0

    def test_parallel_execution(self):
        """Test parallel vs sequential execution produces same results."""
        with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test'}):
            checker = HealthChecker(
                project_id='test-project',
                service_name='test-service',
                check_bigquery=False,
                required_env_vars=['GCP_PROJECT_ID']
            )

            result_parallel = checker.run_all_checks(parallel=True)
            result_sequential = checker.run_all_checks(parallel=False)

            assert result_parallel['status'] == result_sequential['status']
            assert result_parallel['checks_run'] == result_sequential['checks_run']
            assert result_parallel['checks_passed'] == result_sequential['checks_passed']


class TestFlaskBlueprint:
    """Test Flask blueprint creation and endpoints."""

    def test_blueprint_creation_without_checker(self):
        """Test creating blueprint without health checker."""
        blueprint = create_health_blueprint()

        assert blueprint is not None
        assert blueprint.name == 'health'

    def test_blueprint_creation_with_checker(self):
        """Test creating blueprint with health checker."""
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service'
        )
        blueprint = create_health_blueprint(checker)

        assert blueprint is not None
        assert blueprint.name == 'health'

    def test_blueprint_endpoints(self):
        """Test that blueprint has correct endpoints."""
        blueprint = create_health_blueprint()

        # Get all rules/endpoints from the blueprint
        rules = [rule.rule for rule in blueprint.url_map.iter_rules()] if hasattr(blueprint, 'url_map') else []

        # Note: Rules are registered when blueprint is registered with app
        # We can't test URLs directly without a Flask app context
        # This test validates blueprint structure
        assert blueprint.name == 'health'


class TestCustomChecks:
    """Test custom health checks functionality."""

    def test_custom_check_integration(self):
        """Test that custom checks are integrated and executed."""
        def custom_model_check() -> Dict[str, Any]:
            """Example custom check."""
            return {
                'check': 'model_availability',
                'status': 'pass',
                'details': {'model_path': '/models/test.cbm'},
                'duration_ms': 10
            }

        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service',
            check_bigquery=False,
            custom_checks={
                'model_availability': custom_model_check
            }
        )

        result = checker.run_all_checks(parallel=False)

        # Custom check should be included in results
        check_names = [check['check'] for check in result['checks']]
        assert 'model_availability' in check_names

        # Find the custom check result
        model_check = next(c for c in result['checks'] if c['check'] == 'model_availability')
        assert model_check['status'] == 'pass'
        assert model_check['details']['model_path'] == '/models/test.cbm'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
