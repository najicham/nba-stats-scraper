"""
MLB Phase 4 → Phase 5 Orchestrator

Cloud Function that tracks MLB Phase 4 processor completion and triggers Phase 5 predictions.

Architecture:
- Listens to: mlb-phase4-precompute-complete (Phase 4 processors publish here)
- Tracks state in: Firestore collection 'mlb_phase4_completion/{game_date}'
- Triggers: mlb-prediction-worker via HTTP (when all processors complete OR timeout)

Key Feature: TIMEOUT HANDLING
- If all processors don't complete within MAX_WAIT_HOURS, trigger anyway with partial data
- This prevents the pipeline from stalling

MLB Phase 4 Processors:
- pitcher_features
- lineup_k_analysis

Created: 2026-01-08
"""

import base64
import json
import logging
import os
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Tuple

from google.cloud import firestore
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
PREDICTION_URL = "https://mlb-prediction-worker-f7p3g7f6ya-wl.a.run.app"

# Timeout configuration
MAX_WAIT_HOURS = 4  # Maximum hours to wait for all processors
MAX_WAIT_SECONDS = MAX_WAIT_HOURS * 3600

# MLB Phase 4 expected processors
EXPECTED_PROCESSORS: List[str] = [
    'pitcher_features',
    'lineup_k_analysis',
]
EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)

# Initialize clients
db = firestore.Client()


def normalize_processor_name(raw_name: str, output_table: Optional[str] = None) -> str:
    """Normalize processor name to match config format."""
    if raw_name in EXPECTED_PROCESSOR_SET:
        return raw_name

    if output_table and output_table in EXPECTED_PROCESSOR_SET:
        return output_table

    # Convert CamelCase to snake_case
    name = raw_name.replace('Processor', '').replace('Mlb', '')
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    return name


def parse_pubsub_message(cloud_event) -> Dict:
    """Parse Pub/Sub message from CloudEvent."""
    message_data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    return json.loads(message_data)


def get_auth_token(audience: str) -> str:
    """Get identity token for authenticated service calls."""
    import urllib.request

    metadata_url = f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience={audience}"
    req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read().decode("utf-8")


def check_timeout(doc_data: Dict) -> Tuple[bool, str, List[str]]:
    """
    Check if we've waited long enough and should trigger with partial data.

    Returns:
        Tuple of (should_trigger, trigger_reason, missing_processors)
    """
    first_completion = doc_data.get('_first_completion_at')
    if not first_completion:
        return False, '', []

    # Parse first completion timestamp
    if isinstance(first_completion, str):
        first_time = datetime.fromisoformat(first_completion.replace('Z', '+00:00'))
    else:
        first_time = first_completion

    now = datetime.now(timezone.utc)
    elapsed = (now - first_time).total_seconds()

    if elapsed >= MAX_WAIT_SECONDS:
        # Find missing processors
        completed = [k for k in doc_data.keys() if not k.startswith('_')]
        missing = [p for p in EXPECTED_PROCESSORS if p not in completed]
        return True, 'timeout', missing

    return False, '', []


@firestore.transactional
def update_completion_atomic(transaction, doc_ref, processor_name: str, completion_data: Dict) -> Tuple[bool, str, List[str]]:
    """
    Atomically update completion state and check if we should trigger Phase 5.

    Returns:
        Tuple of (should_trigger, trigger_reason, missing_processors)
    """
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Idempotency check
    if processor_name in current:
        logger.info(f"Processor {processor_name} already registered (idempotent)")
        return False, 'already_registered', []

    # Track first completion time for timeout calculation
    if '_first_completion_at' not in current:
        current['_first_completion_at'] = datetime.now(timezone.utc).isoformat()

    # Add this processor's completion
    current[processor_name] = completion_data

    # Count completed processors
    completed = [k for k in current.keys() if not k.startswith('_')]
    completed_count = len(completed)
    current['_completed_count'] = completed_count

    # Check if all complete
    if completed_count >= EXPECTED_PROCESSOR_COUNT and not current.get('_triggered'):
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_trigger_reason'] = 'all_complete'
        transaction.set(doc_ref, current)
        return True, 'all_complete', []

    # Check timeout
    should_timeout, reason, missing = check_timeout(current)
    if should_timeout and not current.get('_triggered'):
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_trigger_reason'] = 'timeout'
        current['_missing_processors'] = missing
        transaction.set(doc_ref, current)
        logger.warning(f"Timeout reached after {MAX_WAIT_HOURS}h - triggering with partial data. Missing: {missing}")
        return True, 'timeout', missing

    transaction.set(doc_ref, current)
    return False, '', []


def trigger_predictions(game_date: str, correlation_id: str, trigger_reason: str, doc_ref):
    """Trigger MLB prediction worker via HTTP."""
    try:
        token = get_auth_token(PREDICTION_URL)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "game_date": game_date,
            "correlation_id": correlation_id,
            "trigger_source": "orchestrator",
            "triggered_by": "mlb_phase4_to_phase5_orchestrator",
            "trigger_reason": trigger_reason
        }

        response = requests.post(
            f"{PREDICTION_URL}/predict-batch",
            headers=headers,
            json=payload,
            timeout=180
        )

        logger.info(f"Prediction trigger response: {response.status_code} - {response.text[:200]}")

        # Update doc with trigger details
        doc_ref.update({
            '_prediction_triggered': True,
            '_prediction_response_code': response.status_code,
            '_prediction_trigger_timestamp': datetime.now(timezone.utc).isoformat()
        })

        return response.status_code == 200

    except Exception as e:
        logger.error(f"Failed to trigger predictions: {e}")
        doc_ref.update({
            '_prediction_triggered': False,
            '_prediction_error': str(e)[:200]
        })
        return False


@functions_framework.cloud_event
def orchestrate_mlb_phase4_to_phase5(cloud_event):
    """
    Handle MLB Phase 4 completion events and trigger Phase 5 predictions.

    Triggered by: Pub/Sub messages to mlb-phase4-precompute-complete
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

        processor_name = normalize_processor_name(raw_processor_name, output_table)

        if processor_name not in EXPECTED_PROCESSOR_SET:
            logger.info(f"Ignoring unexpected processor: {processor_name}")
            return

        logger.info(f"MLB Phase 4 complete: processor={processor_name}, game_date={game_date}, status={status}")

        completion_data = {
            'processor_name': processor_name,
            'correlation_id': correlation_id,
            'status': status,
            'completed_at': firestore.SERVER_TIMESTAMP,
            'record_count': message_data.get('record_count', 0),
        }

        doc_ref = db.collection('mlb_phase4_completion').document(game_date)

        transaction = db.transaction()
        should_trigger, trigger_reason, missing = update_completion_atomic(
            transaction, doc_ref, processor_name, completion_data
        )

        if should_trigger:
            if trigger_reason == 'timeout':
                logger.warning(f"Triggering predictions due to timeout. Missing processors: {missing}")
            trigger_predictions(game_date, correlation_id, trigger_reason, doc_ref)

    except Exception as e:
        logger.error(f"Error in MLB Phase 4→5 orchestrator: {e}", exc_info=True)
        raise


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'function': 'mlb_phase4_to_phase5',
        'expected_processors': EXPECTED_PROCESSORS,
        'timeout_hours': MAX_WAIT_HOURS,
        'sport': 'mlb'
    }, 200
