#!/usr/bin/env python3
"""
Monitor resolution system health.

This module checks:
1. Stale unresolved names (older than threshold)
2. Resolution rate over time
3. AI performance metrics
4. Alias usage statistics

Usage:
    # Run health check
    python monitoring/resolution_health_check.py

    # Run with specific threshold
    python monitoring/resolution_health_check.py --stale-hours 12

    # Output as JSON
    python monitoring/resolution_health_check.py --json
"""

import argparse
import json
import logging
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ResolutionHealthMonitor:
    """
    Monitor resolution system and alert on issues.
    """

    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def check_stale_unresolved(self, hours_threshold: int = 24) -> Dict:
        """
        Check for unresolved names older than threshold.

        Args:
            hours_threshold: Number of hours after which an unresolved name is "stale"

        Returns:
            Dict with count and list of stale names
        """
        query = f"""
        SELECT
            normalized_lookup,
            team_abbr,
            season,
            source,
            created_at,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, HOUR) as hours_old
        FROM `{self.project_id}.nba_reference.unresolved_player_names`
        WHERE status = 'pending'
        AND created_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        ORDER BY created_at ASC
        LIMIT 20
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("hours", "INT64", hours_threshold)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result(timeout=60))

            stale_names = []
            for row in results:
                stale_names.append({
                    'name': row.normalized_lookup,
                    'team': row.team_abbr,
                    'season': row.season,
                    'source': row.source,
                    'hours_old': row.hours_old
                })

            # Get total count
            count_query = f"""
            SELECT COUNT(*) as count
            FROM `{self.project_id}.nba_reference.unresolved_player_names`
            WHERE status = 'pending'
            AND created_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
            """

            count_result = list(self.client.query(count_query, job_config=job_config).result(timeout=60))[0]

            return {
                'count': count_result.count,
                'threshold_hours': hours_threshold,
                'examples': stale_names,
                'status': 'CRITICAL' if count_result.count > 0 else 'OK'
            }

        except Exception as e:
            logger.error(f"Error checking stale unresolved: {e}")
            return {'error': str(e), 'status': 'ERROR'}

    def check_resolution_rate(self, days: int = 7) -> Dict:
        """
        Check resolution success rate over time period.

        Args:
            days: Number of days to look back

        Returns:
            Dict with resolution metrics
        """
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNTIF(status = 'resolved') as resolved,
            COUNTIF(status = 'pending') as pending,
            COUNTIF(status = 'snoozed') as snoozed,
            COUNTIF(status IN ('data_error', 'invalid')) as errors,
            SAFE_DIVIDE(COUNTIF(status = 'resolved'), COUNT(*)) as resolution_rate
        FROM `{self.project_id}.nba_reference.unresolved_player_names`
        WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        try:
            result = list(self.client.query(query, job_config=job_config).result(timeout=60))[0]

            rate = result.resolution_rate or 0
            status = 'OK' if rate >= 0.9 or result.total < 10 else 'WARNING'

            return {
                'period_days': days,
                'total': result.total,
                'resolved': result.resolved,
                'pending': result.pending,
                'snoozed': result.snoozed,
                'errors': result.errors,
                'resolution_rate': round(rate * 100, 1),
                'status': status
            }

        except Exception as e:
            logger.error(f"Error checking resolution rate: {e}")
            return {'error': str(e), 'status': 'ERROR'}

    def check_daily_trends(self, days: int = 7) -> Dict:
        """
        Get daily resolution trends.

        Returns:
            Dict with daily breakdown
        """
        query = f"""
        SELECT
            DATE(created_at) as date,
            COUNT(*) as total,
            COUNTIF(status = 'resolved') as resolved,
            COUNTIF(status = 'pending') as pending
        FROM `{self.project_id}.nba_reference.unresolved_player_names`
        WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        GROUP BY date
        ORDER BY date DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result(timeout=60))

            trends = []
            for row in results:
                trends.append({
                    'date': row.date.isoformat(),
                    'total': row.total,
                    'resolved': row.resolved,
                    'pending': row.pending
                })

            return {
                'period_days': days,
                'daily_data': trends,
                'status': 'OK'
            }

        except Exception as e:
            logger.error(f"Error getting trends: {e}")
            return {'error': str(e), 'status': 'ERROR'}

    def check_alias_stats(self) -> Dict:
        """
        Check alias table statistics.

        Returns:
            Dict with alias metrics
        """
        query = f"""
        SELECT
            alias_type,
            COUNT(*) as count,
            COUNTIF(is_active = TRUE) as active
        FROM `{self.project_id}.nba_reference.player_aliases`
        GROUP BY alias_type
        ORDER BY count DESC
        """

        try:
            results = list(self.client.query(query).result(timeout=60))

            by_type = []
            total_active = 0
            for row in results:
                by_type.append({
                    'type': row.alias_type,
                    'count': row.count,
                    'active': row.active
                })
                total_active += row.active

            return {
                'total_active': total_active,
                'by_type': by_type,
                'status': 'OK'
            }

        except Exception as e:
            logger.error(f"Error checking alias stats: {e}")
            return {'error': str(e), 'status': 'ERROR'}

    def check_sources(self, days: int = 30) -> Dict:
        """
        Check which sources generate most unresolved names.

        Returns:
            Dict with source breakdown
        """
        query = f"""
        SELECT
            source,
            COUNT(*) as total,
            COUNTIF(status = 'resolved') as resolved,
            COUNTIF(status = 'pending') as pending
        FROM `{self.project_id}.nba_reference.unresolved_player_names`
        WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        GROUP BY source
        ORDER BY total DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days)
            ]
        )

        try:
            results = list(self.client.query(query, job_config=job_config).result(timeout=60))

            sources = []
            for row in results:
                sources.append({
                    'source': row.source,
                    'total': row.total,
                    'resolved': row.resolved,
                    'pending': row.pending
                })

            return {
                'period_days': days,
                'sources': sources,
                'status': 'OK'
            }

        except Exception as e:
            logger.error(f"Error checking sources: {e}")
            return {'error': str(e), 'status': 'ERROR'}

    def run_full_health_check(self, stale_hours: int = 24) -> Dict:
        """
        Run complete health check and return all metrics.

        Args:
            stale_hours: Hours threshold for stale check

        Returns:
            Dict with all health metrics
        """
        logger.info("Running resolution system health check...")

        results = {
            'timestamp': datetime.utcnow().isoformat(),
            'stale_check': self.check_stale_unresolved(stale_hours),
            'resolution_rate': self.check_resolution_rate(days=7),
            'daily_trends': self.check_daily_trends(days=7),
            'alias_stats': self.check_alias_stats(),
            'source_breakdown': self.check_sources(days=30)
        }

        # Determine overall status
        statuses = [
            results['stale_check'].get('status', 'OK'),
            results['resolution_rate'].get('status', 'OK')
        ]

        if 'CRITICAL' in statuses:
            results['overall_status'] = 'CRITICAL'
        elif 'WARNING' in statuses:
            results['overall_status'] = 'WARNING'
        elif 'ERROR' in statuses:
            results['overall_status'] = 'ERROR'
        else:
            results['overall_status'] = 'OK'

        return results

    def print_report(self, results: Dict):
        """Print a human-readable health report."""
        print("\n" + "=" * 70)
        print("RESOLUTION SYSTEM HEALTH CHECK")
        print("=" * 70)
        print(f"Timestamp: {results['timestamp']}")
        print(f"Overall Status: {results['overall_status']}")
        print()

        # Stale check
        stale = results['stale_check']
        print(f"[{stale.get('status', 'N/A')}] Stale Unresolved Names")
        print(f"  - Threshold: {stale.get('threshold_hours', 'N/A')} hours")
        print(f"  - Count: {stale.get('count', 'N/A')}")
        if stale.get('examples'):
            print("  - Examples:")
            for ex in stale['examples'][:5]:
                print(f"    - {ex['name']} ({ex['team']}/{ex['season']}) - {ex['hours_old']}h old")
        print()

        # Resolution rate
        rate = results['resolution_rate']
        print(f"[{rate.get('status', 'N/A')}] Resolution Rate (last {rate.get('period_days', 7)} days)")
        print(f"  - Total: {rate.get('total', 'N/A')}")
        print(f"  - Resolved: {rate.get('resolved', 'N/A')}")
        print(f"  - Pending: {rate.get('pending', 'N/A')}")
        print(f"  - Rate: {rate.get('resolution_rate', 'N/A')}%")
        print()

        # Alias stats
        alias = results['alias_stats']
        print(f"[{alias.get('status', 'N/A')}] Alias Statistics")
        print(f"  - Total active aliases: {alias.get('total_active', 'N/A')}")
        if alias.get('by_type'):
            print("  - By type:")
            for t in alias['by_type']:
                print(f"    - {t['type']}: {t['active']} active")
        print()

        # Source breakdown
        sources = results['source_breakdown']
        print(f"[{sources.get('status', 'N/A')}] Source Breakdown (last {sources.get('period_days', 30)} days)")
        if sources.get('sources'):
            for s in sources['sources'][:5]:
                print(f"  - {s['source']}: {s['total']} total, {s['pending']} pending")
        print()

        print("=" * 70)

        # Recommendations
        if results['overall_status'] != 'OK':
            print("\nRECOMMENDATIONS:")
            if stale.get('count', 0) > 0:
                print("  - Run: python tools/player_registry/resolve_unresolved_batch.py")
                print("    to resolve stale unresolved names with AI")
            if rate.get('resolution_rate', 100) < 90:
                print("  - Check alias table for missing entries")
                print("  - Review source-specific normalization")
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Check resolution system health"
    )
    parser.add_argument(
        '--stale-hours',
        type=int,
        default=24,
        help='Hours threshold for stale unresolved names (default: 24)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON instead of human-readable report'
    )

    args = parser.parse_args()

    monitor = ResolutionHealthMonitor()
    results = monitor.run_full_health_check(stale_hours=args.stale_hours)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        monitor.print_report(results)

    # Exit with appropriate code
    if results['overall_status'] == 'CRITICAL':
        sys.exit(2)
    elif results['overall_status'] in ('WARNING', 'ERROR'):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
