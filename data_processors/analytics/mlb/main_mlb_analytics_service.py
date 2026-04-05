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
import uuid
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date, timedelta
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import MLB analytics processors
from data_processors.analytics.mlb import (
    MlbPitcherGameSummaryProcessor,
    MlbBatterGameSummaryProcessor,
)

# Import Pub/Sub publisher for Phase 3 completion notifications
try:
    from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher
    PUBLISHER_AVAILABLE = True
except ImportError:
    PUBLISHER_AVAILABLE = False
    logging.warning("UnifiedPubSubPublisher not available, completion notifications disabled")

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

# Reverse mapping: class name -> processor registry key
# Used for publishing Phase 3 completion messages that the orchestrator can match.
_CLASS_TO_PROCESSOR_NAME = {
    cls.__name__: name
    for name, cls in MLB_ANALYTICS_PROCESSORS.items()
}

# Trigger mapping: which raw tables trigger which analytics processors
# Keys MUST match the table_name published by Phase 2 raw processors:
#   mlbapi_pitcher_stats (MlbApiPitcherStatsProcessor)
#   mlbapi_batter_stats  (MlbApiBatterStatsProcessor)
#   mlb_game_lineups     (MlbLineupsProcessor)
MLB_ANALYTICS_TRIGGERS = {
    'mlbapi_pitcher_stats': [MlbPitcherGameSummaryProcessor],
    'mlbapi_batter_stats': [MlbBatterGameSummaryProcessor],
    'mlb_game_lineups': [MlbPitcherGameSummaryProcessor, MlbBatterGameSummaryProcessor],
}


PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')

# Phase 3 completion topic — must be sport-prefixed for MLB
MLB_PHASE3_COMPLETE_TOPIC = 'mlb-phase3-analytics-complete'


def publish_phase3_completion(game_date: str, processor_name: str, record_count: int = 0,
                              status: str = 'success', correlation_id: str = None):
    """
    Publish Phase 3 completion message to mlb-phase3-analytics-complete.

    This triggers the Phase 3 -> Phase 4 orchestrator (mlb_phase3_to_phase4 CF),
    which tracks processor completion and fires Phase 4 when all expected
    processors (pitcher_game_summary, batter_game_summary) have reported.

    Args:
        game_date: The date that was processed (YYYY-MM-DD)
        processor_name: Name of the completed processor
        record_count: Number of records processed
        status: Processing status ('success' or 'error')
        correlation_id: Optional correlation ID for tracing
    """
    if not PUBLISHER_AVAILABLE:
        logger.warning("Publisher not available, skipping Phase 3 completion notification")
        return

    try:
        publisher = UnifiedPubSubPublisher(project_id=PROJECT_ID)
        execution_id = str(uuid.uuid4())

        message_id = publisher.publish_completion(
            topic=MLB_PHASE3_COMPLETE_TOPIC,
            processor_name=processor_name,
            phase='phase_3_analytics',
            execution_id=execution_id,
            correlation_id=correlation_id or execution_id,
            game_date=game_date,
            output_table=processor_name,
            output_dataset='mlb_analytics',
            status=status,
            record_count=record_count,
            records_failed=0,
            duration_seconds=0,
            metadata={'sport': 'mlb'}
        )

        if message_id:
            logger.info(
                f"Published Phase 3 completion: {processor_name} "
                f"for {game_date} (message_id={message_id})"
            )
        else:
            logger.warning(f"Publish returned None for {processor_name} (non-fatal)")

    except Exception as e:
        logger.error(f"Failed to publish Phase 3 completion for {processor_name}: {e}", exc_info=True)
        # Non-fatal — don't crash the request


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

        # Publish Phase 3 completion for each successful processor.
        # The Phase 3->4 orchestrator (mlb_phase3_to_phase4 CF) tracks
        # per-processor completions and triggers Phase 4 when all are done.
        correlation_id = message.get('correlation_id')
        if game_date:
            for r in results:
                if r['status'] == 'success':
                    # Map class name back to registry key for orchestrator matching
                    class_name = r.get('processor', '')
                    proc_key = _CLASS_TO_PROCESSOR_NAME.get(class_name, class_name)
                    record_count = r.get('stats', {}).get('rows_processed', 0) if isinstance(r.get('stats'), dict) else 0
                    publish_phase3_completion(
                        game_date=game_date,
                        processor_name=proc_key,
                        record_count=record_count,
                        status='success',
                        correlation_id=correlation_id,
                    )

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

        # Publish Phase 3 completion for each successful processor
        skip_downstream = data.get('skip_downstream_trigger', False)
        if game_date and not skip_downstream:
            for r in results:
                if r['status'] == 'success':
                    class_name = r.get('processor', '')
                    proc_key = _CLASS_TO_PROCESSOR_NAME.get(class_name, class_name)
                    record_count = r.get('stats', {}).get('rows_processed', 0) if isinstance(r.get('stats'), dict) else 0
                    publish_phase3_completion(
                        game_date=game_date,
                        processor_name=proc_key,
                        record_count=record_count,
                        status='success',
                    )

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
