"""
Smoke Tests for Health Endpoints (Phase 1 - Task 1.2)

Tests all services' health and readiness endpoints to ensure they respond correctly.

Usage:
    # Test all services in production
    pytest tests/smoke/test_health_endpoints.py -v

    # Test specific service
    pytest tests/smoke/test_health_endpoints.py::test_health_endpoints -k coordinator

    # Test against staging
    ENVIRONMENT=staging pytest tests/smoke/test_health_endpoints.py -v

Environment Variables:
    ENVIRONMENT: Environment to test (production, staging). Default: production
    COORDINATOR_URL: Override coordinator service URL
    WORKER_URL: Override worker service URL
    MLB_WORKER_URL: Override MLB worker service URL
    ADMIN_DASHBOARD_URL: Override admin dashboard URL
    ANALYTICS_PROCESSOR_URL: Override analytics processor URL
    PRECOMPUTE_PROCESSOR_URL: Override precompute processor URL

Reference: docs/08-projects/current/pipeline-reliability-improvements/
"""

import os
import sys
import pytest
import requests
from typing import Dict, Optional

# Service URLs by environment
# URLs discovered from: gcloud run services list --platform=managed --region=us-west2
SERVICE_URLS = {
    'production': {
        'prediction-coordinator': os.environ.get('COORDINATOR_URL', 'https://prediction-coordinator-756957797294.us-west2.run.app'),
        'prediction-worker': os.environ.get('WORKER_URL', 'https://prediction-worker-756957797294.us-west2.run.app'),
        'mlb-worker': os.environ.get('MLB_WORKER_URL', 'https://mlb-prediction-worker-756957797294.us-west2.run.app'),
        'admin-dashboard': os.environ.get('ADMIN_DASHBOARD_URL', 'https://nba-admin-dashboard-756957797294.us-west2.run.app'),
        'analytics-processor': os.environ.get('ANALYTICS_PROCESSOR_URL', 'https://nba-phase3-analytics-processors-756957797294.us-west2.run.app'),
        'precompute-processor': os.environ.get('PRECOMPUTE_PROCESSOR_URL', 'https://nba-phase4-precompute-processors-756957797294.us-west2.run.app'),
    },
    'staging': {
        # Note: Staging URLs would be different Cloud Run revisions with --tag staging
        # These will be created when we deploy to staging
        'prediction-coordinator': os.environ.get('COORDINATOR_URL', 'https://staging---prediction-coordinator-756957797294.us-west2.run.app'),
        'prediction-worker': os.environ.get('WORKER_URL', 'https://staging---prediction-worker-756957797294.us-west2.run.app'),
        'mlb-worker': os.environ.get('MLB_WORKER_URL', 'https://staging---mlb-prediction-worker-756957797294.us-west2.run.app'),
        'admin-dashboard': os.environ.get('ADMIN_DASHBOARD_URL', 'https://staging---nba-admin-dashboard-756957797294.us-west2.run.app'),
        'analytics-processor': os.environ.get('ANALYTICS_PROCESSOR_URL', 'https://staging---nba-phase3-analytics-processors-756957797294.us-west2.run.app'),
        'precompute-processor': os.environ.get('PRECOMPUTE_PROCESSOR_URL', 'https://staging---nba-phase4-precompute-processors-756957797294.us-west2.run.app'),
    }
}

ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production')


def get_service_url(service_name: str) -> Optional[str]:
    """Get service URL for current environment."""
    urls = SERVICE_URLS.get(ENVIRONMENT, SERVICE_URLS['production'])
    url = urls.get(service_name)

    # All production URLs are now configured
    return url


@pytest.mark.smoke
@pytest.mark.parametrize('service_name', [
    'prediction-coordinator',
    'prediction-worker',
    'mlb-worker',
    'admin-dashboard',
    'analytics-processor',
    'precompute-processor',
])
def test_health_endpoints(service_name: str):
    """
    Test /health endpoint returns 200 and correct structure.

    The /health endpoint is a liveness probe that checks if the service is running.
    """
    url = get_service_url(service_name)

    if not url:
        pytest.skip(f"URL not configured for {service_name} in {ENVIRONMENT}")

    response = requests.get(f"{url}/health", timeout=10)

    assert response.status_code == 200, f"{service_name} health check failed with status {response.status_code}"

    data = response.json()
    assert 'status' in data, f"{service_name} health response missing 'status' field"
    assert data['status'] == 'healthy', f"{service_name} reports unhealthy status"
    assert 'service' in data, f"{service_name} health response missing 'service' field"

    print(f"✅ {service_name} /health: {data}")


@pytest.mark.smoke
@pytest.mark.parametrize('service_name', [
    'prediction-coordinator',
    'prediction-worker',
    'mlb-worker',
    'admin-dashboard',
    'analytics-processor',
    'precompute-processor',
])
def test_readiness_endpoints(service_name: str):
    """
    Test /ready endpoint returns 200 and validates dependencies.

    The /ready endpoint is a readiness probe that checks if the service
    can handle traffic (dependencies are available).
    """
    url = get_service_url(service_name)

    if not url:
        pytest.skip(f"URL not configured for {service_name} in {ENVIRONMENT}")

    response = requests.get(f"{url}/ready", timeout=30)

    # Readiness can fail (503) if dependencies are down
    # We accept both 200 (ready) and 503 (not ready) as valid responses
    assert response.status_code in [200, 503], \
        f"{service_name} readiness check returned unexpected status {response.status_code}"

    data = response.json()
    assert 'status' in data, f"{service_name} readiness response missing 'status' field"
    assert 'checks' in data, f"{service_name} readiness response missing 'checks' field"
    assert 'total_duration_ms' in data, f"{service_name} readiness response missing 'total_duration_ms' field"

    # Log check details
    print(f"\n{service_name} /ready status: {data['status']}")
    print(f"  Checks run: {data.get('checks_run', 0)}")
    print(f"  Checks passed: {data.get('checks_passed', 0)}")
    print(f"  Checks failed: {data.get('checks_failed', 0)}")
    print(f"  Duration: {data['total_duration_ms']}ms")

    # Log individual check results
    for check in data.get('checks', []):
        check_status = check.get('status', 'unknown')
        check_name = check.get('check', 'unknown')
        duration = check.get('duration_ms', 0)

        status_emoji = '✅' if check_status == 'pass' else '⚠️' if check_status == 'skip' else '❌'
        print(f"  {status_emoji} {check_name}: {check_status} ({duration}ms)")

        if check_status == 'fail':
            print(f"     Error: {check.get('error', 'unknown')}")

    # If status is 503, at least one critical check failed
    if response.status_code == 503:
        pytest.fail(f"{service_name} is not ready - {data['checks_failed']} checks failed")


@pytest.mark.smoke
@pytest.mark.parametrize('service_name', [
    'prediction-coordinator',
    'prediction-worker',
    'mlb-worker',
    'admin-dashboard',
    'analytics-processor',
    'precompute-processor',
])
def test_deep_health_endpoints(service_name: str):
    """
    Test /health/deep endpoint (alias for /ready).

    This is for backward compatibility with existing health check patterns.
    """
    url = get_service_url(service_name)

    if not url:
        pytest.skip(f"URL not configured for {service_name} in {ENVIRONMENT}")

    response = requests.get(f"{url}/health/deep", timeout=30)

    # Should behave identically to /ready
    assert response.status_code in [200, 503], \
        f"{service_name} deep health check returned unexpected status {response.status_code}"

    data = response.json()
    assert 'status' in data, f"{service_name} deep health response missing 'status' field"
    assert 'checks' in data, f"{service_name} deep health response missing 'checks' field"

    print(f"✅ {service_name} /health/deep: {data['status']} ({len(data.get('checks', []))} checks)")


@pytest.mark.smoke
def test_critical_dependencies_importable():
    """
    Verify critical dependencies can be imported.

    This test runs locally and verifies the Python environment is correctly configured.
    """
    try:
        from google.cloud import bigquery
        from google.cloud import firestore
        from google.cloud import storage
        from google.cloud import secretmanager
        from google.cloud import pubsub_v1
        print("✅ All critical Google Cloud dependencies importable")
    except ImportError as e:
        pytest.fail(f"Critical import failed: {e}")


@pytest.mark.smoke
def test_shared_health_module_importable():
    """
    Verify the shared health module can be imported.
    """
    try:
        # Add project root to path
        project_root = os.path.join(os.path.dirname(__file__), '../..')
        sys.path.insert(0, project_root)

        from shared.endpoints.health import create_health_blueprint, HealthChecker
        print("✅ Shared health module importable")

        # Verify we can instantiate a HealthChecker
        checker = HealthChecker(
            project_id='test-project',
            service_name='test-service'
        )
        assert checker.project_id == 'test-project'
        assert checker.service_name == 'test-service'
        print("✅ HealthChecker instantiates correctly")

    except ImportError as e:
        pytest.fail(f"Failed to import shared health module: {e}")
    except Exception as e:
        pytest.fail(f"Failed to instantiate HealthChecker: {e}")


if __name__ == '__main__':
    # Run smoke tests
    pytest.main([__file__, '-v', '--tb=short'])
