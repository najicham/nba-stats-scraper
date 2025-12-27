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
from data_processors.raw.oddsapi.odds_api_props_processor import OddsApiPropsProcessor
from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
from data_processors.raw.nbacom.nbac_player_list_processor import NbacPlayerListProcessor
from data_processors.raw.balldontlie.bdl_standings_processor import BdlStandingsProcessor
from data_processors.raw.balldontlie.bdl_injuries_processor import BdlInjuriesProcessor
from data_processors.raw.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor
from data_processors.raw.balldontlie.bdl_live_boxscores_processor import BdlLiveBoxscoresProcessor
from data_processors.raw.balldontlie.bdl_active_players_processor import BdlActivePlayersProcessor
from data_processors.raw.nbacom.nbac_player_movement_processor import NbacPlayerMovementProcessor
from data_processors.raw.nbacom.nbac_scoreboard_v2_processor import NbacScoreboardV2Processor
from data_processors.raw.nbacom.nbac_player_boxscore_processor import NbacPlayerBoxscoreProcessor
from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor
from data_processors.raw.nbacom.nbac_play_by_play_processor import NbacPlayByPlayProcessor

from data_processors.raw.espn.espn_boxscore_processor import EspnBoxscoreProcessor
from data_processors.raw.espn.espn_team_roster_processor import EspnTeamRosterProcessor
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
    'ball-dont-lie/boxscores': BdlBoxscoresProcessor,
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
            '_game_date': message.get('game_date')
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
    
    # Case 3: Unrecognized format
    available_fields = list(message.keys())
    raise ValueError(
        f"Unrecognized message format. "
        f"Expected 'name' (GCS) or 'gcs_path' (Scraper) field. "
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
                except:
                    pass
        
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