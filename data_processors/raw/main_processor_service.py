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
from datetime import datetime, timezone, timedelta
import base64
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from google.cloud import storage, firestore
from google.api_core.exceptions import GoogleAPIError, NotFound, ServiceUnavailable, DeadlineExceeded
from google.cloud.exceptions import Conflict as AlreadyExistsError
import requests.exceptions

# Timeout for OddsAPI batch processing (10 minutes)
# This prevents runaway batch jobs from exceeding the Firestore lock TTL (2 hours)
BATCH_PROCESSOR_TIMEOUT_SECONDS = 600

# Initialize Sentry first (before other imports that might error)
from shared.utils.sentry_config import configure_sentry
configure_sentry()

# Import GCP config
from shared.config.gcp_config import get_project_id

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
from data_processors.raw.oddsapi.oddsapi_batch_processor import OddsApiGameLinesBatchProcessor, OddsApiPropsBatchProcessor
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

# Import MLB processors
from data_processors.raw.mlb import (
    MlbPitcherStatsProcessor,
    MlbBatterStatsProcessor,
    MlbScheduleProcessor,
    MlbLineupsProcessor,
    MlbPitcherPropsProcessor,
    MlbBatterPropsProcessor,
    MlbEventsProcessor,
    MlbGameLinesProcessor,
)


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

    # ============================
    # MLB Processors
    # ============================
    'ball-dont-lie/mlb-pitcher-stats': MlbPitcherStatsProcessor,
    'ball-dont-lie/mlb-batter-stats': MlbBatterStatsProcessor,
    'mlb-stats-api/schedule': MlbScheduleProcessor,
    'mlb-stats-api/lineups': MlbLineupsProcessor,
    'mlb-odds-api/pitcher-props': MlbPitcherPropsProcessor,
    'mlb-odds-api/batter-props': MlbBatterPropsProcessor,
    'mlb-odds-api/events': MlbEventsProcessor,
    'mlb-odds-api/game-lines': MlbGameLinesProcessor,
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
    from shared.clients.bigquery_pool import get_bigquery_client

    logger = logging.getLogger(__name__)

    try:
        data = request.get_json() or {}
        check_days = data.get('check_days', 1)
        alert_on_gaps = data.get('alert_on_gaps', True)

        end_date = date.today() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=check_days - 1)

        logger.info(f"Checking boxscore completeness: {start_date} to {end_date}")

        bq_client = get_bigquery_client()

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
                    details={'warning_teams': warning_teams, 'missing_count': missing_count},
                processor_name="Main Processor Service"
                )

        status = 'critical' if critical_teams else ('warning' if warning_teams else 'ok')

        # Auto-reset circuit breakers for players/teams that now have data
        # This prevents cascading lockouts when data gaps are backfilled
        reset_count = 0
        try:
            auto_reset = data.get('auto_reset_circuit_breakers', True)
            if auto_reset:
                reset_count = _auto_reset_circuit_breakers(bq_client, start_date, end_date, logger)
        except (GoogleAPIError, KeyError, AttributeError) as reset_error:
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

    except (GoogleAPIError, KeyError, ValueError, TypeError) as e:
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
    except (GoogleAPIError, DeadlineExceeded) as e:
        logger.warning(f"Circuit breaker auto-reset query failed: {e}")
        return 0


@app.route('/process', methods=['POST'])
def process_pubsub():
    """
    Handle Pub/Sub messages for file processing.

    Supports three message formats:
    1. GCS Object Finalize (legacy)
    2. Scraper Completion (v1)
    3. Unified Format (v2)

    Routes to appropriate batch or file processor.
    """
    from .handlers import (
        MessageHandler,
        BatchDetector,
        ESPNBatchHandler,
        BRBatchHandler,
        OddsAPIBatchHandler,
        FileProcessor
    )

    envelope = request.get_json()

    # Validate envelope
    if not envelope:
        try:
            notify_error(
                title="Processor Service: Empty Pub/Sub Message",
                message="No Pub/Sub message received",
                details={'service': 'processor-orchestration', 'endpoint': '/process'},
                processor_name="Processor Orchestration"
            )
        except (requests.exceptions.RequestException, GoogleAPIError, ValueError, TypeError) as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        return jsonify({"error": "No Pub/Sub message received"}), 400

    try:
        # Decode and normalize message
        handler = MessageHandler()
        message = handler.decode_message(envelope)
        normalized_message = handler.normalize_format(message)

        # Handle skip processing cases
        if normalized_message.get('skip_processing'):
            logger.info(
                f"Skipping processing for {normalized_message.get('scraper_name')} "
                f"(status={normalized_message.get('status')}): {normalized_message.get('reason')}"
            )
            return '', 204

        # Detect batch processing
        detector = BatchDetector()
        if detector.is_batch_trigger(normalized_message):
            batch_type = detector.get_batch_type(normalized_message)
            project_id = get_project_id()

            # Route to appropriate batch handler
            if batch_type == 'espn_backfill':
                result = ESPNBatchHandler().process_backfill(normalized_message, project_id)
            elif batch_type == 'espn_folder':
                result = ESPNBatchHandler().process_folder(
                    normalized_message['name'],
                    normalized_message.get('bucket', 'nba-scraped-data'),
                    project_id
                )
            elif batch_type == 'espn':
                result = ESPNBatchHandler().process_with_lock(
                    normalized_message['name'],
                    normalized_message.get('bucket', 'nba-scraped-data'),
                    project_id,
                    normalized_message.get('_execution_id', 'unknown')
                )
            elif batch_type == 'br_backfill':
                result = BRBatchHandler().process_backfill(normalized_message, project_id)
            elif batch_type == 'br':
                result = BRBatchHandler().process_with_lock(
                    normalized_message['name'],
                    normalized_message.get('bucket', 'nba-scraped-data'),
                    project_id,
                    normalized_message.get('_execution_id', 'unknown')
                )
            elif batch_type in ('oddsapi_game_lines', 'oddsapi_props'):
                result = OddsAPIBatchHandler().process_with_lock(
                    normalized_message['name'],
                    normalized_message.get('bucket', 'nba-scraped-data'),
                    project_id,
                    normalized_message.get('_execution_id', 'unknown')
                )
            else:
                # Unknown batch type - fallback to file processor
                logger.warning(f"Unknown batch type: {batch_type}, falling back to file processor")
                result = FileProcessor().process(
                    normalized_message,
                    PROCESSOR_REGISTRY,
                    extract_opts_from_path,
                    envelope['message']
                )

            # Return batch result
            status_code = 200 if result['status'] in ('success', 'skipped') else 500
            return jsonify(result), status_code

        # Standard file processing
        result = FileProcessor().process(
            normalized_message,
            PROCESSOR_REGISTRY,
            extract_opts_from_path,
            envelope['message']
        )

        status_code = 200 if result['status'] in ('success', 'skipped') else 500
        return jsonify(result), status_code

    except ValueError as e:
        # Message format or validation error
        logger.error(f"Message error: {e}", exc_info=True)
        try:
            notify_error(
                title="Processor Service: Message Error",
                message=str(e),
                details={'service': 'processor-orchestration', 'error': str(e)},
                processor_name="Processor Orchestration"
            )
        except (requests.exceptions.RequestException, GoogleAPIError, ValueError, TypeError) as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        return jsonify({"error": str(e)}), 400

    except (GoogleAPIError, AttributeError, TypeError, KeyError, json.JSONDecodeError) as e:
        # Unexpected orchestration error
        logger.error(f"Processing error: {e}", exc_info=True)
        try:
            message_data = message if 'message' in locals() else {}
            error_context = extract_error_context_from_exception(
                exc=e,
                processor_name="Processor Orchestration",
                message_data=message_data
            )
            send_enhanced_error_notification(error_context)
        except (requests.exceptions.RequestException, GoogleAPIError, ValueError, TypeError) as notify_ex:
            logger.warning(f"Failed to send enhanced notification: {notify_ex}")
        return jsonify({"error": str(e)}), 500


# Create global registry instance
from .path_extractors import create_registry
_path_extractor_registry = create_registry()


def extract_opts_from_path(file_path: str) -> dict:
    """
    Extract processing options from file path using the extractor registry.

    Args:
        file_path: GCS file path

    Returns:
        Dictionary of extracted options

    Raises:
        ValueError: If no extractor matches the path

    Examples:
        - basketball_reference/season_rosters/2023-24/LAL.json
        - ball-dont-lie/standings/2024-25/2025-01-15/timestamp.json
        - ball-dont-lie/injuries/2025-01-15/timestamp.json
        - nba-com/scoreboard-v2/2024-01-15/timestamp.json
        - espn/rosters/2025-01-15/team_GS/timestamp.json
    """
    return _path_extractor_registry.extract_opts(file_path)    


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)