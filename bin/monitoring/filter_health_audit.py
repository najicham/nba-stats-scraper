#!/usr/bin/env python3
"""Filter Health Audit — check if each negative filter is still adding value.

For each BQ-queryable filter, computes the counterfactual hit rate of
predictions that WOULD have been blocked. If blocked predictions would have
been profitable (HR > 55%), the filter may be incorrectly blocking winners.

Filters that require runtime signal evaluation (signal_count, signal_density,
anti_pattern) are marked SKIP — they can only be tested via dry-run simulation.

Usage:
    PYTHONPATH=. python bin/monitoring/filter_health_audit.py \
        --start 2026-01-01 --end 2026-02-27

    # Quick 14-day check
    PYTHONPATH=. python bin/monitoring/filter_health_audit.py --days 14
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Each filter has:
#   name: display name
#   sql_condition: WHERE clause to identify predictions that WOULD be blocked
#   claimed_hr: original HR from when filter was introduced
#   direction: 'UNDER', 'OVER', or 'BOTH' — what direction this filter targets
#   note: optional note about the filter
#
# All queries run against prediction_accuracy (edge 3+, non-voided).
# The sql_condition should match predictions that the filter BLOCKS.
FILTER_REGISTRY = [
    {
        'name': 'edge_floor',
        'sql_condition': 'ABS(predicted_points - line_value) < 3.0',
        'claimed_hr': None,
        'direction': 'BOTH',
        'note': 'Predictions below edge 3.0 floor (checked in prediction_accuracy at edge < 3)',
        'skip': True,  # prediction_accuracy already has edge >= 0; need raw predictions table
    },
    {
        'name': 'bench_under',
        'sql_condition': "recommendation = 'UNDER' AND line_value < 12",
        'claimed_hr': 35.1,
        'direction': 'UNDER',
    },
    {
        'name': 'star_under',
        'sql_condition': """
            recommendation = 'UNDER'
            AND player_lookup IN (
                SELECT player_lookup FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22' AND minutes_played > 0
                GROUP BY player_lookup
                HAVING AVG(points) >= 25
            )
        """,
        'claimed_hr': 51.3,
        'direction': 'UNDER',
    },
    {
        'name': 'under_edge_7plus',
        'sql_condition': """
            recommendation = 'UNDER'
            AND ABS(predicted_points - line_value) >= 7.0
            AND system_id NOT LIKE 'catboost_v12%'
        """,
        'claimed_hr': 40.7,
        'direction': 'UNDER',
    },
    {
        'name': 'line_jumped_under',
        'sql_condition': """
            recommendation = 'UNDER'
            AND player_lookup IN (
                SELECT DISTINCT a.player_lookup
                FROM `nba-props-platform.nba_predictions.prediction_accuracy` a
                JOIN `nba-props-platform.nba_predictions.prediction_accuracy` b
                  ON a.player_lookup = b.player_lookup
                  AND a.system_id = b.system_id
                  AND b.game_date = (
                    SELECT MAX(c.game_date)
                    FROM `nba-props-platform.nba_predictions.prediction_accuracy` c
                    WHERE c.player_lookup = a.player_lookup
                      AND c.system_id = a.system_id
                      AND c.game_date < a.game_date
                  )
                WHERE a.line_value - b.line_value >= 2.0
            )
        """,
        'claimed_hr': 38.2,
        'direction': 'UNDER',
        'skip': True,
        'note': 'Requires prev line lookup — complex, use dry-run simulation instead',
    },
    {
        'name': 'line_dropped_under',
        'sql_condition': "-- requires prev line delta",
        'claimed_hr': 35.2,
        'direction': 'UNDER',
        'skip': True,
        'note': 'Requires prev line lookup — complex, use dry-run simulation instead',
    },
    {
        'name': 'away_v12_noveg',
        'sql_condition': """
            system_id LIKE 'catboost_v12_noveg%'
            AND game_id LIKE CONCAT('%_', SPLIT(game_id, '_')[OFFSET(1)], '_%')
            AND player_lookup IN (
                SELECT pgs.player_lookup
                FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
                WHERE pgs.game_date = pa.game_date
                  AND pgs.team_abbr = SPLIT(pa.game_id, '_')[OFFSET(1)]
            )
        """,
        'claimed_hr': 43.8,
        'direction': 'BOTH',
        'skip': True,
        'note': 'Home/away check requires game_id parsing — use simplified version below',
    },
    {
        'name': 'away_v9',
        'sql_condition': """
            system_id LIKE 'catboost_v9%'
            AND system_id NOT LIKE 'catboost_v9_low_vegas%'
        """,
        'claimed_hr': 48.1,
        'direction': 'BOTH',
        'note': 'All v9 AWAY picks (simplified — includes home too, actual filter is AWAY only)',
        'skip': True,
    },
    {
        'name': 'quality_floor',
        'sql_condition': 'feature_quality_score < 85',
        'claimed_hr': 24.0,
        'direction': 'BOTH',
        'note': 'feature_quality_score may not be in prediction_accuracy — check schema',
        'skip': True,
    },
    {
        'name': 'familiar_matchup',
        'sql_condition': "-- requires games_vs_opponent join",
        'claimed_hr': None,
        'direction': 'BOTH',
        'skip': True,
        'note': 'Requires season game count join — use dry-run simulation',
    },
    {
        'name': 'neg_pm_streak',
        'sql_condition': "-- requires player_game_summary join for +/- streak",
        'claimed_hr': 13.1,
        'direction': 'UNDER',
        'skip': True,
        'note': 'Requires plus_minus streak computation',
    },
    {
        'name': 'model_direction_affinity',
        'sql_condition': "-- computed at runtime",
        'claimed_hr': 45.0,
        'direction': 'BOTH',
        'skip': True,
        'note': 'Dynamic blocking based on rolling HR — computed at runtime',
    },
    {
        'name': 'signal_count',
        'sql_condition': "-- requires signal evaluation",
        'claimed_hr': None,
        'direction': 'BOTH',
        'skip': True,
        'note': 'Requires runtime signal evaluation',
    },
    {
        'name': 'signal_density',
        'sql_condition': "-- requires signal evaluation",
        'claimed_hr': None,
        'direction': 'BOTH',
        'skip': True,
        'note': 'Requires runtime signal evaluation',
    },
    {
        'name': 'med_usage_under',
        'sql_condition': "-- requires feature store join",
        'claimed_hr': 32.0,
        'direction': 'UNDER',
        'skip': True,
        'note': 'Requires teammate_usage_available from feature store',
    },
    {
        'name': 'starter_v12_under',
        'sql_condition': """
            recommendation = 'UNDER'
            AND system_id LIKE 'catboost_v12%'
            AND player_lookup IN (
                SELECT player_lookup FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22' AND minutes_played > 0
                GROUP BY player_lookup
                HAVING AVG(points) BETWEEN 15 AND 20
            )
        """,
        'claimed_hr': 46.7,
        'direction': 'UNDER',
    },
]

# Filters that can be evaluated purely from prediction_accuracy
BQ_QUERYABLE_FILTERS = [
    {
        'name': 'bench_under',
        'sql_condition': "recommendation = 'UNDER' AND line_value < 12",
        'claimed_hr': 35.1,
    },
    {
        'name': 'star_under',
        'sql_condition': """recommendation = 'UNDER'
            AND player_lookup IN (
                SELECT player_lookup FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22' AND minutes_played > 0
                GROUP BY player_lookup HAVING AVG(points) >= 25
            )""",
        'claimed_hr': 51.3,
    },
    {
        'name': 'under_edge_7plus_non_v12',
        'sql_condition': """recommendation = 'UNDER'
            AND ABS(predicted_points - line_value) >= 7.0
            AND system_id NOT LIKE 'catboost_v12%'""",
        'claimed_hr': 40.7,
    },
    {
        'name': 'starter_v12_under',
        'sql_condition': """recommendation = 'UNDER'
            AND system_id LIKE 'catboost_v12%'
            AND player_lookup IN (
                SELECT player_lookup FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date >= '2025-10-22' AND minutes_played > 0
                GROUP BY player_lookup HAVING AVG(points) BETWEEN 15 AND 20
            )""",
        'claimed_hr': 46.7,
    },
    {
        'name': 'v9_under_5plus',
        'sql_condition': """recommendation = 'UNDER'
            AND ABS(predicted_points - line_value) >= 5.0
            AND system_id LIKE 'catboost_v9%'
            AND system_id NOT LIKE 'catboost_v9_low_vegas%'""",
        'claimed_hr': 30.7,
        'note': 'model_direction_affinity: v9 UNDER 5+ band',
    },
]


def run_filter_audit(bq_client: bigquery.Client, start_date: str,
                     end_date: str) -> List[Dict]:
    """Run BQ queries for each queryable filter."""
    results = []

    for f in BQ_QUERYABLE_FILTERS:
        query = f"""
        SELECT
          COUNT(*) as total,
          COUNTIF(prediction_correct = TRUE) as wins,
          COUNTIF(prediction_correct = FALSE) as losses,
          ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / NULLIF(COUNT(*), 0), 1) as hr
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND ABS(predicted_points - line_value) >= 3.0
          AND prediction_correct IS NOT NULL
          AND is_voided IS NOT TRUE
          AND ({f['sql_condition']})
        """
        try:
            row = next(bq_client.query(query).result(timeout=60))
            actual_hr = float(row.hr) if row.hr is not None else None
            delta = round(actual_hr - f['claimed_hr'], 1) if (actual_hr is not None and f['claimed_hr'] is not None) else None

            # Determine status
            status = 'OK'
            if actual_hr is not None and actual_hr > 55.0:
                status = 'REVIEW'  # Filter may be blocking profitable picks
            elif actual_hr is not None and f.get('claimed_hr') and abs(actual_hr - f['claimed_hr']) > 10:
                status = 'DRIFT'

            results.append({
                'name': f['name'],
                'claimed_hr': f.get('claimed_hr'),
                'actual_hr': actual_hr,
                'delta': delta,
                'n': row.total,
                'wins': row.wins,
                'losses': row.losses,
                'status': status,
                'note': f.get('note', ''),
            })
        except Exception as e:
            results.append({
                'name': f['name'],
                'claimed_hr': f.get('claimed_hr'),
                'actual_hr': None,
                'delta': None,
                'n': 0,
                'status': 'ERROR',
                'note': str(e),
            })

    return results


def run_overlap_analysis(bq_client: bigquery.Client, start_date: str,
                         end_date: str) -> List[Dict]:
    """Check how many predictions match multiple filters simultaneously."""
    # Count how many queryable filters each prediction matches
    case_clauses = []
    for f in BQ_QUERYABLE_FILTERS:
        case_clauses.append(f"CASE WHEN ({f['sql_condition']}) THEN 1 ELSE 0 END")

    sum_expr = ' + '.join(case_clauses)

    query = f"""
    WITH filter_counts AS (
      SELECT
        player_lookup, game_date, system_id,
        prediction_correct,
        ({sum_expr}) as n_filters_matched
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND ABS(predicted_points - line_value) >= 3.0
        AND prediction_correct IS NOT NULL
        AND is_voided IS NOT TRUE
    )
    SELECT
      n_filters_matched,
      COUNT(*) as n_picks,
      ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hr
    FROM filter_counts
    WHERE n_filters_matched > 0
    GROUP BY n_filters_matched
    ORDER BY n_filters_matched
    """
    try:
        rows = list(bq_client.query(query).result(timeout=60))
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Overlap analysis failed: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description='Audit negative filter health')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=None,
                        help='Quick mode: last N days (overrides --start/--end)')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    if args.days:
        end_date = (date.today() - timedelta(days=1)).isoformat()
        start_date = (date.today() - timedelta(days=args.days)).isoformat()
    elif args.start and args.end:
        start_date = args.start
        end_date = args.end
    else:
        parser.error('Provide --start/--end or --days')

    bq_client = bigquery.Client(project=PROJECT_ID)

    print(f"\nFILTER HEALTH AUDIT ({start_date} to {end_date})")
    print("=" * 90)
    print(f"{'Filter':<30s} {'Claimed':>8s} {'Actual':>8s} {'Delta':>8s} {'N':>6s} {'Status':<8s}")
    print("-" * 90)

    results = run_filter_audit(bq_client, start_date, end_date)

    drift_alerts = []
    review_alerts = []

    for r in results:
        claimed = f"{r['claimed_hr']}%" if r['claimed_hr'] is not None else 'N/A'
        actual = f"{r['actual_hr']}%" if r['actual_hr'] is not None else 'N/A'
        delta = f"{r['delta']:+.1f}pp" if r['delta'] is not None else 'N/A'
        n_str = str(r.get('n', 0))
        print(f"  {r['name']:<28s} {claimed:>8s} {actual:>8s} {delta:>8s} {n_str:>6s} {r['status']:<8s}")

        if r['status'] == 'DRIFT':
            drift_alerts.append(r)
        if r['status'] == 'REVIEW':
            review_alerts.append(r)

    # Skipped filters
    skipped = [f for f in FILTER_REGISTRY if f.get('skip')]
    if skipped:
        print(f"\n  SKIPPED ({len(skipped)} filters — require runtime evaluation):")
        for f in skipped:
            note = f.get('note', '')
            print(f"    {f['name']:<28s} claimed={f.get('claimed_hr', 'N/A')}%  {note}")

    # Alerts
    if drift_alerts:
        print(f"\nDRIFT ALERTS (>10pp change from claimed HR):")
        for r in drift_alerts:
            print(f"  {r['name']}: claimed {r['claimed_hr']}% → actual {r['actual_hr']}% ({r['delta']:+.1f}pp, N={r.get('n', 0)})")

    if review_alerts:
        print(f"\nREVIEW ALERTS (blocked picks have HR > 55% = above breakeven):")
        for r in review_alerts:
            print(f"  {r['name']}: {r['actual_hr']}% HR on {r.get('n', 0)} blocked picks — may be blocking profitable picks!")

    if not drift_alerts and not review_alerts:
        print(f"\nNo drift or review alerts.")

    # Overlap analysis
    print(f"\nFILTER OVERLAP:")
    overlap = run_overlap_analysis(bq_client, start_date, end_date)
    if overlap:
        for o in overlap:
            print(f"  {o['n_filters_matched']} filter(s): {o['n_picks']:>6,d} picks (HR: {o['hr']}%)")
    else:
        print("  No overlap data available")


if __name__ == '__main__':
    main()
