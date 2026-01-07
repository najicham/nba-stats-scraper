# Force rebuild - $(date)
"""
Main processor service for Cloud Run
Handles Pub/Sub messages when scrapers complete
Enhanced with notifications for orchestration issues

File Path: data_processors/raw/main_processor_service.py

UPDATED: 2025-11-13
- Added support for both GCS Object Finalize and Scraper Completion message formats
- Added normalize_message_format() function to convert between formats
- Enhanced logging for scraper-triggered processing
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone
import base64
import re

from google.cloud import storage

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Import enhanced error notifications
from shared.utils.enhanced_error_notifications import (
    extract_error_context_from_exception,
    send_enhanced_error_notification,
    ErrorContext
)

# Import processors
from data_processors.raw.basketball_ref.br_roster_processor import BasketballRefRosterProcessor
from data_processors.raw.basketball_ref.br_roster_batch_processor import BasketballRefRosterBatchProcessor
from data_processors.raw.oddsapi.odds_api_props_processor import OddsApiPropsProcessor
from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
from data_processors.raw.nbacom.nbac_player_list_processor import NbacPlayerListProcessor
from data_processors.raw.balldontlie.bdl_standings_processor import BdlStandingsProcessor
from data_processors.raw.balldontlie.bdl_injuries_processor import BdlInjuriesProcessor
from data_processors.raw.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor
from data_processors.raw.balldontlie.bdl_live_boxscores_processor import BdlLiveBoxscoresProcessor
from data_processors.raw.balldontlie.bdl_active_players_processor import BdlActivePlayersProcessor
from data_processors.raw.balldontlie.bdl_player_box_scores_processor import BdlPlayerBoxScoresProcessor
from data_processors.raw.nbacom.nbac_player_movement_processor import NbacPlayerMovementProcessor
from data_processors.raw.nbacom.nbac_scoreboard_v2_processor import NbacScoreboardV2Processor
from data_processors.raw.nbacom.nbac_player_boxscore_processor import NbacPlayerBoxscoreProcessor
from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor
from data_processors.raw.nbacom.nbac_play_by_play_processor import NbacPlayByPlayProcessor

from data_processors.raw.espn.espn_boxscore_processor import EspnBoxscoreProcessor
from data_processors.raw.espn.espn_team_roster_processor import EspnTeamRosterProcessor
from data_processors.raw.espn.espn_roster_batch_processor import EspnRosterBatchProcessor
from data_processors.raw.espn.espn_scoreboard_processor import EspnScoreboardProcessor
from data_processors.raw.bettingpros.bettingpros_player_props_processor import BettingPropsProcessor
from data_processors.raw.bigdataball.bigdataball_pbp_processor import BigDataBallPbpProcessor
from data_processors.raw.nbacom.nbac_referee_processor import NbacRefereeProcessor
from data_processors.raw.oddsapi.odds_game_lines_processor import OddsGameLinesProcessor
from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor
from data_processors.raw.nbacom.nbac_injury_report_processor import NbacInjuryReportProcessor


# from balldontlie.bdl_boxscore_processor import BdlBoxscoreProcessor
# from nbacom.nbac_schedule_processor import NbacScheduleProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Processor registry
PROCESSOR_REGISTRY = {
    'basketball-ref/season-rosters': BasketballRefRosterProcessor,
    
    'odds-api/player-props': OddsApiPropsProcessor,
    'odds-api/game-lines-history': OddsGameLinesProcessor,
    'odds-api/game-lines': OddsGameLinesProcessor,  # Current/live game lines (non-historical)
    
    'nba-com/gamebooks-data': NbacGamebookProcessor,
    'nba-com/player-list': NbacPlayerListProcessor,
    
    'ball-dont-lie/standings': BdlStandingsProcessor,
    'ball-dont-lie/injuries': BdlInjuriesProcessor,
    # NOTE: player-box-scores MUST come before boxscores due to substring matching
    'ball-dont-lie/player-box-scores': BdlPlayerBoxScoresProcessor,  # /stats endpoint
    'ball-dont-lie/boxscores': BdlBoxscoresProcessor,  # /boxscores endpoint
    'ball-dont-lie/live-boxscores': BdlLiveBoxscoresProcessor,
    'ball-dont-lie/active-players': BdlActivePlayersProcessor,
    
    'nba-com/player-movement': NbacPlayerMovementProcessor,
    'nba-com/scoreboard-v2': NbacScoreboardV2Processor,
    'nba-com/player-boxscores': NbacPlayerBoxscoreProcessor,
    'nba-com/team-boxscore': NbacTeamBoxscoreProcessor,
    'nba-com/play-by-play': NbacPlayByPlayProcessor,
    'nba-com/referee-assignments': NbacRefereeProcessor,
    'nba-com/schedule': NbacScheduleProcessor,
    'nba-com/injury-report-data': NbacInjuryReportProcessor,

    'espn/boxscores': EspnBoxscoreProcessor,
    'espn/rosters': EspnTeamRosterProcessor,
    'espn/scoreboard': EspnScoreboardProcessor,

    'bettingpros/player-props': BettingPropsProcessor,

    'big-data-ball': BigDataBallPbpProcessor,
}

# Paths that are intentionally not processed (event IDs, metadata, etc.)
# These files are saved to GCS for reference but don't need BigQuery processing
SKIP_PROCESSING_PATHS = [
    'odds-api/events',      # OddsAPI event IDs - used by scrapers, not processed
    'bettingpros/events',   # BettingPros event IDs - used by scrapers, not processed
]


@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "processors",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/monitoring/boxscore-completeness', methods=['POST'])
def check_boxscore_completeness():
    """
    Check boxscore data completeness and send alerts if below threshold.

    Called daily by Cloud Scheduler at 6 AM ET.

    Request body:
        {
            "check_days": 1,  # Number of days to check (default: 1 = yesterday)
            "alert_on_gaps": true  # Whether to send alerts
        }
    """
    from google.cloud import bigquery, storage
    from datetime import date, timedelta

    logger = logging.getLogger(__name__)

    try:
        data = request.get_json() or {}
        check_days = data.get('check_days', 1)
        alert_on_gaps = data.get('alert_on_gaps', True)

        end_date = date.today() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=check_days - 1)

        logger.info(f"Checking boxscore completeness: {start_date} to {end_date}")

        bq_client = bigquery.Client()

        # Query coverage
        coverage_query = f"""
        WITH schedule AS (
          SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION ALL
          SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ),
        team_games AS (
          SELECT team, COUNT(DISTINCT game_date) as scheduled_games
          FROM schedule GROUP BY team
        ),
        boxscore_games AS (
          SELECT team_abbr, COUNT(DISTINCT game_date) as boxscore_games
          FROM nba_raw.bdl_player_boxscores
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          GROUP BY team_abbr
        )
        SELECT t.team, t.scheduled_games, COALESCE(b.boxscore_games, 0) as boxscore_games,
          ROUND(COALESCE(b.boxscore_games, 0) * 100.0 / t.scheduled_games, 1) as coverage_pct
        FROM team_games t
        LEFT JOIN boxscore_games b ON t.team = b.team_abbr
        ORDER BY coverage_pct
        """

        coverage_result = list(bq_client.query(coverage_query).result(timeout=60))

        # Find teams below thresholds
        critical_teams = [(r.team, r.coverage_pct) for r in coverage_result if r.coverage_pct < 70]
        warning_teams = [(r.team, r.coverage_pct) for r in coverage_result if 70 <= r.coverage_pct < 90]

        # Count missing games
        missing_query = f"""
        WITH schedule AS (
          SELECT game_date, home_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
          UNION ALL
          SELECT game_date, away_team_tricode as team FROM nba_raw.nbac_schedule
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ),
        boxscores AS (
          SELECT DISTINCT game_date, team_abbr FROM nba_raw.bdl_player_boxscores
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        SELECT COUNT(*) as missing_count
        FROM schedule s
        LEFT JOIN boxscores b ON s.game_date = b.game_date AND s.team = b.team_abbr
        WHERE b.team_abbr IS NULL
        """

        missing_count = list(bq_client.query(missing_query).result(timeout=60))[0].missing_count

        # Send alerts if needed
        if alert_on_gaps and (critical_teams or warning_teams):
            date_range = f"{start_date} to {end_date}" if start_date != end_date else str(start_date)

            if critical_teams:
                critical_msg = ", ".join([f"{t[0]}:{t[1]}%" for t in critical_teams])
                notify_error(
                    title=f"CRITICAL: Boxscore Data Gaps ({date_range})",
                    message=f"Teams below 70%: {critical_msg}. Missing {missing_count} games total.",
                    details={'critical_teams': critical_teams, 'missing_count': missing_count},
                    processor_name="Boxscore Completeness Check"
                )
            elif warning_teams:
                warning_msg = ", ".join([f"{t[0]}:{t[1]}%" for t in warning_teams])
                notify_warning(
                    title=f"WARNING: Boxscore Coverage Below 90% ({date_range})",
                    message=f"Teams below 90%: {warning_msg}. Missing {missing_count} games total.",
                    details={'warning_teams': warning_teams, 'missing_count': missing_count}
                )

        status = 'critical' if critical_teams else ('warning' if warning_teams else 'ok')

        # Auto-reset circuit breakers for players/teams that now have data
        # This prevents cascading lockouts when data gaps are backfilled
        reset_count = 0
        try:
            auto_reset = data.get('auto_reset_circuit_breakers', True)
            if auto_reset:
                reset_count = _auto_reset_circuit_breakers(bq_client, start_date, end_date, logger)
        except Exception as reset_error:
            logger.warning(f"Circuit breaker auto-reset failed (non-fatal): {reset_error}")

        return jsonify({
            "status": status,
            "date_range": f"{start_date} to {end_date}",
            "missing_games": missing_count,
            "critical_teams": critical_teams,
            "warning_teams": warning_teams,
            "total_teams_checked": len(coverage_result),
            "circuit_breakers_reset": reset_count,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200

    except Exception as e:
        logger.error(f"Boxscore completeness check failed: {e}")
        return jsonify({"error": str(e)}), 500


def _auto_reset_circuit_breakers(bq_client, start_date, end_date, logger) -> int:
    """
    Auto-reset circuit breakers for entities that now have boxscore data.

    When boxscore data is backfilled, players that were previously locked out
    due to missing data should be automatically unlocked.

    Returns:
        Number of circuit breakers reset
    """
    # Find players with active circuit breakers whose teams now have data
    reset_query = f"""
    UPDATE `nba_orchestration.reprocess_attempts`
    SET circuit_breaker_tripped = FALSE,
        circuit_breaker_until = NULL,
        notes = CONCAT(COALESCE(notes, ''), ' | Auto-reset: boxscore data available')
    WHERE circuit_breaker_tripped = TRUE
      AND circuit_breaker_until > CURRENT_TIMESTAMP()
      AND (
        -- Reset if player has recent boxscore data
        entity_id IN (
          SELECT DISTINCT player_lookup
          FROM nba_raw.bdl_player_boxscores
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
        OR
        -- Reset if entity is a team that now has data
        entity_id IN (
          SELECT DISTINCT team_abbr
          FROM nba_raw.bdl_player_boxscores
          WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        )
      )
    """

    try:
        job = bq_client.query(reset_query)
        job.result(timeout=60)
        reset_count = job.num_dml_affected_rows or 0
        if reset_count > 0:
            logger.info(f"Auto-reset {reset_count} circuit breakers for entities with recent boxscore data")
        return reset_count
    except Exception as e:
        logger.warning(f"Circuit breaker auto-reset query failed: {e}")
        return 0


def normalize_message_format(message: dict) -> dict:
    """
    Normalize Pub/Sub message format to be compatible with processor routing.

    Handles three message formats:
    1. GCS Object Finalize (legacy): {"bucket": "...", "name": "..."}
    2. Scraper Completion (old): {"scraper_name": "...", "gcs_path": "gs://...", ...}
    3. Unified Format (v2): {"processor_name": "...", "phase": "...", "metadata": {"gcs_path": "..."}, ...}

    Also handles special cases:
    - Failed scraper events (no gcs_path)
    - No data events (no gcs_path)

    Args:
        message: Raw Pub/Sub message data

    Returns:
        Normalized message with 'bucket' and 'name' fields, or
        a skip_processing dict for events without files

    Raises:
        ValueError: If message format is unrecognized or missing required fields
    """
    import logging

    logger = logging.getLogger(__name__)

    # Case 1: GCS Object Finalize format (legacy)
    if 'bucket' in message and 'name' in message:
        logger.info(f"Processing GCS Object Finalize message: gs://{message['bucket']}/{message['name']}")
        return message

    # Case 2: Unified Format (v2) - from UnifiedPubSubPublisher
    # Identifies by: 'processor_name' AND 'phase' fields
    if 'processor_name' in message and 'phase' in message:
        processor_name = message.get('processor_name')
        status = message.get('status', 'unknown')

        # Extract gcs_path from metadata (unified format stores it there)
        metadata = message.get('metadata', {})
        gcs_path = metadata.get('gcs_path')

        logger.info(f"Processing Unified Format message from: {processor_name} (phase={message.get('phase')}, status={status})")

        # Handle failed or no-data events (no file to process)
        if gcs_path is None or gcs_path == '' or status in ('failed', 'no_data'):
            logger.warning(
                f"Scraper {processor_name} published event with status={status} "
                f"but no gcs_path. This is expected for failed or no-data events. Skipping file processing."
            )
            return {
                'skip_processing': True,
                'reason': f'No file to process (status={status})',
                'scraper_name': processor_name,
                'execution_id': message.get('execution_id'),
                'status': status,
                '_original_message': message
            }

        # Parse GCS path into bucket and name
        if not gcs_path.startswith('gs://'):
            raise ValueError(
                f"Invalid gcs_path format: {gcs_path}. "
                f"Expected gs://bucket/path format from scraper {processor_name}"
            )

        path_without_protocol = gcs_path[5:]  # Remove 'gs://'
        parts = path_without_protocol.split('/', 1)

        if len(parts) != 2:
            raise ValueError(
                f"Invalid gcs_path structure: {gcs_path}. "
                f"Expected gs://bucket/path format from scraper {processor_name}"
            )

        bucket = parts[0]
        name = parts[1]

        # Create normalized message preserving unified metadata
        normalized = {
            'bucket': bucket,
            'name': name,
            '_original_format': 'unified_v2',
            '_scraper_name': processor_name,
            '_execution_id': message.get('execution_id'),
            '_status': status,
            '_record_count': message.get('record_count'),
            '_duration_seconds': message.get('duration_seconds'),
            '_workflow': metadata.get('workflow'),
            '_timestamp': message.get('timestamp'),
            '_game_date': message.get('game_date'),
            '_metadata': metadata  # Preserve full metadata for batch processing
        }

        logger.info(
            f"Normalized unified message: bucket={bucket}, name={name}, "
            f"scraper={processor_name}, status={status}"
        )

        return normalized

    # Case 3: Scraper Completion format (old/v1)
    # Check for 'scraper_name' OR ('name' AND 'gcs_path' without 'bucket')
    if 'scraper_name' in message or ('name' in message and 'gcs_path' in message and 'bucket' not in message):
        # Prefer scraper_name, fallback to name
        scraper_name = message.get('scraper_name') or message.get('name')
        logger.info(f"Processing Scraper Completion message from: {scraper_name}")

        # Get gcs_path (may be None for failed/no-data events)
        gcs_path = message.get('gcs_path')
        status = message.get('status', 'unknown')
        
        # ⭐ NEW: Handle failed or no-data events (no file to process)
        if gcs_path is None or gcs_path == '':
            logger.warning(
                f"Scraper {scraper_name} published event with status={status} "
                f"but no gcs_path. This is expected for failed or no-data events. Skipping file processing."
            )
            # Return a special marker so the caller can handle it appropriately
            return {
                'skip_processing': True,
                'reason': f'No file to process (status={status})',
                'scraper_name': scraper_name,
                'execution_id': message.get('execution_id'),
                'status': status,
                '_original_message': message
            }
        
        # ⭐ NEW: Added null check before accessing
        if not gcs_path.startswith('gs://'):
            raise ValueError(
                f"Invalid gcs_path format: {gcs_path}. "
                f"Expected gs://bucket/path format from scraper {scraper_name}"
            )
        
        # Parse GCS path into bucket and name
        # Format: gs://bucket-name/path/to/file.json
        path_without_protocol = gcs_path[5:]  # Remove 'gs://'
        parts = path_without_protocol.split('/', 1)
        
        if len(parts) != 2:
            raise ValueError(
                f"Invalid gcs_path structure: {gcs_path}. "
                f"Expected gs://bucket/path format from scraper {scraper_name}"
            )
        
        bucket = parts[0]
        name = parts[1]
        
        # Create normalized message preserving scraper metadata
        normalized = {
            'bucket': bucket,
            'name': name,
            '_original_format': 'scraper_completion',
            '_scraper_name': scraper_name,
            '_execution_id': message.get('execution_id'),
            '_status': status,
            '_record_count': message.get('record_count'),
            '_duration_seconds': message.get('duration_seconds'),
            '_workflow': message.get('workflow'),
            '_timestamp': message.get('timestamp')
        }
        
        logger.info(
            f"Normalized scraper message: bucket={bucket}, name={name}, "
            f"scraper={scraper_name}, status={status}"
        )
        
        return normalized
    
    # Case 4: Only gcs_path present (fallback for scrapers with incomplete messages)
    # This handles cases where the message only contains 'gcs_path' without 'scraper_name'
    if 'gcs_path' in message:
        gcs_path = message.get('gcs_path')
        logger.warning(f"Processing message with only gcs_path (no scraper_name): {gcs_path}")

        if not gcs_path or not gcs_path.startswith('gs://'):
            raise ValueError(f"Invalid gcs_path format: {gcs_path}. Expected gs://bucket/path format")

        # Parse GCS path into bucket and name
        path_without_protocol = gcs_path[5:]  # Remove 'gs://'
        parts = path_without_protocol.split('/', 1)

        if len(parts) != 2:
            raise ValueError(f"Invalid gcs_path structure: {gcs_path}. Expected gs://bucket/path format")

        bucket = parts[0]
        name = parts[1]

        # Create normalized message
        normalized = {
            'bucket': bucket,
            'name': name,
            '_original_format': 'gcs_path_only',
            '_scraper_name': 'unknown',
            '_status': message.get('status', 'unknown'),
            '_record_count': message.get('record_count'),
        }

        logger.info(f"Normalized gcs_path-only message: bucket={bucket}, name={name}")
        return normalized

    # Case 5: Unrecognized format
    available_fields = list(message.keys())
    raise ValueError(
        f"Unrecognized message format. "
        f"Expected 'name' (GCS), 'gcs_path' (Scraper), or 'processor_name' (Unified) field. "
        f"Got fields: {available_fields}"
    )


@app.route('/process', methods=['POST'])
def process_pubsub():
    """
    Handle Pub/Sub messages for file processing.
    
    Supports two message formats:
    
    1. GCS Object Finalize (original):
    {
        "bucket": "nba-scraped-data",
        "name": "basketball_reference/season_rosters/2023-24/LAL.json",
        "timeCreated": "2024-01-15T10:30:00Z"
    }
    
    2. Scraper Completion (new):
    {
        "scraper_name": "bdl_boxscores",
        "gcs_path": "gs://nba-scraped-data/ball-dont-lie/boxscores/2024-01-15/timestamp.json",
        "execution_id": "abc-123",
        "status": "success",
        "record_count": 150
    }
    """
    envelope = request.get_json()
    
    if not envelope:
        try:
            notify_error(
                title="Processor Service: Empty Pub/Sub Message",
                message="No Pub/Sub message received",
                details={
                    'service': 'processor-orchestration',
                    'endpoint': '/process',
                    'issue': 'Empty request body'
                },
                processor_name="Processor Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        return jsonify({"error": "No Pub/Sub message received"}), 400
    
    # Decode Pub/Sub message
    if 'message' not in envelope:
        try:
            notify_error(
                title="Processor Service: Invalid Pub/Sub Format",
                message="Missing 'message' field in Pub/Sub envelope",
                details={
                    'service': 'processor-orchestration',
                    'endpoint': '/process',
                    'envelope_keys': list(envelope.keys()),
                    'issue': 'Invalid message format'
                },
                processor_name="Processor Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400
    
    try:
        # Decode the message
        pubsub_message = envelope['message']
        
        if 'data' in pubsub_message:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            message = json.loads(data)
        else:
            try:
                notify_error(
                    title="Processor Service: Missing Message Data",
                    message="No data field in Pub/Sub message",
                    details={
                        'service': 'processor-orchestration',
                        'message_keys': list(pubsub_message.keys()),
                        'issue': 'Missing data field'
                    },
                    processor_name="Processor Orchestration"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return jsonify({"error": "No data in Pub/Sub message"}), 400
        
        # ✅ NEW: Normalize message format (handles both GCS and Scraper formats)
        try:
            normalized_message = normalize_message_format(message)

            if normalized_message.get('skip_processing'):
                reason = normalized_message.get('reason')
                scraper = normalized_message.get('scraper_name')
                status = normalized_message.get('status')
                
                logger.info(
                    f"Skipping processing for {scraper} (status={status}): {reason}"
                )
                
                # Return 204 No Content - successful but no processing needed
                # This tells Pub/Sub to ACK the message without retrying
                return '', 204
        except ValueError as e:
            logger.error(f"Invalid message format: {e}", exc_info=True)
            try:
                notify_error(
                    title="Processor Service: Invalid Message Format",
                    message=f"Message format not recognized: {str(e)}",
                    details={
                        'service': 'processor-orchestration',
                        'error': str(e),
                        'message_fields': list(message.keys()),
                        'message_sample': str(message)[:500]
                    },
                    processor_name="Processor Orchestration"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return jsonify({"error": f"Invalid message format: {str(e)}"}), 400
        
        # ============================================================
        # SPECIAL HANDLING: Batch Processing Trigger
        # Check if this is a batch processing trigger (from scraper backfill)
        # ============================================================
        metadata = normalized_message.get('_metadata', {})
        if metadata.get('trigger_type') == 'batch_processing':
            logger.info(f"📦 Batch processing trigger detected: {metadata}")

            try:
                # Determine which batch processor to use
                scraper_type = metadata.get('scraper_type', '')
                scraper_name = normalized_message.get('_scraper_name', '')

                # Route to appropriate batch processor
                if scraper_type == 'espn_roster' or 'espn_roster' in scraper_name:
                    # ESPN Roster Batch Processor
                    processor = EspnRosterBatchProcessor()
                    processor_name = 'espn_roster_batch'
                    context_key = 'date'
                    context_value = metadata.get('date', 'unknown')
                else:
                    # Default: Basketball Reference Roster Batch Processor
                    processor = BasketballRefRosterBatchProcessor()
                    processor_name = 'br_roster_batch'
                    context_key = 'season'
                    context_value = metadata.get('season', 'unknown')

                opts = {
                    'bucket': normalized_message.get('bucket', 'nba-scraped-data'),
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'metadata': metadata,
                    'execution_id': normalized_message.get('_execution_id'),
                    'workflow': normalized_message.get('_workflow', 'backfill')
                }

                logger.info(f"🚀 Starting {processor_name} for {context_key}={context_value}")
                success = processor.run(opts)

                if success:
                    logger.info(f"✅ Batch processing complete: {processor_name} {context_key}={context_value}")
                    return jsonify({"status": "success", "processor": processor_name}), 200
                else:
                    logger.error(f"❌ Batch processing failed: {processor_name} {context_key}={context_value}")
                    return jsonify({"status": "error", "processor": processor_name}), 500

            except Exception as e:
                logger.error(f"Batch processing error: {e}", exc_info=True)
                return jsonify({"status": "error", "message": str(e)}), 500

        # Extract file info from normalized message
        bucket = normalized_message.get('bucket', 'nba-scraped-data')
        file_path = normalized_message['name']

        # ✅ NEW: Enhanced logging with scraper context
        if normalized_message.get('_original_format') == 'scraper_completion':
            logger.info(
                f"📥 Processing scraper output: gs://{bucket}/{file_path} "
                f"(scraper={normalized_message.get('_scraper_name')}, "
                f"status={normalized_message.get('_status')}, "
                f"records={normalized_message.get('_record_count')}, "
                f"execution_id={normalized_message.get('_execution_id')})"
            )
        else:
            logger.info(f"📥 Processing file: gs://{bucket}/{file_path}")

        # ============================================================
        # SPECIAL HANDLING: ESPN roster folder paths
        # The ESPN roster scraper publishes a folder path like:
        #   espn/rosters/2025-12-28/
        # But individual files are in subfolders:
        #   espn/rosters/2025-12-28/team_ATL/timestamp.json
        # We need to iterate over all files and process each one.
        # ============================================================
        if 'espn/rosters' in file_path and file_path.endswith('/'):
            logger.info(f"🔄 ESPN roster folder detected, listing files...")
            try:
                storage_client = storage.Client()
                bucket_obj = storage_client.bucket(bucket)
                blobs = list(bucket_obj.list_blobs(prefix=file_path))

                json_files = [b.name for b in blobs if b.name.endswith('.json')]
                logger.info(f"Found {len(json_files)} JSON files in {file_path}")

                if not json_files:
                    logger.warning(f"No JSON files found in folder: {file_path}")
                    return jsonify({"status": "skipped", "reason": "No files in folder"}), 200

                # Process each file
                results = {"processed": 0, "failed": 0, "files": []}
                for json_file in json_files:
                    try:
                        opts = extract_opts_from_path(json_file)
                        opts['bucket'] = bucket
                        opts['file_path'] = json_file
                        opts['project_id'] = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

                        # Add trigger context for error notifications
                        opts['trigger_source'] = normalized_message.get('_original_format', 'unknown')
                        opts['trigger_message_id'] = pubsub_message.get('messageId', 'N/A')
                        opts['parent_processor'] = normalized_message.get('_scraper_name', 'N/A')
                        opts['workflow'] = normalized_message.get('_workflow', 'N/A')
                        opts['execution_id'] = normalized_message.get('_execution_id', 'N/A')

                        processor = EspnTeamRosterProcessor()
                        success = processor.run(opts)

                        if success:
                            results["processed"] += 1
                            logger.info(f"✅ Processed ESPN roster: {json_file}")
                        else:
                            results["failed"] += 1
                            logger.error(f"❌ Failed to process ESPN roster: {json_file}")

                        results["files"].append({
                            "file": json_file,
                            "status": "success" if success else "error"
                        })

                    except Exception as file_error:
                        results["failed"] += 1
                        logger.error(f"❌ Error processing {json_file}: {file_error}")
                        results["files"].append({
                            "file": json_file,
                            "status": "error",
                            "error": str(file_error)
                        })

                logger.info(f"📊 ESPN roster batch: {results['processed']} processed, {results['failed']} failed")
                return jsonify({
                    "status": "success" if results["failed"] == 0 else "partial",
                    "processed": results["processed"],
                    "failed": results["failed"],
                    "files": results["files"][:10]  # Limit response size
                }), 200 if results["failed"] == 0 else 207

            except Exception as folder_error:
                logger.error(f"❌ Error processing ESPN roster folder: {folder_error}", exc_info=True)
                return jsonify({"error": str(folder_error)}), 500

        # Determine processor based on file path
        processor_class = None
        for path_prefix, proc_class in PROCESSOR_REGISTRY.items():
            if path_prefix in file_path:
                processor_class = proc_class
                break
        
        if not processor_class:
            # Check if this is an intentionally skipped path (events, metadata, etc.)
            is_skip_path = any(skip_path in file_path for skip_path in SKIP_PROCESSING_PATHS)

            if is_skip_path:
                logger.info(f"Skipping file (no processing needed): {file_path}")
                return jsonify({"status": "skipped", "reason": "Intentionally not processed"}), 200

            logger.warning(f"No processor found for file: {file_path}")

            # Send notification for unregistered file type
            try:
                notify_warning(
                    title="Processor Service: No Processor Found",
                    message=f"No processor registered for file path pattern",
                    details={
                        'service': 'processor-orchestration',
                        'file_path': file_path,
                        'bucket': bucket,
                        'registered_patterns': list(PROCESSOR_REGISTRY.keys()),
                        'action': 'Add processor to PROCESSOR_REGISTRY if this is a new data source'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

            return jsonify({"status": "skipped", "reason": "No processor for file type"}), 200
        
        # Extract metadata from file path
        try:
            opts = extract_opts_from_path(file_path)
        except Exception as e:
            logger.error(f"Failed to extract opts from path: {file_path}", exc_info=True)
            try:
                notify_warning(
                    title="Processor Service: Path Extraction Failed",
                    message=f"Could not extract options from file path: {str(e)}",
                    details={
                        'service': 'processor-orchestration',
                        'file_path': file_path,
                        'processor': processor_class.__name__,
                        'error': str(e),
                        'action': 'Check file naming convention'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            # Continue with empty opts rather than failing
            opts = {}
        
        opts['bucket'] = bucket
        opts['file_path'] = file_path
        opts['project_id'] = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

        # Add trigger context for error notifications
        opts['trigger_source'] = normalized_message.get('_original_format', 'unknown')
        opts['trigger_message_id'] = pubsub_message.get('messageId', 'N/A')
        opts['parent_processor'] = normalized_message.get('_scraper_name', 'N/A')
        opts['workflow'] = normalized_message.get('_workflow', 'N/A')
        opts['execution_id'] = normalized_message.get('_execution_id', 'N/A')

        # Process the file
        processor = processor_class()
        success = processor.run(opts)
        
        if success:
            stats = processor.get_processor_stats()
            logger.info(f"✅ Successfully processed {file_path}: {stats}")
            return jsonify({
                "status": "success",
                "file": file_path,
                "stats": stats
            }), 200
        else:
            # Note: ProcessorBase already sent detailed error notification
            # This is just for orchestration logging
            logger.error(f"❌ Failed to process {file_path}")
            return jsonify({
                "status": "error",
                "file": file_path
            }), 500
            
    except KeyError as e:
        # Missing required field in message
        logger.error(f"Missing required field in message: {e}", exc_info=True)
        try:
            # Extract scraper/workflow info from message if available
            message_data = message if 'message' in locals() else {}
            scraper_name = message_data.get('scraper_name') if isinstance(message_data, dict) else None
            workflow = message_data.get('workflow') if isinstance(message_data, dict) else None
            execution_id = message_data.get('execution_id') if isinstance(message_data, dict) else None

            # Create error context
            error_context = extract_error_context_from_exception(
                exc=e,
                scraper_name=scraper_name,
                processor_name="Processor Orchestration",
                message_data=message_data,
                workflow=workflow,
                execution_id=execution_id
            )

            # Send enhanced notification
            send_enhanced_error_notification(error_context)

        except Exception as notify_ex:
            logger.warning(f"Failed to send enhanced notification: {notify_ex}")
        return jsonify({"error": f"Missing required field: {str(e)}"}), 400
        
    except json.JSONDecodeError as e:
        # Invalid JSON in message data
        logger.error(f"Invalid JSON in message data: {e}", exc_info=True)
        try:
            # Create error context
            error_context = extract_error_context_from_exception(
                exc=e,
                processor_name="Processor Orchestration",
                message_data={'raw_data': data[:200] if 'data' in locals() else 'unavailable'}
            )

            # Send enhanced notification
            send_enhanced_error_notification(error_context)

        except Exception as notify_ex:
            logger.warning(f"Failed to send enhanced notification: {notify_ex}")
        return jsonify({"error": f"Invalid JSON: {str(e)}"}), 400
        
    except Exception as e:
        # Unexpected orchestration error
        logger.error(f"Error processing message: {e}", exc_info=True)
        try:
            # Extract context from local variables
            message_data = message if 'message' in locals() else {}
            scraper_name = message_data.get('scraper_name') if isinstance(message_data, dict) else None
            workflow = message_data.get('workflow') if isinstance(message_data, dict) else None
            execution_id = message_data.get('execution_id') if isinstance(message_data, dict) else None
            processor_name = processor_class.__name__ if 'processor_class' in locals() else "Processor Orchestration"

            # Create error context
            error_context = extract_error_context_from_exception(
                exc=e,
                scraper_name=scraper_name,
                processor_name=processor_name,
                message_data=message_data,
                workflow=workflow,
                execution_id=execution_id
            )

            # Send enhanced notification
            send_enhanced_error_notification(error_context)

        except Exception as notify_ex:
            logger.warning(f"Failed to send enhanced notification: {notify_ex}")
        return jsonify({"error": str(e)}), 500


def extract_opts_from_path(file_path: str) -> dict:
    """
    Extract processing options from file path.
    Examples:
    - basketball_reference/season_rosters/2023-24/LAL.json
    - ball-dont-lie/standings/2024-25/2025-01-15/timestamp.json
    - ball-dont-lie/injuries/2025-01-15/timestamp.json
    - ball-dont-lie/boxscores/2021-12-04/timestamp.json
    - ball-dont-lie/active-players/2025-01-15/timestamp.json  # NEW
    """
    opts = {}
    
    if 'basketball-ref/season-rosters' in file_path:
        # Extract season and team
        parts = file_path.split('/')
        season_str = parts[-2]  # "2023-24"
        team_abbrev = parts[-1].replace('.json', '')  # "LAL"
        season_year = int(season_str.split('-')[0])  # 2023
        
        opts['season_year'] = season_year
        opts['team_abbrev'] = team_abbrev
        
    elif 'ball-dont-lie/standings' in file_path:
        # Extract date from path: ball-dont-lie/standings/2024-25/2025-01-15/timestamp.json
        parts = file_path.split('/')
        date_str = parts[-2]  # "2025-01-15"
        season_formatted = parts[-3]  # "2024-25"
        
        # Parse date
        try:
            from datetime import datetime
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            opts['date_recorded'] = date_obj
        except ValueError:
            logger.warning(f"Could not parse date from path: {date_str}")
        
        # Parse season year from formatted string
        try:
            season_year = int(season_formatted.split('-')[0])  # 2024
            opts['season_year'] = season_year
        except ValueError:
            logger.warning(f"Could not parse season from path: {season_formatted}")
    
    elif 'ball-dont-lie/injuries' in file_path:
        # Extract date from path: ball-dont-lie/injuries/2025-01-15/timestamp.json
        parts = file_path.split('/')
        date_str = parts[-2]  # "2025-01-15"
        
        # Parse scrape date
        try:
            from datetime import datetime
            scrape_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            opts['scrape_date'] = scrape_date
            
            # Calculate season year (Oct-Sept NBA season)
            season_year = scrape_date.year if scrape_date.month >= 10 else scrape_date.year - 1
            opts['season_year'] = season_year
            
        except ValueError:
            logger.warning(f"Could not parse date from injuries path: {date_str}")
    
    elif 'ball-dont-lie/live-boxscores' in file_path:
        # Extract date from path: ball-dont-lie/live-boxscores/2025-12-27/timestamp.json
        # NOTE: This check MUST come before 'ball-dont-lie/boxscores' due to substring matching
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2025-12-27"

            # Parse game date
            try:
                from datetime import datetime
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['game_date'] = game_date

            except ValueError:
                logger.warning(f"Could not parse date from live-boxscores path: {date_str}")

    elif 'ball-dont-lie/player-box-scores' in file_path:
        # Extract date from the JSON data itself, not the file path
        # NOTE: This check MUST come before 'ball-dont-lie/boxscores' due to substring matching
        #
        # IMPORTANT: For backfill files, the file path date (e.g., 2026-01-01) may differ from
        # the actual game dates in the data (e.g., Nov 10-12). We must read the JSON to get
        # the correct dates to avoid run history conflicts.
        try:
            from datetime import datetime
            from google.cloud import storage

            # Download and read the JSON file to get actual dates
            storage_client = storage.Client()
            bucket_name = 'nba-scraped-data'  # Standard bucket for all scraped data
            bucket_obj = storage_client.bucket(bucket_name)
            blob = bucket_obj.blob(file_path)
            file_content = blob.download_as_text()
            file_data = json.loads(file_content)

            # Get actual date range from the data
            start_date_str = file_data.get('startDate')
            end_date_str = file_data.get('endDate')

            if start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

                # Use start_date for run history tracking (single date key)
                opts['game_date'] = start_date

                # Store both dates for processor use
                opts['start_date'] = start_date
                opts['end_date'] = end_date
                opts['is_multi_date'] = (start_date != end_date)

                # Calculate season year from start date
                season_year = start_date.year if start_date.month >= 10 else start_date.year - 1
                opts['season_year'] = season_year

                logger.info(f"BDL player-box-scores: actual dates {start_date} to {end_date} (file created {file_path.split('/')[-2]})")
            else:
                # Fallback to file path date if JSON doesn't have dates
                parts = file_path.split('/')
                if len(parts) >= 4:
                    date_str = parts[-2]
                    game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    opts['game_date'] = game_date
                    season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
                    opts['season_year'] = season_year
                    logger.warning(f"BDL player-box-scores: using file path date {game_date} (startDate/endDate not in JSON)")

        except Exception as e:
            logger.error(f"Failed to read dates from BDL player-box-scores file: {e}")
            # Fallback to file path parsing
            parts = file_path.split('/')
            if len(parts) >= 4:
                try:
                    date_str = parts[-2]
                    game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    opts['game_date'] = game_date
                    season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
                    opts['season_year'] = season_year
                except ValueError:
                    logger.warning(f"Could not parse date from player-box-scores path: {date_str}")

    elif 'ball-dont-lie/boxscores' in file_path:
        # Extract date from path: ball-dont-lie/boxscores/2021-12-04/timestamp.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2021-12-04"

            # Parse game date
            try:
                from datetime import datetime
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['game_date'] = game_date

                # Calculate season year (Oct-Sept NBA season)
                season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
                opts['season_year'] = season_year

            except ValueError:
                logger.warning(f"Could not parse date from boxscores path: {date_str}")
    
    # ADD THIS NEW CASE FOR ACTIVE PLAYERS
    elif 'ball-dont-lie/active-players' in file_path:
        # Extract date from path: ball-dont-lie/active-players/2025-01-15/timestamp.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2025-01-15"
            
            # Parse collection date
            try:
                from datetime import datetime
                collection_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['collection_date'] = collection_date
                
                # Calculate season year (Oct-Sept NBA season)
                season_year = collection_date.year if collection_date.month >= 10 else collection_date.year - 1
                opts['season_year'] = season_year
                
            except ValueError:
                logger.warning(f"Could not parse date from active-players path: {date_str}")
    
    elif 'nba-com/scoreboard-v2' in file_path:
        # NBA.com Scoreboard V2 files have date in path
        # Format: /nba-com/scoreboard-v2/{date}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            try:
                date_str = parts[-2]  # Extract date from path
                opts['scoreDate'] = date_str
            except (IndexError, ValueError):
                pass

    elif 'espn/boxscores' in file_path:
            # Extract game info from ESPN boxscore path
            # Path format: /espn/boxscores/{date}/game_{id}/{timestamp}.json
            parts = file_path.split('/')
            for i, part in enumerate(parts):
                if part == 'boxscores' and i + 1 < len(parts):
                    opts['game_date'] = parts[i + 1]
                elif part.startswith('game_') and i + 1 < len(parts):
                    opts['espn_game_id'] = part.replace('game_', '')

    elif 'espn/rosters' in file_path:
        # Extract team and date from ESPN roster path
        # Path format: espn/rosters/{date}/team_{team_abbr}/{timestamp}.json
        parts = file_path.split('/')
        
        # Extract date
        for part in parts:
            if len(part) == 10 and part.count('-') == 2:  # YYYY-MM-DD format
                try:
                    opts['roster_date'] = part
                    break
                except Exception as e:
                    logger.warning(f"Failed to set roster_date from path part '{part}': {e}")
                    # Continue trying other parts
        
        # Extract team abbreviation from team_{abbr} folder
        for part in parts:
            if part.startswith('team_') and len(part) > 5:
                opts['team_abbr'] = part[5:]  # Remove 'team_' prefix
                break

    elif 'nba-com/player-boxscores' in file_path:  # ADD THIS BLOCK
        # Extract date from path like: /nba-com/player-boxscores/2024-01-15/timestamp.json
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_path)
        if date_match:
            opts['date'] = date_match.group(1)

    elif 'nba-com/play-by-play' in file_path:
        # Extract game date and game ID from play-by-play path
        # Format: /nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json
        parts = file_path.split('/')
        
        # Find date part (YYYY-MM-DD format)
        for part in parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                opts['game_date'] = part
                break
        
        # Find game ID from game_{gameId} directory
        for part in parts:
            if part.startswith('game_'):
                opts['nba_game_id'] = part.replace('game_', '')
                break
    
    elif 'bettingpros/player-props' in file_path:
        # Extract market type from BettingPros path
        # Pattern: /bettingpros/player-props/{market_type}/{date}/{timestamp}.json
        parts = file_path.split('/')
        try:
            if 'player-props' in parts:
                market_idx = parts.index('player-props')
                if market_idx + 1 < len(parts):
                    opts['market_type'] = parts[market_idx + 1]  # Extract 'points', 'rebounds', etc.
        except (ValueError, IndexError):
            pass

    elif 'espn/scoreboard' in file_path:
        # Extract game date from path: espn/scoreboard/{date}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 3:
            opts['game_date'] = parts[-2]  # Extract date from path

    elif 'big-data-ball' in file_path or 'bigdataball' in file_path:
        # BigDataBall play-by-play files
        # Path formats: 
        # - /big-data-ball/{season}/{date}/game_{id}/{filename}.csv
        # - /bigdataball/{season}/{date}/game_{id}/{filename}.csv
        parts = file_path.split('/')
        
        # Find date part (YYYY-MM-DD format)
        for part in parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                opts['game_date'] = part
                
                # Calculate season year from game date
                try:
                    from datetime import datetime
                    game_date_obj = datetime.strptime(part, '%Y-%m-%d').date()
                    season_year = game_date_obj.year if game_date_obj.month >= 10 else game_date_obj.year - 1
                    opts['season_year'] = season_year
                except ValueError:
                    logger.warning(f"Could not parse date from BigDataBall path: {part}")
                break
        
        # Find game ID from game_{gameId} directory  
        for part in parts:
            if part.startswith('game_'):
                opts['game_id'] = part.replace('game_', '')
                break

    elif 'nba-com/referee-assignments' in file_path:
        # Extract date from referee path: /nba-com/referee-assignments/{date}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            date_str = parts[-2]  # "2025-01-01"
            
            # Parse referee assignment date
            try:
                from datetime import datetime
                assignment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                opts['assignment_date'] = assignment_date
                
                # Calculate season year (Oct-Sept NBA season)
                season_year = assignment_date.year if assignment_date.month >= 10 else assignment_date.year - 1
                opts['season_year'] = season_year
                
            except ValueError:
                logger.warning(f"Could not parse date from referee path: {date_str}")

    elif 'odds-api/game-lines-history' in file_path:
        # Extract metadata from path: odds-api/game-lines-history/date/hash-teams/file.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            opts['game_date'] = parts[-3]
            opts['game_hash_teams'] = parts[-2]
            opts['filename'] = parts[-1]
            
            # Extract snapshot timestamp if available
            if 'snap-' in parts[-1]:
                snapshot_part = parts[-1].split('snap-')[-1].replace('.json', '')
                opts['snapshot_timestamp'] = snapshot_part

    elif 'nba-com/schedule' in file_path:
        # Extract metadata from path: /nba-com/schedule/{season}/{timestamp}.json
        parts = file_path.split('/')
        if len(parts) >= 4:
            season_str = parts[-2]  # Extract season like "2023-24"
            
            try:
                # Parse season year (2023 for 2023-24)
                season_year = int(season_str.split('-')[0])
                opts['season_year'] = season_year
                opts['season_nba_format'] = season_str
                
            except (ValueError, IndexError):
                logger.warning(f"Could not parse season from path: {season_str}")

    elif 'nba-com/gamebooks-data' in file_path:
        # Path: nba-com/gamebooks-data/2025-12-21/20251221-TORBKN/timestamp.json
        from datetime import datetime as dt
        parts = file_path.split('/')
        try:
            # Find date part (YYYY-MM-DD format)
            for part in parts:
                if len(part) == 10 and part[4] == '-' and part[7] == '-':
                    game_date = dt.strptime(part, '%Y-%m-%d').date()
                    opts['game_date'] = game_date
                    opts['date'] = str(game_date)

                    # Calculate season year (Oct-Sept NBA season)
                    season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
                    opts['season_year'] = season_year
                    break
        except ValueError:
            logger.warning(f"Could not parse date from gamebook path: {file_path}")

    return opts    


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)