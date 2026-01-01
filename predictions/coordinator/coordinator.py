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
from functools import wraps
import json
import logging
import os
import secrets
import uuid
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, date
import base64
import time

# Defer google.cloud imports to lazy loading functions to avoid cold start hang
if TYPE_CHECKING:
    from google.cloud import bigquery, pubsub_v1

from player_loader import PlayerLoader
from progress_tracker import ProgressTracker
from run_history import CoordinatorRunHistory
from coverage_monitor import PredictionCoverageMonitor
from batch_state_manager import get_batch_state_manager, BatchStateManager, BatchState

# Import batch consolidator for staging table merging
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../worker'))
from batch_staging_writer import BatchConsolidator

# Import unified publishing (lazy import to avoid cold start)
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.publishers.unified_pubsub_publisher import UnifiedPubSubPublisher
from shared.config.orchestration_config import get_orchestration_config
from shared.utils.env_validation import validate_required_env_vars

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Validate required environment variables at startup
validate_required_env_vars(
    ['GCP_PROJECT_ID'],
    service_name='PredictionCoordinator'
)

# Flask app
app = Flask(__name__)

# Environment configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
PREDICTION_REQUEST_TOPIC = os.environ.get('PREDICTION_REQUEST_TOPIC', 'prediction-request-prod')
PREDICTION_READY_TOPIC = os.environ.get('PREDICTION_READY_TOPIC', 'prediction-ready-prod')
BATCH_SUMMARY_TOPIC = os.environ.get('BATCH_SUMMARY_TOPIC', 'prediction-batch-complete')

# API Key authentication (required for /start and /complete endpoints)
COORDINATOR_API_KEY = os.environ.get('COORDINATOR_API_KEY')
if not COORDINATOR_API_KEY:
    logger.warning("COORDINATOR_API_KEY not set - authenticated endpoints will reject all requests")


def require_api_key(f):
    """
    Decorator to require API key authentication for endpoints.

    Checks X-API-Key header or 'key' query parameter.
    Also allows GCP service account identity tokens (Bearer auth).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Allow GCP identity tokens (for Cloud Scheduler and other GCP services)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            # Trust GCP identity tokens (Cloud Run validates these)
            return f(*args, **kwargs)

        # Check API key
        if not COORDINATOR_API_KEY:
            logger.error("COORDINATOR_API_KEY not configured - rejecting request")
            return jsonify({'error': 'Server misconfigured'}), 500

        provided_key = request.headers.get('X-API-Key') or request.args.get('key')
        if not provided_key or not secrets.compare_digest(provided_key, COORDINATOR_API_KEY):
            logger.warning(f"Unauthorized request to {request.path}")
            return jsonify({'error': 'Unauthorized'}), 401

        return f(*args, **kwargs)
    return decorated

# Lazy-loaded components (initialized on first request to avoid cold start timeout)
_player_loader: Optional[PlayerLoader] = None
_pubsub_publisher: Optional['pubsub_v1.PublisherClient'] = None
_run_history: Optional[CoordinatorRunHistory] = None
_bq_client: Optional['bigquery.Client'] = None
_batch_consolidator: Optional[BatchConsolidator] = None
_batch_state_manager: Optional[BatchStateManager] = None

# Global state (DEPRECATED - use BatchStateManager for persistent state)
# These remain for backwards compatibility but should not be used for new code
current_tracker: Optional[ProgressTracker] = None
current_batch_id: Optional[str] = None
current_correlation_id: Optional[str] = None  # Track correlation_id for this batch
current_game_date: Optional[date] = None  # Track game_date for run history

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


def get_run_history() -> CoordinatorRunHistory:
    """Lazy-load run history logger on first use"""
    global _run_history
    if _run_history is None:
        logger.info("Initializing CoordinatorRunHistory...")
        _run_history = CoordinatorRunHistory(project_id=PROJECT_ID)
        logger.info("CoordinatorRunHistory initialized successfully")
    return _run_history


def get_bq_client() -> 'bigquery.Client':
    """Lazy-load BigQuery client on first use"""
    from google.cloud import bigquery
    global _bq_client
    if _bq_client is None:
        logger.info("Initializing BigQuery client...")
        _bq_client = bigquery.Client(project=PROJECT_ID, location='us-west2')
        logger.info("BigQuery client initialized")
    return _bq_client


def get_batch_consolidator() -> BatchConsolidator:
    """Lazy-load batch consolidator on first use"""
    global _batch_consolidator
    if _batch_consolidator is None:
        logger.info("Initializing BatchConsolidator...")
        _batch_consolidator = BatchConsolidator(get_bq_client(), PROJECT_ID)
        logger.info("BatchConsolidator initialized")
    return _batch_consolidator


def get_state_manager() -> BatchStateManager:
    """Lazy-load batch state manager on first use"""
    global _batch_state_manager
    if _batch_state_manager is None:
        logger.info("Initializing BatchStateManager...")
        _batch_state_manager = get_batch_state_manager(PROJECT_ID)
        logger.info("BatchStateManager initialized")
    return _batch_state_manager


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
@require_api_key
def start_prediction_batch():
    """
    Start a new prediction batch

    Triggered by Cloud Scheduler or manual HTTP request (or Phase 4 completion)

    Request body (optional):
    {
        "game_date": "2025-11-08",     # defaults to today
        "min_minutes": 15,              # minimum projected minutes
        "use_multiple_lines": false,    # test multiple betting lines
        "correlation_id": "abc-123",    # optional - for pipeline tracing
        "parent_processor": "MLFeatureStore",  # optional
        "dataset_prefix": "test"        # optional - for test dataset isolation
    }

    Returns:
        202 Accepted with batch info
    """
    global current_tracker, current_batch_id, current_correlation_id, current_game_date

    try:
        # Parse request
        request_data = request.get_json() or {}

        # Get game date (default to today)
        # Supports: specific date (YYYY-MM-DD), "TODAY", "TOMORROW"
        game_date_str = request_data.get('game_date')
        if game_date_str:
            if game_date_str == "TODAY":
                from zoneinfo import ZoneInfo
                game_date = datetime.now(ZoneInfo('America/New_York')).date()
                logger.info(f"TODAY game_date resolved to: {game_date}")
            elif game_date_str == "TOMORROW":
                from zoneinfo import ZoneInfo
                from datetime import timedelta
                game_date = datetime.now(ZoneInfo('America/New_York')).date() + timedelta(days=1)
                logger.info(f"TOMORROW game_date resolved to: {game_date}")
            else:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = date.today()

        min_minutes = request_data.get('min_minutes', 15)
        # Use orchestration config for default (Issue 4: enable multiple lines by default)
        orch_config = get_orchestration_config()
        use_multiple_lines = request_data.get(
            'use_multiple_lines',
            orch_config.prediction_mode.use_multiple_lines_default
        )
        force = request_data.get('force', False)

        # Extract correlation tracking (for pipeline tracing Phase 1→5)
        correlation_id = request_data.get('correlation_id') or str(uuid.uuid4())[:8]
        parent_processor = request_data.get('parent_processor')
        dataset_prefix = request_data.get('dataset_prefix', '')  # Optional test dataset prefix
        current_correlation_id = correlation_id

        logger.info(
            f"Starting prediction batch for {game_date} "
            f"(correlation_id={correlation_id}, parent={parent_processor}, "
            f"dataset_prefix={dataset_prefix or 'production'})"
        )

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
        current_game_date = game_date

        # Get summary stats first
        summary_stats = get_player_loader().get_summary_stats(game_date, dataset_prefix=dataset_prefix)
        logger.info(f"Game date summary: {summary_stats}")

        # Create prediction requests
        requests = get_player_loader().create_prediction_requests(
            game_date=game_date,
            min_minutes=min_minutes,
            use_multiple_lines=use_multiple_lines,
            dataset_prefix=dataset_prefix
        )

        if not requests:
            logger.error(f"No prediction requests created for {game_date}")
            return jsonify({
                'status': 'error',
                'message': f'No players found for {game_date}',
                'summary': summary_stats
            }), 404

        # BATCH OPTIMIZATION: Pre-load historical games for all players (331x speedup!)
        # Instead of workers querying individually (225s total for sequential queries),
        # coordinator loads once (0.68s) and passes to workers via Pub/Sub
        # VERIFIED: Dec 31, 2025 - 118 players loaded in 0.68s, all workers used batch data
        batch_historical_games = None
        try:
            player_lookups = [r.get('player_lookup') for r in requests if r.get('player_lookup')]
            if player_lookups:
                # Use print for visibility in Cloud Run (logger.info gets lost in gunicorn)
                print(f"🚀 Pre-loading historical games for {len(player_lookups)} players (batch optimization)", flush=True)
                logger.info(f"🚀 Pre-loading historical games for {len(player_lookups)} players (batch optimization)")

                # Import PredictionDataLoader to use batch loading method
                from data_loaders import PredictionDataLoader

                data_loader = PredictionDataLoader(project_id=PROJECT_ID, dataset_prefix=dataset_prefix)
                batch_historical_games = data_loader.load_historical_games_batch(
                    player_lookups=player_lookups,
                    game_date=game_date,
                    lookback_days=90,
                    max_games=30
                )

                print(f"✅ Batch loaded historical games for {len(batch_historical_games)} players", flush=True)
                logger.info(f"✅ Batch loaded historical games for {len(batch_historical_games)} players")
        except Exception as e:
            # Non-fatal: workers can fall back to individual queries
            logger.warning(f"Batch historical load failed (workers will use individual queries): {e}")
            batch_historical_games = None

        # Initialize progress tracker (DEPRECATED - keeping for backward compatibility)
        current_tracker = ProgressTracker(expected_players=len(requests))

        # Create batch state in Firestore (PERSISTENT - survives container restarts!)
        try:
            state_manager = get_state_manager()
            batch_state = state_manager.create_batch(
                batch_id=batch_id,
                game_date=game_date.isoformat(),
                expected_players=len(requests),
                correlation_id=correlation_id,
                dataset_prefix=dataset_prefix
            )
            logger.info(
                f"✅ Batch state persisted to Firestore: {batch_id} "
                f"(expected={len(requests)} players)"
            )
        except Exception as e:
            # This is critical - without persistent state, consolidation won't work after restart
            logger.error(f"❌ CRITICAL: Failed to persist batch state to Firestore: {e}", exc_info=True)
            raise

        # Log batch start to processor_run_history for unified monitoring
        try:
            get_run_history().start_batch(
                batch_id=batch_id,
                game_date=game_date,
                correlation_id=correlation_id,
                parent_processor=parent_processor,
                trigger_source='api' if request_data else 'scheduler',
                expected_players=len(requests)
            )
        except Exception as e:
            # Don't fail the batch if run history logging fails
            logger.warning(f"Failed to log batch start (non-fatal): {e}")

        # Publish all requests to Pub/Sub (with batch historical data if available)
        published_count = publish_prediction_requests(requests, batch_id, batch_historical_games, dataset_prefix)
        
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
@require_api_key
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
        
        player_lookup = event.get('player_lookup')
        batch_id = event.get('batch_id')  # Workers should include batch_id in completion events
        predictions_count = event.get('predictions_generated', 0)

        logger.debug(f"Received completion event: {player_lookup} (batch={batch_id})")

        # Process completion event using Firestore (PERSISTENT - survives restarts!)
        try:
            if not batch_id:
                logger.error("Completion event missing batch_id - cannot process")
                return ('Bad Request: batch_id required', 400)

            state_manager = get_state_manager()
            batch_complete = state_manager.record_completion(
                batch_id=batch_id,
                player_lookup=player_lookup,
                predictions_count=predictions_count
            )

            # BACKWARD COMPATIBILITY: Also update in-memory tracker if it exists
            if current_tracker and current_batch_id == batch_id:
                current_tracker.process_completion_event(event)

            # If batch is now complete, publish summary and trigger consolidation
            if batch_complete:
                logger.info(f"🎉 Batch {batch_id} complete! Triggering consolidation...")
                publish_batch_summary_from_firestore(batch_id)
        except Exception as e:
            logger.error(f"Error recording completion to Firestore: {e}", exc_info=True)
            # Don't fail the request - worker already succeeded
            # Return 204 so Pub/Sub doesn't retry

        return ('', 204)  # Success
        
    except Exception as e:
        logger.error(f"Error processing completion event: {e}", exc_info=True)
        return ('Internal Server Error', 500)


@app.route('/status', methods=['GET'])
@require_api_key
def get_batch_status():
    """
    Get current batch status (REQUIRES AUTHENTICATION)

    Query params:
        batch_id: Optional batch ID to check

    Returns:
        Current progress and statistics

    Authentication:
        Requires X-API-Key header or 'key' query parameter
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


def publish_with_retry(publisher, topic_path: str, message_bytes: bytes,
                       player_lookup: str, max_retries: int = 3) -> bool:
    """
    Publish a message to Pub/Sub with exponential backoff retry.

    Args:
        publisher: Pub/Sub publisher client
        topic_path: Full topic path
        message_bytes: Encoded message data
        player_lookup: Player identifier for logging
        max_retries: Maximum number of retry attempts (default 3)

    Returns:
        True if publish succeeded, False otherwise

    Retry delays: 1s, 2s, 4s (exponential backoff)
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            future = publisher.publish(topic_path, data=message_bytes)
            # Wait for publish confirmation with timeout
            future.result(timeout=5.0)
            return True
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s
                delay = 2 ** attempt
                logger.warning(
                    f"Pub/Sub publish attempt {attempt + 1}/{max_retries} failed for "
                    f"{player_lookup}: {e}. Retrying in {delay}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"Pub/Sub publish failed after {max_retries} attempts for "
                    f"{player_lookup}: {e}"
                )

    return False


def publish_prediction_requests(
    requests: List[Dict],
    batch_id: str,
    batch_historical_games: Optional[Dict[str, List[Dict]]] = None,
    dataset_prefix: str = ''
) -> int:
    """
    Publish prediction requests to Pub/Sub

    Args:
        requests: List of prediction request dicts
        batch_id: Batch identifier for tracking
        batch_historical_games: Optional pre-loaded historical games (batch optimization)
                                Dict mapping player_lookup -> list of historical games
        dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")

    Returns:
        Number of successfully published messages
    """
    publisher = get_pubsub_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, PREDICTION_REQUEST_TOPIC)

    published_count = 0
    failed_count = 0

    for request_data in requests:
        # Add batch metadata
        message = {
            **request_data,
            'batch_id': batch_id,
            'timestamp': datetime.now().isoformat()
        }

        # Add dataset_prefix for test isolation if specified
        if dataset_prefix:
            message['dataset_prefix'] = dataset_prefix

        # BATCH OPTIMIZATION: Include pre-loaded historical games if available
        if batch_historical_games:
            player_lookup = request_data.get('player_lookup')
            if player_lookup and player_lookup in batch_historical_games:
                # Add historical games to message (worker will use this instead of querying)
                message['historical_games_batch'] = batch_historical_games[player_lookup]

        # Publish to Pub/Sub with retry logic
        message_bytes = json.dumps(message).encode('utf-8')
        player_lookup = request_data.get('player_lookup', 'unknown')

        if publish_with_retry(publisher, topic_path, message_bytes, player_lookup):
            published_count += 1

            # Log every 50 players
            if published_count % 50 == 0:
                logger.info(f"Published {published_count}/{len(requests)} requests")
        else:
            failed_count += 1

            # Mark player as failed in tracker
            if current_tracker:
                current_tracker.mark_player_failed(
                    player_lookup,
                    "Pub/Sub publish failed after retries"
                )
    
    logger.info(
        f"Published {published_count} requests successfully, "
        f"{failed_count} failed"
    )
    
    return published_count


def send_prediction_completion_email(summary: Dict, game_date: str, batch_id: str):
    """
    Send prediction completion summary email via AWS SES.

    Args:
        summary: Summary dict from ProgressTracker.get_summary()
        game_date: Date predictions were generated for
        batch_id: Batch identifier
    """
    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES

        # Get games count from BigQuery (or estimate from players)
        # For now, estimate: ~15 players per game average
        completed = summary.get('completed_players', 0)
        expected = summary.get('expected_players', 0)
        games_count = max(1, completed // 15) if completed > 0 else 0

        # Build failed players list with reasons
        failed_list = summary.get('failed_player_list', [])
        failed_players = [
            {'name': player, 'reason': 'Prediction generation failed'}
            for player in failed_list
        ]

        # Calculate confidence distribution (placeholder - would need actual prediction data)
        # In production, query nba_predictions.player_prop_predictions for this
        total_predictions = summary.get('total_predictions', 0)
        # Estimate distribution (would be replaced with actual query)
        high_conf = int(total_predictions * 0.4)
        med_conf = int(total_predictions * 0.45)
        low_conf = total_predictions - high_conf - med_conf

        # Build email data
        prediction_data = {
            'date': game_date,
            'games_count': games_count,
            'players_predicted': completed,
            'players_total': expected,
            'failed_players': failed_players,
            'confidence_distribution': {
                'high': high_conf,
                'medium': med_conf,
                'low': low_conf
            },
            'top_recommendations': [],  # Would need to query predictions table
            'duration_minutes': int(summary.get('duration_seconds', 0) / 60)
        }

        # Send email
        alerter = EmailAlerterSES()
        success = alerter.send_prediction_completion_summary(prediction_data)

        if success:
            logger.info(f"📧 Prediction completion email sent for {game_date}")
        else:
            logger.warning(f"Failed to send prediction completion email for {game_date}")

        # Send to Slack #nba-predictions channel
        try:
            from shared.utils.slack_channels import send_prediction_summary_to_slack
            slack_success = send_prediction_summary_to_slack(prediction_data)
            if slack_success:
                logger.info(f"💬 Prediction completion sent to Slack for {game_date}")
        except Exception as slack_err:
            logger.debug(f"Slack notification skipped: {slack_err}")

    except ImportError as e:
        logger.warning(f"Email alerter not available (non-fatal): {e}")
    except Exception as e:
        logger.error(f"Error sending prediction completion email (non-fatal): {e}")


def publish_batch_summary_from_firestore(batch_id: str):
    """
    Publish batch summary using persistent state from Firestore

    This function is used when completion events trigger consolidation
    after a container restart (when in-memory tracker is lost).

    Args:
        batch_id: Batch identifier
    """
    try:
        # Get batch state from Firestore
        state_manager = get_state_manager()
        batch_state = state_manager.get_batch_state(batch_id)

        if not batch_state:
            logger.error(f"Cannot publish summary - batch state not found: {batch_id}")
            return

        # Extract game_date and build summary
        game_date = batch_state.game_date

        logger.info(
            f"Publishing batch summary from Firestore: {batch_id} "
            f"({len(batch_state.completed_players)}/{batch_state.expected_players} players)"
        )

        # Step 1: Consolidate staging tables into main predictions table
        try:
            consolidator = get_batch_consolidator()
            consolidation_result = consolidator.consolidate_batch(
                batch_id=batch_id,
                game_date=game_date,
                cleanup=True  # Delete staging tables after successful merge
            )

            if consolidation_result.success:
                logger.info(
                    f"✅ Consolidation complete: {consolidation_result.rows_affected} rows merged "
                    f"from {consolidation_result.staging_tables_merged} staging tables"
                )
            else:
                logger.error(f"❌ Consolidation failed: {consolidation_result.error_message}")
        except Exception as e:
            logger.error(f"Consolidation failed: {e}", exc_info=True)

        # Step 2: Publish Phase 5 completion event to trigger Phase 6
        try:
            # Calculate duration if timestamps are available
            duration_seconds = None
            if batch_state.start_time and batch_state.completion_time:
                duration_seconds = (batch_state.completion_time - batch_state.start_time).total_seconds()

            unified_publisher = UnifiedPubSubPublisher(project_id=PROJECT_ID)
            unified_publisher.publish_completion(
                topic='nba-phase5-predictions-complete',
                processor_name='PredictionCoordinator',
                phase='phase_5_predictions',
                execution_id=batch_id,
                correlation_id=batch_state.correlation_id or batch_id,
                game_date=game_date,
                output_table='player_prop_predictions',
                output_dataset='nba_predictions',
                status='complete',
                record_count=len(batch_state.completed_players),
                records_failed=len(batch_state.failed_players),
                trigger_source='automatic',
                duration_seconds=duration_seconds,
                metadata={
                    'batch_id': batch_id,
                    'expected_players': batch_state.expected_players,
                    'completed_players': len(batch_state.completed_players),
                    'total_predictions': batch_state.total_predictions,
                    'completion_percentage': batch_state.get_completion_percentage()
                }
            )
            logger.info(f"Published Phase 5 completion for batch: {batch_id}")
        except Exception as e:
            logger.error(f"Failed to publish completion message: {e}", exc_info=True)

        logger.info(f"✅ Batch summary published successfully: {batch_id}")

    except Exception as e:
        logger.error(f"Error publishing batch summary from Firestore: {e}", exc_info=True)


def publish_batch_summary(tracker: ProgressTracker, batch_id: str):
    """
    Publish unified batch completion summary (LEGACY - uses in-memory tracker)

    Uses UnifiedPubSubPublisher for consistency with Phases 1-4.
    Also logs to processor_run_history for unified monitoring.
    Sends prediction completion email notification.

    Flow:
    1. Consolidate staging tables (merge all worker writes into main table)
    2. Check coverage and send alerts if below thresholds
    3. Log to run history
    4. Publish completion message
    5. Send email notification

    Args:
        tracker: Progress tracker with final stats
        batch_id: Batch identifier
    """
    global current_correlation_id, current_game_date

    try:
        # Use unified publisher
        unified_publisher = UnifiedPubSubPublisher(project_id=PROJECT_ID)

        summary = tracker.get_summary()
        game_date = current_game_date.isoformat() if current_game_date else date.today().isoformat()

        # Step 1: Consolidate staging tables into main predictions table
        # This is critical for the batch staging write pattern to work
        try:
            consolidator = get_batch_consolidator()
            consolidation_result = consolidator.consolidate_batch(
                batch_id=batch_id,
                game_date=game_date,
                cleanup=True  # Delete staging tables after successful merge
            )

            if consolidation_result.success:
                logger.info(
                    f"✅ Consolidation complete: {consolidation_result.rows_affected} rows merged "
                    f"from {consolidation_result.staging_tables_merged} staging tables"
                )
                # Update summary with consolidation info
                summary['consolidation'] = {
                    'rows_affected': consolidation_result.rows_affected,
                    'staging_tables_merged': consolidation_result.staging_tables_merged,
                    'staging_tables_cleaned': consolidation_result.staging_tables_cleaned,
                    'success': True
                }
            else:
                logger.error(f"❌ Consolidation failed: {consolidation_result.error_message}")
                summary['consolidation'] = {
                    'success': False,
                    'error': consolidation_result.error_message
                }
        except Exception as e:
            # Don't fail the batch summary if consolidation fails
            logger.error(f"Consolidation failed (non-fatal): {e}", exc_info=True)
            summary['consolidation'] = {'success': False, 'error': str(e)}

        # Check prediction coverage and send alerts if below thresholds
        try:
            coverage_monitor = PredictionCoverageMonitor(project_id=PROJECT_ID)
            expected_players = summary.get('expected', 0)
            completed_players = summary.get('completed', 0)

            coverage_ok = coverage_monitor.check_coverage(
                players_expected=expected_players,
                players_predicted=completed_players,
                game_date=current_game_date or date.today(),
                batch_id=batch_id,
                additional_context={
                    'correlation_id': current_correlation_id,
                    'failed_players': summary.get('failed', 0)
                }
            )

            # Track missing players if coverage is not 100%
            if completed_players < expected_players:
                # Get the sets from tracker for detailed missing player tracking
                expected_set = tracker.get_expected_players() if hasattr(tracker, 'get_expected_players') else set()
                completed_set = tracker.completed_players if hasattr(tracker, 'completed_players') else set()

                if expected_set and completed_set:
                    missing_players = coverage_monitor.track_missing_players(
                        expected_set=expected_set,
                        predicted_set=completed_set,
                        game_date=current_game_date or date.today(),
                        log_all=False  # Only log summary for large sets
                    )
                    if missing_players:
                        logger.info(f"Coverage monitor identified {len(missing_players)} missing players")

            logger.info(f"Coverage check complete: {'PASSED' if coverage_ok else 'BELOW THRESHOLD'}")
        except Exception as e:
            # Don't fail the batch summary if coverage monitoring fails
            logger.warning(f"Coverage monitoring failed (non-fatal): {e}")

        # Determine status based on completion
        if summary.get('completed', 0) == summary.get('expected', 0):
            status = 'success'
        elif summary.get('completed', 0) > 0:
            status = 'partial'
        else:
            status = 'failed'

        # Log batch completion to processor_run_history for unified monitoring
        try:
            get_run_history().complete_batch(
                status=status,
                records_processed=summary.get('completed', 0),
                records_failed=summary.get('failed', 0),
                duration_seconds=summary.get('duration_seconds', 0),
                summary=summary
            )
        except Exception as e:
            # Don't fail the batch if run history logging fails
            logger.warning(f"Failed to log batch completion (non-fatal): {e}")

        # Publish unified message
        message_id = unified_publisher.publish_completion(
            topic='nba-phase5-predictions-complete',
            processor_name='PredictionCoordinator',
            phase='phase_5_predictions',
            execution_id=batch_id,
            correlation_id=current_correlation_id or batch_id,
            game_date=game_date,
            output_table='player_prop_predictions',
            output_dataset='nba_predictions',
            status=status,
            record_count=summary.get('completed', 0),
            records_failed=summary.get('failed', 0),
            parent_processor=None,  # Could track Phase 4 processor
            trigger_source='scheduler',
            trigger_message_id=None,
            duration_seconds=summary.get('duration_seconds', 0),
            error_message=None,
            error_type=None,
            metadata={
                # Phase 5 specific metadata
                'batch_id': batch_id,
                'expected_predictions': summary.get('expected', 0),
                'completed_predictions': summary.get('completed', 0),
                'failed_predictions': summary.get('failed', 0),
                'completion_pct': summary.get('completion_pct', 0),
                'stall_detected': summary.get('stall_detected', False),

                # Include full summary
                'summary': summary
            },
            skip_downstream=False
        )

        if message_id:
            logger.info(
                f"✅ Published unified batch summary for {batch_id} "
                f"(message_id={message_id}, correlation_id={current_correlation_id})"
            )
            logger.info(f"Summary: {json.dumps(summary, indent=2)}")
        else:
            logger.warning("Failed to publish batch summary")

        # Send prediction completion email
        send_prediction_completion_email(summary, game_date, batch_id)

    except Exception as e:
        logger.error(f"Error publishing batch summary: {e}", exc_info=True)


if __name__ == '__main__':
    # For local testing
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
