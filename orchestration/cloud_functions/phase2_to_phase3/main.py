"""
Phase 2 → Phase 3 Orchestrator

Cloud Function that tracks Phase 2 processor completion and triggers Phase 3 when all complete.

Architecture:
- Listens to: nba-phase2-raw-complete (21 Phase 2 processors publish here)
- Tracks state in: Firestore collection 'phase2_completion/{game_date}'
- Publishes to: nba-phase3-trigger (when all 21 complete)

Critical Features:
- Atomic Firestore transactions (prevent race conditions when processors complete simultaneously)
- Idempotency (handles duplicate Pub/Sub messages)
- Deduplication marker (_triggered flag prevents double-trigger)
- Correlation ID preservation (traces back to original scraper run)

Race Condition Prevention (Critical Fix 1.1):
Without transactions:
  - Processor A completes, reads Firestore (4/5 complete)
  - Processor B completes, reads Firestore (4/5 complete)
  - Both increment to 5/5 and trigger Phase 3 (DUPLICATE!)

With transactions:
  - Firestore transaction ensures atomic read-modify-write
  - Only ONE processor successfully marks _triggered=True
  - Safe even with 21 simultaneous completions

Version: 1.0
Created: 2025-11-29
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

from google.cloud import firestore, pubsub_v1
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
EXPECTED_PROCESSORS = 21  # Phase 2 has 21 raw processors
PHASE3_TRIGGER_TOPIC = 'nba-phase3-trigger'

# Initialize clients (reused across invocations)
db = firestore.Client()
publisher = pubsub_v1.PublisherClient()


@functions_framework.cloud_event
def orchestrate_phase2_to_phase3(cloud_event):
    """
    Handle Phase 2 completion events and trigger Phase 3 when all processors complete.

    Triggered by: Pub/Sub messages to nba-phase2-raw-complete

    Message format (unified):
    {
        "processor_name": "BdlGamesProcessor",
        "phase": "phase_2_raw",
        "execution_id": "def-456",
        "correlation_id": "abc-123",
        "game_date": "2025-11-29",
        "output_table": "bdl_games",
        "output_dataset": "nba_raw",
        "status": "success",
        "record_count": 150,
        "timestamp": "2025-11-29T12:00:00Z",
        ...
    }

    Args:
        cloud_event: CloudEvent from Pub/Sub containing Phase 2 completion data
    """
    try:
        # Parse Pub/Sub message
        message_data = parse_pubsub_message(cloud_event)

        # Extract key fields
        game_date = message_data.get('game_date')
        processor_name = message_data.get('processor_name')
        correlation_id = message_data.get('correlation_id')
        status = message_data.get('status')

        # Validate required fields
        if not game_date or not processor_name:
            logger.error(f"Missing required fields in message: {message_data}")
            return

        # Skip non-success statuses (only track successful completions)
        if status not in ('success', 'partial'):
            logger.info(f"Skipping {processor_name} with status '{status}' (only track success/partial)")
            return

        logger.info(
            f"Received completion from {processor_name} for {game_date} "
            f"(status={status}, correlation_id={correlation_id})"
        )

        # Update completion state with atomic transaction
        doc_ref = db.collection('phase2_completion').document(game_date)

        # Create transaction and execute atomic update
        transaction = db.transaction()
        should_trigger = update_completion_atomic(
            transaction,
            doc_ref,
            processor_name,
            {
                'completed_at': firestore.SERVER_TIMESTAMP,
                'correlation_id': correlation_id,
                'status': status,
                'record_count': message_data.get('record_count', 0),
                'execution_id': message_data.get('execution_id')
            }
        )

        if should_trigger:
            # All processors complete - trigger Phase 3
            trigger_phase3(game_date, correlation_id, message_data)
            logger.info(
                f"✅ All {EXPECTED_PROCESSORS} Phase 2 processors complete for {game_date}, "
                f"triggered Phase 3 (correlation_id={correlation_id})"
            )
        else:
            # Still waiting for more processors
            logger.info(f"Registered completion for {processor_name}, waiting for others")

    except Exception as e:
        logger.error(f"Error in Phase 2→3 orchestrator: {e}", exc_info=True)
        # Don't raise - let Pub/Sub retry if transient, or drop if permanent


@firestore.transactional
def update_completion_atomic(transaction: firestore.Transaction, doc_ref, processor_name: str, completion_data: Dict) -> bool:
    """
    Atomically update processor completion and determine if should trigger next phase.

    This function uses Firestore transactions to prevent race conditions when multiple
    processors complete simultaneously. The @firestore.transactional decorator ensures
    atomic read-modify-write operations.

    Transaction flow:
    1. Read current state (locked)
    2. Check if processor already registered (idempotency)
    3. Add processor completion data
    4. Count total completions
    5. If all complete AND not yet triggered → mark triggered and return True
    6. Write atomically (released lock)

    Args:
        transaction: Firestore transaction object
        doc_ref: Firestore document reference for this game_date
        processor_name: Name of completing processor (e.g., "BdlGamesProcessor")
        completion_data: Completion metadata (timestamp, correlation_id, status, etc.)

    Returns:
        bool: True if this update completes the phase and should trigger Phase 3

    Critical Fix 1.1: Race Condition Prevention
    -----------------------------------------
    Without transactions, this scenario breaks:
        11:45 PM - Processor A reads (20/21 complete), increments to 21
        11:45 PM - Processor B reads (20/21 complete), increments to 21
        → Both trigger Phase 3 (duplicate)

    With transactions:
        11:45 PM - Processor A transaction locks doc, reads (20/21), writes (21/21, triggered=True)
        11:45 PM - Processor B transaction waits, then reads (21/21, triggered=True), sees already triggered
        → Only ONE trigger published
    """
    # Read current state within transaction (locked)
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Idempotency check: skip if this processor already registered
    if processor_name in current:
        logger.debug(f"Processor {processor_name} already registered (duplicate Pub/Sub message)")
        return False

    # Add this processor's completion data
    current[processor_name] = completion_data

    # Count completed processors (exclude metadata fields starting with _)
    completed_count = len([k for k in current.keys() if not k.startswith('_')])

    # Check if this completes the phase AND hasn't been triggered yet
    if completed_count >= EXPECTED_PROCESSORS and not current.get('_triggered'):
        # Mark as triggered to prevent duplicate triggers (double safety)
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_completed_count'] = completed_count

        # Write atomically
        transaction.set(doc_ref, current)

        return True  # Trigger Phase 3
    else:
        # Not yet complete, or already triggered
        current['_completed_count'] = completed_count

        # Write atomically
        transaction.set(doc_ref, current)

        return False  # Don't trigger


def trigger_phase3(game_date: str, correlation_id: str, upstream_message: Dict) -> Optional[str]:
    """
    Publish message to trigger Phase 3 analytics processing.

    Message published to: nba-phase3-trigger

    Message format:
    {
        "game_date": "2025-11-29",
        "correlation_id": "abc-123",
        "trigger_source": "orchestrator",
        "triggered_by": "phase2_to_phase3_orchestrator",
        "upstream_processors_count": 21,
        "timestamp": "2025-11-29T12:30:00Z"
    }

    Args:
        game_date: Date that was processed
        correlation_id: Original correlation ID from scraper run
        upstream_message: Original Phase 2 completion message (for metadata)

    Returns:
        Message ID if published successfully, None if failed
    """
    try:
        topic_path = publisher.topic_path(PROJECT_ID, PHASE3_TRIGGER_TOPIC)

        # Build trigger message
        message = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase2_to_phase3_orchestrator',
            'upstream_processors_count': EXPECTED_PROCESSORS,
            'timestamp': datetime.now(timezone.utc).isoformat(),

            # Optional metadata from upstream
            'parent_execution_id': upstream_message.get('execution_id'),
            'parent_processor': 'Phase2Orchestrator'
        }

        # Publish to Pub/Sub
        future = publisher.publish(
            topic_path,
            data=json.dumps(message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)  # Wait up to 10 seconds

        logger.info(f"Published Phase 3 trigger: message_id={message_id}, game_date={game_date}")
        return message_id

    except Exception as e:
        logger.error(f"Failed to publish Phase 3 trigger for {game_date}: {e}", exc_info=True)
        # This is critical - if we can't trigger Phase 3, alert
        # (In production, would send alert here)
        return None


def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

    Handles base64 decoding and JSON parsing.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dictionary with message data

    Raises:
        ValueError: If message cannot be parsed
    """
    try:
        # Get message data from CloudEvent
        pubsub_message = cloud_event.data.get('message', {})

        # Decode base64 data
        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
        else:
            raise ValueError("No data field in Pub/Sub message")

        return message_data

    except Exception as e:
        logger.error(f"Failed to parse Pub/Sub message: {e}")
        raise ValueError(f"Invalid Pub/Sub message format: {e}")


# ============================================================================
# HELPER FUNCTIONS (for debugging and monitoring)
# ============================================================================

def get_completion_status(game_date: str) -> Dict:
    """
    Get current completion status for a game_date (for debugging).

    Args:
        game_date: Date to check

    Returns:
        Dictionary with completion status
    """
    doc_ref = db.collection('phase2_completion').document(game_date)
    doc = doc_ref.get()

    if not doc.exists:
        return {
            'game_date': game_date,
            'status': 'not_started',
            'completed_count': 0,
            'expected_count': EXPECTED_PROCESSORS
        }

    data = doc.to_dict()
    completed_count = len([k for k in data.keys() if not k.startswith('_')])

    return {
        'game_date': game_date,
        'status': 'triggered' if data.get('_triggered') else 'in_progress',
        'completed_count': completed_count,
        'expected_count': EXPECTED_PROCESSORS,
        'completed_processors': [k for k in data.keys() if not k.startswith('_')],
        'triggered_at': data.get('_triggered_at')
    }


# For local testing
if __name__ == '__main__':
    # Example: Check status for a date
    import sys
    if len(sys.argv) > 1:
        game_date = sys.argv[1]
        status = get_completion_status(game_date)
        print(json.dumps(status, indent=2, default=str))
    else:
        print("Usage: python main.py <game_date>")
        print("Example: python main.py 2025-11-29")
