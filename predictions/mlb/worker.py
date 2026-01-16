# predictions/mlb/worker.py
"""
MLB Prediction Worker

Cloud Run service that generates pitcher strikeout predictions.
Can be triggered via HTTP endpoint or Pub/Sub.

Endpoints:
    GET  /health              - Health check
    GET  /                    - Service info
    POST /predict             - Generate prediction for single pitcher
    POST /predict-batch       - Generate predictions for game date
    POST /execute-shadow-mode - Run V1.4 vs V1.6 shadow mode comparison
    POST /pubsub              - Pub/Sub push endpoint
"""

import os
import sys
import json
import base64
import logging
import time
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional

from flask import Flask, request, jsonify

# Import AlertManager for intelligent alerting
try:
    from shared.alerts.alert_manager import get_alert_manager
    ALERTING_ENABLED = True
except ImportError:
    ALERTING_ENABLED = False
    logging.warning("AlertManager not available, alerts disabled")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Environment configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
MODEL_PATH = os.environ.get(
    'MLB_MODEL_PATH',
    'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json'
)
PREDICTIONS_TABLE = os.environ.get(
    'MLB_PREDICTIONS_TABLE',
    'mlb_predictions.pitcher_strikeouts'
)

# Flask app
app = Flask(__name__)

# Initialize AlertManager (with backfill mode detection)
def get_mlb_alert_manager():
    """Get AlertManager instance with MLB-specific configuration."""
    if not ALERTING_ENABLED:
        return None
    backfill_mode = os.environ.get('BACKFILL_MODE', 'false').lower() == 'true'
    return get_alert_manager(backfill_mode=backfill_mode)


def send_mlb_alert(severity: str, title: str, message: str, context: dict = None):
    """Send alert via AlertManager with rate limiting."""
    alert_mgr = get_mlb_alert_manager()
    if alert_mgr:
        try:
            alert_mgr.send_alert(
                severity=severity,
                title=title,
                message=message,
                category='mlb_prediction_failure',
                context=context or {}
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


# Lazy-loaded components
_predictor = None
_bq_client = None
_pubsub_publisher = None


def get_predictor():
    """Lazy-load predictor"""
    global _predictor
    if _predictor is None:
        from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
        logger.info("Initializing PitcherStrikeoutsPredictor...")
        _predictor = PitcherStrikeoutsPredictor(
            model_path=MODEL_PATH,
            project_id=PROJECT_ID
        )
        _predictor.load_model()
        logger.info("Predictor initialized successfully")
    return _predictor


def get_bq_client():
    """Lazy-load BigQuery client"""
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        logger.info("Initializing BigQuery client...")
        _bq_client = bigquery.Client(project=PROJECT_ID)
        logger.info("BigQuery client initialized")
    return _bq_client


def get_pubsub_publisher():
    """Lazy-load Pub/Sub publisher"""
    global _pubsub_publisher
    if _pubsub_publisher is None:
        from google.cloud import pubsub_v1
        logger.info("Initializing Pub/Sub publisher...")
        _pubsub_publisher = pubsub_v1.PublisherClient()
        logger.info("Pub/Sub publisher initialized")
    return _pubsub_publisher


@app.route('/', methods=['GET'])
def index():
    """Service info endpoint"""
    predictor = get_predictor()
    model_info = predictor.model_metadata if predictor.model_metadata else {}

    return jsonify({
        'service': 'MLB Prediction Worker',
        'version': '1.0.0',
        'sport': 'MLB',
        'prediction_type': 'pitcher_strikeouts',
        'model': {
            'id': model_info.get('model_id', 'unknown'),
            'mae': model_info.get('test_mae'),
            'baseline_mae': model_info.get('baseline_mae'),
            'improvement': f"{model_info.get('improvement_pct', 0):.1f}%",
            'features': len(model_info.get('features', []))
        },
        'status': 'healthy'
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Cloud Run"""
    return jsonify({'status': 'healthy'}), 200


@app.route('/predict', methods=['POST'])
def predict_single():
    """
    Generate prediction for a single pitcher

    Request body:
    {
        "pitcher_lookup": "gerrit-cole",
        "game_date": "2025-06-15",
        "strikeouts_line": 6.5,  // optional
        "features": {}  // optional, will load from BigQuery if not provided
    }

    Returns:
        Prediction result
    """
    start_time = time.time()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        pitcher_lookup = data.get('pitcher_lookup')
        game_date_str = data.get('game_date')
        strikeouts_line = data.get('strikeouts_line')
        features = data.get('features')

        if not pitcher_lookup:
            return jsonify({'error': 'pitcher_lookup is required'}), 400

        if not game_date_str:
            return jsonify({'error': 'game_date is required'}), 400

        # Parse date
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        predictor = get_predictor()

        # Load features if not provided
        if not features:
            features = predictor.load_pitcher_features(pitcher_lookup, game_date)
            if not features:
                return jsonify({
                    'error': f'No features found for {pitcher_lookup}',
                    'pitcher_lookup': pitcher_lookup,
                    'game_date': game_date_str
                }), 404

        # Generate prediction
        prediction = predictor.predict(
            pitcher_lookup=pitcher_lookup,
            features=features,
            strikeouts_line=strikeouts_line
        )

        prediction['game_date'] = game_date_str
        prediction['duration_seconds'] = round(time.time() - start_time, 3)

        return jsonify(prediction), 200

    except Exception as e:
        logger.error(f"Prediction error: {e}", exc_info=True)
        # Send alert for prediction failure
        send_mlb_alert(
            severity='warning',
            title='MLB Prediction Failed',
            message=str(e),
            context={
                'endpoint': '/predict',
                'pitcher_lookup': data.get('pitcher_lookup') if 'data' in dir() else None,
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


@app.route('/predict-batch', methods=['POST'])
def predict_batch():
    """
    Generate predictions for all pitchers on a game date

    Request body:
    {
        "game_date": "2025-06-15",
        "pitcher_lookups": ["gerrit-cole", "shohei-ohtani"],  // optional
        "write_to_bigquery": true  // optional, default false
    }

    Returns:
        List of predictions
    """
    start_time = time.time()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        game_date_str = data.get('game_date')
        pitcher_lookups = data.get('pitcher_lookups')
        write_to_bigquery = data.get('write_to_bigquery', False)

        if not game_date_str:
            return jsonify({'error': 'game_date is required'}), 400

        # Parse date
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        predictor = get_predictor()

        # Generate batch predictions
        predictions = predictor.batch_predict(
            game_date=game_date,
            pitcher_lookups=pitcher_lookups
        )

        # Write to BigQuery if requested
        if write_to_bigquery and predictions:
            rows_written = write_predictions_to_bigquery(predictions, game_date)
            logger.info(f"Wrote {rows_written} predictions to BigQuery")

        return jsonify({
            'game_date': game_date_str,
            'predictions_count': len(predictions),
            'predictions': predictions,
            'written_to_bigquery': write_to_bigquery,
            'duration_seconds': round(time.time() - start_time, 3)
        }), 200

    except Exception as e:
        logger.error(f"Batch prediction error: {e}", exc_info=True)
        # Send alert for batch prediction failure (critical - affects all predictions for a date)
        send_mlb_alert(
            severity='critical',
            title='MLB Batch Prediction Failed',
            message=str(e),
            context={
                'endpoint': '/predict-batch',
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


@app.route('/execute-shadow-mode', methods=['POST'])
def execute_shadow_mode():
    """
    Execute shadow mode predictions (V1.4 vs V1.6 comparison)

    Request body:
    {
        "game_date": "2025-06-15",  // optional, default: today
        "dry_run": false  // optional, default: false
    }

    Returns:
        Summary of shadow mode execution
    """
    start_time = time.time()

    try:
        data = request.get_json() or {}

        game_date_str = data.get('game_date')
        dry_run = data.get('dry_run', False)

        # Parse date
        if game_date_str:
            if game_date_str.upper() == 'TODAY':
                game_date = date.today()
            else:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = date.today()

        logger.info(f"Executing shadow mode for {game_date}, dry_run={dry_run}")

        # Import and run shadow mode
        from predictions.mlb.shadow_mode_runner import run_shadow_mode
        result = run_shadow_mode(game_date, dry_run=dry_run)

        result['duration_seconds'] = round(time.time() - start_time, 3)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Shadow mode error: {e}", exc_info=True)
        # Send alert for shadow mode failure
        send_mlb_alert(
            severity='warning',
            title='MLB Shadow Mode Failed',
            message=str(e),
            context={
                'endpoint': '/execute-shadow-mode',
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'status': 'failed',
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


@app.route('/pubsub', methods=['POST'])
def handle_pubsub():
    """
    Handle Pub/Sub push message

    Message format:
    {
        "game_date": "2025-06-15",
        "pitcher_lookup": "gerrit-cole",  // optional, for single pitcher
        "write_to_bigquery": true
    }
    """
    start_time = time.time()

    try:
        envelope = request.get_json()
        if not envelope:
            return ('No Pub/Sub message received', 400)

        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            return ('Invalid Pub/Sub message format', 400)

        # Decode message
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        data = json.loads(message_data)

        logger.info(f"Received Pub/Sub message: {data}")

        game_date_str = data.get('game_date')
        pitcher_lookup = data.get('pitcher_lookup')
        write_to_bigquery = data.get('write_to_bigquery', True)

        if not game_date_str:
            logger.error("game_date is required")
            return ('game_date is required', 400)

        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        predictor = get_predictor()

        if pitcher_lookup:
            # Single pitcher prediction
            features = predictor.load_pitcher_features(pitcher_lookup, game_date)
            if features:
                prediction = predictor.predict(
                    pitcher_lookup=pitcher_lookup,
                    features=features,
                    strikeouts_line=data.get('strikeouts_line')
                )
                predictions = [prediction]
            else:
                logger.warning(f"No features for {pitcher_lookup}")
                predictions = []
        else:
            # Batch prediction
            predictions = predictor.batch_predict(game_date=game_date)

        # Write to BigQuery
        if write_to_bigquery and predictions:
            rows_written = write_predictions_to_bigquery(predictions, game_date)
            logger.info(f"Wrote {rows_written} predictions to BigQuery")

        # Publish completion event
        publish_completion_event(game_date_str, len(predictions))

        logger.info(f"Processed {len(predictions)} predictions in {time.time() - start_time:.2f}s")
        return ('', 204)

    except Exception as e:
        logger.error(f"Pub/Sub handler error: {e}", exc_info=True)
        # Send alert for Pub/Sub handler failure (critical - production trigger)
        send_mlb_alert(
            severity='critical',
            title='MLB Prediction Worker Pub/Sub Error',
            message=str(e),
            context={
                'endpoint': '/pubsub',
                'error_type': type(e).__name__
            }
        )
        return ('Internal Server Error', 500)


def write_predictions_to_bigquery(predictions: List[Dict], game_date: date) -> int:
    """
    Write predictions to BigQuery

    Args:
        predictions: List of prediction dicts
        game_date: Game date

    Returns:
        int: Number of rows written
    """
    if not predictions:
        return 0

    client = get_bq_client()

    # Format rows for BigQuery
    rows = []
    for pred in predictions:
        row = {
            'prediction_id': str(uuid.uuid4()),
            'game_date': game_date.isoformat(),
            'game_id': pred.get('game_id'),
            'pitcher_lookup': pred['pitcher_lookup'],
            'pitcher_name': pred.get('pitcher_name'),
            'team_abbr': pred.get('team_abbr'),
            'opponent_team_abbr': pred.get('opponent_team_abbr'),
            'is_home': pred.get('is_home'),

            # Prediction
            'predicted_strikeouts': pred['predicted_strikeouts'],
            'confidence': pred['confidence'],
            'model_version': pred.get('model_version'),

            # Line info
            'strikeouts_line': pred.get('strikeouts_line'),
            'over_odds': pred.get('over_odds'),
            'under_odds': pred.get('under_odds'),
            'line_minutes_before_game': pred.get('line_minutes_before_game'),  # v3.6

            # Recommendation
            'recommendation': pred['recommendation'],
            'edge': pred.get('edge'),

            # Metadata
            'created_at': datetime.utcnow().isoformat(),
            'processed_at': datetime.utcnow().isoformat()
        }
        rows.append(row)

    # Insert rows
    try:
        table_ref = f"{PROJECT_ID}.{PREDICTIONS_TABLE}"
        errors = client.insert_rows_json(table_ref, rows)

        if errors:
            logger.error(f"BigQuery insert errors: {errors}")
            return 0

        logger.info(f"Inserted {len(rows)} rows to {table_ref}")
        return len(rows)

    except Exception as e:
        logger.error(f"BigQuery write error: {e}")
        return 0


def publish_completion_event(game_date: str, prediction_count: int):
    """
    Publish completion event to Pub/Sub

    Args:
        game_date: Game date string
        prediction_count: Number of predictions generated
    """
    try:
        publisher = get_pubsub_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, 'mlb-phase5-predictions-complete')

        message = {
            'game_date': game_date,
            'predictions_count': prediction_count,
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'mlb-prediction-worker'
        }

        message_bytes = json.dumps(message).encode('utf-8')
        future = publisher.publish(topic_path, data=message_bytes)
        future.result()

        logger.info(f"Published completion event for {game_date}")

    except Exception as e:
        logger.error(f"Failed to publish completion event: {e}")


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
