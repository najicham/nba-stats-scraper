"""
Shared Health Check Endpoints for All Services

Provides standardized /health and /ready endpoints that can be customized per service.

Usage:
    from shared.endpoints.health import create_health_blueprint, HealthChecker

    # Create custom health checker
    checker = HealthChecker(
        project_id="nba-props-platform",
        service_name="my-service",
        check_bigquery=True,
        check_firestore=False,
        required_env_vars=['GCP_PROJECT_ID', 'ENVIRONMENT']
    )

    # Register blueprint
    app.register_blueprint(create_health_blueprint(checker))

Reference Implementation: predictions/worker/health_checks.py
Architecture Plan: docs/08-projects/current/pipeline-reliability-improvements/
"""

import os
import sys
import time
import logging
from typing import Dict, List, Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, jsonify
from pathlib import Path

# Configure logging to match codebase standard
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HealthChecker:
    """
    Performs deep health checks on service dependencies.

    Configurable to check different dependencies based on service needs.
    """

    # Maximum duration for all checks (seconds)
    MAX_TOTAL_DURATION = 5.0

    # Individual check timeout (seconds)
    CHECK_TIMEOUT = 2.0

    def __init__(
        self,
        project_id: str,
        service_name: str,
        check_bigquery: bool = True,
        check_firestore: bool = False,
        check_gcs: bool = False,
        gcs_buckets: Optional[List[str]] = None,
        required_env_vars: Optional[List[str]] = None,
        optional_env_vars: Optional[List[str]] = None,
        custom_checks: Optional[Dict[str, Callable]] = None,
        bigquery_test_query: Optional[str] = None,
        bigquery_test_table: Optional[str] = None
    ):
        """
        Initialize health checker.

        Args:
            project_id: GCP project ID
            service_name: Name of the service (for logging)
            check_bigquery: Whether to check BigQuery connectivity
            check_firestore: Whether to check Firestore connectivity
            check_gcs: Whether to check GCS connectivity
            gcs_buckets: List of GCS buckets to check access for
            required_env_vars: List of required environment variables
            optional_env_vars: List of optional environment variables (warnings only)
            custom_checks: Dict of custom check functions {name: callable}
                          Each function should return: {"check": str, "status": str, "details": dict, "duration_ms": int}

                          Example - Simple custom check:
                              def check_cache() -> Dict[str, Any]:
                                  return {
                                      "check": "redis_cache",
                                      "status": "pass",
                                      "details": {"connected": True},
                                      "duration_ms": 50
                                  }

                          Example - Model availability check (see create_model_check helper):
                              model_check = HealthChecker.create_model_check(
                                  model_paths=['gs://bucket/model.cbm'],
                                  fallback_dir='/models'
                              )
                              custom_checks = {"model_availability": model_check}

                          Example - Multiple custom checks:
                              custom_checks = {
                                  "cache": check_cache,
                                  "model": check_model,
                                  "api": check_external_api
                              }
            bigquery_test_query: Custom SQL query to execute for BigQuery check
                                If None, uses "SELECT 1" (default)
            bigquery_test_table: Table to query for BigQuery check
                                If provided, queries: SELECT COUNT(*) FROM table WHERE game_date >= CURRENT_DATE()
                                Similar to NBA Worker pattern
        """
        self.project_id = project_id
        self.service_name = service_name
        self.check_bigquery = check_bigquery
        self.check_firestore = check_firestore
        self.check_gcs = check_gcs
        self.gcs_buckets = gcs_buckets or []
        self.required_env_vars = required_env_vars or ['GCP_PROJECT_ID']
        self.optional_env_vars = optional_env_vars or []
        self.custom_checks = custom_checks or {}
        self.bigquery_test_query = bigquery_test_query
        self.bigquery_test_table = bigquery_test_table

        # Lazy-load clients (only when checks are run)
        self._bq_client = None
        self._firestore_client = None
        self._storage_client = None

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None and self.check_bigquery:
            from google.cloud import bigquery
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    @property
    def firestore_client(self):
        """Lazy-load Firestore client."""
        if self._firestore_client is None and self.check_firestore:
            from google.cloud import firestore
            self._firestore_client = firestore.Client(project=self.project_id)
        return self._firestore_client

    @property
    def storage_client(self):
        """Lazy-load GCS Storage client."""
        if self._storage_client is None and self.check_gcs:
            from google.cloud import storage
            self._storage_client = storage.Client(project=self.project_id)
        return self._storage_client

    def check_bigquery_connectivity(self) -> Dict[str, Any]:
        """
        Check BigQuery connectivity.

        Supports three modes:
        1. Custom query (if bigquery_test_query provided)
        2. Table query (if bigquery_test_table provided) - checks table exists and has recent data
        3. Default (SELECT 1) - simple connectivity check

        Returns:
            {"check": "bigquery", "status": "pass|fail", "details": {...}, "duration_ms": 123, "service": str}
        """
        start_time = time.time()
        check_name = "bigquery"

        if not self.check_bigquery:
            return {
                'check': check_name,
                'status': 'skip',
                'reason': 'BigQuery check disabled for this service',
                'duration_ms': 0,
                'service': self.service_name
            }

        try:
            details = {}

            # Determine which query to use
            if self.bigquery_test_query:
                # Mode 1: Custom query provided
                query = self.bigquery_test_query
                details['query_type'] = 'custom'
                details['query'] = query
            elif self.bigquery_test_table:
                # Mode 2: Table query (NBA Worker pattern)
                # Query format: SELECT COUNT(*) FROM table WHERE game_date >= CURRENT_DATE()
                query = f"""
                    SELECT COUNT(*) as count
                    FROM `{self.project_id}.{self.bigquery_test_table}`
                    WHERE game_date >= CURRENT_DATE()
                    LIMIT 1
                """
                details['query_type'] = 'table_check'
                details['table'] = self.bigquery_test_table
            else:
                # Mode 3: Default simple connectivity check
                query = "SELECT 1 as test"
                details['query_type'] = 'simple'
                details['query'] = 'SELECT 1'

            # Execute query
            query_job = self.bq_client.query(query)
            results = list(query_job.result())

            # Add results to details
            details['connection'] = 'successful'
            if self.bigquery_test_table and results:
                # Include row count for table queries
                details['row_count'] = results[0]['count'] if results else 0

            return {
                'check': check_name,
                'status': 'pass',
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

        except Exception as e:
            # Log error with full exception info for debugging
            logger.error(f"BigQuery health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

    def check_firestore_connectivity(self) -> Dict[str, Any]:
        """
        Check Firestore connectivity.

        Returns:
            {"check": "firestore", "status": "pass|fail", "details": {...}, "duration_ms": 123, "service": str}
        """
        start_time = time.time()
        check_name = "firestore"

        if not self.check_firestore:
            return {
                'check': check_name,
                'status': 'skip',
                'reason': 'Firestore check disabled for this service',
                'duration_ms': 0,
                'service': self.service_name
            }

        try:
            # Try to access a system collection (doesn't need to exist)
            # This verifies we can connect to Firestore
            self.firestore_client.collection('_health_check').limit(1).get()

            return {
                'check': check_name,
                'status': 'pass',
                'details': {'connection': 'successful'},
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

        except Exception as e:
            logger.error(f"Firestore health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

    def check_gcs_connectivity(self) -> Dict[str, Any]:
        """
        Check GCS connectivity and bucket access.

        Returns:
            {"check": "gcs", "status": "pass|fail", "details": {...}, "duration_ms": 123, "service": str}
        """
        start_time = time.time()
        check_name = "gcs"

        if not self.check_gcs:
            return {
                'check': check_name,
                'status': 'skip',
                'reason': 'GCS check disabled for this service',
                'duration_ms': 0,
                'service': self.service_name
            }

        try:
            details = {}

            if not self.gcs_buckets:
                return {
                    'check': check_name,
                    'status': 'skip',
                    'reason': 'No GCS buckets configured to check',
                    'duration_ms': int((time.time() - start_time) * 1000),
                    'service': self.service_name
                }

            # Check access to each configured bucket
            for bucket_name in self.gcs_buckets:
                try:
                    bucket = self.storage_client.bucket(bucket_name)
                    # List one blob to verify access
                    list(bucket.list_blobs(max_results=1))
                    details[bucket_name] = {'status': 'accessible'}
                except Exception as e:
                    details[bucket_name] = {'status': 'fail', 'error': str(e)}
                    return {
                        'check': check_name,
                        'status': 'fail',
                        'details': details,
                        'duration_ms': int((time.time() - start_time) * 1000),
                        'service': self.service_name
                    }

            return {
                'check': check_name,
                'status': 'pass',
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

        except Exception as e:
            logger.error(f"GCS health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

    def check_environment_variables(self) -> Dict[str, Any]:
        """
        Check required and optional environment variables.

        Returns:
            {"check": "environment", "status": "pass|fail", "details": {...}, "duration_ms": 123, "service": str}
        """
        start_time = time.time()
        check_name = "environment"

        try:
            details = {}
            has_failures = False

            # Check required vars
            for var in self.required_env_vars:
                value = os.environ.get(var)
                if value:
                    details[var] = {'status': 'pass', 'set': True}
                else:
                    details[var] = {'status': 'fail', 'set': False, 'error': 'Required env var not set'}
                    has_failures = True

            # Check optional vars (warnings only)
            for var in self.optional_env_vars:
                value = os.environ.get(var)
                details[var] = {
                    'status': 'pass' if value else 'warn',
                    'set': bool(value),
                    'note': 'optional' if not value else 'configured'
                }

            return {
                'check': check_name,
                'status': 'fail' if has_failures else 'pass',
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

        except Exception as e:
            logger.error(f"Environment health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000),
                'service': self.service_name
            }

    @staticmethod
    def create_model_check(model_paths: List[str], fallback_dir: Optional[str] = None) -> Callable:
        """
        Create a model availability check function.

        This is a helper method that services can use to create custom checks for ML model availability.
        It supports both GCS (gs://) paths and local file paths, with optional fallback directory.

        Args:
            model_paths: List of paths to check (can be gs:// or local paths)
                        Examples: ['gs://bucket/models/catboost_v8.cbm']
                                 ['/models/catboost_v8.cbm', '/models/xgboost_v1.json']
            fallback_dir: Optional directory to check for fallback models if primary paths fail
                         Example: '/models' - will search for *.cbm or *.json files

        Returns:
            Callable that performs the model availability check
            Returns: {"check": "model_availability", "status": "pass|fail|skip", "details": {...}, "duration_ms": int}

        Example usage:
            # Simple model check
            model_check = HealthChecker.create_model_check(
                model_paths=['gs://my-bucket/models/model.cbm']
            )

            # Model check with fallback
            model_check = HealthChecker.create_model_check(
                model_paths=['gs://my-bucket/models/model.cbm'],
                fallback_dir='/models'
            )

            # Create health checker with model check
            checker = HealthChecker(
                project_id="my-project",
                service_name="my-service",
                custom_checks={"model_availability": model_check}
            )
        """
        def model_availability_check() -> Dict[str, Any]:
            """Check model availability based on configured paths."""
            start_time = time.time()
            check_name = "model_availability"

            try:
                details = {}
                all_passed = True

                # Check each model path
                for idx, model_path in enumerate(model_paths):
                    model_key = f"model_{idx}" if len(model_paths) > 1 else "model"

                    if model_path.startswith('gs://'):
                        # GCS path - validate format
                        if not (model_path.endswith('.cbm') or model_path.endswith('.json')):
                            details[model_key] = {
                                'status': 'fail',
                                'path': model_path,
                                'error': 'Invalid model path format (must end with .cbm or .json)'
                            }
                            all_passed = False
                            continue

                        # Parse GCS path
                        parts = model_path[5:].split('/', 1)
                        if len(parts) < 2:
                            details[model_key] = {
                                'status': 'fail',
                                'path': model_path,
                                'error': 'Invalid GCS path format'
                            }
                            all_passed = False
                            continue

                        # For GCS paths, we can't check existence without importing storage client
                        # So we just validate format during health check
                        details[model_key] = {
                            'status': 'pass',
                            'path': model_path,
                            'format_valid': True,
                            'note': 'Model loading deferred to first use (lazy load)'
                        }

                    else:
                        # Local path - check if file exists
                        model_file = Path(model_path)
                        if model_file.exists():
                            details[model_key] = {
                                'status': 'pass',
                                'path': model_path,
                                'file_exists': True,
                                'size_bytes': model_file.stat().st_size
                            }
                        else:
                            details[model_key] = {
                                'status': 'fail',
                                'path': model_path,
                                'error': f'Local model file not found: {model_path}'
                            }
                            all_passed = False

                # If primary paths failed and fallback_dir provided, check fallback
                if not all_passed and fallback_dir:
                    fallback_path = Path(fallback_dir)
                    if fallback_path.exists() and fallback_path.is_dir():
                        # Search for model files (*.cbm or *.json)
                        model_files = list(fallback_path.glob("*.cbm")) + list(fallback_path.glob("*.json"))

                        if model_files:
                            details['fallback_models'] = {
                                'status': 'pass',
                                'directory': fallback_dir,
                                'model_count': len(model_files),
                                'models': [f.name for f in model_files[:5]]  # First 5 models
                            }
                            all_passed = True
                        else:
                            details['fallback_models'] = {
                                'status': 'fail',
                                'directory': fallback_dir,
                                'error': 'No model files found in fallback directory'
                            }
                    else:
                        details['fallback_models'] = {
                            'status': 'skip',
                            'reason': f'Fallback directory not found: {fallback_dir}'
                        }

                overall_status = 'pass' if all_passed else 'fail'

                return {
                    'check': check_name,
                    'status': overall_status,
                    'details': details,
                    'duration_ms': int((time.time() - start_time) * 1000)
                }

            except Exception as e:
                logger.error(f"Model availability check failed: {e}", exc_info=True)
                return {
                    'check': check_name,
                    'status': 'fail',
                    'error': str(e),
                    'duration_ms': int((time.time() - start_time) * 1000)
                }

        return model_availability_check

    def run_all_checks(self, parallel: bool = True) -> Dict[str, Any]:
        """
        Run all configured health checks.

        Args:
            parallel: If True, run checks in parallel (faster, default: True)

        Returns:
            {
                "status": "healthy" | "unhealthy",
                "service": "service-name",
                "checks": [...],
                "total_duration_ms": 123,
                "checks_run": 4,
                "checks_passed": 4,
                "checks_failed": 0
            }
        """
        overall_start = time.time()

        # Log health check execution start
        logger.info(f"Starting health check execution for service: {self.service_name}")

        checks = []

        # Build list of checks to run
        check_functions = [
            self.check_environment_variables,  # Always run
        ]

        if self.check_bigquery:
            check_functions.append(self.check_bigquery_connectivity)

        if self.check_firestore:
            check_functions.append(self.check_firestore_connectivity)

        if self.check_gcs:
            check_functions.append(self.check_gcs_connectivity)

        # Add custom checks
        for check_name, check_func in self.custom_checks.items():
            check_functions.append(check_func)

        if parallel:
            # Run checks in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(check_functions)) as executor:
                futures = {
                    executor.submit(func): func.__name__
                    for func in check_functions
                }

                for future in as_completed(futures, timeout=self.MAX_TOTAL_DURATION):
                    try:
                        result = future.result(timeout=self.CHECK_TIMEOUT)
                        checks.append(result)

                        # Log warning if individual check took too long
                        check_duration_sec = result.get('duration_ms', 0) / 1000.0
                        if check_duration_sec > 2.0:
                            logger.warning(
                                f"Health check '{result.get('check', 'unknown')}' took {check_duration_sec:.2f}s "
                                f"(threshold: 2.0s) - consider optimizing this check"
                            )

                    except Exception as e:
                        check_name = futures[future]
                        logger.error(f"Health check {check_name} failed with exception: {e}", exc_info=True)
                        checks.append({
                            'check': check_name,
                            'status': 'fail',
                            'error': f'Exception: {str(e)}',
                            'duration_ms': 0,
                            'service': self.service_name
                        })
        else:
            # Run checks sequentially
            for func in check_functions:
                try:
                    result = func()
                    checks.append(result)

                    # Log warning if individual check took too long
                    check_duration_sec = result.get('duration_ms', 0) / 1000.0
                    if check_duration_sec > 2.0:
                        logger.warning(
                            f"Health check '{result.get('check', 'unknown')}' took {check_duration_sec:.2f}s "
                            f"(threshold: 2.0s) - consider optimizing this check"
                        )

                except Exception as e:
                    logger.error(f"Health check {func.__name__} failed: {e}", exc_info=True)
                    checks.append({
                        'check': func.__name__,
                        'status': 'fail',
                        'error': str(e),
                        'duration_ms': 0,
                        'service': self.service_name
                    })

        # Determine overall status
        total_duration_ms = int((time.time() - overall_start) * 1000)
        total_duration_sec = total_duration_ms / 1000.0
        checks_run = len(checks)
        checks_passed = sum(1 for c in checks if c.get('status') == 'pass')
        checks_failed = sum(1 for c in checks if c.get('status') == 'fail')
        checks_skipped = sum(1 for c in checks if c.get('status') == 'skip')

        overall_status = 'healthy' if checks_failed == 0 else 'unhealthy'

        # Log health check completion with summary
        logger.info(
            f"Health check execution completed for service: {self.service_name} | "
            f"Status: {overall_status} | Duration: {total_duration_sec:.2f}s | "
            f"Passed: {checks_passed}/{checks_run} | Failed: {checks_failed} | Skipped: {checks_skipped}"
        )

        # Log warning if total check time exceeded threshold
        if total_duration_sec > 4.0:
            logger.warning(
                f"Total health check duration {total_duration_sec:.2f}s exceeded threshold (4.0s) - "
                f"consider running checks in parallel or optimizing slow checks"
            )

        return {
            'status': overall_status,
            'service': self.service_name,
            'checks': checks,
            'total_duration_ms': total_duration_ms,
            'checks_run': checks_run,
            'checks_passed': checks_passed,
            'checks_failed': checks_failed,
            'checks_skipped': checks_skipped
        }


def create_health_blueprint(health_checker: Optional[HealthChecker] = None) -> Blueprint:
    """
    Create Flask blueprint with health and readiness endpoints.

    Args:
        health_checker: Optional HealthChecker instance for deep health checks.
                       If None, only basic health endpoint is provided.

    Returns:
        Flask Blueprint with /health and /ready endpoints

    Usage:
        # Basic health only
        app.register_blueprint(create_health_blueprint())

        # With deep health checks
        checker = HealthChecker(
            project_id="nba-props-platform",
            service_name="my-service",
            check_bigquery=True
        )
        app.register_blueprint(create_health_blueprint(checker))
    """
    health_bp = Blueprint('health', __name__)

    @health_bp.route('/health', methods=['GET'])
    def health():
        """
        Liveness probe - is service running?

        Returns 200 if service process is alive.
        This is a lightweight check used by orchestrators like Cloud Run.
        """
        return jsonify({
            'status': 'healthy',
            'service': os.environ.get('SERVICE_NAME', 'unknown'),
            'version': os.environ.get('VERSION', 'unknown'),
            'python_version': sys.version,
            'environment': os.environ.get('ENVIRONMENT', 'unknown')
        }), 200

    @health_bp.route('/ready', methods=['GET'])
    def readiness():
        """
        Readiness probe - is service ready to handle traffic?

        Returns 200 if all dependencies are available.
        Returns 503 if any critical dependency is unavailable.

        This endpoint runs deep health checks if a HealthChecker is provided.
        """
        if health_checker is None:
            # No health checker configured - return basic readiness
            return jsonify({
                'status': 'ready',
                'service': os.environ.get('SERVICE_NAME', 'unknown'),
                'message': 'No deep health checks configured'
            }), 200

        # Run deep health checks
        try:
            result = health_checker.run_all_checks(parallel=True)

            status_code = 200 if result['status'] == 'healthy' else 503

            return jsonify(result), status_code

        except Exception as e:
            logger.error(f"Readiness check failed with exception: {e}", exc_info=True)
            return jsonify({
                'status': 'unhealthy',
                'service': health_checker.service_name,
                'error': str(e)
            }), 503

    # Alias endpoint for backward compatibility
    @health_bp.route('/health/deep', methods=['GET'])
    def health_deep():
        """
        Deep health check endpoint (alias for /ready).

        Provided for backward compatibility with existing services.
        """
        return readiness()

    return health_bp
