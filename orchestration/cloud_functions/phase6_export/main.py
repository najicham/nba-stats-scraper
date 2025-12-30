"""
Phase 6 Export Cloud Function

Receives Pub/Sub messages from Cloud Scheduler or Phase 5→6 Orchestrator
and triggers Phase 6 publishing (export prediction data to GCS).

Trigger: Pub/Sub topic `nba-phase6-export-trigger`

Message formats:
1. Daily results export (from Scheduler):
   {"export_types": ["results", "performance", "best-bets"], "target_date": "yesterday"}

2. Tonight's picks export (from Orchestrator):
   {"export_types": ["tonight", "tonight-players", "predictions", "best-bets", "streaks"],
    "target_date": "2025-12-12", "correlation_id": "abc-123"}

3. Player profiles export (from Scheduler):
   {"players": true, "min_games": 5}

Publishes completion to: nba-phase6-export-complete

Version: 1.1
Created: 2025-12-12
Updated: 2025-12-12 - Added completion publishing, correlation ID logging
"""

import base64
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import functions_framework
from google.cloud import pubsub_v1

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'nba-props-platform-api')
PHASE6_COMPLETE_TOPIC = 'nba-phase6-export-complete'

# Lazy-loaded publisher
_publisher = None


def get_publisher():
    """Get or create Pub/Sub publisher."""
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def validate_predictions_exist(target_date: str, min_predictions: int = 50) -> Dict:
    """
    Validate that predictions exist for a target date before exporting.

    This pre-export validation prevents Phase 6 from exporting empty/incomplete
    data when predictions are missing.

    Args:
        target_date: Date to validate (YYYY-MM-DD format)
        min_predictions: Minimum number of predictions required (default 50)

    Returns:
        Dict with:
        - ready: bool - True if ready for export
        - predictions_count: int
        - players_count: int
        - missing_reason: str (if not ready)
    """
    from google.cloud import bigquery

    bq_client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT
        COUNT(*) as predictions,
        COUNT(DISTINCT player_lookup) as players
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}'
      AND is_active = TRUE
    """

    try:
        result = bq_client.query(query).to_dataframe()
        predictions_count = int(result.iloc[0]['predictions'])
        players_count = int(result.iloc[0]['players'])

        if predictions_count == 0:
            return {
                'ready': False,
                'predictions_count': 0,
                'players_count': 0,
                'missing_reason': 'no_predictions'
            }

        if predictions_count < min_predictions:
            return {
                'ready': False,
                'predictions_count': predictions_count,
                'players_count': players_count,
                'missing_reason': f'insufficient_predictions ({predictions_count} < {min_predictions})'
            }

        return {
            'ready': True,
            'predictions_count': predictions_count,
            'players_count': players_count,
            'missing_reason': None
        }

    except Exception as e:
        logger.error(f"Error validating predictions: {e}")
        return {
            'ready': False,
            'predictions_count': 0,
            'players_count': 0,
            'missing_reason': f'validation_error: {str(e)}'
        }


def trigger_self_heal(target_date: str) -> bool:
    """
    Trigger self-heal pipeline when predictions are missing.

    Called from Phase 6 pre-export validation when predictions are missing.
    This provides faster recovery than waiting for the scheduled self-heal.

    Args:
        target_date: Date to heal

    Returns:
        True if self-heal was triggered successfully
    """
    import urllib.request

    SELF_HEAL_URL = "https://self-heal-f7p3g7f6ya-wl.a.run.app"

    logger.warning(f"Pre-export validation failed - triggering self-heal for {target_date}")

    try:
        # Get identity token for authenticated call
        metadata_url = f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience={SELF_HEAL_URL}"
        req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                token = response.read().decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not get auth token (expected in local dev): {e}")
            token = None

        # Trigger self-heal
        import requests
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.get(
            SELF_HEAL_URL,
            headers=headers,
            timeout=120
        )

        if response.status_code == 200:
            logger.info(f"Self-heal triggered successfully: {response.json()}")
            return True
        else:
            logger.error(f"Self-heal trigger failed: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Error triggering self-heal: {e}")
        return False


def get_target_date(target_date_str: str) -> str:
    """
    Convert target_date string to actual date.

    Args:
        target_date_str: "today", "yesterday", or "YYYY-MM-DD"

    Returns:
        Date string in YYYY-MM-DD format
    """
    today = datetime.utcnow().date()

    if target_date_str == "today":
        return today.strftime('%Y-%m-%d')
    elif target_date_str == "yesterday":
        return (today - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        # Assume it's already a date string
        return target_date_str


def run_daily_export(
    target_date: str,
    export_types: List[str],
    update_latest: bool = True
) -> Dict:
    """
    Run daily export for specified types.

    Args:
        target_date: Date to export
        export_types: List of export types
        update_latest: Whether to update latest.json

    Returns:
        Export result dictionary
    """
    # Import here to avoid import errors in Cloud Function
    sys.path.insert(0, '/workspace')

    from backfill_jobs.publishing.daily_export import export_date

    logger.info(f"Running daily export for {target_date}, types={export_types}")

    result = export_date(
        target_date=target_date,
        update_latest=update_latest,
        export_types=export_types
    )

    logger.info(f"Export result: {result['status']}, paths={result.get('paths', {})}")

    return result


def run_player_export(min_games: int = 5) -> Dict:
    """
    Run player profiles export.

    Args:
        min_games: Minimum games threshold

    Returns:
        Export result dictionary
    """
    sys.path.insert(0, '/workspace')

    from backfill_jobs.publishing.daily_export import export_players

    logger.info(f"Running player profiles export (min_games={min_games})")

    result = export_players(min_games=min_games)

    logger.info(f"Player export result: {result['status']}, count={result.get('count', 0)}")

    return result


@functions_framework.cloud_event
def main(cloud_event):
    """
    Handle Phase 6 export trigger from Pub/Sub.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Raises:
        Exception: Re-raised to trigger Pub/Sub retry on transient failures
    """
    start_time = time.time()

    # Parse Pub/Sub message
    message_data = parse_pubsub_message(cloud_event)

    # Extract correlation ID for tracing
    correlation_id = message_data.get('correlation_id', 'scheduled')
    trigger_source = message_data.get('trigger_source', 'unknown')

    logger.info(
        f"[{correlation_id}] Received export trigger from {trigger_source}: "
        f"{json.dumps(message_data, default=str)}"
    )

    result = None
    export_type = None

    try:
        # Determine export type
        if message_data.get('players'):
            # Player profiles export
            export_type = 'players'
            min_games = message_data.get('min_games', 5)
            result = run_player_export(min_games=min_games)

        elif message_data.get('export_types'):
            # Daily/tonight export
            export_type = 'daily'
            target_date_str = message_data.get('target_date', 'yesterday')
            target_date = get_target_date(target_date_str)
            export_types = message_data.get('export_types', [])
            update_latest = message_data.get('update_latest', True)

            # Pre-export validation for tonight's picks (requires predictions)
            tonight_types = {'tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks'}
            requires_predictions = bool(tonight_types.intersection(set(export_types)))

            if requires_predictions:
                validation = validate_predictions_exist(target_date)
                logger.info(
                    f"[{correlation_id}] Pre-export validation for {target_date}: "
                    f"predictions={validation['predictions_count']}, "
                    f"players={validation['players_count']}, "
                    f"ready={validation['ready']}"
                )

                if not validation['ready']:
                    logger.error(
                        f"[{correlation_id}] Pre-export validation FAILED: {validation['missing_reason']}"
                    )
                    # Trigger self-heal automatically
                    self_heal_triggered = trigger_self_heal(target_date)

                    result = {
                        'status': 'validation_failed',
                        'target_date': target_date,
                        'export_types': export_types,
                        'validation': validation,
                        'self_heal_triggered': self_heal_triggered,
                        'errors': [f"Pre-export validation failed: {validation['missing_reason']}"]
                    }

                    # Publish completion with validation failure
                    duration_seconds = time.time() - start_time
                    publish_completion(
                        correlation_id=correlation_id,
                        export_type=export_type,
                        result=result,
                        duration_seconds=duration_seconds,
                        message_data=message_data
                    )
                    return result

            result = run_daily_export(
                target_date=target_date,
                export_types=export_types,
                update_latest=update_latest
            )

        else:
            # Default: run full daily export for yesterday
            export_type = 'daily'
            target_date = get_target_date('yesterday')
            result = run_daily_export(
                target_date=target_date,
                export_types=['results', 'performance', 'best-bets', 'predictions'],
                update_latest=True
            )

        # Calculate duration
        duration_seconds = time.time() - start_time

        # Log result
        if result.get('status') == 'success':
            logger.info(
                f"[{correlation_id}] Export completed successfully in {duration_seconds:.1f}s"
            )
        elif result.get('status') == 'partial':
            logger.warning(
                f"[{correlation_id}] Export completed with errors in {duration_seconds:.1f}s: "
                f"{result.get('errors')}"
            )
        else:
            logger.error(
                f"[{correlation_id}] Export failed in {duration_seconds:.1f}s: "
                f"{result.get('errors')}"
            )

        # Publish completion event
        publish_completion(
            correlation_id=correlation_id,
            export_type=export_type,
            result=result,
            duration_seconds=duration_seconds,
            message_data=message_data
        )

        return result

    except Exception as e:
        duration_seconds = time.time() - start_time
        logger.error(
            f"[{correlation_id}] Error in Phase 6 export after {duration_seconds:.1f}s: {e}",
            exc_info=True
        )
        # Re-raise to trigger Pub/Sub retry
        raise


def publish_completion(
    correlation_id: str,
    export_type: str,
    result: Dict,
    duration_seconds: float,
    message_data: Dict
) -> Optional[str]:
    """
    Publish completion event for monitoring.

    Args:
        correlation_id: Correlation ID for tracing
        export_type: Type of export (daily, players)
        result: Export result dictionary
        duration_seconds: Execution time
        message_data: Original trigger message

    Returns:
        Message ID if published, None on failure
    """
    try:
        publisher = get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, PHASE6_COMPLETE_TOPIC)

        completion_message = {
            'processor_name': 'Phase6Export',
            'phase': 'phase_6_publishing',
            'correlation_id': correlation_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': result.get('status', 'unknown'),
            'export_type': export_type,
            'duration_seconds': round(duration_seconds, 2),
            'paths': result.get('paths', {}),
            'errors': result.get('errors', []),
            'trigger_source': message_data.get('trigger_source', 'unknown'),
            'target_date': message_data.get('target_date'),
            'export_types': message_data.get('export_types', []),
        }

        future = publisher.publish(
            topic_path,
            data=json.dumps(completion_message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(f"[{correlation_id}] Published completion event: {message_id}")
        return message_id

    except Exception as e:
        # Don't fail the export if completion publishing fails
        logger.warning(f"[{correlation_id}] Failed to publish completion event: {e}")
        return None


def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dictionary with message data
    """
    try:
        pubsub_message = cloud_event.data.get('message', {})

        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
        else:
            message_data = {}

        return message_data

    except Exception as e:
        logger.error(f"Failed to parse Pub/Sub message: {e}")
        return {}


# For local testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 6 Export')
    parser.add_argument('--date', type=str, default='yesterday', help='Target date')
    parser.add_argument('--types', type=str, default='results,best-bets', help='Export types')
    parser.add_argument('--players', action='store_true', help='Export player profiles')
    parser.add_argument('--min-games', type=int, default=5, help='Min games for players')

    args = parser.parse_args()

    if args.players:
        result = run_player_export(min_games=args.min_games)
    else:
        target_date = get_target_date(args.date)
        export_types = args.types.split(',')
        result = run_daily_export(target_date, export_types)

    print(json.dumps(result, indent=2, default=str))
