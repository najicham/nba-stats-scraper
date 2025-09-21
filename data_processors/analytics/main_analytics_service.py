"""
File: analytics_processors/main_analytics_service.py

Main analytics service for Cloud Run
Handles Pub/Sub messages when raw data processing completes
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime, timezone, date, timedelta
import base64

# Import analytics processors
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseProcessor
from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseProcessor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Analytics processor registry - maps source tables to dependent analytics processors
ANALYTICS_TRIGGERS = {
    'nbac_gamebook_player_stats': [PlayerGameSummaryProcessor],
    'bdl_player_boxscores': [PlayerGameSummaryProcessor, TeamOffenseProcessor],
    'nbac_scoreboard_v2': [TeamOffenseProcessor, TeamDefenseProcessor],
    'bdl_standings': [],  # No analytics dependencies yet
    'nbac_injury_report': [PlayerGameSummaryProcessor],  # Updates player context
    'odds_api_player_points_props': [PlayerGameSummaryProcessor],  # Updates prop context
}

@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "analytics_processors",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/process', methods=['POST'])
def process_analytics():
    """
    Handle Pub/Sub messages for analytics processing.
    Triggered when raw data processing completes.
    Expected message format:
    {
        "source_table": "nbac_gamebook_player_stats",
        "game_date": "2024-01-15",
        "processor_name": "NbacGamebookProcessor",
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
        game_date = message.get('game_date')
        success = message.get('success', True)
        
        if not success:
            logger.info(f"Raw processing failed for {source_table}, skipping analytics")
            return jsonify({"status": "skipped", "reason": "Raw processing failed"}), 200
        
        if not source_table:
            return jsonify({"error": "Missing source_table in message"}), 400
            
        logger.info(f"Processing analytics for {source_table}, date: {game_date}")
        
        # Determine which analytics processors to run
        processors_to_run = ANALYTICS_TRIGGERS.get(source_table, [])
        
        if not processors_to_run:
            logger.info(f"No analytics processors configured for {source_table}")
            return jsonify({"status": "no_processors", "source_table": source_table}), 200
        
        # Process analytics for date range (single day or small range)
        start_date = game_date
        end_date = game_date
        
        results = []
        for processor_class in processors_to_run:
            try:
                logger.info(f"Running {processor_class.__name__} for {game_date}")
                
                processor = processor_class()
                opts = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'triggered_by': source_table
                }
                
                success = processor.run(opts)
                
                if success:
                    stats = processor.get_analytics_stats()
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
                logger.error(f"Analytics processor {processor_class.__name__} failed: {e}")
                results.append({
                    "processor": processor_class.__name__,
                    "status": "exception",
                    "error": str(e)
                })
        
        return jsonify({
            "status": "completed",
            "source_table": source_table,
            "game_date": game_date,
            "results": results
        }), 200
            
    except Exception as e:
        logger.error(f"Error processing analytics message: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/process-date-range', methods=['POST'])
def process_date_range():
    """
    Process analytics for a date range (manual trigger).
    POST body: {"start_date": "2024-01-01", "end_date": "2024-01-07", "processors": ["PlayerGameSummaryProcessor"]}
    """
    try:
        data = request.get_json()
        
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        processor_names = data.get('processors', [])
        
        if not start_date or not end_date:
            return jsonify({"error": "start_date and end_date required"}), 400
        
        # Map processor names to classes
        processor_map = {
            'PlayerGameSummaryProcessor': PlayerGameSummaryProcessor,
            'TeamOffenseProcessor': TeamOffenseProcessor,
            'TeamDefenseProcessor': TeamDefenseProcessor,
        }
        
        if not processor_names:
            # Default: run all processors
            processors_to_run = list(processor_map.values())
        else:
            processors_to_run = [processor_map[name] for name in processor_names if name in processor_map]
        
        results = []
        for processor_class in processors_to_run:
            try:
                logger.info(f"Running {processor_class.__name__} for {start_date} to {end_date}")
                
                processor = processor_class()
                opts = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'triggered_by': 'manual'
                }
                
                success = processor.run(opts)
                stats = processor.get_analytics_stats()
                
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
            "date_range": f"{start_date} to {end_date}",
            "results": results
        }), 200
        
    except Exception as e:
        logger.error(f"Error in manual date range processing: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
