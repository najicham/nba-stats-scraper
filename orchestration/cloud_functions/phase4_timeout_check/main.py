"""
Phase 4 Timeout Check

Cloud Scheduler job that runs every 30 minutes to check for stuck Phase 4 states.
If a game_date has Phase 4 started but not triggered for > 4 hours, force trigger Phase 5.

This catches the edge case where ALL Phase 4 processors fail silently, causing no messages
to arrive at the Phase 4→5 orchestrator, meaning the timeout there never fires.

Architecture:
- Triggered by: Cloud Scheduler (every 30 minutes)
- Checks: Firestore collection 'phase4_completion/{game_date}'
- Triggers: Prediction coordinator /start endpoint
- Alerts: Slack webhook for timeout events

Deployment:
    gcloud functions deploy phase4-timeout-check \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/phase4_timeout_check \
        --entry-point check_phase4_timeouts \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=<webhook>

Scheduler:
    gcloud scheduler jobs create http phase4-timeout-check-job \
        --schedule "*/30 * * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.0
Created: 2026-01-12
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore, pubsub_v1
import functions_framework
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
PREDICTION_COORDINATOR_URL = os.environ.get(
    'PREDICTION_COORDINATOR_URL',
    'https://prediction-coordinator-756957797294.us-west2.run.app'
)
PHASE5_TRIGGER_TOPIC = 'nba-predictions-trigger'

# Timeout configuration
MAX_WAIT_HOURS = 4  # Same as phase4_to_phase5 orchestrator
LOOKBACK_DAYS = 2   # Check today and yesterday

# Timezone
ET = ZoneInfo("America/New_York")

# Initialize clients (reused across invocations)
db = firestore.Client()
publisher = pubsub_v1.PublisherClient()

# Expected Phase 4 processors (for reporting)
EXPECTED_PROCESSORS = [
    'team_defense_zone_analysis',
    'player_shot_zone_analysis',
    'player_composite_factors',
    'player_daily_cache',
    'ml_feature_store',
]


def get_stale_phase4_dates() -> List[Dict]:
    """
    Find Phase 4 states that are stale (started but not triggered after MAX_WAIT_HOURS).

    Returns:
        List of dicts with game_date, wait_hours, completed_processors, missing_processors
    """
    now = datetime.now(timezone.utc)
    stale_dates = []

    # Check today and yesterday
    for days_ago in range(LOOKBACK_DAYS):
        target_date = (now.date() - timedelta(days=days_ago)).isoformat()

        doc_ref = db.collection('phase4_completion').document(target_date)
        doc = doc_ref.get()

        if not doc.exists:
            continue

        data = doc.to_dict()

        # Skip if already triggered
        if data.get('_triggered'):
            continue

        # Check timeout
        first_completion_str = data.get('_first_completion_at')
        if not first_completion_str:
            continue

        # Parse timestamp
        try:
            first_completion = datetime.fromisoformat(
                first_completion_str.replace('Z', '+00:00')
            )
        except (ValueError, TypeError):
            logger.warning(f"Invalid timestamp for {target_date}: {first_completion_str}")
            continue

        wait_hours = (now - first_completion).total_seconds() / 3600

        if wait_hours > MAX_WAIT_HOURS:
            # Get completed/missing processors
            completed = [k for k in data.keys() if not k.startswith('_')]
            missing = [p for p in EXPECTED_PROCESSORS if p not in completed]

            stale_dates.append({
                'game_date': target_date,
                'wait_hours': wait_hours,
                'completed_processors': completed,
                'missing_processors': missing,
                'first_completion_at': first_completion_str
            })

    return stale_dates


def trigger_phase5_for_date(game_date: str, correlation_id: Optional[str] = None) -> bool:
    """
    Trigger Phase 5 predictions for a specific game_date.

    Updates Firestore state and calls prediction coordinator.

    Args:
        game_date: The date to trigger predictions for
        correlation_id: Optional correlation ID for tracing

    Returns:
        True if successful, False otherwise
    """
    if not correlation_id:
        correlation_id = f"timeout-check-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    success = True

    # Update Firestore state
    try:
        doc_ref = db.collection('phase4_completion').document(game_date)
        doc_ref.update({
            '_triggered': True,
            '_triggered_at': firestore.SERVER_TIMESTAMP,
            '_trigger_reason': 'scheduled_timeout_check',
            '_triggered_by': 'phase4_timeout_check'
        })
        logger.info(f"Updated Firestore state for {game_date}")
    except Exception as e:
        logger.error(f"Failed to update Firestore for {game_date}: {e}")
        success = False

    # Publish to Pub/Sub
    try:
        topic_path = publisher.topic_path(PROJECT_ID, PHASE5_TRIGGER_TOPIC)
        message = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'scheduled_timeout_check',
            'triggered_by': 'phase4_timeout_check',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        future = publisher.publish(topic_path, data=json.dumps(message).encode('utf-8'))
        message_id = future.result(timeout=10.0)
        logger.info(f"Published Phase 5 trigger for {game_date}: message_id={message_id}")
    except Exception as e:
        logger.error(f"Failed to publish Phase 5 trigger for {game_date}: {e}")
        success = False

    # Call prediction coordinator directly
    try:
        url = f"{PREDICTION_COORDINATOR_URL}/start"
        payload = {
            'game_date': game_date,
            'correlation_id': correlation_id,
            'trigger_source': 'phase4_timeout_check'
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
        logger.warning(f"Failed to trigger prediction coordinator: {e}")
        # Don't fail - Pub/Sub message was sent

    return success


def send_staleness_alert(stale_dates: List[Dict]) -> bool:
    """
    Send Slack alert for stale Phase 4 states.

    Args:
        stale_dates: List of stale date info dicts

    Returns:
        True if alert sent successfully, False otherwise
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping alert")
        return False

    if not stale_dates:
        return True

    try:
        # Build summary text
        dates_summary = []
        for item in stale_dates:
            dates_summary.append(
                f"• *{item['game_date']}*: waited {item['wait_hours']:.1f}h, "
                f"missing: {', '.join(item['missing_processors']) or 'none'}"
            )

        payload = {
            "attachments": [{
                "color": "#FF0000",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": ":rotating_light: Phase 4 Stale State Detected",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{len(stale_dates)} stale Phase 4 state(s) detected and triggered:*\n\n" +
                                    "\n".join(dates_summary)
                        }
                    },
                    {
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": (
                                f"Detected by scheduled timeout check. "
                                f"Threshold: {MAX_WAIT_HOURS} hours. "
                                f"Phase 5 predictions triggered for all stale dates."
                            )
                        }]
                    }
                ]
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Staleness alert sent for {len(stale_dates)} dates")
        return True

    except Exception as e:
        logger.error(f"Failed to send staleness alert: {e}")
        return False


@functions_framework.http
def check_phase4_timeouts(request):
    """
    HTTP endpoint that checks for stale Phase 4 states and triggers Phase 5 if needed.

    This function is designed to be called by Cloud Scheduler every 30 minutes.

    Returns:
        JSON response with status and triggered dates
    """
    try:
        logger.info("Starting Phase 4 staleness check")

        # Find stale states
        stale_dates = get_stale_phase4_dates()

        if not stale_dates:
            logger.info("No stale Phase 4 states found")
            return json.dumps({
                'status': 'ok',
                'message': 'No stale Phase 4 states found',
                'triggered': 0
            }), 200, {'Content-Type': 'application/json'}

        logger.warning(f"Found {len(stale_dates)} stale Phase 4 state(s)")

        # Trigger Phase 5 for each stale date
        triggered = []
        for item in stale_dates:
            game_date = item['game_date']
            logger.info(f"Triggering Phase 5 for stale date: {game_date}")

            if trigger_phase5_for_date(game_date):
                triggered.append(game_date)
            else:
                logger.error(f"Failed to fully trigger Phase 5 for {game_date}")

        # Send alert
        send_staleness_alert(stale_dates)

        return json.dumps({
            'status': 'triggered',
            'message': f'Triggered Phase 5 for {len(triggered)} stale date(s)',
            'triggered': len(triggered),
            'dates': triggered,
            'details': stale_dates
        }), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in Phase 4 timeout check: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'message': str(e)
        }), 500, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import sys

    print("Checking for stale Phase 4 states...")
    stale = get_stale_phase4_dates()

    if stale:
        print(f"\nFound {len(stale)} stale state(s):")
        for item in stale:
            print(f"  - {item['game_date']}: {item['wait_hours']:.1f}h, missing: {item['missing_processors']}")
    else:
        print("No stale states found")
