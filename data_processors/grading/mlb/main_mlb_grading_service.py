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
from data_processors.grading.mlb.mlb_shadow_grading_processor import MlbShadowModeGradingProcessor as MLBShadowGradingProcessor
from google.cloud import bigquery

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
            # Backfill shadow picks with actuals
            shadow_count = _backfill_shadow_picks(game_date)
            stats['shadow_picks_graded'] = shadow_count
            # Re-export all.json with grading data
            export_stats = _re_export_all_json(game_date)
            stats['export'] = export_stats
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

        # Resolve TODAY/YESTERDAY literals before use
        game_date = _resolve_date(game_date)

        logger.info(f"Grading MLB predictions for {game_date}")

        processor = MlbPredictionGradingProcessor()
        success = processor.run({'game_date': game_date})

        if success:
            stats = processor.get_grading_stats()
            # Backfill shadow picks with actuals
            shadow_count = _backfill_shadow_picks(game_date)
            stats['shadow_picks_graded'] = shadow_count

            # Session 519: Run post-grading analytics (league_macro,
            # model_performance, signal_health). Same pattern as NBA's
            # post_grading_export CF but inline to avoid another CF.
            analytics_stats = _run_post_grading_analytics(game_date)
            stats['analytics'] = analytics_stats

            # Session 520: Re-export all.json with updated grading data
            export_stats = _re_export_all_json(game_date)
            stats['export'] = export_stats

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


def _run_post_grading_analytics(game_date: str) -> dict:
    """Run post-grading analytics: league_macro, model_performance, signal_health.

    Session 519: These tables were schema-only for MLB — never computed.
    Without them, regime_context reads empty tables and there's no model
    performance tracking. Each module is best-effort (errors logged, not raised).
    """
    from datetime import date as date_type
    from google.cloud import bigquery as bq

    stats = {}
    client = bq.Client(project='nba-props-platform')
    target = date_type.fromisoformat(game_date)

    # 1. League macro
    try:
        from ml.analysis.mlb_league_macro import compute_for_date, write_row
        row = compute_for_date(client, target)
        if row:
            written = write_row(client, row)
            stats['league_macro'] = f'{written} row'
            logger.info(f"Post-grading: league_macro wrote {written} row for {game_date}")
        else:
            stats['league_macro'] = 'no data'
    except Exception as e:
        logger.error(f"Post-grading league_macro failed: {e}", exc_info=True)
        stats['league_macro'] = f'error: {e}'

    # 2. Model performance
    try:
        from ml.analysis.mlb_model_performance import compute_for_date as mp_compute, write_rows
        rows = mp_compute(client, target)
        if rows:
            written = write_rows(client, rows)
            stats['model_performance'] = f'{written} rows'
            logger.info(f"Post-grading: model_performance wrote {written} rows for {game_date}")
        else:
            stats['model_performance'] = 'no data'
    except Exception as e:
        logger.error(f"Post-grading model_performance failed: {e}", exc_info=True)
        stats['model_performance'] = f'error: {e}'

    # 3. Signal health
    try:
        from ml.signals.mlb.signal_health import compute_signal_health, write_health_rows
        rows = compute_signal_health(client, game_date)
        if rows:
            written = write_health_rows(client, rows)
            stats['signal_health'] = f'{written} rows'
            logger.info(f"Post-grading: signal_health wrote {written} rows for {game_date}")
        else:
            stats['signal_health'] = 'no data'
    except Exception as e:
        logger.error(f"Post-grading signal_health failed: {e}", exc_info=True)
        stats['signal_health'] = f'error: {e}'

    return stats


def _re_export_all_json(game_date: str) -> dict:
    """Re-export mlb/best-bets/all.json with updated grading data.

    Session 520: After grading, all.json needs refreshing so the frontend
    shows updated win/loss records and pick results.
    """
    try:
        from data_processors.publishing.mlb.mlb_best_bets_exporter import MlbBestBetsExporter
        exporter = MlbBestBetsExporter()
        path = exporter.export_all(today=game_date)
        logger.info(f"Post-grading: re-exported all.json to {path}")
        return {'status': 'ok', 'path': path}
    except Exception as e:
        logger.error(f"Post-grading all.json export failed: {e}", exc_info=True)
        return {'status': f'error: {e}'}


def _backfill_shadow_picks(game_date: str):
    """Backfill actuals into blacklist_shadow_picks after grading completes.

    Joins shadow picks with prediction_accuracy to fill in actual_strikeouts,
    prediction_correct, and is_voided for counterfactual analysis.
    """
    try:
        client = bigquery.Client(project="nba-props-platform")
        query = f"""
        UPDATE `mlb_predictions.blacklist_shadow_picks` sp
        SET
            sp.actual_strikeouts = pa.actual_strikeouts,
            sp.prediction_correct = CASE
                WHEN pa.actual_strikeouts IS NULL THEN NULL
                WHEN sp.recommendation = 'OVER' AND pa.actual_strikeouts > sp.line_value THEN TRUE
                WHEN sp.recommendation = 'UNDER' AND pa.actual_strikeouts < sp.line_value THEN TRUE
                ELSE FALSE
            END,
            sp.is_voided = pa.is_voided,
            sp.graded_at = CURRENT_TIMESTAMP()
        FROM `mlb_predictions.prediction_accuracy` pa
        WHERE sp.game_date = '{game_date}'
          AND pa.game_date = '{game_date}'
          AND sp.pitcher_lookup = pa.pitcher_lookup
          AND sp.system_id = pa.system_id
          AND sp.graded_at IS NULL
        """
        result = client.query(query).result()
        rows_affected = result.num_dml_affected_rows or 0
        if rows_affected > 0:
            logger.info(f"Backfilled {rows_affected} shadow picks for {game_date}")
        return rows_affected
    except Exception as e:
        logger.warning(f"Shadow picks backfill failed for {game_date}: {e}")
        return 0


def _resolve_date(target_date_str: str) -> str:
    """Resolve 'today', 'yesterday', or date string to YYYY-MM-DD."""
    today = datetime.now(timezone.utc).date()

    if target_date_str.lower() == "today":
        return today.isoformat()
    elif target_date_str.lower() == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    else:
        return target_date_str


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
