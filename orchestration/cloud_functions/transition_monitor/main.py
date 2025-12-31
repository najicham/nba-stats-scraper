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

# Document TTL (days) - documents older than this will be cleaned up
DOCUMENT_TTL_DAYS = int(os.environ.get('DOCUMENT_TTL_DAYS', '30'))

# Collections to clean up (phase completion tracking documents)
CLEANUP_COLLECTIONS = [
    'phase1_completion',
    'phase2_completion',
    'phase3_completion',
    'phase4_completion',
    'phase5_completion',
    'phase6_completion',
]

# Timeout thresholds (hours)
PHASE2_TIMEOUT_HOURS = float(os.environ.get('PHASE2_TIMEOUT_HOURS', '2'))
PHASE3_TIMEOUT_HOURS = float(os.environ.get('PHASE3_TIMEOUT_HOURS', '1'))
PHASE4_TIMEOUT_HOURS = float(os.environ.get('PHASE4_TIMEOUT_HOURS', '1'))

# How many days back to check for stuck transitions (default: 7)
# This catches weekend transitions that might be missed if only checking today/yesterday
LOOKBACK_DAYS = int(os.environ.get('TRANSITION_LOOKBACK_DAYS', '7'))

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


def check_player_game_summary_for_yesterday() -> Dict:
    """
    Check if player_game_summary has data for yesterday.

    This is critical for grading - if player_game_summary is empty for yesterday,
    grading will fail. This check catches the scenario where Phase 3 analytics
    didn't run for yesterday's completed games.

    Returns:
        Dict with check results:
        - has_data: bool
        - row_count: int
        - game_date: str
        - status: 'healthy', 'warning', or 'critical'
    """
    from google.cloud import bigquery

    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    try:
        bq_client = bigquery.Client(project=PROJECT_ID)

        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date = '{yesterday}'
        """

        result = bq_client.query(query).to_dataframe()
        row_count = int(result.iloc[0]['cnt'])

        # Also check if there were games yesterday
        games_query = f"""
        SELECT COUNT(DISTINCT game_id) as game_count
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = '{yesterday}'
          AND game_status_text = 'Final'
        """
        games_result = bq_client.query(games_query).to_dataframe()
        game_count = int(games_result.iloc[0]['game_count'])

        if game_count == 0:
            # No games yesterday, so no data expected
            return {
                'has_data': True,
                'row_count': 0,
                'game_count': 0,
                'game_date': yesterday,
                'status': 'healthy',
                'message': 'No games scheduled for yesterday'
            }

        if row_count == 0:
            return {
                'has_data': False,
                'row_count': 0,
                'game_count': game_count,
                'game_date': yesterday,
                'status': 'critical',
                'message': f'CRITICAL: player_game_summary is EMPTY for {yesterday} but {game_count} games were played. Grading will fail!'
            }

        # Calculate expected row count (roughly 13 active players per game × 2 teams)
        expected_min = game_count * 20  # Conservative estimate
        if row_count < expected_min:
            return {
                'has_data': True,
                'row_count': row_count,
                'game_count': game_count,
                'game_date': yesterday,
                'status': 'warning',
                'message': f'Low row count: {row_count} rows for {game_count} games (expected ~{expected_min}+)'
            }

        return {
            'has_data': True,
            'row_count': row_count,
            'game_count': game_count,
            'game_date': yesterday,
            'status': 'healthy',
            'message': f'OK: {row_count} rows for {game_count} games'
        }

    except Exception as e:
        logger.error(f"Error checking player_game_summary: {e}")
        return {
            'has_data': False,
            'row_count': 0,
            'game_count': 0,
            'game_date': yesterday,
            'status': 'error',
            'message': f'Error checking: {str(e)}'
        }


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
        # Critical check: player_game_summary for yesterday (grading dependency)
        'player_game_summary_check': check_player_game_summary_for_yesterday(),
    }

    # Summarize
    stuck_count = sum(
        len(r.get('stuck_transitions', []))
        for r in results.values()
        if isinstance(r, dict) and 'stuck_transitions' in r
    )

    # Check player_game_summary status
    pgs_check = results.get('player_game_summary_check', {})
    pgs_status = pgs_check.get('status', 'unknown')

    # Determine overall status
    if pgs_status == 'critical':
        overall_status = 'critical'
    elif stuck_count > 0:
        overall_status = 'stuck_detected'
    elif pgs_status == 'warning':
        overall_status = 'warning'
    else:
        overall_status = 'healthy'

    results['summary'] = {
        'total_stuck': stuck_count,
        'player_game_summary_status': pgs_status,
        'status': overall_status
    }

    # Send alerts if needed
    if overall_status == 'critical':
        logger.error(f"🚨 CRITICAL: {pgs_check.get('message', 'player_game_summary missing')}")
        send_alerts(results, include_pgs_alert=True)
    elif stuck_count > 0:
        logger.warning(f"⚠️  Found {stuck_count} stuck transition(s)")
        send_alerts(results, include_pgs_alert=False)
    elif pgs_status == 'warning':
        logger.warning(f"⚠️  {pgs_check.get('message', 'Low player_game_summary coverage')}")
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
    # Check last N days to catch weekend/holiday stuck transitions
    today = datetime.now(timezone.utc).date()
    check_dates = [today - timedelta(days=i) for i in range(LOOKBACK_DAYS)]

    stuck_transitions = []
    healthy_count = 0

    for check_date in check_dates:
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


def send_alerts(results: Dict, include_pgs_alert: bool = False) -> None:
    """
    Send alerts for stuck transitions and player_game_summary issues.

    Currently logs warnings. Can be extended to send:
    - Email via SES
    - Slack notifications
    - PagerDuty alerts

    Args:
        results: Monitoring results with stuck transitions
        include_pgs_alert: If True, include player_game_summary alert (critical)
    """
    stuck_transitions = []

    for phase_name, phase_results in results.items():
        if phase_name in ('timestamp', 'summary', 'player_game_summary_check'):
            continue
        if isinstance(phase_results, dict) and phase_results.get('stuck_transitions'):
            for stuck in phase_results['stuck_transitions']:
                stuck_transitions.append({
                    'phase': phase_name,
                    **stuck
                })

    pgs_check = results.get('player_game_summary_check', {})

    # Build alert message
    alert_lines = []

    # Add player_game_summary critical alert if needed
    if include_pgs_alert and pgs_check.get('status') == 'critical':
        alert_lines.extend([
            "🚨 CRITICAL: GRADING WILL FAIL",
            "",
            f"❌ player_game_summary is EMPTY for yesterday ({pgs_check.get('game_date')})",
            f"   Games played: {pgs_check.get('game_count', 'unknown')}",
            f"   Rows found: {pgs_check.get('row_count', 0)}",
            "",
            "ACTION REQUIRED:",
            "   Run Phase 3 analytics for yesterday:",
            "   gcloud scheduler jobs run daily-yesterday-analytics --location=us-west2",
            "",
            "   Or manually trigger:",
            "   curl -X POST https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range \\",
            f"     -d '{{\"start_date\": \"{pgs_check.get('game_date')}\", \"end_date\": \"{pgs_check.get('game_date')}\", \"processors\": [\"PlayerGameSummaryProcessor\"]}}'",
            "",
        ])

    if stuck_transitions:
        alert_lines.extend([
            "🚨 STUCK PHASE TRANSITIONS DETECTED",
            "",
            f"Time: {datetime.now(timezone.utc).isoformat()}",
            f"Total stuck: {len(stuck_transitions)}",
            "",
        ])

        for stuck in stuck_transitions:
            alert_lines.extend([
                f"📍 {stuck['phase']}",
                f"   Game Date: {stuck['game_date']}",
                f"   Progress: {stuck['completed_count']}/{stuck['expected_count']}",
                f"   Age: {stuck['age_hours']} hours (timeout: {stuck['timeout_hours']}h)",
                f"   Missing: {', '.join(stuck['missing_processors'][:5])}",
                "",
            ])

    if not alert_lines:
        return

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


# ============================================================================
# HTTP ENDPOINTS (for health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the transition_monitor function."""
    return json.dumps({
        'status': 'healthy',
        'function': 'transition_monitor',
        'lookback_days': LOOKBACK_DAYS,
        'document_ttl_days': DOCUMENT_TTL_DAYS
    }), 200, {'Content-Type': 'application/json'}


# ============================================================================
# FIRESTORE DOCUMENT CLEANUP (30-day TTL)
# ============================================================================

def cleanup_old_documents(
    collections: Optional[List[str]] = None,
    ttl_days: Optional[int] = None,
    dry_run: bool = False
) -> Dict:
    """
    Clean up Firestore documents older than TTL.

    Documents are keyed by date (YYYY-MM-DD format), so we can determine
    age by parsing the document ID.

    Args:
        collections: List of collection names to clean. Defaults to CLEANUP_COLLECTIONS.
        ttl_days: Number of days to retain documents. Defaults to DOCUMENT_TTL_DAYS (30).
        dry_run: If True, only report what would be deleted without actually deleting.

    Returns:
        Dict with cleanup results per collection
    """
    collections = collections or CLEANUP_COLLECTIONS
    ttl_days = ttl_days if ttl_days is not None else DOCUMENT_TTL_DAYS

    cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=ttl_days)
    cutoff_str = cutoff_date.isoformat()

    logger.info(f"{'[DRY RUN] ' if dry_run else ''}Cleaning up documents older than {cutoff_str} ({ttl_days} days)")

    results = {
        'cutoff_date': cutoff_str,
        'ttl_days': ttl_days,
        'dry_run': dry_run,
        'collections': {},
        'total_deleted': 0,
        'total_errors': 0
    }

    for collection_name in collections:
        collection_result = {
            'documents_checked': 0,
            'documents_deleted': 0,
            'documents_skipped': 0,
            'errors': []
        }

        try:
            # Get all documents in the collection
            collection_ref = db.collection(collection_name)
            docs = collection_ref.stream()

            for doc in docs:
                collection_result['documents_checked'] += 1
                doc_id = doc.id

                # Document IDs should be in YYYY-MM-DD format
                try:
                    doc_date = datetime.strptime(doc_id, '%Y-%m-%d').date()
                except ValueError:
                    # Skip documents that don't match the date format
                    logger.debug(f"Skipping non-date document: {collection_name}/{doc_id}")
                    collection_result['documents_skipped'] += 1
                    continue

                # Check if document is older than TTL
                if doc_date < cutoff_date:
                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete: {collection_name}/{doc_id}")
                        collection_result['documents_deleted'] += 1
                    else:
                        try:
                            doc.reference.delete()
                            logger.info(f"Deleted: {collection_name}/{doc_id}")
                            collection_result['documents_deleted'] += 1
                        except Exception as e:
                            error_msg = f"Failed to delete {collection_name}/{doc_id}: {str(e)}"
                            logger.error(error_msg)
                            collection_result['errors'].append(error_msg)

        except Exception as e:
            error_msg = f"Error processing collection {collection_name}: {str(e)}"
            logger.error(error_msg)
            collection_result['errors'].append(error_msg)

        results['collections'][collection_name] = collection_result
        results['total_deleted'] += collection_result['documents_deleted']
        results['total_errors'] += len(collection_result['errors'])

    logger.info(
        f"{'[DRY RUN] ' if dry_run else ''}Cleanup complete: "
        f"{results['total_deleted']} documents {'would be ' if dry_run else ''}deleted, "
        f"{results['total_errors']} errors"
    )

    return results


@functions_framework.http
def cleanup_firestore_documents(request):
    """
    HTTP endpoint to trigger Firestore document cleanup.

    Can be called by Cloud Scheduler or manually.

    Query parameters:
        - ttl_days: Override default TTL (default: 30)
        - dry_run: Set to 'true' for dry run (default: false)
        - collections: Comma-separated list of collections to clean (optional)

    Example:
        GET /cleanup?dry_run=true
        GET /cleanup?ttl_days=14
        GET /cleanup?collections=phase2_completion,phase3_completion

    Returns:
        JSON response with cleanup results
    """
    logger.info("=" * 60)
    logger.info("🧹 Firestore Document Cleanup Starting")
    logger.info("=" * 60)

    # Parse query parameters
    try:
        ttl_days = int(request.args.get('ttl_days', DOCUMENT_TTL_DAYS))
    except (ValueError, TypeError):
        ttl_days = DOCUMENT_TTL_DAYS

    dry_run = request.args.get('dry_run', 'false').lower() == 'true'

    collections_param = request.args.get('collections')
    if collections_param:
        collections = [c.strip() for c in collections_param.split(',') if c.strip()]
    else:
        collections = CLEANUP_COLLECTIONS

    # Run cleanup
    results = cleanup_old_documents(
        collections=collections,
        ttl_days=ttl_days,
        dry_run=dry_run
    )

    results['timestamp'] = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info("🧹 Firestore Document Cleanup Complete")
    logger.info("=" * 60)

    return json.dumps(results, indent=2, default=str), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def monitor_and_cleanup(request):
    """
    Combined endpoint that runs both monitoring and cleanup.

    Useful for a single scheduled job that does both tasks.
    Cleanup runs first (to reduce document count), then monitoring.

    Query parameters:
        - skip_cleanup: Set to 'true' to skip cleanup (default: false)
        - skip_monitor: Set to 'true' to skip monitoring (default: false)
        - cleanup_dry_run: Set to 'true' for cleanup dry run (default: false)

    Returns:
        JSON response with both monitoring and cleanup results
    """
    logger.info("=" * 60)
    logger.info("🔄 Combined Monitor and Cleanup Starting")
    logger.info("=" * 60)

    results = {
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    # Run cleanup first (unless skipped)
    skip_cleanup = request.args.get('skip_cleanup', 'false').lower() == 'true'
    if not skip_cleanup:
        cleanup_dry_run = request.args.get('cleanup_dry_run', 'false').lower() == 'true'
        results['cleanup'] = cleanup_old_documents(dry_run=cleanup_dry_run)
    else:
        results['cleanup'] = {'skipped': True}

    # Run monitoring (unless skipped)
    skip_monitor = request.args.get('skip_monitor', 'false').lower() == 'true'
    if not skip_monitor:
        # Get monitoring results
        monitor_response, _, _ = monitor_transitions(request)
        results['monitoring'] = json.loads(monitor_response)
    else:
        results['monitoring'] = {'skipped': True}

    logger.info("=" * 60)
    logger.info("🔄 Combined Monitor and Cleanup Complete")
    logger.info("=" * 60)

    return json.dumps(results, indent=2, default=str), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import sys

    class FakeRequest:
        """Fake request object for local testing."""
        def __init__(self, args=None):
            self.args = args or {}

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == 'status':
            # Quick status check
            status = get_all_transition_status()
            print(json.dumps(status, indent=2, default=str))

        elif command == 'cleanup':
            # Run cleanup (dry run by default for safety)
            dry_run = '--dry-run' in sys.argv or '-n' in sys.argv
            ttl_days = DOCUMENT_TTL_DAYS

            # Parse --ttl=N argument
            for arg in sys.argv:
                if arg.startswith('--ttl='):
                    try:
                        ttl_days = int(arg.split('=')[1])
                    except ValueError:
                        pass

            if not dry_run:
                print("WARNING: This will DELETE documents. Use --dry-run to preview.")
                print("Proceeding with actual deletion in 3 seconds...")
                import time
                time.sleep(3)

            results = cleanup_old_documents(ttl_days=ttl_days, dry_run=dry_run)
            print(json.dumps(results, indent=2, default=str))

        elif command == 'help':
            print("""
Transition Monitor - Local Testing Commands

Usage: python main.py [command] [options]

Commands:
  (no command)  - Run full transition monitor
  status        - Quick status check of all transitions
  cleanup       - Run Firestore document cleanup
  help          - Show this help message

Cleanup Options:
  --dry-run, -n   Preview what would be deleted (default)
  --ttl=N         Set TTL to N days (default: 30)

Examples:
  python main.py                  # Run monitor
  python main.py status           # Check status
  python main.py cleanup --dry-run  # Preview cleanup
  python main.py cleanup --ttl=14   # Delete docs older than 14 days
""")

        else:
            print(f"Unknown command: {command}")
            print("Use 'python main.py help' for usage information.")

    else:
        # Run full monitor
        result, status_code, _ = monitor_transitions(FakeRequest())
        print(result)
