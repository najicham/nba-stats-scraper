"""
MLB Phase 3 → Phase 4 Orchestrator

Cloud Function that tracks MLB Phase 3 processor completion and triggers Phase 4 when all complete.

Architecture:
- Listens to: mlb-phase3-analytics-complete (Phase 3 processors publish here)
- Tracks state in: Firestore collection 'mlb_phase3_completion/{game_date}'
- Publishes to: mlb-phase4-trigger (when all expected processors complete)

MLB Phase 3 Processors:
- pitcher_game_summary
- batter_game_summary

Created: 2026-01-08
"""

import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from google.cloud import firestore, pubsub_v1
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
PHASE4_TRIGGER_TOPIC = 'mlb-phase4-trigger'

# MLB Phase 3 expected processors
EXPECTED_PROCESSORS: List[str] = [
    'pitcher_game_summary',
    'batter_game_summary',
]
EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)

# Initialize clients (reused across invocations)
db = firestore.Client()
publisher = pubsub_v1.PublisherClient()


def normalize_processor_name(raw_name: str, output_table: Optional[str] = None) -> str:
    """
    Normalize processor name to match config format.

    Args:
        raw_name: Raw processor name from message
        output_table: Optional output_table field from message

    Returns:
        Normalized processor name matching config
    """
    # If raw_name is already in expected set, use it
    if raw_name in EXPECTED_PROCESSOR_SET:
        return raw_name

    # If output_table matches expected, use it
    if output_table and output_table in EXPECTED_PROCESSOR_SET:
        return output_table

    # Convert CamelCase to snake_case and strip "Processor" suffix
    name = raw_name.replace('Processor', '').replace('Mlb', '')
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    return name


def parse_pubsub_message(cloud_event) -> Dict:
    """Parse Pub/Sub message from CloudEvent."""
    message_data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    return json.loads(message_data)


@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name: str, completion_data: Dict) -> bool:
    """
    Atomically update completion state and check if we should trigger Phase 4.

    Args:
        transaction: Firestore transaction
        doc_ref: Document reference for this game_date
        processor_name: Normalized processor name
        completion_data: Data to store for this processor

    Returns:
        True if we should trigger Phase 4 (all processors complete AND not already triggered)
    """
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Idempotency check - already registered this processor?
    if processor_name in current:
        logger.info(f"Processor {processor_name} already registered (idempotent)")
        return False

    # Add this processor's completion
    current[processor_name] = completion_data

    # Count completed processors (exclude underscore-prefixed metadata fields)
    completed_count = len([k for k in current.keys() if not k.startswith('_')])

    # Check if we should trigger Phase 4
    should_trigger = False
    if completed_count >= EXPECTED_PROCESSOR_COUNT and not current.get('_triggered'):
        # All processors complete and not yet triggered
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_completed_count'] = completed_count
        should_trigger = True
        logger.info(f"All {EXPECTED_PROCESSOR_COUNT} MLB Phase 3 processors complete - will trigger Phase 4")
    else:
        current['_completed_count'] = completed_count

    # Write update
    transaction.set(doc_ref, current)

    return should_trigger


def trigger_phase4(game_date: str, correlation_id: str, doc_ref):
    """Publish message to trigger MLB Phase 4."""
    topic_path = publisher.topic_path(PROJECT_ID, PHASE4_TRIGGER_TOPIC)

    message = {
        'game_date': game_date,
        'correlation_id': correlation_id,
        'trigger_source': 'orchestrator',
        'triggered_by': 'mlb_phase3_to_phase4_orchestrator',
        'upstream_processors_count': EXPECTED_PROCESSOR_COUNT,
        'expected_processors': EXPECTED_PROCESSORS,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'sport': 'mlb'
    }

    future = publisher.publish(topic_path, data=json.dumps(message).encode('utf-8'))
    message_id = future.result(timeout=30)

    logger.info(f"Published MLB Phase 4 trigger: message_id={message_id}, game_date={game_date}")

    # Update doc with trigger details
    doc_ref.update({
        '_trigger_message_id': message_id,
        '_trigger_timestamp': datetime.now(timezone.utc).isoformat()
    })


@functions_framework.cloud_event
def orchestrate_mlb_phase3_to_phase4(cloud_event):
    """
    Handle MLB Phase 3 completion events and trigger Phase 4 when all processors complete.

    Triggered by: Pub/Sub messages to mlb-phase3-analytics-complete
    """
    try:
        message_data = parse_pubsub_message(cloud_event)

        game_date = message_data.get('game_date')
        raw_processor_name = message_data.get('processor_name', '')
        output_table = message_data.get('output_table')
        correlation_id = message_data.get('correlation_id', 'unknown')
        status = message_data.get('status', 'unknown')

        if not game_date:
            logger.warning("Missing game_date in message")
            return

        # Normalize processor name
        processor_name = normalize_processor_name(raw_processor_name, output_table)

        if processor_name not in EXPECTED_PROCESSOR_SET:
            logger.info(f"Ignoring unexpected processor: {processor_name} (raw: {raw_processor_name})")
            return

        if status != 'success':
            logger.warning(f"Processor {processor_name} did not succeed: {status}")
            # Still track it but note the status

        logger.info(f"MLB Phase 3 complete: processor={processor_name}, game_date={game_date}, status={status}")

        # Build completion data
        completion_data = {
            'processor_name': processor_name,
            'raw_processor_name': raw_processor_name,
            'correlation_id': correlation_id,
            'status': status,
            'completed_at': firestore.SERVER_TIMESTAMP,
            'record_count': message_data.get('record_count', 0),
            'execution_id': message_data.get('execution_id'),
        }

        # Get Firestore document reference
        doc_ref = db.collection('mlb_phase3_completion').document(game_date)

        # Atomic update with transaction
        transaction = db.transaction()
        should_trigger = update_completion_atomic(transaction, doc_ref, processor_name, completion_data)

        if should_trigger:
            trigger_phase4(game_date, correlation_id, doc_ref)

    except Exception as e:
        logger.error(f"Error in MLB Phase 3→4 orchestrator: {e}", exc_info=True)
        raise


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'function': 'mlb_phase3_to_phase4',
        'expected_processors': EXPECTED_PROCESSORS,
        'sport': 'mlb'
    }, 200
