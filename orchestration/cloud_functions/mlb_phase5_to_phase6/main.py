"""
MLB Phase 5 → Phase 6 Orchestrator

Cloud Function that triggers MLB Phase 6 (Grading) after predictions complete.

Architecture:
- Listens to: mlb-phase5-predictions-complete
- Triggers: mlb-phase6-grading service via HTTP

Note: For MLB, Phase 6 is grading (comparing predictions to actual results).
This typically runs the morning after games to grade yesterday's predictions.

Created: 2026-01-08
"""

import base64
import json
import logging
import os
import requests
from datetime import datetime, timezone, timedelta

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
GRADING_URL = "https://mlb-phase6-grading-f7p3g7f6ya-wl.a.run.app"

# Minimum predictions required before grading
MIN_PREDICTIONS_REQUIRED = 5


def parse_pubsub_message(cloud_event) -> dict:
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


def check_predictions_exist(game_date: str) -> int:
    """Check if predictions exist for the given date."""
    bq_client = get_bigquery_client(project_id=PROJECT_ID)

    query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.mlb_predictions.pitcher_strikeouts`
    WHERE game_date = '{game_date}'
    """

    try:
        result = list(bq_client.query(query).result(timeout=60))
        return result[0].cnt if result else 0
    except Exception as e:
        logger.warning(f"Failed to check predictions: {e}")
        return 0


def trigger_grading(game_date: str, correlation_id: str) -> bool:
    """Trigger MLB grading service via HTTP."""
    try:
        token = get_auth_token(GRADING_URL)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        payload = {
            "game_date": game_date,
            "correlation_id": correlation_id,
            "trigger_source": "orchestrator",
            "triggered_by": "mlb_phase5_to_phase6_orchestrator"
        }

        response = requests.post(
            f"{GRADING_URL}/grade-date",
            headers=headers,
            json=payload,
            timeout=120
        )

        logger.info(f"Grading trigger response: {response.status_code} - {response.text[:200]}")
        return response.status_code == 200

    except Exception as e:
        logger.error(f"Failed to trigger grading: {e}", exc_info=True)
        return False


@functions_framework.cloud_event
def orchestrate_mlb_phase5_to_phase6(cloud_event):
    """
    Handle MLB Phase 5 completion events and trigger Phase 6 grading.

    Triggered by: Pub/Sub messages to mlb-phase5-predictions-complete

    Note: Grading should only run after games are complete (typically next morning).
    This orchestrator validates predictions exist before triggering grading.
    """
    try:
        message_data = parse_pubsub_message(cloud_event)

        game_date = message_data.get('game_date')
        correlation_id = message_data.get('correlation_id', 'unknown')
        predictions_count = message_data.get('predictions_count', 0)
        status = message_data.get('status', 'unknown')

        if not game_date:
            logger.warning("Missing game_date in message")
            return

        logger.info(f"MLB Phase 5 complete: game_date={game_date}, predictions={predictions_count}, status={status}")

        # Validate predictions exist
        if predictions_count == 0:
            predictions_count = check_predictions_exist(game_date)

        if predictions_count < MIN_PREDICTIONS_REQUIRED:
            logger.warning(f"Insufficient predictions ({predictions_count}) for {game_date}, skipping grading")
            return

        # For MLB, grading should typically wait until games are complete
        # The scheduler handles the timing (runs morning after games)
        # This orchestrator just ensures the trigger flows through

        logger.info(f"Triggering MLB Phase 6 grading for {game_date} ({predictions_count} predictions)")
        success = trigger_grading(game_date, correlation_id)

        if success:
            logger.info(f"Successfully triggered grading for {game_date}")
        else:
            logger.error(f"Failed to trigger grading for {game_date}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in MLB Phase 5→6 orchestrator: {e}", exc_info=True)
        raise


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'function': 'mlb_phase5_to_phase6',
        'min_predictions_required': MIN_PREDICTIONS_REQUIRED,
        'sport': 'mlb'
    }, 200
