"""
Phase 4: Precompute Service
Orchestrates precomputation of shared aggregations for Phase 5 predictions
Handles Pub/Sub messages when Phase 3 analytics processing completes
"""
from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta
import logging
import json
import base64
import os
import sys

# Add project root to path for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Initialize Sentry first (before other imports that might error)
from shared.utils.sentry_config import configure_sentry
configure_sentry()

# Startup verification - MUST be early to detect wrong code deployment
try:
    from shared.utils.startup_verification import verify_startup
    verify_startup(
        expected_module="precompute-processor",
        service_name="nba-phase4-precompute-processors"
    )
except ImportError:
    # Shared module not available (local dev without full setup)
    logging.warning("startup_verification not available - running without verification")

from shared.endpoints.health import create_health_blueprint, HealthChecker
from shared.config.gcp_config import get_project_id

# Import precompute processors
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Health check endpoints (Phase 1 - Task 1.1: Add Health Endpoints)
# Note: HealthChecker simplified in Week 1 to only require service_name
app.register_blueprint(create_health_blueprint('precompute-processor'))
logger.info("Health check endpoints registered: /health, /ready, /health/deep")

# Precompute processor registry - maps analytics tables to dependent precompute processors
PRECOMPUTE_TRIGGERS = {
    'player_game_summary': [PlayerDailyCacheProcessor],
    'team_defense_game_summary': [TeamDefenseZoneAnalysisProcessor],
    'team_offense_game_summary': [PlayerShotZoneAnalysisProcessor],
    'upcoming_player_game_context': [PlayerDailyCacheProcessor],
    'upcoming_team_game_context': [],  # No immediate dependencies
}

# CASCADE processors that check multiple upstream dependencies
CASCADE_PROCESSORS = {
    'player_composite_factors': PlayerCompositeFactorsProcessor,  # Depends on: team_defense_zone_analysis, player_shot_zone_analysis, player_daily_cache, upcoming_player_game_context
    'ml_feature_store': MLFeatureStoreProcessor,  # Depends on all Phase 4 processors
}

# Health check endpoint removed - now provided by shared health blueprint (see initialization above)
# The blueprint provides: /health (liveness), /ready (readiness), /health/deep (deep checks)

@app.route('/', methods=['POST'])
def root_process():
    """
    Root endpoint for Eventarc/Pub/Sub push subscriptions.
    Forwards to the /process handler for backward compatibility.
    """
    return process()

@app.route('/process', methods=['POST'])
def process():
    """
    Handle Pub/Sub messages for precompute processing.
    Triggered when Phase 3 analytics processing completes.
    Expected message format:
    {
        "source_table": "team_defense_game_summary",
        "analysis_date": "2024-11-22",
        "processor_name": "TeamDefenseGameSummaryProcessor",
        "success": true
    }
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
        source_table = message.get('source_table')
        analysis_date = message.get('analysis_date') or message.get('game_date')
        success = message.get('success', True)

        # Extract orchestration metadata for lineage tracking
        trigger_source = message.get('trigger_source', 'pubsub')
        correlation_id = message.get('correlation_id')
        triggered_by = message.get('triggered_by')
        trigger_message_id = pubsub_message.get('messageId')

        if not success:
            logger.info(f"Phase 3 processing failed for {source_table}, skipping precompute")
            return jsonify({"status": "skipped", "reason": "Phase 3 processing failed"}), 200

        if not source_table:
            return jsonify({"error": "Missing source_table in message"}), 400

        logger.info(f"Processing precompute for {source_table}, date: {analysis_date}")

        # Determine which precompute processors to run
        processors_to_run = PRECOMPUTE_TRIGGERS.get(source_table, [])

        if not processors_to_run:
            logger.info(f"No precompute processors configured for {source_table}")
            return jsonify({"status": "no_processors", "source_table": source_table}), 200

        # Convert analysis_date string to datetime object
        if isinstance(analysis_date, str):
            analysis_date_obj = datetime.strptime(analysis_date, '%Y-%m-%d').date()
        else:
            analysis_date_obj = analysis_date

        # Run processors
        results = []
        for processor_class in processors_to_run:
            try:
                logger.info(f"Running {processor_class.__name__} for {analysis_date}")

                processor = processor_class()
                opts = {
                    'analysis_date': analysis_date_obj,
                    'project_id': get_project_id(),
                    'trigger_source': trigger_source,
                    'correlation_id': correlation_id,
                    'triggered_by': triggered_by or source_table,
                    'trigger_message_id': trigger_message_id,
                }

                success = processor.run(opts)

                if success:
                    stats = getattr(processor, 'get_analytics_stats', lambda: {})()
                    logger.info(f"Successfully ran {processor_class.__name__}: {stats}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "success",
                        "stats": stats
                    })
                else:
                    logger.error(f"Failed to run {processor_class.__name__}")
                    results.append({
                        "processor": processor_class.__name__,
                        "status": "error"
                    })

            except Exception as e:
                logger.error(f"Precompute processor {processor_class.__name__} failed: {e}")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "exception",
                    "error": str(e)
                })

        # R-003 FIX: Check for failures and return appropriate status code
        # Previously always returned 200, even when processors failed
        failures = [r for r in results if r.get('status') in ('error', 'exception')]
        successes = [r for r in results if r.get('status') == 'success']

        if not successes and failures:
            # All processors failed - return 500 to trigger Pub/Sub retry
            logger.error(
                f"❌ ALL {len(failures)} precompute processors failed for {analysis_date} "
                f"(source={source_table}) - returning 500 to trigger retry"
            )
            return jsonify({
                "status": "failed",
                "source_table": source_table,
                "analysis_date": analysis_date,
                "failures": len(failures),
                "results": results
            }), 500

        if failures:
            # Partial failure - log warning but return 200 to ACK
            # (retrying won't help if some processors succeeded)
            logger.warning(
                f"⚠️ PARTIAL FAILURE: {len(failures)}/{len(results)} precompute processors failed "
                f"for {analysis_date} (source={source_table})"
            )
            return jsonify({
                "status": "partial_failure",
                "source_table": source_table,
                "analysis_date": analysis_date,
                "successes": len(successes),
                "failures": len(failures),
                "results": results
            }), 200  # ACK to prevent infinite retries, but status indicates partial

        # All succeeded
        return jsonify({
            "status": "completed",
            "source_table": source_table,
            "analysis_date": analysis_date,
            "results": results
        }), 200

    except Exception as e:
        logger.error(f"Error processing precompute message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/process-date', methods=['POST'])
def process_date():
    """
    Process precompute for a specific date (manual trigger).
    POST body: {"analysis_date": "2024-11-22", "processors": ["PlayerCompositeFactorsProcessor"]}
    Special: analysis_date="AUTO" uses yesterday's date (for late-night scheduler jobs)
    """
    try:
        data = request.get_json()

        analysis_date = data.get('analysis_date')
        processor_names = data.get('processors', [])
        backfill_mode = data.get('backfill_mode', False)
        strict_mode = data.get('strict_mode', True)  # Set False to skip defensive checks
        skip_dependency_check = data.get('skip_dependency_check', False)  # Set True for same-day
        dataset_prefix = data.get('dataset_prefix', '')

        if not analysis_date:
            return jsonify({"error": "analysis_date required"}), 400

        # Handle special date values
        if analysis_date == "AUTO":
            # AUTO = yesterday (for overnight post-game processing)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            analysis_date = yesterday.strftime('%Y-%m-%d')
            logger.info(f"AUTO date resolved to: {analysis_date}")
        elif analysis_date == "TODAY":
            # TODAY = today in ET timezone (for same-day pre-game predictions)
            from zoneinfo import ZoneInfo
            today_et = datetime.now(ZoneInfo('America/New_York')).date()
            analysis_date = today_et.strftime('%Y-%m-%d')
            logger.info(f"TODAY date resolved to: {analysis_date}")
        elif analysis_date == "TOMORROW":
            # TOMORROW = tomorrow in ET timezone (for next-day predictions)
            from zoneinfo import ZoneInfo
            tomorrow_et = datetime.now(ZoneInfo('America/New_York')).date() + timedelta(days=1)
            analysis_date = tomorrow_et.strftime('%Y-%m-%d')
            logger.info(f"TOMORROW date resolved to: {analysis_date}")

        # Map processor names to classes
        processor_map = {
            'TeamDefenseZoneAnalysisProcessor': TeamDefenseZoneAnalysisProcessor,
            'PlayerShotZoneAnalysisProcessor': PlayerShotZoneAnalysisProcessor,
            'PlayerDailyCacheProcessor': PlayerDailyCacheProcessor,
            'PlayerCompositeFactorsProcessor': PlayerCompositeFactorsProcessor,
            'MLFeatureStoreProcessor': MLFeatureStoreProcessor,
        }

        if not processor_names:
            # Default: run all processors
            processors_to_run = list(processor_map.values())
        else:
            processors_to_run = [processor_map[name] for name in processor_names if name in processor_map]

        results = []
        for processor_class in processors_to_run:
            try:
                logger.info(f"Running {processor_class.__name__} for {analysis_date}")

                processor = processor_class()
                # Extract trigger_source from request if provided (e.g., from orchestrator)
                trigger_source = data.get('trigger_source', 'manual')
                correlation_id = data.get('correlation_id')
                opts = {
                    'analysis_date': analysis_date,
                    'project_id': get_project_id(),
                    'trigger_source': trigger_source,
                    'correlation_id': correlation_id,
                    'triggered_by': data.get('triggered_by', 'manual'),
                    'backfill_mode': backfill_mode,
                    'strict_mode': strict_mode,
                    'skip_dependency_check': skip_dependency_check,
                    'dataset_prefix': dataset_prefix
                }

                success = processor.run(opts)
                stats = getattr(processor, 'get_analytics_stats', lambda: {})()

                results.append({
                    "processor": processor_class.__name__,
                    "status": "success" if success else "error",
                    "stats": stats
                })

            except Exception as e:
                logger.error(f"Manual processor {processor_class.__name__} failed: {e}")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "exception",
                    "error": str(e)
                })

        return jsonify({
            "status": "completed",
            "analysis_date": analysis_date,
            "results": results
        }), 200

    except Exception as e:
        logger.error(f"Error in manual date processing: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
