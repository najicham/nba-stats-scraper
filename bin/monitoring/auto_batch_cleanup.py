#!/usr/bin/env python3
"""
Automated Batch Cleanup with Full Observability (Session 135)

Auto-heals stalled prediction batches while tracking every action for analysis.

Philosophy: "Self-healing with audit trail enables prevention"

Usage:
    python bin/monitoring/auto_batch_cleanup.py

Runs every 15 minutes via Cloud Scheduler to detect and heal stalled batches.

Tracking:
- Every cleanup action logged to Firestore + BigQuery
- Pattern detection alerts if cleanup runs too frequently
- Full state capture (before/after) for root cause analysis

Created: 2026-02-05
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# Add shared to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import firestore
from shared.utils.healing_tracker import HealingTracker
from shared.utils.slack_alerts import send_slack_alert

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")

# Cleanup thresholds
STALL_THRESHOLD_MINUTES = 15  # Batch stalled for 15+ minutes
MIN_COMPLETION_PCT = 90  # Batch at 90%+ completion
MAX_AGE_HOURS = 24  # Don't touch batches older than 24 hours


class BatchCleanupResult:
    """Result of batch cleanup operation."""

    def __init__(
        self,
        batch_id: str,
        was_stalled: bool,
        action_taken: Optional[str] = None,
        before_state: Optional[Dict] = None,
        after_state: Optional[Dict] = None,
        success: bool = False,
        error: Optional[str] = None
    ):
        self.batch_id = batch_id
        self.was_stalled = was_stalled
        self.action_taken = action_taken
        self.before_state = before_state
        self.after_state = after_state
        self.success = success
        self.error = error


def get_stalled_batches(db: firestore.Client) -> List[Dict]:
    """
    Find batches that are stalled and eligible for cleanup.

    A batch is stalled if:
    - Not marked complete
    - Last updated 15+ minutes ago
    - Completion percentage >= 90%
    - Created within last 24 hours

    Args:
        db: Firestore client

    Returns:
        List of batch documents (dicts with id and data)
    """
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=STALL_THRESHOLD_MINUTES)
    min_age = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    batches_ref = db.collection('prediction_batches') \
        .where('is_complete', '==', False) \
        .where('created_at', '>=', min_age)

    stalled = []

    for doc in batches_ref.stream():
        data = doc.to_dict()
        batch_id = doc.id

        # Check if batch is stalled
        updated_at = data.get('updated_at')
        if not updated_at:
            continue

        if updated_at > cutoff_time:
            continue  # Still active

        # Calculate completion percentage
        completed = len(data.get('completed_players', []))
        expected = data.get('expected_players', 0)

        if expected == 0:
            continue

        completion_pct = (completed / expected) * 100

        if completion_pct < MIN_COMPLETION_PCT:
            continue  # Not enough completion

        # This batch is stalled and eligible for cleanup
        stalled.append({
            'id': batch_id,
            'data': data,
            'completed': completed,
            'expected': expected,
            'completion_pct': completion_pct,
            'stall_minutes': (datetime.now(timezone.utc) - updated_at).total_seconds() / 60
        })

        logger.info(
            f"Found stalled batch: {batch_id} "
            f"({completed}/{expected} = {completion_pct:.1f}%, "
            f"stalled {stalled[-1]['stall_minutes']:.1f} min)"
        )

    return stalled


def cleanup_batch(
    db: firestore.Client,
    batch_info: Dict,
    healing_tracker: HealingTracker
) -> BatchCleanupResult:
    """
    Clean up a stalled batch by marking it complete.

    Args:
        db: Firestore client
        batch_info: Batch information from get_stalled_batches
        healing_tracker: Healing event tracker

    Returns:
        BatchCleanupResult with before/after state
    """
    batch_id = batch_info['id']
    data = batch_info['data']

    # Capture before state
    before_state = {
        'batch_id': batch_id,
        'is_complete': data.get('is_complete', False),
        'completed_players': batch_info['completed'],
        'expected_players': batch_info['expected'],
        'completion_pct': batch_info['completion_pct'],
        'stall_minutes': batch_info['stall_minutes'],
        'game_date': data.get('game_date'),
        'created_at': data.get('created_at').isoformat() if data.get('created_at') else None,
        'updated_at': data.get('updated_at').isoformat() if data.get('updated_at') else None
    }

    logger.info(f"Cleaning up stalled batch: {batch_id}")

    try:
        # Mark batch as complete
        doc_ref = db.collection('prediction_batches').document(batch_id)
        doc_ref.update({
            'is_complete': True,
            'completion_time': firestore.SERVER_TIMESTAMP,
            'auto_completed': True,  # Flag to indicate automated cleanup
            'auto_completion_reason': (
                f"Stalled at {batch_info['completion_pct']:.1f}% for "
                f"{batch_info['stall_minutes']:.1f} minutes"
            ),
            'updated_at': firestore.SERVER_TIMESTAMP
        })

        # Capture after state
        after_state = {
            **before_state,
            'is_complete': True,
            'auto_completed': True,
            'completion_time': datetime.now(timezone.utc).isoformat()
        }

        # Record healing event
        trigger_reason = (
            f"Batch {batch_id} stalled at {batch_info['completion_pct']:.1f}% "
            f"({batch_info['completed']}/{batch_info['expected']} players) "
            f"for {batch_info['stall_minutes']:.1f} minutes"
        )

        action_taken = (
            f"Force completed batch {batch_id} "
            f"(game_date={data.get('game_date')})"
        )

        healing_tracker.record_healing(
            healing_type='batch_cleanup',
            trigger_reason=trigger_reason,
            action_taken=action_taken,
            before_state=before_state,
            after_state=after_state,
            success=True,
            metadata={
                'batch_id': batch_id,
                'game_date': data.get('game_date'),
                'stall_duration_minutes': batch_info['stall_minutes'],
                'completion_pct': batch_info['completion_pct'],
                'completed_players': batch_info['completed'],
                'expected_players': batch_info['expected'],
                'missing_players': batch_info['expected'] - batch_info['completed']
            }
        )

        logger.info(
            f"✅ Successfully cleaned up batch {batch_id} "
            f"({batch_info['completed']}/{batch_info['expected']} players)"
        )

        return BatchCleanupResult(
            batch_id=batch_id,
            was_stalled=True,
            action_taken=action_taken,
            before_state=before_state,
            after_state=after_state,
            success=True
        )

    except Exception as e:
        logger.error(f"Failed to cleanup batch {batch_id}: {e}", exc_info=True)

        # Record failed healing attempt
        healing_tracker.record_healing(
            healing_type='batch_cleanup',
            trigger_reason=f"Batch {batch_id} stalled at {batch_info['completion_pct']:.1f}%",
            action_taken=f"Attempted to force complete batch {batch_id}",
            before_state=before_state,
            after_state={},
            success=False,
            metadata={
                'batch_id': batch_id,
                'error': str(e),
                'error_type': type(e).__name__
            }
        )

        return BatchCleanupResult(
            batch_id=batch_id,
            was_stalled=True,
            action_taken=f"Attempted cleanup of {batch_id}",
            before_state=before_state,
            success=False,
            error=str(e)
        )


def send_cleanup_summary(results: List[BatchCleanupResult], healing_tracker: HealingTracker) -> None:
    """
    Send Slack summary of cleanup actions.

    Args:
        results: List of cleanup results
        healing_tracker: Healing tracker for pattern analysis
    """
    cleaned_count = sum(1 for r in results if r.success)
    failed_count = sum(1 for r in results if not r.success)

    if cleaned_count == 0:
        return  # No cleanup performed, no alert needed

    # Check if cleanup is happening too frequently
    pattern_1h = healing_tracker.check_healing_pattern('batch_cleanup', hours=1)
    pattern_24h = healing_tracker.check_healing_pattern('batch_cleanup', hours=24)

    lines = [
        "🩹 *Automated Batch Cleanup Report*",
        ""
    ]

    # Summary
    if cleaned_count > 0:
        lines.append(f"✅ Successfully cleaned up {cleaned_count} stalled batch(es)")

    if failed_count > 0:
        lines.append(f"❌ Failed to clean up {failed_count} batch(es)")

    lines.append("")

    # Details
    lines.append("*Batches Cleaned:*")
    for result in results:
        if result.success:
            before = result.before_state
            lines.append(
                f"• `{result.batch_id}`: {before['completed_players']}/{before['expected_players']} "
                f"({before['completion_pct']:.1f}%), stalled {before['stall_minutes']:.1f} min"
            )

    # Pattern analysis
    lines.append("")
    lines.append("*Cleanup Frequency Analysis:*")
    lines.append(f"• Last hour: {pattern_1h.count} cleanup(s)")
    lines.append(f"• Last 24 hours: {pattern_24h.count} cleanup(s)")

    # Warning if too frequent
    if pattern_1h.should_alert or pattern_24h.should_alert:
        lines.append("")
        lines.append("⚠️ *WARNING: Cleanup running too frequently*")
        lines.append("This indicates a systemic issue causing batches to stall.")
        lines.append("Review healing events to identify root cause:")
        lines.append("```")
        lines.append(
            f"SELECT * FROM nba_orchestration.healing_events "
            f"WHERE healing_type = 'batch_cleanup' "
            f"ORDER BY timestamp DESC LIMIT 20"
        )
        lines.append("```")

    # Root cause hints
    lines.append("")
    lines.append("*Common Stall Causes:*")
    lines.append("• Injured OUT players causing infinite Pub/Sub retries (check worker logs)")
    lines.append("• Worker failures or timeouts")
    lines.append("• Missing feature store data")
    lines.append("• Network issues")

    message = "\n".join(lines)

    # Send to appropriate channel based on frequency
    channel = '#nba-alerts' if pattern_1h.should_alert or pattern_24h.should_alert else '#nba-alerts'

    send_slack_alert(
        message=message,
        channel=channel,
        alert_type="BATCH_CLEANUP_AUTO"
    )


def main():
    """Main entry point."""
    logger.info("Starting automated batch cleanup")

    db = firestore.Client(project=PROJECT_ID)
    healing_tracker = HealingTracker(project_id=PROJECT_ID)

    # Find stalled batches
    stalled_batches = get_stalled_batches(db)

    if not stalled_batches:
        logger.info("No stalled batches found - system healthy")
        return 0

    logger.info(f"Found {len(stalled_batches)} stalled batch(es)")

    # Clean up each stalled batch
    results = []
    for batch_info in stalled_batches:
        result = cleanup_batch(db, batch_info, healing_tracker)
        results.append(result)

    # Send summary
    send_cleanup_summary(results, healing_tracker)

    # Return error code if any cleanups failed
    failed_count = sum(1 for r in results if not r.success)
    if failed_count > 0:
        logger.error(f"Failed to clean up {failed_count} batch(es)")
        return 1

    logger.info(f"Successfully cleaned up {len(results)} batch(es)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
