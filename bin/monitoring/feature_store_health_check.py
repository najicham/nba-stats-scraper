#!/usr/bin/env python3
"""
Feature Store Health Check

Validates that ml feature store (player_daily_cache) is populated correctly
and identifies any quality issues.

Usage:
    python bin/monitoring/feature_store_health_check.py [--date YYYY-MM-DD] [--alert]
"""

import argparse
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional
from google.cloud import bigquery

# Severity levels
SEVERITY_OK = "OK"
SEVERITY_WARNING = "WARNING"
SEVERITY_ERROR = "ERROR"
SEVERITY_CRITICAL = "CRITICAL"


class FeatureStoreHealthCheck:
    """Validates feature store health and data quality."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.issues = []

    def run_all_checks(self, check_date: date) -> Dict:
        """Run all health checks for the given date."""
        print(f"🔍 Running Feature Store Health Check for {check_date}")
        print("=" * 70)

        results = {
            "date": check_date.isoformat(),
            "checks": [],
            "max_severity": SEVERITY_OK,
            "summary": {}
        }

        # Check 1: Data exists for date
        coverage_result = self._check_date_coverage(check_date)
        results["checks"].append(coverage_result)

        if coverage_result["severity"] == SEVERITY_CRITICAL:
            print(f"\n❌ CRITICAL: No data for {check_date}. Skipping further checks.")
            results["max_severity"] = SEVERITY_CRITICAL
            return results

        # Check 2: Production readiness
        readiness_result = self._check_production_readiness(check_date)
        results["checks"].append(readiness_result)

        # Check 3: NULL rates for critical features
        null_result = self._check_null_rates(check_date)
        results["checks"].append(null_result)

        # Check 4: Quality tiers
        quality_result = self._check_quality_tiers(check_date)
        results["checks"].append(quality_result)

        # Check 5: Completeness
        completeness_result = self._check_completeness(check_date)
        results["checks"].append(completeness_result)

        # Check 6: Downstream usage (predictions)
        usage_result = self._check_downstream_usage(check_date)
        results["checks"].append(usage_result)

        # Check 7: Stale data
        staleness_result = self._check_data_staleness(check_date)
        results["checks"].append(staleness_result)

        # Determine max severity
        severities = [c["severity"] for c in results["checks"]]
        if SEVERITY_CRITICAL in severities:
            results["max_severity"] = SEVERITY_CRITICAL
        elif SEVERITY_ERROR in severities:
            results["max_severity"] = SEVERITY_ERROR
        elif SEVERITY_WARNING in severities:
            results["max_severity"] = SEVERITY_WARNING
        else:
            results["max_severity"] = SEVERITY_OK

        # Generate summary
        results["summary"] = self._generate_summary(results["checks"])

        return results

    def _check_date_coverage(self, check_date: date) -> Dict:
        """Check if data exists for the date."""
        query = f"""
        SELECT COUNT(*) as record_count
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = @check_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        record_count = result.record_count

        if record_count == 0:
            return {
                "name": "Date Coverage",
                "severity": SEVERITY_CRITICAL,
                "message": f"No feature store records for {check_date}",
                "value": 0
            }
        elif record_count < 100:
            return {
                "name": "Date Coverage",
                "severity": SEVERITY_WARNING,
                "message": f"Low record count: {record_count} (expected >150 for game day)",
                "value": record_count
            }
        else:
            return {
                "name": "Date Coverage",
                "severity": SEVERITY_OK,
                "message": f"{record_count} records found",
                "value": record_count
            }

    def _check_production_readiness(self, check_date: date) -> Dict:
        """Check production readiness percentage."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(is_production_ready = TRUE) as ready
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = @check_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        total = result.total
        ready = result.ready
        pct_ready = (ready / total * 100) if total > 0 else 0

        if pct_ready < 95:
            severity = SEVERITY_ERROR
        elif pct_ready < 98:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_OK

        return {
            "name": "Production Readiness",
            "severity": severity,
            "message": f"{ready}/{total} records ready ({pct_ready:.1f}%)",
            "value": pct_ready
        }

    def _check_null_rates(self, check_date: date) -> Dict:
        """Check NULL rates for critical features."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(points_avg_last_10 IS NULL) as null_points,
            COUNTIF(minutes_avg_last_10 IS NULL) as null_minutes,
            COUNTIF(usage_rate_last_10 IS NULL) as null_usage,
            COUNTIF(ts_pct_last_10 IS NULL) as null_ts
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = @check_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        total = result.total

        if total == 0:
            return {
                "name": "NULL Rates",
                "severity": SEVERITY_CRITICAL,
                "message": "No data to check NULL rates",
                "value": {}
            }

        null_rates = {
            "points_avg_last_10": result.null_points / total * 100,
            "minutes_avg_last_10": result.null_minutes / total * 100,
            "usage_rate_last_10": result.null_usage / total * 100,
            "ts_pct_last_10": result.null_ts / total * 100
        }

        max_null_rate = max(null_rates.values())

        if max_null_rate > 5:
            severity = SEVERITY_ERROR
            message = f"High NULL rates detected (max: {max_null_rate:.1f}%)"
        elif max_null_rate > 2:
            severity = SEVERITY_WARNING
            message = f"Moderate NULL rates (max: {max_null_rate:.1f}%)"
        else:
            severity = SEVERITY_OK
            message = f"All NULL rates < 2% ✓"

        return {
            "name": "NULL Rates",
            "severity": severity,
            "message": message,
            "value": null_rates
        }

    def _check_quality_tiers(self, check_date: date) -> Dict:
        """Check quality tier distribution."""
        query = f"""
        SELECT
            quality_tier,
            COUNT(*) as count
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = @check_date
        GROUP BY quality_tier
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        results = self.client.query(query, job_config=job_config)
        tier_counts = {row.quality_tier: row.count for row in results if row.quality_tier}

        poor_count = tier_counts.get("POOR", 0)
        total = sum(tier_counts.values())

        if total == 0:
            return {
                "name": "Quality Tiers",
                "severity": SEVERITY_WARNING,
                "message": "No quality tier data",
                "value": {}
            }

        poor_pct = (poor_count / total * 100) if total > 0 else 0

        if poor_pct > 5:
            severity = SEVERITY_ERROR
        elif poor_pct > 2:
            severity = SEVERITY_WARNING
        elif poor_count == 0 and total > 0:
            severity = SEVERITY_OK
        else:
            severity = SEVERITY_OK

        return {
            "name": "Quality Tiers",
            "severity": severity,
            "message": f"{poor_count} POOR quality records ({poor_pct:.1f}%)",
            "value": tier_counts
        }

    def _check_completeness(self, check_date: date) -> Dict:
        """Check data completeness."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(all_windows_complete = TRUE) as complete,
            AVG(completeness_percentage) as avg_completeness
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = @check_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        total = result.total
        complete = result.complete
        avg_completeness = result.avg_completeness or 0

        pct_complete = (complete / total * 100) if total > 0 else 0

        if pct_complete < 95:
            severity = SEVERITY_ERROR
        elif pct_complete < 98:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_OK

        return {
            "name": "Completeness",
            "severity": severity,
            "message": f"{complete}/{total} records complete ({pct_complete:.1f}%)",
            "value": pct_complete
        }

    def _check_downstream_usage(self, check_date: date) -> Dict:
        """Check if feature store data is being used by predictions."""
        query = f"""
        SELECT COUNT(*) as prediction_count
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = @check_date
          AND is_active = TRUE
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        prediction_count = result.prediction_count

        if prediction_count == 0:
            # Check if games are scheduled
            schedule_query = f"""
            SELECT COUNT(*) as game_count
            FROM `{self.project_id}.nba_reference.nba_schedule`
            WHERE game_date = @check_date
            """
            schedule_result = list(self.client.query(schedule_query, job_config=job_config))[0]
            game_count = schedule_result.game_count

            if game_count > 0:
                severity = SEVERITY_WARNING
                message = f"No predictions generated (but {game_count} games scheduled)"
            else:
                severity = SEVERITY_OK
                message = "No predictions (no games scheduled)"
        else:
            severity = SEVERITY_OK
            message = f"{prediction_count} predictions generated ✓"

        return {
            "name": "Downstream Usage",
            "severity": severity,
            "message": message,
            "value": prediction_count
        }

    def _check_data_staleness(self, check_date: date) -> Dict:
        """Check if data was processed recently."""
        query = f"""
        SELECT
            MAX(processed_at) as last_processed
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = @check_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        last_processed = result.last_processed

        if not last_processed:
            return {
                "name": "Data Staleness",
                "severity": SEVERITY_WARNING,
                "message": "No processing timestamp",
                "value": None
            }

        # Check if data is more than 48 hours old
        age_hours = (datetime.now(last_processed.tzinfo) - last_processed).total_seconds() / 3600

        if age_hours > 48:
            severity = SEVERITY_ERROR
            message = f"Data is {age_hours:.1f} hours old"
        elif age_hours > 24:
            severity = SEVERITY_WARNING
            message = f"Data is {age_hours:.1f} hours old"
        else:
            severity = SEVERITY_OK
            message = f"Data processed {age_hours:.1f} hours ago ✓"

        return {
            "name": "Data Staleness",
            "severity": severity,
            "message": message,
            "value": age_hours
        }

    def _generate_summary(self, checks: List[Dict]) -> Dict:
        """Generate summary of all checks."""
        total = len(checks)
        passed = sum(1 for c in checks if c["severity"] == SEVERITY_OK)
        warnings = sum(1 for c in checks if c["severity"] == SEVERITY_WARNING)
        errors = sum(1 for c in checks if c["severity"] == SEVERITY_ERROR)
        critical = sum(1 for c in checks if c["severity"] == SEVERITY_CRITICAL)

        return {
            "total_checks": total,
            "passed": passed,
            "warnings": warnings,
            "errors": errors,
            "critical": critical
        }

    def print_results(self, results: Dict):
        """Print health check results."""
        print("\n📊 Results:")
        print("-" * 70)

        for check in results["checks"]:
            icon = {
                SEVERITY_OK: "✅",
                SEVERITY_WARNING: "⚠️",
                SEVERITY_ERROR: "❌",
                SEVERITY_CRITICAL: "🚨"
            }[check["severity"]]

            print(f"{icon} {check['name']}: {check['message']}")

        print("\n" + "=" * 70)
        summary = results["summary"]
        print(f"Summary: {summary['passed']}/{summary['total_checks']} checks passed")

        if summary['warnings'] > 0:
            print(f"⚠️  {summary['warnings']} warnings")
        if summary['errors'] > 0:
            print(f"❌ {summary['errors']} errors")
        if summary['critical'] > 0:
            print(f"🚨 {summary['critical']} critical issues")

        print("\n" + "=" * 70)

        # Overall status
        severity_icon = {
            SEVERITY_OK: "✅ HEALTHY",
            SEVERITY_WARNING: "⚠️  DEGRADED",
            SEVERITY_ERROR: "❌ UNHEALTHY",
            SEVERITY_CRITICAL: "🚨 CRITICAL"
        }[results["max_severity"]]

        print(f"Overall Status: {severity_icon}")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Feature Store Health Check")
    parser.add_argument(
        "--date",
        type=str,
        help="Date to check (YYYY-MM-DD). Default: today"
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="Exit with error code if issues found (for CI/CD)"
    )

    args = parser.parse_args()

    # Parse date
    if args.date:
        check_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        check_date = date.today()

    # Run checks
    checker = FeatureStoreHealthCheck()
    results = checker.run_all_checks(check_date)
    checker.print_results(results)

    # Exit with error if alert mode and issues found
    if args.alert and results["max_severity"] in [SEVERITY_ERROR, SEVERITY_CRITICAL]:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
