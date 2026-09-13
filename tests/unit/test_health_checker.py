"""
Unit tests for shared/endpoints/health.py.

History (2026-09-08): the previous version of this file was written against a
`HealthChecker(project_id=..., check_bigquery=...)` API that has never existed.
Both the test and the module arrived in the same merge (a7a8fb83) and the
signatures disagreed on day one, so all 23 tests have failed continuously since
then — the module that six orchestrator Cloud Functions mount their /health
endpoints from had, in effect, zero coverage. This rewrite targets the API the
module actually exposes.

Run with:
    pytest tests/unit/test_health_checker.py -v
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from shared.endpoints.health import (
    CachedHealthChecker,
    DependencyHealth,
    HealthChecker,
    HealthMetrics,
    create_bigquery_checker,
    create_firestore_checker,
    create_health_blueprint,
    create_pubsub_checker,
)


class TestHealthCheckerInstantiation:
    def test_defaults(self):
        checker = HealthChecker(service_name='test-service')

        assert checker.service_name == 'test-service'
        assert checker.version == '1.0'
        assert checker.request_count == 0
        assert checker.total_latency_ms == 0.0
        assert checker.last_request_at is None
        assert checker.dependency_checkers == {}

    def test_explicit_version(self):
        checker = HealthChecker(service_name='svc', version='2.5')
        assert checker.version == '2.5'


class TestRequestMetrics:
    def test_record_request_accumulates(self):
        checker = HealthChecker(service_name='svc')
        checker.record_request(latency_ms=10.0)
        checker.record_request(latency_ms=30.0)

        assert checker.request_count == 2
        assert checker.total_latency_ms == 40.0
        assert checker.get_avg_latency() == 20.0
        assert checker.last_request_at is not None

    def test_avg_latency_with_no_requests_does_not_divide_by_zero(self):
        assert HealthChecker(service_name='svc').get_avg_latency() == 0.0

    def test_uptime_is_positive_and_monotonic(self):
        checker = HealthChecker(service_name='svc')
        first = checker.get_uptime()
        time.sleep(0.01)
        assert 0 <= first <= checker.get_uptime()

    def test_get_metrics_snapshot(self):
        checker = HealthChecker(service_name='svc', version='3.0')
        checker.record_request(latency_ms=12.345)

        metrics = checker.get_metrics()

        assert isinstance(metrics, HealthMetrics)
        assert metrics.service_name == 'svc'
        assert metrics.version == '3.0'
        assert metrics.request_count == 1
        assert metrics.avg_latency_ms == 12.35  # rounded to 2dp


class TestDependencyChecks:
    def test_healthy_dependency(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bigquery', lambda: True)

        results = checker.check_dependencies()

        assert set(results) == {'bigquery'}
        assert isinstance(results['bigquery'], DependencyHealth)
        assert results['bigquery'].healthy is True
        assert results['bigquery'].error is None

    def test_unhealthy_dependency_reports_false_without_error(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('firestore', lambda: False)

        results = checker.check_dependencies()

        assert results['firestore'].healthy is False
        assert results['firestore'].error is None

    def test_raising_dependency_is_captured_not_propagated(self):
        checker = HealthChecker(service_name='svc')

        def boom():
            raise RuntimeError('connection refused')

        checker.add_dependency_checker('pubsub', boom)
        results = checker.check_dependencies()

        assert results['pubsub'].healthy is False
        assert 'connection refused' in results['pubsub'].error

    def test_add_dependency_checker_overwrites_same_name(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bq', lambda: True)
        checker.add_dependency_checker('bq', lambda: False)

        assert checker.check_dependencies()['bq'].healthy is False


class TestHealthResponse:
    def test_healthy_when_no_dependencies_registered(self):
        response, status = HealthChecker(service_name='svc').get_health_response()

        assert status == 200
        assert response['status'] == 'healthy'
        assert 'dependencies' not in response
        assert response['metrics']['service_name'] == 'svc'

    def test_all_dependencies_healthy_returns_200(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bq', lambda: True)

        response, status = checker.get_health_response()

        assert status == 200
        assert response['status'] == 'healthy'
        assert response['dependencies']['bq']['healthy'] is True

    def test_one_bad_dependency_degrades_to_503(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bq', lambda: True)
        checker.add_dependency_checker('firestore', lambda: False)

        response, status = checker.get_health_response()

        assert status == 503
        assert response['status'] == 'degraded'
        assert response['unhealthy_dependencies'] == ['firestore']

    def test_include_dependencies_false_skips_the_checks(self):
        called = []
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bq', lambda: called.append(1) or False)

        response, status = checker.get_health_response(include_dependencies=False)

        assert called == []
        assert status == 200
        assert 'dependencies' not in response


class TestHealthBlueprint:
    def _client(self, **kwargs):
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(create_health_blueprint(**kwargs))
        return app.test_client()

    def test_service_name_is_required(self):
        with pytest.raises(TypeError):
            create_health_blueprint()

    def test_health_endpoint(self):
        resp = self._client(service_name='svc').get('/health')

        assert resp.status_code == 200
        assert resp.get_json() == {'status': 'healthy', 'service': 'svc'}

    def test_liveness_does_not_consult_dependencies(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bq', lambda: False)

        resp = self._client(service_name='svc', health_checker=checker).get('/health/live')

        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'alive'

    def test_metrics_endpoint_uses_the_injected_checker(self):
        checker = HealthChecker(service_name='svc', version='9.9')
        checker.record_request(latency_ms=5.0)

        resp = self._client(service_name='svc', health_checker=checker).get('/health/metrics')

        assert resp.status_code == 200
        assert resp.get_json()['metrics']['request_count'] == 1
        assert resp.get_json()['metrics']['version'] == '9.9'

    def test_readiness_reports_not_ready_when_a_dependency_is_down(self):
        checker = HealthChecker(service_name='svc')
        checker.add_dependency_checker('bq', lambda: False)

        resp = self._client(service_name='svc', health_checker=checker).get('/health/ready')

        assert resp.status_code == 503
        body = resp.get_json()
        assert body['status'] == 'not ready'
        assert body['reason'] == ['bq']

    def test_readiness_ok_when_healthy(self):
        resp = self._client(service_name='svc').get('/health/ready')

        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ready'


class TestDependencyCheckerFactories:
    """The factories must swallow failures and return False, never raise —
    a health endpoint that 500s is worse than one that reports degraded."""

    def test_bigquery_checker_true_on_success(self):
        with patch('shared.clients.get_bigquery_client') as get_client:
            get_client.return_value = MagicMock()
            assert create_bigquery_checker('proj')() is True

    def test_bigquery_checker_false_on_failure(self):
        with patch('shared.clients.get_bigquery_client', side_effect=RuntimeError('nope')):
            assert create_bigquery_checker('proj')() is False

    def test_firestore_checker_false_on_failure(self):
        with patch('shared.clients.get_firestore_client', side_effect=RuntimeError('nope')):
            assert create_firestore_checker('proj')() is False

    def test_pubsub_checker_false_on_failure(self):
        with patch('shared.clients.get_pubsub_publisher', side_effect=RuntimeError('nope')):
            assert create_pubsub_checker('proj')() is False


class TestCachedHealthChecker:
    def _checker(self, **kwargs):
        kwargs.setdefault('service_name', 'svc')
        kwargs.setdefault('project_id', 'proj')
        return CachedHealthChecker(**kwargs)

    def test_all_dependency_flags_off_is_healthy_and_hits_nothing(self):
        checker = self._checker(
            check_bigquery=False, check_firestore=False, check_pubsub=False
        )

        result = checker.get_health()

        assert result['status'] == 'healthy'
        assert result['dependencies'] == {}
        assert result['cached'] is False

    def test_failing_dependency_degrades_and_truncates_the_error(self):
        checker = self._checker(check_firestore=False, check_pubsub=False)
        long_error = 'x' * 500

        with patch('google.cloud.bigquery.Client', side_effect=RuntimeError(long_error)):
            result = checker.get_health()

        assert result['status'] == 'degraded'
        assert result['unhealthy_dependencies'] == ['bigquery']
        assert len(result['dependencies']['bigquery']['error']) == 100

    def test_second_call_within_ttl_is_served_from_cache(self):
        checker = self._checker(
            check_bigquery=False, check_firestore=False, check_pubsub=False
        )

        first = checker.get_health()
        second = checker.get_health()

        assert first['cached'] is False
        assert second['cached'] is True
        assert 'cache_age_seconds' in second

    def test_expired_cache_recomputes(self):
        checker = self._checker(
            cache_ttl_seconds=0,
            check_bigquery=False,
            check_firestore=False,
            check_pubsub=False,
        )

        checker.get_health()
        assert checker.get_health()['cached'] is False

    def test_cache_does_not_mutate_the_stored_result(self):
        checker = self._checker(
            check_bigquery=False, check_firestore=False, check_pubsub=False
        )

        checker.get_health()
        checker.get_health()

        assert checker._cached_result['cached'] is False

    def test_get_health_json_shape_and_status(self):
        checker = self._checker(
            check_bigquery=False, check_firestore=False, check_pubsub=False
        )

        body, status, headers = checker.get_health_json()

        assert status == 200
        assert headers == {'Content-Type': 'application/json'}
        assert json.loads(body)['service'] == 'svc'

    def test_get_health_json_returns_503_when_degraded(self):
        checker = self._checker(check_firestore=False, check_pubsub=False)

        with patch('google.cloud.bigquery.Client', side_effect=RuntimeError('down')):
            _, status, _ = checker.get_health_json()

        assert status == 503
