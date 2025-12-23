"""
Phase 2 → Phase 3 Orchestrator (Monitoring Mode)

Cloud Function that tracks Phase 2 processor completion for observability.

NOTE: This orchestrator is now MONITORING-ONLY. Phase 3 is triggered directly
via Pub/Sub subscription (nba-phase3-analytics-sub), not by this orchestrator.
The nba-phase3-trigger topic has no subscribers.

Architecture:
- Listens to: nba-phase2-raw-complete (Phase 2 processors publish here)
- Tracks state in: Firestore collection 'phase2_completion/{game_date}'
- NO LONGER publishes to nba-phase3-trigger (vestigial, no subscribers)

Purpose:
- Track which processors complete each day (observability)
- Provide completion status via HTTP endpoint
- Enable debugging of pipeline issues

Critical Features:
- Atomic Firestore transactions (prevent race conditions)
- Idempotency (handles duplicate Pub/Sub messages)
- Correlation ID preservation (traces back to original scraper run)

Version: 2.0 - Monitoring-only mode (no longer triggers Phase 3)
Created: 2025-11-29
Updated: 2025-12-23
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from google.cloud import firestore
import functions_framework

# Configure logging - use structured logging for Cloud Run
import google.cloud.logging
try:
    client = google.cloud.logging.Client()
    client.setup_logging()
except Exception as e:
    print(f"Could not setup Cloud Logging client: {e}")

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

# Debug: print to stdout/stderr to ensure visibility
print("Phase2-to-Phase3 Orchestrator module loaded")

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Import expected processors from centralized config
# This ensures consistency across the codebase (Issue A fix)
try:
    from shared.config.orchestration_config import get_orchestration_config
    _config = get_orchestration_config()
    EXPECTED_PROCESSORS: List[str] = _config.phase_transitions.phase2_expected_processors
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)
    logger.info(f"Loaded {EXPECTED_PROCESSOR_COUNT} expected Phase 2 processors from config")
except ImportError:
    # Fallback for Cloud Functions where shared module may not be available
    # This is a realistic list of processors that actually run daily
    # NOTE: In monitoring mode, this is used for tracking completeness
    logger.warning("Could not import orchestration_config, using fallback list")
    EXPECTED_PROCESSORS: List[str] = [
        # Core daily processors
        'bdl_player_boxscores',      # Daily box scores from balldontlie
        'bigdataball_play_by_play',  # Per-game play-by-play
        'odds_api_game_lines',       # Per-game odds
        'nbac_schedule',             # Schedule updates
        'nbac_gamebook_player_stats', # Post-game player stats
        'br_roster',                 # Basketball-ref rosters
    ]
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)

# Initialize clients (reused across invocations)
db = firestore.Client()


def normalize_processor_name(raw_name: str, output_table: Optional[str] = None) -> str:
    """
    Normalize processor name to match config format.

    Phase 2 processors may publish:
    - Class names: BdlPlayerBoxscoresProcessor
    - Table names: bdl_player_boxscores

    This function normalizes to config format: bdl_player_boxscores

    Args:
        raw_name: Raw processor name from message
        output_table: Optional output_table field from message

    Returns:
        Normalized processor name matching config
    """
    import re

    # If raw_name is already in expected set, use it
    if raw_name in EXPECTED_PROCESSOR_SET:
        return raw_name

    # If output_table matches expected, use it (strip dataset prefix first)
    # Example: "nba_raw.bdl_player_boxscores" -> "bdl_player_boxscores"
    if output_table:
        table_name = output_table.split('.')[-1] if '.' in output_table else output_table
        if table_name in EXPECTED_PROCESSOR_SET:
            logger.debug(f"Matched via output_table: '{output_table}' -> '{table_name}'")
            return table_name

    # Convert CamelCase to snake_case and strip "Processor" suffix
    name = raw_name.replace('Processor', '')
    # Insert underscore before capitals and lowercase
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    logger.debug(f"Normalized '{raw_name}' -> '{name}'")
    return name


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
    # Debug: print immediately to verify function is invoked
    print(f"DEBUG: orchestrate_phase2_to_phase3 invoked with cloud_event type: {type(cloud_event)}")
    import sys
    sys.stdout.flush()

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

        # Normalize processor name to match config format
        # This handles class names like BdlPlayerBoxscoresProcessor -> bdl_player_boxscores
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
            # All expected processors complete - log for monitoring
            # NOTE: Phase 3 is triggered directly via Pub/Sub subscription, not here
            logger.info(
                f"✅ MONITORING: All {EXPECTED_PROCESSOR_COUNT} expected Phase 2 processors "
                f"complete for {game_date} (correlation_id={correlation_id})"
            )
        else:
            # Still waiting for more processors
            logger.info(f"MONITORING: Registered {processor_name} completion, waiting for others")

    except Exception as e:
        logger.error(f"Error in Phase 2→3 orchestrator: {e}", exc_info=True)
        # Don't raise - let Pub/Sub retry if transient, or drop if permanent


@firestore.transactional
def update_completion_atomic(transaction: firestore.Transaction, doc_ref, processor_name: str, completion_data: Dict) -> bool:
    """
    Atomically update processor completion and determine if all expected are complete.

    This function uses Firestore transactions to prevent race conditions when multiple
    processors complete simultaneously. The @firestore.transactional decorator ensures
    atomic read-modify-write operations.

    NOTE: In monitoring mode, this is used for tracking only. Phase 3 is triggered
    directly via Pub/Sub subscription, not by this orchestrator.

    Transaction flow:
    1. Read current state (locked)
    2. Check if processor already registered (idempotency)
    3. Add processor completion data
    4. Count total completions
    5. If all complete AND not yet marked → mark as complete and return True
    6. Write atomically (released lock)

    Args:
        transaction: Firestore transaction object
        doc_ref: Firestore document reference for this game_date
        processor_name: Name of completing processor (e.g., "BdlGamesProcessor")
        completion_data: Completion metadata (timestamp, correlation_id, status, etc.)

    Returns:
        bool: True if this update completes the expected processor count (for logging)
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
    if completed_count >= EXPECTED_PROCESSOR_COUNT and not current.get('_triggered'):
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


# ============================================================================
# HTTP ENDPOINTS (for monitoring and status queries)
# ============================================================================

@functions_framework.http
def status(request):
    """
    HTTP endpoint for querying Phase 2 completion status.

    Usage:
        GET /status?date=2025-12-23
        GET /status?date=2025-12-23,2025-12-22  (multiple dates)
        GET /status  (defaults to today)

    Returns:
        JSON with completion status for requested date(s)
    """
    from datetime import date

    # Get date(s) from query params
    date_param = request.args.get('date', date.today().isoformat())
    dates = [d.strip() for d in date_param.split(',')]

    # Get status for each date
    if len(dates) == 1:
        result = get_completion_status(dates[0])
    else:
        result = {
            'dates': {d: get_completion_status(d) for d in dates}
        }

    return json.dumps(result, indent=2, default=str), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return json.dumps({
        'status': 'healthy',
        'mode': 'monitoring-only',
        'expected_processors': EXPECTED_PROCESSOR_COUNT,
        'version': '2.0'
    }), 200, {'Content-Type': 'application/json'}


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
