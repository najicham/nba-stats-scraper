# File: data_processors/reference/main_reference_service.py

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from flask import Flask, request, jsonify

# Import notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# FIXED: Import from the new split processors
from .player_reference.gamebook_registry_processor import GamebookRegistryProcessor
from .player_reference.roster_registry_processor import RosterRegistryProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def update_registry_from_gamebook(game_date: str, season: str) -> Dict[str, Any]:
    """
    Update registry after gamebook processing.
    
    Args:
        game_date: Date of games processed (YYYY-MM-DD)
        season: NBA season (e.g., 2024-25)
    
    Returns:
        Processing result dictionary
    """
    try:
        logger.info(f"Updating gamebook registry for {game_date}, season {season}")
        
        # Use gamebook processor with name change detection enabled for daily updates
        processor = GamebookRegistryProcessor(
            test_mode=False,
            strategy="merge",  # Safe MERGE strategy for daily updates
            enable_name_change_detection=True  # Enable for production daily runs
        )
        
        # Build registry for the specific season
        result = processor.build_registry_for_season(season)
        
        logger.info(f"Gamebook registry update complete: {result['records_processed']} records processed")
        
        return {
            'scenario': 'gamebook_processed_update',
            'game_date': game_date,
            'season': season,
            'success': True,
            'records_processed': result['records_processed'],
            'players_processed': result['players_processed'],
            'teams_processed': result['teams_processed'],
            'errors': result.get('errors', []),
            'processing_run_id': result['processing_run_id']
        }
        
    except Exception as e:
        error_msg = f"Error updating registry from gamebook: {str(e)}"
        logger.error(error_msg)
        
        # Note: registry_processor_base already sent detailed error notification
        # This is just for orchestration context
        try:
            notify_error(
                title="Registry Service: Gamebook Update Failed",
                message=f"Failed to update registry from gamebook data: {str(e)}",
                details={
                    'service': 'reference-processor-orchestration',
                    'scenario': 'gamebook_processed_update',
                    'game_date': game_date,
                    'season': season,
                    'error_type': type(e).__name__,
                    'error': str(e)
                },
                processor_name="Reference Service Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'scenario': 'gamebook_processed_update',
            'game_date': game_date,
            'season': season,
            'success': False,
            'error': error_msg
        }


def update_registry_from_rosters(season: str, teams: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Update registry after roster scraping.
    
    Args:
        season: NBA season (e.g., 2024-25)
        teams: Optional list of specific teams to update
    
    Returns:
        Processing result dictionary
    """
    try:
        logger.info(f"Updating roster registry for season {season}")
        if teams:
            logger.info(f"Specific teams: {teams}")
        
        # Use roster processor with name change detection enabled for daily updates
        processor = RosterRegistryProcessor(
            test_mode=False,
            strategy="merge",  # Safe MERGE strategy for daily updates
            enable_name_change_detection=True  # Enable for production daily runs
        )
        
        if teams:
            # Process specific teams
            results = []
            total_records = 0
            total_players = 0
            all_errors = []
            
            for team in teams:
                logger.info(f"Processing roster data for team: {team}")
                result = processor.build_registry_for_season(season, team)
                results.append({
                    'team': team,
                    'records_processed': result['records_processed'],
                    'players_processed': result['players_processed'],
                    'errors': result.get('errors', [])
                })
                total_records += result['records_processed']
                total_players += result['players_processed']
                all_errors.extend(result.get('errors', []))
            
            return {
                'scenario': 'roster_scraped_update',
                'season': season,
                'teams': teams,
                'success': True,
                'total_records_processed': total_records,
                'total_players_processed': total_players,
                'team_results': results,
                'errors': all_errors
            }
        else:
            # Process entire season
            result = processor.build_registry_for_season(season)
            
            logger.info(f"Roster registry update complete: {result['records_processed']} records processed")
            
            return {
                'scenario': 'roster_scraped_update',
                'season': season,
                'teams': None,
                'success': True,
                'records_processed': result['records_processed'],
                'players_processed': result['players_processed'],
                'teams_processed': result['teams_processed'],
                'errors': result.get('errors', []),
                'processing_run_id': result['processing_run_id']
            }
        
    except Exception as e:
        error_msg = f"Error updating registry from rosters: {str(e)}"
        logger.error(error_msg)
        
        # Note: registry_processor_base already sent detailed error notification
        # This is just for orchestration context
        try:
            notify_error(
                title="Registry Service: Roster Update Failed",
                message=f"Failed to update registry from roster data: {str(e)}",
                details={
                    'service': 'reference-processor-orchestration',
                    'scenario': 'roster_scraped_update',
                    'season': season,
                    'teams': teams,
                    'error_type': type(e).__name__,
                    'error': str(e)
                },
                processor_name="Reference Service Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'scenario': 'roster_scraped_update',
            'season': season,
            'teams': teams,
            'success': False,
            'error': error_msg
        }


def get_registry_summary() -> Dict[str, Any]:
    """
    Get registry statistics from both gamebook and roster sources.
    
    Returns:
        Registry summary dictionary
    """
    try:
        # Get gamebook registry summary
        gamebook_processor = GamebookRegistryProcessor()
        gamebook_summary = gamebook_processor.get_registry_summary()
        
        # Get roster registry summary
        roster_processor = RosterRegistryProcessor()
        roster_summary = roster_processor.get_registry_summary()
        
        return {
            'summary_type': 'combined_registry_summary',
            'gamebook_registry': gamebook_summary,
            'roster_registry': roster_summary,
            'generated_at': datetime.now().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Error getting registry summary: {str(e)}"
        logger.error(error_msg)
        
        try:
            notify_error(
                title="Registry Service: Summary Query Failed",
                message="Unable to retrieve registry statistics",
                details={
                    'service': 'reference-processor-orchestration',
                    'operation': 'get_registry_summary',
                    'error_type': type(e).__name__,
                    'error': str(e)
                },
                processor_name="Reference Service Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'summary_type': 'combined_registry_summary',
            'error': error_msg,
            'generated_at': datetime.now().isoformat()
        }


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
                error_msg = 'Missing game_date or season for gamebook_processed trigger'
                try:
                    notify_error(
                        title="Registry Service: Missing Parameters",
                        message=error_msg,
                        details={
                            'service': 'reference-processor-orchestration',
                            'trigger_type': trigger_type,
                            'game_date': game_date,
                            'season': season,
                            'required_fields': ['game_date', 'season']
                        },
                        processor_name="Reference Service Orchestration"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {
                    'status': 'error',
                    'message': error_msg
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
                error_msg = 'Missing season for roster_scraped trigger'
                try:
                    notify_error(
                        title="Registry Service: Missing Parameters",
                        message=error_msg,
                        details={
                            'service': 'reference-processor-orchestration',
                            'trigger_type': trigger_type,
                            'season': season,
                            'required_fields': ['season']
                        },
                        processor_name="Reference Service Orchestration"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {
                    'status': 'error', 
                    'message': error_msg
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
            # Manual registry refresh - FIXED to work with split architecture
            season = message_data.get('season')
            team = message_data.get('team')
            processor_type = message_data.get('processor_type', 'gamebook')  # Default to gamebook
            
            if processor_type == 'gamebook':
                processor = GamebookRegistryProcessor(enable_name_change_detection=True)
                
                if season:
                    logger.info(f"Manual gamebook refresh for season {season}")
                    result = processor.build_registry_for_season(season, team)
                else:
                    logger.info("Manual gamebook refresh for all seasons")
                    result = processor.build_historical_registry()
                    
            elif processor_type == 'roster':
                processor = RosterRegistryProcessor(enable_name_change_detection=True)
                
                if season:
                    logger.info(f"Manual roster refresh for season {season}")
                    result = processor.build_registry_for_season(season, team)
                else:
                    logger.info("Manual roster refresh for all seasons")
                    result = processor.build_historical_registry()
                
            else:
                error_msg = f'Unknown processor_type: {processor_type}. Use "gamebook" or "roster"'
                try:
                    notify_error(
                        title="Registry Service: Invalid Processor Type",
                        message=error_msg,
                        details={
                            'service': 'reference-processor-orchestration',
                            'trigger_type': trigger_type,
                            'processor_type': processor_type,
                            'valid_types': ['gamebook', 'roster']
                        },
                        processor_name="Reference Service Orchestration"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
                return {
                    'status': 'error',
                    'message': error_msg
                }
            
            return {
                'status': 'success',
                'trigger_type': trigger_type,
                'processor_type': processor_type,
                'result': result
            }
        
        else:
            error_msg = f'Unknown trigger type: {trigger_type}'
            try:
                notify_warning(
                    title="Registry Service: Unknown Trigger Type",
                    message=error_msg,
                    details={
                        'service': 'reference-processor-orchestration',
                        'trigger_type': trigger_type,
                        'valid_types': ['gamebook_processed', 'roster_scraped', 'manual_refresh'],
                        'action': 'Check message format or add new trigger handler'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return {
                'status': 'error',
                'message': error_msg
            }
    
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        try:
            notify_error(
                title="Registry Service: Message Processing Failed",
                message=f"Unexpected error processing registry message: {str(e)}",
                details={
                    'service': 'reference-processor-orchestration',
                    'trigger_type': message_data.get('trigger_type', 'unknown'),
                    'error_type': type(e).__name__,
                    'error': str(e),
                    'message_data': str(message_data)[:500]  # Truncate for safety
                },
                processor_name="Reference Service Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
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
        'timestamp': datetime.now().isoformat(),
        'processors_available': {
            'gamebook_registry': True,
            'roster_registry': True
        }
    })


@app.route('/process', methods=['POST'])
def process_message():
    """Main Pub/Sub message processing endpoint."""
    try:
        # Extract message from Pub/Sub format
        envelope = request.get_json()
        
        if not envelope:
            try:
                notify_error(
                    title="Registry Service: Empty Pub/Sub Message",
                    message="No Pub/Sub message received",
                    details={
                        'service': 'reference-processor-orchestration',
                        'endpoint': '/process',
                        'issue': 'Empty request body'
                    },
                    processor_name="Reference Service Orchestration"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return jsonify({'error': 'No message received'}), 400
        
        if 'message' not in envelope:
            try:
                notify_error(
                    title="Registry Service: Invalid Pub/Sub Format",
                    message="Missing 'message' field in Pub/Sub envelope",
                    details={
                        'service': 'reference-processor-orchestration',
                        'endpoint': '/process',
                        'envelope_keys': list(envelope.keys()),
                        'issue': 'Invalid message format'
                    },
                    processor_name="Reference Service Orchestration"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return jsonify({'error': 'Invalid Pub/Sub format'}), 400
        
        # Decode the message
        import base64
        try:
            message_data = json.loads(
                base64.b64decode(envelope['message']['data']).decode('utf-8')
            )
        except (KeyError, json.JSONDecodeError, Exception) as e:
            try:
                notify_error(
                    title="Registry Service: Message Decode Failed",
                    message=f"Could not decode Pub/Sub message: {str(e)}",
                    details={
                        'service': 'reference-processor-orchestration',
                        'endpoint': '/process',
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="Reference Service Orchestration"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return jsonify({'error': f'Message decode failed: {str(e)}'}), 400
        
        # Process the message
        result = process_pub_sub_message(message_data)
        
        # Return appropriate HTTP status
        if result.get('status') == 'success':
            return jsonify(result), 200
        else:
            return jsonify(result), 500
    
    except Exception as e:
        logger.error(f"Error in process endpoint: {e}")
        try:
            notify_error(
                title="Registry Service: Endpoint Error",
                message=f"Unexpected error in /process endpoint: {str(e)}",
                details={
                    'service': 'reference-processor-orchestration',
                    'endpoint': '/process',
                    'error_type': type(e).__name__,
                    'error': str(e)
                },
                processor_name="Reference Service Orchestration"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
        
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


@app.route('/trigger/gamebook/<action>', methods=['POST'])
def gamebook_specific_trigger(action: str):
    """Gamebook-specific trigger endpoints."""
    try:
        params = request.get_json() or {}
        
        if action == 'refresh':
            message_data = {
                'trigger_type': 'manual_refresh',
                'processor_type': 'gamebook',
                **params
            }
        elif action == 'summary':
            processor = GamebookRegistryProcessor()
            summary = processor.get_registry_summary()
            return jsonify({
                'status': 'success',
                'summary': summary
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'Unknown gamebook action: {action}'
            }), 400
        
        result = process_pub_sub_message(message_data)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error in gamebook trigger: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)