#!/usr/bin/env python3
"""
MLB Daily Performance Tracking

Queries MLB best bets picks and grading data to show daily performance.
Outputs to stdout for easy piping to Slack or other destinations.

Usage:
    PYTHONPATH=. python bin/monitoring/mlb_daily_performance.py
    PYTHONPATH=. python bin/monitoring/mlb_daily_performance.py --days 14
    PYTHONPATH=. python bin/monitoring/mlb_daily_performance.py --since 2026-03-28

Created: 2026-04-05 (MLB operational maturity)
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

# Add repo root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")


def get_bq_client() -> bigquery.Client:
    """Get BigQuery client."""
    return bigquery.Client(project=PROJECT_ID)


def query_daily_picks(bq_client: bigquery.Client, since_date: date) -> List[dict]:
    """Query daily pick counts from signal_best_bets_picks."""
    query = """
    SELECT
      game_date,
      COUNT(*) AS total_picks,
      COUNTIF(recommendation = 'OVER') AS over_picks,
      COUNTIF(recommendation = 'UNDER') AS under_picks,
      ROUND(AVG(edge), 1) AS avg_edge,
      ROUND(MIN(edge), 1) AS min_edge,
      ROUND(MAX(edge), 1) AS max_edge,
      COUNT(DISTINCT system_id) AS models_used,
      COUNT(DISTINCT pitcher_lookup) AS distinct_pitchers
    FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
    WHERE game_date >= @since_date
    GROUP BY game_date
    ORDER BY game_date DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('since_date', 'DATE', since_date),
        ]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"signal_best_bets_picks query failed: {e}")
        return []


def query_graded_performance(bq_client: bigquery.Client, since_date: date) -> List[dict]:
    """Query daily graded performance from prediction_accuracy."""
    query = """
    SELECT
      game_date,
      COUNT(*) AS graded,
      COUNTIF(prediction_correct = TRUE) AS wins,
      COUNTIF(prediction_correct = FALSE) AS losses,
      ROUND(100.0 * COUNTIF(prediction_correct = TRUE)
            / NULLIF(COUNT(*), 0), 1) AS hit_rate_pct,
      ROUND(AVG(ABS(predicted_strikeouts - line_value)), 1) AS avg_edge,
      COUNTIF(is_voided = TRUE) AS voided,
      COUNTIF(recommendation = 'OVER' AND prediction_correct = TRUE) AS over_wins,
      COUNTIF(recommendation = 'OVER' AND prediction_correct = FALSE) AS over_losses,
      COUNTIF(recommendation = 'UNDER' AND prediction_correct = TRUE) AS under_wins,
      COUNTIF(recommendation = 'UNDER' AND prediction_correct = FALSE) AS under_losses
    FROM `nba-props-platform.mlb_predictions.prediction_accuracy`
    WHERE game_date >= @since_date
      AND has_prop_line = TRUE
      AND recommendation IN ('OVER', 'UNDER')
      AND prediction_correct IS NOT NULL
    GROUP BY game_date
    ORDER BY game_date DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('since_date', 'DATE', since_date),
        ]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"prediction_accuracy query failed: {e}")
        return []


def query_bb_graded_performance(bq_client: bigquery.Client, since_date: date) -> List[dict]:
    """Query best bets graded performance (picks that came through the BB pipeline).

    Uses signal_best_bets_picks table directly since it has prediction_correct.
    """
    query = """
    SELECT
      game_date,
      COUNT(*) AS bb_graded,
      COUNTIF(prediction_correct = TRUE) AS bb_wins,
      COUNTIF(prediction_correct = FALSE) AS bb_losses,
      ROUND(100.0 * COUNTIF(prediction_correct = TRUE)
            / NULLIF(COUNT(*), 0), 1) AS bb_hit_rate_pct,
      ROUND(AVG(edge), 1) AS bb_avg_edge,
      COUNTIF(recommendation = 'OVER') AS bb_over,
      COUNTIF(recommendation = 'UNDER') AS bb_under
    FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
    WHERE game_date >= @since_date
      AND prediction_correct IS NOT NULL
    GROUP BY game_date
    ORDER BY game_date DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('since_date', 'DATE', since_date),
        ]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"BB graded query failed: {e}")
        return []


def query_edge_distribution(bq_client: bigquery.Client, since_date: date) -> List[dict]:
    """Query edge bucket distribution for best bets picks."""
    query = """
    SELECT
      CASE
        WHEN ABS(edge) < 0.5 THEN '<0.5'
        WHEN ABS(edge) < 1.0 THEN '0.5-1.0'
        WHEN ABS(edge) < 1.5 THEN '1.0-1.5'
        WHEN ABS(edge) < 2.0 THEN '1.5-2.0'
        WHEN ABS(edge) < 3.0 THEN '2.0-3.0'
        ELSE '3.0+'
      END AS edge_bucket,
      COUNT(*) AS picks,
      COUNTIF(prediction_correct = TRUE) AS wins,
      COUNTIF(prediction_correct = FALSE) AS losses,
      ROUND(100.0 * COUNTIF(prediction_correct = TRUE)
            / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) AS hit_rate_pct,
      COUNTIF(prediction_correct IS NULL) AS ungraded
    FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
    WHERE game_date >= @since_date
    GROUP BY edge_bucket
    ORDER BY
      CASE edge_bucket
        WHEN '<0.5' THEN 1
        WHEN '0.5-1.0' THEN 2
        WHEN '1.0-1.5' THEN 3
        WHEN '1.5-2.0' THEN 4
        WHEN '2.0-3.0' THEN 5
        WHEN '3.0+' THEN 6
      END
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('since_date', 'DATE', since_date),
        ]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"Edge distribution query failed: {e}")
        return []


def query_cumulative_totals(bq_client: bigquery.Client, since_date: date) -> dict:
    """Query cumulative totals across all dates."""
    query = """
    SELECT
      COUNT(*) AS total_picks,
      COUNTIF(prediction_correct = TRUE) AS total_wins,
      COUNTIF(prediction_correct = FALSE) AS total_losses,
      COUNTIF(prediction_correct IS NULL) AS total_ungraded,
      ROUND(100.0 * COUNTIF(prediction_correct = TRUE)
            / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) AS cumulative_hr_pct,
      ROUND(AVG(edge), 2) AS avg_edge,
      MIN(game_date) AS first_pick_date,
      MAX(game_date) AS last_pick_date,
      COUNT(DISTINCT game_date) AS active_days
    FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks`
    WHERE game_date >= @since_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('since_date', 'DATE', since_date),
        ]
    )
    try:
        rows = list(bq_client.query(query, job_config=job_config).result())
        if rows:
            return dict(rows[0])
        return {}
    except Exception as e:
        logger.warning(f"Cumulative query failed: {e}")
        return {}


def format_report(
    daily_picks: List[dict],
    graded: List[dict],
    bb_graded: List[dict],
    edge_dist: List[dict],
    cumulative: dict,
    since_date: date
) -> str:
    """Format the performance report for stdout."""
    lines = []
    lines.append("=" * 60)
    lines.append("MLB DAILY PERFORMANCE REPORT")
    lines.append(f"Period: {since_date} to {date.today()}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    # Cumulative summary
    lines.append("")
    lines.append("CUMULATIVE SUMMARY")
    lines.append("-" * 40)
    if cumulative and cumulative.get('total_picks', 0) > 0:
        total = cumulative['total_picks']
        wins = cumulative.get('total_wins') or 0
        losses = cumulative.get('total_losses') or 0
        ungraded = cumulative.get('total_ungraded') or 0
        hr = cumulative.get('cumulative_hr_pct')
        avg_edge = cumulative.get('avg_edge')
        days = cumulative.get('active_days') or 0
        first = cumulative.get('first_pick_date')
        last = cumulative.get('last_pick_date')

        lines.append(f"  Total picks:     {total}")
        lines.append(f"  Record:          {wins}-{losses}"
                     f" ({hr}% HR)" if hr is not None
                     else f"  Record:          {wins}-{losses} (no graded)")
        if ungraded > 0:
            lines.append(f"  Ungraded:        {ungraded}")
        lines.append(f"  Avg edge:        {avg_edge}")
        lines.append(f"  Active days:     {days} ({first} to {last})")
    else:
        lines.append("  No picks found in this period.")
        lines.append("")
        lines.append("  The MLB system is 8 days old (launched 2026-03-28).")
        lines.append("  If picks are expected, check:")
        lines.append("    - mlb-prediction-worker health endpoint")
        lines.append("    - MLB schedule has games today")
        lines.append("    - Phase 5 predictions are writing to pitcher_strikeouts")
        lines.append("    - signal_best_bets_picks table exists and has data")
        return "\n".join(lines)

    # Daily pick volume
    lines.append("")
    lines.append("DAILY PICK VOLUME")
    lines.append("-" * 40)
    if daily_picks:
        lines.append(f"  {'Date':<12} {'Picks':>5} {'OVER':>5} {'UNDER':>6}"
                     f" {'AvgEdge':>8} {'Pitchers':>9}")
        lines.append(f"  {'-'*12} {'-'*5} {'-'*5} {'-'*6} {'-'*8} {'-'*9}")
        for row in daily_picks:
            gd = row['game_date']
            date_str = gd.strftime('%Y-%m-%d') if hasattr(gd, 'strftime') else str(gd)
            lines.append(
                f"  {date_str:<12} {row['total_picks']:>5}"
                f" {row['over_picks']:>5} {row['under_picks']:>6}"
                f" {row['avg_edge']:>8}"
                f" {row['distinct_pitchers']:>9}"
            )
    else:
        lines.append("  No daily pick data.")

    # Daily graded performance (best bets)
    lines.append("")
    lines.append("DAILY GRADED PERFORMANCE (Best Bets)")
    lines.append("-" * 40)
    if bb_graded:
        lines.append(f"  {'Date':<12} {'W':>3} {'L':>3} {'HR%':>6}"
                     f" {'OVER':>6} {'UNDER':>6} {'AvgEdge':>8}")
        lines.append(f"  {'-'*12} {'-'*3} {'-'*3} {'-'*6}"
                     f" {'-'*6} {'-'*6} {'-'*8}")
        for row in bb_graded:
            gd = row['game_date']
            date_str = gd.strftime('%Y-%m-%d') if hasattr(gd, 'strftime') else str(gd)
            hr = row.get('bb_hit_rate_pct')
            hr_str = f"{hr:>5.1f}%" if hr is not None else "   N/A"
            lines.append(
                f"  {date_str:<12} {row['bb_wins']:>3} {row['bb_losses']:>3}"
                f" {hr_str}"
                f" {row['bb_over']:>6} {row['bb_under']:>6}"
                f" {row['bb_avg_edge']:>8}"
            )
    elif graded:
        # Fall back to prediction_accuracy if BB grading not available
        lines.append("  (Using prediction_accuracy — BB picks not yet graded)")
        lines.append(f"  {'Date':<12} {'W':>3} {'L':>3} {'HR%':>6}"
                     f" {'AvgEdge':>8} {'Voided':>7}")
        lines.append(f"  {'-'*12} {'-'*3} {'-'*3} {'-'*6}"
                     f" {'-'*8} {'-'*7}")
        for row in graded:
            gd = row['game_date']
            date_str = gd.strftime('%Y-%m-%d') if hasattr(gd, 'strftime') else str(gd)
            hr = row.get('hit_rate_pct')
            hr_str = f"{hr:>5.1f}%" if hr is not None else "   N/A"
            lines.append(
                f"  {date_str:<12} {row['wins']:>3} {row['losses']:>3}"
                f" {hr_str}"
                f" {row['avg_edge']:>8}"
                f" {row['voided']:>7}"
            )
    else:
        lines.append("  No graded picks yet.")
        lines.append("  Games need to complete before grading runs.")

    # Edge distribution
    lines.append("")
    lines.append("EDGE DISTRIBUTION (Best Bets)")
    lines.append("-" * 40)
    if edge_dist:
        lines.append(f"  {'Bucket':<10} {'Picks':>6} {'W':>4} {'L':>4}"
                     f" {'HR%':>6} {'Ungraded':>9}")
        lines.append(f"  {'-'*10} {'-'*6} {'-'*4} {'-'*4}"
                     f" {'-'*6} {'-'*9}")
        for row in edge_dist:
            hr = row.get('hit_rate_pct')
            hr_str = f"{hr:>5.1f}%" if hr is not None else "   N/A"
            lines.append(
                f"  {row['edge_bucket']:<10} {row['picks']:>6}"
                f" {row['wins']:>4} {row['losses']:>4}"
                f" {hr_str}"
                f" {row['ungraded']:>9}"
            )
    else:
        lines.append("  No edge distribution data.")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="MLB Daily Performance Tracking"
    )
    parser.add_argument(
        '--days', type=int, default=30,
        help='Number of days to look back (default: 30)'
    )
    parser.add_argument(
        '--since', type=str, default=None,
        help='Start date (YYYY-MM-DD). Overrides --days.'
    )
    args = parser.parse_args()

    if args.since:
        since_date = date.fromisoformat(args.since)
    else:
        since_date = date.today() - timedelta(days=args.days)

    logger.info(f"Querying MLB performance since {since_date}")

    bq_client = get_bq_client()

    # Run all queries
    daily_picks = query_daily_picks(bq_client, since_date)
    graded = query_graded_performance(bq_client, since_date)
    bb_graded = query_bb_graded_performance(bq_client, since_date)
    edge_dist = query_edge_distribution(bq_client, since_date)
    cumulative = query_cumulative_totals(bq_client, since_date)

    # Format and print report
    report = format_report(
        daily_picks, graded, bb_graded, edge_dist, cumulative, since_date
    )
    print(report)


if __name__ == '__main__':
    main()
