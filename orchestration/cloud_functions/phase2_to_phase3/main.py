"""
Phase 2 → Phase 3 Orchestrator (Monitoring Mode)

Cloud Function that tracks Phase 2 processor completion for observability.

NOTE: This orchestrator is now MONITORING-ONLY. Phase 3 is triggered directly
via Pub/Sub subscription (nba-phase3-analytics-sub), not by this orchestrator.
The nba-phase3-trigger topic has no subscribers.

Architecture:
- Listens to: nba-phase2-raw-complete (Phase 2 processors publish here)
- Tracks state in: Firestore collection 'phase2_completion/{game_date}'
- NO LONGER publishes to nba-phase3-trigger (vestigial, no subscribers)

Purpose:
- Track which processors complete each day (observability)
- Provide completion status via HTTP endpoint
- Enable debugging of pipeline issues
- Prevent indefinite waits with completion deadline (Week 1)

Critical Features:
- Atomic Firestore transactions (prevent race conditions)
- Idempotency (handles duplicate Pub/Sub messages)
- Correlation ID preservation (traces back to original scraper run)
- Completion deadline monitoring (Week 1 - prevents indefinite waits)

Version: 2.2 - Added Week 1 completion deadline feature
Created: 2025-11-29
Updated: 2026-01-20
"""

import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from google.cloud import firestore, bigquery
import functions_framework
import requests
from shared.clients.bigquery_pool import get_bigquery_client
from shared.validation.phase_boundary_validator import PhaseBoundaryValidator, ValidationMode
from shared.utils.phase_execution_logger import log_phase_execution

# Pydantic validation for Pub/Sub messages (Week 2 addition)
try:
    from shared.validation.pubsub_models import Phase2CompletionMessage
    from pydantic import ValidationError as PydanticValidationError
    PYDANTIC_VALIDATION_ENABLED = True
except ImportError:
    PYDANTIC_VALIDATION_ENABLED = False
    PydanticValidationError = Exception  # Fallback

# Configure logging - use structured logging for Cloud Run
import google.cloud.logging
try:
    client = google.cloud.logging.Client()
    client.setup_logging()
except Exception as e:
    print(f"Could not setup Cloud Logging client: {e}")

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

# Debug: print to stdout/stderr to ensure visibility
print("Phase2-to-Phase3 Orchestrator module loaded")

# Constants
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Week 1: Phase 2 Completion Deadline Feature
ENABLE_PHASE2_COMPLETION_DEADLINE = os.environ.get('ENABLE_PHASE2_COMPLETION_DEADLINE', 'false').lower() == 'true'
PHASE2_COMPLETION_TIMEOUT_MINUTES = int(os.environ.get('PHASE2_COMPLETION_TIMEOUT_MINUTES', '30'))

# Import expected processors from centralized config
# This ensures consistency across the codebase (Issue A fix)
try:
    from shared.config.orchestration_config import get_orchestration_config
    _config = get_orchestration_config()
    EXPECTED_PROCESSORS: List[str] = _config.phase_transitions.phase2_expected_processors
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)
    logger.info(f"Loaded {EXPECTED_PROCESSOR_COUNT} expected Phase 2 processors from config")
except ImportError:
    # Fallback for Cloud Functions where shared module may not be available
    # This is a realistic list of processors that actually run daily
    # NOTE: In monitoring mode, this is used for tracking completeness
    logger.warning("Could not import orchestration_config, using fallback list")
    EXPECTED_PROCESSORS: List[str] = [
        # Core daily processors
        'bdl_player_boxscores',      # Daily box scores from balldontlie
        'bigdataball_play_by_play',  # Per-game play-by-play
        'odds_api_game_lines',       # Per-game odds
        'nbac_schedule',             # Schedule updates
        'nbac_gamebook_player_stats', # Post-game player stats
        'br_rosters_current',        # Basketball-ref rosters
    ]
    EXPECTED_PROCESSOR_COUNT: int = len(EXPECTED_PROCESSORS)
    EXPECTED_PROCESSOR_SET: Set[str] = set(EXPECTED_PROCESSORS)

# Initialize clients (reused across invocations)
db = firestore.Client()


def normalize_processor_name(raw_name: str, output_table: Optional[str] = None) -> str:
    """
    Normalize processor name to match config format.

    Phase 2 processors may publish:
    - Class names: BdlPlayerBoxscoresProcessor
    - Table names: bdl_player_boxscores

    This function normalizes to config format: bdl_player_boxscores

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

    # If output_table matches expected, use it (strip dataset prefix first)
    # Example: "nba_raw.bdl_player_boxscores" -> "bdl_player_boxscores"
    if output_table:
        table_name = output_table.split('.')[-1] if '.' in output_table else output_table
        if table_name in EXPECTED_PROCESSOR_SET:
            logger.debug(f"Matched via output_table: '{output_table}' -> '{table_name}'")
            return table_name

    # Convert CamelCase to snake_case and strip "Processor" suffix
    name = raw_name.replace('Processor', '')
    # Insert underscore before capitals and lowercase
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

    logger.debug(f"Normalized '{raw_name}' -> '{name}'")
    return name


# ============================================================================
# DATA FRESHNESS VALIDATION
# ============================================================================

# R-007: Data freshness validation for Phase 2 raw data tables
# Required Phase 2 tables that must have data before Phase 3 can proceed
REQUIRED_PHASE2_TABLES = [
    ('nba_raw', 'bdl_player_boxscores', 'game_date'),
    ('nba_raw', 'nbac_gamebook_player_stats', 'game_date'),
    ('nba_raw', 'nbac_team_boxscore', 'game_date'),
    ('nba_raw', 'odds_api_game_lines', 'game_date'),
    ('nba_raw', 'nbac_schedule', 'game_date'),
    ('nba_raw', 'bigdataball_play_by_play', 'game_date'),
]


def verify_phase2_data_ready(game_date: str) -> tuple:
    """
    R-007: Verify Phase 2 raw tables have fresh data for game_date.

    This is a belt-and-suspenders check - even if all processors report success,
    verify the data actually exists in BigQuery.

    Args:
        game_date: The date to verify (YYYY-MM-DD)

    Returns:
        tuple: (is_ready: bool, missing_tables: list, table_counts: dict)
    """
    try:
        bq_client = get_bigquery_client(project_id=PROJECT_ID)
        missing = []
        table_counts = {}

        for dataset, table, date_col in REQUIRED_PHASE2_TABLES:
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
                    logger.warning(f"R-007: Missing data in {dataset}.{table} for {game_date}")

            except Exception as query_error:
                # If query fails (table doesn't exist, etc.), treat as missing
                logger.error(f"R-007: Failed to verify {dataset}.{table}: {query_error}")
                missing.append(f"{dataset}.{table}")
                table_counts[f"{dataset}.{table}"] = -1  # Error marker

        is_ready = len(missing) == 0
        if is_ready:
            logger.info(f"R-007: All Phase 2 tables verified for {game_date}: {table_counts}")
        else:
            logger.warning(f"R-007: Data freshness check FAILED for {game_date}. Missing: {missing}")

        return (is_ready, missing, table_counts)

    except Exception as e:
        logger.error(f"R-007: Data freshness verification failed: {e}")
        # On error, return False with empty details
        return (False, ['verification_error'], {'error': str(e)})


def verify_gamebook_data_quality(game_date: str) -> tuple:
    """
    R-009: Verify gamebook data quality - check for incomplete games.

    A gamebook with 0 active players but roster entries indicates the PDF
    was scraped before game data was available. This was the root cause of
    data gaps on Jan 17-18, 2026 (WAS@DEN, POR@SAC).

    Args:
        game_date: The date to verify (YYYY-MM-DD)

    Returns:
        tuple: (is_quality_ok: bool, incomplete_games: list, quality_details: dict)
            - incomplete_games: list of game_ids with 0 active players
            - quality_details: dict with per-game active/roster counts
    """
    try:
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # Query for games with potential data quality issues
        query = f"""
        SELECT
            game_id,
            game_date,
            COUNT(*) as total_records,
            COUNTIF(player_status = 'active') as active_count,
            COUNTIF(player_status IN ('inactive', 'dnp')) as roster_count
        FROM `{PROJECT_ID}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date = '{game_date}'
        GROUP BY game_id, game_date
        ORDER BY game_id
        """

        result = list(bq_client.query(query).result())

        incomplete_games = []
        quality_details = {}

        for row in result:
            game_id = row.game_id
            active_count = row.active_count
            roster_count = row.roster_count

            quality_details[game_id] = {
                'active_count': active_count,
                'roster_count': roster_count,
                'total_records': row.total_records
            }

            # R-009: Game has roster data but no active players = incomplete gamebook
            if active_count == 0 and roster_count > 0:
                incomplete_games.append(game_id)
                logger.warning(
                    f"R-009: Incomplete gamebook data for {game_id} on {game_date}: "
                    f"0 active players, {roster_count} roster entries"
                )

        is_quality_ok = len(incomplete_games) == 0

        if is_quality_ok:
            logger.info(f"R-009: Gamebook data quality OK for {game_date}: {len(result)} games verified")
        else:
            logger.warning(
                f"R-009: Gamebook data quality FAILED for {game_date}: "
                f"{len(incomplete_games)} incomplete games: {incomplete_games}"
            )

        return (is_quality_ok, incomplete_games, quality_details)

    except Exception as e:
        logger.error(f"R-009: Gamebook data quality verification failed: {e}")
        return (False, ['verification_error'], {'error': str(e)})


def send_gamebook_quality_alert(game_date: str, incomplete_games: list, quality_details: dict) -> None:
    """
    Send alert for gamebook data quality issues.

    These alerts indicate games where the gamebook PDF was scraped before
    stats were available. The games need to be re-scraped.

    Args:
        game_date: The date with quality issues
        incomplete_games: List of game_ids with incomplete data
        quality_details: Per-game quality details
    """
    try:
        # Format game details for alert
        game_details = []
        for game_id in incomplete_games:
            details = quality_details.get(game_id, {})
            game_details.append(
                f"  - {game_id}: {details.get('active_count', 0)} active, "
                f"{details.get('roster_count', 0)} roster"
            )

        message = (
            f"🚨 *R-009: Incomplete Gamebook Data Detected*\n"
            f"Date: {game_date}\n"
            f"Incomplete Games ({len(incomplete_games)}):\n" +
            "\n".join(game_details) +
            f"\n\n*Action Required:* Re-scrape these games using:\n"
            f"```\npython -m data_processors.raw.nbacom.nbac_gamebook_processor "
            f"--start-date {game_date} --end-date {game_date}\n```"
        )

        if SLACK_WEBHOOK_URL:
            requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
            logger.info(f"Sent gamebook quality alert for {game_date}")
        else:
            logger.warning(f"No Slack webhook configured. Alert message:\n{message}")

    except Exception as e:
        logger.error(f"Failed to send gamebook quality alert: {e}")


def check_completion_deadline(game_date: str, current_processor: str) -> tuple:
    """
    Week 1: Check if Phase 2 completion deadline has been exceeded.

    Returns completion status and triggers Phase 3 if deadline exceeded.

    Args:
        game_date: The date being processed
        current_processor: The processor that just completed

    Returns:
        tuple: (deadline_exceeded: bool, first_completion_time: datetime, completed_processors: list)
    """
    if not ENABLE_PHASE2_COMPLETION_DEADLINE:
        return (False, None, [])

    try:
        doc_ref = db.collection('phase2_completion').document(game_date)
        doc = doc_ref.get()

        if not doc.exists:
            logger.warning(f"No completion doc found for {game_date}, cannot check deadline")
            return (False, None, [])

        data = doc.to_dict()
        completed_processors = [k for k in data.keys() if not k.startswith('_')]

        # Get first completion time
        first_completion_time = data.get('_first_completion_at')

        if not first_completion_time:
            logger.warning(f"No _first_completion_at found for {game_date}")
            return (False, None, completed_processors)

        # Calculate time since first completion
        from datetime import timedelta
        now = datetime.now(timezone.utc)

        # Handle both Firestore timestamp and datetime objects
        if hasattr(first_completion_time, 'seconds'):
            # Firestore timestamp
            first_completion_dt = datetime.fromtimestamp(first_completion_time.seconds, tz=timezone.utc)
        else:
            # Already a datetime
            first_completion_dt = first_completion_time

        time_elapsed = now - first_completion_dt
        deadline_minutes = timedelta(minutes=PHASE2_COMPLETION_TIMEOUT_MINUTES)

        deadline_exceeded = time_elapsed > deadline_minutes

        if deadline_exceeded:
            logger.warning(
                f"⏰ DEADLINE EXCEEDED: Phase 2 for {game_date} has been running for "
                f"{time_elapsed.total_seconds() / 60:.1f} minutes (deadline: {PHASE2_COMPLETION_TIMEOUT_MINUTES}m). "
                f"Completed: {len(completed_processors)}/{EXPECTED_PROCESSOR_COUNT} processors"
            )

        return (deadline_exceeded, first_completion_dt, completed_processors)

    except Exception as e:
        logger.error(f"Failed to check completion deadline: {e}")
        return (False, None, [])


def send_completion_deadline_alert(game_date: str, completed_processors: list,
                                   missing_processors: list, elapsed_minutes: float) -> bool:
    """
    Send Slack alert when Phase 2 completion deadline is exceeded.

    Args:
        game_date: The date being processed
        completed_processors: List of processors that completed
        missing_processors: List of processors still pending
        elapsed_minutes: Time elapsed since first completion

    Returns:
        True if alert sent successfully, False otherwise
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping deadline alert")
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
                            "text": "⏰ Phase 2 Completion Deadline Exceeded",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Phase 2 processors for {game_date} exceeded {PHASE2_COMPLETION_TIMEOUT_MINUTES}-minute deadline!*\n"
                                   f"Proceeding to Phase 3 with partial data to maintain SLA compliance."
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Date:*\n{game_date}"},
                            {"type": "mrkdwn", "text": f"*Elapsed Time:*\n{elapsed_minutes:.1f} minutes"},
                            {"type": "mrkdwn", "text": f"*Completed:*\n{len(completed_processors)}/{EXPECTED_PROCESSOR_COUNT}"},
                            {"type": "mrkdwn", "text": f"*Missing:*\n{len(missing_processors)} processors"},
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Completed Processors:*\n```{', '.join(completed_processors)}```"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Missing Processors:*\n```{', '.join(missing_processors)}```"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": "⚠️ Action: Phase 3 analytics triggered with available data. Review missing processor logs."
                        }]
                    }
                ]
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Completion deadline alert sent successfully for {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to send completion deadline alert: {e}")
        return False


def send_data_freshness_alert(game_date: str, missing_tables: List[str], table_counts: Dict) -> bool:
    """
    Send Slack alert when Phase 2 data freshness check fails.

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

        payload = {
            "attachments": [{
                "color": "#FFA500",  # Orange for warning
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": ":warning: R-007: Phase 2 Data Freshness Alert",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Data freshness check failed!* Some Phase 2 raw tables are missing data for {game_date}."
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
                            "text": "Phase 3 analytics will proceed, but may use incomplete data. Review Phase 2 processor logs."
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


def send_validation_warning_alert(game_date: str, validation_result) -> bool:
    """
    Send Slack alert when phase boundary validation finds warnings.

    Args:
        game_date: The date being processed
        validation_result: ValidationResult from PhaseBoundaryValidator

    Returns:
        True if alert sent successfully, False otherwise
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping validation alert")
        return False

    try:
        # Format issues for display
        issues_text = "\n".join([
            f"• [{issue.severity.value.upper()}] {issue.message}"
            for issue in validation_result.issues
        ])

        # Determine color based on severity
        has_errors = validation_result.has_errors
        color = "#FF0000" if has_errors else "#FFA500"  # Red for errors, orange for warnings

        payload = {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f":warning: Phase 2→3 Validation {'Failed' if has_errors else 'Warnings'}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Date:*\n{game_date}"},
                            {"type": "mrkdwn", "text": f"*Phase:*\nPhase 2 → 3"},
                            {"type": "mrkdwn", "text": f"*Mode:*\n{validation_result.mode.value}"},
                            {"type": "mrkdwn", "text": f"*Issues:*\n{len(validation_result.issues)}"}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Validation Issues:*\n{issues_text}"
                        }
                    }
                ]
            }]
        }

        # Add metrics if available
        if validation_result.metrics:
            metrics_fields = []
            if 'actual_game_count' in validation_result.metrics:
                metrics_fields.append({
                    "type": "mrkdwn",
                    "text": f"*Actual Games:*\n{validation_result.metrics['actual_game_count']}"
                })
            if 'expected_game_count' in validation_result.metrics:
                metrics_fields.append({
                    "type": "mrkdwn",
                    "text": f"*Expected Games:*\n{validation_result.metrics['expected_game_count']}"
                })
            if 'completed_processors' in validation_result.metrics:
                completed = validation_result.metrics['completed_processors']
                metrics_fields.append({
                    "type": "mrkdwn",
                    "text": f"*Completed Processors:*\n{len(completed)}"
                })

            if metrics_fields:
                payload["attachments"][0]["blocks"].append({
                    "type": "section",
                    "fields": metrics_fields
                })

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Validation alert sent successfully for {game_date}")
        return True

    except Exception as e:
        logger.error(f"Failed to send validation alert: {e}")
        return False


@functions_framework.cloud_event
def orchestrate_phase2_to_phase3(cloud_event):
    """
    Handle Phase 2 completion events and trigger Phase 3 when all processors complete.

    Triggered by: Pub/Sub messages to nba-phase2-raw-complete

    Message format (unified):
    {
        "processor_name": "BdlGamesProcessor",
        "phase": "phase_2_raw",
        "execution_id": "def-456",
        "correlation_id": "abc-123",
        "game_date": "2025-11-29",
        "output_table": "bdl_games",
        "output_dataset": "nba_raw",
        "status": "success",
        "record_count": 150,
        "timestamp": "2025-11-29T12:00:00Z",
        ...
    }

    Args:
        cloud_event: CloudEvent from Pub/Sub containing Phase 2 completion data
    """
    # Capture start time for execution logging
    execution_start_time = datetime.now(timezone.utc)

    # Debug: print immediately to verify function is invoked
    print(f"DEBUG: orchestrate_phase2_to_phase3 invoked with cloud_event type: {type(cloud_event)}")
    import sys
    sys.stdout.flush()

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

        # Normalize processor name to match config format
        # This handles class names like BdlPlayerBoxscoresProcessor -> bdl_player_boxscores
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
        doc_ref = db.collection('phase2_completion').document(game_date)

        # Create transaction and execute atomic update
        transaction = db.transaction()
        should_trigger, deadline_exceeded = update_completion_atomic(
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

        # Week 1: Check if completion deadline has been exceeded
        if ENABLE_PHASE2_COMPLETION_DEADLINE and not should_trigger:
            deadline_exceeded, first_completion_time, completed_processors = check_completion_deadline(
                game_date, processor_name
            )

            if deadline_exceeded:
                # Calculate missing processors
                missing_processors = list(EXPECTED_PROCESSOR_SET - set(completed_processors))

                # Calculate elapsed time
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                elapsed = now - first_completion_time
                elapsed_minutes = elapsed.total_seconds() / 60

                logger.error(
                    f"⏰ DEADLINE EXCEEDED: Phase 2 for {game_date} exceeded {PHASE2_COMPLETION_TIMEOUT_MINUTES}m deadline. "
                    f"Completed {len(completed_processors)}/{EXPECTED_PROCESSOR_COUNT} processors. "
                    f"Missing: {missing_processors}"
                )

                # Send Slack alert
                send_completion_deadline_alert(
                    game_date,
                    completed_processors,
                    missing_processors,
                    elapsed_minutes
                )

                # Mark as triggered with partial data (prevent further deadline checks)
                doc_ref.update({
                    '_triggered': True,
                    '_triggered_at': firestore.SERVER_TIMESTAMP,
                    '_triggered_reason': 'deadline_exceeded',
                    '_partial_completion': True
                })

                logger.warning(
                    f"⚠️ Phase 3 will proceed with partial data from {len(completed_processors)} processors. "
                    f"Phase 3 is triggered via Pub/Sub subscription (monitoring mode)."
                )

                # Log execution metrics for deadline exceeded case
                execution_duration = (datetime.now(timezone.utc) - execution_start_time).total_seconds()
                log_phase_execution(
                    phase_name="phase2_to_phase3",
                    game_date=game_date,
                    start_time=execution_start_time,
                    duration_seconds=execution_duration,
                    games_processed=len(completed_processors),
                    status="deadline_exceeded",
                    correlation_id=correlation_id,
                    metadata={
                        "completed_processors": completed_processors,
                        "missing_processors": missing_processors,
                        "elapsed_minutes": elapsed_minutes,
                        "deadline_minutes": PHASE2_COMPLETION_TIMEOUT_MINUTES,
                        "trigger_reason": "deadline_exceeded"
                    }
                )

        if should_trigger:
            # All expected processors complete - log for monitoring
            # NOTE: Phase 3 is triggered directly via Pub/Sub subscription, not here
            logger.info(
                f"✅ MONITORING: All {EXPECTED_PROCESSOR_COUNT} expected Phase 2 processors "
                f"complete for {game_date} (correlation_id={correlation_id})"
            )

            # Log execution metrics for latency tracking
            execution_duration = (datetime.now(timezone.utc) - execution_start_time).total_seconds()
            log_phase_execution(
                phase_name="phase2_to_phase3",
                game_date=game_date,
                start_time=execution_start_time,
                duration_seconds=execution_duration,
                games_processed=EXPECTED_PROCESSOR_COUNT,
                status="complete",
                correlation_id=correlation_id,
                metadata={
                    "completed_processors": list(EXPECTED_PROCESSOR_SET),
                    "trigger_reason": "all_complete",
                    "orchestrator_mode": "monitoring_only"
                }
            )

            # R-007: Verify Phase 2 data exists in BigQuery
            # This is monitoring-only - we don't block Phase 3 (it's triggered via Pub/Sub)
            is_ready, missing_tables, table_counts = verify_phase2_data_ready(game_date)

            if not is_ready:
                logger.warning(
                    f"R-007: Data freshness check FAILED for {game_date}. "
                    f"Missing tables: {missing_tables}. Monitoring alert sent."
                )
                # Send alert for visibility
                send_data_freshness_alert(game_date, missing_tables, table_counts)
            else:
                logger.info(f"R-007: Data freshness check PASSED for {game_date}")

            # R-009: Verify gamebook data quality (check for incomplete games)
            is_quality_ok, incomplete_games, quality_details = verify_gamebook_data_quality(game_date)

            if not is_quality_ok:
                logger.warning(
                    f"R-009: Gamebook data quality check FAILED for {game_date}. "
                    f"Incomplete games: {incomplete_games}"
                )
                # Send alert for visibility and action
                send_gamebook_quality_alert(game_date, incomplete_games, quality_details)
            else:
                logger.info(f"R-009: Gamebook data quality check PASSED for {game_date}")

            # Phase Boundary Validation (WARNING mode - non-blocking)
            try:
                validator = PhaseBoundaryValidator(
                    bq_client=get_bigquery_client(),
                    project_id=PROJECT_ID,
                    phase_name='phase2',
                    mode=ValidationMode.WARNING  # Non-blocking, logs warnings only
                )

                # Get schedule context for expected game count (if available)
                from datetime import datetime as dt
                schedule_context = None
                try:
                    # Try to get schedule from BigQuery
                    schedule_query = f"""
                    SELECT COUNT(*) as game_count
                    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
                    WHERE DATE(game_date_est) = '{game_date}'
                    """
                    schedule_result = list(get_bigquery_client().query(schedule_query).result())
                    expected_game_count = schedule_result[0].game_count if schedule_result else 0
                except Exception as e:
                    logger.warning(f"Could not fetch expected game count from schedule: {e}")
                    expected_game_count = 0

                validation_result = validator.run_validation(
                    game_date=dt.strptime(game_date, '%Y-%m-%d').date(),
                    validation_config={
                        'check_game_count': True,
                        'expected_game_count': expected_game_count,
                        'game_count_dataset': 'nba_raw',
                        'game_count_table': 'bdl_games',
                        'check_processors': True,
                        'expected_processors': EXPECTED_PROCESSORS,
                        'check_data_quality': False  # Skip quality check for now (no quality_score column yet)
                    }
                )

                # Log validation result
                if validation_result.has_warnings or validation_result.has_errors:
                    logger.warning(
                        f"Phase 2→3 validation found {len(validation_result.issues)} issues for {game_date}: "
                        f"{[issue.message for issue in validation_result.issues]}"
                    )
                    # Send alert for visibility
                    send_validation_warning_alert(game_date, validation_result)

                    # Log to BigQuery for monitoring
                    validator.log_validation_to_bigquery(validation_result)
                else:
                    logger.info(f"Phase 2→3 validation PASSED for {game_date}")

            except Exception as validation_error:
                # Don't fail the orchestrator if validation fails
                logger.error(f"Phase boundary validation error: {validation_error}", exc_info=True)
        else:
            # Still waiting for more processors (and deadline not exceeded)
            logger.info(f"MONITORING: Registered {processor_name} completion, waiting for others")

    except Exception as e:
        logger.error(f"Error in Phase 2→3 orchestrator: {e}", exc_info=True)
        # Don't raise - let Pub/Sub retry if transient, or drop if permanent


@firestore.transactional
def update_completion_atomic(transaction: firestore.Transaction, doc_ref, processor_name: str, completion_data: Dict) -> tuple:
    """
    Atomically update processor completion and determine if all expected are complete.

    This function uses Firestore transactions to prevent race conditions when multiple
    processors complete simultaneously. The @firestore.transactional decorator ensures
    atomic read-modify-write operations.

    Week 1 Update: Now tracks first completion time for deadline monitoring.

    NOTE: In monitoring mode, this is used for tracking only. Phase 3 is triggered
    directly via Pub/Sub subscription, not by this orchestrator.

    Transaction flow:
    1. Read current state (locked)
    2. Check if processor already registered (idempotency)
    3. Add processor completion data
    4. Track first completion time (Week 1)
    5. Count total completions
    6. If all complete AND not yet marked → mark as complete and return True
    7. Write atomically (released lock)

    Args:
        transaction: Firestore transaction object
        doc_ref: Firestore document reference for this game_date
        processor_name: Name of completing processor (e.g., "BdlGamesProcessor")
        completion_data: Completion metadata (timestamp, correlation_id, status, etc.)

    Returns:
        tuple: (should_trigger: bool, deadline_exceeded: bool)
    """
    # Read current state within transaction (locked)
    doc_snapshot = doc_ref.get(transaction=transaction)
    current = doc_snapshot.to_dict() if doc_snapshot.exists else {}

    # Idempotency check: skip if this processor already registered
    if processor_name in current:
        logger.debug(f"Processor {processor_name} already registered (duplicate Pub/Sub message)")
        return (False, False)

    # Add this processor's completion data
    current[processor_name] = completion_data

    # Count completed processors (exclude metadata fields starting with _)
    completed_count = len([k for k in current.keys() if not k.startswith('_')])

    # Week 1: Track first completion time for deadline monitoring
    if ENABLE_PHASE2_COMPLETION_DEADLINE and '_first_completion_at' not in current:
        current['_first_completion_at'] = firestore.SERVER_TIMESTAMP
        logger.info(f"First processor completed for this batch: {processor_name}")

    # Check if this completes the phase AND hasn't been triggered yet
    if completed_count >= EXPECTED_PROCESSOR_COUNT and not current.get('_triggered'):
        # Mark as triggered to prevent duplicate triggers (double safety)
        current['_triggered'] = True
        current['_triggered_at'] = firestore.SERVER_TIMESTAMP
        current['_completed_count'] = completed_count

        # Write atomically
        transaction.set(doc_ref, current)

        return (True, False)  # Trigger Phase 3, not deadline exceeded
    else:
        # Not yet complete, or already triggered
        current['_completed_count'] = completed_count

        # Write atomically
        transaction.set(doc_ref, current)

        return (False, False)  # Don't trigger


def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

    Handles base64 decoding, JSON parsing, and Pydantic validation.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dictionary with validated message data

    Raises:
        ValueError: If message cannot be parsed or validation fails
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

        # Week 2: Validate with Pydantic if available
        if PYDANTIC_VALIDATION_ENABLED:
            try:
                validated = Phase2CompletionMessage.model_validate(message_data)
                logger.debug(f"Pydantic validation passed for {validated.processor_name}")
                return message_data  # Return original dict for backward compatibility
            except PydanticValidationError as e:
                logger.warning(f"Pydantic validation failed: {e}. Falling back to dict.")
                # Don't raise - fall through to return raw dict for backward compatibility
                # This allows gradual migration without breaking existing messages

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
    doc_ref = db.collection('phase2_completion').document(game_date)
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
# HTTP ENDPOINTS (for monitoring and status queries)
# ============================================================================

@functions_framework.http
def status(request):
    """
    HTTP endpoint for querying Phase 2 completion status.

    Usage:
        GET /status?date=2025-12-23
        GET /status?date=2025-12-23,2025-12-22  (multiple dates)
        GET /status  (defaults to today)

    Returns:
        JSON with completion status for requested date(s)
    """
    from datetime import date

    # Get date(s) from query params
    date_param = request.args.get('date', date.today().isoformat())
    dates = [d.strip() for d in date_param.split(',')]

    # Get status for each date
    if len(dates) == 1:
        result = get_completion_status(dates[0])
    else:
        result = {
            'dates': {d: get_completion_status(d) for d in dates}
        }

    return json.dumps(result, indent=2, default=str), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def health(request):
    """Health check endpoint for the phase2_to_phase3 orchestrator."""
    return json.dumps({
        'status': 'healthy',
        'function': 'phase2_to_phase3',
        'mode': 'monitoring-only',
        'expected_processors': EXPECTED_PROCESSOR_COUNT,
        'data_freshness_validation': 'enabled',
        'completion_deadline': {
            'enabled': ENABLE_PHASE2_COMPLETION_DEADLINE,
            'timeout_minutes': PHASE2_COMPLETION_TIMEOUT_MINUTES
        },
        'version': '2.2'
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
