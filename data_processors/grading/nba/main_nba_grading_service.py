"""
NBA Grading Service for Cloud Run

Phase 5B: Grade NBA predictions against actual game results.
Runs after games complete to calculate prediction accuracy.

Endpoints:
- /health: Health check
- /process: Process Pub/Sub trigger (for automation)
- /grade-date: Grade specific date (HTTP trigger)

Usage:
    # Via Pub/Sub (automated daily)
    Message: {"target_date": "yesterday"}

    # Via HTTP (manual/testing)
    POST /grade-date?date=2026-01-30
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date, timedelta
import base64

from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor

# Specific exceptions for better error handling
from google.api_core.exceptions import GoogleAPIError

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "nba_grading_service",
        "sport": "nba",
        "phase": "5B",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200


@app.route('/process', methods=['POST'])
def process_grading():
    """
    Handle Pub/Sub messages for grading.
    Triggered daily after games complete.

    Message format:
    {
        "target_date": "yesterday" | "2026-01-30"
    }
    """
    envelope = request.get_json()

    if not envelope:
        return jsonify({"error": "No Pub/Sub message received"}), 400

    if 'message' not in envelope:
        return jsonify({"error": "Invalid Pub/Sub message format"}), 400

    try:
        pubsub_message = envelope['message']

        # Decode message data
        if 'data' in pubsub_message:
            message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            data = json.loads(message_data)
        else:
            data = {}

        # Determine target date
        target_date_str = data.get('target_date', 'yesterday')

        if target_date_str == 'yesterday':
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        else:
            target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

        logger.info(f"Grading predictions for {target_date}")

        # Grade predictions for the target date
        processor = PredictionAccuracyProcessor()
        result = processor.process_game_date(target_date.strftime('%Y-%m-%d'))

        logger.info(f"Grading complete for {target_date}: {result}")

        return jsonify({
            "status": "success",
            "game_date": target_date.strftime('%Y-%m-%d'),
            "result": result
        }), 200

    except Exception as e:
        logger.error(f"Error grading predictions: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


@app.route('/grade-date', methods=['POST', 'GET'])
def grade_specific_date():
    """
    Grade predictions for a specific date.
    HTTP endpoint for manual triggering.

    Query params:
    - date: Target date (YYYY-MM-DD), defaults to yesterday

    Example:
    POST /grade-date?date=2026-01-30
    """
    try:
        # Get date from query params or default to yesterday
        date_str = request.args.get('date')

        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        logger.info(f"Manual grading request for {target_date}")

        # Grade predictions
        processor = PredictionAccuracyProcessor()
        result = processor.process_game_date(target_date.strftime('%Y-%m-%d'))

        logger.info(f"Manual grading complete for {target_date}: {result}")

        return jsonify({
            "status": "success",
            "game_date": target_date.strftime('%Y-%m-%d'),
            "result": result,
            "trigger": "manual"
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "error": f"Invalid date format: {e}"
        }), 400
    except Exception as e:
        logger.error(f"Error in manual grading: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
