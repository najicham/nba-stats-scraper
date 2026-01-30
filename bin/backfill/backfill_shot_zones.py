#!/usr/bin/env python3
"""
Backfill Shot Zone Data

Reprocesses Phase 3 for dates that were processed without BigDataBall data.
BDB data is now available, so re-running will populate paint_attempts correctly.

Usage:
    # Dry run - show what would be done
    python bin/backfill/backfill_shot_zones.py --dry-run

    # Process specific date
    python bin/backfill/backfill_shot_zones.py --date 2026-01-23

    # Process all affected dates
    python bin/backfill/backfill_shot_zones.py --all

    # Process with delay between dates (avoid overwhelming system)
    python bin/backfill/backfill_shot_zones.py --all --delay 60

Created: Session 39 (2026-01-30)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, date, timedelta
from typing import List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from google.cloud import pubsub_v1

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
PHASE3_TOPIC = 'nba-phase3-trigger'


def get_dates_needing_backfill(client: bigquery.Client) -> List[Dict]:
    """
    Find dates that have BDB data but missing paint_attempts in player_game_summary.

    Returns list of {game_date, total_players, with_paint, paint_pct}
    """
    query = f"""
    WITH pgs_summary AS (
        SELECT
            game_date,
            COUNT(*) as total_players,
            COUNTIF(paint_attempts IS NOT NULL) as with_paint,
            ROUND(100.0 * COUNTIF(paint_attempts IS NOT NULL) / COUNT(*), 1) as paint_pct
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date >= '2026-01-01'
          AND minutes_played > 0
        GROUP BY 1
    ),
    bdb_available AS (
        SELECT
            game_date,
            COUNT(DISTINCT LPAD(CAST(bdb_game_id AS STRING), 10, '0')) as games_with_bdb,
            COUNTIF(event_type = 'shot' AND shot_distance IS NOT NULL) as shots_with_distance
        FROM `{PROJECT_ID}.nba_raw.bigdataball_play_by_play`
        WHERE game_date >= '2026-01-01'
          AND bdb_game_id IS NOT NULL
        GROUP BY 1
    )
    SELECT
        p.game_date,
        p.total_players,
        p.with_paint,
        p.paint_pct,
        COALESCE(b.games_with_bdb, 0) as bdb_games,
        COALESCE(b.shots_with_distance, 0) as bdb_shots
    FROM pgs_summary p
    LEFT JOIN bdb_available b ON p.game_date = b.game_date
    WHERE p.paint_pct < 50  -- Less than 50% have paint data
      AND b.shots_with_distance >= 100  -- BDB data IS available
    ORDER BY p.game_date
    """

    result = client.query(query).to_dataframe()
    return result.to_dict('records')


def trigger_phase3_rerun(
    publisher: pubsub_v1.PublisherClient,
    topic_path: str,
    game_date: date,
    dry_run: bool = False
) -> bool:
    """Trigger Phase 3 reprocessing for a date."""
    if dry_run:
        logger.info(f"[DRY-RUN] Would trigger Phase 3 for {game_date}")
        return True

    try:
        message = json.dumps({
            'game_date': game_date.isoformat(),
            'trigger_reason': 'shot_zone_backfill',
            'is_rerun': True,
            'source': 'backfill_shot_zones',
            'backfill_timestamp': datetime.utcnow().isoformat()
        }).encode('utf-8')

        future = publisher.publish(topic_path, message)
        future.result(timeout=30)

        logger.info(f"✓ Triggered Phase 3 for {game_date}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to trigger Phase 3 for {game_date}: {e}")
        return False


def record_backfill_attempt(
    client: bigquery.Client,
    game_date: date,
    status: str,
    notes: str
) -> None:
    """Record backfill attempt in orchestration log."""
    try:
        query = f"""
        INSERT INTO `{PROJECT_ID}.nba_orchestration.backfill_log`
        (backfill_type, target_date, status, notes, created_at)
        VALUES
        ('shot_zone_reprocess', '{game_date}', '{status}', '{notes}', CURRENT_TIMESTAMP())
        """
        client.query(query).result()
    except Exception as e:
        # Table might not exist, that's OK
        logger.debug(f"Could not log backfill attempt: {e}")


def main():
    parser = argparse.ArgumentParser(description='Backfill shot zone data')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--date', type=str, help='Process specific date (YYYY-MM-DD)')
    parser.add_argument('--all', action='store_true', help='Process all affected dates')
    parser.add_argument('--delay', type=int, default=30, help='Seconds between dates (default: 30)')
    parser.add_argument('--limit', type=int, help='Max dates to process')
    args = parser.parse_args()

    client = bigquery.Client()

    # Get dates needing backfill
    logger.info("Checking for dates needing backfill...")
    dates_to_process = get_dates_needing_backfill(client)

    if not dates_to_process:
        logger.info("No dates need backfill - all dates have paint_attempts populated!")
        return

    logger.info(f"Found {len(dates_to_process)} dates needing backfill:")
    for d in dates_to_process:
        logger.info(
            f"  {d['game_date']}: {d['with_paint']}/{d['total_players']} with paint "
            f"({d['paint_pct']}%), BDB has {d['bdb_shots']} shots"
        )

    # Filter to specific date if requested
    if args.date:
        target_date = date.fromisoformat(args.date)
        dates_to_process = [d for d in dates_to_process if d['game_date'] == target_date]
        if not dates_to_process:
            logger.warning(f"Date {args.date} not in list of dates needing backfill")
            return

    # Apply limit if specified
    if args.limit:
        dates_to_process = dates_to_process[:args.limit]

    if not args.all and not args.date:
        logger.info("\nUse --all to process all dates, or --date YYYY-MM-DD for specific date")
        logger.info("Add --dry-run to see what would happen without making changes")
        return

    # Initialize Pub/Sub
    if not args.dry_run:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, PHASE3_TOPIC)
    else:
        publisher = None
        topic_path = None

    # Process dates
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing {len(dates_to_process)} dates (dry_run={args.dry_run})")
    logger.info(f"{'='*60}\n")

    success_count = 0
    fail_count = 0

    for i, d in enumerate(dates_to_process):
        game_date = d['game_date']

        if trigger_phase3_rerun(publisher, topic_path, game_date, args.dry_run):
            success_count += 1
            if not args.dry_run:
                record_backfill_attempt(client, game_date, 'triggered',
                    f"Paint coverage was {d['paint_pct']}%, BDB has {d['bdb_shots']} shots")
        else:
            fail_count += 1
            if not args.dry_run:
                record_backfill_attempt(client, game_date, 'failed', 'Pub/Sub publish failed')

        # Delay between dates (except for last one)
        if i < len(dates_to_process) - 1 and not args.dry_run and args.delay > 0:
            logger.info(f"Waiting {args.delay}s before next date...")
            time.sleep(args.delay)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"BACKFILL COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  Triggered: {success_count}")
    logger.info(f"  Failed: {fail_count}")
    logger.info(f"  Total: {len(dates_to_process)}")

    if not args.dry_run:
        logger.info("\nPhase 3 jobs have been triggered. After they complete:")
        logger.info("1. Run Phase 4 backfill for player_shot_zone_analysis")
        logger.info("2. Run Phase 4 backfill for ml_feature_store")
        logger.info("3. Verify with: python bin/monitoring/bdb_critical_monitor.py")


if __name__ == '__main__':
    main()
