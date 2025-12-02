"""
Phase Transition Monitor

Cloud Function that monitors phase transitions for stuck states and sends alerts.

Triggered by: Cloud Scheduler (hourly or as configured)

For each phase transition (2→3, 3→4, 4→5):
1. Check Firestore for documents with incomplete status
2. If document age > timeout threshold AND not triggered:
   - Calculate missing processors
   - Send alert via email/Slack
3. Optionally: Auto-retry missing processors

Monitored Collections:
- phase2_completion: Phase 2 → Phase 3
- phase3_completion: Phase 3 → Phase 4
- phase4_completion: Phase 4 → Phase 5

Version: 1.0
Created: 2025-12-02
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

from google.cloud import firestore
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Timeout thresholds (hours)
PHASE2_TIMEOUT_HOURS = float(os.environ.get('PHASE2_TIMEOUT_HOURS', '2'))
PHASE3_TIMEOUT_HOURS = float(os.environ.get('PHASE3_TIMEOUT_HOURS', '1'))
PHASE4_TIMEOUT_HOURS = float(os.environ.get('PHASE4_TIMEOUT_HOURS', '1'))

# Import expected processors from centralized config
try:
    from shared.config.orchestration_config import get_orchestration_config
    _config = get_orchestration_config()
    PHASE2_EXPECTED = set(_config.phase_transitions.phase2_expected_processors)
    PHASE3_EXPECTED = set(_config.phase_transitions.phase3_expected_processors)
    PHASE4_EXPECTED = set(_config.phase_transitions.phase4_expected_processors)
    logger.info("Loaded expected processors from config")
except ImportError:
    logger.warning("Could not import orchestration_config, using fallback")
    PHASE2_EXPECTED = set([
        'bdl_player_boxscores', 'bdl_injuries', 'nbac_gamebook_player_stats',
        'nbac_team_boxscore', 'nbac_schedule', 'nbac_injury_report',
        'nbac_play_by_play', 'espn_boxscores', 'espn_team_rosters',
        'espn_scoreboard', 'odds_api_game_lines', 'odds_api_player_points_props',
        'bettingpros_player_points_props', 'bigdataball_play_by_play',
        'bigdataball_schedule', 'nbac_player_list_current', 'nbac_team_list',
        'nbac_standings', 'nbac_active_players', 'nbac_referee_assignments',
        'nbac_officials',
    ])
    PHASE3_EXPECTED = set([
        'player_game_summary', 'team_defense_game_summary',
        'team_offense_game_summary', 'upcoming_player_game_context',
        'upcoming_team_game_context',
    ])
    PHASE4_EXPECTED = set([
        'team_defense_zone_analysis', 'player_shot_zone_analysis',
        'player_composite_factors', 'player_daily_cache', 'ml_feature_store',
    ])

# Initialize Firestore client
db = firestore.Client()


@functions_framework.http
def monitor_transitions(request):
    """
    Monitor all phase transitions for stuck states.

    Called by Cloud Scheduler (hourly recommended).

    Returns:
        JSON response with monitoring results
    """
    logger.info("=" * 60)
    logger.info("🔍 Phase Transition Monitor Starting")
    logger.info("=" * 60)

    results = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'phase2_to_phase3': check_phase_transition(
            collection='phase2_completion',
            expected_processors=PHASE2_EXPECTED,
            timeout_hours=PHASE2_TIMEOUT_HOURS,
            phase_name='Phase 2 → Phase 3'
        ),
        'phase3_to_phase4': check_phase_transition(
            collection='phase3_completion',
            expected_processors=PHASE3_EXPECTED,
            timeout_hours=PHASE3_TIMEOUT_HOURS,
            phase_name='Phase 3 → Phase 4'
        ),
        'phase4_to_phase5': check_phase_transition(
            collection='phase4_completion',
            expected_processors=PHASE4_EXPECTED,
            timeout_hours=PHASE4_TIMEOUT_HOURS,
            phase_name='Phase 4 → Phase 5'
        ),
    }

    # Summarize
    stuck_count = sum(
        len(r.get('stuck_transitions', []))
        for r in results.values()
        if isinstance(r, dict)
    )

    results['summary'] = {
        'total_stuck': stuck_count,
        'status': 'healthy' if stuck_count == 0 else 'stuck_detected'
    }

    if stuck_count > 0:
        logger.warning(f"⚠️  Found {stuck_count} stuck transition(s)")
        # Send alerts for stuck transitions
        send_alerts(results)
    else:
        logger.info("✅ All transitions healthy")

    logger.info("=" * 60)
    logger.info("🔍 Phase Transition Monitor Complete")
    logger.info("=" * 60)

    return json.dumps(results, indent=2, default=str), 200, {'Content-Type': 'application/json'}


def check_phase_transition(
    collection: str,
    expected_processors: Set[str],
    timeout_hours: float,
    phase_name: str
) -> Dict:
    """
    Check a single phase transition for stuck states.

    Args:
        collection: Firestore collection name
        expected_processors: Set of expected processor names
        timeout_hours: Hours before considering stuck
        phase_name: Human-readable phase name

    Returns:
        Dict with check results
    """
    logger.info(f"\n📊 Checking {phase_name}")
    logger.info(f"   Collection: {collection}")
    logger.info(f"   Expected: {len(expected_processors)} processors")
    logger.info(f"   Timeout: {timeout_hours} hours")

    # Calculate cutoff time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

    # Query for recent documents that are NOT triggered
    # Only check today's and yesterday's dates
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    stuck_transitions = []
    healthy_count = 0

    for check_date in [today, yesterday]:
        date_str = check_date.isoformat()
        doc_ref = db.collection(collection).document(date_str)
        doc = doc_ref.get()

        if not doc.exists:
            logger.debug(f"   {date_str}: No document (not started)")
            continue

        data = doc.to_dict()

        # Skip if already triggered
        if data.get('_triggered'):
            logger.debug(f"   {date_str}: Already triggered ✓")
            healthy_count += 1
            continue

        # Get completed processors
        completed = set(k for k in data.keys() if not k.startswith('_'))
        missing = expected_processors - completed

        # Calculate age of document
        # Use the earliest completion timestamp
        earliest_completion = None
        for proc_name, proc_data in data.items():
            if proc_name.startswith('_'):
                continue
            if isinstance(proc_data, dict) and 'completed_at' in proc_data:
                comp_time = proc_data['completed_at']
                if hasattr(comp_time, 'timestamp'):
                    # Firestore timestamp
                    if earliest_completion is None or comp_time < earliest_completion:
                        earliest_completion = comp_time

        if earliest_completion is None:
            # No timestamps found, skip
            logger.debug(f"   {date_str}: No timestamps found")
            continue

        # Check if stuck (document older than timeout and not complete)
        if missing and earliest_completion < cutoff_time:
            age_hours = (datetime.now(timezone.utc) - earliest_completion.replace(tzinfo=timezone.utc)).total_seconds() / 3600

            stuck_info = {
                'game_date': date_str,
                'completed_count': len(completed),
                'expected_count': len(expected_processors),
                'missing_processors': list(missing),
                'age_hours': round(age_hours, 1),
                'timeout_hours': timeout_hours
            }

            logger.warning(
                f"   {date_str}: STUCK! {len(completed)}/{len(expected_processors)} "
                f"(missing: {list(missing)[:3]}{'...' if len(missing) > 3 else ''})"
            )
            stuck_transitions.append(stuck_info)
        else:
            logger.debug(f"   {date_str}: In progress ({len(completed)}/{len(expected_processors)})")

    return {
        'healthy_count': healthy_count,
        'stuck_transitions': stuck_transitions,
        'status': 'stuck' if stuck_transitions else 'healthy'
    }


def send_alerts(results: Dict) -> None:
    """
    Send alerts for stuck transitions.

    Currently logs warnings. Can be extended to send:
    - Email via SES
    - Slack notifications
    - PagerDuty alerts

    Args:
        results: Monitoring results with stuck transitions
    """
    stuck_transitions = []

    for phase_name, phase_results in results.items():
        if phase_name in ('timestamp', 'summary'):
            continue
        if isinstance(phase_results, dict) and phase_results.get('stuck_transitions'):
            for stuck in phase_results['stuck_transitions']:
                stuck_transitions.append({
                    'phase': phase_name,
                    **stuck
                })

    if not stuck_transitions:
        return

    # Build alert message
    alert_lines = [
        "🚨 STUCK PHASE TRANSITIONS DETECTED",
        "",
        f"Time: {datetime.now(timezone.utc).isoformat()}",
        f"Total stuck: {len(stuck_transitions)}",
        "",
    ]

    for stuck in stuck_transitions:
        alert_lines.extend([
            f"📍 {stuck['phase']}",
            f"   Game Date: {stuck['game_date']}",
            f"   Progress: {stuck['completed_count']}/{stuck['expected_count']}",
            f"   Age: {stuck['age_hours']} hours (timeout: {stuck['timeout_hours']}h)",
            f"   Missing: {', '.join(stuck['missing_processors'][:5])}",
            "",
        ])

    alert_message = "\n".join(alert_lines)
    logger.warning(alert_message)

    # TODO: Add actual alert sending
    # - Email via shared/alerts/email_alerter.py
    # - Slack via webhook
    # For now, just log (Cloud Logging will capture this)

    try:
        # Try to send via existing alert system
        from shared.alerts.email_alerter import send_alert_email

        send_alert_email(
            subject="🚨 NBA Pipeline: Stuck Phase Transitions Detected",
            body=alert_message,
            level='warning'
        )
        logger.info("Alert email sent successfully")
    except ImportError:
        logger.debug("Email alerter not available, skipping email")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")


def get_all_transition_status() -> Dict:
    """
    Get current status of all phase transitions (for debugging).

    Returns:
        Dict with all transition statuses
    """
    today = datetime.now(timezone.utc).date().isoformat()

    return {
        'phase2_completion': get_document_status('phase2_completion', today),
        'phase3_completion': get_document_status('phase3_completion', today),
        'phase4_completion': get_document_status('phase4_completion', today),
    }


def get_document_status(collection: str, game_date: str) -> Dict:
    """Get status of a single Firestore document."""
    doc = db.collection(collection).document(game_date).get()

    if not doc.exists:
        return {'status': 'not_started'}

    data = doc.to_dict()
    completed = [k for k in data.keys() if not k.startswith('_')]

    return {
        'status': 'triggered' if data.get('_triggered') else 'in_progress',
        'completed_count': len(completed),
        'triggered_at': data.get('_triggered_at')
    }


# For local testing
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'status':
        # Quick status check
        status = get_all_transition_status()
        print(json.dumps(status, indent=2, default=str))
    else:
        # Run full monitor
        class FakeRequest:
            pass
        result, status_code, _ = monitor_transitions(FakeRequest())
        print(result)
