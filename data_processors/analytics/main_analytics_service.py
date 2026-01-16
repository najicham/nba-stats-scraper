"""
File: analytics_processors/main_analytics_service.py

Main analytics service for Cloud Run
Handles Pub/Sub messages when raw data processing completes
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date, timedelta
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import analytics processors
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
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
def process_date_range():
    """
    Process analytics for a date range (manual trigger).
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
