"""
Validation System Integration for Health Endpoints

Bridges the gap between infrastructure health checks (shared/endpoints/health.py)
and data quality validation (validation/ directory).

Provides custom health checks that query validation results to detect data quality
issues and degrade service health accordingly.

Usage:
    from shared.health.validation_checks import create_validation_checks
    from shared.endpoints.health import HealthChecker

    validation_checks = create_validation_checks(project_id="nba-props-platform")

    health_checker = HealthChecker(
        project_id="nba-props-platform",
        service_name="data-pipeline",
        custom_checks=validation_checks
    )

Reference:
- Agent Analysis: docs/08-projects/current/health-endpoints-implementation/
                 AGENT-FINDINGS.md (validation integration section)
- Validation System: /validation/ directory
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from google.cloud import bigquery

logger = logging.getLogger(__name__)


def check_prediction_coverage(
    project_id: str,
    threshold: float = 90.0,
    lookback_hours: int = 24
) -> Dict[str, Any]:
    """
    Check prediction coverage from validation results.

    Queries the validation_results table to see if prediction coverage
    is above the threshold.

    Args:
        project_id: GCP project ID
        threshold: Minimum acceptable coverage percentage (default: 90%)
        lookback_hours: Hours to look back for validation results (default: 24)

    Returns:
        Dict with check results:
        {
            "check": "prediction_coverage",
            "status": "pass|warn|fail",
            "details": {
                "coverage_pct": 92.5,
                "threshold": 90.0,
                "last_validation": "2026-01-18T10:00:00Z",
                "affected_players": 5
            },
            "duration_ms": 150
        }
    """
    import time
    start = time.time()

    try:
        client = bigquery.Client(project=project_id)

        # Query latest validation results
        query = f"""
            SELECT
                validation_name,
                validation_timestamp,
                success,
                details
            FROM `{project_id}.validation.validation_results`
            WHERE validation_name = 'prediction_coverage'
                AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_hours} HOUR)
            ORDER BY validation_timestamp DESC
            LIMIT 1
        """

        result = list(client.query(query).result())

        if not result:
            return {
                "check": "prediction_coverage",
                "status": "warn",
                "details": {
                    "message": f"No prediction coverage validation found in last {lookback_hours} hours",
                    "threshold": threshold
                },
                "duration_ms": int((time.time() - start) * 1000)
            }

        row = result[0]
        details = row.details if hasattr(row, 'details') else {}

        # Extract coverage from details (format depends on validator implementation)
        coverage_pct = details.get('coverage_pct', 0.0)

        # Determine status
        if coverage_pct >= threshold:
            status = "pass"
        elif coverage_pct >= (threshold - 10):  # Within 10% of threshold
            status = "warn"
        else:
            status = "fail"

        return {
            "check": "prediction_coverage",
            "status": status,
            "details": {
                "coverage_pct": coverage_pct,
                "threshold": threshold,
                "last_validation": row.validation_timestamp.isoformat(),
                "affected_players": details.get('missing_predictions', 0)
            },
            "duration_ms": int((time.time() - start) * 1000)
        }

    except Exception as e:
        logger.error(f"Prediction coverage check failed: {e}")
        return {
            "check": "prediction_coverage",
            "status": "fail",
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }


def check_data_freshness(
    project_id: str,
    max_age_hours: int = 24
) -> Dict[str, Any]:
    """
    Check data freshness by querying latest scrape/process timestamps.

    Args:
        project_id: GCP project ID
        max_age_hours: Maximum acceptable data age in hours (default: 24)

    Returns:
        Dict with check results
    """
    import time
    start = time.time()

    try:
        client = bigquery.Client(project=project_id)

        # Check latest game data
        query = f"""
            SELECT
                MAX(game_date) as latest_game_date,
                MAX(scrape_timestamp) as latest_scrape
            FROM `{project_id}.raw_data.games`
            WHERE game_date >= CURRENT_DATE() - 2
        """

        result = list(client.query(query).result())

        if not result or not result[0].latest_scrape:
            return {
                "check": "data_freshness",
                "status": "warn",
                "details": {"message": "No recent game data found"},
                "duration_ms": int((time.time() - start) * 1000)
            }

        row = result[0]
        latest_scrape = row.latest_scrape
        age_hours = (datetime.utcnow() - latest_scrape.replace(tzinfo=None)).total_seconds() / 3600

        status = "pass" if age_hours <= max_age_hours else "warn" if age_hours <= (max_age_hours * 2) else "fail"

        return {
            "check": "data_freshness",
            "status": status,
            "details": {
                "latest_scrape": latest_scrape.isoformat(),
                "age_hours": round(age_hours, 2),
                "max_age_hours": max_age_hours,
                "latest_game_date": row.latest_game_date.isoformat() if row.latest_game_date else None
            },
            "duration_ms": int((time.time() - start) * 1000)
        }

    except Exception as e:
        logger.error(f"Data freshness check failed: {e}")
        return {
            "check": "data_freshness",
            "status": "fail",
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }


def check_validation_failures(
    project_id: str,
    lookback_hours: int = 24,
    max_failures: int = 5
) -> Dict[str, Any]:
    """
    Check for recent validation failures.

    Args:
        project_id: GCP project ID
        lookback_hours: Hours to look back (default: 24)
        max_failures: Maximum acceptable failures (default: 5)

    Returns:
        Dict with check results
    """
    import time
    start = time.time()

    try:
        client = bigquery.Client(project=project_id)

        query = f"""
            SELECT
                COUNT(*) as failure_count,
                ARRAY_AGG(validation_name ORDER BY validation_timestamp DESC LIMIT 10) as failed_validations
            FROM `{project_id}.validation.validation_results`
            WHERE success = FALSE
                AND validation_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {lookback_hours} HOUR)
        """

        result = list(client.query(query).result())

        if not result:
            return {
                "check": "validation_failures",
                "status": "pass",
                "details": {"failure_count": 0, "max_failures": max_failures},
                "duration_ms": int((time.time() - start) * 1000)
            }

        row = result[0]
        failure_count = row.failure_count

        status = "pass" if failure_count <= max_failures else "warn" if failure_count <= (max_failures * 2) else "fail"

        return {
            "check": "validation_failures",
            "status": status,
            "details": {
                "failure_count": failure_count,
                "max_failures": max_failures,
                "recent_failures": row.failed_validations[:5] if hasattr(row, 'failed_validations') else []
            },
            "duration_ms": int((time.time() - start) * 1000)
        }

    except Exception as e:
        logger.error(f"Validation failures check failed: {e}")
        return {
            "check": "validation_failures",
            "status": "fail",
            "error": str(e),
            "duration_ms": int((time.time() - start) * 1000)
        }


def create_validation_checks(
    project_id: str,
    coverage_threshold: float = 90.0,
    freshness_hours: int = 24,
    max_failures: int = 5
) -> Dict[str, callable]:
    """
    Create validation check functions for use with HealthChecker.

    Args:
        project_id: GCP project ID
        coverage_threshold: Minimum prediction coverage percentage
        freshness_hours: Maximum acceptable data age
        max_failures: Maximum acceptable validation failures

    Returns:
        Dict of check name -> check function

    Example:
        from shared.health.validation_checks import create_validation_checks
        from shared.endpoints.health import HealthChecker

        validation_checks = create_validation_checks("nba-props-platform")

        health_checker = HealthChecker(
            project_id="nba-props-platform",
            service_name="data-pipeline",
            check_bigquery=True,
            custom_checks=validation_checks
        )

        # Health checks will now include validation metrics
        result = health_checker.run_all_checks()
        # result['checks'] will include:
        # - prediction_coverage
        # - data_freshness
        # - validation_failures
    """
    return {
        "prediction_coverage": lambda: check_prediction_coverage(
            project_id, coverage_threshold
        ),
        "data_freshness": lambda: check_data_freshness(
            project_id, freshness_hours
        ),
        "validation_failures": lambda: check_validation_failures(
            project_id, max_failures=max_failures
        )
    }


if __name__ == "__main__":
    # Demo: Run validation checks
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    project_id = "nba-props-platform"

    print("Demo: Validation Health Checks\n")
    print("=" * 60)

    # Run each check
    print("\n1. Prediction Coverage Check:")
    result = check_prediction_coverage(project_id)
    print(f"   Status: {result['status']}")
    print(f"   Details: {result.get('details', result.get('error'))}")

    print("\n2. Data Freshness Check:")
    result = check_data_freshness(project_id)
    print(f"   Status: {result['status']}")
    print(f"   Details: {result.get('details', result.get('error'))}")

    print("\n3. Validation Failures Check:")
    result = check_validation_failures(project_id)
    print(f"   Status: {result['status']}")
    print(f"   Details: {result.get('details', result.get('error'))}")

    print("\n" + "=" * 60)
    print("Note: These checks integrate with the existing validation system")
    print("      and can be added to health endpoints for real-time monitoring")
