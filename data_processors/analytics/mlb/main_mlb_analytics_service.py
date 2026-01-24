"""
MLB Analytics Service for Cloud Run

Phase 3 analytics processors for MLB data.
Handles Pub/Sub messages when MLB raw data processing completes.

Endpoints:
- /health: Health check
- /process: Process Pub/Sub trigger
- /process-date: Process specific date (HTTP trigger)
- /process-date-range: Process date range (HTTP trigger)
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date, timedelta
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import MLB analytics processors
from data_processors.analytics.mlb import (
    MlbPitcherGameSummaryProcessor,
    MlbBatterGameSummaryProcessor,
)

# Import AlertManager for intelligent alerting
try:
    from shared.alerts.alert_manager import get_alert_manager
    ALERTING_ENABLED = True
except ImportError:
    ALERTING_ENABLED = False
    logging.warning("AlertManager not available, alerts disabled")

# Import MLB schedule-aware utilities
try:
    from shared.validation.context.mlb_schedule_context import (
        get_mlb_schedule_context,
        is_mlb_offseason,
        is_mlb_all_star_break,
    )
    SCHEDULE_AWARE_ENABLED = True
except ImportError:
    SCHEDULE_AWARE_ENABLED = False
    logging.warning("MLB schedule context not available, schedule-aware checks disabled")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MLB Alert utilities (consolidated in shared module)
from shared.utils.mlb_alert_utils import (
    get_mlb_alert_manager,
    send_mlb_analytics_alert as send_mlb_alert,
)


# MLB Analytics processor registry
MLB_ANALYTICS_PROCESSORS = {
    'pitcher_game_summary': MlbPitcherGameSummaryProcessor,
    'batter_game_summary': MlbBatterGameSummaryProcessor,
}

# Trigger mapping: which raw tables trigger which analytics processors
MLB_ANALYTICS_TRIGGERS = {
    'mlb_pitcher_stats': [MlbPitcherGameSummaryProcessor],
    'bdl_pitcher_stats': [MlbPitcherGameSummaryProcessor],
    'mlb_batter_stats': [MlbBatterGameSummaryProcessor],
    'bdl_batter_stats': [MlbBatterGameSummaryProcessor],
    'mlb_game_lineups': [MlbPitcherGameSummaryProcessor, MlbBatterGameSummaryProcessor],
}


def should_skip_date(game_date_str: str, skip_schedule_check: bool = False) -> tuple:
    """
    Check if a date should be skipped for MLB processing.

    Returns:
        Tuple of (should_skip: bool, reason: str or None)
    """
    if not SCHEDULE_AWARE_ENABLED or skip_schedule_check:
        return False, None

    try:
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        # Check offseason (Oct-Mar)
        if is_mlb_offseason(game_date):
            return True, "MLB offseason - no games scheduled"

        # Check All-Star break
        if is_mlb_all_star_break(game_date):
            return True, "MLB All-Star break - no regular games"

        # Check schedule for actual games
        context = get_mlb_schedule_context(game_date)
        if not context.is_valid_processing_date:
            return True, context.skip_reason or "No games on this date"

        return False, None
    except Exception as e:
        logger.warning(f"Schedule check failed for {game_date_str}: {e}, proceeding with processing")
        return False, None


def run_single_processor(processor_class, opts):
    """Run a single analytics processor."""
    try:
        logger.info(f"Running {processor_class.__name__} for {opts.get('start_date')}")
        processor = processor_class()
        success = processor.run(opts)

        if success:
            stats = processor.get_analytics_stats()
            logger.info(f"Successfully ran {processor_class.__name__}: {stats}")
            return {
                "processor": processor_class.__name__,
                "status": "success",
                "stats": stats
            }
        else:
            logger.error(f"Failed to run {processor_class.__name__}")
            return {
                "processor": processor_class.__name__,
                "status": "error"
            }
    except Exception as e:
        logger.error(f"Analytics processor {processor_class.__name__} failed: {e}", exc_info=True)
        # Send alert for processor failure
        send_mlb_alert(
            severity='warning',
            title=f'MLB Analytics Processor Failed: {processor_class.__name__}',
            message=str(e),
            context={
                'processor': processor_class.__name__,
                'game_date': opts.get('start_date'),
                'error_type': type(e).__name__
            }
        )
        return {
            "processor": processor_class.__name__,
            "status": "exception",
            "error": str(e)
        }


@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "mlb_analytics_processors",
        "sport": "mlb",
        "processors": list(MLB_ANALYTICS_PROCESSORS.keys()),
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/process', methods=['POST'])
def process_analytics():
    """
    Handle Pub/Sub messages for analytics processing.
    Triggered when MLB raw data processing completes.
    """
    envelope = request.get_json()

    if not envelope:
        return jsonify({"error": "No Pub/Sub message received"}), 400

    if 'message' not in envelope:
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400

    try:
        pubsub_message = envelope['message']

        if 'data' in pubsub_message:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            message = json.loads(data)
        else:
            return jsonify({"error": "No data in Pub/Sub message"}), 400

        raw_table = message.get('output_table') or message.get('source_table')
        game_date = message.get('game_date')
        status = message.get('status', 'success')

        if status == 'failed':
            logger.info(f"Raw processing failed for {raw_table}, skipping analytics")
            return jsonify({"status": "skipped", "reason": "Raw processing failed"}), 200

        if not raw_table:
            return jsonify({"error": "Missing output_table in message"}), 400

        source_table = raw_table.split('.')[-1] if '.' in raw_table else raw_table

        logger.info(f"Processing MLB analytics for {source_table}, date: {game_date}")

        # Schedule-aware early exit (if game_date provided)
        if game_date:
            should_skip, skip_reason = should_skip_date(game_date)
            if should_skip:
                logger.info(f"Skipping analytics for {game_date}: {skip_reason}")
                return jsonify({
                    "status": "skipped",
                    "game_date": game_date,
                    "reason": skip_reason,
                    "schedule_aware": True
                }), 200

        processors_to_run = MLB_ANALYTICS_TRIGGERS.get(source_table, [])

        if not processors_to_run:
            logger.info(f"No MLB analytics processors configured for {source_table}")
            return jsonify({"status": "skipped", "reason": f"No processors for {source_table}"}), 200

        # Build opts
        opts = {
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'start_date': game_date,
            'end_date': game_date,
        }

        # Run processors in parallel
        results = []
        with ThreadPoolExecutor(max_workers=len(processors_to_run)) as executor:
            futures = {executor.submit(run_single_processor, proc, opts): proc for proc in processors_to_run}
            for future in as_completed(futures):
                results.append(future.result())

        success_count = sum(1 for r in results if r['status'] == 'success')

        return jsonify({
            "status": "success" if success_count == len(results) else "partial",
            "source_table": source_table,
            "game_date": game_date,
            "processors_run": len(results),
            "success_count": success_count,
            "results": results
        }), 200 if success_count == len(results) else 207

    except Exception as e:
        logger.error(f"Error processing MLB analytics: {e}", exc_info=True)
        # Send alert for service-level failure
        send_mlb_alert(
            severity='critical',
            title='MLB Analytics Service Error',
            message=str(e),
            context={
                'endpoint': '/process',
                'error_type': type(e).__name__
            }
        )
        return jsonify({"error": str(e)}), 500


@app.route('/process-date', methods=['POST'])
def process_date():
    """
    Process analytics for a specific date (HTTP trigger).

    Request body:
    {
        "game_date": "2025-06-15",
        "processors": ["pitcher_game_summary", "batter_game_summary"],  // optional, defaults to all
        "skip_schedule_check": false  // optional, set true to bypass schedule checks
    }
    """
    try:
        data = request.get_json() or {}
        game_date = data.get('game_date')
        skip_schedule_check = data.get('skip_schedule_check', False)

        if not game_date:
            return jsonify({"error": "game_date is required"}), 400

        # Schedule-aware early exit
        should_skip, skip_reason = should_skip_date(game_date, skip_schedule_check)
        if should_skip:
            logger.info(f"Skipping {game_date}: {skip_reason}")
            return jsonify({
                "status": "skipped",
                "game_date": game_date,
                "reason": skip_reason,
                "schedule_aware": True
            }), 200

        processor_names = data.get('processors', list(MLB_ANALYTICS_PROCESSORS.keys()))

        opts = {
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'start_date': game_date,
            'end_date': game_date,
        }

        results = []
        for name in processor_names:
            if name not in MLB_ANALYTICS_PROCESSORS:
                results.append({"processor": name, "status": "unknown"})
                continue

            processor_class = MLB_ANALYTICS_PROCESSORS[name]
            result = run_single_processor(processor_class, opts)
            results.append(result)

        success_count = sum(1 for r in results if r['status'] == 'success')

        return jsonify({
            "status": "success" if success_count == len(results) else "partial",
            "game_date": game_date,
            "processors_run": len(results),
            "success_count": success_count,
            "results": results
        }), 200 if success_count == len(results) else 207

    except Exception as e:
        logger.error(f"Error in process-date: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/process-date-range', methods=['POST'])
def process_date_range():
    """
    Process analytics for a date range (HTTP trigger for backfills).

    Request body:
    {
        "start_date": "2024-03-28",
        "end_date": "2024-09-28",
        "processors": ["pitcher_game_summary"]  // optional
    }
    """
    try:
        data = request.get_json() or {}
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if not start_date or not end_date:
            return jsonify({"error": "start_date and end_date are required"}), 400

        processor_names = data.get('processors', list(MLB_ANALYTICS_PROCESSORS.keys()))

        opts = {
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'start_date': start_date,
            'end_date': end_date,
        }

        results = []
        for name in processor_names:
            if name not in MLB_ANALYTICS_PROCESSORS:
                results.append({"processor": name, "status": "unknown"})
                continue

            processor_class = MLB_ANALYTICS_PROCESSORS[name]
            result = run_single_processor(processor_class, opts)
            results.append(result)

        success_count = sum(1 for r in results if r['status'] == 'success')

        return jsonify({
            "status": "success" if success_count == len(results) else "partial",
            "start_date": start_date,
            "end_date": end_date,
            "processors_run": len(results),
            "success_count": success_count,
            "results": results
        }), 200 if success_count == len(results) else 207

    except Exception as e:
        logger.error(f"Error in process-date-range: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
