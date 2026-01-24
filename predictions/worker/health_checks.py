"""
Deep Health Check Module for NBA Prediction Worker

Validates all dependencies beyond basic HTTP 200 response.
Checks: GCS access, BigQuery access, model loading, configuration.

Usage:
    checker = HealthChecker(project_id="nba-props-platform")
    result = checker.run_all_checks()
    # Returns: {"status": "healthy|unhealthy", "checks": [...], "total_duration_ms": 123}
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import storage, bigquery
from pathlib import Path

logger = logging.getLogger(__name__)


class HealthChecker:
    """Performs deep health checks on all worker dependencies."""

    # Maximum duration for all checks (seconds)
    MAX_TOTAL_DURATION = 3.0

    def __init__(self, project_id: str):
        """
        Initialize health checker.

        Args:
            project_id: GCP project ID
        """
        self.project_id = project_id
        from shared.clients import get_storage_client, get_bigquery_client
        self.storage_client = get_storage_client(project_id)
        self.bq_client = get_bigquery_client(project_id)

    def check_gcs_access(self) -> Dict[str, Any]:
        """
        Check GCS access by reading from model buckets.

        Tests:
        - Access to model bucket
        - Ability to list and read model files
        - CATBOOST_V8_MODEL_PATH existence (if set)

        Returns:
            {"check": "gcs_access", "status": "pass|fail", "details": {...}, "duration_ms": 123}
        """
        start_time = time.time()
        check_name = "gcs_access"

        try:
            details = {}

            # Check 1: Verify CATBOOST_V8_MODEL_PATH if set
            catboost_path = os.environ.get('CATBOOST_V8_MODEL_PATH')
            if catboost_path and catboost_path.startswith('gs://'):
                # Parse gs://bucket/path/to/file.cbm
                parts = catboost_path[5:].split('/', 1)
                bucket_name = parts[0]
                blob_path = parts[1] if len(parts) > 1 else None

                if not blob_path:
                    details['catboost_model'] = {
                        'status': 'fail',
                        'error': 'Invalid CATBOOST_V8_MODEL_PATH format'
                    }
                    return {
                        'check': check_name,
                        'status': 'fail',
                        'details': details,
                        'duration_ms': int((time.time() - start_time) * 1000)
                    }

                # Try to access the model file
                bucket = self.storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_path)

                if blob.exists():
                    # Verify we can read metadata (not the whole file)
                    blob.reload()
                    details['catboost_model'] = {
                        'status': 'pass',
                        'path': catboost_path,
                        'size_bytes': blob.size,
                        'updated': blob.updated.isoformat() if blob.updated else None
                    }
                else:
                    details['catboost_model'] = {
                        'status': 'fail',
                        'error': f'Model file not found: {catboost_path}'
                    }
                    return {
                        'check': check_name,
                        'status': 'fail',
                        'details': details,
                        'duration_ms': int((time.time() - start_time) * 1000)
                    }
            else:
                details['catboost_model'] = {
                    'status': 'skip',
                    'reason': 'CATBOOST_V8_MODEL_PATH not set or not GCS path'
                }

            # Check 2: Test access to data bucket (nba-scraped-data)
            test_bucket_name = "nba-scraped-data"
            try:
                bucket = self.storage_client.bucket(test_bucket_name)
                # Try to list one blob to verify access
                blobs = list(bucket.list_blobs(max_results=1))
                details['data_bucket'] = {
                    'status': 'pass',
                    'bucket': test_bucket_name,
                    'accessible': True
                }
            except Exception as e:
                details['data_bucket'] = {
                    'status': 'fail',
                    'error': str(e)
                }
                return {
                    'check': check_name,
                    'status': 'fail',
                    'details': details,
                    'duration_ms': int((time.time() - start_time) * 1000)
                }

            return {
                'check': check_name,
                'status': 'pass',
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000)
            }

        except Exception as e:
            logger.error(f"GCS health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000)
            }

    def check_bigquery_access(self) -> Dict[str, Any]:
        """
        Check BigQuery access by running test queries.

        Tests:
        - Access to nba_predictions dataset
        - Ability to query player_prop_predictions table
        - Query performance

        Returns:
            {"check": "bigquery_access", "status": "pass|fail", "details": {...}, "duration_ms": 123}
        """
        start_time = time.time()
        check_name = "bigquery_access"

        try:
            # Test query: Count predictions from today
            predictions_table = os.environ.get('PREDICTIONS_TABLE', 'nba_predictions.player_prop_predictions')

            query = f"""
                SELECT COUNT(*) as count
                FROM `{self.project_id}.{predictions_table}`
                WHERE game_date >= CURRENT_DATE()
                LIMIT 1
            """

            query_job = self.bq_client.query(query)
            results = list(query_job.result())

            details = {
                'table': predictions_table,
                'query_successful': True,
                'row_count': results[0]['count'] if results else 0
            }

            return {
                'check': check_name,
                'status': 'pass',
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000)
            }

        except Exception as e:
            logger.error(f"BigQuery health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000)
            }

    def check_model_loading(self) -> Dict[str, Any]:
        """
        Check that ML models can be loaded.

        Tests:
        - CatBoost V8 model loading (if CATBOOST_V8_MODEL_PATH set)
        - Model file validity

        Note: This performs a quick validation, not a full inference test.

        Returns:
            {"check": "model_loading", "status": "pass|fail", "details": {...}, "duration_ms": 123}
        """
        start_time = time.time()
        check_name = "model_loading"

        try:
            details = {}

            # Check CatBoost model
            catboost_path = os.environ.get('CATBOOST_V8_MODEL_PATH')

            if catboost_path:
                # Verify path format
                if catboost_path.startswith('gs://'):
                    if not catboost_path.endswith('.cbm'):
                        details['catboost_v8'] = {
                            'status': 'fail',
                            'error': 'Invalid model path format (must end with .cbm)'
                        }
                    else:
                        details['catboost_v8'] = {
                            'status': 'pass',
                            'path': catboost_path,
                            'format_valid': True,
                            'note': 'Model loading deferred to first prediction (lazy load)'
                        }
                elif Path(catboost_path).exists():
                    details['catboost_v8'] = {
                        'status': 'pass',
                        'path': catboost_path,
                        'file_exists': True
                    }
                else:
                    details['catboost_v8'] = {
                        'status': 'fail',
                        'error': f'Local model file not found: {catboost_path}'
                    }
                    return {
                        'check': check_name,
                        'status': 'fail',
                        'details': details,
                        'duration_ms': int((time.time() - start_time) * 1000)
                    }
            else:
                # No model path set - check for local models
                models_dir = Path(__file__).parent.parent.parent / "models"
                model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))

                if model_files:
                    details['catboost_v8'] = {
                        'status': 'pass',
                        'source': 'local_models_directory',
                        'model_count': len(model_files),
                        'latest_model': str(model_files[0].name)
                    }
                else:
                    details['catboost_v8'] = {
                        'status': 'warn',
                        'warning': 'No CATBOOST_V8_MODEL_PATH set and no local models found',
                        'fallback_mode': True
                    }

            overall_status = 'pass'
            if any(d.get('status') == 'fail' for d in details.values()):
                overall_status = 'fail'

            return {
                'check': check_name,
                'status': overall_status,
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000)
            }

        except Exception as e:
            logger.error(f"Model loading health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000)
            }

    def check_configuration(self) -> Dict[str, Any]:
        """
        Check that all required configuration is valid.

        Tests:
        - Required environment variables are set
        - Values are parseable and valid
        - Configuration is consistent

        Returns:
            {"check": "configuration", "status": "pass|fail", "details": {...}, "duration_ms": 123}
        """
        start_time = time.time()
        check_name = "configuration"

        try:
            details = {}
            required_vars = ['GCP_PROJECT_ID']
            optional_vars = [
                'CATBOOST_V8_MODEL_PATH',
                'PREDICTIONS_TABLE',
                'PUBSUB_READY_TOPIC'
            ]

            # Check required vars
            for var in required_vars:
                value = os.environ.get(var)
                if value:
                    details[var] = {'status': 'pass', 'set': True}
                else:
                    details[var] = {'status': 'fail', 'set': False, 'error': 'Required env var not set'}
                    return {
                        'check': check_name,
                        'status': 'fail',
                        'details': details,
                        'duration_ms': int((time.time() - start_time) * 1000)
                    }

            # Check optional vars (warn if not set)
            for var in optional_vars:
                value = os.environ.get(var)
                details[var] = {
                    'status': 'pass' if value else 'warn',
                    'set': bool(value),
                    'value': value if value else 'using default'
                }

            return {
                'check': check_name,
                'status': 'pass',
                'details': details,
                'duration_ms': int((time.time() - start_time) * 1000)
            }

        except Exception as e:
            logger.error(f"Configuration health check failed: {e}", exc_info=True)
            return {
                'check': check_name,
                'status': 'fail',
                'error': str(e),
                'duration_ms': int((time.time() - start_time) * 1000)
            }

    def run_all_checks(self, parallel: bool = True) -> Dict[str, Any]:
        """
        Run all health checks.

        Args:
            parallel: If True, run checks in parallel (faster, default: True)

        Returns:
            {
                "status": "healthy" | "unhealthy",
                "checks": [...],
                "total_duration_ms": 123,
                "checks_run": 4,
                "checks_passed": 4
            }
        """
        overall_start = time.time()
        checks = []

        if parallel:
            # Run checks in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(self.check_gcs_access): "gcs_access",
                    executor.submit(self.check_bigquery_access): "bigquery_access",
                    executor.submit(self.check_model_loading): "model_loading",
                    executor.submit(self.check_configuration): "configuration"
                }

                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=2.0)  # 2 second timeout per check
                        checks.append(result)
                    except Exception as e:
                        check_name = futures[future]
                        logger.error(f"Health check {check_name} failed with exception: {e}", exc_info=True)
                        checks.append({
                            'check': check_name,
                            'status': 'fail',
                            'error': f'Exception: {str(e)}',
                            'duration_ms': 0
                        })
        else:
            # Run checks sequentially
            checks = [
                self.check_gcs_access(),
                self.check_bigquery_access(),
                self.check_model_loading(),
                self.check_configuration()
            ]

        # Determine overall status
        total_duration_ms = int((time.time() - overall_start) * 1000)
        checks_run = len(checks)
        checks_passed = sum(1 for c in checks if c.get('status') == 'pass')
        checks_failed = sum(1 for c in checks if c.get('status') == 'fail')

        overall_status = 'healthy' if checks_failed == 0 else 'unhealthy'

        return {
            'status': overall_status,
            'checks': checks,
            'total_duration_ms': total_duration_ms,
            'checks_run': checks_run,
            'checks_passed': checks_passed,
            'checks_failed': checks_failed
        }
