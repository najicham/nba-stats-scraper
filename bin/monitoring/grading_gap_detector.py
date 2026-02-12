#!/usr/bin/env python3
"""
Grading Gap Detector (Session 209)

Detects incomplete grading (<80% of predictions) and auto-triggers backfills.
Runs daily at 9 AM ET after grading runs complete.

Critical finding (Session 209): Four dates with significant grading gaps:
- 2026-02-03: 146/171 (85.4%)
- 2026-01-31: 102/209 (48.8%)
- 2026-01-30: 130/351 (37.0%)
- 2026-01-29: 117/282 (41.5%)

Usage:
    python bin/monitoring/grading_gap_detector.py [--dry-run] [--days N]

Options:
    --dry-run: Show gaps without triggering backfills
    --days: Number of days to check (default: 14)
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
import requests

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from shared.utils.slack_alerts import send_slack_alert

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")
GRADING_THRESHOLD = 0.80  # Trigger backfill if <80% graded
COORDINATOR_URL = "https://prediction-coordinator-qgppybjaja-uw.a.run.app"


def detect_grading_gaps(
    client: bigquery.Client,
    lookback_days: int = 14
) -> List[Dict]:
    """
    Find dates where graded < 80% of predictions.

    Returns list of gap records:
    [
        {
            'game_date': '2026-01-30',
            'predicted': 351,
            'graded': 130,
            'grading_pct': 37.0,
            'status': 'gap'
        }
    ]
    """
    logger.info(f"Checking for grading gaps in last {lookback_days} days")

    query = f"""
    WITH completed_dates AS (
        -- Only check dates where all games are final
        SELECT DISTINCT game_date
        FROM `nba-props-platform.nba_reference.nba_schedule`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
          AND game_date < CURRENT_DATE()
          AND game_status = 3  -- Final
        GROUP BY game_date
        HAVING COUNT(*) = COUNTIF(game_status = 3)
    ),
    predictions AS (
        -- Count ALL active predictions across ALL models
        SELECT
            p.game_date,
            COUNT(*) as total_predictions,
            COUNT(DISTINCT system_id) as models_with_predictions
        FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
        JOIN completed_dates c ON p.game_date = c.game_date
        WHERE p.is_active = TRUE
        GROUP BY p.game_date
    ),
    graded AS (
        -- Count ALL graded predictions across ALL models
        SELECT
            game_date,
            COUNT(*) as graded_predictions,
            COUNT(DISTINCT system_id) as models_graded
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE game_date IN (SELECT game_date FROM completed_dates)
        GROUP BY game_date
    )
    SELECT
        p.game_date,
        p.total_predictions as predicted,
        COALESCE(g.graded_predictions, 0) as graded,
        ROUND(100.0 * COALESCE(g.graded_predictions, 0) / p.total_predictions, 1) as grading_pct,
        p.models_with_predictions,
        COALESCE(g.models_graded, 0) as models_graded,
        CASE
            WHEN COALESCE(g.graded_predictions, 0) = 0 THEN 'missing'
            WHEN 100.0 * COALESCE(g.graded_predictions, 0) / p.total_predictions < {GRADING_THRESHOLD * 100} THEN 'gap'
            ELSE 'ok'
        END as status
    FROM predictions p
    LEFT JOIN graded g ON p.game_date = g.game_date
    WHERE COALESCE(g.graded_predictions, 0) < p.total_predictions * {GRADING_THRESHOLD}
    ORDER BY p.game_date DESC
    """

    query_job = client.query(query)
    results = list(query_job.result())

    gaps = []
    for row in results:
        gaps.append({
            'game_date': str(row.game_date),
            'predicted': row.predicted,
            'graded': row.graded,
            'grading_pct': float(row.grading_pct),
            'models_with_predictions': row.models_with_predictions,
            'models_graded': row.models_graded,
            'status': row.status
        })

    return gaps


def trigger_grading_backfill(
    game_date: str,
    dry_run: bool = False
) -> Dict:
    """
    Trigger BACKFILL mode via prediction-coordinator /start.

    Safe: only fills gaps, doesn't overwrite existing grades.

    Returns:
        {
            'success': True/False,
            'message': '...',
            'batch_id': '...'  # if success
        }
    """
    if dry_run:
        logger.info(f"[DRY-RUN] Would trigger BACKFILL for {game_date}")
        return {'success': True, 'message': 'Dry run', 'batch_id': 'dry-run'}

    try:
        # Get Cloud Run auth token (same pattern as pipeline_canary_queries.py)
        metadata_server_url = 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token'
        headers = {'Metadata-Flavor': 'Google'}

        try:
            token_response = requests.get(metadata_server_url, headers=headers, timeout=5)
            token_response.raise_for_status()
            access_token = token_response.json()['access_token']
        except Exception as e:
            logger.error(f"Failed to get auth token: {e}")
            return {
                'success': False,
                'message': f'Auth failed: {e}'
            }

        # Trigger BACKFILL
        url = f"{COORDINATOR_URL}/start"
        payload = {
            'mode': 'BACKFILL',
            'backfill_date': game_date
        }
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        logger.info(f"Triggering BACKFILL for {game_date}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        result = response.json()
        logger.info(f"BACKFILL triggered: {result}")

        return {
            'success': True,
            'message': result.get('message', 'Success'),
            'batch_id': result.get('batch_id')
        }

    except Exception as e:
        logger.error(f"Failed to trigger BACKFILL for {game_date}: {e}")
        return {
            'success': False,
            'message': str(e)
        }


def format_slack_alert(
    gaps: List[Dict],
    backfill_results: List[Dict],
    dry_run: bool = False
) -> str:
    """Format Slack alert with gap details + backfill status."""
    if not gaps:
        return None

    mode_str = "[DRY-RUN] " if dry_run else ""
    lines = [
        f"{mode_str}🔍 *Grading Gap Detector*",
        f"Found {len(gaps)} dates with <{int(GRADING_THRESHOLD * 100)}% grading completion:\n"
    ]

    for gap in gaps:
        lines.append(
            f"• `{gap['game_date']}`: {gap['graded']}/{gap['predicted']} "
            f"({gap['grading_pct']:.1f}%) - {gap['status'].upper()}"
        )

    if backfill_results and not dry_run:
        lines.append("\n*Backfill Results:*")
        for result in backfill_results:
            status_emoji = "✅" if result['success'] else "❌"
            lines.append(
                f"{status_emoji} `{result['game_date']}`: {result['message']}"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Detect grading gaps and trigger backfills')
    parser.add_argument('--dry-run', action='store_true', help='Show gaps without triggering backfills')
    parser.add_argument('--days', type=int, default=14, help='Number of days to check')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    # Detect gaps
    gaps = detect_grading_gaps(client, lookback_days=args.days)

    if not gaps:
        logger.info(f"✅ No grading gaps found in last {args.days} days")
        return 0

    logger.warning(f"Found {len(gaps)} grading gaps:")
    for gap in gaps:
        logger.warning(
            f"  {gap['game_date']}: {gap['graded']}/{gap['predicted']} "
            f"({gap['grading_pct']:.1f}%) - {gap['status']} "
            f"[{gap['models_graded']}/{gap['models_with_predictions']} models]"
        )

    # Trigger backfills
    backfill_results = []
    for gap in gaps:
        result = trigger_grading_backfill(gap['game_date'], dry_run=args.dry_run)
        backfill_results.append({
            'game_date': gap['game_date'],
            'success': result['success'],
            'message': result['message']
        })

    # Send Slack alert
    alert_message = format_slack_alert(gaps, backfill_results, dry_run=args.dry_run)
    if alert_message:
        send_slack_alert(alert_message, channel='#nba-alerts')

    # Exit with error code if any backfills failed (unless dry-run)
    if not args.dry_run and any(not r['success'] for r in backfill_results):
        logger.error("Some backfills failed")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
