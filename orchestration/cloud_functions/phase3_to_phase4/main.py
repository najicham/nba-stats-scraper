"""
Phase 3 → Phase 4 Orchestrator

Cloud Function that tracks Phase 3 processor completion and triggers Phase 4 when all complete.

Architecture:
- Listens to: nba-phase3-analytics-complete (Phase 3 processors publish here)
- Tracks state in: Firestore collection 'phase3_completion/{game_date}'
- Publishes to: nba-phase4-trigger (when all expected processors complete)

Critical Features:
- Atomic Firestore transactions (prevent race conditions)
- Idempotency (handles duplicate Pub/Sub messages)
- Deduplication marker (_triggered flag prevents double-trigger)
- Correlation ID preservation (traces back to original scraper run)
- Entity change propagation (combines entities_changed from all processors)
- Centralized config: Expected processors loaded from orchestration_config.py
- **MODE-AWARE ORCHESTRATION**: Different processor expectations for overnight vs same-day vs tomorrow
- **HEALTH CHECK INTEGRATION**: Validates downstream services before triggering
- **GRACEFUL DEGRADATION**: Triggers if critical processors + majority complete

Phase 3 Processors:
- player_game_summary
- team_defense_game_summary
- team_offense_game_summary
- upcoming_player_game_context
- upcoming_team_game_context

Version: 1.2 - Added mode-aware orchestration and health checks
Created: 2025-11-29
Updated: 2026-01-18
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple

from google.cloud import firestore, pubsub_v1
import functions_framework
import pytz
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
PHASE4_TRIGGER_TOPIC = 'nba-phase4-trigger'

# Health check configuration
ANALYTICS_PROCESSOR_URL = os.environ.get('ANALYTICS_PROCESSOR_URL', '')
PRECOMPUTE_PROCESSOR_URL = os.environ.get('PRECOMPUTE_PROCESSOR_URL', '')
HEALTH_CHECK_ENABLED = os.environ.get('HEALTH_CHECK_ENABLED', 'true').lower() == 'true'
HEALTH_CHECK_TIMEOUT = int(os.environ.get('HEALTH_CHECK_TIMEOUT', '5'))

# Mode-aware configuration
MODE_AWARE_ENABLED = os.environ.get('MODE_AWARE_ENABLED', 'true').lower() == 'true'

# Import expected processors from centralized config
# This ensures consistency across the codebase (Issue A fix)
try:
    from shared.config.orchestration_config import get_orchestration_config
    _config = get_orchestration_config()
    EXPECTED_PROCESSORS: List[str] = _config.phase_transitions.phase3_expected_processors
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)
    logger.info(f"Loaded {EXPECTED_PROCESSOR_COUNT} expected Phase 3 processors from config")
except ImportError:
    # Fallback for Cloud Functions where shared module may not be available
    # This list should match orchestration_config.py
    logger.warning("Could not import orchestration_config, using fallback list")
    EXPECTED_PROCESSORS: List[str] = [
        'player_game_summary',
        'team_defense_game_summary',
        'team_offense_game_summary',
        'upcoming_player_game_context',
        'upcoming_team_game_context',
    ]
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)

# Initialize clients (reused across invocations)
db = firestore.Client()
publisher = pubsub_v1.PublisherClient()


# ============================================================================
# MODE-AWARE ORCHESTRATION FUNCTIONS
# ============================================================================

def detect_orchestration_mode(game_date: str, current_time: Optional[datetime] = None) -> str:
    """
    Detect orchestration mode based on game_date and current time.

    Modes:
    - 'overnight': Processing yesterday's completed games (runs 6-8 AM ET)
    - 'same_day': Processing today's upcoming games (runs 10:30 AM ET)
    - 'tomorrow': Processing tomorrow's games (runs 5:00 PM ET)

    Args:
        game_date: Target game date (YYYY-MM-DD)
        current_time: Current timestamp (defaults to now in ET)

    Returns:
        Mode string: 'overnight', 'same_day', or 'tomorrow'
    """
    if current_time is None:
        et_tz = pytz.timezone('America/New_York')
        current_time = datetime.now(et_tz)

    try:
        game_dt = datetime.strptime(game_date, '%Y-%m-%d').date()
        current_date = current_time.date()

        # Determine mode based on date relationship
        if game_dt < current_date:
            return 'overnight'  # Processing yesterday's games
        elif game_dt == current_date:
            return 'same_day'  # Processing today's games
        else:
            return 'tomorrow'  # Processing tomorrow's games
    except Exception as e:
        logger.warning(f"Error detecting mode for game_date={game_date}: {e}, defaulting to 'overnight'")
        return 'overnight'


def get_expected_processors_for_mode(mode: str) -> Tuple[int, Set[str], Set[str]]:
    """
    Get expected processor configuration based on orchestration mode.

    Overnight mode (6-8 AM ET):
        - Expected: ALL 5 processors
        - Critical: player_game_summary, upcoming_player_game_context
        - Optional: team summaries, upcoming_team_game_context

    Same-day/Tomorrow mode (10:30 AM / 5 PM ET):
        - Expected: 1-2 processors
        - Critical: upcoming_player_game_context (required for predictions)
        - Optional: upcoming_team_game_context

    Args:
        mode: Orchestration mode ('overnight', 'same_day', 'tomorrow')

    Returns:
        Tuple of (expected_count, critical_processors, optional_processors)
    """
    if mode == 'overnight':
        return (
            5,  # Expected count
            {   # Critical processors (must have these)
                'player_game_summary',
                'upcoming_player_game_context'
            },
            {   # Optional processors (nice to have)
                'team_defense_game_summary',
                'team_offense_game_summary',
                'upcoming_team_game_context'
            }
        )
    elif mode in ['same_day', 'tomorrow']:
        return (
            1,  # Expected count (minimum)
            {   # Critical processors
                'upcoming_player_game_context'
            },
            {   # Optional processors
                'upcoming_team_game_context'
            }
        )
    else:
        # Unknown mode - default to overnight (safest/most comprehensive)
        logger.warning(f"Unknown mode '{mode}', defaulting to overnight expectations")
        return (5, {'player_game_summary', 'upcoming_player_game_context'},
                {'team_defense_game_summary', 'team_offense_game_summary', 'upcoming_team_game_context'})


def should_trigger_phase4(
    completed_processors: Set[str],
    mode: str,
    expected_count: int,
    critical_processors: Set[str],
    optional_processors: Set[str]
) -> Tuple[bool, str]:
    """
    Determine if Phase 4 should be triggered based on completion status.

    Triggering logic:
    1. ALL expected complete → trigger (ideal case)
    2. ALL critical + 60% of optional → trigger (graceful degradation)
    3. Otherwise → wait

    Args:
        completed_processors: Set of completed processor names
        mode: Current orchestration mode
        expected_count: Expected number of processors for this mode
        critical_processors: Set of critical processor names
        optional_processors: Set of optional processor names

    Returns:
        Tuple of (should_trigger: bool, reason: str)
    """
    total_complete = len(completed_processors)
    critical_complete = critical_processors.issubset(completed_processors)

    # Case 1: All expected processors complete (ideal)
    if total_complete >= expected_count:
        return (True, "all_complete")

    # Case 2: Graceful degradation - critical + majority of optional
    if critical_complete:
        total_expected = len(critical_processors) + len(optional_processors)
        completion_ratio = total_complete / total_expected if total_expected > 0 else 0

        if completion_ratio >= 0.6:  # 60% threshold
            return (True, f"critical_plus_majority_{int(completion_ratio * 100)}pct")

    # Case 3: Not enough processors complete
    return (False, f"waiting_critical={critical_complete}_total={total_complete}/{expected_count}")


# ============================================================================
# HEALTH CHECK FUNCTIONS
# ============================================================================

def check_service_health(service_url: str, timeout: int = 5) -> Dict[str, any]:
    """
    Check if a downstream service is healthy and ready to process requests.

    Calls the /ready endpoint which performs dependency checks (BigQuery, Firestore, etc).

    Args:
        service_url: Base URL of the service (e.g., https://analytics-processor...)
        timeout: Request timeout in seconds

    Returns:
        Dict with:
            - healthy: bool (True if status is 'ready' or 'degraded')
            - status: str ('ready', 'degraded', 'unhealthy', or 'unreachable')
            - details: dict (full health check response)
            - error: str (if unreachable)
    """
    try:
        response = requests.get(
            f"{service_url}/ready",
            timeout=timeout
        )
        response.raise_for_status()
        health_data = response.json()

        status = health_data.get('status', 'unknown')
        # Consider 'degraded' as healthy (some non-critical checks failing)
        is_healthy = status in ['ready', 'degraded']

        return {
            "healthy": is_healthy,
            "status": status,
            "details": health_data
        }
    except requests.exceptions.Timeout:
        logger.error(f"Health check timeout for {service_url}")
        return {
            "healthy": False,
            "status": "timeout",
            "error": f"Request timed out after {timeout}s"
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Health check failed for {service_url}: {e}")
        return {
            "healthy": False,
            "status": "unreachable",
            "error": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error checking health for {service_url}: {e}")
        return {
            "healthy": False,
            "status": "error",
            "error": str(e)
        }


def check_phase4_services_health() -> Tuple[bool, Dict[str, Dict]]:
    """
    Check health of all Phase 4 downstream services.

    Services checked:
    - Analytics Processor (processes analytical queries)
    - Precompute Processor (generates feature store)

    Returns:
        Tuple of (all_healthy: bool, health_status: dict)
    """
    if not HEALTH_CHECK_ENABLED:
        logger.info("Health checks disabled via HEALTH_CHECK_ENABLED=false")
        return (True, {"health_checks": "disabled"})

    health_status = {}
    all_healthy = True

    # Check analytics processor
    if ANALYTICS_PROCESSOR_URL:
        analytics_health = check_service_health(ANALYTICS_PROCESSOR_URL, HEALTH_CHECK_TIMEOUT)
        health_status['analytics_processor'] = analytics_health
        if not analytics_health['healthy']:
            all_healthy = False
            logger.warning(f"Analytics Processor not ready: {analytics_health['status']}")
    else:
        logger.info("ANALYTICS_PROCESSOR_URL not set, skipping health check")

    # Check precompute processor
    if PRECOMPUTE_PROCESSOR_URL:
        precompute_health = check_service_health(PRECOMPUTE_PROCESSOR_URL, HEALTH_CHECK_TIMEOUT)
        health_status['precompute_processor'] = precompute_health
        if not precompute_health['healthy']:
            all_healthy = False
            logger.warning(f"Precompute Processor not ready: {precompute_health['status']}")
    else:
        logger.info("PRECOMPUTE_PROCESSOR_URL not set, skipping health check")

    return (all_healthy, health_status)


def normalize_processor_name(raw_name: str, output_table: Optional[str] = None) -> str:
    """
    Normalize processor name to match config format.

    Phase 3 processors may publish:
    - Class names: PlayerGameSummaryProcessor
    - Table names: player_game_summary

    This function normalizes to config format: player_game_summary

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

    # If output_table matches expected, use it
    if output_table and output_table in EXPECTED_PROCESSOR_SET:
        return output_table

    # Convert CamelCase to snake_case and strip "Processor" suffix
    name = raw_name.replace('Processor', '')
    # Insert underscore before capitals and lowercase
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    logger.debug(f"Normalized '{raw_name}' -> '{name}'")
    return name


@functions_framework.cloud_event
def orchestrate_phase3_to_phase4(cloud_event):
    """
    Handle Phase 3 completion events and trigger Phase 4 when all processors complete.

    Triggered by: Pub/Sub messages to nba-phase3-analytics-complete

    Message format (unified):
    {
        "processor_name": "PlayerGameSummaryProcessor",
        "phase": "phase_3_analytics",
        "execution_id": "def-456",
        "correlation_id": "abc-123",
        "game_date": "2025-11-29",
        "output_table": "player_game_summary",
        "output_dataset": "nba_analytics",
        "status": "success",
        "record_count": 450,
        "metadata": {
            "is_incremental": true,
            "entities_changed": ["lebron-james"]
        },
        ...
    }

    Args:
        cloud_event: CloudEvent from Pub/Sub containing Phase 3 completion data
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

        # Extract entities_changed from metadata (for selective processing)
        metadata = message_data.get('metadata', {})
        entities_changed = metadata.get('entities_changed', [])
        is_incremental = metadata.get('is_incremental', False)

        # Validate required fields
        if not game_date or not raw_processor_name:
            logger.error(f"Missing required fields in message: {message_data}")
            return

        # Normalize processor name to match config format
        # This handles class names like PlayerGameSummaryProcessor -> player_game_summary
        processor_name = normalize_processor_name(raw_processor_name, output_table)

        # Skip non-success statuses (only track successful completions)
        if status not in ('success', 'partial'):
            logger.info(f"Skipping {processor_name} with status '{status}' (only track success/partial)")
            return

        logger.info(
            f"Received completion from {processor_name} (raw: {raw_processor_name}) for {game_date} "
            f"(status={status}, incremental={is_incremental}, "
            f"entities_changed={len(entities_changed)}, correlation_id={correlation_id})"
        )

        # Update completion state with atomic transaction
        doc_ref = db.collection('phase3_completion').document(game_date)

        # Create transaction and execute atomic update
        transaction = db.transaction()
        should_trigger, mode, trigger_reason = update_completion_atomic(
            transaction,
            doc_ref,
            processor_name,
            {
                'completed_at': firestore.SERVER_TIMESTAMP,
                'correlation_id': correlation_id,
                'status': status,
                'record_count': message_data.get('record_count', 0),
                'execution_id': message_data.get('execution_id'),
                'is_incremental': is_incremental,
                'entities_changed': entities_changed
            },
            game_date  # Pass game_date for mode detection
        )

        if should_trigger:
            logger.info(
                f"Phase 3 ready to trigger Phase 4: mode={mode}, reason={trigger_reason}, "
                f"game_date={game_date}"
            )

            # Check health of downstream services before triggering
            services_healthy, health_status = check_phase4_services_health()

            if services_healthy:
                # All services healthy - trigger Phase 4
                trigger_phase4(game_date, correlation_id, doc_ref, message_data, mode, trigger_reason)
                logger.info(
                    f"✅ Phase 4 triggered successfully: mode={mode}, reason={trigger_reason}, "
                    f"game_date={game_date}, correlation_id={correlation_id}"
                )
            else:
                # Services not healthy - log warning but don't block
                # (Phase 4 trigger will be published but may fail - Pub/Sub will retry)
                logger.warning(
                    f"⚠️ Phase 4 services not fully healthy, but triggering anyway "
                    f"(Pub/Sub will retry if fails): {health_status}"
                )
                trigger_phase4(game_date, correlation_id, doc_ref, message_data, mode, trigger_reason)
                logger.info(
                    f"⚠️ Phase 4 triggered with unhealthy services: mode={mode}, "
                    f"reason={trigger_reason}, health={health_status}"
                )
        else:
            # Still waiting for more processors
            logger.info(
                f"Registered completion for {processor_name}, mode={mode}, "
                f"trigger_reason={trigger_reason}"
            )

    except Exception as e:
        logger.error(f"Error in Phase 3→4 orchestrator: {e}", exc_info=True)
        # Don't raise - let Pub/Sub retry if transient, or drop if permanent


@firestore.transactional
def update_completion_atomic(transaction: firestore.Transaction, doc_ref, processor_name: str,
                             completion_data: Dict, game_date: str) -> Tuple[bool, str, str]:
    """
    Atomically update processor completion and determine if should trigger next phase.

    **ENHANCED WITH MODE-AWARE ORCHESTRATION**

    This function uses Firestore transactions to prevent race conditions when multiple
    processors complete simultaneously.

    Transaction flow:
    1. Read current state (locked)
    2. Check if processor already registered (idempotency)
    3. Add processor completion data
    4. Detect orchestration mode (overnight vs same-day vs tomorrow)
    5. Get expected processors for this mode
    6. Determine if should trigger using mode-aware logic
    7. If should trigger AND not yet triggered → mark triggered and return True
    8. Write atomically (released lock)

    Args:
        transaction: Firestore transaction object
        doc_ref: Firestore document reference for this game_date
        processor_name: Name of completing processor
        completion_data: Completion metadata
        game_date: Date being processed (for mode detection)

    Returns:
        Tuple of (should_trigger: bool, mode: str, trigger_reason: str)
    """
    # Read current state within transaction (locked)
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Idempotency check: skip if this processor already registered
    if processor_name in current:
        logger.debug(f"Processor {processor_name} already registered (duplicate Pub/Sub message)")
        return (False, 'unknown', 'duplicate')

    # Add this processor's completion data
    current[processor_name] = completion_data

    # Count completed processors (exclude metadata fields starting with _)
    completed_processor_names = [k for k in current.keys() if not k.startswith('_')]
    completed_processors = set(completed_processor_names)
    completed_count = len(completed_processors)

    # Detect mode and get expectations
    if MODE_AWARE_ENABLED:
        mode = detect_orchestration_mode(game_date)
        expected_count, critical_processors, optional_processors = get_expected_processors_for_mode(mode)

        logger.info(
            f"Mode-aware orchestration: mode={mode}, expected={expected_count}, "
            f"critical={len(critical_processors)}, optional={len(optional_processors)}, "
            f"completed={completed_count}"
        )
    else:
        # Fallback to original all-or-nothing logic
        mode = 'legacy'
        expected_count = EXPECTED_PROCESSOR_COUNT
        critical_processors = set()
        optional_processors = set()
        logger.info(f"Legacy orchestration: expected={expected_count}, completed={completed_count}")

    # Determine if should trigger
    if MODE_AWARE_ENABLED:
        should_trigger, trigger_reason = should_trigger_phase4(
            completed_processors,
            mode,
            expected_count,
            critical_processors,
            optional_processors
        )
    else:
        # Legacy logic: all-or-nothing
        should_trigger = completed_count >= expected_count
        trigger_reason = "all_complete" if should_trigger else f"waiting_{completed_count}/{expected_count}"

    # Check if this completes the phase AND hasn't been triggered yet
    if should_trigger and not current.get('_triggered'):
        # Mark as triggered to prevent duplicate triggers
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_completed_count'] = completed_count
        current['_mode'] = mode
        current['_trigger_reason'] = trigger_reason

        # Write atomically
        transaction.set(doc_ref, current)

        return (True, mode, trigger_reason)  # Trigger Phase 4
    else:
        # Not yet complete, or already triggered
        current['_completed_count'] = completed_count
        current['_mode'] = mode
        current['_last_update'] = firestore.SERVER_TIMESTAMP

        # Write atomically
        transaction.set(doc_ref, current)

        if current.get('_triggered'):
            return (False, mode, 'already_triggered')
        else:
            return (False, mode, trigger_reason)  # Don't trigger


def trigger_phase4(game_date: str, correlation_id: str, doc_ref, upstream_message: Dict,
                   mode: str, trigger_reason: str) -> Optional[str]:
    """
    Publish message to trigger Phase 4 precompute processing.

    Combines entities_changed from all Phase 3 processors for efficient downstream processing.

    **ENHANCED**: Now includes orchestration mode and trigger reason for downstream processing.

    Message published to: nba-phase4-trigger

    Message format:
    {
        "game_date": "2025-11-29",
        "correlation_id": "abc-123",
        "trigger_source": "orchestrator",
        "triggered_by": "phase3_to_phase4_orchestrator",
        "upstream_processors_count": 5,
        "timestamp": "2025-11-29T12:30:00Z",
        "entities_changed": {
            "players": ["lebron-james", "stephen-curry"],
            "teams": ["LAL", "GSW"]
        },
        "is_incremental": true,
        "mode": "overnight",  # NEW: orchestration mode
        "trigger_reason": "all_complete"  # NEW: why was Phase 4 triggered
    }

    Args:
        game_date: Date that was processed
        correlation_id: Original correlation ID from scraper run
        doc_ref: Firestore document with all processor completions
        upstream_message: Original Phase 3 completion message
        mode: Orchestration mode (overnight, same_day, tomorrow)
        trigger_reason: Reason for triggering (all_complete, critical_plus_majority_XX, etc.)

    Returns:
        Message ID if published successfully, None if failed
    """
    try:
        # Read Firestore to get all processor data (including entities_changed)
        doc_snapshot = doc_ref.get()
        all_processors = doc_snapshot.to_dict() if doc_snapshot.exists else {}

        # Combine entities_changed from all processors
        all_player_changes = set()
        all_team_changes = set()
        any_incremental = False

        for processor_name, processor_data in all_processors.items():
            if processor_name.startswith('_'):
                continue  # Skip metadata fields

            # Check if this processor was incremental
            if isinstance(processor_data, dict) and processor_data.get('is_incremental'):
                any_incremental = True

                # Get entities_changed for this processor
                entities = processor_data.get('entities_changed', [])

                # Categorize by type (player processors vs team processors)
                if 'Player' in processor_name:
                    all_player_changes.update(entities)
                elif 'Team' in processor_name:
                    all_team_changes.update(entities)

        # Build combined entities_changed
        combined_entities = {}
        if all_player_changes:
            combined_entities['players'] = list(all_player_changes)
        if all_team_changes:
            combined_entities['teams'] = list(all_team_changes)

        logger.info(
            f"Combined entities from {EXPECTED_PROCESSOR_COUNT} processors: "
            f"{len(all_player_changes)} players, {len(all_team_changes)} teams changed"
        )

        topic_path = publisher.topic_path(PROJECT_ID, PHASE4_TRIGGER_TOPIC)

        # Build trigger message
        message = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase3_to_phase4_orchestrator',
            'upstream_processors_count': EXPECTED_PROCESSOR_COUNT,
            'expected_processors': EXPECTED_PROCESSORS,  # Include list for debugging
            'timestamp': datetime.now(timezone.utc).isoformat(),

            # Selective processing metadata
            'entities_changed': combined_entities,
            'is_incremental': any_incremental,

            # NEW: Mode-aware orchestration metadata
            'mode': mode,  # overnight, same_day, or tomorrow
            'trigger_reason': trigger_reason,  # all_complete, critical_plus_majority_XX, etc.

            # Optional metadata from upstream
            'parent_execution_id': upstream_message.get('execution_id'),
            'parent_processor': 'Phase3Orchestrator'
        }

        # Publish to Pub/Sub
        future = publisher.publish(
            topic_path,
            data=json.dumps(message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(
            f"Published Phase 4 trigger: message_id={message_id}, game_date={game_date}, "
            f"incremental={any_incremental}, players_changed={len(all_player_changes)}"
        )
        return message_id

    except Exception as e:
        logger.error(f"Failed to publish Phase 4 trigger for {game_date}: {e}", exc_info=True)
        return None


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
    doc_ref = db.collection('phase3_completion').document(game_date)
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

    # Calculate combined entities_changed
    all_player_changes = set()
    all_team_changes = set()

    for processor_name, processor_data in data.items():
        if processor_name.startswith('_'):
            continue
        if isinstance(processor_data, dict):
            entities = processor_data.get('entities_changed', [])
            if 'Player' in processor_name:
                all_player_changes.update(entities)
            elif 'Team' in processor_name:
                all_team_changes.update(entities)

    return {
        'game_date': game_date,
        'status': 'triggered' if data.get('_triggered') else 'in_progress',
        'completed_count': completed_count,
        'expected_count': EXPECTED_PROCESSOR_COUNT,
        'completed_processors': completed_processors,
        'missing_processors': missing_processors,
        'triggered_at': data.get('_triggered_at'),
        'combined_entities_changed': {
            'players': list(all_player_changes),
            'teams': list(all_team_changes)
        }
    }


# ============================================================================
# HTTP ENDPOINTS (for monitoring and health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the phase3_to_phase4 orchestrator."""
    return json.dumps({
        'status': 'healthy',
        'function': 'phase3_to_phase4',
        'expected_processors': EXPECTED_PROCESSOR_COUNT,
        'version': '1.1'
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
