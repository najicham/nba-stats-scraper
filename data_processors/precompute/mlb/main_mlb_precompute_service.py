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
                category='mlb_precompute_failure',
                context=context or {}
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


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
        # Send alert for processor failure
        send_mlb_alert(
            severity='warning',
            title=f'MLB Precompute Processor Failed: {processor_class.__name__}',
            message=str(e),
            context={
                'processor': processor_class.__name__,
                'game_date': opts.get('game_date'),
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

        # Schedule-aware early exit (if game_date provided)
        if game_date:
            should_skip, skip_reason = should_skip_date(game_date)
            if should_skip:
                logger.info(f"Skipping precompute for {game_date}: {skip_reason}")
                return jsonify({
                    "status": "skipped",
                    "game_date": game_date,
                    "reason": skip_reason,
                    "schedule_aware": True
                }), 200

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
        # Send alert for service-level failure
        send_mlb_alert(
            severity='critical',
            title='MLB Precompute Service Error',
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
    Process precompute for a specific date (HTTP trigger).

    Request body:
    {
        "game_date": "2025-06-15",
        "processors": ["pitcher_features", "lineup_k_analysis"],  // optional
        "skip_schedule_check": false  // optional, set true to bypass schedule checks
    }
    """
    try:
        data = request.get_json() or {}
        game_date = data.get('game_date')
        skip_schedule_check = data.get('skip_schedule_check', False)

        # Schedule-aware early exit
        if game_date and not skip_schedule_check:
            should_skip, skip_reason = should_skip_date(game_date)
            if should_skip:
                logger.info(f"Skipping {game_date}: {skip_reason}")
                return jsonify({
                    "status": "skipped",
                    "game_date": game_date,
                    "reason": skip_reason,
                    "schedule_aware": True
                }), 200

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
