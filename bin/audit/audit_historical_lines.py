#!/usr/bin/env python3
"""
Historical Lines Audit Script

Audits all prediction lines from the season to verify they came from real sources
(odds_api or bettingpros) and flags any that used estimated/fallback values.

This helps ensure data quality for grading and model training.

Usage:
    python bin/audit/audit_historical_lines.py [--start-date 2025-10-22] [--end-date 2026-01-29]
"""

import argparse
from datetime import date, timedelta
from google.cloud import bigquery
from typing import Dict, List, Tuple
import json


def run_audit(start_date: str, end_date: str, verbose: bool = False) -> Dict:
    """
    Run comprehensive audit of historical lines

    Returns:
        Dictionary with audit results
    """
    client = bigquery.Client()
    results = {}

    # 1. Overall line source breakdown
    print("=" * 60)
    print("1. OVERALL LINE SOURCE BREAKDOWN")
    print("=" * 60)

    query = f"""
    SELECT
        line_source,
        line_source_api,
        has_prop_line,
        COUNT(*) as prediction_count,
        COUNT(DISTINCT player_lookup) as unique_players,
        COUNT(DISTINCT game_date) as game_days
    FROM nba_predictions.player_prop_predictions
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND system_id = 'catboost_v8'
    GROUP BY line_source, line_source_api, has_prop_line
    ORDER BY prediction_count DESC
    """
    result = list(client.query(query))
    results['line_source_breakdown'] = [dict(row) for row in result]

    for row in result:
        print(f"  {row.line_source or 'NULL':<20} | {row.line_source_api or 'NULL':<15} | "
              f"has_prop={row.has_prop_line} | {row.prediction_count:,} predictions")

    # 2. Sentinel value detection (line = 20 is known fake)
    print("\n" + "=" * 60)
    print("2. SENTINEL VALUE DETECTION (line=20 is legacy fake value)")
    print("=" * 60)

    query = f"""
    SELECT
        game_date,
        COUNT(*) as total,
        SUM(CASE WHEN current_points_line = 20 THEN 1 ELSE 0 END) as sentinel_20,
        SUM(CASE WHEN current_points_line IS NULL THEN 1 ELSE 0 END) as null_lines,
        SUM(CASE WHEN current_points_line NOT IN (20) AND current_points_line IS NOT NULL THEN 1 ELSE 0 END) as valid_lines
    FROM nba_predictions.player_prop_predictions
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND system_id = 'catboost_v8'
    GROUP BY game_date
    HAVING sentinel_20 > 0 OR null_lines > 0
    ORDER BY game_date
    """
    result = list(client.query(query))
    results['sentinel_issues'] = [dict(row) for row in result]

    if result:
        print(f"  Found {len(result)} days with potential issues:")
        for row in result[:10]:
            print(f"    {row.game_date}: sentinel_20={row.sentinel_20}, null={row.null_lines}")
        if len(result) > 10:
            print(f"    ... and {len(result) - 10} more days")
    else:
        print("  No sentinel value issues found!")

    # 3. Estimated lines breakdown
    print("\n" + "=" * 60)
    print("3. ESTIMATED LINES BREAKDOWN (line_source_api='ESTIMATED')")
    print("=" * 60)

    query = f"""
    SELECT
        estimation_method,
        COUNT(*) as count,
        ROUND(AVG(estimated_line_value), 1) as avg_estimated,
        ROUND(AVG(current_points_line), 1) as avg_current_line
    FROM nba_predictions.player_prop_predictions
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND system_id = 'catboost_v8'
      AND (line_source_api = 'ESTIMATED' OR line_source = 'ESTIMATED_AVG')
    GROUP BY estimation_method
    ORDER BY count DESC
    """
    result = list(client.query(query))
    results['estimated_breakdown'] = [dict(row) for row in result]

    if result:
        for row in result:
            print(f"  {row.estimation_method or 'NULL':<25} | {row.count:,} predictions")
    else:
        print("  No estimated lines found!")

    # 4. Cross-reference with raw data
    print("\n" + "=" * 60)
    print("4. CROSS-REFERENCE: Lines that claim ACTUAL but have no raw data")
    print("=" * 60)

    query = f"""
    WITH predictions_actual AS (
        SELECT
            p.game_date,
            p.player_lookup,
            p.current_points_line,
            p.line_source,
            p.line_source_api
        FROM nba_predictions.player_prop_predictions p
        WHERE p.game_date BETWEEN '{start_date}' AND '{end_date}'
          AND p.system_id = 'catboost_v8'
          AND p.has_prop_line = TRUE
          AND p.line_source = 'ACTUAL_PROP'
    ),
    odds_api_lines AS (
        SELECT DISTINCT game_date, player_lookup
        FROM nba_raw.odds_api_player_points_props
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    ),
    bettingpros_lines AS (
        SELECT DISTINCT game_date, player_lookup
        FROM nba_raw.bettingpros_player_points_props
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
    )
    SELECT
        pa.game_date,
        COUNT(*) as predictions_with_actual,
        SUM(CASE WHEN oa.player_lookup IS NULL AND bp.player_lookup IS NULL THEN 1 ELSE 0 END) as no_raw_data,
        SUM(CASE WHEN oa.player_lookup IS NOT NULL THEN 1 ELSE 0 END) as in_odds_api,
        SUM(CASE WHEN bp.player_lookup IS NOT NULL THEN 1 ELSE 0 END) as in_bettingpros
    FROM predictions_actual pa
    LEFT JOIN odds_api_lines oa ON pa.game_date = oa.game_date AND pa.player_lookup = oa.player_lookup
    LEFT JOIN bettingpros_lines bp ON pa.game_date = bp.game_date AND pa.player_lookup = bp.player_lookup
    GROUP BY pa.game_date
    HAVING no_raw_data > 0
    ORDER BY pa.game_date
    """
    result = list(client.query(query))
    results['missing_raw_data'] = [dict(row) for row in result]

    if result:
        print(f"  Found {len(result)} days where ACTUAL_PROP lines have no raw data:")
        for row in result[:10]:
            print(f"    {row.game_date}: {row.no_raw_data} predictions without raw source "
                  f"(odds_api={row.in_odds_api}, bettingpros={row.in_bettingpros})")
        if len(result) > 10:
            print(f"    ... and {len(result) - 10} more days")
    else:
        print("  All ACTUAL_PROP lines have corresponding raw data!")

    # 5. Line source API coverage by date
    print("\n" + "=" * 60)
    print("5. LINE SOURCE API COVERAGE BY MONTH")
    print("=" * 60)

    query = f"""
    WITH monthly_totals AS (
        SELECT
            FORMAT_DATE('%Y-%m', game_date) as month,
            COUNT(*) as total
        FROM nba_predictions.player_prop_predictions
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND system_id = 'catboost_v8'
        GROUP BY month
    )
    SELECT
        FORMAT_DATE('%Y-%m', p.game_date) as month,
        p.line_source_api,
        COUNT(*) as count,
        ROUND(100.0 * COUNT(*) / t.total, 1) as pct
    FROM nba_predictions.player_prop_predictions p
    JOIN monthly_totals t ON FORMAT_DATE('%Y-%m', p.game_date) = t.month
    WHERE p.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND p.system_id = 'catboost_v8'
    GROUP BY month, p.line_source_api, t.total
    ORDER BY month, count DESC
    """
    result = list(client.query(query))
    results['monthly_coverage'] = [dict(row) for row in result]

    current_month = None
    for row in result:
        if row.month != current_month:
            current_month = row.month
            print(f"\n  {current_month}:")
        print(f"    {row.line_source_api or 'NULL':<15} | {row.count:>6,} ({row.pct:>5.1f}%)")

    # 6. Suspicious patterns (same line for many players)
    print("\n" + "=" * 60)
    print("6. SUSPICIOUS PATTERNS (same line value repeated excessively)")
    print("=" * 60)

    query = f"""
    SELECT
        current_points_line,
        COUNT(*) as count,
        COUNT(DISTINCT player_lookup) as unique_players,
        COUNT(DISTINCT game_date) as game_days,
        MIN(game_date) as first_seen,
        MAX(game_date) as last_seen
    FROM nba_predictions.player_prop_predictions
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND system_id = 'catboost_v8'
      AND current_points_line IS NOT NULL
    GROUP BY current_points_line
    HAVING COUNT(*) > 100
    ORDER BY count DESC
    LIMIT 20
    """
    result = list(client.query(query))
    results['suspicious_patterns'] = [dict(row) for row in result]

    for row in result:
        suspicion = ""
        if row.current_points_line == 20:
            suspicion = " <-- SENTINEL VALUE"
        elif row.current_points_line == 15.5:
            suspicion = " <-- POSSIBLE DEFAULT"
        print(f"  Line {row.current_points_line:>5.1f}: {row.count:>5,} predictions, "
              f"{row.unique_players} players{suspicion}")

    # 7. Summary
    print("\n" + "=" * 60)
    print("7. AUDIT SUMMARY")
    print("=" * 60)

    query = f"""
    SELECT
        COUNT(*) as total_predictions,
        SUM(CASE WHEN has_prop_line = TRUE THEN 1 ELSE 0 END) as with_real_line,
        SUM(CASE WHEN has_prop_line = FALSE OR has_prop_line IS NULL THEN 1 ELSE 0 END) as without_real_line,
        SUM(CASE WHEN line_source_api = 'ODDS_API' THEN 1 ELSE 0 END) as from_odds_api,
        SUM(CASE WHEN line_source_api = 'BETTINGPROS' THEN 1 ELSE 0 END) as from_bettingpros,
        SUM(CASE WHEN line_source_api = 'ESTIMATED' THEN 1 ELSE 0 END) as estimated,
        SUM(CASE WHEN current_points_line = 20 THEN 1 ELSE 0 END) as sentinel_value,
        SUM(CASE WHEN current_points_line IS NULL THEN 1 ELSE 0 END) as null_lines
    FROM nba_predictions.player_prop_predictions
    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND system_id = 'catboost_v8'
    """
    result = list(client.query(query))[0]
    results['summary'] = dict(result)

    total = result.total_predictions
    print(f"""
  Date range: {start_date} to {end_date}
  Total predictions: {total:,}

  Line Sources:
    - ODDS_API:     {result.from_odds_api:>8,} ({100*result.from_odds_api/total:.1f}%)
    - BETTINGPROS:  {result.from_bettingpros:>8,} ({100*result.from_bettingpros/total:.1f}%)
    - ESTIMATED:    {result.estimated:>8,} ({100*result.estimated/total:.1f}%)
    - NULL:         {total - result.from_odds_api - result.from_bettingpros - result.estimated:>8,}

  Data Quality:
    - With real prop line:    {result.with_real_line:>8,} ({100*result.with_real_line/total:.1f}%)
    - Without real prop line: {result.without_real_line:>8,} ({100*result.without_real_line/total:.1f}%)
    - Sentinel value (20):    {result.sentinel_value:>8,}
    - NULL current_line:      {result.null_lines:>8,}
""")

    return results


def main():
    parser = argparse.ArgumentParser(description='Audit historical lines')
    parser.add_argument('--start-date', default='2025-10-22',
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', default=date.today().isoformat(),
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', '-o', help='Output JSON file')
    parser.add_argument('--verbose', '-v', action='store_true')

    args = parser.parse_args()

    print(f"\nAuditing historical lines from {args.start_date} to {args.end_date}\n")

    results = run_audit(args.start_date, args.end_date, args.verbose)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
