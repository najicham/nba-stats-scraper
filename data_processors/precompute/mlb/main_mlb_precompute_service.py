"""
MLB Precompute Service for Cloud Run

Phase 4 precompute processors for MLB data.
Handles Pub/Sub messages when MLB analytics processing completes.

Endpoints:
- /health: Health check
- /process: Process Pub/Sub trigger
- /process-date: Process specific date (HTTP trigger)
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import MLB precompute processors
from data_processors.precompute.mlb import (
    MlbPitcherFeaturesProcessor,
    MlbLineupKAnalysisProcessor,
)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# MLB Precompute processor registry
MLB_PRECOMPUTE_PROCESSORS = {
    'pitcher_features': MlbPitcherFeaturesProcessor,
    'lineup_k_analysis': MlbLineupKAnalysisProcessor,
}

# Trigger mapping: which analytics tables trigger which precompute processors
MLB_PRECOMPUTE_TRIGGERS = {
    'pitcher_game_summary': [MlbPitcherFeaturesProcessor],
    'batter_game_summary': [MlbLineupKAnalysisProcessor],
}


def run_single_processor(processor_class, opts):
    """Run a single precompute processor."""
    try:
        analysis_date = opts.get('analysis_date') or opts.get('game_date')
        logger.info(f"Running {processor_class.__name__} for {analysis_date}")
        processor = processor_class()

        # MLB processors use process_date() directly instead of run()
        from datetime import datetime
        if isinstance(analysis_date, str):
            target_date = datetime.strptime(analysis_date, '%Y-%m-%d').date()
        else:
            target_date = analysis_date

        result = processor.process_date(target_date)

        if result:
            stats = result if isinstance(result, dict) else {}
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
        logger.error(f"Precompute processor {processor_class.__name__} failed: {e}", exc_info=True)
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
        "service": "mlb_precompute_processors",
        "sport": "mlb",
        "processors": list(MLB_PRECOMPUTE_PROCESSORS.keys()),
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/process', methods=['POST'])
def process_precompute():
    """
    Handle Pub/Sub messages for precompute processing.
    Triggered when MLB analytics processing completes.
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

        analytics_table = message.get('output_table') or message.get('source_table')
        game_date = message.get('game_date')
        status = message.get('status', 'success')

        if status == 'failed':
            logger.info(f"Analytics processing failed for {analytics_table}, skipping precompute")
            return jsonify({"status": "skipped", "reason": "Analytics processing failed"}), 200

        if not analytics_table:
            return jsonify({"error": "Missing output_table in message"}), 400

        source_table = analytics_table.split('.')[-1] if '.' in analytics_table else analytics_table

        logger.info(f"Processing MLB precompute for {source_table}, date: {game_date}")

        processors_to_run = MLB_PRECOMPUTE_TRIGGERS.get(source_table, [])

        if not processors_to_run:
            logger.info(f"No MLB precompute processors configured for {source_table}")
            return jsonify({"status": "skipped", "reason": f"No processors for {source_table}"}), 200

        # Build opts
        opts = {
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'analysis_date': game_date,
            'game_date': game_date,
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
        logger.error(f"Error processing MLB precompute: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/process-date', methods=['POST'])
def process_date():
    """
    Process precompute for a specific date (HTTP trigger).

    Request body:
    {
        "game_date": "2025-06-15",
        "processors": ["pitcher_features", "lineup_k_analysis"]  // optional
    }
    """
    try:
        data = request.get_json() or {}
        game_date = data.get('game_date')

        if not game_date:
            return jsonify({"error": "game_date is required"}), 400

        processor_names = data.get('processors', list(MLB_PRECOMPUTE_PROCESSORS.keys()))

        opts = {
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'analysis_date': game_date,
            'game_date': game_date,
        }

        results = []
        for name in processor_names:
            if name not in MLB_PRECOMPUTE_PROCESSORS:
                results.append({"processor": name, "status": "unknown"})
                continue

            processor_class = MLB_PRECOMPUTE_PROCESSORS[name]
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
