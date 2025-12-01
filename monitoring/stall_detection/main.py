"""
Pipeline Stall Detection Cloud Function

Periodically checks for stalled pipeline phases and sends alerts.
Triggered by Cloud Scheduler every 15 minutes during processing hours.

Architecture:
- Triggered by: HTTP (Cloud Scheduler)
- Queries: Firestore orchestration documents
- Sends: Email/Slack alerts via notification system

Stall Detection Logic:
- Phase 2→3: Check phase2_completion collection for dates with incomplete processors
- Phase 3→4: Check phase3_completion collection for dates with incomplete processors
- Alert if waiting > STALL_THRESHOLD_MINUTES without all processors complete

Version: 1.0
Created: 2025-11-30
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from google.cloud import firestore
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
STALL_THRESHOLD_MINUTES = int(os.environ.get('STALL_THRESHOLD_MINUTES', '30'))

# Phase configuration
PHASE_CONFIG = {
    'phase2_completion': {
        'waiting_phase': 'Phase 3',
        'blocked_by_phase': 'Phase 2',
        'expected_count': 21,
        'collection': 'phase2_completion'
    },
    'phase3_completion': {
        'waiting_phase': 'Phase 4',
        'blocked_by_phase': 'Phase 3',
        'expected_count': 5,
        'collection': 'phase3_completion'
    }
}

# Initialize Firestore client
db = firestore.Client()


@functions_framework.http
def check_pipeline_stalls(request):
    """
    Check for stalled pipeline phases and send alerts.

    Triggered by Cloud Scheduler every 15 minutes.

    Query params:
        - dry_run: If 'true', don't send alerts, just report findings

    Returns:
        JSON response with stall detection results
    """
    try:
        request_args = request.args
        dry_run = request_args.get('dry_run', 'false').lower() == 'true'

        logger.info(f"Checking for pipeline stalls (dry_run={dry_run})")

        stalls_found = []
        alerts_sent = []

        # Check each phase transition
        for phase_key, config in PHASE_CONFIG.items():
            stalled_dates = check_phase_stalls(
                collection_name=config['collection'],
                expected_count=config['expected_count'],
                waiting_phase=config['waiting_phase'],
                blocked_by_phase=config['blocked_by_phase']
            )

            for stall in stalled_dates:
                stalls_found.append(stall)

                if not dry_run and not stall.get('alert_already_sent'):
                    # Send alert
                    success = send_stall_alert(stall)
                    if success:
                        alerts_sent.append(stall['game_date'])
                        # Mark alert as sent in Firestore
                        mark_alert_sent(config['collection'], stall['game_date'])

        # Summary
        result = {
            'status': 'success',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'stalls_found': len(stalls_found),
            'alerts_sent': len(alerts_sent),
            'dry_run': dry_run,
            'details': stalls_found
        }

        if stalls_found:
            logger.warning(f"Found {len(stalls_found)} stalled pipelines: {[s['game_date'] for s in stalls_found]}")
        else:
            logger.info("No pipeline stalls detected")

        return result, 200

    except Exception as e:
        logger.error(f"Error checking pipeline stalls: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}, 500


def check_phase_stalls(
    collection_name: str,
    expected_count: int,
    waiting_phase: str,
    blocked_by_phase: str
) -> List[Dict]:
    """
    Check a Firestore collection for stalled orchestration documents.

    Args:
        collection_name: Firestore collection to check
        expected_count: Expected number of processors
        waiting_phase: Phase that is waiting (for alert message)
        blocked_by_phase: Phase being waited on (for alert message)

    Returns:
        List of stalled date info dictionaries
    """
    stalls = []

    try:
        # Get today and yesterday (the most likely dates to have active processing)
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        dates_to_check = [today.isoformat(), yesterday.isoformat()]

        for game_date in dates_to_check:
            doc_ref = db.collection(collection_name).document(game_date)
            doc = doc_ref.get()

            if not doc.exists:
                continue

            data = doc.to_dict()

            # Skip if already triggered (completed successfully)
            if data.get('_triggered'):
                continue

            # Count completed processors
            completed_processors = [k for k in data.keys() if not k.startswith('_')]
            completed_count = len(completed_processors)

            # Skip if not yet started (no completions)
            if completed_count == 0:
                continue

            # Get first completion time
            first_completion_at = get_first_completion_time(data)
            if not first_completion_at:
                continue

            # Calculate wait time
            wait_minutes = (datetime.now(timezone.utc) - first_completion_at).total_seconds() / 60

            # Check if stalled
            if wait_minutes > STALL_THRESHOLD_MINUTES and completed_count < expected_count:
                missing_count = expected_count - completed_count

                stalls.append({
                    'game_date': game_date,
                    'waiting_phase': waiting_phase,
                    'blocked_by_phase': blocked_by_phase,
                    'wait_minutes': int(wait_minutes),
                    'completed_count': completed_count,
                    'total_count': expected_count,
                    'missing_count': missing_count,
                    'completed_processors': completed_processors,
                    'first_completion_at': first_completion_at.isoformat(),
                    'alert_already_sent': data.get('_stall_alert_sent', False)
                })

                logger.warning(
                    f"Stall detected: {game_date} - {waiting_phase} waiting {int(wait_minutes)} mins "
                    f"for {blocked_by_phase} ({completed_count}/{expected_count} complete)"
                )

    except Exception as e:
        logger.error(f"Error checking {collection_name}: {e}")

    return stalls


def get_first_completion_time(data: Dict) -> Optional[datetime]:
    """
    Get the earliest completion timestamp from orchestration document.

    Args:
        data: Firestore document data

    Returns:
        Earliest completion datetime, or None if not found
    """
    earliest = None

    for key, value in data.items():
        if key.startswith('_'):
            continue

        if isinstance(value, dict) and 'completed_at' in value:
            completed_at = value['completed_at']
            # Handle Firestore timestamp
            if hasattr(completed_at, 'timestamp'):
                ts = datetime.fromtimestamp(completed_at.timestamp(), tz=timezone.utc)
            elif isinstance(completed_at, datetime):
                ts = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=timezone.utc)
            else:
                continue

            if earliest is None or ts < earliest:
                earliest = ts

    return earliest


def get_missing_processors(completed: List[str], phase: str) -> List[str]:
    """
    Determine which processors are missing based on phase.

    Args:
        completed: List of completed processor names
        phase: Phase name to get expected processors for

    Returns:
        List of missing processor names
    """
    # Define expected processors by phase
    expected_phase2 = [
        'BdlGamesProcessor', 'BdlPlayerSeasonStatsProcessor', 'BdlTeamSeasonStatsProcessor',
        'EspnGamesProcessor', 'EspnPlayerSeasonStatsProcessor', 'EspnTeamStandingsProcessor',
        'NbacomBoxScoresProcessor', 'NbacomGamesProcessor', 'NbacomInjuriesProcessor',
        'NbacomPlayerSeasonStatsProcessor', 'NbacomTeamSeasonStatsProcessor',
        'OddsAPIProcessor', 'PbpStatsGamesProcessor', 'PbpStatsPlayByPlayProcessor',
        'PbpStatsPlayerBoxScoreProcessor', 'PbpStatsPlayerSeasonStatsProcessor',
        'PbpStatsTeamBoxScoreProcessor', 'PbpStatsTeamSeasonStatsProcessor',
        'RegistryProcessor', 'RotowireInjuriesProcessor', 'RotowireLineupProcessor'
    ]

    expected_phase3 = [
        'PlayerGameSummaryProcessor', 'TeamDefenseGameSummaryProcessor',
        'TeamOffenseGameSummaryProcessor', 'UpcomingPlayerGameContextProcessor',
        'UpcomingTeamGameContextProcessor'
    ]

    if 'Phase 2' in phase:
        expected = expected_phase2
    elif 'Phase 3' in phase:
        expected = expected_phase3
    else:
        return []

    completed_set = set(completed)
    return [p for p in expected if p not in completed_set]


def send_stall_alert(stall: Dict) -> bool:
    """
    Send stall alert via email and Slack.

    Args:
        stall: Stall info dictionary

    Returns:
        True if alert sent successfully
    """
    email_success = False
    slack_success = False

    # Get missing processors
    missing_processors = get_missing_processors(
        stall['completed_processors'],
        stall['blocked_by_phase']
    )

    # Build alert data
    stall_data = {
        'waiting_phase': stall['waiting_phase'],
        'blocked_by_phase': stall['blocked_by_phase'],
        'wait_minutes': stall['wait_minutes'],
        'missing_processors': missing_processors or [f"Unknown ({stall['missing_count']} missing)"],
        'completed_count': stall['completed_count'],
        'total_count': stall['total_count']
    }

    # Send email
    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
        email_success = alerter.send_dependency_stall_alert(stall_data)
        if email_success:
            logger.info(f"📧 Stall alert email sent for {stall['game_date']}")
    except ImportError as e:
        logger.warning(f"Email alerter not available: {e}")
    except Exception as e:
        logger.error(f"Error sending stall email: {e}")

    # Send to Slack #nba-alerts channel
    try:
        from shared.utils.slack_channels import send_stall_alert_to_slack
        slack_success = send_stall_alert_to_slack(stall_data)
        if slack_success:
            logger.info(f"💬 Stall alert sent to Slack for {stall['game_date']}")
    except Exception as e:
        logger.debug(f"Slack notification skipped: {e}")

    return email_success or slack_success


def mark_alert_sent(collection_name: str, game_date: str):
    """
    Mark that a stall alert has been sent for this date.

    Prevents duplicate alerts for the same stall.

    Args:
        collection_name: Firestore collection
        game_date: Date document ID
    """
    try:
        doc_ref = db.collection(collection_name).document(game_date)
        doc_ref.update({
            '_stall_alert_sent': True,
            '_stall_alert_sent_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"Marked stall alert sent for {collection_name}/{game_date}")
    except Exception as e:
        logger.error(f"Error marking alert sent: {e}")


# For local testing
if __name__ == '__main__':
    import sys

    # Set up test environment
    os.environ['AWS_SES_ACCESS_KEY_ID'] = os.environ.get('AWS_SES_ACCESS_KEY_ID', '')
    os.environ['AWS_SES_SECRET_ACCESS_KEY'] = os.environ.get('AWS_SES_SECRET_ACCESS_KEY', '')
    os.environ['AWS_SES_REGION'] = 'us-west-2'
    os.environ['AWS_SES_FROM_EMAIL'] = 'alert@989.ninja'
    os.environ['EMAIL_ALERTS_TO'] = os.environ.get('EMAIL_ALERTS_TO', 'nchammas@gmail.com')

    print("Checking for pipeline stalls...")

    # Check stalls
    for phase_key, config in PHASE_CONFIG.items():
        print(f"\nChecking {phase_key}...")
        stalls = check_phase_stalls(
            collection_name=config['collection'],
            expected_count=config['expected_count'],
            waiting_phase=config['waiting_phase'],
            blocked_by_phase=config['blocked_by_phase']
        )

        if stalls:
            print(f"  Found {len(stalls)} stalls:")
            for s in stalls:
                print(f"    - {s['game_date']}: {s['completed_count']}/{s['total_count']} "
                      f"(waiting {s['wait_minutes']} mins)")

                if '--send' in sys.argv:
                    print("    Sending alert...")
                    send_stall_alert(s)
        else:
            print("  No stalls found")

    if '--send' not in sys.argv:
        print("\nAdd --send flag to send alerts")
