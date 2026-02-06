#!/usr/bin/env python3
"""
Feature Store Health Check

Validates that ml feature store (ml_feature_store_v2) is populated correctly
and identifies any quality issues using the new quality fields:
is_quality_ready, quality_alert_level, matchup_quality_pct, etc.

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
        """Check if data exists for the date in ml_feature_store_v2."""
        query = f"""
        SELECT COUNT(*) as record_count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @check_date
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
        """Check production readiness using is_quality_ready from ml_feature_store_v2."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(is_quality_ready = TRUE) as ready
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @check_date
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
            "name": "Production Readiness (is_quality_ready)",
            "severity": severity,
            "message": f"{ready}/{total} records quality-ready ({pct_ready:.1f}%)",
            "value": pct_ready
        }

    def _check_null_rates(self, check_date: date) -> Dict:
        """Check NULL rates for critical features in ml_feature_store_v2."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(feature_quality_score IS NULL) as null_quality_score,
            COUNTIF(matchup_quality_pct IS NULL) as null_matchup,
            COUNTIF(player_history_quality_pct IS NULL) as null_history,
            COUNTIF(game_context_quality_pct IS NULL) as null_context
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @check_date
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
            "feature_quality_score": result.null_quality_score / total * 100,
            "matchup_quality_pct": result.null_matchup / total * 100,
            "player_history_quality_pct": result.null_history / total * 100,
            "game_context_quality_pct": result.null_context / total * 100
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
            message = "All NULL rates < 2%"

        return {
            "name": "NULL Rates",
            "severity": severity,
            "message": message,
            "value": null_rates
        }

    def _check_quality_tiers(self, check_date: date) -> Dict:
        """Check quality_alert_level distribution from ml_feature_store_v2."""
        query = f"""
        SELECT
            quality_alert_level,
            COUNT(*) as count
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @check_date
        GROUP BY quality_alert_level
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        results = self.client.query(query, job_config=job_config)
        level_counts = {row.quality_alert_level: row.count for row in results if row.quality_alert_level}

        red_count = level_counts.get("red", 0)
        yellow_count = level_counts.get("yellow", 0)
        green_count = level_counts.get("green", 0)
        total = sum(level_counts.values())

        if total == 0:
            return {
                "name": "Quality Alert Levels",
                "severity": SEVERITY_WARNING,
                "message": "No quality alert level data",
                "value": {}
            }

        red_pct = (red_count / total * 100) if total > 0 else 0

        if red_pct > 5:
            severity = SEVERITY_ERROR
        elif red_pct > 2 or yellow_count > total * 0.2:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_OK

        return {
            "name": "Quality Alert Levels",
            "severity": severity,
            "message": f"green={green_count}, yellow={yellow_count}, red={red_count} ({red_pct:.1f}% red)",
            "value": level_counts
        }

    def _check_completeness(self, check_date: date) -> Dict:
        """Check data completeness and matchup quality from ml_feature_store_v2."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(is_quality_ready = TRUE) as complete,
            AVG(feature_quality_score) as avg_quality,
            AVG(matchup_quality_pct) as avg_matchup_quality
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @check_date
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("check_date", "DATE", check_date)
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]
        total = result.total
        complete = result.complete
        avg_quality = result.avg_quality or 0
        avg_matchup = result.avg_matchup_quality or 0

        pct_complete = (complete / total * 100) if total > 0 else 0

        # Flag matchup quality separately (Session 132 recurrence indicator)
        matchup_warning = ""
        if avg_matchup < 50 and total > 0:
            matchup_warning = f" | WARNING: avg matchup_quality_pct={avg_matchup:.1f}% (<50%)"

        if pct_complete < 95 or avg_matchup < 50:
            severity = SEVERITY_ERROR
        elif pct_complete < 98:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_OK

        return {
            "name": "Completeness & Matchup Quality",
            "severity": severity,
            "message": f"{complete}/{total} quality-ready ({pct_complete:.1f}%), avg_quality={avg_quality:.1f}{matchup_warning}",
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
            MAX(created_at) as last_processed
        FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = @check_date
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
            message = f"Data processed {age_hours:.1f} hours ago"

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
