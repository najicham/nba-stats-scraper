"""
Phase 4 → Phase 5 Orchestrator

Cloud Function that tracks Phase 4 processor completion and triggers Phase 5 (predictions) when all complete.

Architecture:
- Listens to: nba-phase4-precompute-complete (Phase 4 processors publish here)
- Tracks state in: Firestore collection 'phase4_completion/{game_date}'
- Triggers: Prediction coordinator /start endpoint directly

NOTE: Phase 4 processors publish to nba-phase4-precompute-complete (not nba-phase4-processor-complete).
The processor_name field contains the class name (e.g., MLFeatureStoreProcessor) or output_table
contains the table name (e.g., ml_feature_store_v2). We normalize both to match config.

Critical Features:
- Atomic Firestore transactions (prevent race conditions)
- Idempotency (handles duplicate Pub/Sub messages)
- Deduplication marker (_triggered flag prevents double-trigger)
- Correlation ID preservation (traces back to original scraper run)
- Centralized config: Expected processors loaded from orchestration_config.py

Phase 4 Processors:
- team_defense_zone_analysis
- player_shot_zone_analysis
- player_composite_factors
- player_daily_cache
- ml_feature_store

Version: 1.0
Created: 2025-12-02
"""

import base64
import json
import logging
import os
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from google.cloud import firestore, pubsub_v1
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
PHASE5_TRIGGER_TOPIC = 'nba-predictions-trigger'  # Downstream topic for predictions
MAX_WAIT_HOURS = 4  # Maximum hours to wait for all processors before timeout
MAX_WAIT_SECONDS = MAX_WAIT_HOURS * 3600

# Processor name normalization - maps various formats to config names
# Phase 4 processors publish class names or table names, but config uses simple names
PROCESSOR_NAME_MAPPING = {
    # Class name -> config name
    'TeamDefenseZoneAnalysisProcessor': 'team_defense_zone_analysis',
    'PlayerShotZoneAnalysisProcessor': 'player_shot_zone_analysis',
    'PlayerCompositeFactorsProcessor': 'player_composite_factors',
    'PlayerDailyCacheProcessor': 'player_daily_cache',
    'MLFeatureStoreProcessor': 'ml_feature_store',
    # Table name variants -> config name
    'team_defense_zone_analysis': 'team_defense_zone_analysis',
    'player_shot_zone_analysis': 'player_shot_zone_analysis',
    'player_composite_factors': 'player_composite_factors',
    'player_daily_cache': 'player_daily_cache',
    'ml_feature_store': 'ml_feature_store',
    'ml_feature_store_v2': 'ml_feature_store',  # v2 suffix
}
PREDICTION_COORDINATOR_URL = os.environ.get(
    'PREDICTION_COORDINATOR_URL',
    'https://prediction-coordinator-756957797294.us-west2.run.app'
)

# Import expected processors from centralized config
try:
    from shared.config.orchestration_config import get_orchestration_config
    _config = get_orchestration_config()
    EXPECTED_PROCESSORS: List[str] = _config.phase_transitions.phase4_expected_processors
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)
    logger.info(f"Loaded {EXPECTED_PROCESSOR_COUNT} expected Phase 4 processors from config")
except ImportError:
    # Fallback for Cloud Functions where shared module may not be available
    logger.warning("Could not import orchestration_config, using fallback list")
    EXPECTED_PROCESSORS: List[str] = [
        'team_defense_zone_analysis',
        'player_shot_zone_analysis',
        'player_composite_factors',
        'player_daily_cache',
        'ml_feature_store',
    ]
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)

# Initialize clients (reused across invocations)
db = firestore.Client()
publisher = pubsub_v1.PublisherClient()


def normalize_processor_name(raw_name: str, output_table: Optional[str] = None) -> str:
    """
    Normalize processor name to match config format.

    Phase 4 processors may publish:
    - Class names: MLFeatureStoreProcessor
    - Table names: ml_feature_store_v2

    This function normalizes to config format: ml_feature_store

    Args:
        raw_name: Raw processor name from message
        output_table: Optional output_table field from message

    Returns:
        Normalized processor name matching config
    """
    # Try direct mapping first
    if raw_name in PROCESSOR_NAME_MAPPING:
        return PROCESSOR_NAME_MAPPING[raw_name]

    # Try output_table if provided
    if output_table and output_table in PROCESSOR_NAME_MAPPING:
        return PROCESSOR_NAME_MAPPING[output_table]

    # Fallback: convert CamelCase to snake_case and strip "Processor" suffix
    import re
    name = raw_name.replace('Processor', '')
    # Insert underscore before capitals and lowercase
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    logger.debug(f"Normalized '{raw_name}' -> '{name}'")
    return name


@functions_framework.cloud_event
def orchestrate_phase4_to_phase5(cloud_event):
    """
    Handle Phase 4 completion events and trigger Phase 5 when all processors complete.

    Triggered by: Pub/Sub messages to nba-phase4-precompute-complete

    Message format:
    {
        "processor_name": "MLFeatureStoreProcessor",  # Class name
        "phase": "phase_4_precompute",
        "execution_id": "def-456",
        "correlation_id": "abc-123",
        "game_date": "2025-11-29",
        "output_table": "ml_feature_store_v2",  # Table name
        "output_dataset": "nba_precompute",
        "status": "success",
        "record_count": 450,
        ...
    }

    Args:
        cloud_event: CloudEvent from Pub/Sub containing Phase 4 completion data
    """
    try:
        # Parse Pub/Sub message
        message_data = parse_pubsub_message(cloud_event)

        # Extract key fields
        game_date = message_data.get('game_date')
        raw_processor_name = message_data.get('processor_name')
        output_table = message_data.get('output_table')
        correlation_id = message_data.get('correlation_id')
        status = message_data.get('status')

        # Validate required fields
        if not game_date or not raw_processor_name:
            logger.error(f"Missing required fields in message: {message_data}")
            return

        # Normalize processor name to match config
        processor_name = normalize_processor_name(raw_processor_name, output_table)

        # Skip non-success statuses (only track successful completions)
        if status not in ('success', 'partial'):
            logger.info(f"Skipping {processor_name} with status '{status}' (only track success/partial)")
            return

        logger.info(
            f"Received completion from {processor_name} (raw: {raw_processor_name}) for {game_date} "
            f"(status={status}, correlation_id={correlation_id})"
        )

        # Update completion state with atomic transaction
        doc_ref = db.collection('phase4_completion').document(game_date)

        # Create transaction and execute atomic update
        transaction = db.transaction()
        should_trigger, trigger_reason, missing = update_completion_atomic(
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
            if trigger_reason == 'all_complete':
                # All processors complete - trigger Phase 5 (predictions)
                trigger_phase5(game_date, correlation_id, message_data)
                logger.info(
                    f"✅ All {EXPECTED_PROCESSOR_COUNT} Phase 4 processors complete for {game_date}, "
                    f"triggered Phase 5 predictions (correlation_id={correlation_id})"
                )
            elif trigger_reason == 'timeout':
                # Timeout reached - trigger with partial data
                trigger_phase5(game_date, correlation_id, message_data)
                logger.warning(
                    f"⚠️ TIMEOUT: Triggering Phase 5 for {game_date} with partial data. "
                    f"Missing processors: {missing}"
                )
        elif trigger_reason == 'waiting':
            # Still waiting for more processors
            logger.info(f"Registered completion for {processor_name}, waiting for {len(missing)} more: {missing}")

    except Exception as e:
        logger.error(f"Error in Phase 4→5 orchestrator: {e}", exc_info=True)


@firestore.transactional
def update_completion_atomic(transaction: firestore.Transaction, doc_ref, processor_name: str, completion_data: Dict) -> tuple:
    """
    Atomically update processor completion and determine if should trigger next phase.

    This function uses Firestore transactions to prevent race conditions when multiple
    processors complete simultaneously.

    Args:
        transaction: Firestore transaction object
        doc_ref: Firestore document reference for this game_date
        processor_name: Name of completing processor
        completion_data: Completion metadata

    Returns:
        tuple: (should_trigger: bool, trigger_reason: str, missing_processors: list)
    """
    # Read current state within transaction (locked)
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Idempotency check: skip if this processor already registered
    if processor_name in current:
        logger.debug(f"Processor {processor_name} already registered (duplicate Pub/Sub message)")
        return (False, 'duplicate', [])

    # Already triggered - don't trigger again
    if current.get('_triggered'):
        return (False, 'already_triggered', [])

    # Add this processor's completion data
    current[processor_name] = completion_data

    # Track when first processor completed (for timeout calculation)
    now = datetime.now(timezone.utc)
    if '_first_completion_at' not in current:
        current['_first_completion_at'] = now.isoformat()

    # Count completed processors (exclude metadata fields starting with _)
    completed_processors = [k for k in current.keys() if not k.startswith('_')]
    completed_count = len(completed_processors)
    missing_processors = list(EXPECTED_PROCESSOR_SET - set(completed_processors))

    # Check if this completes the phase
    if completed_count >= EXPECTED_PROCESSOR_COUNT:
        # Mark as triggered to prevent duplicate triggers
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_completed_count'] = completed_count
        current['_trigger_reason'] = 'all_complete'

        # Write atomically
        transaction.set(doc_ref, current)

        return (True, 'all_complete', [])

    # Check for timeout - trigger with partial completion
    first_completion_str = current.get('_first_completion_at')
    if first_completion_str:
        first_completion = datetime.fromisoformat(first_completion_str.replace('Z', '+00:00'))
        wait_seconds = (now - first_completion).total_seconds()

        if wait_seconds > MAX_WAIT_SECONDS:
            logger.warning(
                f"TIMEOUT: Waited {wait_seconds/3600:.1f} hours for Phase 4 completion. "
                f"Got {completed_count}/{EXPECTED_PROCESSOR_COUNT} processors. "
                f"Missing: {missing_processors}. Triggering Phase 5 anyway."
            )

            # Mark as triggered with timeout reason
            current['_triggered'] = True
            current['_triggered_at'] = firestore.SERVER_TIMESTAMP
            current['_completed_count'] = completed_count
            current['_trigger_reason'] = 'timeout'
            current['_missing_processors'] = missing_processors
            current['_wait_seconds'] = wait_seconds

            # Write atomically
            transaction.set(doc_ref, current)

            return (True, 'timeout', missing_processors)

    # Not yet complete, update state
    current['_completed_count'] = completed_count

    # Write atomically
    transaction.set(doc_ref, current)

    return (False, 'waiting', missing_processors)


def trigger_phase5(game_date: str, correlation_id: str, upstream_message: Dict) -> Optional[str]:
    """
    Trigger Phase 5 predictions when Phase 4 is complete.

    Does two things:
    1. Publishes message to nba-phase4-precompute-complete topic
    2. Calls prediction coordinator /start endpoint directly

    Args:
        game_date: Date that was processed
        correlation_id: Original correlation ID from scraper run
        upstream_message: Original Phase 4 completion message

    Returns:
        Message ID if published successfully, None if failed
    """
    try:
        topic_path = publisher.topic_path(PROJECT_ID, PHASE5_TRIGGER_TOPIC)

        # Build trigger message
        message = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase4_to_phase5_orchestrator',
            'upstream_processors_count': EXPECTED_PROCESSOR_COUNT,
            'expected_processors': EXPECTED_PROCESSORS,
            'timestamp': datetime.now(timezone.utc).isoformat(),

            # Optional metadata from upstream
            'parent_execution_id': upstream_message.get('execution_id'),
            'parent_processor': 'Phase4Orchestrator'
        }

        # Publish to Pub/Sub
        future = publisher.publish(
            topic_path,
            data=json.dumps(message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(
            f"Published Phase 5 trigger: message_id={message_id}, game_date={game_date}"
        )

        # Also call prediction coordinator directly (HTTP trigger)
        try:
            trigger_prediction_coordinator(game_date, correlation_id)
        except Exception as e:
            logger.warning(f"Failed to trigger prediction coordinator via HTTP: {e}")
            # Don't fail - Pub/Sub message was sent, coordinator can pick it up

        return message_id

    except Exception as e:
        logger.error(f"Failed to publish Phase 5 trigger for {game_date}: {e}", exc_info=True)
        return None


def trigger_prediction_coordinator(game_date: str, correlation_id: str) -> None:
    """
    Trigger the prediction coordinator via HTTP.

    The coordinator has a /start endpoint that accepts game_date.

    Args:
        game_date: Date to generate predictions for
        correlation_id: Correlation ID for tracing
    """
    try:
        url = f"{PREDICTION_COORDINATOR_URL}/start"

        payload = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'phase4_orchestrator'
        }

        # Get identity token for Cloud Run authentication
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token

            auth_req = google.auth.transport.requests.Request()
            id_token = google.oauth2.id_token.fetch_id_token(auth_req, PREDICTION_COORDINATOR_URL)
            headers = {
                'Authorization': f'Bearer {id_token}',
                'Content-Type': 'application/json'
            }
        except Exception as e:
            logger.warning(f"Could not get ID token: {e}, trying without auth")
            headers = {'Content-Type': 'application/json'}

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            logger.info(f"Successfully triggered prediction coordinator for {game_date}")
        else:
            logger.warning(
                f"Prediction coordinator returned {response.status_code}: {response.text[:200]}"
            )

    except Exception as e:
        logger.error(f"Error triggering prediction coordinator: {e}")
        raise


def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

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
    doc_ref = db.collection('phase4_completion').document(game_date)
    doc = doc_ref.get()

    if not doc.exists:
        return {
            'game_date': game_date,
            'status': 'not_started',
            'completed_count': 0,
            'expected_count': EXPECTED_PROCESSOR_COUNT,
            'expected_processors': EXPECTED_PROCESSORS
        }

    data = doc.to_dict()
    completed_processors = [k for k in data.keys() if not k.startswith('_')]
    completed_count = len(completed_processors)

    # Find missing processors
    missing_processors = list(EXPECTED_PROCESSOR_SET - set(completed_processors))

    return {
        'game_date': game_date,
        'status': 'triggered' if data.get('_triggered') else 'in_progress',
        'completed_count': completed_count,
        'expected_count': EXPECTED_PROCESSOR_COUNT,
        'completed_processors': completed_processors,
        'missing_processors': missing_processors,
        'triggered_at': data.get('_triggered_at')
    }


# For local testing
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        game_date = sys.argv[1]
        status = get_completion_status(game_date)
        print(json.dumps(status, indent=2, default=str))
    else:
        print("Usage: python main.py <game_date>")
        print("Example: python main.py 2025-11-29")
