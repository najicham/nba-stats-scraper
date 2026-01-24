"""
Automatic Backfill Trigger Cloud Function

Listens to Pub/Sub topic 'boxscore-gaps-detected' and triggers appropriate
backfill operations when data gaps are detected.

Architecture:
- Listens to: boxscore-gaps-detected (Pub/Sub)
- Tracks state in: Firestore collection 'backfill_requests'
- Triggers: Appropriate backfill scripts via Cloud Run Jobs or HTTP endpoints

Message Format (expected from gap detection system):
{
    "game_ids": ["0022400123", "0022400124"],  # List of game IDs needing backfill
    "gap_type": "boxscore",                     # Type: 'boxscore', 'gamebook', 'analytics'
    "detected_at": "2025-12-30T12:00:00Z",      # When the gap was detected
    "source": "completeness_monitor",            # What detected the gap
    "severity": "warning",                       # 'info', 'warning', 'critical'
    "game_dates": ["2025-12-29", "2025-12-28"], # Optional: dates of affected games
    "team_abbrs": ["LAL", "GSW"]                # Optional: affected teams
}

Features:
- Deduplication: Prevents duplicate backfill requests using Firestore
- Cooldown: Won't re-trigger backfill for same games within cooldown period
- Logging: Comprehensive logging of all backfill requests
- Alerting: Integrates with AlertManager for notifications

Deployment:
    gcloud functions deploy backfill-trigger \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/backfill_trigger \
        --entry-point handle_gaps_detected \
        --trigger-topic boxscore-gaps-detected \
        --set-env-vars GCP_PROJECT=nba-props-platform

Version: 1.0
Created: 2025-12-30
"""

import base64
import json
import logging
import os
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

from google.cloud import firestore, pubsub_v1
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Firestore collection for tracking backfill requests
BACKFILL_COLLECTION = 'backfill_requests'

# Cooldown period: Don't trigger same backfill within this window (hours)
BACKFILL_COOLDOWN_HOURS = float(os.environ.get('BACKFILL_COOLDOWN_HOURS', '4'))

# Maximum games per backfill request (to prevent overwhelming the system)
MAX_GAMES_PER_REQUEST = int(os.environ.get('MAX_GAMES_PER_REQUEST', '20'))

# Cloud Run service URLs for backfill endpoints
PHASE2_RAW_URL = os.environ.get(
    'PHASE2_RAW_URL',
    'https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app'
)
PHASE3_ANALYTICS_URL = os.environ.get(
    'PHASE3_ANALYTICS_URL',
    'https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app'
)

# Gap type to backfill action mapping
GAP_TYPE_ACTIONS = {
    'boxscore': {
        'description': 'Raw boxscore data missing',
        'service_url': PHASE2_RAW_URL,
        'endpoint': '/process-date-range',
        'processors': ['BdlPlayerBoxscoreProcessor', 'NbacTeamBoxscoreProcessor'],
        'priority': 'high'
    },
    'gamebook': {
        'description': 'Gamebook data missing',
        'service_url': PHASE2_RAW_URL,
        'endpoint': '/process-date-range',
        'processors': ['NbacGamebookProcessor'],
        'priority': 'medium'
    },
    'player_game_summary': {
        'description': 'Player game summary analytics missing',
        'service_url': PHASE3_ANALYTICS_URL,
        'endpoint': '/process-date-range',
        'processors': ['PlayerGameSummaryProcessor'],
        'priority': 'high'
    },
    'analytics': {
        'description': 'Analytics data missing',
        'service_url': PHASE3_ANALYTICS_URL,
        'endpoint': '/process-date-range',
        'processors': ['PlayerGameSummaryProcessor', 'TeamDefenseGameSummaryProcessor'],
        'priority': 'medium'
    }
}

# Initialize clients (reused across invocations)
db = firestore.Client()
publisher = pubsub_v1.PublisherClient()


def generate_request_id(game_ids: List[str], gap_type: str) -> str:
    """
    Generate a unique ID for a backfill request.

    Used for deduplication in Firestore.

    Args:
        game_ids: List of game IDs
        gap_type: Type of gap

    Returns:
        Hash-based unique ID
    """
    # Sort game IDs for consistent hashing
    sorted_ids = sorted(game_ids)
    content = f"{gap_type}:{','.join(sorted_ids)}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


def check_pending_backfill(request_id: str) -> Optional[Dict]:
    """
    Check if there's a pending backfill request with this ID.

    Args:
        request_id: Unique request ID

    Returns:
        Existing request data if found and not expired, None otherwise
    """
    doc_ref = db.collection(BACKFILL_COLLECTION).document(request_id)
    doc = doc_ref.get()

    if not doc.exists:
        return None

    data = doc.to_dict()

    # Check if within cooldown period
    created_at = data.get('created_at')
    if created_at:
        if hasattr(created_at, 'timestamp'):
            # Firestore timestamp
            created_time = created_at.replace(tzinfo=timezone.utc)
        else:
            created_time = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))

        cooldown = timedelta(hours=BACKFILL_COOLDOWN_HOURS)
        if datetime.now(timezone.utc) - created_time < cooldown:
            return data

    return None


def create_backfill_request(
    request_id: str,
    game_ids: List[str],
    gap_type: str,
    message_data: Dict
) -> Dict:
    """
    Create a new backfill request in Firestore.

    Args:
        request_id: Unique request ID
        game_ids: List of game IDs to backfill
        gap_type: Type of gap
        message_data: Original message data

    Returns:
        Created request document
    """
    now = datetime.now(timezone.utc)

    request_doc = {
        'request_id': request_id,
        'game_ids': game_ids,
        'gap_type': gap_type,
        'status': 'pending',
        'created_at': now,
        'updated_at': now,
        'detected_at': message_data.get('detected_at'),
        'source': message_data.get('source', 'unknown'),
        'severity': message_data.get('severity', 'info'),
        'game_dates': message_data.get('game_dates', []),
        'team_abbrs': message_data.get('team_abbrs', []),
        'trigger_attempts': 0,
        'last_trigger_at': None,
        'completed_at': None,
        'error': None
    }

    doc_ref = db.collection(BACKFILL_COLLECTION).document(request_id)
    doc_ref.set(request_doc)

    logger.info(f"Created backfill request: {request_id} for {len(game_ids)} games")

    return request_doc


def update_backfill_status(
    request_id: str,
    status: str,
    error: Optional[str] = None
) -> None:
    """
    Update the status of a backfill request.

    Args:
        request_id: Request ID to update
        status: New status ('pending', 'triggered', 'completed', 'failed')
        error: Optional error message
    """
    doc_ref = db.collection(BACKFILL_COLLECTION).document(request_id)

    update_data = {
        'status': status,
        'updated_at': datetime.now(timezone.utc)
    }

    if status == 'triggered':
        update_data['last_trigger_at'] = datetime.now(timezone.utc)
        update_data['trigger_attempts'] = firestore.Increment(1)
    elif status == 'completed':
        update_data['completed_at'] = datetime.now(timezone.utc)
    elif status == 'failed' and error:
        update_data['error'] = error

    doc_ref.update(update_data)
    logger.info(f"Updated backfill request {request_id}: status={status}")


def get_auth_token(audience: str) -> str:
    """
    Get identity token for authenticated service calls using metadata server.

    Args:
        audience: Target service URL

    Returns:
        Identity token string
    """
    import urllib.request

    metadata_url = (
        f"http://metadata.google.internal/computeMetadata/v1/instance/"
        f"service-accounts/default/identity?audience={audience}"
    )
    req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to get auth token: {e}")
        raise


def trigger_backfill(
    gap_type: str,
    game_dates: List[str],
    request_id: str
) -> bool:
    """
    Trigger the actual backfill operation.

    Args:
        gap_type: Type of gap (determines which processors to run)
        game_dates: List of dates to backfill (YYYY-MM-DD format)
        request_id: Request ID for tracking

    Returns:
        True if trigger was successful, False otherwise
    """
    import requests

    action = GAP_TYPE_ACTIONS.get(gap_type)
    if not action:
        logger.error(f"Unknown gap type: {gap_type}")
        return False

    if not game_dates:
        logger.warning(f"No game dates provided for backfill request {request_id}")
        return False

    # Sort dates to get range
    sorted_dates = sorted(game_dates)
    start_date = sorted_dates[0]
    end_date = sorted_dates[-1]

    service_url = action['service_url']
    endpoint = action['endpoint']
    processors = action['processors']

    logger.info(
        f"Triggering backfill for {gap_type}: "
        f"{start_date} to {end_date}, processors: {processors}"
    )

    try:
        # Get auth token
        token = get_auth_token(service_url)
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Build payload
        payload = {
            'start_date': start_date,
            'end_date': end_date,
            'processors': processors,
            'backfill_mode': True,
            'skip_dependency_check': True,  # Backfill may have incomplete upstream
            'correlation_id': f'backfill-{request_id}'
        }

        # Make request
        url = f"{service_url}{endpoint}"
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code == 200:
            logger.info(f"Backfill triggered successfully: {response.text[:200]}")
            return True
        else:
            logger.error(
                f"Backfill trigger failed: {response.status_code} - {response.text[:200]}"
            )
            return False

    except Exception as e:
        logger.error(f"Error triggering backfill: {e}")
        return False


def send_backfill_notification(
    request_id: str,
    game_ids: List[str],
    gap_type: str,
    status: str,
    message_data: Dict
) -> None:
    """
    Send notification about backfill request.

    Args:
        request_id: Request ID
        game_ids: List of game IDs
        gap_type: Type of gap
        status: Current status
        message_data: Original message data
    """
    try:
        from shared.alerts.alert_manager import get_alert_manager

        severity = message_data.get('severity', 'info')
        game_dates = message_data.get('game_dates', [])

        title = f"Backfill {status.upper()}: {gap_type} ({len(game_ids)} games)"

        message_lines = [
            f"Request ID: {request_id}",
            f"Gap Type: {gap_type}",
            f"Games: {len(game_ids)}",
            f"Dates: {', '.join(game_dates[:5])}{'...' if len(game_dates) > 5 else ''}",
            f"Source: {message_data.get('source', 'unknown')}",
            f"Status: {status}",
        ]

        if status == 'triggered':
            message_lines.append("")
            message_lines.append("Backfill operation has been triggered automatically.")
        elif status == 'skipped':
            message_lines.append("")
            message_lines.append("Request skipped - similar backfill already pending.")

        alert_mgr = get_alert_manager()
        alert_mgr.send_alert(
            severity=severity if status != 'triggered' else 'info',
            title=title,
            message="\n".join(message_lines),
            category=f"backfill_{gap_type}",
            context={
                'request_id': request_id,
                'game_ids': game_ids[:10],  # Limit for context
                'gap_type': gap_type,
                'status': status
            }
        )

    except ImportError:
        logger.debug("AlertManager not available, skipping notification")
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")


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
        pubsub_message = cloud_event.data.get('message', {})

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


def validate_message(message_data: Dict) -> tuple:
    """
    Validate the incoming message format.

    Args:
        message_data: Parsed message data

    Returns:
        Tuple of (is_valid, error_message)
    """
    required_fields = ['gap_type', 'detected_at']

    for field in required_fields:
        if field not in message_data:
            return False, f"Missing required field: {field}"

    # Must have either game_ids or game_dates
    if not message_data.get('game_ids') and not message_data.get('game_dates'):
        return False, "Must provide either game_ids or game_dates"

    gap_type = message_data.get('gap_type')
    if gap_type not in GAP_TYPE_ACTIONS:
        return False, f"Unknown gap_type: {gap_type}"

    return True, None


@functions_framework.cloud_event
def handle_gaps_detected(cloud_event):
    """
    Main entry point: Handle gap detection events and trigger backfills.

    Triggered by: Pub/Sub messages to boxscore-gaps-detected topic

    Message format:
    {
        "game_ids": ["0022400123"],
        "gap_type": "boxscore",
        "detected_at": "2025-12-30T12:00:00Z",
        "source": "completeness_monitor",
        "severity": "warning",
        "game_dates": ["2025-12-29"]
    }
    """
    try:
        # Parse message
        message_data = parse_pubsub_message(cloud_event)

        logger.info(f"Received gap detection event: {json.dumps(message_data)[:500]}")

        # Validate message
        is_valid, error = validate_message(message_data)
        if not is_valid:
            logger.error(f"Invalid message: {error}")
            return

        # Extract fields
        game_ids = message_data.get('game_ids', [])
        gap_type = message_data.get('gap_type')
        game_dates = message_data.get('game_dates', [])

        # If no game_ids but we have game_dates, use dates for deduplication
        if not game_ids and game_dates:
            game_ids = game_dates  # Use dates as pseudo-IDs

        # Limit games per request
        if len(game_ids) > MAX_GAMES_PER_REQUEST:
            logger.warning(
                f"Truncating request from {len(game_ids)} to {MAX_GAMES_PER_REQUEST} games"
            )
            game_ids = game_ids[:MAX_GAMES_PER_REQUEST]
            game_dates = game_dates[:MAX_GAMES_PER_REQUEST] if game_dates else []

        # Generate request ID for deduplication
        request_id = generate_request_id(game_ids, gap_type)

        # Check for existing pending request
        existing = check_pending_backfill(request_id)
        if existing:
            logger.info(
                f"Skipping duplicate backfill request {request_id} - "
                f"existing request from {existing.get('created_at')}"
            )
            send_backfill_notification(
                request_id, game_ids, gap_type, 'skipped', message_data
            )
            return

        # Create new backfill request
        request_doc = create_backfill_request(
            request_id, game_ids, gap_type, message_data
        )

        # Trigger the backfill
        success = trigger_backfill(gap_type, game_dates, request_id)

        if success:
            update_backfill_status(request_id, 'triggered')
            send_backfill_notification(
                request_id, game_ids, gap_type, 'triggered', message_data
            )
            logger.info(f"Backfill triggered successfully for request {request_id}")
        else:
            update_backfill_status(request_id, 'failed', 'Trigger failed')
            send_backfill_notification(
                request_id, game_ids, gap_type, 'failed', message_data
            )
            logger.error(f"Backfill trigger failed for request {request_id}")

    except Exception as e:
        logger.error(f"Error handling gap detection event: {e}", exc_info=True)


# ============================================================================
# HTTP ENDPOINTS (for monitoring and manual triggers)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the backfill_trigger function."""
    return json.dumps({
        'status': 'healthy',
        'function': 'backfill_trigger',
        'cooldown_hours': BACKFILL_COOLDOWN_HOURS,
        'max_games_per_request': MAX_GAMES_PER_REQUEST,
        'supported_gap_types': list(GAP_TYPE_ACTIONS.keys())
    }), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def list_pending_backfills(request):
    """
    List all pending backfill requests.

    Query params:
        - status: Filter by status (pending, triggered, completed, failed)
        - limit: Maximum results (default 50)
    """
    try:
        status_filter = request.args.get('status')
        limit = int(request.args.get('limit', 50))

        query = db.collection(BACKFILL_COLLECTION)

        if status_filter:
            query = query.where('status', '==', status_filter)

        query = query.order_by('created_at', direction=firestore.Query.DESCENDING)
        query = query.limit(limit)

        results = []
        for doc in query.stream():
            data = doc.to_dict()
            # Convert timestamps for JSON serialization
            for key in ['created_at', 'updated_at', 'last_trigger_at', 'completed_at']:
                if data.get(key):
                    data[key] = data[key].isoformat() if hasattr(data[key], 'isoformat') else str(data[key])
            results.append(data)

        return json.dumps({
            'count': len(results),
            'requests': results
        }, indent=2), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error listing backfill requests: {e}")
        return json.dumps({
            'error': str(e)
        }), 500, {'Content-Type': 'application/json'}


@functions_framework.http
def manual_trigger(request):
    """
    Manually trigger a backfill request.

    POST body:
    {
        "game_dates": ["2025-12-29"],
        "gap_type": "boxscore"
    }
    """
    try:
        if request.method != 'POST':
            return json.dumps({'error': 'Method not allowed'}), 405, {'Content-Type': 'application/json'}

        data = request.get_json()
        if not data:
            return json.dumps({'error': 'No JSON body provided'}), 400, {'Content-Type': 'application/json'}

        game_dates = data.get('game_dates', [])
        gap_type = data.get('gap_type', 'boxscore')

        if not game_dates:
            return json.dumps({'error': 'game_dates is required'}), 400, {'Content-Type': 'application/json'}

        if gap_type not in GAP_TYPE_ACTIONS:
            return json.dumps({
                'error': f'Unknown gap_type: {gap_type}',
                'valid_types': list(GAP_TYPE_ACTIONS.keys())
            }), 400, {'Content-Type': 'application/json'}

        # Generate request ID
        request_id = generate_request_id(game_dates, gap_type)

        # Create message data
        message_data = {
            'game_ids': game_dates,
            'gap_type': gap_type,
            'detected_at': datetime.now(timezone.utc).isoformat(),
            'source': 'manual_trigger',
            'severity': 'info',
            'game_dates': game_dates
        }

        # Check for existing
        existing = check_pending_backfill(request_id)
        if existing:
            return json.dumps({
                'status': 'skipped',
                'message': 'Similar backfill request already pending',
                'existing_request': {
                    'request_id': request_id,
                    'created_at': str(existing.get('created_at'))
                }
            }), 200, {'Content-Type': 'application/json'}

        # Create and trigger
        create_backfill_request(request_id, game_dates, gap_type, message_data)
        success = trigger_backfill(gap_type, game_dates, request_id)

        if success:
            update_backfill_status(request_id, 'triggered')
            return json.dumps({
                'status': 'triggered',
                'request_id': request_id,
                'gap_type': gap_type,
                'game_dates': game_dates
            }), 200, {'Content-Type': 'application/json'}
        else:
            update_backfill_status(request_id, 'failed', 'Manual trigger failed')
            return json.dumps({
                'status': 'failed',
                'request_id': request_id,
                'error': 'Backfill trigger failed'
            }), 500, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in manual trigger: {e}")
        return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}


@functions_framework.http
def cleanup_old_requests(request):
    """
    Clean up old backfill request documents from Firestore.

    Query params:
        - days: Delete requests older than N days (default 30)
        - dry_run: If 'true', only report what would be deleted
    """
    try:
        days = int(request.args.get('days', 30))
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        query = db.collection(BACKFILL_COLLECTION).where(
            'created_at', '<', cutoff
        )

        deleted = 0
        for doc in query.stream():
            if dry_run:
                logger.info(f"[DRY RUN] Would delete: {doc.id}")
            else:
                doc.reference.delete()
                logger.info(f"Deleted: {doc.id}")
            deleted += 1

        return json.dumps({
            'deleted': deleted,
            'dry_run': dry_run,
            'cutoff_date': cutoff.isoformat(),
            'days': days
        }), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error cleaning up requests: {e}")
        return json.dumps({'error': str(e)}), 500, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import sys

    print("Backfill Trigger - Local Test")
    print("=" * 60)

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == 'list':
            # List pending requests
            class MockRequest:
                args = {'limit': '10'}
            result, _, _ = list_pending_backfills(MockRequest())
            print(result)

        elif command == 'trigger':
            # Manual trigger test
            if len(sys.argv) < 3:
                print("Usage: python main.py trigger YYYY-MM-DD [gap_type]")
                sys.exit(1)

            date = sys.argv[2]
            gap_type = sys.argv[3] if len(sys.argv) > 3 else 'boxscore'

            class MockRequest:
                method = 'POST'
                def get_json(self):
                    return {
                        'game_dates': [date],
                        'gap_type': gap_type
                    }

            result, status, _ = manual_trigger(MockRequest())
            print(f"Status: {status}")
            print(result)

        elif command == 'health':
            class MockRequest:
                pass
            result, _, _ = health(MockRequest())
            print(result)

        else:
            print(f"Unknown command: {command}")
            print("Commands: list, trigger, health")
    else:
        print("Usage: python main.py [command]")
        print("Commands:")
        print("  list              - List pending backfill requests")
        print("  trigger DATE      - Manually trigger backfill for a date")
        print("  health            - Check function health")
