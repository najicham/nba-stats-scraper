# File: data_processors/reference/main_reference_service.py

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, Any
from flask import Flask, request, jsonify

from .player_reference.nba_players_registry_processor import (
    NbaPlayersRegistryProcessor,
    update_registry_from_gamebook,
    update_registry_from_rosters,
    get_registry_summary
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def process_pub_sub_message(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process Pub/Sub messages for registry updates.
    
    Supported message types:
    - gamebook_processed: Update registry after gamebook processing
    - roster_scraped: Update registry after roster scraping
    - manual_refresh: Manual registry refresh
    """
    try:
        trigger_type = message_data.get('trigger_type')
        logger.info(f"Processing trigger: {trigger_type}")
        
        if trigger_type == 'gamebook_processed':
            # Scenario 2: Nightly update after gamebook processing
            game_date = message_data.get('game_date')
            season = message_data.get('season')
            
            if not game_date or not season:
                return {
                    'status': 'error',
                    'message': 'Missing game_date or season for gamebook_processed trigger'
                }
            
            logger.info(f"Updating registry for gamebook processing: {game_date}, season {season}")
            result = update_registry_from_gamebook(game_date, season)
            
            return {
                'status': 'success',
                'trigger_type': trigger_type,
                'result': result
            }
        
        elif trigger_type == 'roster_scraped':
            # Scenario 3: Morning update after roster scraping
            season = message_data.get('season')
            teams = message_data.get('teams')  # Optional list of teams
            
            if not season:
                return {
                    'status': 'error', 
                    'message': 'Missing season for roster_scraped trigger'
                }
            
            logger.info(f"Updating registry for roster scraping: season {season}")
            if teams:
                logger.info(f"Teams to update: {teams}")
            
            result = update_registry_from_rosters(season, teams)
            
            return {
                'status': 'success',
                'trigger_type': trigger_type,
                'result': result
            }
        
        elif trigger_type == 'manual_refresh':
            # Manual registry refresh
            season = message_data.get('season')
            team = message_data.get('team')
            
            processor = NbaPlayersRegistryProcessor()
            
            if season:
                logger.info(f"Manual refresh for season {season}")
                result = processor.build_registry_for_season(season, team)
            else:
                logger.info("Manual refresh for all seasons")
                result = processor.build_historical_registry()
            
            return {
                'status': 'success',
                'trigger_type': trigger_type,
                'result': result
            }
        
        else:
            return {
                'status': 'error',
                'message': f'Unknown trigger type: {trigger_type}'
            }
    
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'reference-processor',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/process', methods=['POST'])
def process_message():
    """Main Pub/Sub message processing endpoint."""
    try:
        # Extract message from Pub/Sub format
        envelope = request.get_json()
        
        if not envelope:
            return jsonify({'error': 'No message received'}), 400
        
        if 'message' not in envelope:
            return jsonify({'error': 'Invalid Pub/Sub format'}), 400
        
        # Decode the message
        import base64
        message_data = json.loads(
            base64.b64decode(envelope['message']['data']).decode('utf-8')
        )
        
        # Process the message
        result = process_pub_sub_message(message_data)
        
        # Return appropriate HTTP status
        if result.get('status') == 'success':
            return jsonify(result), 200
        else:
            return jsonify(result), 500
    
    except Exception as e:
        logger.error(f"Error in process endpoint: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/trigger/<trigger_type>', methods=['POST'])
def manual_trigger(trigger_type: str):
    """Manual trigger endpoint for testing."""
    try:
        # Get parameters from request
        params = request.get_json() or {}
        
        # Build message data
        message_data = {
            'trigger_type': trigger_type,
            **params
        }
        
        # Process the message
        result = process_pub_sub_message(message_data)
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in manual trigger: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/stats', methods=['GET'])
def get_stats():
    """Get registry statistics endpoint."""
    try:
        summary = get_registry_summary()
        return jsonify({
            'status': 'success',
            'registry_summary': summary
        })
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
    