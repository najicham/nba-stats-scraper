#!/usr/bin/env python3
"""
Fix Postponed Game Data

This script fixes data issues caused by postponed games:
1. Updates schedule status from "Final" to "Postponed"
2. Invalidates predictions for the original date
3. Records the postponement in the tracking table
4. Optionally triggers prediction generation for the new date

Usage:
    python bin/fixes/fix_postponed_game.py --game-id 0022500644 --original-date 2026-01-24 --new-date 2026-01-25 --reason "Minneapolis shooting incident"
    python bin/fixes/fix_postponed_game.py --game-id 0022500644 --original-date 2026-01-24 --dry-run
"""

import argparse
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from google.cloud import bigquery

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

client = bigquery.Client()
PROJECT_ID = "nba-props-platform"


def get_game_info(game_id: str, game_date: date) -> dict:
    """Get game information from schedule."""
    query = """
    SELECT
        game_id,
        game_date,
        game_status,
        game_status_text,
        home_team_tricode,
        away_team_tricode,
        home_team_score,
        away_team_score
    FROM `nba_raw.nbac_schedule`
    WHERE game_date = @game_date
      AND game_id = @game_id
    LIMIT 1
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
        ]
    )

    results = list(client.query(query, job_config=job_config).result())
    if results:
        row = results[0]
        return {
            'game_id': row.game_id,
            'game_date': str(row.game_date),
            'status': row.game_status,
            'status_text': row.game_status_text,
            'home_team': row.home_team_tricode,
            'away_team': row.away_team_tricode,
            'home_score': row.home_team_score,
            'away_score': row.away_team_score,
        }
    return None


def get_affected_predictions(game_date: date, home_team: str, away_team: str) -> list:
    """Get predictions that need to be invalidated."""
    # Build the game_id pattern used in predictions
    date_str = game_date.strftime('%Y%m%d')
    game_id_pattern = f"{date_str}_{away_team}_{home_team}"

    query = """
    SELECT
        prediction_id,
        player_lookup,
        game_id,
        system_id,
        predicted_points,
        invalidation_reason
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
      AND game_id = @game_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("game_id", "STRING", game_id_pattern),
        ]
    )

    results = list(client.query(query, job_config=job_config).result())
    return [dict(row) for row in results]


def invalidate_predictions(
    game_date: date,
    home_team: str,
    away_team: str,
    reason: str,
    dry_run: bool = False
) -> int:
    """
    Actually invalidate predictions by updating the invalidation columns.

    Args:
        game_date: Date of the game
        home_team: Home team tricode
        away_team: Away team tricode
        reason: Reason for invalidation (e.g., 'game_postponed')
        dry_run: If True, don't make changes

    Returns:
        Number of predictions invalidated
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would invalidate predictions for {away_team}@{home_team} on {game_date}")
        return 0

    # Build the game_id pattern used in predictions
    date_str = game_date.strftime('%Y%m%d')
    game_id_pattern = f"{date_str}_{away_team}_{home_team}"

    # Use MERGE to update predictions (BigQuery doesn't support UPDATE on partitioned tables easily)
    # We'll use a DML UPDATE with partition filter
    query = """
    UPDATE `nba_predictions.player_prop_predictions`
    SET
        invalidation_reason = @reason,
        invalidated_at = CURRENT_TIMESTAMP()
    WHERE game_date = @game_date
      AND game_id = @game_id
      AND invalidation_reason IS NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("game_id", "STRING", game_id_pattern),
            bigquery.ScalarQueryParameter("reason", "STRING", reason),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result()
        # Get the number of rows modified
        rows_affected = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0
        logger.info(f"Invalidated {rows_affected} predictions for {away_team}@{home_team}")
        return rows_affected
    except Exception as e:
        logger.error(f"Failed to invalidate predictions: {e}")
        return 0


def update_schedule_status(game_id: str, game_date: date, dry_run: bool = False) -> bool:
    """Update schedule record to show postponed status."""
    if dry_run:
        logger.info(f"[DRY RUN] Would update schedule for {game_id} on {game_date}")
        return True

    # Note: BigQuery doesn't support UPDATE on partitioned tables easily
    # We'll use a MERGE or just log the required fix
    query = """
    UPDATE `nba_raw.nbac_schedule`
    SET game_status_text = 'Postponed'
    WHERE game_date = @game_date
      AND game_id = @game_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
        ]
    )

    try:
        client.query(query, job_config=job_config).result()
        logger.info(f"Updated schedule status for {game_id} to 'Postponed'")
        return True
    except Exception as e:
        logger.error(f"Failed to update schedule: {e}")
        return False


def record_postponement(
    game_id: str,
    original_date: date,
    new_date: Optional[date],
    reason: str,
    home_team: str,
    away_team: str,
    predictions_count: int,
    dry_run: bool = False
) -> bool:
    """Record the postponement in tracking table."""
    if dry_run:
        logger.info(f"[DRY RUN] Would record postponement for {game_id}")
        return True

    query = """
    INSERT INTO `nba_orchestration.game_postponements`
    (sport, game_id, original_date, new_date, reason, detection_source,
     detection_details, predictions_invalidated, status, confirmed_at)
    VALUES
    ('NBA', @game_id, @original_date, @new_date, @reason, 'manual_fix',
     @details, @predictions_count, 'confirmed', CURRENT_TIMESTAMP())
    """

    details = json.dumps({
        'home_team': home_team,
        'away_team': away_team,
        'matchup': f"{away_team}@{home_team}",
        'fixed_at': datetime.now(timezone.utc).isoformat(),
    })

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
            bigquery.ScalarQueryParameter("original_date", "DATE", original_date),
            bigquery.ScalarQueryParameter("new_date", "DATE", new_date),
            bigquery.ScalarQueryParameter("reason", "STRING", reason),
            bigquery.ScalarQueryParameter("details", "STRING", details),
            bigquery.ScalarQueryParameter("predictions_count", "INT64", predictions_count),
        ]
    )

    try:
        client.query(query, job_config=job_config).result()
        logger.info(f"Recorded postponement in tracking table")
        return True
    except Exception as e:
        logger.error(f"Failed to record postponement: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Fix postponed game data')
    parser.add_argument('--game-id', required=True, help='NBA.com game ID (e.g., 0022500644)')
    parser.add_argument('--original-date', required=True, help='Original scheduled date (YYYY-MM-DD)')
    parser.add_argument('--new-date', help='Rescheduled date (YYYY-MM-DD)')
    parser.add_argument('--reason', default='Game postponed', help='Reason for postponement')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')

    args = parser.parse_args()

    original_date = datetime.strptime(args.original_date, '%Y-%m-%d').date()
    new_date = datetime.strptime(args.new_date, '%Y-%m-%d').date() if args.new_date else None

    print("=" * 60)
    print("POSTPONED GAME FIX")
    print("=" * 60)

    if args.dry_run:
        print("[DRY RUN MODE - No changes will be made]")
    print()

    # Step 1: Get game info
    print("Step 1: Getting game information...")
    game_info = get_game_info(args.game_id, original_date)
    if not game_info:
        print(f"  ERROR: Game {args.game_id} not found for date {original_date}")
        return 1

    print(f"  Game: {game_info['away_team']}@{game_info['home_team']}")
    print(f"  Current Status: {game_info['status_text']}")
    print(f"  Scores: {game_info['away_score']} - {game_info['home_score']}")

    # Step 2: Find affected predictions
    print("\nStep 2: Finding affected predictions...")
    predictions = get_affected_predictions(
        original_date,
        game_info['home_team'],
        game_info['away_team']
    )
    # Count already invalidated vs pending
    already_invalidated = sum(1 for p in predictions if p.get('invalidation_reason'))
    pending_invalidation = len(predictions) - already_invalidated

    print(f"  Found {len(predictions)} total predictions")
    if already_invalidated:
        print(f"  Already invalidated: {already_invalidated}")
    print(f"  To invalidate: {pending_invalidation}")

    if predictions:
        # Show sample
        print("  Sample predictions:")
        for p in predictions[:5]:
            status = " (already invalidated)" if p.get('invalidation_reason') else ""
            print(f"    - {p['player_lookup']}: {p['predicted_points']} pts ({p['system_id']}){status}")
        if len(predictions) > 5:
            print(f"    ... and {len(predictions) - 5} more")

    # Step 3: Invalidate predictions
    print("\nStep 3: Invalidating predictions...")
    invalidation_reason = f"game_postponed_{game_info['away_team']}_{game_info['home_team']}_{original_date}"
    invalidated_count = invalidate_predictions(
        original_date,
        game_info['home_team'],
        game_info['away_team'],
        invalidation_reason,
        args.dry_run
    )
    if args.dry_run:
        print(f"  [DRY RUN] Would invalidate {pending_invalidation} predictions")
    else:
        print(f"  Invalidated {invalidated_count} predictions")

    # Step 4: Update schedule
    print("\nStep 4: Updating schedule status...")
    if update_schedule_status(args.game_id, original_date, args.dry_run):
        print("  Schedule updated to 'Postponed'")
    else:
        print("  WARNING: Failed to update schedule")

    # Step 5: Record postponement
    print("\nStep 5: Recording postponement...")
    if record_postponement(
        args.game_id,
        original_date,
        new_date,
        args.reason,
        game_info['home_team'],
        game_info['away_team'],
        len(predictions),
        args.dry_run
    ):
        print("  Postponement recorded in tracking table")
    else:
        print("  WARNING: Failed to record postponement")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Game: {game_info['away_team']}@{game_info['home_team']} ({args.game_id})")
    print(f"  Original Date: {original_date}")
    print(f"  New Date: {new_date or 'TBD'}")
    print(f"  Reason: {args.reason}")
    print(f"  Predictions Found: {len(predictions)}")
    print(f"  Predictions Invalidated: {invalidated_count if not args.dry_run else f'(dry run) {pending_invalidation}'}")

    if args.dry_run:
        print("\n[DRY RUN - No changes were made]")
        print("Run without --dry-run to apply changes")

    return 0


if __name__ == '__main__':
    exit(main())
