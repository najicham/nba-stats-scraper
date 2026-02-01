"""
Monthly Model Retrain Cloud Function

Automatically retrains CatBoost model on recent data and evaluates against baseline.
Runs on 1st of each month via Cloud Scheduler.

Workflow:
1. Train on last 60 days of data
2. Evaluate on last 7 days with real prop lines
3. Compare to V8 baseline
4. Store results in ml_experiments table
5. Send Slack notification with recommendation
6. If significantly better, mark for shadow mode

Deployment:
    cd orchestration/cloud_functions/monthly_retrain
    ./deploy.sh

Scheduler (1st of month at 6 AM ET):
    gcloud scheduler jobs create http monthly-retrain-job \
        --schedule "0 6 1 * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method POST

Session 58 - Monthly Retraining Infrastructure
"""

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, Any, Tuple

import functions_framework
from google.cloud import bigquery
from google.cloud import storage
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

# Lazy import for catboost (large library)
cb = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'nba-ml-models')
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')

# V8 Baseline (January 2026)
V8_BASELINE = {
    'mae': 5.36,
    'hit_rate_all': 50.24,
    'hit_rate_high_edge': 62.8,
    'hit_rate_premium': 78.5,
}

FEATURES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    "fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back", "playoff_game",
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    "team_pace", "team_off_rating", "team_win_pct",
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10",
]


def get_catboost():
    """Lazy load catboost."""
    global cb
    if cb is None:
        import catboost
        cb = catboost
    return cb


def compute_dates(train_days: int = 60, eval_days: int = 7) -> Dict[str, str]:
    """Compute training and evaluation date ranges."""
    yesterday = date.today() - timedelta(days=1)
    eval_end = yesterday
    eval_start = eval_end - timedelta(days=eval_days - 1)
    train_end = eval_start - timedelta(days=1)
    train_start = train_end - timedelta(days=train_days - 1)

    return {
        'train_start': train_start.isoformat(),
        'train_end': train_end.isoformat(),
        'eval_start': eval_start.isoformat(),
        'eval_end': eval_end.isoformat(),
    }


def load_training_data(client: bigquery.Client, start: str, end: str) -> pd.DataFrame:
    """Load training data from feature store."""
    query = f"""
    SELECT mf.features, pgs.points as actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND mf.feature_count >= 33
      AND pgs.points IS NOT NULL AND pgs.minutes_played > 0
    """
    return client.query(query).to_dataframe()


def load_eval_data(client: bigquery.Client, start: str, end: str) -> pd.DataFrame:
    """Load evaluation data with real prop lines."""
    query = f"""
    WITH lines AS (
      SELECT game_date, player_lookup, points_line as line
      FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
      WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
        AND game_date BETWEEN '{start}' AND '{end}'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
    )
    SELECT mf.features, pgs.points as actual_points, l.line as vegas_line
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    JOIN lines l ON mf.player_lookup = l.player_lookup AND mf.game_date = l.game_date
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND mf.feature_count >= 33 AND pgs.points IS NOT NULL
      AND (l.line - FLOOR(l.line)) IN (0, 0.5)
    """
    return client.query(query).to_dataframe()


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """Prepare feature matrix."""
    X = pd.DataFrame([row[:33] for row in df['features'].tolist()], columns=FEATURES)
    X = X.fillna(X.median())
    y = df['actual_points'].astype(float)
    return X, y


def compute_hit_rate(preds: np.ndarray, actuals: np.ndarray, lines: np.ndarray,
                     min_edge: float = 1.0) -> Tuple[float, int]:
    """Compute hit rate for given edge threshold."""
    edges = preds - lines
    mask = np.abs(edges) >= min_edge
    if mask.sum() == 0:
        return None, 0

    b_actual = actuals[mask]
    b_lines = lines[mask]
    b_over = edges[mask] > 0

    wins = ((b_actual > b_lines) & b_over) | ((b_actual < b_lines) & ~b_over)
    pushes = b_actual == b_lines
    graded = len(b_actual) - pushes.sum()

    return round(wins.sum() / graded * 100, 2) if graded > 0 else None, int(graded)


def train_and_evaluate(dates: Dict[str, str]) -> Dict[str, Any]:
    """Train model and evaluate against baseline."""
    catboost = get_catboost()
    client = bigquery.Client(project=PROJECT_ID)

    # Load data
    logger.info(f"Loading training data: {dates['train_start']} to {dates['train_end']}")
    df_train = load_training_data(client, dates['train_start'], dates['train_end'])
    logger.info(f"Loaded {len(df_train)} training samples")

    logger.info(f"Loading eval data: {dates['eval_start']} to {dates['eval_end']}")
    df_eval = load_eval_data(client, dates['eval_start'], dates['eval_end'])
    logger.info(f"Loaded {len(df_eval)} eval samples")

    if len(df_train) < 1000:
        raise ValueError(f"Not enough training data: {len(df_train)}")
    if len(df_eval) < 100:
        raise ValueError(f"Not enough eval data: {len(df_eval)}")

    # Prepare features
    X_train_full, y_train_full = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    lines = df_eval['vegas_line'].values

    X_train, X_val, y_train, y_val = train_test_split(
        X_train_full, y_train_full, test_size=0.15, random_state=42
    )

    # Train
    logger.info("Training CatBoost model...")
    model = catboost.CatBoostRegressor(
        iterations=1000, learning_rate=0.05, depth=6,
        l2_leaf_reg=3, random_seed=42, verbose=0, early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=False)

    # Evaluate
    logger.info("Evaluating model...")
    preds = model.predict(X_eval)
    mae = mean_absolute_error(y_eval, preds)

    hr_all, bets_all = compute_hit_rate(preds, y_eval.values, lines, min_edge=1.0)
    hr_high, bets_high = compute_hit_rate(preds, y_eval.values, lines, min_edge=5.0)

    # Premium approximation
    std = X_eval['points_std_last_10'].values
    edges = np.abs(preds - lines)
    premium_mask = (std < 6) & (edges >= 3)
    if premium_mask.sum() > 0:
        hr_prem, bets_prem = compute_hit_rate(
            preds[premium_mask], y_eval.values[premium_mask], lines[premium_mask], min_edge=0
        )
    else:
        hr_prem, bets_prem = None, 0

    results = {
        'mae': round(mae, 4),
        'hit_rate_all': hr_all,
        'bets_all': bets_all,
        'hit_rate_high_edge': hr_high,
        'bets_high_edge': bets_high,
        'hit_rate_premium': hr_prem,
        'bets_premium': bets_prem,
        'train_samples': len(df_train),
        'eval_samples': len(df_eval),
    }

    # Save model to GCS
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    month = datetime.now().strftime('%Y-%m')
    model_filename = f"catboost_monthly_{month}_{timestamp}.cbm"

    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET)

    # Save to temp file then upload
    temp_path = f"/tmp/{model_filename}"
    model.save_model(temp_path)

    blob = bucket.blob(f"monthly_retrains/{model_filename}")
    blob.upload_from_filename(temp_path)
    model_path = f"gs://{GCS_BUCKET}/monthly_retrains/{model_filename}"
    logger.info(f"Model saved to {model_path}")

    results['model_path'] = model_path

    return results


def evaluate_vs_baseline(results: Dict[str, Any]) -> Dict[str, Any]:
    """Compare results to V8 baseline."""
    comparison = {
        'mae_diff': round(results['mae'] - V8_BASELINE['mae'], 4),
        'hr_all_diff': round((results['hit_rate_all'] or 0) - V8_BASELINE['hit_rate_all'], 2),
        'hr_high_diff': round((results['hit_rate_high_edge'] or 0) - V8_BASELINE['hit_rate_high_edge'], 2),
    }

    mae_better = results['mae'] < V8_BASELINE['mae']
    hr_better = (results['hit_rate_all'] or 0) > V8_BASELINE['hit_rate_all']

    if mae_better and hr_better:
        comparison['recommendation'] = 'PROMOTE'
        comparison['message'] = 'Model beats V8 on both MAE and hit rate - recommend shadow mode'
    elif mae_better:
        comparison['recommendation'] = 'MIXED'
        comparison['message'] = 'Better MAE but similar/lower hit rate - needs more evaluation'
    elif hr_better:
        comparison['recommendation'] = 'MIXED'
        comparison['message'] = 'Better hit rate but worse MAE - may be overfitting'
    else:
        comparison['recommendation'] = 'KEEP_V8'
        comparison['message'] = 'V8 still better - no promotion recommended'

    return comparison


def register_experiment(client: bigquery.Client, exp_id: str, dates: Dict,
                       results: Dict, comparison: Dict) -> None:
    """Register experiment in ml_experiments table."""
    month = datetime.now().strftime('%b').upper()
    row = {
        'experiment_id': exp_id,
        'experiment_name': f'{month}_MONTHLY_AUTO',
        'experiment_type': 'monthly_retrain',
        'hypothesis': 'Automated monthly retrain on 60 days',
        'config_json': json.dumps({'train_days': 60, 'eval_days': 7, 'features': 33}),
        'train_period': {
            'start_date': dates['train_start'],
            'end_date': dates['train_end'],
            'samples': results['train_samples']
        },
        'eval_period': {
            'start_date': dates['eval_start'],
            'end_date': dates['eval_end'],
            'samples': results['eval_samples']
        },
        'results_json': json.dumps({
            'mae': results['mae'],
            'hit_rate_all': results['hit_rate_all'],
            'hit_rate_high_edge': results['hit_rate_high_edge'],
            'hit_rate_premium': results['hit_rate_premium'],
            'vs_baseline': comparison,
        }),
        'model_path': results['model_path'],
        'status': 'shadow' if comparison['recommendation'] == 'PROMOTE' else 'completed',
        'tags': ['monthly', 'automated'],
        'created_at': datetime.utcnow().isoformat(),
        'completed_at': datetime.utcnow().isoformat(),
    }

    table_id = f"{PROJECT_ID}.nba_predictions.ml_experiments"
    errors = client.insert_rows_json(table_id, [row])
    if errors:
        logger.error(f"Failed to register experiment: {errors}")
    else:
        logger.info(f"Registered experiment {exp_id}")


def send_slack_notification(dates: Dict, results: Dict, comparison: Dict) -> None:
    """Send Slack notification with results."""
    if not SLACK_WEBHOOK:
        logger.warning("No Slack webhook configured")
        return

    import requests

    emoji = {
        'PROMOTE': ':rocket:',
        'MIXED': ':warning:',
        'KEEP_V8': ':no_entry_sign:'
    }.get(comparison['recommendation'], ':question:')

    month = datetime.now().strftime('%B %Y')

    payload = {
        "attachments": [{
            "color": "#36a64f" if comparison['recommendation'] == 'PROMOTE' else "#ff9800",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{emoji} Monthly Retrain Complete - {month}",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*MAE:* {results['mae']:.4f} ({comparison['mae_diff']:+.4f})"},
                        {"type": "mrkdwn", "text": f"*Hit Rate:* {results['hit_rate_all']}% ({comparison['hr_all_diff']:+.2f}%)"},
                        {"type": "mrkdwn", "text": f"*Training:* {results['train_samples']:,} samples"},
                        {"type": "mrkdwn", "text": f"*Eval:* {results['eval_samples']:,} samples"},
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Recommendation:* {comparison['message']}"
                    }
                }
            ]
        }]
    }

    try:
        response = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Slack notification sent")
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")


@functions_framework.http
def monthly_retrain(request):
    """
    HTTP Cloud Function entry point.

    Query params:
        train_days: Days of training data (default: 60)
        eval_days: Days of evaluation data (default: 7)
        dry_run: If 'true', show plan without executing
    """
    try:
        # Parse parameters
        train_days = int(request.args.get('train_days', 60))
        eval_days = int(request.args.get('eval_days', 7))
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        dates = compute_dates(train_days, eval_days)
        exp_id = str(uuid.uuid4())[:8]

        logger.info(f"Monthly retrain started: {exp_id}")
        logger.info(f"Training: {dates['train_start']} to {dates['train_end']}")
        logger.info(f"Evaluation: {dates['eval_start']} to {dates['eval_end']}")

        if dry_run:
            return {
                'status': 'dry_run',
                'dates': dates,
                'message': 'Dry run - would train and evaluate on above dates'
            }, 200

        # Train and evaluate
        results = train_and_evaluate(dates)

        # Compare to baseline
        comparison = evaluate_vs_baseline(results)

        # Register experiment
        client = bigquery.Client(project=PROJECT_ID)
        register_experiment(client, exp_id, dates, results, comparison)

        # Send notification
        send_slack_notification(dates, results, comparison)

        response = {
            'status': 'success',
            'experiment_id': exp_id,
            'dates': dates,
            'results': results,
            'comparison': comparison,
        }

        logger.info(f"Monthly retrain complete: {comparison['recommendation']}")
        return response, 200

    except Exception as e:
        logger.exception(f"Monthly retrain failed: {e}")
        return {'status': 'error', 'message': str(e)}, 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {'status': 'healthy', 'function': 'monthly-retrain'}, 200
