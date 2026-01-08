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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
        return jsonify({"error": str(e)}), 500


@app.route('/process-date', methods=['POST'])
def process_date():
    """
    Process analytics for a specific date (HTTP trigger).

    Request body:
    {
        "game_date": "2025-06-15",
        "processors": ["pitcher_game_summary", "batter_game_summary"]  // optional, defaults to all
    }
    """
    try:
        data = request.get_json() or {}
        game_date = data.get('game_date')

        if not game_date:
            return jsonify({"error": "game_date is required"}), 400

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
