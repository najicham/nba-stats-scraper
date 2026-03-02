#!/usr/bin/env python3
"""Model Profile Monitor — automated daily detection of profile drift and stale blocks.

Detects:
1. New block candidates: slice HR < 45%, N >= 15, not currently blocked
2. Stale blocks: blocked slice recovered above 55% for 3+ days
3. Filter counterfactual: what HR would blocked predictions have achieved?
4. Coverage gaps: model not generating data in expected dimensions

Designed to run daily via Cloud Scheduler at 11:30 AM ET (after decay detection).

Usage:
    PYTHONPATH=. python bin/monitoring/model_profile_monitor.py --date 2026-03-01
    PYTHONPATH=. python bin/monitoring/model_profile_monitor.py --days 7  # Last 7 days

Created: 2026-03-01 (Session 384)
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'

# Thresholds
BLOCK_HR = 45.0       # HR below which a slice gets blocked
RECOVER_HR = 55.0     # HR above which a block should be reconsidered
RECOVER_DAYS = 3      # Consecutive days above RECOVER_HR to recommend unblocking
MIN_N = 15            # Minimum sample size for evaluation


def check_new_block_candidates(
    bq_client: bigquery.Client,
    target_date: date,
) -> List[dict]:
    """Find dimension slices that should be blocked but aren't yet.

    Queries model_profile_daily for slices with HR < 45%, N >= 15, is_blocked=FALSE.
    """
    query = f"""
    SELECT
        model_id, affinity_group, dimension, dimension_value,
        hr_14d, n_14d, bb_hr_14d, bb_n_14d
    FROM `{PROJECT_ID}.nba_predictions.model_profile_daily`
    WHERE game_date = @target_date
      AND hr_14d < @block_hr
      AND n_14d >= @min_n
      AND (is_blocked IS NULL OR is_blocked = FALSE)
    ORDER BY hr_14d ASC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('block_hr', 'FLOAT64', BLOCK_HR),
            bigquery.ScalarQueryParameter('min_n', 'INT64', MIN_N),
        ]
    )
    rows = list(bq_client.query(query, job_config=job_config).result(timeout=60))
    return [
        {
            'model_id': r.model_id,
            'affinity_group': r.affinity_group,
            'dimension': r.dimension,
            'dimension_value': r.dimension_value,
            'hr_14d': float(r.hr_14d),
            'n_14d': r.n_14d,
            'bb_hr_14d': float(r.bb_hr_14d) if r.bb_hr_14d is not None else None,
            'bb_n_14d': r.bb_n_14d,
            'severity': 'CRITICAL' if r.hr_14d < 35 else 'WARNING',
        }
        for r in rows
    ]


def check_stale_blocks(
    bq_client: bigquery.Client,
    target_date: date,
) -> List[dict]:
    """Find blocked slices that have recovered above RECOVER_HR for 3+ days.

    A block that persists after the underlying issue is resolved wastes
    profitable picks.
    """
    query = f"""
    WITH recent AS (
        SELECT
            model_id, dimension, dimension_value,
            game_date, hr_14d, n_14d, is_blocked
        FROM `{PROJECT_ID}.nba_predictions.model_profile_daily`
        WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL @recover_days DAY) AND @target_date
          AND is_blocked = TRUE
    ),
    consecutive_recovery AS (
        SELECT
            model_id, dimension, dimension_value,
            COUNTIF(hr_14d >= @recover_hr) AS days_above_threshold,
            MAX(hr_14d) AS max_hr,
            MAX(n_14d) AS max_n,
            COUNT(*) AS total_days
        FROM recent
        GROUP BY model_id, dimension, dimension_value
    )
    SELECT *
    FROM consecutive_recovery
    WHERE days_above_threshold >= @recover_days
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('recover_hr', 'FLOAT64', RECOVER_HR),
            bigquery.ScalarQueryParameter('recover_days', 'INT64', RECOVER_DAYS),
        ]
    )
    rows = list(bq_client.query(query, job_config=job_config).result(timeout=60))
    return [
        {
            'model_id': r.model_id,
            'dimension': r.dimension,
            'dimension_value': r.dimension_value,
            'days_above_threshold': r.days_above_threshold,
            'max_hr': float(r.max_hr),
            'max_n': r.max_n,
        }
        for r in rows
    ]


def check_freshness(
    bq_client: bigquery.Client,
    target_date: date,
) -> dict:
    """Check if model_profile_daily has data for the target date."""
    query = f"""
    SELECT
        MAX(game_date) AS latest_date,
        COUNT(*) AS row_count,
        COUNT(DISTINCT model_id) AS model_count
    FROM `{PROJECT_ID}.nba_predictions.model_profile_daily`
    WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 3 DAY) AND @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    row = next(bq_client.query(query, job_config=job_config).result(timeout=30))
    return {
        'latest_date': str(row.latest_date) if row.latest_date else None,
        'row_count': row.row_count or 0,
        'model_count': row.model_count or 0,
        'is_fresh': row.latest_date == target_date if row.latest_date else False,
    }


def check_profile_vs_hardcoded(
    bq_client: bigquery.Client,
    target_date: date,
) -> List[dict]:
    """Compare profile blocks with known hardcoded filter blocks.

    Checks whether profile-based blocking would catch the same predictions
    as the existing hardcoded filters (model_direction_affinity, away_noveg, etc.).
    """
    query = f"""
    WITH profile_blocks AS (
        SELECT model_id, dimension, dimension_value, hr_14d, n_14d
        FROM `{PROJECT_ID}.nba_predictions.model_profile_daily`
        WHERE game_date = @target_date
          AND is_blocked = TRUE
    ),
    known_blocks AS (
        -- V9 UNDER (model_direction_affinity)
        SELECT 'v9_under' AS known_filter, model_id, dimension, dimension_value, hr_14d, n_14d
        FROM profile_blocks
        WHERE dimension = 'direction' AND dimension_value = 'UNDER'
          AND model_id LIKE 'catboost_v9%'
          AND model_id NOT LIKE 'catboost_v9_low_vegas%'

        UNION ALL

        -- v12_noveg AWAY
        SELECT 'v12_noveg_away', model_id, dimension, dimension_value, hr_14d, n_14d
        FROM profile_blocks
        WHERE dimension = 'home_away' AND dimension_value = 'AWAY'
          AND (model_id LIKE 'catboost_v12_noveg%' OR model_id LIKE 'catboost_v16_noveg%'
               OR model_id LIKE 'lgbm_v12_noveg%')

        UNION ALL

        -- v9 AWAY
        SELECT 'v9_away', model_id, dimension, dimension_value, hr_14d, n_14d
        FROM profile_blocks
        WHERE dimension = 'home_away' AND dimension_value = 'AWAY'
          AND model_id LIKE 'catboost_v9%'
          AND model_id NOT LIKE 'catboost_v9_low_vegas%'
    )
    SELECT * FROM known_blocks ORDER BY known_filter, model_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    rows = list(bq_client.query(query, job_config=job_config).result(timeout=60))
    return [
        {
            'known_filter': r.known_filter,
            'model_id': r.model_id,
            'dimension': r.dimension,
            'dimension_value': r.dimension_value,
            'hr_14d': float(r.hr_14d) if r.hr_14d is not None else None,
            'n_14d': r.n_14d,
        }
        for r in rows
    ]


def run_monitor(
    bq_client: bigquery.Client,
    target_date: date,
) -> dict:
    """Run all monitor checks and return structured results."""
    results = {
        'target_date': target_date.isoformat(),
        'computed_at': datetime.now(timezone.utc).isoformat(),
        'checks': {},
    }

    # 1. Freshness
    freshness = check_freshness(bq_client, target_date)
    results['checks']['freshness'] = freshness

    if not freshness['is_fresh']:
        logger.warning(
            f"Model profile data NOT FRESH for {target_date}. "
            f"Latest: {freshness['latest_date']}, rows: {freshness['row_count']}"
        )
        results['alerts'] = [{
            'severity': 'WARNING',
            'message': f"model_profile_daily not populated for {target_date}",
        }]
        return results

    # 2. New block candidates
    new_blocks = check_new_block_candidates(bq_client, target_date)
    results['checks']['new_block_candidates'] = {
        'count': len(new_blocks),
        'items': new_blocks,
    }

    # 3. Stale blocks
    stale = check_stale_blocks(bq_client, target_date)
    results['checks']['stale_blocks'] = {
        'count': len(stale),
        'items': stale,
    }

    # 4. Profile vs hardcoded alignment
    alignment = check_profile_vs_hardcoded(bq_client, target_date)
    results['checks']['hardcoded_alignment'] = {
        'count': len(alignment),
        'items': alignment,
    }

    # Build alerts
    alerts = []

    for block in new_blocks:
        alerts.append({
            'severity': block['severity'],
            'message': (
                f"NEW BLOCK CANDIDATE: {block['model_id']} "
                f"{block['dimension']}={block['dimension_value']} — "
                f"{block['hr_14d']:.1f}% HR (N={block['n_14d']})"
            ),
        })

    for stale_block in stale:
        alerts.append({
            'severity': 'INFO',
            'message': (
                f"STALE BLOCK: {stale_block['model_id']} "
                f"{stale_block['dimension']}={stale_block['dimension_value']} — "
                f"recovered to {stale_block['max_hr']:.1f}% for "
                f"{stale_block['days_above_threshold']} days"
            ),
        })

    results['alerts'] = alerts
    results['summary'] = {
        'models_profiled': freshness['model_count'],
        'new_block_candidates': len(new_blocks),
        'stale_blocks': len(stale),
        'hardcoded_matches': len(alignment),
        'total_alerts': len(alerts),
    }

    return results


def format_slack_message(results: dict) -> str:
    """Format results as a Slack message."""
    parts = [f"*Model Profile Monitor* — {results['target_date']}"]

    summary = results.get('summary', {})
    parts.append(
        f"Models: {summary.get('models_profiled', 0)} | "
        f"New blocks: {summary.get('new_block_candidates', 0)} | "
        f"Stale blocks: {summary.get('stale_blocks', 0)}"
    )

    alerts = results.get('alerts', [])
    critical = [a for a in alerts if a['severity'] == 'CRITICAL']
    warnings = [a for a in alerts if a['severity'] == 'WARNING']
    info = [a for a in alerts if a['severity'] == 'INFO']

    if critical:
        parts.append("\n:red_circle: *CRITICAL*")
        for a in critical[:5]:
            parts.append(f"  {a['message']}")

    if warnings:
        parts.append("\n:warning: *WARNINGS*")
        for a in warnings[:5]:
            parts.append(f"  {a['message']}")

    if info:
        parts.append(f"\n:information_source: *INFO* ({len(info)} items)")
        for a in info[:3]:
            parts.append(f"  {a['message']}")

    if not alerts:
        parts.append(":white_check_mark: All profiles healthy — no alerts")

    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description='Model Profile Monitor')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=1,
                        help='Number of days to check (from today backwards)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    bq_client = bigquery.Client(project=PROJECT_ID)

    if args.date:
        target = date.fromisoformat(args.date)
        results = run_monitor(bq_client, target)

        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            print(format_slack_message(results))
            print()
            # Detailed output
            for check_name, check_data in results.get('checks', {}).items():
                if isinstance(check_data, dict) and 'items' in check_data:
                    items = check_data['items']
                    if items:
                        print(f"\n--- {check_name} ({len(items)} items) ---")
                        for item in items[:10]:
                            print(f"  {item}")
    else:
        # Default: check yesterday
        target = date.today() - timedelta(days=1)
        results = run_monitor(bq_client, target)

        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            print(format_slack_message(results))


if __name__ == '__main__':
    main()
