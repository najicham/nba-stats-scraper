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
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
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

# Session 64: Build tracking for debugging hit rate issues
# These enable fast investigation by filtering predictions by code version
BUILD_COMMIT_SHA = os.environ.get('BUILD_COMMIT', 'unknown')
DEPLOYMENT_REVISION = os.environ.get('K_REVISION', 'unknown')
logger.info(f"✓ Build tracking: commit={BUILD_COMMIT_SHA[:8] if BUILD_COMMIT_SHA != 'unknown' else 'unknown'}, revision={DEPLOYMENT_REVISION}")


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
            # CRITICAL: No model available - FAIL FAST (Session 40: no silent fallbacks)
            error_msg = (
                f"CRITICAL: No CatBoost V8 model available! "
                f"Searched: {models_dir}/catboost_v8_33features_*.cbm. "
                f"Set CATBOOST_V8_MODEL_PATH environment variable to a valid model path. "
                f"Example: gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_YYYYMMDD_HHMMSS.cbm"
            )
            logger.critical(
                error_msg,
                extra={
                    "severity": "CRITICAL",
                    "alert_type": "model_not_available",
                    "model_id": "catboost_v8",
                    "searched_path": str(models_dir),
                }
            )
            raise RuntimeError(error_msg)
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
    from prediction_systems.catboost_v8 import CatBoostV8  # v8 ML model (historical)
    from prediction_systems.catboost_v9 import CatBoostV9  # v9 ML model (current season)
    from prediction_systems.catboost_monthly import CatBoostMonthly  # monthly retrained models
    from prediction_systems.ensemble_v1 import EnsembleV1
    from prediction_systems.ensemble_v1_1 import EnsembleV1_1
    from data_loaders import PredictionDataLoader, normalize_confidence, validate_features
    from system_circuit_breaker import SystemCircuitBreaker
    from execution_logger import ExecutionLogger
    from shared.utils.player_registry import RegistryReader, PlayerNotFoundError
    from batch_staging_writer import BatchStagingWriter, get_worker_id
    from predictions.shared.injury_filter import InjuryFilter, InjuryStatus, DNPHistory

from predictions.worker.write_metrics import PredictionWriteMetrics
from shared.utils.bigquery_retry import retry_on_quota_exceeded

logger.info("✓ Heavy imports deferred (will lazy-load on first request)")

# Flask app
app = Flask(__name__)
logger.info("✓ Flask app created")

# Environment configuration
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
PREDICTIONS_TABLE = os.environ.get('PREDICTIONS_TABLE', 'nba_predictions.player_prop_predictions')
PUBSUB_READY_TOPIC = os.environ.get('PUBSUB_READY_TOPIC', 'prediction-ready')
# CatBoost model version: 'v8' (historical training) or 'v9' (current season)
CATBOOST_VERSION = os.environ.get('CATBOOST_VERSION', 'v9')  # Default to V9 (Session 67)
CATBOOST_SYSTEM_ID = f'catboost_{CATBOOST_VERSION}'  # e.g., 'catboost_v9' or 'catboost_v8'
logger.info(f"✓ Environment configuration loaded (CATBOOST_VERSION={CATBOOST_VERSION}, SYSTEM_ID={CATBOOST_SYSTEM_ID})")

# Failure Classification for Retry Logic
# Permanent failures - data won't appear on retry, ack message immediately
PERMANENT_SKIP_REASONS = {
    'no_features',           # Player not in ml_feature_store_v2
    'player_not_found',      # Invalid player_lookup
    'no_prop_lines',         # No betting lines scraped for player
    'game_not_found',        # Game doesn't exist in schedule
    'player_inactive',       # Player not active/playing
    'no_historical_data',    # No historical games for player
}

# Transient failures - might resolve on retry, return 500 to trigger Pub/Sub retry
TRANSIENT_SKIP_REASONS = {
    'feature_store_timeout', # Temporary BigQuery connectivity
    'model_load_error',      # Model loading failed temporarily
    'bigquery_timeout',      # Temporary BQ query timeout
    'rate_limited',          # External API rate limit
    'circuit_breaker_open',  # All systems tripped, might recover
}
logger.info("✓ Failure classification loaded")

# Lazy-loaded components (initialized on first request to avoid cold start timeout)
_data_loader: Optional['PredictionDataLoader'] = None
_bq_client: Optional['bigquery.Client'] = None
_pubsub_publisher: Optional['pubsub_v1.PublisherClient'] = None
_player_registry: Optional['RegistryReader'] = None
_moving_average: Optional['MovingAverageBaseline'] = None
_zone_matchup: Optional['ZoneMatchupV1'] = None
_similarity: Optional['SimilarityBalancedV1'] = None
_xgboost: Optional['XGBoostV1'] = None
_catboost: Optional['CatBoostV8'] = None
_ensemble: Optional['EnsembleV1'] = None
_ensemble_v1_1: Optional['EnsembleV1_1'] = None
_monthly_models: Optional[list] = None  # List of CatBoostMonthly instances
_staging_writer: Optional['BatchStagingWriter'] = None
_injury_filter: Optional['InjuryFilter'] = None

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
    """Lazy-load BigQuery client on first use via pool"""
    from shared.clients import get_bigquery_client
    global _bq_client
    if _bq_client is None:
        logger.info("Initializing BigQuery client via pool...")
        _bq_client = get_bigquery_client(PROJECT_ID)
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
    """Lazy-load Pub/Sub publisher on first use via pool"""
    from shared.clients import get_pubsub_publisher as get_pooled_publisher
    global _pubsub_publisher
    if _pubsub_publisher is None:
        logger.info("Initializing Pub/Sub publisher via pool...")
        _pubsub_publisher = get_pooled_publisher()
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


def get_injury_filter() -> 'InjuryFilter':
    """Lazy-load injury filter on first use"""
    from predictions.shared.injury_filter import InjuryFilter
    global _injury_filter
    if _injury_filter is None:
        logger.info("Initializing InjuryFilter...")
        _injury_filter = InjuryFilter(project_id=PROJECT_ID)
        logger.info("InjuryFilter initialized")
    return _injury_filter

def get_prediction_systems() -> tuple:
    """Lazy-load all prediction systems on first use"""
    from prediction_systems.moving_average_baseline import MovingAverageBaseline
    from prediction_systems.zone_matchup_v1 import ZoneMatchupV1
    from prediction_systems.similarity_balanced_v1 import SimilarityBalancedV1
    from prediction_systems.xgboost_v1 import XGBoostV1
    from prediction_systems.catboost_v8 import CatBoostV8
    from prediction_systems.catboost_v9 import CatBoostV9
    from prediction_systems.catboost_monthly import get_enabled_monthly_models
    from prediction_systems.ensemble_v1 import EnsembleV1
    from prediction_systems.ensemble_v1_1 import EnsembleV1_1

    global _moving_average, _zone_matchup, _similarity, _xgboost, _catboost, _ensemble, _ensemble_v1_1, _monthly_models
    if _ensemble is None:
        logger.info("Initializing prediction systems...")
        _moving_average = MovingAverageBaseline()
        _zone_matchup = ZoneMatchupV1()
        _similarity = SimilarityBalancedV1()
        _xgboost = XGBoostV1()  # Mock XGBoost V1 (baseline)

        # Load CatBoost model based on CATBOOST_VERSION env var
        if CATBOOST_VERSION == 'v9':
            logger.info("Loading CatBoost V9 (current season training)...")
            _catboost = CatBoostV9()  # CatBoost v9: 4.82 MAE (Session 67)
        else:
            logger.info("Loading CatBoost V8 (historical training)...")
            _catboost = CatBoostV8()  # CatBoost v8: 5.36 MAE

        # Load monthly models (Session 68)
        logger.info("Loading monthly models...")
        _monthly_models = get_enabled_monthly_models()
        if _monthly_models:
            logger.info(f"Loaded {len(_monthly_models)} monthly model(s): {[m.model_id for m in _monthly_models]}")
        else:
            logger.info("No monthly models enabled")

        _ensemble = EnsembleV1(
            moving_average_system=_moving_average,
            zone_matchup_system=_zone_matchup,
            similarity_system=_similarity,
            xgboost_system=_catboost  # Ensemble uses champion (CatBoost)
        )
        _ensemble_v1_1 = EnsembleV1_1(
            moving_average_system=_moving_average,
            zone_matchup_system=_zone_matchup,
            similarity_system=_similarity,
            xgboost_system=_xgboost,
            catboost_system=_catboost
        )
        catboost_version = "V9" if CATBOOST_VERSION == 'v9' else "V8"
        monthly_count = len(_monthly_models) if _monthly_models else 0
        total_systems = 7 + monthly_count
        logger.info(f"All prediction systems initialized ({total_systems} systems: XGBoost V1, CatBoost {catboost_version}, {monthly_count} monthly models, Ensemble V1, Ensemble V1.1, + 3 others)")
    return _moving_average, _zone_matchup, _similarity, _xgboost, _catboost, _ensemble, _ensemble_v1_1

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


# Session 103: Tier calibration helper functions
# These compute metadata WITHOUT modifying the raw prediction
# Calibration can be applied at query time: predicted_points + tier_adjustment

def _compute_scoring_tier(points_avg_season: float) -> str:
    """
    Determine player scoring tier based on season average.

    Tiers match the regression-to-mean bias analysis:
    - Stars (25+ avg): Model tends to under-predict
    - Starters (15-24 avg): Model slightly under-predicts
    - Role (5-14 avg): Model slightly over-predicts
    - Bench (<5 avg): Model tends to over-predict
    """
    if points_avg_season >= 25:
        return 'star'
    elif points_avg_season >= 15:
        return 'starter'
    elif points_avg_season >= 5:
        return 'role'
    else:
        return 'bench'


def _compute_tier_adjustment(points_avg_season: float) -> float:
    """
    Compute suggested calibration adjustment for tier bias.

    Based on measured bias from prediction_accuracy (14-day window Feb 2026):
    - Stars (25+): Model under-predicts by ~9 pts → suggest +9.0
    - Starters (15-24): Model under-predicts by ~3 pts → suggest +3.0
    - Role (5-14): Model over-predicts by ~1.5 pts → suggest -1.5
    - Bench (<5): Model over-predicts by ~5.5 pts → suggest -5.5

    Returns the adjustment to ADD to predicted_points if applying calibration.
    Raw prediction stays unchanged; this is metadata only.
    """
    if points_avg_season >= 25:  # Stars
        return 9.0
    elif points_avg_season >= 15:  # Starters
        return 3.0
    elif points_avg_season >= 5:  # Role players
        return -1.5
    else:  # Bench players
        return -5.5


# Session 112: Player blacklist for UNDER bets (verified hit rates < 50%)
UNDER_BLACKLIST_PLAYERS = {
    'lukadoncic',      # 45.5% UNDER hit rate
    'juliusrandle',    # 42.9% UNDER hit rate
    'jarenjacksonjr',  # 28.6% UNDER hit rate
    'lamellobald',     # 44.4% UNDER hit rate (note: might be lameloBall in registry)
    'dillonbrooks',    # 40.0% UNDER hit rate
    'michaelporterjr', # 40.0% UNDER hit rate
}

# Session 112: Risky opponents for UNDER bets (hit rates < 40%)
UNDER_RISK_OPPONENTS = {'PHI', 'MIN', 'DET', 'MIA', 'DEN'}


def _classify_scenario(
    recommendation: str,
    line_value: float,
    predicted_points: float,
    player_lookup: str = None,
    opponent_tricode: str = None
) -> tuple:
    """
    Classify a prediction into a betting scenario.

    Session 112 validated scenarios:
    - optimal_over: OVER + line < 12 + edge >= 5 (87.3% HR)
    - optimal_under: UNDER + line >= 25 + edge >= 3 (70.7% HR)
    - ultra_high_edge_over: OVER + edge >= 7 (88.5% HR)
    - under_safe: UNDER + line >= 20 + edge >= 3 + not blacklisted (65% HR)
    - anti_under_low_line: UNDER + line < 15 + edge >= 3 (53.8% HR - AVOID)
    - standard: Everything else with edge >= 3
    - low_edge: Edge < 3 (51.5% HR - SKIP)

    Returns:
        tuple: (scenario_category, scenario_flags_dict)
    """
    if line_value is None or predicted_points is None:
        return ('unknown', {'reason': 'missing_line_or_prediction'})

    edge = abs(predicted_points - line_value)
    flags = {
        'edge': round(edge, 1),
        'line_value': round(line_value, 1),
    }

    # Check blacklist and opponent risk for UNDER bets
    is_blacklisted = False
    is_risky_opponent = False

    if recommendation == 'UNDER':
        if player_lookup and player_lookup.lower().replace(' ', '').replace("'", "") in UNDER_BLACKLIST_PLAYERS:
            is_blacklisted = True
            flags['blacklisted_player'] = True

        if opponent_tricode and opponent_tricode.upper() in UNDER_RISK_OPPONENTS:
            is_risky_opponent = True
            flags['risky_opponent'] = True

    # Classify into scenario
    if edge < 3:
        return ('low_edge', flags)

    if recommendation == 'OVER':
        if line_value < 12 and edge >= 5:
            return ('optimal_over', flags)
        elif edge >= 7:
            return ('ultra_high_edge_over', flags)
        elif edge >= 5:
            return ('high_edge_over', flags)
        else:
            return ('standard_over', flags)

    elif recommendation == 'UNDER':
        if line_value < 15:
            flags['anti_pattern'] = 'low_line_under'
            return ('anti_under_low_line', flags)
        elif line_value >= 25 and edge >= 3 and not is_blacklisted:
            return ('optimal_under', flags)
        elif line_value >= 20 and not is_blacklisted and not is_risky_opponent:
            return ('under_safe', flags)
        elif is_blacklisted or is_risky_opponent:
            return ('under_risky', flags)
        else:
            return ('standard_under', flags)

    else:  # PASS, NO_LINE, etc.
        return ('non_actionable', flags)


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
            'xgboost_v1': str(_xgboost),
            CATBOOST_SYSTEM_ID: str(_catboost),
            'ensemble': str(_ensemble),
            'ensemble_v1_1': str(_ensemble_v1_1)
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


def validate_line_quality(predictions: List[Dict], player_lookup: str, game_date_str: str) -> Tuple[bool, Optional[str]]:
    """
    PHASE 1 FIX: Validate line quality before BigQuery write.

    Blocks placeholder lines (20.0) from entering the database.
    This is the last line of defense against data corruption.

    Args:
        predictions: List of prediction dicts to validate
        player_lookup: Player identifier for error messages
        game_date_str: Game date for error messages

    Returns:
        (is_valid, error_message) - False if validation fails
    """
    placeholder_count = 0
    issues = []

    for pred in predictions:
        line_value = pred.get('current_points_line')
        line_source = pred.get('line_source')
        system_id = pred.get('system_id', 'unknown')

        # Check 1: Explicit placeholder 20.0
        if line_value == 20.0:
            placeholder_count += 1
            issues.append(f"{system_id}: line_value=20.0 (PLACEHOLDER)")

        # Check 2: Missing or invalid line source
        if line_source in [None, 'NEEDS_BOOTSTRAP']:
            issues.append(f"{system_id}: invalid line_source={line_source}")
            placeholder_count += 1

        # Check 3: NULL line with actual prop claim (data inconsistency)
        if line_value is None and pred.get('has_prop_line') == True:
            issues.append(f"{system_id}: NULL line but has_prop_line=TRUE")
            placeholder_count += 1

        # Check 4: ACTUAL_PROP should not have ESTIMATED api (contradiction)
        # Session 21 fix: Prevent line_source and line_source_api contradictions
        line_source_api = pred.get('line_source_api')
        has_prop_line = pred.get('has_prop_line')

        if line_source == 'ACTUAL_PROP' and line_source_api == 'ESTIMATED':
            issues.append(f"{system_id}: ACTUAL_PROP with ESTIMATED api (contradiction)")
            placeholder_count += 1

        # Check 5: ACTUAL_PROP should have has_prop_line=TRUE
        if line_source == 'ACTUAL_PROP' and has_prop_line is False:
            issues.append(f"{system_id}: ACTUAL_PROP with has_prop_line=FALSE (contradiction)")
            placeholder_count += 1

        # Check 6: ESTIMATED_AVG should not have ODDS_API/BETTINGPROS api
        if line_source == 'ESTIMATED_AVG' and line_source_api in ('ODDS_API', 'BETTINGPROS'):
            issues.append(f"{system_id}: ESTIMATED_AVG with {line_source_api} api (contradiction)")
            placeholder_count += 1

    if placeholder_count > 0:
        error_msg = (
            f"❌ LINE QUALITY VALIDATION FAILED\n"
            f"Player: {player_lookup}\n"
            f"Date: {game_date_str}\n"
            f"Failed: {placeholder_count}/{len(predictions)} predictions\n"
            f"Issues: {', '.join(issues[:5])}"  # First 5 issues
        )
        return False, error_msg

    return True, None


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
    moving_average, zone_matchup, similarity, xgboost, catboost, ensemble, ensemble_v1_1 = get_prediction_systems()
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
            logger.error("No Pub/Sub message received", exc_info=True)
            return ('Bad Request: no Pub/Sub message received', 400)

        # Decode message
        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            logger.error("No message field in envelope", exc_info=True)
            return ('Bad Request: invalid Pub/Sub message format', 400)

        # Get message data
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        request_data = json.loads(message_data)

        # Extract dataset_prefix for test isolation (if present)
        dataset_prefix = request_data.get('dataset_prefix', '')

        # Extract correlation_id for request tracing
        correlation_id = request_data.get('correlation_id')

        logger.info(
            f"Processing prediction request: {request_data.get('player_lookup')} on {request_data.get('game_date')} "
            f"(dataset_prefix: {dataset_prefix or 'production'}, correlation_id: {correlation_id})"
        )

        # Extract request parameters
        player_lookup = request_data['player_lookup']
        game_date_str = request_data['game_date']
        game_id = request_data['game_id']
        line_values = request_data.get('line_values') or []  # Handle explicit None from JSON
        batch_id = request_data.get('batch_id')  # From coordinator for staging writes
        prediction_run_mode = request_data.get('prediction_run_mode', 'OVERNIGHT')  # Session 76: Traceability

        # BATCH OPTIMIZATION: Extract pre-loaded historical games if available
        historical_games_batch = request_data.get('historical_games_batch')
        if historical_games_batch:
            logger.info(f"Worker using pre-loaded historical games ({len(historical_games_batch)} games) from coordinator")

        # DATASET ISOLATION: Create new data_loader with dataset_prefix if specified
        # Otherwise use the cached global loader for production
        if dataset_prefix:
            from data_loaders import PredictionDataLoader
            data_loader = PredictionDataLoader(PROJECT_ID, dataset_prefix=dataset_prefix)
            logger.debug(f"Created isolated data_loader with prefix: {dataset_prefix}")
        else:
            data_loader = get_data_loader()  # Use cached production loader

        # v3.2: Extract line source tracking info, v3.3: Add API/sportsbook tracking
        line_source_info = {
            'has_prop_line': request_data.get('has_prop_line', True),  # Default True for backwards compat
            'actual_prop_line': request_data.get('actual_prop_line'),
            'line_source': request_data.get('line_source', 'ACTUAL_PROP'),  # Default to actual
            'estimated_line_value': request_data.get('estimated_line_value'),
            'estimation_method': request_data.get('estimation_method'),
            # v3.3: Line source API and sportsbook tracking
            'line_source_api': request_data.get('line_source_api'),  # 'ODDS_API', 'BETTINGPROS', 'ESTIMATED'
            'sportsbook': request_data.get('sportsbook'),  # 'DRAFTKINGS', 'FANDUEL', etc.
            'was_line_fallback': request_data.get('was_line_fallback', False),  # True if not primary
            # v3.6: Line timing tracking (how close to closing line was the captured line)
            'line_minutes_before_game': request_data.get('line_minutes_before_game'),  # Minutes before tipoff
            # v4.0: Team context for teammate injury impact
            'team_abbr': request_data.get('team_abbr'),
            'opponent_team_abbr': request_data.get('opponent_team_abbr'),
            # Session 76: Run mode tracking for early vs overnight analysis
            'prediction_run_mode': prediction_run_mode,
            # Session 79: Kalshi prediction market data
            'kalshi_available': request_data.get('kalshi_available', False),
            'kalshi_line': request_data.get('kalshi_line'),
            'kalshi_yes_price': request_data.get('kalshi_yes_price'),
            'kalshi_no_price': request_data.get('kalshi_no_price'),
            'kalshi_liquidity': request_data.get('kalshi_liquidity'),
            'kalshi_market_ticker': request_data.get('kalshi_market_ticker'),
            'line_discrepancy': request_data.get('line_discrepancy'),
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

        # VALIDATION GATE: Block placeholder lines from entering database
        if predictions:
            validation_passed, validation_error = validate_line_quality(predictions, player_lookup, game_date_str)
            if not validation_passed:
                logger.error(f"LINE QUALITY VALIDATION FAILED: {validation_error}", exc_info=True)
                # Return 500 to trigger Pub/Sub retry - this prevents data corruption
                return ('Line quality validation failed - triggering retry', 500)

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

            # Classify failure to determine retry behavior
            skip_reason = metadata.get('skip_reason') or 'unknown'
            error_type = metadata.get('error_type') or 'UnknownError'

            if skip_reason in PERMANENT_SKIP_REASONS:
                # Permanent failure - data won't appear on retry
                # Return 204 to ack message and stop retries (prevents retry storm)
                logger.warning(
                    f"PERMANENT failure for {player_lookup} on {game_date_str} - "
                    f"acknowledging message (no retry). Reason: {skip_reason}"
                )
                return ('', 204)
            else:
                # Transient failure (or unknown) - might resolve on retry
                # Return 500 to trigger Pub/Sub retry
                logger.error(
                    f"TRANSIENT failure for {player_lookup} on {game_date_str} - "
                    f"returning 500 to trigger Pub/Sub retry. Reason: {skip_reason}, Error: {error_type}"
                )
                return ('Transient failure - triggering retry', 500)

        # Write to BigQuery staging table (consolidation happens later by coordinator)
        # CRITICAL: Check return value - if write fails, return 500 to trigger Pub/Sub retry
        write_start = time.time()
        write_success = write_predictions_to_bigquery(predictions, batch_id=batch_id, dataset_prefix=dataset_prefix)
        write_duration = time.time() - write_start

        if not write_success:
            # LAYER 1 FIX: Staging write failed - return 500 to trigger Pub/Sub retry
            # This prevents silent data loss by ensuring the message is retried or sent to DLQ
            logger.error(
                f"Staging write failed for {player_lookup} on {game_date_str} - "
                f"returning 500 to trigger Pub/Sub retry (batch={batch_id})"
            )
            return ('Staging write failed - triggering retry', 500)

        # Publish completion event ONLY if staging write succeeded
        # (include batch_id for Firestore state tracking, correlation_id for tracing)
        pubsub_start = time.time()
        publish_completion_event(player_lookup, game_date_str, len(predictions), batch_id=batch_id, correlation_id=correlation_id)
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
        logger.error(f"Missing required field: {e}", exc_info=True)

        # Log failure if we have player info
        if player_lookup:
            execution_logger.log_failure(
                player_lookup=player_lookup,
                universal_player_id=universal_player_id,
                game_date=game_date_str or '1900-01-01',  # Sentinel date for BigQuery DATE type
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
                game_date=game_date_str or '1900-01-01',  # Sentinel date for BigQuery DATE type
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
    moving_average, zone_matchup, similarity, xgboost, catboost, ensemble, ensemble_v1_1 = get_prediction_systems()

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
        logger.error(f"No features available for {player_lookup} on {game_date}", exc_info=True)
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

    # Configurable threshold - default 50 allows more predictions with confidence tracking
    min_quality_threshold = float(os.environ.get('PREDICTION_MIN_QUALITY_THRESHOLD', '50.0'))
    is_valid, validation_errors = validate_features(features, min_quality_score=min_quality_threshold)

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
    # v3.3: Add line source API and sportsbook tracking
    features['line_source_api'] = line_source_info.get('line_source_api')
    features['sportsbook'] = line_source_info.get('sportsbook')
    features['was_line_fallback'] = line_source_info.get('was_line_fallback', False)
    # v3.6: Add line timing tracking (how close to closing line)
    features['line_minutes_before_game'] = line_source_info.get('line_minutes_before_game')
    # Session 77 FIX: Extract prediction_run_mode for BigQuery record
    # Bug: Session 76 added to line_source_info but forgot to extract to features
    features['prediction_run_mode'] = line_source_info.get('prediction_run_mode', 'OVERNIGHT')

    # Session 79: Extract Kalshi prediction market data
    features['kalshi_available'] = line_source_info.get('kalshi_available', False)
    features['kalshi_line'] = line_source_info.get('kalshi_line')
    features['kalshi_yes_price'] = line_source_info.get('kalshi_yes_price')
    features['kalshi_no_price'] = line_source_info.get('kalshi_no_price')
    features['kalshi_liquidity'] = line_source_info.get('kalshi_liquidity')
    features['kalshi_market_ticker'] = line_source_info.get('kalshi_market_ticker')
    features['line_discrepancy'] = line_source_info.get('line_discrepancy')

    # v3.7 (Session 24 FIX): Add CatBoost V8 required features
    # The ml_feature_store_v2 only has 25 base features, but CatBoost V8 needs 33.
    # Features 25-32 (Vegas/opponent/PPM) must be populated from available data.
    # Without this fix, predictions were inflated by +29 points (64.48 vs 34.96 expected).

    # Snapshot original features to track which V8 features need fallbacks
    # This is used by the v3.8 fallback severity logging below
    original_features = set(features.keys())

    actual_prop = line_source_info.get('actual_prop_line')
    if actual_prop is not None:
        # Vegas features (indices 25-28)
        features['vegas_points_line'] = actual_prop
        features['vegas_opening_line'] = actual_prop  # Use same as closing (no opening data)
        features['vegas_line_move'] = 0.0  # No line movement data available
        features['has_vegas_line'] = 1.0  # CRITICAL: Must be 1.0 when we have a line!
    else:
        # No prop line - use np.nan for Vegas features (CatBoost handles natively)
        features['vegas_points_line'] = None
        features['vegas_opening_line'] = None
        features['vegas_line_move'] = None
        features['has_vegas_line'] = 0.0

    # Opponent history features (indices 29-30)
    # These would require a separate query to player_game_summary.
    # For now, use season average as fallback (same as training imputation).
    # Future enhancement: Add opponent history lookup to data_loader.
    season_avg = features.get('points_avg_season', 15.0)
    if 'avg_points_vs_opponent' not in features:
        features['avg_points_vs_opponent'] = season_avg
    if 'games_vs_opponent' not in features:
        features['games_vs_opponent'] = 0.0

    # PPM features (indices 31-32)
    # minutes_avg_last_10 is already in feature store (feature #5 = games_in_last_7_days proxy)
    # ppm_avg_last_10 can be calculated from available data
    if 'minutes_avg_last_10' not in features:
        features['minutes_avg_last_10'] = 30.0  # Default NBA starter minutes
    if 'ppm_avg_last_10' not in features:
        # Calculate PPM from available data if possible
        pts_avg = features.get('points_avg_last_10', season_avg)
        mins_avg = features.get('minutes_avg_last_10', 30.0)
        if mins_avg and mins_avg > 0:
            features['ppm_avg_last_10'] = pts_avg / mins_avg
        else:
            features['ppm_avg_last_10'] = 0.5  # Typical NBA PPM

    # v3.8: Track which V8 features used fallback values and classify severity
    # This implements Task #8 from the CatBoost V8 Prevention Plan to enable
    # "loud failures" for missing features instead of silent degradation.
    # v3.9: Also record Prometheus metrics for monitoring (Prevention Task #9)
    from predictions.worker.prediction_systems.catboost_v8 import (
        classify_fallback_severity,
        get_fallback_details,
        FallbackSeverity,
        record_feature_fallback_metrics,
    )

    # Track features that used fallback/default values
    v8_fallback_features: List[str] = []

    # Check Vegas features (most critical for V8 accuracy)
    if actual_prop is None:
        v8_fallback_features.extend(['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line'])

    # Check opponent history (would require separate query, using season avg fallback)
    # These always use fallback unless we add opponent lookup in future
    if 'avg_points_vs_opponent' not in original_features:
        v8_fallback_features.append('avg_points_vs_opponent')
    if 'games_vs_opponent' not in original_features:
        v8_fallback_features.append('games_vs_opponent')

    # Check PPM features
    if 'minutes_avg_last_10' not in original_features:
        v8_fallback_features.append('minutes_avg_last_10')
    if 'ppm_avg_last_10' not in original_features:
        v8_fallback_features.append('ppm_avg_last_10')

    # Classify fallback severity
    fallback_severity = classify_fallback_severity(v8_fallback_features)
    fallback_details = get_fallback_details(v8_fallback_features)

    # v3.9: Record Prometheus metrics for feature fallbacks (Prevention Task #9)
    # This enables monitoring dashboards and alerts for fallback rates
    record_feature_fallback_metrics(v8_fallback_features)

    # Log based on severity level (loud failures principle)
    log_extra = {
        "player_lookup": player_lookup,
        "fallback_severity": fallback_severity.value,
        "fallback_count": len(v8_fallback_features),
        "fallback_features": v8_fallback_features,
        "critical_features": fallback_details['critical_features'],
        "major_features": fallback_details['major_features'],
        "vegas_points_line": features.get('vegas_points_line'),
        "has_vegas_line": features.get('has_vegas_line'),
        "ppm_avg_last_10": round(features.get('ppm_avg_last_10', 0), 3),
        "avg_points_vs_opponent": features.get('avg_points_vs_opponent'),
    }

    if fallback_severity == FallbackSeverity.CRITICAL:
        logger.error(
            "catboost_v8_critical_fallback",
            extra=log_extra
        )
    elif fallback_severity == FallbackSeverity.MAJOR:
        logger.warning(
            "catboost_v8_major_fallback",
            extra=log_extra
        )
    elif fallback_severity == FallbackSeverity.MINOR:
        logger.info(
            "catboost_v8_minor_fallback",
            extra=log_extra
        )
    else:
        # NONE severity - all features present, use debug level
        logger.debug(
            "catboost_v8_features_complete",
            extra=log_extra
        )

    # Store fallback info in features for potential use in prediction quality tracking
    features['_v8_fallback_severity'] = fallback_severity.value
    features['_v8_fallback_features'] = v8_fallback_features

    # Log V8 feature enrichment for monitoring (original debug log)
    logger.debug(
        "catboost_v8_features_enriched",
        extra={
            "player_lookup": player_lookup,
            "vegas_points_line": features.get('vegas_points_line'),
            "has_vegas_line": features.get('has_vegas_line'),
            "ppm_avg_last_10": round(features.get('ppm_avg_last_10', 0), 3),
            "avg_points_vs_opponent": features.get('avg_points_vs_opponent'),
        }
    )

    # v3.4: Check and inject injury status at prediction time
    # This enables distinguishing expected vs surprise voids after game completes
    try:
        injury_filter = get_injury_filter()
        injury_status = injury_filter.check_player(player_lookup, game_date)

        # Inject injury info into features for format_prediction_for_bigquery
        features['injury_status_at_prediction'] = injury_status.injury_status.upper() if injury_status.injury_status else None
        features['injury_flag_at_prediction'] = injury_status.has_warning or injury_status.should_skip
        features['injury_reason_at_prediction'] = injury_status.reason
        features['injury_checked_at'] = datetime.utcnow().isoformat()

        # Track in metadata
        metadata['injury_status'] = injury_status.injury_status
        metadata['injury_has_warning'] = injury_status.has_warning
        metadata['injury_should_skip'] = injury_status.should_skip

        # v4.2: CRITICAL FIX - Actually skip predictions for OUT players
        # Previously the should_skip flag was recorded but never enforced
        # Session 104: Fix to prevent 40% of predictions being wasted on DNP players
        if injury_status.should_skip:
            logger.warning(
                f"⛔ Skipping prediction for {player_lookup}: Player is "
                f"{injury_status.injury_status.upper() if injury_status.injury_status else 'OUT'} "
                f"({injury_status.reason or 'no reason provided'})"
            )
            metadata['error_message'] = f"Player injury status: {injury_status.message}"
            metadata['skip_reason'] = 'player_injury_out'
            return {'predictions': [], 'metadata': metadata}

        if injury_status.has_warning:
            logger.info(
                f"⚠️ Injury flag for {player_lookup}: {injury_status.injury_status} - "
                f"{injury_status.reason or 'no reason'}"
            )

        # v4.1: Check DNP history for additional risk signal (from gamebook data)
        # Catches late scratches, coach decisions not in pre-game injury report
        dnp_history = injury_filter.check_dnp_history(player_lookup, game_date)

        # Inject DNP history into features
        features['dnp_history'] = {
            'has_dnp_risk': dnp_history.has_dnp_risk,
            'dnp_count': dnp_history.dnp_count,
            'dnp_rate': dnp_history.dnp_rate,
            'games_checked': dnp_history.games_checked,
            'risk_category': dnp_history.risk_category,
            'days_since_last_dnp': dnp_history.days_since_last_dnp,
            'recent_reasons': dnp_history.recent_dnp_reasons[:2] if dnp_history.recent_dnp_reasons else []
        }

        # Track in metadata
        metadata['dnp_history'] = {
            'has_risk': dnp_history.has_dnp_risk,
            'dnp_count': dnp_history.dnp_count,
            'category': dnp_history.risk_category
        }

        if dnp_history.has_dnp_risk:
            logger.info(
                f"⚠️ DNP risk for {player_lookup}: {dnp_history.dnp_count}/{dnp_history.games_checked} "
                f"recent games DNP ({dnp_history.risk_category or 'unknown'})"
            )

        # v4.0: Calculate teammate injury impact for usage/points adjustments
        team_abbr = line_source_info.get('team_abbr')
        if team_abbr:
            teammate_impact = injury_filter.get_teammate_impact(player_lookup, team_abbr, game_date)

            # Inject teammate impact into features
            features['teammate_injury_impact'] = {
                'usage_boost_factor': teammate_impact.usage_boost_factor,
                'minutes_boost_factor': teammate_impact.minutes_boost_factor,
                'opportunity_score': teammate_impact.opportunity_score,
                'out_starters': teammate_impact.out_starters,
                'out_star_players': teammate_impact.out_star_players,
                'total_out': len(teammate_impact.out_teammates),
                'total_questionable': len(teammate_impact.questionable_teammates),
                'has_significant_impact': teammate_impact.has_significant_impact
            }

            # Track in metadata for logging/analysis
            metadata['teammate_impact'] = {
                'usage_boost': teammate_impact.usage_boost_factor,
                'opportunity_score': teammate_impact.opportunity_score,
                'out_starters': teammate_impact.out_starters,
                'has_significant': teammate_impact.has_significant_impact
            }

            if teammate_impact.has_significant_impact:
                logger.info(
                    f"📊 Teammate impact for {player_lookup}: "
                    f"usage_boost={teammate_impact.usage_boost_factor:.2f}, "
                    f"out_starters={teammate_impact.out_starters}"
                )
        else:
            features['teammate_injury_impact'] = None
            metadata['teammate_impact'] = None

    except Exception as e:
        # Non-fatal: continue prediction without injury info (fail-open)
        logger.warning(f"Failed to check injury status for {player_lookup}: {e}")
        features['injury_status_at_prediction'] = None
        features['injury_flag_at_prediction'] = None
        features['injury_reason_at_prediction'] = None
        features['injury_checked_at'] = None
        features['dnp_history'] = None
        features['teammate_injury_impact'] = None
        metadata['dnp_history'] = None
        metadata['teammate_impact'] = None

    # Step 2.5: Check feature completeness (Phase 5)
    # SELF-HEALING: Made more lenient - proceed with warnings instead of blocking
    completeness = features.get('completeness', {})
    metadata['completeness'] = completeness

    # LENIENT: Accept if ANY of these conditions are true:
    # - production_ready flag set
    # - bootstrap_mode flag set
    # - quality score >= 35 (lowered from 50 to prevent filtering valid players)
    # - has valid context (player is expected to play today)
    # NOTE: 2026-01-10 - Lowered from 50 to 35 to fix UNKNOWN_REASON gaps where
    # players had context + features + betting lines but no predictions (e.g., Murray, Porzingis)
    has_valid_context = features.get('context', {}).get('is_starter') is not None
    is_acceptable = (
        completeness.get('is_production_ready', False) or
        completeness.get('backfill_bootstrap_mode', False) or
        quality_score >= 35 or  # Lowered for self-healing (confidence_level tracks actual quality)
        has_valid_context  # If we have player context, allow prediction attempt
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

            logger.error(f"Moving Average failed for {player_lookup}: {e}", exc_info=True)
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

            logger.error(f"Zone Matchup failed for {player_lookup}: {e}", exc_info=True)
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

            logger.error(f"Similarity failed for {player_lookup}: {e}", exc_info=True)
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['similarity_balanced_v1'] = None
        
        # System 4: XGBoost V1 (baseline ML model)
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

                    system_predictions['catboost_v8'] = {
                        'predicted_points': result['predicted_points'],
                        'confidence': result['confidence_score'],
                        'recommendation': result['recommendation'],
                        'system_type': 'dict',
                        'metadata': result
                    }
                else:
                    logger.warning(f"XGBoost V1 returned None for {player_lookup}")
                    metadata['systems_failed'].append(system_id)
                    metadata['system_errors'][system_id] = 'Prediction returned None'
                    system_predictions[CATBOOST_SYSTEM_ID] = None
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"XGBoost V1 failed for {player_lookup}: {e}", exc_info=True)
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['xgboost_v1'] = None

        # System 5: CatBoost (champion ML model - V8 or V9 based on CATBOOST_VERSION)
        system_id = CATBOOST_SYSTEM_ID
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
                result = catboost.predict(
                    player_lookup=player_lookup,
                    features=features,
                    betting_line=line_value
                )

                if result['predicted_points'] is not None:
                    # Record success
                    circuit_breaker.record_success(system_id)
                    metadata['systems_succeeded'].append(system_id)

                    system_predictions[CATBOOST_SYSTEM_ID] = {
                        'predicted_points': result['predicted_points'],
                        'confidence': result['confidence_score'],
                        'recommendation': result['recommendation'],
                        'system_type': 'dict',
                        'metadata': result
                    }
                else:
                    logger.warning(f"CatBoost {CATBOOST_VERSION} returned None for {player_lookup}")
                    metadata['systems_failed'].append(system_id)
                    metadata['system_errors'][system_id] = 'Prediction returned None'
                    system_predictions[CATBOOST_SYSTEM_ID] = None
        except Exception as e:
            # Record failure
            error_msg = str(e)
            circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

            logger.error(f"CatBoost v8 failed for {player_lookup}: {e}", exc_info=True)
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['catboost_v8'] = None
        
        # System 6: Ensemble V1 (combines 4 base systems using CatBoost as champion)
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

            logger.error(f"Ensemble failed for {player_lookup}: {e}", exc_info=True)
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['ensemble_v1'] = None

        # System 7: Ensemble V1.1 (performance-based weighted ensemble with CatBoost V8)
        system_id = 'ensemble_v1_1'
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
                pred, conf, rec, ensemble_meta = ensemble_v1_1.predict(
                    features=features,
                    player_lookup=player_lookup,
                    game_date=game_date,
                    prop_line=line_value,
                    historical_games=historical_games if historical_games else None
                )
                # Record success
                circuit_breaker.record_success(system_id)
                metadata['systems_succeeded'].append(system_id)

                system_predictions['ensemble_v1_1'] = {
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

            logger.error(f"Ensemble V1.1 failed for {player_lookup}: {e}", exc_info=True)
            metadata['systems_failed'].append(system_id)
            metadata['system_errors'][system_id] = error_msg
            system_predictions['ensemble_v1_1'] = None

        # Monthly Models (Session 68): Run all enabled monthly retrained models
        if _monthly_models:
            for monthly_model in _monthly_models:
                system_id = monthly_model.model_id
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
                        result = monthly_model.predict(
                            player_lookup=player_lookup,
                            features=features,
                            betting_line=line_value
                        )

                        if result['predicted_points'] is not None:
                            # Record success
                            circuit_breaker.record_success(system_id)
                            metadata['systems_succeeded'].append(system_id)

                            system_predictions[system_id] = {
                                'predicted_points': result['predicted_points'],
                                'confidence': result['confidence_score'],
                                'recommendation': result['recommendation'],
                                'system_type': 'dict',
                                'metadata': result
                            }
                        else:
                            logger.warning(f"Monthly model {system_id} returned None for {player_lookup}")
                            metadata['systems_failed'].append(system_id)
                            metadata['system_errors'][system_id] = 'Prediction returned None'
                            system_predictions[system_id] = None
                except Exception as e:
                    # Record failure
                    error_msg = str(e)
                    circuit_breaker.record_failure(system_id, error_msg, type(e).__name__)

                    logger.error(f"Monthly model {system_id} failed for {player_lookup}: {e}", exc_info=True)
                    metadata['systems_failed'].append(system_id)
                    metadata['system_errors'][system_id] = error_msg
                    system_predictions[system_id] = None

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
        logger.error(f"Error looking up universal_player_id for {player_lookup}: {e}", exc_info=True)
        # Still proceed with None value

    # Check if player has a prop line (v3.2 - All-Player Predictions)
    has_prop_line = features.get('has_prop_line', True)  # Default True for backwards compatibility

    # Get line source tracking info (v3.2)
    line_source = features.get('line_source', 'ACTUAL_PROP')
    estimated_line_value = features.get('estimated_line_value')
    estimation_method = features.get('estimation_method')
    actual_prop_line = features.get('actual_prop_line')

    # v3.3: Get line source API and sportsbook tracking
    line_source_api = features.get('line_source_api')
    sportsbook = features.get('sportsbook')
    was_line_fallback = features.get('was_line_fallback', False)

    # v3.4: Confidence tier filtering
    # 88-90% confidence tier has 61.8% hit rate vs 74-76% for other tiers
    # Filter these picks but preserve original recommendation for shadow tracking
    # See: docs/08-projects/current/pipeline-reliability-improvements/FILTER-DECISIONS.md
    confidence = prediction['confidence']
    confidence_decimal = confidence / 100.0 if confidence > 1 else confidence

    is_actionable = True
    filter_reason = None

    if 0.88 <= confidence_decimal < 0.90:
        is_actionable = False
        filter_reason = 'confidence_tier_88_90'
        logger.info(
            f"Filtered pick for {player_lookup}: confidence={confidence_decimal:.3f} "
            f"in 88-90 tier, original_recommendation={prediction['recommendation']}"
        )

    # Determine recommendation and line values based on has_prop_line
    # v3.5 FIX: Always use line_value (actual or estimated) for current_points_line
    # This ensures predictions can be graded even when no actual prop exists.
    # The has_prop_line and line_source fields indicate whether line was actual or estimated.
    if has_prop_line:
        # Player has prop line - use actual prop line
        recommendation = prediction['recommendation']
        current_points_line = round(actual_prop_line if actual_prop_line else line_value, 1)
        line_margin = round(prediction['predicted_points'] - current_points_line, 2)
    elif line_value is not None:
        # Player does NOT have prop line, but we have an estimated line
        # Still generate OVER/UNDER recommendation using estimated line
        # Use line_source='ESTIMATED_AVG' to track these for separate analysis
        current_points_line = round(line_value, 1)
        line_margin = round(prediction['predicted_points'] - current_points_line, 2)
        # Recalculate recommendation based on estimated line
        if prediction['predicted_points'] > current_points_line:
            recommendation = 'OVER'
        elif prediction['predicted_points'] < current_points_line:
            recommendation = 'UNDER'
        else:
            recommendation = 'PASS'
    else:
        # No line at all (shouldn't happen, but handle gracefully)
        recommendation = 'NO_LINE'
        current_points_line = None
        line_margin = None

    # Session 102: Additional filters for edge and model bias
    # These mark predictions as not actionable but still store them for analysis
    predicted_points = prediction['predicted_points']

    if is_actionable and current_points_line is not None:
        edge = abs(predicted_points - current_points_line)

        # Low edge filter: edge < 3 has ~50% hit rate (no better than chance)
        if edge < 3.0:
            is_actionable = False
            filter_reason = 'low_edge'

        # Star UNDER bias filter: Model under-predicts stars by ~9 pts
        # High-edge UNDERs on stars are systematically wrong (Feb 2: 0/7)
        season_avg = features.get('points_avg_season', 0)
        if season_avg >= 25 and recommendation == 'UNDER' and edge >= 5:
            is_actionable = False
            filter_reason = 'star_under_bias_suspect'
            logger.info(
                f"Filtered star UNDER for {player_lookup}: season_avg={season_avg:.1f}, "
                f"predicted={predicted_points:.1f}, line={current_points_line}, edge={edge:.1f}"
            )

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

        # v3.3: Line source API and sportsbook tracking (enables hit rate by source analysis)
        'line_source_api': line_source_api,  # 'ODDS_API', 'BETTINGPROS', 'ESTIMATED'
        'sportsbook': sportsbook,  # 'DRAFTKINGS', 'FANDUEL', 'BETMGM', etc.
        'was_line_fallback': was_line_fallback,  # True if line came from fallback source

        # v3.6: Line timing tracking (enables closing line vs early line analysis)
        'line_minutes_before_game': features.get('line_minutes_before_game'),  # Minutes before tipoff

        # Status
        'is_active': True,
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': None,
        'superseded_by': None,

        # v3.4: Confidence tier filtering (shadow tracking)
        # See: docs/08-projects/current/pipeline-reliability-improvements/FILTER-DECISIONS.md
        'is_actionable': is_actionable,
        'filter_reason': filter_reason,

        # v3.4: Pre-game injury tracking (enables expected vs surprise void analysis)
        'injury_status_at_prediction': features.get('injury_status_at_prediction'),
        'injury_flag_at_prediction': features.get('injury_flag_at_prediction'),
        'injury_reason_at_prediction': features.get('injury_reason_at_prediction'),

        # v4.0: Teammate injury impact tracking (enables usage boost analysis)
        'teammate_usage_boost': (
            features.get('teammate_injury_impact', {}).get('usage_boost_factor')
            if features.get('teammate_injury_impact') else None
        ),
        'teammate_opportunity_score': (
            features.get('teammate_injury_impact', {}).get('opportunity_score')
            if features.get('teammate_injury_impact') else None
        ),
        'teammate_out_starters': (
            json.dumps((features.get('teammate_injury_impact') or {}).get('out_starters'))
            if (features.get('teammate_injury_impact') or {}).get('out_starters') else None
        ),
        'injury_checked_at': features.get('injury_checked_at'),

        # Session 64: Build tracking for debugging hit rate issues
        # These enable fast investigation by filtering predictions by code version
        'build_commit_sha': BUILD_COMMIT_SHA,
        'deployment_revision': DEPLOYMENT_REVISION,
        'predicted_at': datetime.utcnow().isoformat(),

        # Session 76: Run mode for early vs overnight analysis
        'prediction_run_mode': features.get('prediction_run_mode', 'OVERNIGHT'),

        # Session 79: Kalshi prediction market data
        'kalshi_available': features.get('kalshi_available', False),
        'kalshi_line': features.get('kalshi_line'),
        'kalshi_yes_price': features.get('kalshi_yes_price'),
        'kalshi_no_price': features.get('kalshi_no_price'),
        'kalshi_liquidity': features.get('kalshi_liquidity'),
        'kalshi_market_ticker': features.get('kalshi_market_ticker'),
        'line_discrepancy': features.get('line_discrepancy'),

        # Session 64: Critical features snapshot for debugging
        # Without this, we couldn't prove the Jan 2026 hit rate collapse was caused
        # by broken feature enrichment (took 2+ hours to investigate)
        'critical_features': json.dumps({
            'vegas_points_line': features.get('vegas_points_line'),
            'has_vegas_line': 1.0 if features.get('vegas_points_line') else 0.0,
            'ppm_avg_last_10': features.get('ppm_avg_last_10'),
            'avg_points_vs_opponent': features.get('avg_points_vs_opponent'),
            'team_win_pct': features.get('team_win_pct'),
        }),

        # Session 67: Full feature snapshot for ALL predictions (not just CatBoost)
        # Enables debugging and reproducibility for any prediction system
        'features_snapshot': json.dumps({
            'points_avg_last_5': features.get('points_avg_last_5'),
            'points_avg_last_10': features.get('points_avg_last_10'),
            'points_avg_season': features.get('points_avg_season'),
            'points_std_last_10': features.get('points_std_last_10'),
            'vegas_points_line': features.get('vegas_points_line'),
            'has_vegas_line': features.get('has_vegas_line'),
            'minutes_avg_last_10': features.get('minutes_avg_last_10'),
            'ppm_avg_last_10': features.get('ppm_avg_last_10'),
            'fatigue_score': features.get('fatigue_score'),
            'opponent_def_rating': features.get('opponent_def_rating'),
            'team_win_pct': features.get('team_win_pct'),
            'back_to_back': features.get('back_to_back'),
            'home_away': features.get('home_away'),
            'feature_version': features.get('feature_version'),
            'pace_score': features.get('pace_score'),
            'usage_spike_score': features.get('usage_spike_score'),
            'feature_quality_score': features.get('feature_quality_score'),
        }),

        # Session 97: Feature quality tracking - enables filtering predictions by data quality
        # feature_quality_score: 0-100 score based on data completeness from ml_feature_store_v2
        # low_quality_flag: True if quality < 70% (predictions made with incomplete data)
        'feature_quality_score': features.get('feature_quality_score'),
        'low_quality_flag': features.get('feature_quality_score', 100) < 70,  # True if quality < 70%

        # Session 99: Data provenance tracking - enables audit trail and quality filtering
        # matchup_data_status: COMPLETE, PARTIAL_FALLBACK, or MATCHUP_UNAVAILABLE
        # feature_sources_json: Per-feature source tracking for full audit trail
        'matchup_data_status': features.get('matchup_data_status'),
        'feature_sources_json': features.get('feature_sources_json'),

        # Session 103: Tier calibration metadata - raw prediction stays pure, calibration is metadata
        # scoring_tier: Player category based on season scoring average
        # tier_adjustment: Suggested calibration (add to predicted_points at query time if desired)
        # This addresses regression-to-mean bias WITHOUT modifying stored predictions
        'scoring_tier': _compute_scoring_tier(features.get('points_avg_season', 15.0)),
        'tier_adjustment': _compute_tier_adjustment(features.get('points_avg_season', 15.0)),

        # Session 112: Scenario classification for optimal betting strategies
        # scenario_category: optimal_over, optimal_under, ultra_high_edge_over, anti_under_low_line, etc.
        # scenario_flags: JSON with edge, line_value, blacklisted_player, risky_opponent, etc.
        # See: docs/08-projects/current/scenario-filtering-system/README.md
    }

    # Session 112: Classify scenario AFTER record creation (needs recommendation and line values)
    scenario_category, scenario_flags = _classify_scenario(
        recommendation=recommendation,
        line_value=current_points_line,
        predicted_points=predicted_points,
        player_lookup=player_lookup,
        opponent_tricode=features.get('opponent_tricode')
    )
    record['scenario_category'] = scenario_category
    record['scenario_flags'] = json.dumps(scenario_flags)

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
            'home_away_adjustment': adjustments.get('venue'),
            'model_version': 'v1'  # Set model version for tracking
        })

    elif system_id.startswith('catboost_') and 'metadata' in prediction:
        # prediction['metadata'] is the full catboost result dict
        # The actual metadata fields are NESTED in result['metadata']
        # Session 88 FIX: Access nested metadata correctly
        catboost_result = prediction['metadata']
        catboost_meta = catboost_result.get('metadata', {})
        record.update({
            'model_version': catboost_meta.get('model_version', system_id),
            'feature_importance': json.dumps({
                'model_type': catboost_meta.get('model_type'),
                'feature_count': catboost_meta.get('feature_count', 33),
                'training_approach': catboost_meta.get('training_approach'),  # V9: 'current_season_only'
                'training_period': catboost_meta.get('training_period'),  # V9: date range
            }) if catboost_meta.get('model_type') or catboost_meta.get('training_approach') else None,
            # Note: features_snapshot now set in base record for ALL systems (Session 67)

            # Session 84: Model attribution tracking
            'model_file_name': catboost_meta.get('model_file_name'),
            'model_training_start_date': catboost_meta.get('model_training_start_date'),
            'model_training_end_date': catboost_meta.get('model_training_end_date'),
            'model_expected_mae': catboost_meta.get('model_expected_mae'),
            'model_expected_hit_rate': catboost_meta.get('model_expected_hit_rate'),
            'model_trained_at': catboost_meta.get('model_trained_at'),
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

    elif system_id == 'ensemble_v1_1' and 'metadata' in prediction:
        metadata = prediction['metadata']
        agreement = metadata.get('agreement', {})

        # Store ensemble V1.1 metadata in feature_importance as JSON (schema-compatible)
        record.update({
            'feature_importance': json.dumps({
                'variance': agreement.get('variance'),
                'agreement_percentage': agreement.get('agreement_percentage'),
                'systems_used': metadata.get('systems_used'),
                'weights_used': metadata.get('weights_used'),  # NEW: track performance-based weights
                'predictions': metadata.get('predictions'),
                'agreement_type': agreement.get('type')
            }),
            'model_version': 'ensemble_v1_1'
        })

    elif system_id == 'moving_average':
        # Set model version for tracking
        record.update({
            'model_version': 'v1'
        })

    elif system_id == 'zone_matchup_v1':
        # Set model version for tracking
        record.update({
            'model_version': 'v1'
        })

    elif system_id == 'xgboost_v1' and 'metadata' in prediction:
        # xgboost has metadata field
        metadata = prediction['metadata']
        record.update({
            'model_version': metadata.get('model_version', 'v1')
        })

    # Add completeness metadata (Phase 5)
    completeness = features.get('completeness', {})

    # data_quality_issues is STRING in schema (not ARRAY) - serialize to JSON
    data_quality_issues = completeness.get('data_quality_issues', [])
    if not isinstance(data_quality_issues, list):
        data_quality_issues = []  # Ensure it's always a list before serializing
    data_quality_issues_json = json.dumps(data_quality_issues) if data_quality_issues else None

    record.update({
        'expected_games_count': completeness.get('expected_games_count'),
        'actual_games_count': completeness.get('actual_games_count'),
        'completeness_percentage': completeness.get('completeness_percentage', 0.0),
        'missing_games_count': completeness.get('missing_games_count'),
        'is_production_ready': completeness.get('is_production_ready', False),
        'data_quality_issues': data_quality_issues_json,  # STRING - serialize to JSON
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


@retry_on_quota_exceeded
def write_predictions_to_bigquery(predictions: List[Dict], batch_id: Optional[str] = None, dataset_prefix: str = '') -> bool:
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

    Returns:
        bool: True if staging write succeeded, False otherwise.
              CRITICAL: Caller MUST check return value and handle failures appropriately.
              Returning False should trigger Pub/Sub retry (return 500), NOT silent continuation.
    """
    from batch_staging_writer import get_worker_id, BatchStagingWriter

    if not predictions:
        logger.warning("No predictions to write")
        return True  # No predictions is not a failure - nothing to write

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
            return True  # SUCCESS: Staging write completed
        else:
            # Staging write failed - this is a critical failure
            write_duration = time.time() - write_start_time
            logger.error(
                f"STAGING WRITE FAILED for {player_lookup}: {result.error_message} "
                f"(batch={batch_id}, worker={worker_id}) - will trigger Pub/Sub retry"
            )

            PredictionWriteMetrics.track_write_attempt(
                player_lookup=player_lookup,
                records_count=records_count,
                success=False,
                duration_seconds=write_duration,
                error_type='StagingWriteError'
            )
            return False  # FAILURE: Signal caller to return 500 for retry

    except Exception as e:
        write_duration = time.time() - write_start_time
        logger.error(
            f"STAGING WRITE EXCEPTION for {player_lookup}: {type(e, exc_info=True).__name__}: {e} "
            f"(batch={batch_id}) - will trigger Pub/Sub retry"
        )

        # Track write failure
        PredictionWriteMetrics.track_write_attempt(
            player_lookup=player_lookup,
            records_count=records_count,
            success=False,
            duration_seconds=write_duration,
            error_type=type(e).__name__
        )
        return False  # FAILURE: Signal caller to return 500 for retry


def publish_completion_event(player_lookup: str, game_date: str, prediction_count: int, batch_id: str = None, correlation_id: str = None):
    """
    Publish prediction-ready event to Pub/Sub

    Notifies downstream systems that predictions are available

    Args:
        player_lookup: Player identifier
        game_date: Game date string
        prediction_count: Number of predictions generated
        batch_id: Batch identifier (REQUIRED for Firestore state tracking)
        correlation_id: Correlation ID for request tracing
    """
    pubsub_publisher = get_pubsub_publisher()
    topic_path = pubsub_publisher.topic_path(PROJECT_ID, PUBSUB_READY_TOPIC)

    message_data = {
        'player_lookup': player_lookup,
        'game_date': game_date,
        'predictions_generated': prediction_count,
        'batch_id': batch_id,  # Critical for Firestore state persistence!
        'correlation_id': correlation_id,  # For request tracing
        'timestamp': datetime.utcnow().isoformat(),
        'worker_instance': os.environ.get('K_REVISION', 'unknown')
    }
    
    try:
        message_bytes = json.dumps(message_data).encode('utf-8')
        future = pubsub_publisher.publish(topic_path, data=message_bytes)
        # CRITICAL FIX (Jan 25, 2026): Added timeout to prevent indefinite hang
        future.result(timeout=30)  # 30 second max for publish
        logger.debug(f"Published completion event for {player_lookup}")
    except TimeoutError:
        logger.error(f"Timeout publishing completion event for {player_lookup} after 30s", exc_info=True)
        # Don't raise - log and continue
    except Exception as e:
        logger.error(f"Error publishing completion event: {e}", exc_info=True)
        # Don't raise - log and continue


logger.info("=" * 80)
logger.info("WEEK 2 ALERTING ENDPOINTS LOADING...")
logger.info("  - /health/deep")
logger.info("  - /ready")
logger.info("  - /internal/check-env")
logger.info("  - /internal/deployment-started")
logger.info("  - /metrics (CatBoost V8 Prometheus metrics - Prevention Task #9)")
logger.info("=" * 80)


@app.route('/ready', methods=['GET'])
@app.route('/health/deep', methods=['GET'])
def deep_health_check():
    """
    Deep health check endpoint.
    Validates all dependencies: GCS, BigQuery, model loading, configuration.

    Returns:
        200: All checks passed (healthy)
        503: One or more checks failed (unhealthy)
    """
    try:
        from health_checks import HealthChecker

        checker = HealthChecker(project_id=PROJECT_ID)
        result = checker.run_all_checks(parallel=True)

        status_code = 200 if result['status'] == 'healthy' else 503

        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Deep health check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'checks': [],
            'total_duration_ms': 0
        }), 503


@app.route('/internal/check-env', methods=['POST'])
def check_env_vars():
    """
    Internal endpoint for environment variable change detection.
    Called by Cloud Scheduler every 5 minutes.

    Returns:
        200: Check completed (may include alert in logs)
        500: Check failed
    """
    try:
        from env_monitor import EnvVarMonitor

        monitor = EnvVarMonitor(project_id=PROJECT_ID)
        result = monitor.check_for_changes()

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Environment check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'ERROR',
            'message': str(e)
        }), 500


@app.route('/internal/deployment-started', methods=['POST'])
def mark_deployment_started():
    """
    Internal endpoint to mark that a deployment has started.
    This activates the deployment grace period to prevent false alerts.

    Should be called at the START of deployment (before env vars change).

    Returns:
        200: Deployment grace period activated
        500: Failed to mark deployment
    """
    try:
        from env_monitor import EnvVarMonitor

        monitor = EnvVarMonitor(project_id=PROJECT_ID)
        result = monitor.mark_deployment_started()

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Failed to mark deployment started: {e}", exc_info=True)
        return jsonify({
            'status': 'ERROR',
            'message': str(e)
        }), 500


# =============================================================================
# Prometheus Metrics Endpoint (Prevention Task #9)
# =============================================================================
# Exposes CatBoost V8 prediction metrics for monitoring and alerting.
# Metrics:
#   - catboost_v8_feature_fallback_total: Counter by feature_name, severity
#   - catboost_v8_prediction_points: Histogram of prediction values
#   - catboost_v8_extreme_prediction_total: Counter by boundary (high_60, low_0)
# =============================================================================

@app.route('/metrics', methods=['GET'])
def prometheus_metrics():
    """
    Prometheus metrics endpoint for CatBoost V8 prediction monitoring.

    Exposes metrics in Prometheus text format:
    - catboost_v8_feature_fallback_total: Count of predictions using fallback values
    - catboost_v8_prediction_points: Distribution of predicted points
    - catboost_v8_extreme_prediction_total: Count of predictions at clamp boundaries

    Returns:
        200: Prometheus-formatted metrics text
    """
    from flask import Response
    from predictions.worker.prediction_systems.catboost_v8 import (
        catboost_v8_feature_fallback_total,
        catboost_v8_prediction_points,
        catboost_v8_extreme_prediction_total,
    )

    lines = []

    # Format feature fallback counter
    lines.append(f"# HELP catboost_v8_feature_fallback_total {catboost_v8_feature_fallback_total.help_text}")
    lines.append(f"# TYPE catboost_v8_feature_fallback_total counter")
    for labels, value in catboost_v8_feature_fallback_total.get_samples():
        label_str = ','.join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        lines.append(f"catboost_v8_feature_fallback_total{{{label_str}}} {value}")

    lines.append("")

    # Format prediction histogram
    lines.append(f"# HELP catboost_v8_prediction_points {catboost_v8_prediction_points.help_text}")
    lines.append(f"# TYPE catboost_v8_prediction_points histogram")
    for labels, suffix, value in catboost_v8_prediction_points.get_samples():
        label_str = ','.join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        if label_str:
            lines.append(f"catboost_v8_prediction_points{suffix}{{{label_str}}} {value}")
        else:
            lines.append(f"catboost_v8_prediction_points{suffix} {value}")

    lines.append("")

    # Format extreme prediction counter
    lines.append(f"# HELP catboost_v8_extreme_prediction_total {catboost_v8_extreme_prediction_total.help_text}")
    lines.append(f"# TYPE catboost_v8_extreme_prediction_total counter")
    for labels, value in catboost_v8_extreme_prediction_total.get_samples():
        label_str = ','.join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        lines.append(f"catboost_v8_extreme_prediction_total{{{label_str}}} {value}")

    output = '\n'.join(lines) + '\n'

    return Response(
        output,
        mimetype='text/plain; version=0.0.4; charset=utf-8'
    )


logger.info("✓ Prometheus /metrics endpoint registered for CatBoost V8 monitoring")


if __name__ == '__main__':
    # For local testing
    # Week 2 alerting endpoints added: /health/deep, /internal/check-env, /internal/deployment-started
    # Prevention Task #9: Added /metrics for CatBoost V8 Prometheus metrics
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)