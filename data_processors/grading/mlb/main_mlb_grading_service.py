"""
MLB Grading Service for Cloud Run

Phase 6: Grade MLB predictions against actual game results.
Runs after games complete to calculate prediction accuracy.

Endpoints:
- /health: Health check
- /process: Process Pub/Sub trigger
- /grade-date: Grade specific date (HTTP trigger)
- /grade-shadow: Grade shadow mode predictions (V1.4 vs V1.6)
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date, timedelta
import base64

from data_processors.grading.mlb.mlb_prediction_grading_processor import MlbPredictionGradingProcessor
from data_processors.grading.mlb.mlb_shadow_grading_processor import MLBShadowGradingProcessor

# Specific exceptions for better error handling
from google.api_core.exceptions import GoogleAPIError

# Import AlertManager for intelligent alerting
try:
    from shared.alerts.alert_manager import get_alert_manager
    ALERTING_ENABLED = True
except ImportError:
    ALERTING_ENABLED = False
    logging.warning("AlertManager not available, alerts disabled")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MLB Alert utilities (consolidated in shared module)
from shared.utils.mlb_alert_utils import (
    get_mlb_alert_manager,
    send_mlb_grading_alert as send_mlb_alert,
)


@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "mlb_grading_service",
        "sport": "mlb",
        "phase": 6,
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/process', methods=['POST'])
def process_grading():
    """
    Handle Pub/Sub messages for grading.
    Triggered after games complete.

    Message format:
    {
        "target_date": "yesterday" | "2025-06-15"
    }
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

        target_date = message.get('target_date', 'yesterday')
        game_date = _resolve_date(target_date)

        logger.info(f"Grading MLB predictions for {game_date}")

        processor = MlbPredictionGradingProcessor()
        success = processor.run({'game_date': game_date})

        if success:
            stats = processor.get_grading_stats()
            return jsonify({
                "status": "success",
                "game_date": game_date,
                "stats": stats
            }), 200
        else:
            return jsonify({
                "status": "error",
                "game_date": game_date
            }), 500

    except (GoogleAPIError, ValueError, json.JSONDecodeError) as e:
        logger.error(f"Error in grading: {e}", exc_info=True)
        # Send alert for grading failure
        send_mlb_alert(
            severity='warning',
            title='MLB Grading Failed',
            message=str(e),
            context={
                'endpoint': '/process',
                'error_type': type(e).__name__
            }
        )
        return jsonify({"error": str(e)}), 500


@app.route('/grade-date', methods=['POST'])
def grade_date():
    """
    Grade predictions for a specific date (HTTP trigger).

    Request body:
    {
        "game_date": "2025-06-15"
    }
    """
    try:
        data = request.get_json() or {}
        game_date = data.get('game_date')

        if not game_date:
            return jsonify({"error": "game_date is required"}), 400

        logger.info(f"Grading MLB predictions for {game_date}")

        processor = MlbPredictionGradingProcessor()
        success = processor.run({'game_date': game_date})

        if success:
            stats = processor.get_grading_stats()
            return jsonify({
                "status": "success",
                "game_date": game_date,
                "stats": stats
            }), 200
        else:
            return jsonify({
                "status": "error",
                "game_date": game_date
            }), 500

    except (GoogleAPIError, ValueError) as e:
        logger.error(f"Error in grade-date: {e}", exc_info=True)
        # Send alert for grading failure
        send_mlb_alert(
            severity='warning',
            title='MLB Grading Failed',
            message=str(e),
            context={
                'endpoint': '/grade-date',
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({"error": str(e)}), 500


@app.route('/grade-shadow', methods=['POST'])
def grade_shadow():
    """
    Grade shadow mode predictions (V1.4 vs V1.6 comparison).

    Request body:
    {
        "dry_run": false  // optional, default: false
    }

    Returns:
        Summary of grading results including V1.4 vs V1.6 comparison
    """
    try:
        data = request.get_json() or {}
        dry_run = data.get('dry_run', False)

        logger.info(f"Grading shadow mode predictions (dry_run={dry_run})")

        processor = MLBShadowGradingProcessor()
        result = processor.grade_pending(dry_run=dry_run)

        return jsonify({
            "status": "success",
            "dry_run": dry_run,
            **result
        }), 200

    except (GoogleAPIError, ValueError) as e:
        logger.error(f"Error in grade-shadow: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _resolve_date(target_date_str: str) -> str:
    """Resolve 'today', 'yesterday', or date string to YYYY-MM-DD."""
    today = datetime.now(timezone.utc).date()

    if target_date_str == "today":
        return today.isoformat()
    elif target_date_str == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    else:
        return target_date_str


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
