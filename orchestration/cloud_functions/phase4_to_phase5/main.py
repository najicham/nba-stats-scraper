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
from typing import Dict, List, Optional, Set, Tuple

from google.cloud import firestore, pubsub_v1, bigquery
from shared.clients.bigquery_pool import get_bigquery_client
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
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Health check configuration
HEALTH_CHECK_ENABLED = os.environ.get('HEALTH_CHECK_ENABLED', 'true').lower() == 'true'
HEALTH_CHECK_TIMEOUT = int(os.environ.get('HEALTH_CHECK_TIMEOUT', '5'))

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


def send_timeout_alert(game_date: str, completed_count: int, expected_count: int, missing_processors: List[str], wait_hours: float) -> bool:
    """
    Send Slack alert when Phase 4→5 timeout fires.

    Args:
        game_date: The date being processed
        completed_count: How many processors completed
        expected_count: How many processors were expected
        missing_processors: List of processors that didn't complete
        wait_hours: How long we waited before timeout

    Returns:
        True if alert sent successfully, False otherwise
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping timeout alert")
        return False

    try:
        payload = {
            "attachments": [{
                "color": "#FF0000",  # Red for critical
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": ":rotating_light: Phase 4→5 Timeout Alert",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Pipeline timeout reached!* Phase 5 predictions triggered with incomplete Phase 4 data."
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Date:*\n{game_date}"},
                            {"type": "mrkdwn", "text": f"*Wait Time:*\n{wait_hours:.1f} hours"},
                            {"type": "mrkdwn", "text": f"*Processors:*\n{completed_count}/{expected_count}"},
                            {"type": "mrkdwn", "text": f"*Missing:*\n{', '.join(missing_processors) if missing_processors else 'None'}"},
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": "Predictions will proceed with available data. Check Cloud Function logs for details."
                        }]
                    }
                ]
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Timeout alert sent successfully for {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to send timeout alert: {e}")
        return False


# ============================================================================
# HEALTH CHECK FUNCTIONS
# ============================================================================

def check_service_health(service_url: str, timeout: int = 5) -> Dict[str, any]:
    """
    Check if a downstream service is healthy and ready to process requests.

    Calls the /ready endpoint which performs dependency checks (BigQuery, Firestore, etc).

    Args:
        service_url: Base URL of the service (e.g., https://prediction-coordinator...)
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
        # Don't raise for 503 - degraded state is acceptable
        if response.status_code in [200, 503]:
            health_data = response.json()
            status = health_data.get('status', 'unknown')
            # Consider 'degraded' and 'healthy' as acceptable
            is_healthy = status in ['ready', 'degraded', 'healthy']
        else:
            response.raise_for_status()
            health_data = response.json()
            status = health_data.get('status', 'unknown')
            is_healthy = status in ['ready', 'degraded', 'healthy']

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


def check_coordinator_health() -> Tuple[bool, Dict[str, Dict]]:
    """
    Check health of the Prediction Coordinator service.

    This is critical - if the coordinator is down, predictions cannot run.
    However, we still trigger even if unhealthy to let Pub/Sub retry handle it.

    Returns:
        Tuple of (all_healthy: bool, health_status: dict)
    """
    if not HEALTH_CHECK_ENABLED:
        logger.info("Health checks disabled via HEALTH_CHECK_ENABLED=false")
        return (True, {"health_checks": "disabled"})

    health_status = {}

    if PREDICTION_COORDINATOR_URL:
        coordinator_health = check_service_health(PREDICTION_COORDINATOR_URL, HEALTH_CHECK_TIMEOUT)
        health_status['prediction_coordinator'] = coordinator_health

        if not coordinator_health['healthy']:
            logger.warning(
                f"⚠️ Prediction Coordinator not ready: {coordinator_health['status']}. "
                f"Will trigger anyway - Pub/Sub will retry if it fails."
            )
            return (False, health_status)
    else:
        logger.warning("PREDICTION_COORDINATOR_URL not set, skipping health check")

    return (True, health_status)


# ============================================================================
# DATA FRESHNESS VALIDATION
# ============================================================================

# R-006: Data freshness validation before triggering Phase 5
# Required Phase 4 tables that must have data before triggering predictions
# NOTE: ml_feature_store_v2 is in nba_predictions, not nba_precompute
REQUIRED_PHASE4_TABLES = [
    ('nba_predictions', 'ml_feature_store_v2', 'game_date'),
    ('nba_precompute', 'player_daily_cache', 'cache_date'),
    ('nba_precompute', 'player_composite_factors', 'game_date'),
    ('nba_precompute', 'player_shot_zone_analysis', 'analysis_date'),
    ('nba_precompute', 'team_defense_zone_analysis', 'analysis_date'),
]


def verify_phase4_data_ready(game_date: str) -> tuple:
    """
    R-006: Verify Phase 4 tables have fresh data for game_date before triggering predictions.

    This is a belt-and-suspenders check - even if all processors report success,
    verify the data actually exists in BigQuery.

    Args:
        game_date: The date to verify (YYYY-MM-DD)

    Returns:
        tuple: (is_ready: bool, missing_tables: list, table_counts: dict)
    """
    try:
        bq_client = get_bigquery_client(project_id=os.environ.get('GCP_PROJECT', 'nba-props-platform'))
        missing = []
        table_counts = {}

        for dataset, table, date_col in REQUIRED_PHASE4_TABLES:
            try:
                query = f"""
                SELECT COUNT(*) as cnt
                FROM `{PROJECT_ID}.{dataset}.{table}`
                WHERE {date_col} = '{game_date}'
                """
                result = list(bq_client.query(query).result())
                count = result[0].cnt if result else 0
                table_counts[f"{dataset}.{table}"] = count

                if count == 0:
                    missing.append(f"{dataset}.{table}")
                    logger.warning(f"R-006: Missing data in {dataset}.{table} for {game_date}")

            except Exception as query_error:
                # If query fails (table doesn't exist, etc.), treat as missing
                logger.error(f"R-006: Failed to verify {dataset}.{table}: {query_error}")
                missing.append(f"{dataset}.{table}")
                table_counts[f"{dataset}.{table}"] = -1  # Error marker

        is_ready = len(missing) == 0
        if is_ready:
            logger.info(f"R-006: All Phase 4 tables verified for {game_date}: {table_counts}")
        else:
            logger.warning(f"R-006: Data freshness check FAILED for {game_date}. Missing: {missing}")

        return (is_ready, missing, table_counts)

    except Exception as e:
        logger.error(f"R-006: Data freshness verification failed: {e}")
        # On error, return False with empty details
        return (False, ['verification_error'], {'error': str(e)})


def send_data_freshness_alert(game_date: str, missing_tables: List[str], table_counts: Dict) -> bool:
    """
    Send Slack alert when Phase 4 data freshness check fails or circuit breaker trips.

    UPDATED: Now sends CRITICAL alert when circuit breaker trips (blocks predictions).
    Sends WARNING alert when degraded mode allowed (quality threshold met).

    Args:
        game_date: The date being processed
        missing_tables: List of tables with no data
        table_counts: Dict of table -> row count

    Returns:
        True if alert sent successfully, False otherwise
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping data freshness alert")
        return False

    try:
        # Format table counts for display
        counts_text = "\n".join([f"• {t}: {c}" for t, c in table_counts.items()])

        # Determine severity based on circuit breaker logic
        critical_processors = {
            'nba_precompute.player_daily_cache',
            'nba_predictions.ml_feature_store_v2'
        }
        tables_with_data = {t for t, count in table_counts.items() if count > 0}
        critical_complete = critical_processors.issubset(tables_with_data)
        total_complete = len(tables_with_data)
        circuit_breaker_tripped = (total_complete < 3) or (not critical_complete)

        if circuit_breaker_tripped:
            # CRITICAL: Circuit breaker has tripped - predictions BLOCKED
            payload = {
                "attachments": [{
                    "color": "#FF0000",  # Red for critical
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": ":octagonal_sign: R-006: Circuit Breaker TRIPPED - Predictions BLOCKED",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*CRITICAL: Phase 5 predictions BLOCKED!* Insufficient Phase 4 data quality for {game_date}."
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Date:*\n{game_date}"},
                                {"type": "mrkdwn", "text": f"*Processors:*\n{total_complete}/5 complete"},
                                {"type": "mrkdwn", "text": f"*Critical:*\n{'✅ Complete' if critical_complete else '❌ MISSING'}"},
                                {"type": "mrkdwn", "text": f"*Missing:*\n{', '.join(missing_tables) if missing_tables else 'None'}"},
                            ]
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Table Row Counts:*\n```{counts_text}```"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": ":no_entry: Predictions will NOT run until Phase 4 meets quality threshold (≥3/5 processors + both critical). Review Phase 4 logs and backfill if needed."
                            }]
                        }
                    ]
                }]
            }
        else:
            # WARNING: Degraded mode - some data missing but quality threshold met
            payload = {
                "attachments": [{
                    "color": "#FFA500",  # Orange for warning
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": ":warning: R-006: Phase 4 Degraded Mode",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Some Phase 4 tables missing data for {game_date}, but quality threshold MET. Proceeding with degraded predictions.*"
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Date:*\n{game_date}"},
                                {"type": "mrkdwn", "text": f"*Missing Tables:*\n{', '.join(missing_tables)}"},
                            ]
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Table Row Counts:*\n```{counts_text}```"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": "Predictions proceeding with {total_complete}/5 processors (threshold: ≥3 + critical complete). Review Phase 4 logs."
                            }]
                        }
                    ]
                }]
            }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Data freshness alert sent successfully for {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to send data freshness alert: {e}")
        return False


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
                # Send Slack alert for timeout
                completed_count = EXPECTED_PROCESSOR_COUNT - len(missing)
                send_timeout_alert(
                    game_date=game_date,
                    completed_count=completed_count,
                    expected_count=EXPECTED_PROCESSOR_COUNT,
                    missing_processors=missing,
                    wait_hours=MAX_WAIT_HOURS
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

    Does three things:
    1. R-006: Verifies Phase 4 data actually exists in BigQuery (BLOCKING circuit breaker)
    2. Verifies minimum coverage: ≥3/5 processors + both critical (PDC, MLFS)
    3. If checks pass: Publishes message + calls prediction coordinator

    UPDATED: Now implements circuit breaker pattern - BLOCKS predictions if quality threshold not met.

    Args:
        game_date: Date that was processed
        correlation_id: Original correlation ID from scraper run
        upstream_message: Original Phase 4 completion message

    Returns:
        Message ID if published successfully, None if failed

    Raises:
        ValueError: If circuit breaker trips (insufficient Phase 4 data quality)
    """
    try:
        # R-006: Verify Phase 4 data exists before triggering predictions
        # This is a belt-and-suspenders check even when all processors report success
        is_ready, missing_tables, table_counts = verify_phase4_data_ready(game_date)

        # Circuit breaker logic: Check minimum quality thresholds
        critical_processors = {
            'nba_precompute.player_daily_cache',  # PDC - Critical for predictions
            'nba_predictions.ml_feature_store_v2'  # MLFS - Critical for predictions
        }

        tables_with_data = {t for t, count in table_counts.items() if count > 0}
        critical_complete = critical_processors.issubset(tables_with_data)
        total_complete = len(tables_with_data)
        min_required = 3  # Require at least 3/5 processors

        # Circuit breaker trips if:
        # 1. Less than 3 processors completed, OR
        # 2. Missing either critical processor (PDC or MLFS)
        circuit_breaker_tripped = (total_complete < min_required) or (not critical_complete)

        if circuit_breaker_tripped:
            logger.error(
                f"R-006: Circuit breaker TRIPPED for {game_date}. "
                f"Processors: {total_complete}/5, Critical: {critical_complete}, "
                f"Missing: {missing_tables}. BLOCKING Phase 5 predictions."
            )
            # Send critical alert
            send_data_freshness_alert(game_date, missing_tables, table_counts)

            # CRITICAL: Raise exception to BLOCK predictions with insufficient data
            # This prevents poor-quality predictions (10-15% of weekly quality issues)
            raise ValueError(
                f"Phase 4 circuit breaker tripped for {game_date}. "
                f"Insufficient data quality: {total_complete}/5 processors complete, "
                f"critical processors {'complete' if critical_complete else 'MISSING'}. "
                f"Missing tables: {missing_tables}. "
                f"Cannot generate predictions without minimum Phase 4 coverage."
            )

        if not is_ready:
            logger.warning(
                f"R-006: Data freshness check shows missing tables for {game_date}. "
                f"Missing: {missing_tables}. However, circuit breaker threshold MET "
                f"({total_complete}/5 processors, critical complete). Proceeding with degraded mode."
            )
            # Send warning alert but continue (quality threshold met even if not all tables present)
            send_data_freshness_alert(game_date, missing_tables, table_counts)

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
            'parent_processor': 'Phase4Orchestrator',

            # R-006: Include data freshness verification results
            'data_freshness_verified': is_ready,
            'missing_tables': missing_tables if not is_ready else [],
            'table_row_counts': table_counts
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

        # Check health of prediction coordinator before calling it directly
        coordinator_healthy, health_status = check_coordinator_health()

        if coordinator_healthy:
            logger.info(f"✅ Prediction Coordinator is healthy, triggering via HTTP")
        else:
            logger.warning(
                f"⚠️ Prediction Coordinator health check failed: {health_status}. "
                f"Will attempt trigger anyway - Pub/Sub message already sent."
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
        # Don't raise - Pub/Sub message was sent, self-heal will catch it if needed


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


# ============================================================================
# HTTP ENDPOINTS (for monitoring and health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the phase4_to_phase5 orchestrator."""
    return json.dumps({
        'status': 'healthy',
        'function': 'phase4_to_phase5',
        'expected_processors': EXPECTED_PROCESSOR_COUNT,
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}


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
