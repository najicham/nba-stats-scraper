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
        
        return response, 200


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
            from google.cloud import bigquery
            client = bigquery.Client(project=project_id)
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
            from google.cloud import firestore
            db = firestore.Client(project=project_id)
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
            from google.cloud import pubsub_v1
            publisher = pubsub_v1.PublisherClient()
            # List topics to test connection
            project_path = f"projects/{project_id}"
            list(publisher.list_topics(request={"project": project_path}, timeout=5))
            return True
        except Exception as e:
            logger.error(f"Pub/Sub health check failed: {e}", exc_info=True)
            return False
    return check_pubsub
