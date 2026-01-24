#!/usr/bin/env python3
"""
BigQuery Cost Tracker

Tracks and monitors BigQuery query costs using INFORMATION_SCHEMA.JOBS.
Aggregates costs by day, dataset, and user for dashboard display.

Architecture:
- Queries INFORMATION_SCHEMA.JOBS for query costs
- Calculates bytes processed and estimated costs
- Aggregates by various dimensions (day, dataset, user)
- Returns structured data for admin dashboard

BigQuery Pricing:
- On-demand: $6.25 per TB processed (first 1TB free per month)
- Costs are estimated based on bytes billed

Usage:
    # Get cost metrics for last 7 days
    python monitoring/bigquery_cost_tracker.py

    # Get costs for specific number of days
    python monitoring/bigquery_cost_tracker.py --days 30

    # Output as JSON
    python monitoring/bigquery_cost_tracker.py --json

Created: 2026-01-23
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()

# BigQuery pricing (on-demand)
COST_PER_TB = 6.25  # USD per TB processed
BYTES_PER_TB = 1024 ** 4  # 1 TB in bytes


class BigQueryCostTracker:
    """
    Track and analyze BigQuery query costs.

    Uses INFORMATION_SCHEMA.JOBS to get query execution details
    including bytes processed, which can be used to estimate costs.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self._bq_client = None

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    def _bytes_to_cost(self, bytes_billed: int) -> float:
        """
        Convert bytes billed to estimated cost in USD.

        Args:
            bytes_billed: Number of bytes billed

        Returns:
            Estimated cost in USD
        """
        if bytes_billed is None or bytes_billed == 0:
            return 0.0
        tb_billed = bytes_billed / BYTES_PER_TB
        return round(tb_billed * COST_PER_TB, 4)

    def _bytes_to_gb(self, bytes_value: int) -> float:
        """Convert bytes to GB."""
        if bytes_value is None:
            return 0.0
        return round(bytes_value / (1024 ** 3), 2)

    def get_daily_costs(self, days: int = 7) -> List[Dict]:
        """
        Get daily aggregated BigQuery costs.

        Args:
            days: Number of days to look back

        Returns:
            List of daily cost summaries
        """
        query = f"""
        SELECT
            DATE(creation_time) as query_date,
            COUNT(*) as query_count,
            SUM(total_bytes_billed) as total_bytes_billed,
            SUM(total_bytes_processed) as total_bytes_processed,
            AVG(total_bytes_billed) as avg_bytes_per_query,
            MAX(total_bytes_billed) as max_bytes_query,
            SUM(total_slot_ms) as total_slot_ms,
            AVG(total_slot_ms) as avg_slot_ms_per_query,
            COUNTIF(error_result IS NOT NULL) as error_count,
            COUNTIF(cache_hit = true) as cache_hits
        FROM `region-us`.INFORMATION_SCHEMA.JOBS
        WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND job_type = 'QUERY'
          AND statement_type != 'SCRIPT'
        GROUP BY query_date
        ORDER BY query_date DESC
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            daily_costs = []

            for row in result:
                bytes_billed = row.total_bytes_billed or 0
                estimated_cost = self._bytes_to_cost(bytes_billed)

                daily_costs.append({
                    'date': row.query_date.isoformat(),
                    'query_count': row.query_count,
                    'total_bytes_billed': bytes_billed,
                    'total_gb_billed': self._bytes_to_gb(bytes_billed),
                    'total_bytes_processed': row.total_bytes_processed or 0,
                    'total_gb_processed': self._bytes_to_gb(row.total_bytes_processed),
                    'avg_bytes_per_query': int(row.avg_bytes_per_query or 0),
                    'avg_mb_per_query': round((row.avg_bytes_per_query or 0) / (1024 ** 2), 2),
                    'max_bytes_query': row.max_bytes_query or 0,
                    'max_gb_query': self._bytes_to_gb(row.max_bytes_query),
                    'estimated_cost_usd': estimated_cost,
                    'total_slot_ms': row.total_slot_ms or 0,
                    'avg_slot_ms_per_query': round(row.avg_slot_ms_per_query or 0, 1),
                    'error_count': row.error_count,
                    'cache_hits': row.cache_hits,
                    'cache_hit_rate_pct': round(100.0 * row.cache_hits / row.query_count, 1) if row.query_count > 0 else 0
                })

            return daily_costs

        except Exception as e:
            logger.error(f"Error getting daily costs: {e}")
            return []

    def get_costs_by_dataset(self, days: int = 7) -> List[Dict]:
        """
        Get costs aggregated by destination dataset.

        Args:
            days: Number of days to look back

        Returns:
            List of per-dataset cost summaries
        """
        query = f"""
        SELECT
            COALESCE(
                REGEXP_EXTRACT(destination_table.dataset_id, r'^(.+)$'),
                'unknown'
            ) as dataset_id,
            COUNT(*) as query_count,
            SUM(total_bytes_billed) as total_bytes_billed,
            SUM(total_bytes_processed) as total_bytes_processed,
            AVG(total_bytes_billed) as avg_bytes_per_query,
            SUM(total_slot_ms) as total_slot_ms,
            COUNTIF(cache_hit = true) as cache_hits
        FROM `region-us`.INFORMATION_SCHEMA.JOBS
        WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND job_type = 'QUERY'
          AND statement_type != 'SCRIPT'
        GROUP BY dataset_id
        ORDER BY total_bytes_billed DESC
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            dataset_costs = []

            for row in result:
                bytes_billed = row.total_bytes_billed or 0
                estimated_cost = self._bytes_to_cost(bytes_billed)

                dataset_costs.append({
                    'dataset_id': row.dataset_id,
                    'query_count': row.query_count,
                    'total_bytes_billed': bytes_billed,
                    'total_gb_billed': self._bytes_to_gb(bytes_billed),
                    'total_bytes_processed': row.total_bytes_processed or 0,
                    'total_gb_processed': self._bytes_to_gb(row.total_bytes_processed),
                    'avg_bytes_per_query': int(row.avg_bytes_per_query or 0),
                    'avg_mb_per_query': round((row.avg_bytes_per_query or 0) / (1024 ** 2), 2),
                    'estimated_cost_usd': estimated_cost,
                    'total_slot_ms': row.total_slot_ms or 0,
                    'cache_hits': row.cache_hits,
                    'cache_hit_rate_pct': round(100.0 * row.cache_hits / row.query_count, 1) if row.query_count > 0 else 0
                })

            return dataset_costs

        except Exception as e:
            logger.error(f"Error getting costs by dataset: {e}")
            return []

    def get_costs_by_user(self, days: int = 7) -> List[Dict]:
        """
        Get costs aggregated by user/service account.

        Args:
            days: Number of days to look back

        Returns:
            List of per-user cost summaries
        """
        query = f"""
        SELECT
            user_email,
            COUNT(*) as query_count,
            SUM(total_bytes_billed) as total_bytes_billed,
            SUM(total_bytes_processed) as total_bytes_processed,
            AVG(total_bytes_billed) as avg_bytes_per_query,
            MAX(total_bytes_billed) as max_bytes_query,
            SUM(total_slot_ms) as total_slot_ms,
            COUNTIF(error_result IS NOT NULL) as error_count,
            COUNTIF(cache_hit = true) as cache_hits
        FROM `region-us`.INFORMATION_SCHEMA.JOBS
        WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND job_type = 'QUERY'
          AND statement_type != 'SCRIPT'
        GROUP BY user_email
        ORDER BY total_bytes_billed DESC
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            user_costs = []

            for row in result:
                bytes_billed = row.total_bytes_billed or 0
                estimated_cost = self._bytes_to_cost(bytes_billed)

                # Extract service account name or show email
                user_display = row.user_email
                if '@' in user_display and '.iam.gserviceaccount.com' in user_display:
                    # Extract service account name
                    user_display = user_display.split('@')[0]

                user_costs.append({
                    'user_email': row.user_email,
                    'user_display': user_display,
                    'query_count': row.query_count,
                    'total_bytes_billed': bytes_billed,
                    'total_gb_billed': self._bytes_to_gb(bytes_billed),
                    'total_bytes_processed': row.total_bytes_processed or 0,
                    'total_gb_processed': self._bytes_to_gb(row.total_bytes_processed),
                    'avg_bytes_per_query': int(row.avg_bytes_per_query or 0),
                    'avg_mb_per_query': round((row.avg_bytes_per_query or 0) / (1024 ** 2), 2),
                    'max_bytes_query': row.max_bytes_query or 0,
                    'max_gb_query': self._bytes_to_gb(row.max_bytes_query),
                    'estimated_cost_usd': estimated_cost,
                    'total_slot_ms': row.total_slot_ms or 0,
                    'error_count': row.error_count,
                    'cache_hits': row.cache_hits,
                    'cache_hit_rate_pct': round(100.0 * row.cache_hits / row.query_count, 1) if row.query_count > 0 else 0
                })

            return user_costs

        except Exception as e:
            logger.error(f"Error getting costs by user: {e}")
            return []

    def get_expensive_queries(self, days: int = 7, limit: int = 20) -> List[Dict]:
        """
        Get the most expensive queries by bytes processed.

        Args:
            days: Number of days to look back
            limit: Maximum number of queries to return

        Returns:
            List of expensive query details
        """
        query = f"""
        SELECT
            job_id,
            user_email,
            creation_time,
            total_bytes_billed,
            total_bytes_processed,
            total_slot_ms,
            cache_hit,
            statement_type,
            SUBSTR(query, 1, 500) as query_preview,
            destination_table.dataset_id as destination_dataset,
            destination_table.table_id as destination_table,
            TIMESTAMP_DIFF(end_time, start_time, SECOND) as duration_seconds
        FROM `region-us`.INFORMATION_SCHEMA.JOBS
        WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND job_type = 'QUERY'
          AND statement_type != 'SCRIPT'
          AND total_bytes_billed > 0
        ORDER BY total_bytes_billed DESC
        LIMIT {limit}
        """

        try:
            result = self.bq_client.query(query).result(timeout=120)
            expensive_queries = []

            for row in result:
                bytes_billed = row.total_bytes_billed or 0
                estimated_cost = self._bytes_to_cost(bytes_billed)

                expensive_queries.append({
                    'job_id': row.job_id,
                    'user_email': row.user_email,
                    'creation_time': row.creation_time.isoformat() if row.creation_time else None,
                    'total_bytes_billed': bytes_billed,
                    'total_gb_billed': self._bytes_to_gb(bytes_billed),
                    'total_bytes_processed': row.total_bytes_processed or 0,
                    'total_gb_processed': self._bytes_to_gb(row.total_bytes_processed),
                    'estimated_cost_usd': estimated_cost,
                    'total_slot_ms': row.total_slot_ms or 0,
                    'duration_seconds': row.duration_seconds or 0,
                    'cache_hit': row.cache_hit,
                    'statement_type': row.statement_type,
                    'query_preview': row.query_preview,
                    'destination_dataset': row.destination_dataset,
                    'destination_table': row.destination_table
                })

            return expensive_queries

        except Exception as e:
            logger.error(f"Error getting expensive queries: {e}")
            return []

    def get_cost_summary(self, days: int = 7) -> Dict:
        """
        Get overall cost summary with totals and statistics.

        Args:
            days: Number of days to look back

        Returns:
            Summary dict with aggregated cost metrics
        """
        query = f"""
        SELECT
            COUNT(*) as total_queries,
            SUM(total_bytes_billed) as total_bytes_billed,
            SUM(total_bytes_processed) as total_bytes_processed,
            AVG(total_bytes_billed) as avg_bytes_per_query,
            MAX(total_bytes_billed) as max_bytes_query,
            SUM(total_slot_ms) as total_slot_ms,
            AVG(total_slot_ms) as avg_slot_ms_per_query,
            COUNTIF(error_result IS NOT NULL) as error_count,
            COUNTIF(cache_hit = true) as cache_hits,
            COUNT(DISTINCT user_email) as unique_users,
            COUNT(DISTINCT DATE(creation_time)) as active_days,
            MIN(creation_time) as earliest_query,
            MAX(creation_time) as latest_query
        FROM `region-us`.INFORMATION_SCHEMA.JOBS
        WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND job_type = 'QUERY'
          AND statement_type != 'SCRIPT'
        """

        try:
            result = list(self.bq_client.query(query).result(timeout=120))

            if not result:
                return {'error': 'No data found'}

            row = result[0]
            total_bytes_billed = row.total_bytes_billed or 0
            total_queries = row.total_queries or 0

            return {
                'period_days': days,
                'total_queries': total_queries,
                'total_bytes_billed': total_bytes_billed,
                'total_gb_billed': self._bytes_to_gb(total_bytes_billed),
                'total_tb_billed': round(total_bytes_billed / BYTES_PER_TB, 4),
                'estimated_cost_usd': self._bytes_to_cost(total_bytes_billed),
                'avg_bytes_per_query': int(row.avg_bytes_per_query or 0),
                'avg_mb_per_query': round((row.avg_bytes_per_query or 0) / (1024 ** 2), 2),
                'avg_cost_per_query_usd': round(self._bytes_to_cost(total_bytes_billed) / total_queries, 6) if total_queries > 0 else 0,
                'max_bytes_query': row.max_bytes_query or 0,
                'max_gb_query': self._bytes_to_gb(row.max_bytes_query),
                'max_query_cost_usd': self._bytes_to_cost(row.max_bytes_query),
                'total_slot_ms': row.total_slot_ms or 0,
                'total_slot_hours': round((row.total_slot_ms or 0) / (1000 * 60 * 60), 2),
                'avg_slot_ms_per_query': round(row.avg_slot_ms_per_query or 0, 1),
                'error_count': row.error_count,
                'error_rate_pct': round(100.0 * row.error_count / total_queries, 2) if total_queries > 0 else 0,
                'cache_hits': row.cache_hits,
                'cache_hit_rate_pct': round(100.0 * row.cache_hits / total_queries, 1) if total_queries > 0 else 0,
                'unique_users': row.unique_users,
                'active_days': row.active_days,
                'earliest_query': row.earliest_query.isoformat() if row.earliest_query else None,
                'latest_query': row.latest_query.isoformat() if row.latest_query else None,
                'tracked_at': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error getting cost summary: {e}")
            return {'error': str(e)}

    def get_all_cost_metrics(self, days: int = 7) -> Dict:
        """
        Get all cost metrics for dashboard display.

        Args:
            days: Number of days to look back

        Returns:
            Dict with all cost metrics organized by type
        """
        return {
            'summary': self.get_cost_summary(days),
            'daily_costs': self.get_daily_costs(days),
            'costs_by_dataset': self.get_costs_by_dataset(days),
            'costs_by_user': self.get_costs_by_user(days),
            'expensive_queries': self.get_expensive_queries(days, limit=10),
            'period_days': days,
            'generated_at': datetime.now(timezone.utc).isoformat()
        }

    def print_report(self, days: int = 7) -> None:
        """Print human-readable cost report."""
        summary = self.get_cost_summary(days)

        print("\n" + "=" * 70)
        print("BIGQUERY COST TRACKING REPORT")
        print("=" * 70)
        print(f"Period: Last {days} days")
        print(f"Project: {self.project_id}")
        print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()

        if 'error' in summary:
            print(f"Error: {summary['error']}")
            return

        # Summary stats
        print("SUMMARY:")
        print(f"  Total Queries: {summary['total_queries']:,}")
        print(f"  Total GB Billed: {summary['total_gb_billed']:,.2f} GB")
        print(f"  Estimated Cost: ${summary['estimated_cost_usd']:,.4f}")
        print(f"  Avg MB/Query: {summary['avg_mb_per_query']:,.2f} MB")
        print(f"  Cache Hit Rate: {summary['cache_hit_rate_pct']}%")
        print(f"  Error Rate: {summary['error_rate_pct']}%")
        print(f"  Unique Users: {summary['unique_users']}")
        print()

        # Daily breakdown
        daily_costs = self.get_daily_costs(days)
        if daily_costs:
            print("DAILY BREAKDOWN:")
            print(f"  {'Date':<12} {'Queries':>10} {'GB Billed':>12} {'Est. Cost':>12}")
            print("  " + "-" * 50)
            for day in daily_costs[:7]:  # Show last 7 days
                print(f"  {day['date']:<12} {day['query_count']:>10,} "
                      f"{day['total_gb_billed']:>12,.2f} ${day['estimated_cost_usd']:>10,.4f}")
        print()

        # Top users
        user_costs = self.get_costs_by_user(days)
        if user_costs:
            print("TOP USERS BY COST:")
            for i, user in enumerate(user_costs[:5], 1):
                print(f"  {i}. {user['user_display'][:40]:<40} "
                      f"${user['estimated_cost_usd']:>8,.4f} ({user['query_count']:,} queries)")
        print()

        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Track BigQuery query costs"
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Number of days to look back (default: 7)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show only summary'
    )
    parser.add_argument(
        '--expensive',
        action='store_true',
        help='Show expensive queries'
    )

    args = parser.parse_args()

    tracker = BigQueryCostTracker()

    if args.json:
        if args.summary:
            data = tracker.get_cost_summary(args.days)
        elif args.expensive:
            data = tracker.get_expensive_queries(args.days, limit=20)
        else:
            data = tracker.get_all_cost_metrics(args.days)
        print(json.dumps(data, indent=2))
    else:
        if args.expensive:
            queries = tracker.get_expensive_queries(args.days, limit=20)
            print("\nMOST EXPENSIVE QUERIES:")
            print("=" * 70)
            for i, q in enumerate(queries, 1):
                print(f"\n{i}. Job ID: {q['job_id']}")
                print(f"   User: {q['user_email']}")
                print(f"   Cost: ${q['estimated_cost_usd']:.4f} ({q['total_gb_billed']:.2f} GB)")
                print(f"   Duration: {q['duration_seconds']}s")
                print(f"   Preview: {q['query_preview'][:100]}...")
        else:
            tracker.print_report(args.days)


if __name__ == '__main__':
    main()
