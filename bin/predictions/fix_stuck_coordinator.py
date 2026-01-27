#!/usr/bin/env python3
"""
Fix Stuck Prediction Coordinator

This script investigates and fixes coordinator batches that are stuck in "in_progress" state.

Usage:
    python bin/predictions/fix_stuck_coordinator.py --batch-id batch_2026-01-28_1769555415
    python bin/predictions/fix_stuck_coordinator.py --list-stuck
    python bin/predictions/fix_stuck_coordinator.py --force-complete batch_2026-01-28_1769555415

Created: 2026-01-27
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import firestore
from predictions.coordinator.batch_state_manager import BatchStateManager


def list_stuck_batches(project_id: str, hours: int = 24):
    """
    List all batches that appear to be stuck.

    Args:
        project_id: GCP project ID
        hours: How many hours to look back
    """
    print(f"=== Searching for Stuck Batches (last {hours} hours) ===\n")

    state_manager = BatchStateManager(project_id)
    active_batches = state_manager.get_active_batches()

    if not active_batches:
        print("✅ No active batches found")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stuck_batches = []

    for batch in active_batches:
        # Get full batch document for timing info
        doc = state_manager.collection.document(batch.batch_id).get()
        if not doc.exists:
            continue

        data = doc.to_dict()
        updated_at = data.get('updated_at')

        if updated_at:
            if hasattr(updated_at, 'timestamp'):
                last_update = datetime.fromtimestamp(updated_at.timestamp(), tz=timezone.utc)
            else:
                last_update = updated_at

            time_stalled = datetime.now(timezone.utc) - last_update

            # Consider stuck if no updates for 10+ minutes
            if time_stalled > timedelta(minutes=10):
                stuck_batches.append({
                    'batch': batch,
                    'last_update': last_update,
                    'stalled_for': time_stalled,
                    'data': data
                })

    if not stuck_batches:
        print("✅ No stuck batches found")
        return

    print(f"⚠️  Found {len(stuck_batches)} stuck batch(es):\n")

    for item in stuck_batches:
        batch = item['batch']
        stalled_for = item['stalled_for']
        data = item['data']

        completed = len(batch.completed_players)
        expected = batch.expected_players
        completion_pct = (completed / expected * 100) if expected > 0 else 0

        print(f"Batch: {batch.batch_id}")
        print(f"  Game Date: {batch.game_date}")
        print(f"  Progress: {completed}/{expected} ({completion_pct:.1f}%)")
        print(f"  Total Predictions: {batch.total_predictions}")
        print(f"  Last Update: {item['last_update']} ({stalled_for.total_seconds() / 60:.0f} min ago)")
        print(f"  Is Complete: {batch.is_complete}")

        # Show claim info if exists
        claimed_by = data.get('claimed_by_instance')
        if claimed_by:
            print(f"  Claimed By: {claimed_by}")
            claim_expires = data.get('claim_expires_at')
            if claim_expires:
                if hasattr(claim_expires, 'timestamp'):
                    expires_dt = datetime.fromtimestamp(claim_expires.timestamp(), tz=timezone.utc)
                else:
                    expires_dt = claim_expires
                print(f"  Claim Expires: {expires_dt}")

        print()

    return stuck_batches


def inspect_batch(project_id: str, batch_id: str):
    """
    Inspect a specific batch in detail.

    Args:
        project_id: GCP project ID
        batch_id: Batch identifier
    """
    print(f"=== Inspecting Batch: {batch_id} ===\n")

    state_manager = BatchStateManager(project_id)
    batch = state_manager.get_batch_state(batch_id)

    if not batch:
        print(f"❌ Batch not found: {batch_id}")
        return

    # Get full document for extra metadata
    doc = state_manager.collection.document(batch_id).get()
    data = doc.to_dict() if doc.exists else {}

    print(f"Batch ID: {batch.batch_id}")
    print(f"Game Date: {batch.game_date}")
    print(f"Expected Players: {batch.expected_players}")
    print(f"Completed Players: {len(batch.completed_players)}")
    print(f"Failed Players: {len(batch.failed_players)}")
    print(f"Total Predictions: {batch.total_predictions}")
    print(f"Is Complete: {batch.is_complete}")
    print(f"Completion %: {batch.get_completion_percentage():.1f}%")
    print(f"Start Time: {batch.start_time}")
    print(f"Completion Time: {batch.completion_time}")
    print(f"Correlation ID: {batch.correlation_id}")

    # Additional metadata
    updated_at = data.get('updated_at')
    if updated_at:
        if hasattr(updated_at, 'timestamp'):
            last_update = datetime.fromtimestamp(updated_at.timestamp(), tz=timezone.utc)
        else:
            last_update = updated_at
        time_since = datetime.now(timezone.utc) - last_update
        print(f"Last Update: {last_update} ({time_since.total_seconds() / 60:.0f} min ago)")

    claimed_by = data.get('claimed_by_instance')
    if claimed_by:
        print(f"Claimed By: {claimed_by}")

    created_by = data.get('created_by_instance')
    if created_by:
        print(f"Created By: {created_by}")

    # Show sample of completed players
    if batch.completed_players:
        print(f"\nCompleted Players (first 10):")
        for player in batch.completed_players[:10]:
            pred_count = batch.predictions_by_player.get(player, 0)
            print(f"  - {player} ({pred_count} predictions)")

    # Show failed players
    if batch.failed_players:
        print(f"\nFailed Players:")
        for player in batch.failed_players:
            print(f"  - {player}")

    # Check for subcollection data
    if state_manager.enable_subcollection:
        completed_count = data.get('completed_count', 0)
        print(f"\nSubcollection Mode:")
        print(f"  Completed Count (counter): {completed_count}")
        print(f"  Array Length: {len(batch.completed_players)}")
        if completed_count != len(batch.completed_players):
            print(f"  ⚠️  MISMATCH between counter and array!")


def force_complete_batch(project_id: str, batch_id: str, dry_run: bool = False):
    """
    Force-complete a stuck batch.

    Args:
        project_id: GCP project ID
        batch_id: Batch identifier
        dry_run: If True, only show what would be done
    """
    print(f"=== Force-Completing Batch: {batch_id} ===\n")

    state_manager = BatchStateManager(project_id)
    batch = state_manager.get_batch_state(batch_id)

    if not batch:
        print(f"❌ Batch not found: {batch_id}")
        return False

    if batch.is_complete:
        print(f"✅ Batch already complete")
        return True

    completed = len(batch.completed_players)
    expected = batch.expected_players
    completion_pct = batch.get_completion_percentage()

    print(f"Current Status:")
    print(f"  Progress: {completed}/{expected} ({completion_pct:.1f}%)")
    print(f"  Total Predictions: {batch.total_predictions}")

    if dry_run:
        print(f"\n[DRY RUN] Would mark batch as complete with partial results")
        print(f"  Missing: {expected - completed} players")
        return False

    # Confirm with user
    print(f"\n⚠️  This will mark the batch as complete with partial results.")
    print(f"Missing {expected - completed} players will NOT be processed.")
    response = input("Continue? [y/N]: ")

    if response.lower() != 'y':
        print("Cancelled")
        return False

    # Mark as complete
    print("\nMarking batch as complete...")
    state_manager.mark_batch_complete(batch_id)

    print(f"✅ Batch marked as complete!")
    print(f"\nNext steps:")
    print(f"  1. Trigger consolidation manually if needed")
    print(f"  2. Check for missing players and investigate why they failed")

    return True


def check_stalled_batch(project_id: str, batch_id: str, stall_threshold_minutes: int = 10):
    """
    Check if a batch is stalled and auto-complete if appropriate.

    Args:
        project_id: GCP project ID
        batch_id: Batch identifier
        stall_threshold_minutes: Minutes without progress = stalled
    """
    print(f"=== Checking Batch for Stall: {batch_id} ===\n")

    state_manager = BatchStateManager(project_id)

    # Use the built-in stall check method
    was_completed = state_manager.check_and_complete_stalled_batch(
        batch_id=batch_id,
        stall_threshold_minutes=stall_threshold_minutes,
        min_completion_pct=95.0
    )

    if was_completed:
        print(f"✅ Batch was stalled and has been marked complete")
        print(f"\nNext step: Trigger consolidation")
        print(f"  curl -X POST https://prediction-coordinator-URL/check-stalled \\")
        print(f"       -H 'X-API-Key: YOUR_KEY' \\")
        print(f"       -d '{{\"batch_id\": \"{batch_id}\"}}'")
    else:
        print(f"ℹ️  Batch is not stalled (either still progressing or below 95% completion)")

        # Show current status
        batch = state_manager.get_batch_state(batch_id)
        if batch:
            completed = len(batch.completed_players)
            expected = batch.expected_players
            completion_pct = batch.get_completion_percentage()
            print(f"\nCurrent Status:")
            print(f"  Progress: {completed}/{expected} ({completion_pct:.1f}%)")
            print(f"  Is Complete: {batch.is_complete}")


def main():
    parser = argparse.ArgumentParser(description='Fix stuck prediction coordinator batches')
    parser.add_argument('--project', default='nba-props-platform', help='GCP project ID')

    # Actions
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list-stuck', action='store_true', help='List all stuck batches')
    group.add_argument('--inspect', metavar='BATCH_ID', help='Inspect a specific batch')
    group.add_argument('--force-complete', metavar='BATCH_ID', help='Force-complete a batch')
    group.add_argument('--check-stalled', metavar='BATCH_ID', help='Check if batch is stalled and auto-complete')

    # Options
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back for stuck batches')
    parser.add_argument('--stall-threshold', type=int, default=10, help='Minutes without progress = stalled')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')

    args = parser.parse_args()

    try:
        if args.list_stuck:
            list_stuck_batches(args.project, args.hours)
        elif args.inspect:
            inspect_batch(args.project, args.inspect)
        elif args.force_complete:
            force_complete_batch(args.project, args.force_complete, args.dry_run)
        elif args.check_stalled:
            check_stalled_batch(args.project, args.check_stalled, args.stall_threshold)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
