#!/usr/bin/env python3
"""
Audit historical cache data for DNP pollution.

Session 123: Discovered 67% DNP pollution that was hidden by flawed validation query.
This script audits historical caches and generates regeneration plans.

Usage:
    # Audit February 2026
    python bin/audit/audit_cache_dnp_pollution.py \\
        --start-date 2026-02-01 \\
        --end-date 2026-02-04

    # Generate regeneration list
    python bin/audit/audit_cache_dnp_pollution.py \\
        --start-date 2026-02-01 \\
        --end-date 2026-02-04 \\
        --output regen_dates.txt \\
        --threshold 5.0
"""

import argparse
from datetime import date, timedelta
from google.cloud import bigquery
import pandas as pd
import sys


def audit_dnp_pollution(
    start_date: str,
    end_date: str,
    threshold_pct: float = 5.0,
    project: str = 'nba-props-platform'
) -> pd.DataFrame:
    """
    Audit cache dates for DNP pollution.

    Args:
        start_date: Start of audit range (YYYY-MM-DD)
        end_date: End of audit range (YYYY-MM-DD)
        threshold_pct: Pollution percentage above which to flag for action
        project: GCP project ID

    Returns:
        DataFrame with audit results
    """
    client = bigquery.Client(project=project)

    query = f"""
    -- DNP Pollution Audit (Session 123 Corrected Query)
    -- Data Model: cache_date is ANALYSIS date, cache contains games BEFORE that date

    WITH pollution_by_date AS (
      SELECT
        pdc.cache_date,
        COUNT(DISTINCT pdc.player_lookup) as total_cached,
        COUNT(DISTINCT CASE
          WHEN pgs.is_dnp = TRUE
          THEN pdc.player_lookup
        END) as dnp_polluted,
        COUNT(pgs.player_lookup) as join_count  -- Should be > 0 to verify join works
      FROM `{project}.nba_precompute.player_daily_cache` pdc
      LEFT JOIN `{project}.nba_analytics.player_game_summary` pgs
        ON pdc.player_lookup = pgs.player_lookup
        AND pgs.game_date >= '{start_date}'  -- Partition filter
        AND pgs.game_date < pdc.cache_date   -- Games BEFORE cache date
      WHERE pdc.cache_date >= '{start_date}'
        AND pdc.cache_date <= '{end_date}'
      GROUP BY pdc.cache_date
    )
    SELECT
      cache_date,
      total_cached,
      dnp_polluted,
      join_count,
      ROUND(100.0 * dnp_polluted / NULLIF(total_cached, 0), 1) as dnp_pct
    FROM pollution_by_date
    ORDER BY cache_date
    """

    print(f"Running audit query for {start_date} to {end_date}...")
    results = client.query(query).to_dataframe()

    if results.empty:
        print(f"⚠️  No cache data found for date range {start_date} to {end_date}")
        return results

    # Verify join is working (Session 123 check)
    if (results['join_count'] == 0).any():
        print("🚨 WARNING: Some dates have join_count = 0, indicating JOIN may not be working!")
        print("    This is the Session 123 anti-pattern. Review the query.")

    # Add severity and action columns
    results['severity'] = results['dnp_pct'].apply(
        lambda x: 'CRITICAL' if x >= 50 else
                  'HIGH' if x >= 20 else
                  'MEDIUM' if x >= 5 else
                  'LOW' if x > 0 else 'CLEAN'
    )
    results['action'] = results['dnp_pct'].apply(
        lambda x: 'REGENERATE' if x >= threshold_pct else 'OK'
    )

    return results


def generate_regeneration_plan(audit_results: pd.DataFrame) -> list:
    """Generate list of dates needing regeneration."""
    needs_regen = audit_results[audit_results['action'] == 'REGENERATE']
    return needs_regen['cache_date'].tolist()


def print_summary(results: pd.DataFrame):
    """Print audit summary."""
    total_dates = len(results)
    critical_dates = len(results[results['severity'] == 'CRITICAL'])
    high_dates = len(results[results['severity'] == 'HIGH'])
    medium_dates = len(results[results['severity'] == 'MEDIUM'])
    low_dates = len(results[results['severity'] == 'LOW'])
    clean_dates = len(results[results['severity'] == 'CLEAN'])

    print("\n" + "="*60)
    print("=== Audit Summary ===")
    print("="*60)
    print(f"Total dates audited:  {total_dates}")
    print(f"  CRITICAL (>=50%):   {critical_dates}")
    print(f"  HIGH (20-50%):      {high_dates}")
    print(f"  MEDIUM (5-20%):     {medium_dates}")
    print(f"  LOW (>0%, <5%):     {low_dates}")
    print(f"  CLEAN (0%):         {clean_dates}")
    print("="*60)


def print_detailed_results(results: pd.DataFrame):
    """Print detailed results for each date."""
    print("\n=== Detailed Results ===\n")
    for _, row in results.iterrows():
        status_emoji = {
            'CRITICAL': '🔴',
            'HIGH': '🟠',
            'MEDIUM': '🟡',
            'LOW': '🟢',
            'CLEAN': '✅'
        }[row['severity']]

        print(f"{status_emoji} {row['cache_date']}: {row['dnp_pct']}% polluted "
              f"({row['dnp_polluted']}/{row['total_cached']} players) "
              f"[{row['severity']}] {row['action']}")


def main():
    parser = argparse.ArgumentParser(
        description='Audit cache DNP pollution (Session 123)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--start-date', required=True,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--threshold', type=float, default=5.0,
                        help='Pollution threshold %% for regeneration (default: 5.0)')
    parser.add_argument('--output', help='Output file for regeneration date list')
    parser.add_argument('--project', default='nba-props-platform',
                        help='GCP project ID (default: nba-props-platform)')
    parser.add_argument('--detailed', action='store_true',
                        help='Show detailed results for each date')

    args = parser.parse_args()

    print(f"Auditing cache pollution from {args.start_date} to {args.end_date}...")
    print(f"Regeneration threshold: {args.threshold}%%")
    print()

    try:
        results = audit_dnp_pollution(
            args.start_date,
            args.end_date,
            args.threshold,
            args.project
        )
    except Exception as e:
        print(f"❌ Error running audit: {e}")
        return 1

    if results.empty:
        return 1

    # Print summary
    print_summary(results)

    # Print detailed results if requested
    if args.detailed:
        print_detailed_results(results)

    # Show dates needing action
    regen_dates = generate_regeneration_plan(results)
    if regen_dates:
        print(f"\n=== Dates Needing Regeneration ({len(regen_dates)}) ===")
        for d in regen_dates:
            row = results[results['cache_date'] == d].iloc[0]
            print(f"  {d}: {row['dnp_pct']}% polluted "
                  f"({row['dnp_polluted']}/{row['total_cached']} players)")

        if args.output:
            with open(args.output, 'w') as f:
                for d in regen_dates:
                    f.write(f"{d}\n")
            print(f"\n✅ Regeneration list saved to: {args.output}")
            print(f"\nTo regenerate all dates:")
            print(f"  while read date; do")
            print(f"    python bin/regenerate_cache_bypass_bootstrap.py $date")
            print(f"  done < {args.output}")
    else:
        print("\n✅ No dates need regeneration (all below threshold).")

    return 0


if __name__ == '__main__':
    sys.exit(main())
