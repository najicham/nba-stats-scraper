# predictions/mlb/worker.py
"""
MLB Prediction Worker

Cloud Run service that generates pitcher strikeout predictions.
Can be triggered via HTTP endpoint or Pub/Sub.

Endpoints:
    GET  /health              - Health check
    GET  /                    - Service info
    POST /predict             - Generate prediction for single pitcher
    POST /predict-batch       - Generate predictions for game date
    POST /execute-shadow-mode - Run V1.4 vs V1.6 shadow mode comparison
    POST /pubsub              - Pub/Sub push endpoint
"""

import os
import sys
import json
import base64
import logging
import time
import uuid
from datetime import datetime, date
from typing import Dict, List, Optional

from flask import Flask, request, jsonify

# Import AlertManager for intelligent alerting
try:
    from shared.alerts.alert_manager import get_alert_manager
    ALERTING_ENABLED = True
except ImportError:
    ALERTING_ENABLED = False
    logging.warning("AlertManager not available, alerts disabled")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Import shared health endpoints
from shared.endpoints.health import create_health_blueprint, HealthChecker

# Environment configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
MODEL_PATH = os.environ.get(
    'MLB_MODEL_PATH',
    'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json'
)
PREDICTIONS_TABLE = os.environ.get(
    'MLB_PREDICTIONS_TABLE',
    'mlb_predictions.pitcher_strikeouts'
)

# Flask app
app = Flask(__name__)

# Health check endpoints (Phase 1 - Task 1.1: Add Health Endpoints)
# Updated to use new HealthChecker API (service_name, version only)
health_checker = HealthChecker(
    service_name='mlb-prediction-worker',
    version='1.0'
)
app.register_blueprint(create_health_blueprint(service_name='mlb-prediction-worker', health_checker=health_checker))
logger.info("Health check endpoints registered: /health, /ready, /health/deep")

# Initialize AlertManager (with backfill mode detection)
def get_mlb_alert_manager():
    """Get AlertManager instance with MLB-specific configuration."""
    if not ALERTING_ENABLED:
        return None
    backfill_mode = os.environ.get('BACKFILL_MODE', 'false').lower() == 'true'
    return get_alert_manager(backfill_mode=backfill_mode)


def send_mlb_alert(severity: str, title: str, message: str, context: dict = None):
    """Send alert via AlertManager with rate limiting."""
    alert_mgr = get_mlb_alert_manager()
    if alert_mgr:
        try:
            alert_mgr.send_alert(
                severity=severity,
                title=title,
                message=message,
                category='mlb_prediction_failure',
                context=context or {}
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}", exc_info=True)


# Lazy-loaded components
_prediction_systems = None
_bq_client = None
_pubsub_publisher = None


def get_prediction_systems() -> Dict:
    """
    Load all active MLB prediction systems

    Returns:
        Dict[str, BaseMLBPredictor]: Map of system_id -> predictor instance
    """
    global _prediction_systems
    if _prediction_systems is None:
        from predictions.mlb.config import get_config
        from predictions.mlb.prediction_systems.v1_baseline_predictor import V1BaselinePredictor
        from predictions.mlb.prediction_systems.v1_6_rolling_predictor import V1_6RollingPredictor
        from predictions.mlb.prediction_systems.catboost_v1_predictor import CatBoostV1Predictor
        from predictions.mlb.prediction_systems.catboost_v2_regressor_predictor import CatBoostV2RegressorPredictor
        from predictions.mlb.prediction_systems.ensemble_v1 import MLBEnsembleV1

        config = get_config()
        active_systems = config.systems.get_active_systems()

        logger.info(f"Initializing prediction systems: {active_systems}")

        systems = {}
        v1_baseline = None
        v1_6_rolling = None

        # CatBoost V1 (Sprint 3 — walk-forward validated)
        if 'catboost_v1' in active_systems:
            catboost_v1 = CatBoostV1Predictor(
                model_path=config.systems.catboost_v1_model_path,
                project_id=PROJECT_ID
            )
            catboost_v1.load_model()
            systems['catboost_v1'] = catboost_v1
            logger.info("CatBoost V1 predictor initialized")

        # CatBoost V2 Regressor (opt-in via MLB_ACTIVE_SYSTEMS)
        if 'catboost_v2_regressor' in active_systems:
            catboost_v2_model_path = os.environ.get('MLB_CATBOOST_V2_MODEL_PATH')
            catboost_v2 = CatBoostV2RegressorPredictor(
                model_path=catboost_v2_model_path,
                project_id=PROJECT_ID
            )
            catboost_v2.load_model()
            systems['catboost_v2_regressor'] = catboost_v2
            logger.info("CatBoost V2 Regressor predictor initialized")

        # V1 Baseline
        if 'v1_baseline' in active_systems or 'ensemble_v1' in active_systems:
            v1_baseline = V1BaselinePredictor(
                model_path=config.systems.v1_model_path,
                project_id=PROJECT_ID
            )
            v1_baseline.load_model()
            if 'v1_baseline' in active_systems:
                systems['v1_baseline'] = v1_baseline
            logger.info("V1 Baseline predictor initialized")

        # V1.6 Rolling
        if 'v1_6_rolling' in active_systems or 'ensemble_v1' in active_systems:
            v1_6_rolling = V1_6RollingPredictor(
                model_path=config.systems.v1_6_model_path,
                project_id=PROJECT_ID
            )
            v1_6_rolling.load_model()
            if 'v1_6_rolling' in active_systems:
                systems['v1_6_rolling'] = v1_6_rolling
            logger.info("V1.6 Rolling predictor initialized")

        # Ensemble V1 (requires V1 and V1.6 to be initialized)
        if 'ensemble_v1' in active_systems:
            if v1_baseline is None or v1_6_rolling is None:
                logger.error("Ensemble requires both V1 and V1.6 predictors", exc_info=True)
            else:
                ensemble = MLBEnsembleV1(
                    v1_predictor=v1_baseline,
                    v1_6_predictor=v1_6_rolling,
                    v1_weight=config.systems.ensemble_v1_weight,
                    v1_6_weight=config.systems.ensemble_v1_6_weight,
                    project_id=PROJECT_ID
                )
                systems['ensemble_v1'] = ensemble
                logger.info(f"Ensemble V1 initialized (V1:{config.systems.ensemble_v1_weight:.0%}, V1.6:{config.systems.ensemble_v1_6_weight:.0%})")

        # LightGBM V1 Regressor (opt-in via MLB_ACTIVE_SYSTEMS)
        if 'lightgbm_v1_regressor' in active_systems:
            from predictions.mlb.prediction_systems.lightgbm_v1_regressor_predictor import LightGBMV1RegressorPredictor
            lgbm_model_path = os.environ.get('MLB_LIGHTGBM_V1_MODEL_PATH')
            lgbm_v1 = LightGBMV1RegressorPredictor(
                model_path=lgbm_model_path,
                project_id=PROJECT_ID
            )
            lgbm_v1.load_model()
            systems['lightgbm_v1_regressor'] = lgbm_v1
            logger.info("LightGBM V1 Regressor predictor initialized")

        # XGBoost V1 Regressor (opt-in via MLB_ACTIVE_SYSTEMS)
        if 'xgboost_v1_regressor' in active_systems:
            from predictions.mlb.prediction_systems.xgboost_v1_regressor_predictor import XGBoostV1RegressorPredictor
            xgb_model_path = os.environ.get('MLB_XGBOOST_V1_MODEL_PATH')
            xgb_v1 = XGBoostV1RegressorPredictor(
                model_path=xgb_model_path,
                project_id=PROJECT_ID
            )
            xgb_v1.load_model()
            systems['xgboost_v1_regressor'] = xgb_v1
            logger.info("XGBoost V1 Regressor predictor initialized")

        logger.info(f"Initialized {len(systems)} prediction systems")
        _prediction_systems = systems

    return _prediction_systems


def get_predictor():
    """
    Legacy function for backward compatibility.
    Returns the first available predictor system.
    """
    systems = get_prediction_systems()
    if not systems:
        raise RuntimeError("No prediction systems available")
    # Return first system (maintains backward compatibility)
    return next(iter(systems.values()))


def get_bq_client():
    """Lazy-load BigQuery client"""
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        logger.info("Initializing BigQuery client...")
        _bq_client = bigquery.Client(project=PROJECT_ID)
        logger.info("BigQuery client initialized")
    return _bq_client


def get_pubsub_publisher():
    """Lazy-load Pub/Sub publisher"""
    global _pubsub_publisher
    if _pubsub_publisher is None:
        from google.cloud import pubsub_v1
        logger.info("Initializing Pub/Sub publisher...")
        _pubsub_publisher = pubsub_v1.PublisherClient()
        logger.info("Pub/Sub publisher initialized")
    return _pubsub_publisher


@app.route('/', methods=['GET'])
def index():
    """Service info endpoint"""
    systems = get_prediction_systems()

    # Build system info
    systems_info = {}
    for system_id, predictor in systems.items():
        model_info = predictor.model_metadata if hasattr(predictor, 'model_metadata') and predictor.model_metadata else {}
        systems_info[system_id] = {
            'model_id': model_info.get('model_id', 'unknown'),
            'mae': model_info.get('test_mae'),
            'baseline_mae': model_info.get('baseline_mae'),
            'improvement': f"{model_info.get('improvement_pct', 0):.1f}%",
            'features': len(model_info.get('features', []))
        }

    return jsonify({
        'service': 'MLB Prediction Worker',
        'version': '2.0.0',  # Bumped for multi-system support
        'sport': 'MLB',
        'prediction_type': 'pitcher_strikeouts',
        'architecture': 'multi-model',
        'active_systems': list(systems.keys()),
        'systems': systems_info,
        'status': 'healthy'
    }), 200


# Health check endpoint removed - now provided by shared health blueprint
# The blueprint provides: /health (liveness), /ready (readiness), /health/deep (deep checks)


@app.route('/predict', methods=['POST'])
def predict_single():
    """
    Generate prediction for a single pitcher

    Request body:
    {
        "pitcher_lookup": "gerrit-cole",
        "game_date": "2025-06-15",
        "strikeouts_line": 6.5,  // optional
        "features": {}  // optional, will load from BigQuery if not provided
    }

    Returns:
        Prediction result
    """
    start_time = time.time()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        pitcher_lookup = data.get('pitcher_lookup')
        game_date_str = data.get('game_date')
        strikeouts_line = data.get('strikeouts_line')
        features = data.get('features')

        if not pitcher_lookup:
            return jsonify({'error': 'pitcher_lookup is required'}), 400

        if not game_date_str:
            return jsonify({'error': 'game_date is required'}), 400

        # Parse date (resolve TODAY literal)
        if game_date_str.upper() == 'TODAY':
            game_date_str = date.today().isoformat()
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        predictor = get_predictor()

        # Load features if not provided
        if not features:
            features = predictor.load_pitcher_features(pitcher_lookup, game_date)
            if not features:
                return jsonify({
                    'error': f'No features found for {pitcher_lookup}',
                    'pitcher_lookup': pitcher_lookup,
                    'game_date': game_date_str
                }), 404

        # Generate prediction
        prediction = predictor.predict(
            pitcher_lookup=pitcher_lookup,
            features=features,
            strikeouts_line=strikeouts_line
        )

        prediction['game_date'] = game_date_str
        prediction['duration_seconds'] = round(time.time() - start_time, 3)

        return jsonify(prediction), 200

    except Exception as e:
        logger.error(f"Prediction error: {e}", exc_info=True)
        # Send alert for prediction failure
        send_mlb_alert(
            severity='warning',
            title='MLB Prediction Failed',
            message=str(e),
            context={
                'endpoint': '/predict',
                'pitcher_lookup': data.get('pitcher_lookup') if 'data' in dir() else None,
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


def run_multi_system_batch_predictions(game_date: date, pitcher_lookups: Optional[List[str]] = None) -> List[Dict]:
    """
    Run batch predictions across all active systems

    OPTIMIZATION: Uses shared feature loader to avoid redundant BigQuery queries.
    Previously each system would call batch_predict() separately, executing the
    same query 3 times. Now we load features ONCE and pass to all systems.

    Expected improvement: 66% reduction in BigQuery queries, 30-40% faster batch times.

    Args:
        game_date: Game date
        pitcher_lookups: Optional list of pitcher lookups to filter

    Returns:
        List[Dict]: All predictions from all systems (multiple rows per pitcher)
    """
    all_predictions = []
    systems = get_prediction_systems()

    if not systems:
        logger.error("No prediction systems available", exc_info=True)
        return []

    # OPTIMIZATION: Load features ONCE using shared feature loader
    # This avoids redundant BigQuery queries (previously 3x queries, now 1x)
    from predictions.mlb.pitcher_loader import (
        load_batch_features, load_schedule_context, _normalize_pitcher_name,
    )
    from predictions.mlb.supplemental_loader import load_supplemental_by_pitcher

    logger.info(f"Loading features for {game_date} (pitcher_lookups={pitcher_lookups})")
    features_by_pitcher = load_batch_features(
        game_date=game_date,
        pitcher_lookups=pitcher_lookups,
        project_id=PROJECT_ID
    )

    if not features_by_pitcher:
        logger.warning(f"No pitchers found for {game_date}")
        return []

    logger.info(f"Loaded features for {len(features_by_pitcher)} pitchers")

    # Session 519: Load schedule to get game_pk, is_home, pitcher_name for today's games.
    # load_batch_features queries pitcher_game_summary for PAST games only, so game_id and
    # is_home were always NULL in the prediction dict, causing BQ insert failures downstream.
    # Returns two lookups: by_pitcher (normalized name) and by_team (team_abbr).
    # Pitcher-name match is tried first (handles team changes like OAK→ATH).
    sched_by_pitcher, sched_by_team = load_schedule_context(
        game_date=game_date, project_id=PROJECT_ID
    )

    # Load supplemental data (umpire K-rate, weather) for signal evaluation
    supplemental_by_pitcher = load_supplemental_by_pitcher(
        game_date=game_date,
        pitcher_lookups=pitcher_lookups,
        project_id=PROJECT_ID
    )

    # For each pitcher, run predictions through ALL active systems
    for pitcher_lookup, features in features_by_pitcher.items():
        # Extract game context from features
        team_abbr = features.get('team_abbr')
        opponent_team_abbr = features.get('opponent_team_abbr')
        strikeouts_line = features.get('strikeouts_line')

        # Run prediction through each active system
        for system_id, predictor in systems.items():
            try:
                # Call system's predict() with preloaded features
                prediction = predictor.predict(
                    pitcher_lookup=pitcher_lookup,
                    features=features,
                    strikeouts_line=strikeouts_line
                )

                # Add metadata
                prediction['system_id'] = system_id
                prediction['game_date'] = game_date.isoformat()
                prediction['team_abbr'] = team_abbr
                prediction['opponent_team_abbr'] = opponent_team_abbr

                # Session 519: Populate game_id, is_home, pitcher_name from schedule.
                # These were always NULL, causing game_pk insert failures and wrong
                # edge floor gating in the best bets exporter.
                # Try pitcher name first (handles team renames like OAK→ATH), then team.
                norm_name = _normalize_pitcher_name(pitcher_lookup)
                sched = sched_by_pitcher.get(norm_name) or sched_by_team.get(team_abbr) or {}
                prediction['game_id'] = str(sched['game_pk']) if sched.get('game_pk') else None
                prediction['is_home'] = sched.get('is_home')
                prediction['pitcher_name'] = sched.get('pitcher_name')

                all_predictions.append(prediction)

            except Exception as e:
                logger.error(f"Prediction failed for {pitcher_lookup} using {system_id}: {e}", exc_info=True)
                # Circuit breaker: Continue with other systems even if one fails
                continue

    logger.info(f"Generated {len(all_predictions)} predictions from {len(systems)} systems")
    return all_predictions


@app.route('/predict-batch', methods=['POST'])
def predict_batch():
    """
    Generate predictions for all pitchers on a game date

    Request body:
    {
        "game_date": "2025-06-15",
        "pitcher_lookups": ["gerrit-cole", "shohei-ohtani"],  // optional
        "write_to_bigquery": true  // optional, default false
    }

    Returns:
        List of predictions (multiple per pitcher if multiple systems active)
    """
    start_time = time.time()

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        game_date_str = data.get('game_date')
        pitcher_lookups = data.get('pitcher_lookups')
        write_to_bigquery = data.get('write_to_bigquery', True)

        if not game_date_str:
            return jsonify({'error': 'game_date is required'}), 400

        # Resolve TODAY literal
        if game_date_str.upper() == 'TODAY':
            game_date_str = date.today().isoformat()

        # Parse date
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        # Generate batch predictions across all active systems
        predictions = run_multi_system_batch_predictions(game_date, pitcher_lookups)

        # Write to BigQuery if requested
        if write_to_bigquery and predictions:
            rows_written = write_predictions_to_bigquery(predictions, game_date)
            logger.info(f"Wrote {rows_written} predictions to BigQuery")

        # Group predictions by system for response summary
        systems_used = list(set(p.get('system_id', 'unknown') for p in predictions))

        return jsonify({
            'game_date': game_date_str,
            'predictions_count': len(predictions),
            'systems_used': systems_used,
            'predictions': predictions,
            'written_to_bigquery': write_to_bigquery,
            'duration_seconds': round(time.time() - start_time, 3)
        }), 200

    except Exception as e:
        logger.error(f"Batch prediction error: {e}", exc_info=True)
        # Send alert for batch prediction failure (critical - affects all predictions for a date)
        send_mlb_alert(
            severity='critical',
            title='MLB Batch Prediction Failed',
            message=str(e),
            context={
                'endpoint': '/predict-batch',
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


@app.route('/execute-shadow-mode', methods=['POST'])
def execute_shadow_mode():
    """
    Execute shadow mode predictions (V1.4 vs V1.6 comparison)

    Request body:
    {
        "game_date": "2025-06-15",  // optional, default: today
        "dry_run": false  // optional, default: false
    }

    Returns:
        Summary of shadow mode execution
    """
    start_time = time.time()

    try:
        data = request.get_json() or {}

        game_date_str = data.get('game_date')
        dry_run = data.get('dry_run', False)

        # Parse date
        if game_date_str:
            if game_date_str.upper() == 'TODAY':
                game_date = date.today()
            else:
                game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        else:
            game_date = date.today()

        logger.info(f"Executing shadow mode for {game_date}, dry_run={dry_run}")

        # Import and run shadow mode
        from predictions.mlb.shadow_mode_runner import run_shadow_mode
        result = run_shadow_mode(game_date, dry_run=dry_run)

        result['duration_seconds'] = round(time.time() - start_time, 3)

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Shadow mode error: {e}", exc_info=True)
        # Send alert for shadow mode failure
        send_mlb_alert(
            severity='warning',
            title='MLB Shadow Mode Failed',
            message=str(e),
            context={
                'endpoint': '/execute-shadow-mode',
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'status': 'failed',
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


@app.route('/best-bets', methods=['POST'])
def generate_best_bets():
    """
    Generate signal-based best bets for a game date.

    Runs the full pipeline: predictions → signals → filters → ranking → ultra → BQ.
    Wires supplemental data (umpire K-rate, weather) into signal evaluation.

    Request body:
    {
        "game_date": "2026-06-15",
        "dry_run": false  // optional, default: false
    }
    """
    start_time = time.time()

    try:
        data = request.get_json() or {}
        game_date_str = data.get('game_date')
        dry_run = data.get('dry_run', False)

        if not game_date_str:
            return jsonify({'error': 'game_date is required'}), 400

        # Resolve TODAY literal
        if game_date_str.upper() == 'TODAY':
            game_date_str = date.today().isoformat()
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()

        # 1. Generate predictions across all active systems
        predictions = run_multi_system_batch_predictions(game_date)

        if not predictions:
            return jsonify({
                'game_date': game_date_str,
                'best_bets': [],
                'message': 'No predictions generated',
                'duration_seconds': round(time.time() - start_time, 3)
            }), 200

        # Write raw predictions to BQ — skip if predictions already exist for this date
        # to avoid duplication (daily cron runs /predict-batch separately).
        existing = _count_predictions_for_date(game_date)
        if existing == 0:
            rows_written = write_predictions_to_bigquery(predictions, game_date)
            logger.info(f"Wrote {rows_written} raw predictions to BigQuery")
        else:
            logger.info(
                f"Skipping raw prediction write — {existing} rows already exist "
                f"for {game_date} in pitcher_strikeouts"
            )

        # 2. Load features and supplemental for signal evaluation
        from predictions.mlb.pitcher_loader import load_batch_features
        from predictions.mlb.supplemental_loader import load_supplemental_by_pitcher

        features_by_pitcher = load_batch_features(
            game_date=game_date, project_id=PROJECT_ID
        )
        supplemental_by_pitcher = load_supplemental_by_pitcher(
            game_date=game_date, project_id=PROJECT_ID
        )

        # 3. Run best bets pipeline
        from ml.signals.mlb.best_bets_exporter import MLBBestBetsExporter

        exporter = MLBBestBetsExporter(project_id=PROJECT_ID)
        best_bets = exporter.export(
            predictions=predictions,
            game_date=game_date_str,
            features_by_pitcher=features_by_pitcher,
            supplemental_by_pitcher=supplemental_by_pitcher,
            dry_run=dry_run,
        )

        # 4. Publish completion event
        publish_completion_event(game_date_str, len(predictions))

        n_ultra = sum(1 for p in best_bets if p.get('ultra_tier'))
        return jsonify({
            'game_date': game_date_str,
            'predictions_count': len(predictions),
            'best_bets_count': len(best_bets),
            'ultra_count': n_ultra,
            'dry_run': dry_run,
            'best_bets': [
                {
                    'pitcher_lookup': p.get('pitcher_lookup'),
                    'recommendation': p.get('recommendation'),
                    'edge': p.get('edge'),
                    'signal_tags': p.get('signal_tags', []),
                    'ultra_tier': p.get('ultra_tier', False),
                    'rank': p.get('rank'),
                    'pick_angles': p.get('pick_angles', []),
                }
                for p in best_bets
            ],
            'duration_seconds': round(time.time() - start_time, 3)
        }), 200

    except Exception as e:
        logger.error(f"Best bets error: {e}", exc_info=True)
        send_mlb_alert(
            severity='critical',
            title='MLB Best Bets Generation Failed',
            message=str(e),
            context={
                'endpoint': '/best-bets',
                'game_date': data.get('game_date') if 'data' in dir() else None,
                'error_type': type(e).__name__
            }
        )
        return jsonify({
            'error': str(e),
            'duration_seconds': round(time.time() - start_time, 3)
        }), 500


@app.route('/pubsub', methods=['POST'])
def handle_pubsub():
    """
    Handle Pub/Sub push message

    Message format:
    {
        "game_date": "2025-06-15",
        "pitcher_lookup": "gerrit-cole",  // optional, for single pitcher
        "write_to_bigquery": true
    }
    """
    start_time = time.time()

    try:
        envelope = request.get_json()
        if not envelope:
            return ('No Pub/Sub message received', 400)

        pubsub_message = envelope.get('message', {})
        if not pubsub_message:
            return ('Invalid Pub/Sub message format', 400)

        # Decode message
        message_data = base64.b64decode(pubsub_message['data']).decode('utf-8')
        data = json.loads(message_data)

        logger.info(f"Received Pub/Sub message: {data}")

        game_date_str = data.get('game_date')
        pitcher_lookup = data.get('pitcher_lookup')
        write_to_bigquery = data.get('write_to_bigquery', True)

        if not game_date_str:
            logger.error("game_date is required", exc_info=True)
            return ('game_date is required', 400)

        # Resolve TODAY literal
        if game_date_str.upper() == 'TODAY':
            game_date_str = date.today().isoformat()
        game_date = datetime.strptime(game_date_str, '%Y-%m-%d').date()
        predictor = get_predictor()

        if pitcher_lookup:
            # Single pitcher prediction
            features = predictor.load_pitcher_features(pitcher_lookup, game_date)
            if features:
                prediction = predictor.predict(
                    pitcher_lookup=pitcher_lookup,
                    features=features,
                    strikeouts_line=data.get('strikeouts_line')
                )
                predictions = [prediction]
            else:
                logger.warning(f"No features for {pitcher_lookup}")
                predictions = []
        else:
            # Batch prediction
            predictions = predictor.batch_predict(game_date=game_date)

        # Write to BigQuery
        if write_to_bigquery and predictions:
            rows_written = write_predictions_to_bigquery(predictions, game_date)
            logger.info(f"Wrote {rows_written} predictions to BigQuery")

        # Publish completion event
        publish_completion_event(game_date_str, len(predictions))

        logger.info(f"Processed {len(predictions)} predictions in {time.time() - start_time:.2f}s")
        return ('', 204)

    except Exception as e:
        logger.error(f"Pub/Sub handler error: {e}", exc_info=True)
        # Send alert for Pub/Sub handler failure (critical - production trigger)
        send_mlb_alert(
            severity='critical',
            title='MLB Prediction Worker Pub/Sub Error',
            message=str(e),
            context={
                'endpoint': '/pubsub',
                'error_type': type(e).__name__
            }
        )
        return ('Internal Server Error', 500)


def _count_predictions_for_date(game_date: date) -> int:
    """Check if predictions already exist for a game date."""
    try:
        client = get_bq_client()
        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{PROJECT_ID}.{PREDICTIONS_TABLE}`
        WHERE game_date = '{game_date.isoformat()}'
        """
        rows = list(client.query(query).result())
        return rows[0].cnt if rows else 0
    except Exception as e:
        logger.warning(f"Could not check existing predictions: {e}")
        return 0  # Fail open — write if check fails


def write_predictions_to_bigquery(predictions: List[Dict], game_date: date) -> int:
    """
    Write predictions to BigQuery

    Args:
        predictions: List of prediction dicts (may include multiple systems per pitcher)
        game_date: Game date

    Returns:
        int: Number of rows written
    """
    if not predictions:
        return 0

    client = get_bq_client()

    # Format rows for BigQuery
    rows = []
    for pred in predictions:
        row = {
            'prediction_id': str(uuid.uuid4()),
            'game_date': game_date.isoformat(),
            'game_id': pred.get('game_id'),
            'pitcher_lookup': pred['pitcher_lookup'],
            'pitcher_name': pred.get('pitcher_name'),
            'team_abbr': pred.get('team_abbr'),
            'opponent_team_abbr': pred.get('opponent_team_abbr'),
            'is_home': pred.get('is_home'),

            # Prediction
            'predicted_strikeouts': pred['predicted_strikeouts'],
            'confidence': pred['confidence'],
            'model_version': pred.get('model_version'),  # Keep for backward compatibility
            'system_id': pred.get('system_id'),  # NEW: Multi-model support

            # Line info
            'strikeouts_line': pred.get('strikeouts_line'),
            'over_odds': pred.get('over_odds'),
            'under_odds': pred.get('under_odds'),
            'line_minutes_before_game': pred.get('line_minutes_before_game'),  # v3.6

            # Recommendation
            'recommendation': pred['recommendation'],
            'edge': pred.get('edge'),

            # Metadata
            'created_at': datetime.utcnow().isoformat(),
            'processed_at': datetime.utcnow().isoformat()
        }
        rows.append(row)

    # Insert rows
    try:
        table_ref = f"{PROJECT_ID}.{PREDICTIONS_TABLE}"
        errors = client.insert_rows_json(table_ref, rows)

        if errors:
            logger.error(f"BigQuery insert errors: {errors}", exc_info=True)
            return 0

        logger.info(f"Inserted {len(rows)} rows to {table_ref}")
        return len(rows)

    except Exception as e:
        logger.error(f"BigQuery write error: {e}", exc_info=True)
        return 0


def publish_completion_event(game_date: str, prediction_count: int):
    """
    Publish completion event to Pub/Sub

    Args:
        game_date: Game date string
        prediction_count: Number of predictions generated
    """
    try:
        publisher = get_pubsub_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, 'mlb-phase5-predictions-complete')

        message = {
            'game_date': game_date,
            'predictions_count': prediction_count,
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'mlb-prediction-worker'
        }

        message_bytes = json.dumps(message).encode('utf-8')
        future = publisher.publish(topic_path, data=message_bytes)
        future.result()

        logger.info(f"Published completion event for {game_date}")

    except Exception as e:
        logger.error(f"Failed to publish completion event: {e}", exc_info=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
