# predictions/coordinator/coordinator.py

"""
Phase 5 Prediction Coordinator

Cloud Run service that orchestrates daily prediction generation for all NBA players.

Flow:
1. Triggered by Cloud Scheduler (or HTTP request)
2. Query players with games today (~450 players)
3. Publish prediction request for each player to Pub/Sub
4. Monitor completion events from workers
5. Track progress (450/450)
6. Publish summary when complete

Architecture:
- /start endpoint: Initiates prediction batch
- /status endpoint: Check progress
- /complete endpoint: Receives completion events from workers
"""

from flask import Flask, request, jsonify
import json
import logging
import os
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, date
import base64
import time

# Defer google.cloud imports to lazy loading functions to avoid cold start hang
if TYPE_CHECKING:
    from google.cloud import bigquery, pubsub_v1

from player_loader import PlayerLoader
from progress_tracker import ProgressTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)

# Environment configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
PREDICTION_REQUEST_TOPIC = os.environ.get('PREDICTION_REQUEST_TOPIC', 'prediction-request')
PREDICTION_READY_TOPIC = os.environ.get('PREDICTION_READY_TOPIC', 'prediction-ready')
BATCH_SUMMARY_TOPIC = os.environ.get('BATCH_SUMMARY_TOPIC', 'prediction-batch-complete')

# Lazy-loaded components (initialized on first request to avoid cold start timeout)
_player_loader: Optional[PlayerLoader] = None
_pubsub_publisher: Optional['pubsub_v1.PublisherClient'] = None

# Global state (in production, use Firestore or Redis for multi-instance support)
current_tracker: Optional[ProgressTracker] = None
current_batch_id: Optional[str] = None

def get_player_loader() -> PlayerLoader:
    """Lazy-load PlayerLoader on first use"""
    global _player_loader
    if _player_loader is None:
        logger.info("Initializing PlayerLoader...")
        _player_loader = PlayerLoader(PROJECT_ID)
        logger.info("PlayerLoader initialized successfully")
    return _player_loader

def get_pubsub_publisher() -> 'pubsub_v1.PublisherClient':
    """Lazy-load Pub/Sub publisher on first use"""
    from google.cloud import pubsub_v1
    global _pubsub_publisher
    if _pubsub_publisher is None:
        logger.info("Initializing Pub/Sub publisher...")
        _pubsub_publisher = pubsub_v1.PublisherClient()
        logger.info("Pub/Sub publisher initialized successfully")
    return _pubsub_publisher

logger.info("Coordinator initialized successfully (heavy clients will lazy-load on first request)")


@app.route('/', methods=['GET'])
def index():
    """Health check and info endpoint"""
    return jsonify({
        'service': 'Phase 5 Prediction Coordinator',
        'status': 'healthy',
        'project_id': PROJECT_ID,
        'current_batch': current_batch_id,
        'batch_active': current_tracker is not None and not current_tracker.is_complete
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Kubernetes/Cloud Run health check"""
    return jsonify({'status': 'healthy'}), 200


@app.route('/start', methods=['POST'])
def start_prediction_batch():
    """
    Start a new prediction batch
    
    Triggered by Cloud Scheduler or manual HTTP request
    
    Request body (optional):
    {
        "game_date": "2025-11-08",  # defaults to today
        "min_minutes": 15,           # minimum projected minutes
        "use_multiple_lines": false  # test multiple betting lines
    }
    
    Returns:
        202 Accepted with batch info
    """
    global current_tracker, current_batch_id
    
    try:
        # Parse request
        request_data = request.get_json() or {}
        
        # Get game date (default to today)
        game_date_str = request_data.get('game_date')
        if game_date_str:
            game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = date.today()
        
        min_minutes = request_data.get('min_minutes', 15)
        use_multiple_lines = request_data.get('use_multiple_lines', False)
        force = request_data.get('force', False)

        logger.info(f"Starting prediction batch for {game_date}")

        # Check if batch already running
        if current_tracker and not current_tracker.is_complete:
            is_stalled = current_tracker.is_stalled(stall_threshold_seconds=600)
            if not force and not is_stalled:
                logger.warning("Batch already in progress")
                return jsonify({
                    'status': 'already_running',
                    'batch_id': current_batch_id,
                    'progress': current_tracker.get_progress()
                }), 409  # Conflict
            else:
                # Allow override if forced or stalled
                reason = "forced" if force else "stalled"
                logger.warning(f"Overriding existing batch ({reason}), starting new batch")
                current_tracker.reset()
        
        # Create batch ID
        batch_id = f"batch_{game_date.isoformat()}_{int(time.time())}"
        current_batch_id = batch_id
        
        # Get summary stats first
        summary_stats = get_player_loader().get_summary_stats(game_date)
        logger.info(f"Game date summary: {summary_stats}")

        # Create prediction requests
        requests = get_player_loader().create_prediction_requests(
            game_date=game_date,
            min_minutes=min_minutes,
            use_multiple_lines=use_multiple_lines
        )
        
        if not requests:
            logger.error(f"No prediction requests created for {game_date}")
            return jsonify({
                'status': 'error',
                'message': f'No players found for {game_date}',
                'summary': summary_stats
            }), 404
        
        # Initialize progress tracker
        current_tracker = ProgressTracker(expected_players=len(requests))
        
        # Publish all requests to Pub/Sub
        published_count = publish_prediction_requests(requests, batch_id)
        
        logger.info(f"Published {published_count}/{len(requests)} prediction requests")
        
        # Return batch info
        return jsonify({
            'status': 'started',
            'batch_id': batch_id,
            'game_date': game_date.isoformat(),
            'total_requests': len(requests),
            'published': published_count,
            'summary': summary_stats,
            'monitor_url': f'/status?batch_id={batch_id}'
        }), 202  # Accepted
        
    except Exception as e:
        logger.error(f"Error starting batch: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@app.route('/complete', methods=['POST'])
def handle_completion_event():
    """
    Handle prediction-ready events from workers
    
    This endpoint is called by Pub/Sub push subscription when
    a worker completes predictions for a player.
    
    Message format:
    {
        'player_lookup': 'lebron-james',
        'game_date': '2025-11-08',
        'predictions_generated': 5,
        'timestamp': '2025-11-08T10:30:00.123Z'
    }
    """
    global current_tracker
    
    try:
        # Parse Pub/Sub message
        envelope = request.get_json()
        if not envelope:
            logger.error("No Pub/Sub message received")
            return ('Bad Request: no Pub/Sub message received', 400)
        
        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            logger.error("No message field in envelope")
            return ('Bad Request: invalid Pub/Sub message format', 400)
        
        # Decode message data
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        event = json.loads(message_data)
        
        logger.debug(f"Received completion event: {event.get('player_lookup')}")
        
        # Process completion event
        if current_tracker:
            batch_complete = current_tracker.process_completion_event(event)
            
            # If batch is now complete, publish summary
            if batch_complete:
                publish_batch_summary(current_tracker, current_batch_id)
        else:
            logger.warning("Received completion event but no active batch")
        
        return ('', 204)  # Success
        
    except Exception as e:
        logger.error(f"Error processing completion event: {e}", exc_info=True)
        return ('Internal Server Error', 500)


@app.route('/status', methods=['GET'])
def get_batch_status():
    """
    Get current batch status
    
    Query params:
        batch_id: Optional batch ID to check
    
    Returns:
        Current progress and statistics
    """
    global current_tracker, current_batch_id
    
    requested_batch_id = request.args.get('batch_id')
    
    # Check if requested batch matches current batch
    if requested_batch_id and requested_batch_id != current_batch_id:
        return jsonify({
            'status': 'not_found',
            'message': f'Batch {requested_batch_id} not found',
            'current_batch': current_batch_id
        }), 404
    
    if not current_tracker:
        return jsonify({
            'status': 'no_active_batch',
            'current_batch': None
        }), 200
    
    # Get current progress
    progress = current_tracker.get_progress()
    
    # Check if stalled
    is_stalled = current_tracker.is_stalled()
    
    return jsonify({
        'status': 'complete' if current_tracker.is_complete else 'in_progress',
        'batch_id': current_batch_id,
        'progress': progress,
        'is_stalled': is_stalled,
        'summary': current_tracker.get_summary() if current_tracker.is_complete else None
    }), 200


def publish_prediction_requests(requests: List[Dict], batch_id: str) -> int:
    """
    Publish prediction requests to Pub/Sub
    
    Args:
        requests: List of prediction request dicts
        batch_id: Batch identifier for tracking
    
    Returns:
        Number of successfully published messages
    """
    publisher = get_pubsub_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, PREDICTION_REQUEST_TOPIC)

    published_count = 0
    failed_count = 0

    for request_data in requests:
        try:
            # Add batch metadata
            message = {
                **request_data,
                'batch_id': batch_id,
                'timestamp': datetime.now().isoformat()
            }

            # Publish to Pub/Sub
            message_bytes = json.dumps(message).encode('utf-8')
            future = publisher.publish(topic_path, data=message_bytes)
            
            # Wait for publish (with timeout)
            future.result(timeout=5.0)
            
            published_count += 1
            
            # Log every 50 players
            if published_count % 50 == 0:
                logger.info(f"Published {published_count}/{len(requests)} requests")
            
        except Exception as e:
            failed_count += 1
            logger.error(f"Error publishing request for {request_data.get('player_lookup')}: {e}")
            
            # Mark player as failed in tracker
            if current_tracker:
                current_tracker.mark_player_failed(
                    request_data.get('player_lookup', 'unknown'),
                    str(e)
                )
    
    logger.info(
        f"Published {published_count} requests successfully, "
        f"{failed_count} failed"
    )
    
    return published_count


def publish_batch_summary(tracker: ProgressTracker, batch_id: str):
    """
    Publish batch completion summary
    
    Args:
        tracker: Progress tracker with final stats
        batch_id: Batch identifier
    """
    publisher = get_pubsub_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, BATCH_SUMMARY_TOPIC)

    summary = tracker.get_summary()
    summary['batch_id'] = batch_id

    try:
        message_bytes = json.dumps(summary).encode('utf-8')
        future = publisher.publish(topic_path, data=message_bytes)
        future.result(timeout=5.0)
        
        logger.info(f"Published batch summary for {batch_id}")
        logger.info(f"Summary: {json.dumps(summary, indent=2)}")
        
    except Exception as e:
        logger.error(f"Error publishing batch summary: {e}")


if __name__ == '__main__':
    # For local testing
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
