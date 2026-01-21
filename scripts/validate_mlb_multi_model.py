#!/usr/bin/env python3
# scripts/validate_mlb_multi_model.py
"""
MLB Multi-Model Architecture Validation Script

Validates the multi-model architecture is working correctly:
1. Service health check
2. Active systems verification
3. BigQuery schema validation
4. Daily coverage check
5. System performance metrics

Usage:
    python3 scripts/validate_mlb_multi_model.py [--service-url URL] [--project-id PROJECT]

Example:
    python3 scripts/validate_mlb_multi_model.py \\
        --service-url https://mlb-prediction-worker-xxx.run.app \\
        --project-id nba-props-platform
"""

import argparse
import requests
import sys
from datetime import date
from google.cloud import bigquery


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text):
    """Print a section header"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


def print_success(text):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_warning(text):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.END}")


def print_error(text):
    """Print error message"""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def validate_service_health(service_url):
    """Validate service is healthy and responding"""
    print_header("Service Health Check")

    try:
        response = requests.get(f"{service_url}/", timeout=10)

        if response.status_code == 200:
            print_success(f"Service is healthy (HTTP 200)")
            service_info = response.json()

            # Check version
            version = service_info.get('version', 'unknown')
            print(f"  Version: {version}")

            if version == '2.0.0':
                print_success("Correct version (2.0.0)")
            else:
                print_warning(f"Unexpected version: {version}")

            # Check architecture
            architecture = service_info.get('architecture', 'unknown')
            print(f"  Architecture: {architecture}")

            if architecture == 'multi-model':
                print_success("Multi-model architecture confirmed")
            else:
                print_error(f"Expected 'multi-model', got '{architecture}'")
                return False

            # Check active systems
            active_systems = service_info.get('active_systems', [])
            print(f"  Active Systems: {', '.join(active_systems)}")

            expected_systems = {'v1_baseline', 'v1_6_rolling', 'ensemble_v1'}
            if set(active_systems) == expected_systems:
                print_success("All expected systems active")
            else:
                missing = expected_systems - set(active_systems)
                extra = set(active_systems) - expected_systems
                if missing:
                    print_warning(f"Missing systems: {', '.join(missing)}")
                if extra:
                    print_warning(f"Unexpected systems: {', '.join(extra)}")

            # Check system metadata
            systems_info = service_info.get('systems', {})
            for system_id, system_data in systems_info.items():
                mae = system_data.get('mae', 'N/A')
                features = system_data.get('features', 'N/A')
                print(f"    {system_id}: MAE={mae}, Features={features}")

            return True
        else:
            print_error(f"Service health check failed (HTTP {response.status_code})")
            return False

    except requests.RequestException as e:
        print_error(f"Failed to connect to service: {e}")
        return False


def validate_bigquery_schema(project_id):
    """Validate BigQuery schema has system_id column"""
    print_header("BigQuery Schema Validation")

    try:
        client = bigquery.Client(project=project_id)
        table_ref = f"{project_id}.mlb_predictions.pitcher_strikeouts"

        # Get table schema
        table = client.get_table(table_ref)

        # Check for system_id column
        system_id_field = None
        for field in table.schema:
            if field.name == 'system_id':
                system_id_field = field
                break

        if system_id_field:
            print_success("system_id column exists")
            print(f"  Type: {system_id_field.field_type}")
            print(f"  Mode: {system_id_field.mode}")

            if system_id_field.mode == 'NULLABLE':
                print_warning("system_id is NULLABLE (expected during migration)")
            elif system_id_field.mode == 'REQUIRED':
                print_success("system_id is REQUIRED (migration complete)")

            return True
        else:
            print_error("system_id column not found")
            print("  Run migration: bq query < schemas/bigquery/mlb_predictions/migration_add_system_id.sql")
            return False

    except Exception as e:
        print_error(f"BigQuery schema validation failed: {e}")
        return False


def validate_views_exist(project_id):
    """Validate required BigQuery views exist"""
    print_header("BigQuery Views Validation")

    required_views = [
        'todays_picks',
        'system_comparison',
        'system_performance',
        'daily_coverage',
        'system_agreement'
    ]

    client = bigquery.Client(project=project_id)
    all_exist = True

    for view_name in required_views:
        view_ref = f"{project_id}.mlb_predictions.{view_name}"
        try:
            client.get_table(view_ref)
            print_success(f"View exists: {view_name}")
        except Exception:
            print_error(f"View missing: {view_name}")
            all_exist = False

    if not all_exist:
        print_warning("Create views: bq query < schemas/bigquery/mlb_predictions/multi_system_views.sql")

    return all_exist


def validate_daily_coverage(project_id, check_date=None):
    """Validate all systems ran for today's pitchers"""
    print_header("Daily Coverage Check")

    if check_date is None:
        check_date = date.today()

    client = bigquery.Client(project=project_id)

    query = f"""
    SELECT
        game_date,
        unique_pitchers,
        systems_per_date,
        systems_used,
        v1_count,
        v1_6_count,
        ensemble_count,
        min_systems_per_pitcher,
        max_systems_per_pitcher
    FROM `{project_id}.mlb_predictions.daily_coverage`
    WHERE game_date = '{check_date.isoformat()}'
    """

    try:
        results = list(client.query(query).result())

        if not results:
            print_warning(f"No predictions found for {check_date}")
            print("  This is normal if predictions haven't run yet today")
            return True

        row = results[0]

        print(f"Date: {row.game_date}")
        print(f"Unique Pitchers: {row.unique_pitchers}")
        print(f"Systems Used: {row.systems_used}")
        print(f"  V1 Baseline: {row.v1_count}")
        print(f"  V1.6 Rolling: {row.v1_6_count}")
        print(f"  Ensemble V1: {row.ensemble_count}")

        # Validate coverage
        expected_systems = 3
        if row.min_systems_per_pitcher == expected_systems and row.max_systems_per_pitcher == expected_systems:
            print_success(f"All pitchers have {expected_systems} systems")
            return True
        else:
            print_error(f"Incomplete coverage: min={row.min_systems_per_pitcher}, max={row.max_systems_per_pitcher}")
            print("  Expected: All pitchers should have 3 systems")
            return False

    except Exception as e:
        print_error(f"Daily coverage check failed: {e}")
        return False


def validate_system_performance(project_id):
    """Check system performance metrics"""
    print_header("System Performance Metrics")

    client = bigquery.Client(project=project_id)

    query = f"""
    SELECT
        system_id,
        total_predictions,
        actionable_predictions,
        graded_predictions,
        ROUND(mae, 2) as mae,
        recommendation_accuracy_pct,
        ROUND(avg_confidence, 1) as avg_confidence
    FROM `{project_id}.mlb_predictions.system_performance`
    ORDER BY system_id
    """

    try:
        results = list(client.query(query).result())

        if not results:
            print_warning("No performance metrics available yet")
            print("  This is normal if predictions haven't been graded yet")
            return True

        for row in results:
            print(f"\n{row.system_id}:")
            print(f"  Total Predictions: {row.total_predictions}")
            print(f"  Actionable: {row.actionable_predictions}")
            print(f"  Graded: {row.graded_predictions}")
            print(f"  MAE: {row.mae if row.mae else 'N/A'}")
            print(f"  Accuracy: {row.recommendation_accuracy_pct if row.recommendation_accuracy_pct else 'N/A'}%")
            print(f"  Avg Confidence: {row.avg_confidence if row.avg_confidence else 'N/A'}")

        print_success("Performance metrics loaded")
        return True

    except Exception as e:
        print_error(f"Performance metrics check failed: {e}")
        return False


def main():
    """Main validation script"""
    parser = argparse.ArgumentParser(description='Validate MLB Multi-Model Architecture')
    parser.add_argument('--service-url', help='Cloud Run service URL')
    parser.add_argument('--project-id', default='nba-props-platform', help='GCP project ID')
    parser.add_argument('--date', help='Date to check (YYYY-MM-DD)', default=None)

    args = parser.parse_args()

    check_date = date.fromisoformat(args.date) if args.date else date.today()

    print(f"\n{Colors.BOLD}MLB Multi-Model Architecture Validation{Colors.END}")
    print(f"Project: {args.project_id}")
    if args.service_url:
        print(f"Service: {args.service_url}")
    print(f"Check Date: {check_date}")

    results = []

    # 1. Service health (if URL provided)
    if args.service_url:
        results.append(('Service Health', validate_service_health(args.service_url)))
    else:
        print_warning("Skipping service health check (no --service-url provided)")

    # 2. BigQuery schema
    results.append(('BigQuery Schema', validate_bigquery_schema(args.project_id)))

    # 3. Views
    results.append(('BigQuery Views', validate_views_exist(args.project_id)))

    # 4. Daily coverage
    results.append(('Daily Coverage', validate_daily_coverage(args.project_id, check_date)))

    # 5. System performance
    results.append(('System Performance', validate_system_performance(args.project_id)))

    # Summary
    print_header("Validation Summary")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for check_name, result in results:
        if result:
            print_success(f"{check_name}: PASSED")
        else:
            print_error(f"{check_name}: FAILED")

    print(f"\n{Colors.BOLD}Overall: {passed}/{total} checks passed{Colors.END}\n")

    if passed == total:
        print_success("All validation checks passed! ✓")
        sys.exit(0)
    else:
        print_error(f"{total - passed} validation check(s) failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
