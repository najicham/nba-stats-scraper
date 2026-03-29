#!/usr/bin/env python3
"""
Manually reactivate a demoted filter in filter_overrides.

Usage:
    python bin/monitoring/reset_demoted_filter.py --filter-name friday_over_block
    python bin/monitoring/reset_demoted_filter.py --filter-name friday_over_block --dry-run

This sets active = FALSE for the specified filter in filter_overrides,
allowing it to block picks again immediately. Use when a filter was
auto-demoted but the market window that caused it has passed.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


def get_filter_status(bq: bigquery.Client, filter_name: str) -> dict:
    """Get current status of a filter in filter_overrides."""
    query = f"""
    SELECT filter_name, active, cf_hr_7d, n_7d, triggered_at, triggered_by,
           demote_start_date, re_eval_date, reason
    FROM `{PROJECT_ID}.nba_predictions.filter_overrides`
    WHERE filter_name = @filter_name
    ORDER BY triggered_at DESC
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('filter_name', 'STRING', filter_name)]
    )
    rows = list(bq.query(query, job_config=job_config).result(timeout=30))
    return dict(rows[0]) if rows else {}


def reset_filter(bq: bigquery.Client, filter_name: str, dry_run: bool = False) -> bool:
    """Set active = FALSE for the specified filter. Returns True if updated."""
    status = get_filter_status(bq, filter_name)

    if not status:
        print(f"ERROR: Filter '{filter_name}' not found in filter_overrides")
        return False

    if not status.get('active'):
        print(f"Filter '{filter_name}' is already inactive (active=FALSE) — nothing to do")
        return False

    print(f"Filter: {filter_name}")
    print(f"  active: {status.get('active')}")
    print(f"  cf_hr_7d: {status.get('cf_hr_7d')}%")
    print(f"  n_7d: {status.get('n_7d')}")
    print(f"  triggered_by: {status.get('triggered_by')}")
    print(f"  triggered_at: {status.get('triggered_at')}")
    print(f"  demote_start_date: {status.get('demote_start_date')}")
    print(f"  re_eval_date: {status.get('re_eval_date')}")
    print(f"  reason: {status.get('reason')}")

    if dry_run:
        print(f"\n[DRY RUN] Would reactivate filter '{filter_name}' (set active = FALSE)")
        return True

    update_query = f"""
    UPDATE `{PROJECT_ID}.nba_predictions.filter_overrides`
    SET active = FALSE
    WHERE filter_name = @filter_name AND active = TRUE
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter('filter_name', 'STRING', filter_name)]
    )
    bq.query(update_query, job_config=job_config).result(timeout=30)
    print(f"\nReactivated filter '{filter_name}' — it will now block picks again immediately")
    return True


def main():
    parser = argparse.ArgumentParser(description='Reset a demoted filter in filter_overrides')
    parser.add_argument('--filter-name', required=True, help='Name of the filter to reactivate')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()

    bq = bigquery.Client(project=PROJECT_ID)
    success = reset_filter(bq, args.filter_name, dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
