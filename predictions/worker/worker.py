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
from typing import Dict, List, Optional, TYPE_CHECKING
from datetime import datetime, date
import uuid
import base64
import time
logger.info("✓ Standard library imports completed")

# Defer google.cloud imports to lazy loading functions to avoid cold start hang
if TYPE_CHECKING:
    from google.cloud import bigquery, pubsub_v1
logger.info("✓ Google Cloud client imports deferred (will lazy-load)")

# Import prediction systems
from prediction_systems.moving_average_baseline import MovingAverageBaseline
logger.info("✓ MovingAverageBaseline imported")

from prediction_systems.zone_matchup_v1 import ZoneMatchupV1
logger.info("✓ ZoneMatchupV1 imported")

from prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
logger.info("✓ SimilarityBalancedV1 imported")

from prediction_systems.xgboost_v1 import XGBoostV1
logger.info("✓ XGBoostV1 imported")

from prediction_systems.ensemble_v1 import EnsembleV1
logger.info("✓ EnsembleV1 imported")

# Import data loader
from data_loaders import PredictionDataLoader, normalize_confidence, validate_features
logger.info("✓ Data loaders imported")

# Pattern imports (Week 1 - Foundation Patterns)
from system_circuit_breaker import SystemCircuitBreaker
logger.info("✓ SystemCircuitBreaker imported")

from execution_logger import ExecutionLogger
logger.info("✓ ExecutionLogger imported")

# Import player registry for universal_player_id lookup
# Note: PYTHONPATH is set to /app in Dockerfile, so imports work correctly
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError
logger.info("✓ Player registry imported")

# Flask app
app = Flask(__name__)
logger.info("✓ Flask app created")

# Environment configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
PREDICTIONS_TABLE = os.environ.get('PREDICTIONS_TABLE', 'nba_predictions.player_prop_predictions')
PUBSUB_READY_TOPIC = os.environ.get('PUBSUB_READY_TOPIC', 'prediction-ready')
logger.info("✓ Environment configuration loaded")

# Lazy-loaded components (initialized on first request to avoid cold start timeout)
_data_loader: Optional[PredictionDataLoader] = None
_bq_client: Optional['bigquery.Client'] = None
_pubsub_publisher: Optional['pubsub_v1.PublisherClient'] = None
_player_registry: Optional[RegistryReader] = None
_moving_average: Optional[MovingAverageBaseline] = None
_zone_matchup: Optional[ZoneMatchupV1] = None
_similarity: Optional[SimilarityBalancedV1] = None
_xgboost: Optional[XGBoostV1] = None
_ensemble: Optional[EnsembleV1] = None

def get_data_loader() -> PredictionDataLoader:
    """Lazy-load data loader on first use"""
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
        _bq_client = bigquery.Client(project=PROJECT_ID)
        logger.info("BigQuery client initialized")
    return _bq_client

def get_pubsub_publisher() -> 'pubsub_v1.PublisherClient':
    """Lazy-load Pub/Sub publisher on first use"""
    from google.cloud import pubsub_v1
    global _pubsub_publisher
    if _pubsub_publisher is None:
        logger.info("Initializing Pub/Sub publisher...")
        _pubsub_publisher = pubsub_v1.PublisherClient()
        logger.info("Pub/Sub publisher initialized")
    return _pubsub_publisher

def get_player_registry() -> RegistryReader:
    """Lazy-load player registry on first use"""
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
    global _moving_average, _zone_matchup, _similarity, _xgboost, _ensemble
    if _ensemble is None:
        logger.info("Initializing prediction systems...")
        _moving_average = MovingAverageBaseline()
        _zone_matchup = ZoneMatchupV1()
        _similarity = SimilarityBalancedV1()
        _xgboost = XGBoostV1()
        _ensemble = EnsembleV1(
            moving_average_system=_moving_average,
            zone_matchup_system=_zone_matchup,
            similarity_system=_similarity,
            xgboost_system=_xgboost
        )
        logger.info("All prediction systems initialized")
    return _moving_average, _zone_matchup, _similarity, _xgboost, _ensemble

_circuit_breaker: Optional[SystemCircuitBreaker] = None
_execution_logger: Optional[ExecutionLogger] = None

def get_circuit_breaker() -> SystemCircuitBreaker:
    """Lazy-load circuit breaker on first use"""
    global _circuit_breaker
    if _circuit_breaker is None:
        logger.info("Initializing SystemCircuitBreaker...")
        _circuit_breaker = SystemCircuitBreaker(get_bq_client(), PROJECT_ID)
        logger.info("SystemCircuitBreaker initialized")
    return _circuit_breaker

def get_execution_logger() -> ExecutionLogger:
    """Lazy-load execution logger on first use"""
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

    # Lazy-load all components on first request
    data_loader = get_data_loader()
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

        logger.info(f"Processing prediction request: {request_data.get('player_lookup')} on {request_data.get('game_date')}")

        # Extract request parameters
        player_lookup = request_data['player_lookup']
        game_date_str = request_data['game_date']
        game_id = request_data['game_id']
        line_values = request_data.get('line_values', [])

        # Convert date string to date object
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        # Get universal player ID
        try:
            universal_player_id = player_registry.get_universal_id(player_lookup, required=False)
        except:
            pass

        # Process player predictions (returns predictions + metadata)
        result = process_player_predictions(
            player_lookup=player_lookup,
            game_date=game_date,
            game_id=game_id,
            line_values=line_values
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

            logger.warning(f"No predictions generated for {player_lookup}")
            return ('', 204)  # Still return success (graceful degradation)

        # Write to BigQuery
        write_start = time.time()
        write_predictions_to_bigquery(predictions)
        write_duration = time.time() - write_start

        # Publish completion event
        pubsub_start = time.time()
        publish_completion_event(player_lookup, game_date_str, len(predictions))
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
    line_values: List[float]
) -> Dict:
    """
    Generate predictions for one player across multiple lines

    Process:
    1. Load features (required for ALL systems)
    2. Validate features (NEW - ensure data quality)
    3. Load historical games (required for Similarity + Ensemble)
    4. Call each prediction system (with circuit breaker checks)
    5. Format predictions for BigQuery

    Args:
        player_lookup: Player identifier (e.g., 'lebron-james')
        game_date: Game date (date object)
        game_id: Game identifier (e.g., '20251108_LAL_GSW')
        line_values: List of prop lines to test (e.g., [25.5])

    Returns:
        Dict with 'predictions' and 'metadata' keys
    """
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
    is_valid, validation_errors = validate_features(features, min_quality_score=70.0)
    if not is_valid:
        logger.error(
            f"Invalid features for {player_lookup} on {game_date}: {validation_errors}"
        )
        metadata['error_message'] = f'Invalid features: {validation_errors}'
        metadata['error_type'] = 'FeatureValidationError'
        metadata['skip_reason'] = 'invalid_features'
        metadata['feature_quality_score'] = features.get('feature_quality_score', 0)
        return {'predictions': [], 'metadata': metadata}

    logger.info(f"Features validated for {player_lookup} (quality: {features['feature_quality_score']:.1f})")
    metadata['feature_quality_score'] = features['feature_quality_score']

    # Step 2.5: Check feature completeness (Phase 5)
    completeness = features.get('completeness', {})
    metadata['completeness'] = completeness

    if not completeness.get('is_production_ready', False) and not completeness.get('backfill_bootstrap_mode', False):
        logger.warning(
            f"Features not production-ready for {player_lookup} "
            f"(completeness: {completeness.get('completeness_percentage', 0):.1f}%) - skipping"
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
    logger.debug(f"Loading historical games for {player_lookup}")
    historical_load_start = time.time()
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
        
        # System 4: XGBoost V1
        system_id = 'xgboost_v1'
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

                    system_predictions['xgboost_v1'] = {
                        'predicted_points': result['predicted_points'],
                        'confidence': result['confidence_score'],
                        'recommendation': result['recommendation'],
                        'system_type': 'dict',
                        'metadata': result
                    }
                else:
                    logger.warning(f"XGBoost returned None for {player_lookup}")
                    metadata['systems_failed'].append(system_id)
                    metadata['system_errors'][system_id] = 'Prediction returned None'
                    system_predictions['xgboost_v1'] = None
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"XGBoost failed for {player_lookup}: {e}")
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['xgboost_v1'] = None
        
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
    
    Args:
        system_id: System identifier
        prediction: Prediction dict from system
        player_lookup: Player identifier
        game_id: Game identifier
        game_date: Game date
        line_value: Prop line value
        features: Feature dict (for quality score)
    
    Returns:
        Dict formatted for BigQuery insertion
    """
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
    
    # Base record
    record = {
        'prediction_id': str(uuid.uuid4()),
        'system_id': system_id,
        'player_lookup': player_lookup,
        'universal_player_id': universal_player_id,  # Now populated!
        'game_date': game_date.isoformat(),
        'game_id': game_id,
        'prediction_version': 1,
        
        # Core prediction
        'predicted_points': round(prediction['predicted_points'], 1),
        'confidence_score': round(normalize_confidence(prediction['confidence'], system_id), 2),
        'recommendation': prediction['recommendation'],
        
        # Context
        'current_points_line': round(line_value, 1),
        'line_margin': round(prediction['predicted_points'] - line_value, 2),
        
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
    
    elif system_id == 'xgboost_v1' and 'metadata' in prediction:
        metadata = prediction['metadata']
        record.update({
            'ml_model_id': metadata.get('model_version', 'v1')
        })
    
    elif system_id == 'ensemble_v1' and 'metadata' in prediction:
        metadata = prediction['metadata']
        agreement = metadata.get('agreement', {})
        
        record.update({
            'prediction_variance': agreement.get('variance'),
            'system_agreement_score': agreement.get('agreement_percentage'),
            'contributing_systems': metadata.get('systems_used'),
            'key_factors': json.dumps({
                'systems': metadata.get('predictions'),
                'agreement_type': agreement.get('type')
            })
        })

    # Add completeness metadata (Phase 5)
    completeness = features.get('completeness', {})
    record.update({
        'expected_games_count': completeness.get('expected_games_count'),
        'actual_games_count': completeness.get('actual_games_count'),
        'completeness_percentage': completeness.get('completeness_percentage', 0.0),
        'missing_games_count': completeness.get('missing_games_count'),
        'is_production_ready': completeness.get('is_production_ready', False),
        'data_quality_issues': completeness.get('data_quality_issues', []),
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


def write_predictions_to_bigquery(predictions: List[Dict]):
    """
    Write predictions to BigQuery player_prop_predictions table
    
    Uses streaming insert for low latency
    
    Args:
        predictions: List of prediction dicts
    """
    if not predictions:
        logger.warning("No predictions to write")
        return
    
    table_id = f"{PROJECT_ID}.{PREDICTIONS_TABLE}"
    
    try:
        errors = bq_client.insert_rows_json(table_id, predictions)
        
        if errors:
            logger.error(f"Errors writing to BigQuery: {errors}")
            # Don't raise - log and continue (graceful degradation)
        else:
            logger.info(f"Successfully wrote {len(predictions)} predictions to BigQuery")
            
    except Exception as e:
        logger.error(f"Error writing to BigQuery: {e}")
        # Don't raise - log and continue


def publish_completion_event(player_lookup: str, game_date: str, prediction_count: int):
    """
    Publish prediction-ready event to Pub/Sub
    
    Notifies downstream systems that predictions are available
    
    Args:
        player_lookup: Player identifier
        game_date: Game date string
        prediction_count: Number of predictions generated
    """
    topic_path = pubsub_publisher.topic_path(PROJECT_ID, PUBSUB_READY_TOPIC)
    
    message_data = {
        'player_lookup': player_lookup,
        'game_date': game_date,
        'predictions_generated': prediction_count,
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