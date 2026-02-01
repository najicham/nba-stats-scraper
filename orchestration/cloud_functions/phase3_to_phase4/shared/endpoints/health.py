"""
Week 1: Enhanced Health Check Endpoints

Provides detailed health endpoints with metrics for monitoring.

Before: Simple true/false health checks
After: Detailed metrics (uptime, request count, latency, dependencies)

Features:
- Uptime tracking
- Request counter
- Average latency calculation
- Dependency health checks (BigQuery, Firestore, Pub/Sub)
- Service-specific metrics

Created: 2026-01-20 (Week 1, Day 5)
"""

import time
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, asdict
from flask import Blueprint, jsonify, Response
import logging

logger = logging.getLogger(__name__)


@dataclass
class HealthMetrics:
    """Health check metrics."""
    uptime_seconds: float
    request_count: int
    avg_latency_ms: float
    last_request_at: Optional[str]
    service_name: str
    version: str


@dataclass
class DependencyHealth:
    """Dependency health status."""
    name: str
    healthy: bool
    latency_ms: float
    error: Optional[str] = None


class HealthChecker:
    """
    Health checker with metrics tracking.
    
    Usage:
        health_checker = HealthChecker(service_name='prediction-coordinator')
        health_checker.record_request(latency_ms=45.2)
        
        @app.route('/health')
        def health():
            return health_checker.get_health_response()
    """
    
    def __init__(self, service_name: str, version: str = '1.0'):
        self.service_name = service_name
        self.version = version
        self.start_time = time.time()
        self.request_count = 0
        self.total_latency_ms = 0.0
        self.last_request_at = None
        
        # Dependency checkers (optional)
        self.dependency_checkers: Dict[str, Callable[[], bool]] = {}
    
    def record_request(self, latency_ms: float):
        """Record a request for metrics."""
        self.request_count += 1
        self.total_latency_ms += latency_ms
        self.last_request_at = datetime.now(timezone.utc).isoformat()
    
    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self.start_time
    
    def get_avg_latency(self) -> float:
        """Get average latency in milliseconds."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency_ms / self.request_count
    
    def add_dependency_checker(self, name: str, checker: Callable[[], bool]):
        """Add a dependency health checker function."""
        self.dependency_checkers[name] = checker
    
    def check_dependencies(self) -> Dict[str, DependencyHealth]:
        """Check all dependencies and return health status."""
        results = {}
        
        for name, checker in self.dependency_checkers.items():
            start = time.time()
            try:
                healthy = checker()
                latency = (time.time() - start) * 1000  # ms
                results[name] = DependencyHealth(
                    name=name,
                    healthy=healthy,
                    latency_ms=round(latency, 2)
                )
            except Exception as e:
                latency = (time.time() - start) * 1000  # ms
                results[name] = DependencyHealth(
                    name=name,
                    healthy=False,
                    latency_ms=round(latency, 2),
                    error=str(e)
                )
        
        return results
    
    def get_metrics(self) -> HealthMetrics:
        """Get current health metrics."""
        return HealthMetrics(
            uptime_seconds=round(self.get_uptime(), 2),
            request_count=self.request_count,
            avg_latency_ms=round(self.get_avg_latency(), 2),
            last_request_at=self.last_request_at,
            service_name=self.service_name,
            version=self.version
        )
    
    def get_health_response(self, include_dependencies: bool = True) -> tuple:
        """
        Get health check response.
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        metrics = self.get_metrics()
        response = {
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'metrics': asdict(metrics)
        }
        
        # Check dependencies if requested
        if include_dependencies and self.dependency_checkers:
            dependencies = self.check_dependencies()
            response['dependencies'] = {
                name: asdict(dep) for name, dep in dependencies.items()
            }
            
            # Mark as unhealthy if any dependency is down
            unhealthy_deps = [name for name, dep in dependencies.items() if not dep.healthy]
            if unhealthy_deps:
                response['status'] = 'degraded'
                response['unhealthy_dependencies'] = unhealthy_deps

        http_status = 200 if response['status'] == 'healthy' else 503
        return response, http_status


def create_health_blueprint(
    service_name: str,
    version: str = '1.0',
    health_checker: Optional[HealthChecker] = None
) -> Blueprint:
    """
    Create a health check blueprint with metrics.
    
    Args:
        service_name: Name of the service
        version: Service version
        health_checker: Optional existing HealthChecker instance
    
    Returns:
        Flask Blueprint with /health and /health/metrics endpoints
    """
    bp = Blueprint('health', __name__)
    
    # Use provided health checker or create new one
    checker = health_checker or HealthChecker(service_name=service_name, version=version)
    
    @bp.route('/health', methods=['GET'])
    def health():
        """Basic health check endpoint."""
        return jsonify({'status': 'healthy', 'service': service_name}), 200
    
    @bp.route('/health/metrics', methods=['GET'])
    def health_metrics():
        """Detailed health check with metrics."""
        response, status = checker.get_health_response(include_dependencies=True)
        return jsonify(response), status
    
    @bp.route('/health/ready', methods=['GET'])
    def readiness():
        """Readiness probe (for Kubernetes)."""
        response, status = checker.get_health_response(include_dependencies=True)
        if response['status'] == 'healthy':
            return jsonify({'status': 'ready'}), 200
        else:
            return jsonify({'status': 'not ready', 'reason': response.get('unhealthy_dependencies')}), 503
    
    @bp.route('/health/live', methods=['GET'])
    def liveness():
        """Liveness probe (for Kubernetes)."""
        # Liveness doesn't check dependencies, just if service is alive
        return jsonify({'status': 'alive', 'uptime_seconds': checker.get_uptime()}), 200
    
    return bp


# Example dependency checkers

def create_bigquery_checker(project_id: str) -> Callable[[], bool]:
    """Create a BigQuery dependency checker."""
    def check_bigquery() -> bool:
        try:
            from shared.clients import get_bigquery_client
            client = get_bigquery_client(project_id)
            # Simple query to test connection
            query = "SELECT 1 as test"
            result = client.query(query, timeout=5).result()
            return True
        except Exception as e:
            logger.error(f"BigQuery health check failed: {e}", exc_info=True)
            return False
    return check_bigquery


def create_firestore_checker(project_id: str) -> Callable[[], bool]:
    """Create a Firestore dependency checker."""
    def check_firestore() -> bool:
        try:
            from shared.clients import get_firestore_client
            db = get_firestore_client(project_id)
            # Try to read from a test collection
            test_ref = db.collection('_health_check').document('test')
            test_ref.get(timeout=5)
            return True
        except Exception as e:
            logger.error(f"Firestore health check failed: {e}", exc_info=True)
            return False
    return check_firestore


def create_pubsub_checker(project_id: str) -> Callable[[], bool]:
    """Create a Pub/Sub dependency checker."""
    def check_pubsub() -> bool:
        try:
            from shared.clients import get_pubsub_publisher
            publisher = get_pubsub_publisher()
            # List topics to test connection
            project_path = f"projects/{project_id}"
            list(publisher.list_topics(request={"project": project_path}, timeout=5))
            return True
        except Exception as e:
            logger.error(f"Pub/Sub health check failed: {e}", exc_info=True)
            return False
    return check_pubsub


# ============================================================================
# CACHED HEALTH CHECKER (for Cloud Functions and high-frequency probes)
# ============================================================================

class CachedHealthChecker:
    """
    Health checker with TTL-based caching to prevent overloading dependencies.

    Use this for Cloud Functions or services with frequent health probes.
    Caches the full health check result for `cache_ttl_seconds` to avoid
    hitting BigQuery/Firestore/Pub/Sub on every probe.

    Usage:
        checker = CachedHealthChecker(
            service_name='phase3_to_phase4',
            project_id='nba-props-platform',
            cache_ttl_seconds=30
        )

        # In HTTP handler:
        return checker.get_health_json()
    """

    def __init__(
        self,
        service_name: str,
        project_id: str,
        version: str = '1.0',
        cache_ttl_seconds: int = 30,
        check_bigquery: bool = True,
        check_firestore: bool = True,
        check_pubsub: bool = True
    ):
        self.service_name = service_name
        self.project_id = project_id
        self.version = version
        self.cache_ttl_seconds = cache_ttl_seconds
        self.start_time = time.time()

        # Cache state
        self._cached_result: Optional[Dict] = None
        self._cache_timestamp: float = 0

        # Dependency check flags
        self._check_bigquery = check_bigquery
        self._check_firestore = check_firestore
        self._check_pubsub = check_pubsub

    def _is_cache_valid(self) -> bool:
        """Check if cached result is still valid."""
        if self._cached_result is None:
            return False
        elapsed = time.time() - self._cache_timestamp
        return elapsed < self.cache_ttl_seconds

    def _check_dependencies(self) -> Dict[str, Dict]:
        """Check all configured dependencies."""
        results = {}

        if self._check_bigquery:
            start = time.time()
            try:
                from google.cloud import bigquery
                client = bigquery.Client(project=self.project_id)
                list(client.query("SELECT 1").result(timeout=5))
                results['bigquery'] = {
                    'healthy': True,
                    'latency_ms': round((time.time() - start) * 1000, 2)
                }
            except Exception as e:
                results['bigquery'] = {
                    'healthy': False,
                    'latency_ms': round((time.time() - start) * 1000, 2),
                    'error': str(e)[:100]
                }

        if self._check_firestore:
            start = time.time()
            try:
                from google.cloud import firestore
                db = firestore.Client(project=self.project_id)
                db.collection('_health_check').document('test').get(timeout=5)
                results['firestore'] = {
                    'healthy': True,
                    'latency_ms': round((time.time() - start) * 1000, 2)
                }
            except Exception as e:
                results['firestore'] = {
                    'healthy': False,
                    'latency_ms': round((time.time() - start) * 1000, 2),
                    'error': str(e)[:100]
                }

        if self._check_pubsub:
            start = time.time()
            try:
                from google.cloud import pubsub_v1
                publisher = pubsub_v1.PublisherClient()
                project_path = f"projects/{self.project_id}"
                # Just check we can create the client (listing topics is slow)
                results['pubsub'] = {
                    'healthy': True,
                    'latency_ms': round((time.time() - start) * 1000, 2)
                }
            except Exception as e:
                results['pubsub'] = {
                    'healthy': False,
                    'latency_ms': round((time.time() - start) * 1000, 2),
                    'error': str(e)[:100]
                }

        return results

    def get_health(self) -> Dict:
        """Get health check result (uses cache if valid)."""
        # Return cached result if valid
        if self._is_cache_valid():
            # Update timestamp to show it's from cache
            cached = self._cached_result.copy()
            cached['cached'] = True
            cached['cache_age_seconds'] = round(time.time() - self._cache_timestamp, 1)
            return cached

        # Perform fresh health check
        uptime = time.time() - self.start_time
        dependencies = self._check_dependencies()

        # Determine overall status
        unhealthy_deps = [name for name, dep in dependencies.items() if not dep.get('healthy', False)]
        if unhealthy_deps:
            status = 'degraded'
        else:
            status = 'healthy'

        result = {
            'status': status,
            'service': self.service_name,
            'version': self.version,
            'uptime_seconds': round(uptime, 2),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'dependencies': dependencies,
            'cached': False
        }

        if unhealthy_deps:
            result['unhealthy_dependencies'] = unhealthy_deps

        # Cache the result
        self._cached_result = result
        self._cache_timestamp = time.time()

        return result

    def get_health_json(self) -> tuple:
        """Get health as JSON response tuple (body, status_code, headers)."""
        import json
        result = self.get_health()
        status_code = 200 if result['status'] == 'healthy' else 503
        return (
            json.dumps(result),
            status_code,
            {'Content-Type': 'application/json'}
        )
