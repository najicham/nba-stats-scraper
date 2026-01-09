# predictions/worker/worker.py

"""
Phase 5 Prediction Worker

Cloud Run service that receives player prediction requests via Pub/Sub
and generates predictions using all 5 prediction systems.

Architecture:
- Flask app with Pub/Sub push endpoint
- Scales 0-20 instances with 5 threads each (100 concurrent players)
- Loads data from BigQuery (features + historical games)
- Calls all 5 prediction systems
- Writes predictions to BigQuery
- Publishes completion events

Performance:
- Target: 450 players in 2-3 minutes (parallel processing)
- Per-player: ~200-300ms (data loading + 5 predictions + write)
"""

# Early logging setup for debugging import issues
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("=== WORKER MODULE IMPORT START ===")

from flask import Flask, request, jsonify
logger.info("✓ Flask imported")

import json
import os
import sys
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, date
import uuid
import base64
import time
logger.info("✓ Standard library imports completed")

# Validate required environment variables at startup
# Import path setup needed before shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from shared.utils.env_validation import validate_required_env_vars
validate_required_env_vars(
    ['GCP_PROJECT_ID'],
    service_name='PredictionWorker'
)
logger.info("✓ Environment variables validated")


def validate_ml_model_availability():
    """
    Fail-fast validation for ML model accessibility at startup.

    In production (Cloud Run), CATBOOST_V8_MODEL_PATH should be set.
    If set, validates the model path is properly formatted.
    If not set, validates local models exist in models/ directory.

    Raises RuntimeError if no valid model configuration found.
    """
    from pathlib import Path

    model_path = os.environ.get('CATBOOST_V8_MODEL_PATH')

    if model_path:
        # Production: env var is set - validate path format
        if model_path.startswith('gs://'):
            # GCS path - can't verify accessibility at startup without adding latency
            # Just validate format: gs://bucket/path/to/file.cbm
            if not model_path.endswith('.cbm'):
                raise RuntimeError(
                    f"CATBOOST_V8_MODEL_PATH invalid format: {model_path}. "
                    f"Expected path ending with .cbm"
                )
            logger.info(f"✓ CATBOOST_V8_MODEL_PATH set: {model_path} (GCS, will verify on first use)")
        else:
            # Local path - verify file exists
            if not Path(model_path).exists():
                raise RuntimeError(
                    f"CATBOOST_V8_MODEL_PATH file not found: {model_path}. "
                    f"Ensure the model file exists or correct the path."
                )
            logger.info(f"✓ CATBOOST_V8_MODEL_PATH verified: {model_path}")
    else:
        # Development/local: check for local models
        models_dir = Path(__file__).parent.parent.parent / "models"
        model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))

        if not model_files:
            logger.warning(
                "⚠ No CATBOOST_V8_MODEL_PATH set and no local v8 models found. "
                f"Searched: {models_dir}/catboost_v8_33features_*.cbm. "
                "CatBoost v8 will use fallback predictions (confidence=50)."
            )
        else:
            logger.info(f"✓ Found {len(model_files)} local CatBoost v8 model(s): {[f.name for f in model_files]}")


# Validate ML model availability at startup
validate_ml_model_availability()

# Defer google.cloud imports to lazy loading functions to avoid cold start hang
if TYPE_CHECKING:
    from google.cloud import bigquery, pubsub_v1
logger.info("✓ Google Cloud client imports deferred (will lazy-load)")

# Defer ALL heavy imports to lazy loading functions to avoid cold start timeouts
if TYPE_CHECKING:
    from prediction_systems.moving_average_baseline import MovingAverageBaseline
    from prediction_systems.zone_matchup_v1 import ZoneMatchupV1
    from prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
    from prediction_systems.catboost_v8 import CatBoostV8  # v8 ML model (3.40 MAE)
    from prediction_systems.ensemble_v1 import EnsembleV1
    from data_loaders import PredictionDataLoader, normalize_confidence, validate_features
    from system_circuit_breaker import SystemCircuitBreaker
    from execution_logger import ExecutionLogger
    from shared.utils.player_registry import RegistryReader, PlayerNotFoundError
    from batch_staging_writer import BatchStagingWriter, get_worker_id

from write_metrics import PredictionWriteMetrics

logger.info("✓ Heavy imports deferred (will lazy-load on first request)")

# Flask app
app = Flask(__name__)
logger.info("✓ Flask app created")

# Environment configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
PREDICTIONS_TABLE = os.environ.get('PREDICTIONS_TABLE', 'nba_predictions.player_prop_predictions')
PUBSUB_READY_TOPIC = os.environ.get('PUBSUB_READY_TOPIC', 'prediction-ready')
logger.info("✓ Environment configuration loaded")

# Lazy-loaded components (initialized on first request to avoid cold start timeout)
_data_loader: Optional['PredictionDataLoader'] = None
_bq_client: Optional['bigquery.Client'] = None
_pubsub_publisher: Optional['pubsub_v1.PublisherClient'] = None
_player_registry: Optional['RegistryReader'] = None
_moving_average: Optional['MovingAverageBaseline'] = None
_zone_matchup: Optional['ZoneMatchupV1'] = None
_similarity: Optional['SimilarityBalancedV1'] = None
_xgboost: Optional['XGBoostV1'] = None
_ensemble: Optional['EnsembleV1'] = None
_staging_writer: Optional['BatchStagingWriter'] = None

def get_data_loader() -> 'PredictionDataLoader':
    """Lazy-load data loader on first use"""
    from data_loaders import PredictionDataLoader
    global _data_loader
    if _data_loader is None:
        logger.info("Initializing PredictionDataLoader...")
        _data_loader = PredictionDataLoader(PROJECT_ID)
        logger.info("PredictionDataLoader initialized")
    return _data_loader

def get_bq_client() -> 'bigquery.Client':
    """Lazy-load BigQuery client on first use"""
    from google.cloud import bigquery
    global _bq_client
    if _bq_client is None:
        logger.info("Initializing BigQuery client...")
        _bq_client = bigquery.Client(project=PROJECT_ID, location='us-west2')
        logger.info("BigQuery client initialized")
    return _bq_client

def get_staging_writer() -> 'BatchStagingWriter':
    """Lazy-load staging writer on first use"""
    from batch_staging_writer import BatchStagingWriter
    global _staging_writer
    if _staging_writer is None:
        logger.info("Initializing BatchStagingWriter...")
        _staging_writer = BatchStagingWriter(get_bq_client(), PROJECT_ID)
        logger.info("BatchStagingWriter initialized")
    return _staging_writer

def get_pubsub_publisher() -> 'pubsub_v1.PublisherClient':
    """Lazy-load Pub/Sub publisher on first use"""
    from google.cloud import pubsub_v1
    global _pubsub_publisher
    if _pubsub_publisher is None:
        logger.info("Initializing Pub/Sub publisher...")
        _pubsub_publisher = pubsub_v1.PublisherClient()
        logger.info("Pub/Sub publisher initialized")
    return _pubsub_publisher

def get_player_registry() -> 'RegistryReader':
    """Lazy-load player registry on first use"""
    from shared.utils.player_registry import RegistryReader
    global _player_registry
    if _player_registry is None:
        logger.info("Initializing player registry...")
        _player_registry = RegistryReader(
            project_id=PROJECT_ID,
            source_name='prediction_worker',
            cache_ttl_seconds=300
        )
        logger.info("Player registry initialized")
    return _player_registry

def get_prediction_systems() -> tuple:
    """Lazy-load all prediction systems on first use"""
    from prediction_systems.moving_average_baseline import MovingAverageBaseline
    from prediction_systems.zone_matchup_v1 import ZoneMatchupV1
    from prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
    from prediction_systems.catboost_v8 import CatBoostV8  # v8 replaces mock XGBoostV1
    from prediction_systems.ensemble_v1 import EnsembleV1

    global _moving_average, _zone_matchup, _similarity, _xgboost, _ensemble
    if _ensemble is None:
        logger.info("Initializing prediction systems...")
        _moving_average = MovingAverageBaseline()
        _zone_matchup = ZoneMatchupV1()
        _similarity = SimilarityBalancedV1()
        _xgboost = CatBoostV8()  # CatBoost v8: 3.40 MAE (vs mock's 4.80)
        _ensemble = EnsembleV1(
            moving_average_system=_moving_average,
            zone_matchup_system=_zone_matchup,
            similarity_system=_similarity,
            xgboost_system=_xgboost
        )
        logger.info("All prediction systems initialized (using CatBoost v8)")
    return _moving_average, _zone_matchup, _similarity, _xgboost, _ensemble

_circuit_breaker: Optional['SystemCircuitBreaker'] = None
_execution_logger: Optional['ExecutionLogger'] = None

def get_circuit_breaker() -> 'SystemCircuitBreaker':
    """Lazy-load circuit breaker on first use"""
    from system_circuit_breaker import SystemCircuitBreaker
    global _circuit_breaker
    if _circuit_breaker is None:
        logger.info("Initializing SystemCircuitBreaker...")
        _circuit_breaker = SystemCircuitBreaker(get_bq_client(), PROJECT_ID)
        logger.info("SystemCircuitBreaker initialized")
    return _circuit_breaker

def get_execution_logger() -> 'ExecutionLogger':
    """Lazy-load execution logger on first use"""
    from execution_logger import ExecutionLogger
    global _execution_logger
    if _execution_logger is None:
        logger.info("Initializing ExecutionLogger...")
        _execution_logger = ExecutionLogger(get_bq_client(), PROJECT_ID, worker_version="1.0")
        logger.info("ExecutionLogger initialized")
    return _execution_logger

logger.info("✓ Lazy loading functions defined")
logger.info("=== WORKER MODULE IMPORT COMPLETE ===")
logger.info("Worker initialized successfully (heavy clients will lazy-load on first request)")


@app.route('/', methods=['GET'])
def index():
    """Health check endpoint"""
    # Get systems only if they're already loaded (don't force lazy load for health check)
    systems_info = {}
    if _ensemble is not None:
        systems_info = {
            'moving_average': str(_moving_average),
            'zone_matchup': str(_zone_matchup),
            'similarity': str(_similarity),
            'xgboost': str(_xgboost),
            'ensemble': str(_ensemble)
        }
    else:
        systems_info = {'status': 'not yet loaded (will lazy-load on first prediction)'}

    return jsonify({
        'service': 'Phase 5 Prediction Worker',
        'status': 'healthy',
        'systems': systems_info
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Kubernetes/Cloud Run health check"""
    return jsonify({'status': 'healthy'}), 200


@app.route('/predict', methods=['POST'])
def handle_prediction_request():
    """
    Handle Pub/Sub push request for player prediction

    Expected message format:
    {
        'player_lookup': 'lebron-james',
        'game_date': '2025-11-08',
        'game_id': '20251108_LAL_GSW',
        'line_values': [25.5]  # Or multiple: [23.5, 24.5, 25.5, 26.5, 27.5]
    }

    Returns:
        204 on success, 400/500 on error
    """
    start_time = time.time()

    # Lazy-load all components on first request (except data_loader - created per request for dataset isolation)
    bq_client = get_bq_client()
    pubsub_publisher = get_pubsub_publisher()
    player_registry = get_player_registry()
    moving_average, zone_matchup, similarity, xgboost, ensemble = get_prediction_systems()
    circuit_breaker = get_circuit_breaker()
    execution_logger = get_execution_logger()

    player_lookup = None
    game_date_str = None
    game_id = None
    line_values = []
    universal_player_id = None

    try:
        # Parse Pub/Sub message
        envelope = request.get_json()
        if not envelope:
            logger.error("No Pub/Sub message received")
            return ('Bad Request: no Pub/Sub message received', 400)

        # Decode message
        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            logger.error("No message field in envelope")
            return ('Bad Request: invalid Pub/Sub message format', 400)

        # Get message data
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        request_data = json.loads(message_data)

        # Extract dataset_prefix for test isolation (if present)
        dataset_prefix = request_data.get('dataset_prefix', '')

        logger.info(f"Processing prediction request: {request_data.get('player_lookup')} on {request_data.get('game_date')} (dataset_prefix: {dataset_prefix or 'production'})")

        # Extract request parameters
        player_lookup = request_data['player_lookup']
        game_date_str = request_data['game_date']
        game_id = request_data['game_id']
        line_values = request_data.get('line_values', [])
        batch_id = request_data.get('batch_id')  # From coordinator for staging writes

        # BATCH OPTIMIZATION: Extract pre-loaded historical games if available
        historical_games_batch = request_data.get('historical_games_batch')
        if historical_games_batch:
            print(f"✅ Worker using pre-loaded historical games ({len(historical_games_batch)} games) from coordinator", flush=True)
            logger.info(f"Using pre-loaded historical games ({len(historical_games_batch)} games) from coordinator")

        # DATASET ISOLATION: Create new data_loader with dataset_prefix if specified
        # Otherwise use the cached global loader for production
        if dataset_prefix:
            from data_loaders import PredictionDataLoader
            data_loader = PredictionDataLoader(PROJECT_ID, dataset_prefix=dataset_prefix)
            logger.debug(f"Created isolated data_loader with prefix: {dataset_prefix}")
        else:
            data_loader = get_data_loader()  # Use cached production loader

        # v3.2: Extract line source tracking info
        line_source_info = {
            'has_prop_line': request_data.get('has_prop_line', True),  # Default True for backwards compat
            'actual_prop_line': request_data.get('actual_prop_line'),
            'line_source': request_data.get('line_source', 'ACTUAL_PROP'),  # Default to actual
            'estimated_line_value': request_data.get('estimated_line_value'),
            'estimation_method': request_data.get('estimation_method')
        }

        # Convert date string to date object
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        # Get universal player ID
        try:
            universal_player_id = player_registry.get_universal_id(player_lookup, required=False)
        except Exception as e:
            logger.warning(
                f"Failed to get universal_player_id for {player_lookup}: {e}",
                extra={'player_lookup': player_lookup, 'error': str(e)}
            )
            # Continue without universal_player_id (not critical for predictions)

        # Process player predictions (returns predictions + metadata)
        result = process_player_predictions(
            player_lookup=player_lookup,
            game_date=game_date,
            game_id=game_id,
            line_values=line_values,
            data_loader=data_loader,
            circuit_breaker=circuit_breaker,
            line_source_info=line_source_info,  # v3.2: Pass line source tracking
            historical_games_batch=historical_games_batch  # BATCH OPTIMIZATION: Use pre-loaded data
        )

        predictions = result['predictions']
        metadata = result['metadata']

        if not predictions:
            # Log failure (no predictions generated)
            duration = time.time() - start_time
            execution_logger.log_failure(
                player_lookup=player_lookup,
                universal_player_id=universal_player_id,
                game_date=game_date_str,
                game_id=game_id,
                line_values=line_values,
                duration_seconds=duration,
                error_message=metadata.get('error_message', 'No predictions generated'),
                error_type=metadata.get('error_type', 'UnknownError'),
                skip_reason=metadata.get('skip_reason'),
                systems_attempted=metadata.get('systems_attempted', []),
                systems_failed=metadata.get('systems_failed', []),
                circuit_breaker_triggered=metadata.get('circuit_breaker_triggered', False),
                circuits_opened=metadata.get('circuits_opened', [])
            )

            # P1-PROC-2: Return 500 to trigger Pub/Sub retry instead of 204
            # Empty predictions indicate a transient failure (data not ready, systems failed, etc.)
            # Pub/Sub will retry the message, allowing the worker to succeed on subsequent attempts
            error_reason = metadata.get('skip_reason') or metadata.get('error_type') or 'unknown'
            logger.error(
                f"No predictions generated for {player_lookup} on {game_date_str} - "
                f"returning 500 to trigger Pub/Sub retry. Reason: {error_reason}"
            )
            return ('Empty predictions - triggering retry', 500)

        # Write to BigQuery staging table (consolidation happens later by coordinator)
        write_start = time.time()
        write_predictions_to_bigquery(predictions, batch_id=batch_id, dataset_prefix=dataset_prefix)
        write_duration = time.time() - write_start

        # Publish completion event (include batch_id for Firestore state tracking)
        pubsub_start = time.time()
        publish_completion_event(player_lookup, game_date_str, len(predictions), batch_id=batch_id)
        pubsub_duration = time.time() - pubsub_start

        # Log successful execution
        duration = time.time() - start_time
        performance_breakdown = {
            'data_load': metadata.get('data_load_seconds', 0),
            'prediction_compute': metadata.get('prediction_compute_seconds', 0),
            'write_bigquery': write_duration,
            'pubsub_publish': pubsub_duration
        }

        execution_logger.log_success(
            player_lookup=player_lookup,
            universal_player_id=universal_player_id,
            game_date=game_date_str,
            game_id=game_id,
            line_values=line_values,
            duration_seconds=duration,
            predictions_generated=len(predictions),
            systems_succeeded=metadata.get('systems_succeeded', []),
            systems_failed=metadata.get('systems_failed', []),
            system_errors=metadata.get('system_errors', {}),
            feature_quality_score=metadata.get('feature_quality_score', 0),
            historical_games_count=metadata.get('historical_games_count', 0),
            performance_breakdown=performance_breakdown
        )

        logger.info(f"Successfully generated {len(predictions)} predictions for {player_lookup}")

        return ('', 204)

    except KeyError as e:
        duration = time.time() - start_time
        logger.error(f"Missing required field: {e}")

        # Log failure if we have player info
        if player_lookup:
            execution_logger.log_failure(
                player_lookup=player_lookup,
                universal_player_id=universal_player_id,
                game_date=game_date_str or 'unknown',
                game_id=game_id or 'unknown',
                line_values=line_values,
                duration_seconds=duration,
                error_message=f'Missing required field: {e}',
                error_type='KeyError'
            )

        return (f'Bad Request: missing field {e}', 400)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Error processing prediction request: {e}", exc_info=True)

        # Log failure if we have player info
        if player_lookup:
            execution_logger.log_failure(
                player_lookup=player_lookup,
                universal_player_id=universal_player_id,
                game_date=game_date_str or 'unknown',
                game_id=game_id or 'unknown',
                line_values=line_values,
                duration_seconds=duration,
                error_message=str(e),
                error_type=type(e).__name__
            )

        return ('Internal Server Error', 500)


def process_player_predictions(
    player_lookup: str,
    game_date: date,
    game_id: str,
    line_values: List[float],
    data_loader: 'PredictionDataLoader',
    circuit_breaker: 'SystemCircuitBreaker',
    line_source_info: Dict = None,  # v3.2: Line source tracking
    historical_games_batch: List[Dict] = None  # BATCH OPTIMIZATION: Pre-loaded historical games
) -> Dict:
    """
    Generate predictions for one player across multiple lines

    Process:
    1. Load features (required for ALL systems)
    2. Validate features (NEW - ensure data quality)
    3. Load historical games (required for Similarity + Ensemble)
       - BATCH OPTIMIZATION: Use pre-loaded data if available (50x speedup!)
    4. Call each prediction system (with circuit breaker checks)
    5. Format predictions for BigQuery

    v3.2 CHANGE: Added line_source_info for tracking estimated vs actual lines.
    v3.3 CHANGE: Added historical_games_batch for coordinator-level batch loading (50x speedup).

    Args:
        player_lookup: Player identifier (e.g., 'lebron-james')
        game_date: Game date (date object)
        game_id: Game identifier (e.g., '20251108_LAL_GSW')
        line_values: List of prop lines to test (e.g., [25.5])
        line_source_info: Dict with has_prop_line, line_source, estimated_line_value, estimation_method
        historical_games_batch: Optional pre-loaded historical games from coordinator

    Returns:
        Dict with 'predictions' and 'metadata' keys
    """
    # Default line source info for backwards compatibility
    if line_source_info is None:
        line_source_info = {
            'has_prop_line': True,
            'line_source': 'ACTUAL_PROP',
            'actual_prop_line': None,
            'estimated_line_value': None,
            'estimation_method': None
        }
    # Lazy-load prediction systems
    moving_average, zone_matchup, similarity, xgboost, ensemble = get_prediction_systems()

    all_predictions = []

    # Metadata tracking
    metadata = {
        'systems_attempted': [],
        'systems_succeeded': [],
        'systems_failed': [],
        'system_errors': {},
        'circuit_breaker_triggered': False,
        'circuits_opened': [],
        'feature_quality_score': 0,
        'historical_games_count': 0,
        'data_load_seconds': 0,
        'prediction_compute_seconds': 0
    }

    data_load_start = time.time()

    # Step 1: Load features (REQUIRED for all systems)
    logger.debug(f"Loading features for {player_lookup}")
    feature_load_start = time.time()
    features = data_loader.load_features(player_lookup, game_date)
    feature_load_duration = time.time() - feature_load_start

    if features is None:
        logger.error(f"No features available for {player_lookup} on {game_date}")
        metadata['error_message'] = f'No features available for {player_lookup}'
        metadata['error_type'] = 'FeatureLoadError'
        metadata['skip_reason'] = 'no_features'
        return {'predictions': [], 'metadata': metadata}

    # Step 2: Validate features before running predictions
    # SELF-HEALING: Use tiered quality thresholds
    # - quality >= 70: High confidence (normal)
    # - quality >= 50: Low confidence (proceed with warning)
    # - quality < 50: Skip (too unreliable)
    from data_loaders import validate_features
    quality_score = features.get('feature_quality_score', 0)

    # Use lower threshold (50) but track confidence level
    is_valid, validation_errors = validate_features(features, min_quality_score=50.0)

    if not is_valid:
        logger.error(
            f"Invalid features for {player_lookup} on {game_date}: {validation_errors}"
        )
        metadata['error_message'] = f'Invalid features: {validation_errors}'
        metadata['error_type'] = 'FeatureValidationError'
        metadata['skip_reason'] = 'invalid_features'
        metadata['feature_quality_score'] = quality_score
        return {'predictions': [], 'metadata': metadata}

    # Determine confidence level based on quality score
    if quality_score >= 70:
        confidence_level = 'high'
    elif quality_score >= 50:
        confidence_level = 'low'
        logger.warning(
            f"Low quality features for {player_lookup} ({quality_score:.1f}%) - "
            f"proceeding with low confidence predictions"
        )
    else:
        confidence_level = 'skip'
        logger.warning(f"Quality too low for {player_lookup} ({quality_score:.1f}%) - skipping")
        metadata['skip_reason'] = 'quality_too_low'
        metadata['feature_quality_score'] = quality_score
        return {'predictions': [], 'metadata': metadata}

    metadata['confidence_level'] = confidence_level

    logger.info(f"Features validated for {player_lookup} (quality: {features['feature_quality_score']:.1f})")
    metadata['feature_quality_score'] = features['feature_quality_score']

    # v3.2: Inject line source tracking info into features for format_prediction_for_bigquery
    features['has_prop_line'] = line_source_info.get('has_prop_line', True)
    features['line_source'] = line_source_info.get('line_source', 'ACTUAL_PROP')
    features['actual_prop_line'] = line_source_info.get('actual_prop_line')
    features['estimated_line_value'] = line_source_info.get('estimated_line_value')
    features['estimation_method'] = line_source_info.get('estimation_method')

    # Step 2.5: Check feature completeness (Phase 5)
    # SELF-HEALING: Made more lenient - proceed with warnings instead of blocking
    completeness = features.get('completeness', {})
    metadata['completeness'] = completeness

    # LENIENT: Accept if ANY of these conditions are true:
    # - production_ready flag set
    # - bootstrap_mode flag set
    # - quality score >= 50 (lowered from 70 for self-healing)
    is_acceptable = (
        completeness.get('is_production_ready', False) or
        completeness.get('backfill_bootstrap_mode', False) or
        quality_score >= 50  # Lowered for self-healing (confidence_level tracks actual quality)
    )

    if not is_acceptable:
        logger.warning(
            f"Features not production-ready for {player_lookup} "
            f"(completeness: {completeness.get('completeness_percentage', 0):.1f}%, quality: {quality_score:.1f}) - skipping"
        )
        metadata['error_message'] = (
            f"Features incomplete: {completeness.get('completeness_percentage', 0):.1f}% "
            f"(expected: {completeness.get('expected_games_count', 0)}, "
            f"actual: {completeness.get('actual_games_count', 0)})"
        )
        metadata['error_type'] = 'IncompleFeatureDataError'
        metadata['skip_reason'] = 'features_not_production_ready'
        return {'predictions': [], 'metadata': metadata}

    if completeness.get('backfill_bootstrap_mode', False):
        logger.info(f"Processing {player_lookup} in bootstrap mode (completeness: {completeness.get('completeness_percentage', 0):.1f}%)")

    # Step 3: Load historical games (REQUIRED for Similarity)
    # BATCH OPTIMIZATION: Use pre-loaded data if available (331x speedup!)
    # VERIFIED: Coordinator loads all players in 0.68s vs 225s for sequential individual queries
    historical_load_start = time.time()

    if historical_games_batch is not None:
        # Use pre-loaded batch data from coordinator (0.68s for all players vs 225s total!)
        logger.debug(f"Using pre-loaded historical games for {player_lookup} ({len(historical_games_batch)} games)")
        historical_games = historical_games_batch
    else:
        # Fall back to individual query (original behavior)
        logger.debug(f"Loading historical games for {player_lookup} (individual query)")
        historical_games = data_loader.load_historical_games(player_lookup, game_date)

    historical_load_duration = time.time() - historical_load_start

    if not historical_games:
        logger.warning(f"No historical games found for {player_lookup} - Similarity system will be skipped")
        metadata['historical_games_count'] = 0
    else:
        metadata['historical_games_count'] = len(historical_games)

    metadata['data_load_seconds'] = time.time() - data_load_start


    # Step 4: Generate predictions for each line
    prediction_compute_start = time.time()

    for line_value in line_values:
        logger.debug(f"Generating predictions for {player_lookup} at line {line_value}")

        # Call each prediction system with circuit breaker checks
        system_predictions = {}

        # System 1: Moving Average Baseline
        system_id = 'moving_average'
        metadata['systems_attempted'].append(system_id)
        try:
            # Check circuit breaker
            state, skip_reason = circuit_breaker.check_circuit(system_id)
            if state == 'OPEN':
                logger.warning(f"Circuit breaker OPEN for {system_id}: {skip_reason}")
                metadata['circuit_breaker_triggered'] = True
                metadata['circuits_opened'].append(system_id)
                metadata['systems_failed'].append(system_id)
                metadata['system_errors'][system_id] = f'Circuit breaker open: {skip_reason}'
                system_predictions[system_id] = None
            else:
                pred, conf, rec = moving_average.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=line_value
                )
                # Record success
                circuit_breaker.record_success(system_id)
                metadata['systems_succeeded'].append(system_id)

                system_predictions['moving_average'] = {
                    'predicted_points': pred,
                    'confidence': conf,
                    'recommendation': rec,
                    'system_type': 'tuple'
                }
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"Moving Average failed for {player_lookup}: {e}")
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['moving_average'] = None
        
        # System 2: Zone Matchup V1
        system_id = 'zone_matchup_v1'
        metadata['systems_attempted'].append(system_id)
        try:
            # Check circuit breaker
            state, skip_reason = circuit_breaker.check_circuit(system_id)
            if state == 'OPEN':
                logger.warning(f"Circuit breaker OPEN for {system_id}: {skip_reason}")
                metadata['circuit_breaker_triggered'] = True
                metadata['circuits_opened'].append(system_id)
                metadata['systems_failed'].append(system_id)
                metadata['system_errors'][system_id] = f'Circuit breaker open: {skip_reason}'
                system_predictions[system_id] = None
            else:
                pred, conf, rec = zone_matchup.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=line_value
                )
                # Record success
                circuit_breaker.record_success(system_id)
                metadata['systems_succeeded'].append(system_id)

                system_predictions['zone_matchup_v1'] = {
                    'predicted_points': pred,
                    'confidence': conf,
                    'recommendation': rec,
                    'system_type': 'tuple'
                }
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"Zone Matchup failed for {player_lookup}: {e}")
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['zone_matchup_v1'] = None
        
        # System 3: Similarity Balanced V1 (NEEDS historical_games!)
        system_id = 'similarity_balanced_v1'
        metadata['systems_attempted'].append(system_id)
        try:
            if not historical_games:
                logger.debug(f"Skipping Similarity for {player_lookup} - no historical games")
                metadata['systems_failed'].append(system_id)
                metadata['system_errors'][system_id] = 'No historical games available'
                system_predictions['similarity_balanced_v1'] = None
            else:
                # Check circuit breaker
                state, skip_reason = circuit_breaker.check_circuit(system_id)
                if state == 'OPEN':
                    logger.warning(f"Circuit breaker OPEN for {system_id}: {skip_reason}")
                    metadata['circuit_breaker_triggered'] = True
                    metadata['circuits_opened'].append(system_id)
                    metadata['systems_failed'].append(system_id)
                    metadata['system_errors'][system_id] = f'Circuit breaker open: {skip_reason}'
                    system_predictions[system_id] = None
                else:
                    result = similarity.predict(
                        player_lookup=player_lookup,
                        features=features,
                        historical_games=historical_games,
                        betting_line=line_value
                    )

                    if result['predicted_points'] is not None:
                        # Record success
                        circuit_breaker.record_success(system_id)
                        metadata['systems_succeeded'].append(system_id)

                        system_predictions['similarity_balanced_v1'] = {
                            'predicted_points': result['predicted_points'],
                            'confidence': result['confidence_score'],
                            'recommendation': result['recommendation'],
                            'system_type': 'dict',
                            'metadata': result  # Keep full result for component fields
                        }
                    else:
                        logger.warning(f"Similarity returned None for {player_lookup}")
                        metadata['systems_failed'].append(system_id)
                        metadata['system_errors'][system_id] = 'Prediction returned None'
                        system_predictions['similarity_balanced_v1'] = None
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"Similarity failed for {player_lookup}: {e}")
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['similarity_balanced_v1'] = None
        
        # System 4: CatBoost V8 (replaced XGBoost V1 mock)
        system_id = 'catboost_v8'
        metadata['systems_attempted'].append(system_id)
        try:
            # Check circuit breaker
            state, skip_reason = circuit_breaker.check_circuit(system_id)
            if state == 'OPEN':
                logger.warning(f"Circuit breaker OPEN for {system_id}: {skip_reason}")
                metadata['circuit_breaker_triggered'] = True
                metadata['circuits_opened'].append(system_id)
                metadata['systems_failed'].append(system_id)
                metadata['system_errors'][system_id] = f'Circuit breaker open: {skip_reason}'
                system_predictions[system_id] = None
            else:
                result = xgboost.predict(
                    player_lookup=player_lookup,
                    features=features,
                    betting_line=line_value
                )

                if result['predicted_points'] is not None:
                    # Record success
                    circuit_breaker.record_success(system_id)
                    metadata['systems_succeeded'].append(system_id)

                    system_predictions['catboost_v8'] = {
                        'predicted_points': result['predicted_points'],
                        'confidence': result['confidence_score'],
                        'recommendation': result['recommendation'],
                        'system_type': 'dict',
                        'metadata': result
                    }
                else:
                    logger.warning(f"CatBoost v8 returned None for {player_lookup}")
                    metadata['systems_failed'].append(system_id)
                    metadata['system_errors'][system_id] = 'Prediction returned None'
                    system_predictions['catboost_v8'] = None
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"CatBoost v8 failed for {player_lookup}: {e}")
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['catboost_v8'] = None
        
        # System 5: Ensemble V1 (combines all 4 systems)
        system_id = 'ensemble_v1'
        metadata['systems_attempted'].append(system_id)
        try:
            # Check circuit breaker
            state, skip_reason = circuit_breaker.check_circuit(system_id)
            if state == 'OPEN':
                logger.warning(f"Circuit breaker OPEN for {system_id}: {skip_reason}")
                metadata['circuit_breaker_triggered'] = True
                metadata['circuits_opened'].append(system_id)
                metadata['systems_failed'].append(system_id)
                metadata['system_errors'][system_id] = f'Circuit breaker open: {skip_reason}'
                system_predictions[system_id] = None
            else:
                pred, conf, rec, ensemble_meta = ensemble.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=line_value,
                    historical_games=historical_games if historical_games else None
                )
                # Record success
                circuit_breaker.record_success(system_id)
                metadata['systems_succeeded'].append(system_id)

                system_predictions['ensemble_v1'] = {
                    'predicted_points': pred,
                    'confidence': conf,
                    'recommendation': rec,
                    'system_type': 'tuple',
                    'metadata': ensemble_meta
                }
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"Ensemble failed for {player_lookup}: {e}")
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['ensemble_v1'] = None
        
        # Convert system predictions to BigQuery format
        for system_id, prediction in system_predictions.items():
            if prediction is None:
                continue
            
            # Format prediction for BigQuery
            bq_prediction = format_prediction_for_bigquery(
                system_id=system_id,
                prediction=prediction,
                player_lookup=player_lookup,
                game_id=game_id,
                game_date=game_date,
                line_value=line_value,
                features=features
            )
            
            all_predictions.append(bq_prediction)

    # Track prediction compute time
    metadata['prediction_compute_seconds'] = time.time() - prediction_compute_start

    return {
        'predictions': all_predictions,
        'metadata': metadata
    }


def format_prediction_for_bigquery(
    system_id: str,
    prediction: Dict,
    player_lookup: str,
    game_id: str,
    game_date: date,
    line_value: float,
    features: Dict
) -> Dict:
    """
    Format prediction for BigQuery player_prop_predictions table

    Handles different return formats from different systems

    v3.2 CHANGE (All-Player Predictions):
    - For players WITHOUT prop lines, sets recommendation to 'NO_LINE'
    - current_points_line and line_margin are NULL for NO_LINE players
    - has_prop_line flag indicates whether player had a betting line

    Args:
        system_id: System identifier
        prediction: Prediction dict from system
        player_lookup: Player identifier
        game_id: Game identifier
        game_date: Game date
        line_value: Prop line value (may be estimated for NO_LINE players)
        features: Feature dict (for quality score)

    Returns:
        Dict formatted for BigQuery insertion
    """
    from data_loaders import normalize_confidence
    player_registry = get_player_registry()

    # Lookup universal player ID from registry
    universal_player_id = None
    try:
        universal_player_id = player_registry.get_universal_id(
            player_lookup,
            required=False  # Graceful degradation
        )

        if universal_player_id is None:
            logger.warning(f"No universal_player_id found for {player_lookup}")
            # Still proceed - universal_player_id is optional
    except Exception as e:
        logger.error(f"Error looking up universal_player_id for {player_lookup}: {e}")
        # Still proceed with None value

    # Check if player has a prop line (v3.2 - All-Player Predictions)
    has_prop_line = features.get('has_prop_line', True)  # Default True for backwards compatibility

    # Get line source tracking info (v3.2)
    line_source = features.get('line_source', 'ACTUAL_PROP')
    estimated_line_value = features.get('estimated_line_value')
    estimation_method = features.get('estimation_method')
    actual_prop_line = features.get('actual_prop_line')

    # Determine recommendation and line values based on has_prop_line
    if has_prop_line:
        # Player has prop line - use normal recommendation
        recommendation = prediction['recommendation']
        current_points_line = round(actual_prop_line if actual_prop_line else line_value, 1)
        line_margin = round(prediction['predicted_points'] - current_points_line, 2)
    else:
        # Player does NOT have prop line - set NO_LINE recommendation
        recommendation = 'NO_LINE'
        current_points_line = None  # No actual betting line
        line_margin = None  # Can't calculate margin without line

    # Base record
    record = {
        'prediction_id': str(uuid.uuid4()),
        'system_id': system_id,
        'player_lookup': player_lookup,
        'universal_player_id': universal_player_id,  # Now populated!
        'game_date': game_date.isoformat(),
        'game_id': game_id,
        'prediction_version': 1,

        # Core prediction (v3.2: has_prop_line and NO_LINE handling)
        'predicted_points': round(prediction['predicted_points'], 1),
        'confidence_score': round(normalize_confidence(prediction['confidence'], system_id), 2),
        'recommendation': recommendation,
        'has_prop_line': has_prop_line,

        # Context (v3.2: NULL for NO_LINE players)
        'current_points_line': current_points_line,
        'line_margin': line_margin,

        # Line source tracking (v3.2: Track what line was used for prediction)
        'line_source': line_source,  # 'ACTUAL_PROP' or 'ESTIMATED_AVG'
        'estimated_line_value': round(estimated_line_value, 1) if estimated_line_value else None,
        'estimation_method': estimation_method,  # 'points_avg_last_5', 'points_avg_last_10', 'default_15.5'

        # Status
        'is_active': True,
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': None,
        'superseded_by': None
    }
    
    # Add system-specific fields
    if system_id == 'similarity_balanced_v1' and 'metadata' in prediction:
        metadata = prediction['metadata']
        adjustments = metadata.get('adjustments', {})
        
        record.update({
            'similarity_baseline': metadata.get('baseline_from_similar'),
            'similar_games_count': metadata.get('similar_games_count'),
            'avg_similarity_score': metadata.get('avg_similarity_score'),
            'min_similarity_score': None,  # Not provided by current system
            'fatigue_adjustment': adjustments.get('fatigue'),
            'shot_zone_adjustment': adjustments.get('zone_matchup'),
            'pace_adjustment': adjustments.get('pace'),
            'usage_spike_adjustment': adjustments.get('usage'),
            'home_away_adjustment': adjustments.get('venue')
        })
    
    elif system_id == 'catboost_v8' and 'metadata' in prediction:
        metadata = prediction['metadata']
        record.update({
            'model_version': metadata.get('model_version', 'catboost_v8'),
            'feature_importance': json.dumps({
                'model_type': metadata.get('model_type'),
                'feature_count': metadata.get('feature_count', 33),
            }) if metadata.get('model_type') else None
        })
    
    elif system_id == 'ensemble_v1' and 'metadata' in prediction:
        metadata = prediction['metadata']
        agreement = metadata.get('agreement', {})

        # Store ensemble metadata in feature_importance as JSON (schema-compatible)
        record.update({
            'feature_importance': json.dumps({
                'variance': agreement.get('variance'),
                'agreement_percentage': agreement.get('agreement_percentage'),
                'systems_used': metadata.get('systems_used'),
                'predictions': metadata.get('predictions'),
                'agreement_type': agreement.get('type')
            }),
            'model_version': 'ensemble_v1'
        })

    # Add completeness metadata (Phase 5)
    completeness = features.get('completeness', {})

    # Convert data_quality_issues list to JSON string (schema expects STRING)
    data_quality_issues = completeness.get('data_quality_issues', [])
    if isinstance(data_quality_issues, list):
        data_quality_issues = json.dumps(data_quality_issues) if data_quality_issues else None

    record.update({
        'expected_games_count': completeness.get('expected_games_count'),
        'actual_games_count': completeness.get('actual_games_count'),
        'completeness_percentage': completeness.get('completeness_percentage', 0.0),
        'missing_games_count': completeness.get('missing_games_count'),
        'is_production_ready': completeness.get('is_production_ready', False),
        'data_quality_issues': data_quality_issues,
        'last_reprocess_attempt_at': None,  # Not tracked at worker level
        'reprocess_attempt_count': 0,  # Not tracked at worker level
        'circuit_breaker_active': False,  # Not tracked at worker level
        'circuit_breaker_until': None,  # Not tracked at worker level
        'manual_override_required': False,  # Not tracked at worker level
        'season_boundary_detected': False,  # Not tracked at worker level
        'backfill_bootstrap_mode': completeness.get('backfill_bootstrap_mode', False),
        'processing_decision_reason': completeness.get('processing_decision_reason', 'processed_successfully')
    })

    return record


def write_predictions_to_bigquery(predictions: List[Dict], batch_id: Optional[str] = None, dataset_prefix: str = ''):
    """
    Write predictions to a batch staging table for later consolidation.

    Uses the BatchStagingWriter to avoid DML concurrency limits:
    - Each worker writes to its own staging table using batch INSERT (not DML)
    - The coordinator consolidates all staging tables with a single MERGE later
    - This eliminates "Too many DML statements" errors with 20+ concurrent workers

    Args:
        predictions: List of prediction dicts
        batch_id: Unique identifier for the batch (from coordinator).
                  If not provided, generates a fallback batch_id.
        dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")
    """
    from batch_staging_writer import get_worker_id, BatchStagingWriter

    if not predictions:
        logger.warning("No predictions to write")
        return

    # Track write metrics
    write_start_time = time.time()
    player_lookup = predictions[0].get('player_lookup', 'unknown') if predictions else 'unknown'
    records_count = len(predictions)

    # Get batch_id (from coordinator message) or generate fallback
    if not batch_id:
        # Fallback for backwards compatibility or direct calls
        batch_id = f"fallback_{int(time.time() * 1000)}"
        logger.warning(f"No batch_id provided, using fallback: {batch_id}")

    # Get unique worker ID for this instance
    worker_id = get_worker_id()

    try:
        # DATASET ISOLATION: Create staging writer with dataset_prefix if specified
        # Otherwise use the cached global writer for production
        if dataset_prefix:
            staging_writer = BatchStagingWriter(get_bq_client(), PROJECT_ID, dataset_prefix=dataset_prefix)
            logger.debug(f"Created isolated staging_writer with prefix: {dataset_prefix}")
        else:
            staging_writer = get_staging_writer()  # Use cached production writer

        # Write to staging table (NOT a DML operation - no concurrency limits)
        result = staging_writer.write_to_staging(
            predictions=predictions,
            batch_id=batch_id,
            worker_id=worker_id
        )

        if result.success:
            logger.info(
                f"Staging write complete: {result.rows_written} rows to {result.staging_table_name} "
                f"(batch={batch_id}, worker={worker_id})"
            )

            # Track successful write
            write_duration = time.time() - write_start_time
            PredictionWriteMetrics.track_write_attempt(
                player_lookup=player_lookup,
                records_count=records_count,
                success=True,
                duration_seconds=write_duration
            )
        else:
            # Staging write failed
            write_duration = time.time() - write_start_time
            logger.error(f"Staging write failed: {result.error_message}")

            PredictionWriteMetrics.track_write_attempt(
                player_lookup=player_lookup,
                records_count=records_count,
                success=False,
                duration_seconds=write_duration,
                error_type='StagingWriteError'
            )

    except Exception as e:
        write_duration = time.time() - write_start_time
        error_message = str(e)
        logger.error(f"Error writing to staging: {e}")

        # Track write failure
        PredictionWriteMetrics.track_write_attempt(
            player_lookup=player_lookup,
            records_count=records_count,
            success=False,
            duration_seconds=write_duration,
            error_type=type(e).__name__
        )
        # Don't raise - log and continue (graceful degradation)


def publish_completion_event(player_lookup: str, game_date: str, prediction_count: int, batch_id: str = None):
    """
    Publish prediction-ready event to Pub/Sub

    Notifies downstream systems that predictions are available

    Args:
        player_lookup: Player identifier
        game_date: Game date string
        prediction_count: Number of predictions generated
        batch_id: Batch identifier (REQUIRED for Firestore state tracking)
    """
    pubsub_publisher = get_pubsub_publisher()
    topic_path = pubsub_publisher.topic_path(PROJECT_ID, PUBSUB_READY_TOPIC)
    
    message_data = {
        'player_lookup': player_lookup,
        'game_date': game_date,
        'predictions_generated': prediction_count,
        'batch_id': batch_id,  # Critical for Firestore state persistence!
        'timestamp': datetime.utcnow().isoformat(),
        'worker_instance': os.environ.get('K_REVISION', 'unknown')
    }
    
    try:
        message_bytes = json.dumps(message_data).encode('utf-8')
        future = pubsub_publisher.publish(topic_path, data=message_bytes)
        future.result()  # Wait for publish to complete
        logger.debug(f"Published completion event for {player_lookup}")
    except Exception as e:
        logger.error(f"Error publishing completion event: {e}")
        # Don't raise - log and continue


if __name__ == '__main__':
    # For local testing
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)