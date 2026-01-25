#!/usr/bin/env python3
"""
Comprehensive Health Check Script

Single command to check entire pipeline health:
- Grading coverage (last 7 days)
- System performance updates
- GCS export freshness
- ML adjustment recency
- Feature availability
- Duplicate prediction detection

Usage:
    python bin/validation/comprehensive_health.py
    python bin/validation/comprehensive_health.py --days 3
    python bin/validation/comprehensive_health.py --json

Created: 2026-01-25
Part of: Post-Grading Quality Improvements (Session 17)
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery, storage

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


class HealthChecker:
    """Comprehensive pipeline health checker."""

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)
        self.gcs_client = storage.Client(project=project_id)

    def check_grading_coverage(self, days: int = 7) -> Dict:
        """Check grading coverage for last N days."""
        logger.info("Checking grading coverage...")

        query = f"""
        WITH dates AS (
            SELECT game_date
            FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
            WHERE game_status = 3
                AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
                AND game_date < CURRENT_DATE()
            GROUP BY game_date
        ),
        gradable AS (
            SELECT
                game_date,
                COUNT(*) as gradable_count
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
                AND is_active = TRUE
                AND current_points_line IS NOT NULL
                AND current_points_line != 20.0
                AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
                AND invalidation_reason IS NULL
            GROUP BY game_date
        ),
        graded AS (
            SELECT
                game_date,
                COUNT(*) as graded_count
            FROM `{self.project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            GROUP BY game_date
        )
        SELECT
            d.game_date,
            COALESCE(gp.gradable_count, 0) as gradable,
            COALESCE(gr.graded_count, 0) as graded,
            ROUND(COALESCE(gr.graded_count, 0) * 100.0 / NULLIF(gp.gradable_count, 0), 1) as coverage_pct
        FROM dates d
        LEFT JOIN gradable gp ON d.game_date = gp.game_date
        LEFT JOIN graded gr ON d.game_date = gr.game_date
        ORDER BY d.game_date DESC
        """

        try:
            results = list(self.bq_client.query(query).result())

            coverage_data = []
            low_coverage_dates = []

            for row in results:
                coverage_pct = row.coverage_pct or 0
                coverage_data.append({
                    'date': str(row.game_date),
                    'gradable': row.gradable,
                    'graded': row.graded,
                    'coverage_pct': coverage_pct
                })

                if coverage_pct < 90 and row.gradable > 0:
                    low_coverage_dates.append(str(row.game_date))

            avg_coverage = sum(d['coverage_pct'] for d in coverage_data) / len(coverage_data) if coverage_data else 0

            return {
                'status': 'OK' if not low_coverage_dates else 'WARNING',
                'avg_coverage': round(avg_coverage, 1),
                'dates_checked': len(coverage_data),
                'low_coverage_dates': low_coverage_dates,
                'details': coverage_data
            }
        except Exception as e:
            logger.error(f"Error checking grading coverage: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def check_system_performance(self) -> Dict:
        """Check if system performance metrics are up to date."""
        logger.info("Checking system performance...")

        query = f"""
        SELECT
            MAX(game_date) as latest_date,
            COUNT(DISTINCT system_id) as systems,
            COUNT(*) as records
        FROM `{self.project_id}.nba_predictions.system_daily_performance`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            latest_date = result.latest_date
            days_old = (date.today() - latest_date).days if latest_date else 999

            return {
                'status': 'OK' if days_old <= 2 else 'WARNING',
                'latest_date': str(latest_date) if latest_date else None,
                'days_old': days_old,
                'systems': result.systems or 0,
                'records': result.records or 0
            }
        except Exception as e:
            logger.error(f"Error checking system performance: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def check_gcs_exports(self) -> Dict:
        """Check freshness of GCS exports."""
        logger.info("Checking GCS exports...")

        exports_to_check = [
            'nba-props-platform-api/v1/results/latest.json',
            'nba-props-platform-api/v1/systems/performance.json',
        ]

        results = {}
        all_ok = True

        for blob_path in exports_to_check:
            bucket_name, blob_name = blob_path.split('/', 1)

            try:
                bucket = self.gcs_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)

                if blob.exists():
                    blob.reload()
                    updated = blob.updated
                    hours_old = (datetime.now(updated.tzinfo) - updated).total_seconds() / 3600

                    results[blob_name] = {
                        'status': 'OK' if hours_old < 48 else 'WARNING',
                        'updated': updated.isoformat(),
                        'hours_old': round(hours_old, 1)
                    }

                    if hours_old >= 48:
                        all_ok = False
                else:
                    results[blob_name] = {'status': 'ERROR', 'error': 'File not found'}
                    all_ok = False

            except Exception as e:
                results[blob_name] = {'status': 'ERROR', 'error': str(e)}
                all_ok = False

        return {
            'status': 'OK' if all_ok else 'WARNING',
            'exports': results
        }

    def check_ml_adjustments(self) -> Dict:
        """Check ML adjustment recency."""
        logger.info("Checking ML adjustments...")

        query = f"""
        SELECT
            MAX(as_of_date) as latest_date,
            COUNT(DISTINCT scoring_tier) as tiers
        FROM `{self.project_id}.nba_predictions.scoring_tier_adjustments`
        WHERE as_of_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            latest_date = result.latest_date
            days_old = (date.today() - latest_date).days if latest_date else 999

            return {
                'status': 'OK' if days_old <= 14 else 'WARNING',
                'latest_date': str(latest_date) if latest_date else None,
                'days_old': days_old,
                'tiers': result.tiers or 0
            }
        except Exception as e:
            logger.error(f"Error checking ML adjustments: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def check_feature_availability(self) -> Dict:
        """Check feature availability for recent dates."""
        logger.info("Checking feature availability...")

        query = f"""
        SELECT
            COUNT(DISTINCT player_lookup) as players,
            AVG(completeness_percentage) as avg_completeness,
            COUNTIF(completeness_percentage >= 90) * 100.0 / COUNT(*) as high_quality_pct
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            high_quality_pct = result.high_quality_pct or 0

            return {
                'status': 'OK' if high_quality_pct >= 95 else 'WARNING',
                'players': result.players or 0,
                'avg_completeness': round(result.avg_completeness or 0, 1),
                'high_quality_pct': round(high_quality_pct, 1)
            }
        except Exception as e:
            logger.error(f"Error checking feature availability: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def check_duplicates(self, days: int = 7) -> Dict:
        """Check for duplicate predictions."""
        logger.info("Checking for duplicate predictions...")

        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT prediction_id) as unique_ids
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        """

        try:
            result = list(self.bq_client.query(query).result())[0]

            total = result.total or 0
            unique = result.unique_ids or 0
            duplicates = total - unique

            return {
                'status': 'OK' if duplicates == 0 else 'WARNING',
                'total': total,
                'unique': unique,
                'duplicates': duplicates
            }
        except Exception as e:
            logger.error(f"Error checking duplicates: {e}")
            return {'status': 'ERROR', 'error': str(e)}

    def run_all_checks(self, days: int = 7) -> Dict:
        """Run all health checks."""
        logger.info(f"Running comprehensive health check (last {days} days)...")

        results = {
            'timestamp': datetime.now().isoformat(),
            'grading_coverage': self.check_grading_coverage(days),
            'system_performance': self.check_system_performance(),
            'gcs_exports': self.check_gcs_exports(),
            'ml_adjustments': self.check_ml_adjustments(),
            'feature_availability': self.check_feature_availability(),
            'duplicates': self.check_duplicates(days)
        }

        # Overall status
        statuses = [v.get('status') for v in results.values() if isinstance(v, dict) and 'status' in v]
        if 'ERROR' in statuses:
            results['overall_status'] = 'ERROR'
        elif 'WARNING' in statuses:
            results['overall_status'] = 'WARNING'
        else:
            results['overall_status'] = 'OK'

        return results


def format_report(results: Dict) -> str:
    """Format health check results as text report."""
    lines = [
        "=" * 70,
        "COMPREHENSIVE PIPELINE HEALTH CHECK",
        "=" * 70,
        f"Timestamp: {results['timestamp']}",
        f"Overall Status: {results['overall_status']}",
        "",
    ]

    # Grading Coverage
    grading = results['grading_coverage']
    lines.extend([
        "📊 GRADING COVERAGE:",
        f"   Status: {grading['status']}",
        f"   Average: {grading.get('avg_coverage', 0)}%",
        f"   Dates checked: {grading.get('dates_checked', 0)}",
    ])
    if grading.get('low_coverage_dates'):
        lines.append(f"   ⚠️  Low coverage dates: {', '.join(grading['low_coverage_dates'])}")
    lines.append("")

    # System Performance
    perf = results['system_performance']
    lines.extend([
        "⚙️  SYSTEM PERFORMANCE:",
        f"   Status: {perf['status']}",
        f"   Latest date: {perf.get('latest_date', 'N/A')}",
        f"   Days old: {perf.get('days_old', 'N/A')}",
        f"   Systems: {perf.get('systems', 0)}",
        ""
    ])

    # GCS Exports
    gcs = results['gcs_exports']
    lines.extend([
        "☁️  GCS EXPORTS:",
        f"   Status: {gcs['status']}",
    ])
    for export_name, export_data in gcs.get('exports', {}).items():
        if export_data.get('status') == 'OK':
            lines.append(f"   ✅ {export_name}: {export_data.get('hours_old', 0)}h old")
        else:
            lines.append(f"   ❌ {export_name}: {export_data.get('error', 'Error')}")
    lines.append("")

    # ML Adjustments
    ml = results['ml_adjustments']
    lines.extend([
        "🤖 ML ADJUSTMENTS:",
        f"   Status: {ml['status']}",
        f"   Latest date: {ml.get('latest_date', 'N/A')}",
        f"   Days old: {ml.get('days_old', 'N/A')}",
        f"   Tiers: {ml.get('tiers', 0)}",
        ""
    ])

    # Feature Availability
    features = results['feature_availability']
    lines.extend([
        "📈 FEATURE AVAILABILITY:",
        f"   Status: {features['status']}",
        f"   Players: {features.get('players', 0)}",
        f"   Avg completeness: {features.get('avg_completeness', 0)}%",
        f"   High quality: {features.get('high_quality_pct', 0)}%",
        ""
    ])

    # Duplicates
    dups = results['duplicates']
    lines.extend([
        "🔍 DUPLICATE DETECTION:",
        f"   Status: {dups['status']}",
        f"   Total predictions: {dups.get('total', 0)}",
        f"   Unique IDs: {dups.get('unique', 0)}",
        f"   Duplicates: {dups.get('duplicates', 0)}",
    ])

    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Comprehensive pipeline health check")
    parser.add_argument('--days', type=int, default=7, help='Days to check (default: 7)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    checker = HealthChecker()
    results = checker.run_all_checks(args.days)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        report = format_report(results)
        print(report)

    # Exit with appropriate code
    if results['overall_status'] == 'ERROR':
        sys.exit(2)
    elif results['overall_status'] == 'WARNING':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
