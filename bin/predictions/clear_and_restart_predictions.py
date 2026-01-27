#!/usr/bin/env python3
"""
Clear stuck batch and restart predictions

This script:
1. Marks a stuck batch as complete (so it doesn't block new batches)
2. Optionally triggers a new prediction batch

Usage:
    # Just clear the stuck batch
    python bin/predictions/clear_and_restart_predictions.py --batch-id batch_2026-01-28_1769555415

    # Clear and restart for the same game_date
    python bin/predictions/clear_and_restart_predictions.py --batch-id batch_2026-01-28_1769555415 --restart

Created: 2026-01-27
"""

import argparse
import os
import sys
import requests
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from predictions.coordinator.batch_state_manager import BatchStateManager


def clear_stuck_batch(project_id: str, batch_id: str):
    """
    Mark a stuck batch as complete so it doesn't block new batches.

    Args:
        project_id: GCP project ID
        batch_id: Batch identifier
    """
    print(f"=== Clearing Stuck Batch: {batch_id} ===\n")

    state_manager = BatchStateManager(project_id)
    batch = state_manager.get_batch_state(batch_id)

    if not batch:
        print(f"❌ Batch not found: {batch_id}")
        return None

    if batch.is_complete:
        print(f"✅ Batch already complete")
        return batch

    completed = len(batch.completed_players)
    expected = batch.expected_players
    completion_pct = batch.get_completion_percentage()

    print(f"Current Status:")
    print(f"  Progress: {completed}/{expected} ({completion_pct:.1f}%)")
    print(f"  Total Predictions: {batch.total_predictions}")
    print(f"  Game Date: {batch.game_date}")

    # Mark as complete with failure flag
    print("\nMarking batch as complete (failed)...")

    from google.cloud.firestore import SERVER_TIMESTAMP
    doc_ref = state_manager.collection.document(batch_id)
    doc_ref.update({
        'is_complete': True,
        'completion_time': SERVER_TIMESTAMP,
        'updated_at': SERVER_TIMESTAMP,
        'manual_clear': True,
        'clear_reason': 'Stuck with 0 predictions generated - manually cleared'
    })

    print(f"✅ Batch marked as complete (failed)")
    return batch


def restart_predictions(coordinator_url: str, api_key: str, game_date: str):
    """
    Trigger a new prediction batch via coordinator API.

    Args:
        coordinator_url: Base URL of coordinator service
        api_key: API key for authentication
        game_date: Game date to generate predictions for (YYYY-MM-DD)
    """
    print(f"\n=== Restarting Predictions for {game_date} ===\n")

    # Call /start endpoint
    start_url = f"{coordinator_url}/start"
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }

    payload = {
        'game_date': game_date,
        'force': True,  # Force restart even if batch exists
        'skip_completeness_check': True  # Skip data completeness check (emergency mode)
    }

    print(f"Calling {start_url}...")
    print(f"Payload: {payload}")

    try:
        response = requests.post(
            start_url,
            json=payload,
            headers=headers,
            timeout=300  # 5 minute timeout
        )

        print(f"Response Status: {response.status_code}")
        print(f"Response: {response.text}")

        if response.status_code == 202:
            print("\n✅ Prediction batch started successfully!")
            data = response.json()
            print(f"Batch ID: {data.get('batch_id')}")
            print(f"Total Requests: {data.get('total_requests')}")
            print(f"Published: {data.get('published')}")
            return True
        else:
            print(f"\n❌ Failed to start batch: {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("\n⚠️  Request timed out (5 minutes)")
        print("This likely means the coordinator is still loading historical data.")
        print("The batch may have been created but requests not published yet.")
        return False
    except Exception as e:
        print(f"\n❌ Error calling coordinator: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Clear stuck batch and restart predictions')
    parser.add_argument('--batch-id', required=True, help='Batch ID to clear')
    parser.add_argument('--project', default='nba-props-platform', help='GCP project ID')
    parser.add_argument('--restart', action='store_true', help='Restart predictions after clearing')
    parser.add_argument('--coordinator-url',
                       default='https://prediction-coordinator-969772464058.us-west2.run.app',
                       help='Coordinator service URL')
    parser.add_argument('--api-key',
                       help='Coordinator API key (or set COORDINATOR_API_KEY env var)')

    args = parser.parse_args()

    # Get API key
    api_key = args.api_key or os.environ.get('COORDINATOR_API_KEY')
    if args.restart and not api_key:
        print("❌ API key required for restart. Set --api-key or COORDINATOR_API_KEY env var")
        sys.exit(1)

    # Step 1: Clear stuck batch
    batch = clear_stuck_batch(args.project, args.batch_id)
    if not batch:
        sys.exit(1)

    # Step 2: Restart predictions if requested
    if args.restart:
        success = restart_predictions(args.coordinator_url, api_key, batch.game_date)
        sys.exit(0 if success else 1)
    else:
        print("\nBatch cleared. Use --restart to trigger new predictions.")


if __name__ == '__main__':
    main()
