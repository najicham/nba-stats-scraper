"""
File: analytics_processors/main_analytics_service.py

Main analytics service for Cloud Run
Handles Pub/Sub messages when raw data processing completes
"""

import os
import sys
import json
import logging
from functools import wraps
from flask import Flask, request, jsonify

# Add project root to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.endpoints.health import create_health_blueprint, HealthChecker
from shared.utils.validation import validate_game_date, validate_project_id, ValidationError
from datetime import datetime, timezone, date, timedelta
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import analytics processors
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

# Import BigQuery client for completeness checks
from google.cloud import bigquery

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# AUTHENTICATION (Issue #9: Add Authentication)
# ============================================================================

def require_auth(f):
    """
    Decorator to require API key authentication.

    Validates requests against VALID_API_KEYS environment variable.
    Returns 401 Unauthorized for missing or invalid API keys.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        valid_keys_str = os.getenv('VALID_API_KEYS', '')
        valid_keys = [k.strip() for k in valid_keys_str.split(',') if k.strip()]

        if not api_key or api_key not in valid_keys:
            logger.warning(
                f"Unauthorized access attempt to {request.path} "
                f"(API key {'missing' if not api_key else 'invalid'})"
            )
            return jsonify({"error": "Unauthorized"}), 401

        return f(*args, **kwargs)
    return decorated_function

# Health check endpoints (Phase 1 - Task 1.1: Add Health Endpoints)
# Note: HealthChecker simplified in Week 1 to only require service_name
health_checker = HealthChecker(service_name='analytics-processor')
app.register_blueprint(create_health_blueprint(health_checker))
logger.info("Health check endpoints registered: /health, /ready, /health/deep")

# ============================================================================
# BOXSCORE COMPLETENESS CHECK (Phase 1.2)
# ============================================================================

def verify_boxscore_completeness(game_date: str, project_id: str) -> dict:
    """
    Phase 1.2: Verify all scheduled games have final boxscores before triggering Phase 3.

    This prevents incomplete analytics when some games haven't been scraped yet.

    Args:
        game_date: The date to verify (YYYY-MM-DD)
        project_id: GCP project ID

    Returns:
        dict with keys:
            - complete: bool (all games have boxscores)
            - coverage_pct: float (percentage of games with boxscores)
            - expected_games: int (scheduled games)
            - actual_games: int (games with boxscores)
            - missing_games: list of dicts (games without boxscores)
    """
    # Input validation (Issue #4: Input Validation)
    try:
        game_date = validate_game_date(game_date)
        project_id = validate_project_id(project_id)
    except ValidationError as e:
        logger.error(f"Input validation failed: {e}")
        return {
            "complete": False,
            "error": f"Invalid input: {e}",
            "coverage_pct": 0.0,
            "expected_games": 0,
            "actual_games": 0,
            "missing_games": []
        }

    try:
        bq_client = bigquery.Client(project=project_id)

        # Q1: How many games scheduled and completed?
        # Use parameterized query to prevent SQL injection
        scheduled_query = f"""
        SELECT
            game_id,
            home_team_tricode,
            away_team_tricode
        FROM `{project_id}.nba_raw.nbac_schedule`
        WHERE game_date = @game_date
          AND game_status_text = 'Final'
        """

        job_config_scheduled = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        scheduled_result = list(bq_client.query(scheduled_query, job_config=job_config_scheduled).result())
        scheduled_games = {row.game_id: (row.home_team_tricode, row.away_team_tricode) for row in scheduled_result}
        expected_count = len(scheduled_games)

        # Q2: How many games have boxscores? (Use BDL format: YYYYMMDD_AWAY_HOME)
        # Note: BDL uses different game ID format than NBA.com schedule
        # Use parameterized query to prevent SQL injection
        boxscore_query = f"""
        SELECT DISTINCT game_id
        FROM `{project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date = @game_date
        """

        job_config_boxscore = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
            ]
        )

        boxscore_result = list(bq_client.query(boxscore_query, job_config=job_config_boxscore).result())
        boxscore_game_ids = {row.game_id for row in boxscore_result}
        actual_count = len(boxscore_game_ids)

        # Q3: Which games are missing?
        # Convert NBA.com game IDs to expected BDL format for comparison
        # BDL format: YYYYMMDD_AWAY_HOME (e.g., 20260118_BKN_CHI)
        missing_games = []
        date_part = game_date.replace('-', '')  # 2026-01-18 -> 20260118

        for nba_game_id, (home, away) in scheduled_games.items():
            bdl_game_id = f"{date_part}_{away}_{home}"
            if bdl_game_id not in boxscore_game_ids:
                missing_games.append({
                    "game_id_nba": nba_game_id,
                    "game_id_bdl": bdl_game_id,
                    "home_team": home,
                    "away_team": away
                })

        # Calculate coverage
        coverage = (actual_count / expected_count * 100) if expected_count > 0 else 100

        is_complete = len(missing_games) == 0

        result = {
            "complete": is_complete,
            "coverage_pct": coverage,
            "expected_games": expected_count,
            "actual_games": actual_count,
            "missing_games": missing_games
        }

        if is_complete:
            logger.info(f"✅ Boxscore completeness check PASSED for {game_date}: {actual_count}/{expected_count} games")
        else:
            logger.warning(
                f"⚠️ Boxscore completeness check FAILED for {game_date}: {actual_count}/{expected_count} games "
                f"({coverage:.1f}% coverage). Missing: {len(missing_games)} games"
            )

        return result

    except Exception as e:
        logger.error(f"Boxscore completeness check failed: {e}", exc_info=True)

        # Issue #3: Fail-closed by default to prevent processing with incomplete data
        # Degraded mode escape hatch: set ALLOW_DEGRADED_MODE=true to bypass
        allow_degraded = os.getenv('ALLOW_DEGRADED_MODE', 'false').lower() == 'true'

        if allow_degraded:
            logger.warning(
                "⚠️ DEGRADED MODE: Allowing analytics to proceed despite completeness check failure"
            )
            return {
                "complete": True,
                "coverage_pct": 0,
                "expected_games": 0,
                "actual_games": 0,
                "missing_games": [],
                "error": str(e),
                "degraded_mode": True
            }
        else:
            # Fail-closed: mark as incomplete to block analytics processing
            return {
                "complete": False,
                "coverage_pct": 0,
                "expected_games": 0,
                "actual_games": 0,
                "missing_games": [],
                "error": str(e),
                "is_error_state": True
            }


def trigger_missing_boxscore_scrapes(missing_games: list, game_date: str) -> int:
    """
    Trigger BDL boxscore scraper for the entire date (will catch all missing games).

    Note: BDL box_scores scraper operates on full dates, not individual games.
    This is simpler and ensures we don't miss any games.

    Args:
        missing_games: List of missing game dictionaries
        game_date: Date to re-scrape (YYYY-MM-DD)

    Returns:
        Number of scrape requests triggered (always 1 for date-based scraping)
    """
    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path('nba-props-platform', 'nba-scraper-trigger')

        # Trigger BDL box scores scraper for the entire date
        message_data = {
            "scraper_name": "bdl_box_scores",
            "date": game_date,
            "retry_count": 0,
            "reason": "incomplete_boxscore_coverage_detected",
            "missing_count": len(missing_games)
        }

        future = publisher.publish(
            topic_path,
            json.dumps(message_data).encode('utf-8')
        )
        message_id = future.result(timeout=10)

        logger.info(
            f"🔄 Triggered BDL box scores re-scrape for {game_date} "
            f"(missing {len(missing_games)} games, message_id={message_id})"
        )

        return 1

    except Exception as e:
        logger.error(f"Failed to trigger missing boxscore scrapes: {e}", exc_info=True)
        return 0

def run_single_analytics_processor(processor_class, opts):
    """
    Run a single analytics processor (for parallel execution).

    Args:
        processor_class: Processor class to instantiate
        opts: Options dict for processor.run()

    Returns:
        Dict with processor results
    """
    try:
        logger.info(f"Running {processor_class.__name__} for {opts.get('start_date')}")

        processor = processor_class()
        success = processor.run(opts)

        if success:
            stats = processor.get_analytics_stats()
            logger.info(f"✅ Successfully ran {processor_class.__name__}: {stats}")
            return {
                "processor": processor_class.__name__,
                "status": "success",
                "stats": stats
            }
        else:
            logger.error(f"❌ Failed to run {processor_class.__name__}")
            return {
                "processor": processor_class.__name__,
                "status": "error"
            }
    except Exception as e:
        logger.error(f"❌ Analytics processor {processor_class.__name__} failed: {e}", exc_info=True)
        return {
            "processor": processor_class.__name__,
            "status": "exception",
            "error": str(e)
        }

# Analytics processor registry - maps source tables to dependent analytics processors
ANALYTICS_TRIGGERS = {
    'nbac_gamebook_player_stats': [PlayerGameSummaryProcessor],
    'bdl_player_boxscores': [PlayerGameSummaryProcessor, TeamOffenseGameSummaryProcessor, UpcomingPlayerGameContextProcessor],
    'nbac_scoreboard_v2': [TeamOffenseGameSummaryProcessor, TeamDefenseGameSummaryProcessor, UpcomingTeamGameContextProcessor],
    'bdl_standings': [],  # No analytics dependencies yet
    'nbac_injury_report': [PlayerGameSummaryProcessor],  # Updates player context
    'odds_api_player_points_props': [PlayerGameSummaryProcessor],  # Updates prop context
}

@app.route('/', methods=['GET'])
def index():
    """Root endpoint - service info."""
    return jsonify({
        "status": "healthy",
        "service": "analytics_processors",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/process', methods=['POST'])
def process_analytics():
    """
    Handle Pub/Sub messages for analytics processing.
    Triggered when raw data processing completes.

    Expected message format (from Phase 2 UnifiedPubSubPublisher):
    {
        "processor_name": "BdlBoxscoresProcessor",
        "phase": "phase_2_raw",
        "output_table": "nba_raw.bdl_player_boxscores",
        "output_dataset": "nba_raw",
        "game_date": "2024-01-15",
        "status": "success",
        "record_count": 150
    }

    Also supports legacy format with 'source_table' for backward compatibility.
    """
    envelope = request.get_json()
    
    if not envelope:
        return jsonify({"error": "No Pub/Sub message received"}), 400
    
    # Decode Pub/Sub message
    if 'message' not in envelope:
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400
    
    try:
        # Decode the message
        pubsub_message = envelope['message']
        
        if 'data' in pubsub_message:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            message = json.loads(data)
        else:
            return jsonify({"error": "No data in Pub/Sub message"}), 400
        
        # Extract trigger info
        # Phase 2 processors publish 'output_table' (e.g., "nba_raw.bdl_player_boxscores")
        # For backward compatibility, also check 'source_table'
        raw_table = message.get('output_table') or message.get('source_table')
        game_date = message.get('game_date')
        status = message.get('status', 'success')
        success = message.get('success', status == 'success')

        if not success or status == 'failed':
            logger.info(f"Raw processing failed for {raw_table}, skipping analytics")
            return jsonify({"status": "skipped", "reason": "Raw processing failed"}), 200

        if not raw_table:
            logger.warning(f"Missing output_table/source_table in message: {list(message.keys())}")
            return jsonify({"error": "Missing output_table in message"}), 400

        # Strip dataset prefix if present: "nba_raw.bdl_player_boxscores" -> "bdl_player_boxscores"
        source_table = raw_table.split('.')[-1] if '.' in raw_table else raw_table

        logger.info(f"Processing analytics for {source_table} (from {raw_table}), date: {game_date}")
        
        # Determine which analytics processors to run
        processors_to_run = ANALYTICS_TRIGGERS.get(source_table, [])
        
        if not processors_to_run:
            logger.info(f"No analytics processors configured for {source_table}")
            return jsonify({"status": "no_processors", "source_table": source_table}), 200
        
        # Process analytics for date range (single day or small range)
        start_date = game_date
        end_date = game_date

        # Build options dict for all processors
        opts = {
            'start_date': start_date,
            'end_date': end_date,
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'triggered_by': source_table
        }

        # Phase 1.2: Boxscore completeness pre-flight check
        # Only run this check when triggered by bdl_player_boxscores completion
        # This ensures all scheduled games have boxscores before analytics run
        if source_table == 'bdl_player_boxscores' and game_date:
            logger.info(f"🔍 Running boxscore completeness check for {game_date}")
            completeness = verify_boxscore_completeness(game_date, opts['project_id'])

            if not completeness.get("complete"):
                # Issue #3: Check if this is an error state (fail-closed)
                if completeness.get("is_error_state"):
                    # Completeness check itself failed (BigQuery error, etc.)
                    logger.error(
                        f"❌ Boxscore completeness check ERROR for {game_date}: {completeness.get('error')} "
                        f"(Set ALLOW_DEGRADED_MODE=true to bypass)"
                    )
                    return jsonify({
                        "status": "error",
                        "reason": "completeness_check_failed",
                        "game_date": game_date,
                        "error": completeness.get("error"),
                        "action": "Fix underlying issue or set ALLOW_DEGRADED_MODE=true to bypass"
                    }), 500

                # Not all games have boxscores yet (normal incompleteness)
                missing_count = len(completeness.get("missing_games", []))
                coverage_pct = completeness.get("coverage_pct", 0)

                logger.warning(
                    f"⚠️ Boxscore completeness check FAILED for {game_date}: "
                    f"{completeness['actual_games']}/{completeness['expected_games']} games "
                    f"({coverage_pct:.1f}% coverage). Missing: {missing_count} games"
                )

                # Trigger missing boxscore scrapes
                trigger_missing_boxscore_scrapes(completeness["missing_games"], game_date)

                # Return 500 to trigger Pub/Sub retry
                # When missing scrapes complete, they'll republish and retry analytics
                return jsonify({
                    "status": "delayed",
                    "reason": "incomplete_boxscores",
                    "game_date": game_date,
                    "completeness": {
                        "expected": completeness["expected_games"],
                        "actual": completeness["actual_games"],
                        "coverage_pct": coverage_pct,
                        "missing_count": missing_count
                    },
                    "action": "Triggered re-scrape and will retry analytics when complete"
                }), 500  # 500 triggers Pub/Sub retry
            else:
                logger.info(
                    f"✅ Boxscore completeness check PASSED for {game_date}: "
                    f"{completeness['actual_games']}/{completeness['expected_games']} games"
                )

        # Execute processors in PARALLEL for 75% speedup (20 min → 5 min)
        logger.info(f"🚀 Running {len(processors_to_run)} analytics processors in PARALLEL for {game_date}")
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit all processors for parallel execution
            futures = {
                executor.submit(run_single_analytics_processor, processor_class, opts): processor_class
                for processor_class in processors_to_run
            }

            # Collect results as they complete
            for future in as_completed(futures):
                processor_class = futures[future]
                try:
                    result = future.result(timeout=600)  # 10 min timeout per processor
                    results.append(result)
                except TimeoutError:
                    logger.error(f"⏱️ Processor {processor_class.__name__} timed out after 10 minutes")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "timeout"
                    })
                except Exception as e:
                    logger.error(f"❌ Failed to get result from {processor_class.__name__}: {e}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "exception",
                        "error": str(e)
                    })
        
        # R-002 FIX: Check for failures and return appropriate status code
        # Previously always returned 200, even when processors failed
        failures = [r for r in results if r.get('status') in ('error', 'exception', 'timeout')]
        successes = [r for r in results if r.get('status') == 'success']

        if not successes and failures:
            # All processors failed - return 500 to trigger Pub/Sub retry
            logger.error(
                f"❌ ALL {len(failures)} analytics processors failed for {game_date} "
                f"(source={source_table}) - returning 500 to trigger retry"
            )
            return jsonify({
                "status": "failed",
                "source_table": source_table,
                "game_date": game_date,
                "failures": len(failures),
                "results": results
            }), 500

        if failures:
            # Partial failure - log warning but return 200 to ACK
            # (retrying won't help if some processors succeeded)
            logger.warning(
                f"⚠️ PARTIAL FAILURE: {len(failures)}/{len(results)} analytics processors failed "
                f"for {game_date} (source={source_table})"
            )
            return jsonify({
                "status": "partial_failure",
                "source_table": source_table,
                "game_date": game_date,
                "successes": len(successes),
                "failures": len(failures),
                "results": results
            }), 200  # ACK to prevent infinite retries, but status indicates partial

        # All succeeded
        return jsonify({
            "status": "completed",
            "source_table": source_table,
            "game_date": game_date,
            "results": results
        }), 200

    except Exception as e:
        logger.error(f"Error processing analytics message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/process-date-range', methods=['POST'])
@require_auth
def process_date_range():
    """
    Process analytics for a date range (manual trigger).
    Requires X-API-Key header for authentication.

    POST body: {
        "start_date": "2024-01-01",
        "end_date": "2024-01-07",
        "processors": ["PlayerGameSummaryProcessor"],
        "backfill_mode": true  // Optional: bypass dependency checks
    }
    """
    try:
        data = request.get_json()

        start_date = data.get('start_date')
        end_date = data.get('end_date')
        processor_names = data.get('processors', [])
        backfill_mode = data.get('backfill_mode', False)
        dataset_prefix = data.get('dataset_prefix', '')

        if not start_date or not end_date:
            return jsonify({"error": "start_date and end_date required"}), 400

        # Handle special date values (TODAY/TOMORROW/YESTERDAY = relative to ET timezone)
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        et_now = datetime.now(ZoneInfo('America/New_York'))
        today_et = et_now.date().strftime('%Y-%m-%d')
        yesterday_et = (et_now.date() - timedelta(days=1)).strftime('%Y-%m-%d')
        tomorrow_et = (et_now.date() + timedelta(days=1)).strftime('%Y-%m-%d')

        if start_date == "TODAY":
            start_date = today_et
            logger.info(f"TODAY start_date resolved to: {start_date}")
        elif start_date == "YESTERDAY":
            start_date = yesterday_et
            logger.info(f"YESTERDAY start_date resolved to: {start_date}")
        elif start_date == "TOMORROW":
            start_date = tomorrow_et
            logger.info(f"TOMORROW start_date resolved to: {start_date}")

        if end_date == "TODAY":
            end_date = today_et
            logger.info(f"TODAY end_date resolved to: {end_date}")
        elif end_date == "YESTERDAY":
            end_date = yesterday_et
            logger.info(f"YESTERDAY end_date resolved to: {end_date}")
        elif end_date == "TOMORROW":
            end_date = tomorrow_et
            logger.info(f"TOMORROW end_date resolved to: {end_date}")

        # Map processor names to classes
        processor_map = {
            'PlayerGameSummaryProcessor': PlayerGameSummaryProcessor,
            'TeamOffenseGameSummaryProcessor': TeamOffenseGameSummaryProcessor,
            'TeamDefenseGameSummaryProcessor': TeamDefenseGameSummaryProcessor,
            'UpcomingPlayerGameContextProcessor': UpcomingPlayerGameContextProcessor,
            'UpcomingTeamGameContextProcessor': UpcomingTeamGameContextProcessor,
        }
        
        if not processor_names:
            # Default: run all processors
            processors_to_run = list(processor_map.values())
        else:
            processors_to_run = [processor_map[name] for name in processor_names if name in processor_map]

        # Build options dict for all processors
        opts = {
            'start_date': start_date,
            'end_date': end_date,
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'triggered_by': 'manual',
            'backfill_mode': backfill_mode,
            'dataset_prefix': dataset_prefix
        }

        if backfill_mode:
            logger.info(f"Running {len(processors_to_run)} processors in BACKFILL mode (PARALLEL)")

        # Execute processors in PARALLEL for faster manual runs
        logger.info(f"🚀 Running {len(processors_to_run)} analytics processors in PARALLEL for {start_date} to {end_date}")
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            # Submit all processors for parallel execution
            futures = {
                executor.submit(run_single_analytics_processor, processor_class, opts): processor_class
                for processor_class in processors_to_run
            }

            # Collect results as they complete
            for future in as_completed(futures):
                processor_class = futures[future]
                try:
                    result = future.result(timeout=600)  # 10 min timeout per processor
                    results.append(result)
                except TimeoutError:
                    logger.error(f"⏱️ Processor {processor_class.__name__} timed out after 10 minutes")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "timeout"
                    })
                except Exception as e:
                    logger.error(f"❌ Failed to get result from {processor_class.__name__}: {e}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "exception",
                        "error": str(e)
                    })
        
        return jsonify({
            "status": "completed",
            "date_range": f"{start_date} to {end_date}",
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in manual date range processing: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
