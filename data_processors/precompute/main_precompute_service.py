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

# Import precompute processors
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'precompute',
        'version': '1.0.0',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })

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
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'triggered_by': source_table
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
                opts = {
                    'analysis_date': analysis_date,
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'triggered_by': 'manual',
                    'backfill_mode': backfill_mode,
                    'strict_mode': strict_mode,
                    'skip_dependency_check': skip_dependency_check
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
