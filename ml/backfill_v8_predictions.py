#!/usr/bin/env python3
"""
Backfill CatBoost predictions for historical games.

Supports both V8 (historical training) and V9 (current season training).

This script:
1. Queries all dates from ml_feature_store_v2
2. For each date, gets features and betting lines
3. Runs CatBoost.predict() for each player
4. Inserts predictions to player_prop_predictions table

Usage:
    # Backfill with V9 (default)
    PYTHONPATH=. python ml/backfill_v8_predictions.py --start-date 2026-01-09 --end-date 2026-01-31

    # Backfill with V8
    PYTHONPATH=. python ml/backfill_v8_predictions.py --model-version v8 --start-date 2026-01-01

    # Dry run (no writes)
    PYTHONPATH=. python ml/backfill_v8_predictions.py --dry-run
"""

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('backfill_v8.log')
    ]
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import bigquery
from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8
from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9

# Constants
PROJECT_ID = 'nba-props-platform'
FEATURE_STORE_TABLE = 'nba_predictions.ml_feature_store_v2'
BETTING_PROPS_TABLE = 'nba_raw.bettingpros_player_points_props'
PREDICTIONS_TABLE = 'nba_predictions.player_prop_predictions'
BATCH_SIZE = 500  # Insert batch size

# Global model version (set by main())
CURRENT_MODEL_VERSION = 'v9'
CURRENT_SYSTEM_ID = 'catboost_v9'

# Feature names in the feature store (must match order) - now 33 features
FEATURE_NAMES = [
    # Base 25 features
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    # Extra 8 features (v33)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10"
]


def get_all_dates(client: bigquery.Client) -> List[date]:
    """Get all dates from feature store, ordered ascending."""
    query = f"""
    SELECT DISTINCT game_date
    FROM `{FEATURE_STORE_TABLE}`
    ORDER BY game_date ASC
    """
    results = client.query(query).result()
    return [row.game_date for row in results]


def get_features_and_lines_for_date(
    client: bigquery.Client,
    game_date: date
) -> List[Dict]:
    """
    Get features and betting lines for all players on a given date.

    Returns list of dicts with player_lookup, game_id, features, and betting_line.
    """
    query = f"""
    WITH features AS (
        SELECT
            f.player_lookup,
            f.universal_player_id,
            f.game_id,
            f.game_date,
            f.features,
            f.feature_quality_score,
            f.is_home,
            f.days_rest
        FROM `{FEATURE_STORE_TABLE}` f
        WHERE f.game_date = @game_date
          AND f.feature_count IN (33, 37)  -- Accept v2_33features and v2_37features
    ),
    best_lines AS (
        SELECT
            player_lookup,
            game_date,
            -- Get consensus line (average across books)
            AVG(points_line) as avg_line,
            MIN(points_line) as min_line,
            MAX(points_line) as max_line,
            COUNT(DISTINCT bookmaker) as num_books
        FROM `{BETTING_PROPS_TABLE}`
        WHERE game_date = @game_date
          AND bet_side = 'over'  -- Over lines have the threshold
          AND points_line IS NOT NULL
        GROUP BY player_lookup, game_date
    )
    SELECT
        f.player_lookup,
        f.universal_player_id,
        f.game_id,
        f.game_date,
        f.features,
        f.feature_quality_score,
        f.is_home,
        f.days_rest,
        b.avg_line as betting_line,
        b.num_books,
        CASE WHEN b.avg_line IS NOT NULL THEN TRUE ELSE FALSE END as has_prop_line
    FROM features f
    LEFT JOIN best_lines b
        ON f.player_lookup = b.player_lookup
        AND f.game_date = b.game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    results = client.query(query, job_config=job_config).result()

    players = []
    for row in results:
        # Convert features array to dict
        feature_dict = {}
        if row.features:
            for i, name in enumerate(FEATURE_NAMES):
                if i < len(row.features):
                    feature_dict[name] = row.features[i]

        # Add quality score and feature version
        feature_dict['feature_quality_score'] = float(row.feature_quality_score or 80.0)
        feature_dict['feature_version'] = 'v2_33features'  # Required by CatBoostV8

        players.append({
            'player_lookup': row.player_lookup,
            'universal_player_id': row.universal_player_id,
            'game_id': row.game_id,
            'game_date': row.game_date,
            'features': feature_dict,
            'betting_line': float(row.betting_line) if row.betting_line else None,
            'has_prop_line': row.has_prop_line,
            'is_home': row.is_home,
            'days_rest': row.days_rest,
        })

    return players


def run_prediction(
    model: CatBoostV8,
    player_data: Dict
) -> Optional[Dict]:
    """
    Run CatBoostV8 prediction for a single player.

    Returns formatted prediction dict for BigQuery, or None if failed.
    """
    try:
        features = player_data['features']
        betting_line = player_data['betting_line']

        # Use season average as fallback line if no prop line
        if betting_line is None:
            betting_line = features.get('points_avg_season', 15.0)

        # Run prediction with all 33 features
        result = model.predict(
            player_lookup=player_data['player_lookup'],
            features=features,
            betting_line=betting_line,
            # Pass extra features explicitly (from feature store v33)
            vegas_line=features.get('vegas_points_line'),
            vegas_opening=features.get('vegas_opening_line'),
            opponent_avg=features.get('avg_points_vs_opponent'),
            games_vs_opponent=int(features.get('games_vs_opponent', 0)),
            minutes_avg_last_10=features.get('minutes_avg_last_10'),
            ppm_avg_last_10=features.get('ppm_avg_last_10'),
        )

        if result.get('predicted_points') is None:
            return None

        # Determine recommendation based on has_prop_line
        has_prop_line = player_data['has_prop_line']
        if has_prop_line:
            recommendation = result['recommendation']
            current_line = player_data['betting_line']
            line_margin = round(result['predicted_points'] - current_line, 2)
        else:
            recommendation = 'NO_LINE'
            current_line = None
            line_margin = None

        # Format for BigQuery
        prediction = {
            'prediction_id': str(uuid.uuid4()),
            'system_id': CURRENT_SYSTEM_ID,
            'player_lookup': player_data['player_lookup'],
            'universal_player_id': player_data['universal_player_id'],
            'game_date': player_data['game_date'].isoformat(),
            'game_id': player_data['game_id'],
            'prediction_version': 1,
            'predicted_points': round(result['predicted_points'], 1),
            'confidence_score': round(result['confidence_score'], 2),
            'recommendation': recommendation,
            'current_points_line': round(current_line, 1) if current_line else None,
            'line_margin': line_margin,
            'is_active': True,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': None,
            'superseded_by': None,
            'model_version': CURRENT_SYSTEM_ID,
            'has_prop_line': has_prop_line,
            'line_source': 'ACTUAL_PROP' if has_prop_line else 'ESTIMATED_AVG',
            'estimated_line_value': round(betting_line, 1) if not has_prop_line else None,
            'estimation_method': 'points_avg_season' if not has_prop_line else None,
            'feature_importance': json.dumps({
                'model_type': result.get('model_type'),
                'feature_count': result.get('feature_count', 33),
            }),
            'completeness_percentage': features.get('feature_quality_score', 80.0),
            'is_production_ready': True,
            'backfill_bootstrap_mode': True,
            'processing_decision_reason': 'backfill_v8',
            # v4.1: Store feature snapshot for debugging and reproducibility
            'features_snapshot': json.dumps({
                'points_avg_last_5': features.get('points_avg_last_5'),
                'points_avg_last_10': features.get('points_avg_last_10'),
                'points_avg_season': features.get('points_avg_season'),
                'vegas_points_line': features.get('vegas_points_line'),
                'has_vegas_line': features.get('has_vegas_line'),
                'minutes_avg_last_10': features.get('minutes_avg_last_10'),
                'ppm_avg_last_10': features.get('ppm_avg_last_10'),
            }),
            'feature_version': features.get('feature_version', 'v2_33features'),
            'feature_quality_score': features.get('feature_quality_score', 80.0),
        }

        return prediction

    except Exception as e:
        logger.error(f"Prediction failed for {player_data['player_lookup']}: {e}")
        return None


def insert_predictions(
    client: bigquery.Client,
    predictions: List[Dict],
    dry_run: bool = False
) -> int:
    """
    Insert predictions to BigQuery.

    Returns number of rows inserted.
    """
    if not predictions:
        return 0

    if dry_run:
        logger.info(f"DRY RUN: Would insert {len(predictions)} predictions")
        return len(predictions)

    table_ref = client.dataset('nba_predictions').table('player_prop_predictions')

    errors = client.insert_rows_json(table_ref, predictions)

    if errors:
        logger.error(f"Insert errors: {errors[:5]}")  # Log first 5 errors
        return 0

    return len(predictions)


def backfill_date(
    client: bigquery.Client,
    model: CatBoostV8,
    game_date: date,
    dry_run: bool = False
) -> Tuple[int, int]:
    """
    Backfill predictions for a single date.

    Returns (total_players, successful_predictions).
    """
    # Get features and lines
    players = get_features_and_lines_for_date(client, game_date)

    if not players:
        return 0, 0

    # Generate predictions
    predictions = []
    for player_data in players:
        pred = run_prediction(model, player_data)
        if pred:
            predictions.append(pred)

    # Insert in batches
    total_inserted = 0
    for i in range(0, len(predictions), BATCH_SIZE):
        batch = predictions[i:i + BATCH_SIZE]
        inserted = insert_predictions(client, batch, dry_run)
        total_inserted += inserted

    return len(players), total_inserted


def main():
    parser = argparse.ArgumentParser(description='Backfill CatBoost predictions')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--model-version', type=str, default='v9', choices=['v8', 'v9'],
                        help='Model version to use (default: v9)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no writes)')
    args = parser.parse_args()

    model_version = args.model_version
    system_id = f'catboost_{model_version}'

    logger.info("=" * 60)
    logger.info(f"CatBoost {model_version.upper()} Backfill Starting")
    logger.info("=" * 60)

    # Initialize
    client = bigquery.Client(project=PROJECT_ID)

    if model_version == 'v9':
        logger.info("Loading CatBoost V9 (current season training)...")
        model = CatBoostV9()
    else:
        logger.info("Loading CatBoost V8 (historical training)...")
        model = CatBoostV8()

    if model.model is None:
        logger.error(f"Failed to load CatBoost {model_version.upper()} model!")
        sys.exit(1)

    # Store model version for use in generate_prediction
    global CURRENT_MODEL_VERSION, CURRENT_SYSTEM_ID
    CURRENT_MODEL_VERSION = model_version
    CURRENT_SYSTEM_ID = system_id

    logger.info("Model loaded successfully")

    # Get all dates
    all_dates = get_all_dates(client)
    logger.info(f"Found {len(all_dates)} dates in feature store")

    # Filter by start/end date if provided
    if args.start_date:
        start = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        all_dates = [d for d in all_dates if d >= start]
        logger.info(f"Filtered to {len(all_dates)} dates (starting {args.start_date})")

    if args.end_date:
        end = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        all_dates = [d for d in all_dates if d <= end]
        logger.info(f"Filtered to {len(all_dates)} dates (ending {args.end_date})")

    # Process each date
    total_players = 0
    total_predictions = 0
    start_time = time.time()

    for i, game_date in enumerate(all_dates):
        date_start = time.time()

        players, predictions = backfill_date(client, model, game_date, args.dry_run)

        total_players += players
        total_predictions += predictions

        date_duration = time.time() - date_start
        elapsed = time.time() - start_time

        # Progress logging
        pct = (i + 1) / len(all_dates) * 100
        rate = total_predictions / elapsed if elapsed > 0 else 0
        eta_seconds = (len(all_dates) - i - 1) * (elapsed / (i + 1)) if i > 0 else 0
        eta_minutes = eta_seconds / 60

        logger.info(
            f"[{i+1}/{len(all_dates)}] {game_date}: "
            f"{predictions}/{players} predictions "
            f"({date_duration:.1f}s) | "
            f"Total: {total_predictions:,} | "
            f"Progress: {pct:.1f}% | "
            f"Rate: {rate:.0f}/s | "
            f"ETA: {eta_minutes:.0f}m"
        )

    # Summary
    duration = time.time() - start_time
    logger.info("=" * 60)
    logger.info("BACKFILL COMPLETE")
    logger.info(f"Dates processed: {len(all_dates)}")
    logger.info(f"Total players: {total_players:,}")
    logger.info(f"Total predictions: {total_predictions:,}")
    logger.info(f"Duration: {duration/60:.1f} minutes")
    logger.info(f"Rate: {total_predictions/duration:.0f} predictions/second")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
