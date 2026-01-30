#!/usr/bin/env python3
"""
ML Experiment Runner

Runs all enabled ML models from the registry against today's games.
Stores predictions in ml_model_predictions table for comparison.

This is the main entry point for the ML experimentation pipeline.

Usage:
    # Run for today
    PYTHONPATH=. python ml/experiment_runner.py

    # Run for specific date
    PYTHONPATH=. python ml/experiment_runner.py --date 2026-01-10

    # Dry run (no BigQuery writes)
    PYTHONPATH=. python ml/experiment_runner.py --dry-run

    # Run specific model only
    PYTHONPATH=. python ml/experiment_runner.py --model catboost_v8
"""

import argparse
import uuid
from datetime import date, datetime
from typing import Dict, List, Optional, Any
import json
import logging
import numpy as np
from google.cloud import bigquery
from dataclasses import dataclass, asdict

from ml.model_loader import ModelInfo, get_cached_model, load_model

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


@dataclass
class ModelPrediction:
    """Single prediction from a model"""
    prediction_id: str
    model_id: str
    player_lookup: str
    game_date: str  # ISO format
    game_id: str
    team_abbr: Optional[str]
    opponent_team_abbr: Optional[str]
    predicted_points: float
    confidence_score: Optional[float]
    recommendation: Optional[str]
    betting_line: Optional[float]
    edge_vs_line: Optional[float]
    vegas_opening_line: Optional[float]
    injury_status: Optional[str]
    injury_warning: bool
    feature_version: str
    feature_count: int
    features_hash: Optional[str]
    prediction_time: str  # ISO format


def get_enabled_models(client: bigquery.Client) -> List[ModelInfo]:
    """Get all enabled models from the registry"""
    query = """
    SELECT
        model_id,
        model_type,
        model_path,
        model_format,
        feature_version,
        feature_count,
        feature_list
    FROM `nba-props-platform.nba_predictions.ml_model_registry`
    WHERE enabled = TRUE
    ORDER BY model_id
    """

    result = client.query(query).result()
    models = []

    for row in result:
        feature_list = None
        if row.feature_list:
            try:
                feature_list = json.loads(row.feature_list)
            except (json.JSONDecodeError, ValueError):
                pass

        models.append(ModelInfo(
            model_id=row.model_id,
            model_type=row.model_type,
            model_path=row.model_path,
            model_format=row.model_format,
            feature_count=row.feature_count,
            feature_list=feature_list
        ))

    return models


def get_players_with_features(
    client: bigquery.Client,
    game_date: date
) -> List[Dict]:
    """Load players with features for the specified date"""
    query = """
    WITH
    -- Base features from feature store (25 features)
    features AS (
        SELECT
            mf.player_lookup,
            mf.game_date,
            mf.game_id,
            mf.features,
            mf.opponent_team_abbr
        FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
        WHERE mf.game_date = @game_date
          AND mf.feature_count = 25
    ),
    -- Vegas lines
    vegas AS (
        SELECT
            game_date,
            player_lookup,
            points_line as vegas_line,
            opening_line as vegas_opening
        FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
        WHERE game_date = @game_date
          AND bookmaker = 'BettingPros Consensus'
          AND bet_side = 'over'
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY processed_at DESC
        ) = 1
    ),
    -- Opponent history
    opponent_history AS (
        SELECT
            pgs1.player_lookup,
            pgs1.game_date,
            AVG(pgs2.points) as avg_points_vs_opponent,
            COUNT(pgs2.points) as games_vs_opponent
        FROM `nba-props-platform.nba_analytics.player_game_summary` pgs1
        LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs2
            ON pgs1.player_lookup = pgs2.player_lookup
            AND pgs1.opponent_team_abbr = pgs2.opponent_team_abbr
            AND pgs2.game_date < pgs1.game_date
            AND pgs2.game_date >= DATE_SUB(pgs1.game_date, INTERVAL 3 YEAR)
        WHERE pgs1.game_date = @game_date
        GROUP BY pgs1.player_lookup, pgs1.game_date
    ),
    -- Minutes/PPM history
    history AS (
        SELECT
            player_lookup,
            game_date,
            team_abbr,
            AVG(minutes_played) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as minutes_avg_last_10,
            AVG(SAFE_DIVIDE(points, minutes_played)) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as ppm_avg_last_10,
            AVG(points) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) as season_avg
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        -- Note: <= is correct here because window function uses "1 PRECEDING" which excludes current row
        -- QUALIFY then selects only the target date row with its pre-computed rolling averages
        WHERE game_date <= @game_date
        QUALIFY game_date = @game_date
    ),
    -- Injury status
    injuries AS (
        SELECT
            player_lookup,
            game_date,
            injury_status
        FROM `nba-props-platform.nba_raw.nbac_injury_report`
        WHERE game_date = @game_date
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY report_hour DESC
        ) = 1
    )

    SELECT
        f.player_lookup,
        f.game_id,
        f.features,
        f.opponent_team_abbr,
        h.team_abbr,
        h.season_avg,
        v.vegas_line,
        v.vegas_opening,
        oh.avg_points_vs_opponent,
        COALESCE(oh.games_vs_opponent, 0) as games_vs_opponent,
        h.minutes_avg_last_10,
        h.ppm_avg_last_10,
        i.injury_status
    FROM features f
    LEFT JOIN history h ON f.player_lookup = h.player_lookup
    LEFT JOIN vegas v ON f.player_lookup = v.player_lookup
    LEFT JOIN opponent_history oh ON f.player_lookup = oh.player_lookup
    LEFT JOIN injuries i ON f.player_lookup = i.player_lookup
    WHERE h.minutes_avg_last_10 IS NOT NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]


def build_feature_vector(
    player_data: Dict,
    feature_count: int,
    feature_list: Optional[List[str]] = None
) -> Optional[np.ndarray]:
    """Build feature vector for a model"""

    # Base 25 features from feature store
    base_features = list(player_data['features'])

    if feature_count == 25:
        return np.array(base_features).reshape(1, -1)

    elif feature_count == 33:
        # V8 model: base + vegas + opponent + minutes/ppm
        season_avg = player_data.get('season_avg') or 10.0
        vegas_line = player_data.get('vegas_line')
        vegas_opening = player_data.get('vegas_opening')

        extra_features = [
            vegas_line if vegas_line is not None else season_avg,
            vegas_opening if vegas_opening is not None else season_avg,
            (vegas_line - vegas_opening) if vegas_line and vegas_opening else 0,
            1.0 if vegas_line is not None else 0.0,
            player_data.get('avg_points_vs_opponent') or season_avg,
            float(player_data.get('games_vs_opponent') or 0),
            player_data.get('minutes_avg_last_10') or 25.0,
            player_data.get('ppm_avg_last_10') or 0.4,
        ]

        return np.array(base_features + extra_features).reshape(1, -1)

    else:
        logger.warning(f"Unknown feature count: {feature_count}")
        return None


def run_model_predictions(
    model: Any,
    model_info: ModelInfo,
    players: List[Dict],
    game_date: date
) -> List[ModelPrediction]:
    """Run predictions for all players using a model"""
    predictions = []
    skipped_out = 0
    skipped_error = 0

    for player_data in players:
        player_lookup = player_data['player_lookup']
        injury_status = player_data.get('injury_status')

        # Skip OUT players
        if injury_status and injury_status.lower() == 'out':
            skipped_out += 1
            continue

        # Build feature vector
        features = build_feature_vector(
            player_data,
            model_info.feature_count,
            model_info.feature_list
        )

        if features is None:
            skipped_error += 1
            continue

        # Run prediction
        try:
            predicted = float(model.predict(features)[0])
            predicted = max(0, min(60, predicted))  # Clamp
        except Exception as e:
            logger.error(f"Prediction error for {player_lookup}: {e}")
            skipped_error += 1
            continue

        # Calculate edge
        vegas_line = player_data.get('vegas_line')
        edge = (predicted - vegas_line) if vegas_line else None

        # Recommendation
        if vegas_line is None:
            recommendation = 'NO_LINE'
        elif edge and edge >= 1.5:
            recommendation = 'OVER'
        elif edge and edge <= -1.5:
            recommendation = 'UNDER'
        else:
            recommendation = 'PASS'

        # Injury warning
        injury_warning = injury_status and injury_status.lower() in ('questionable', 'doubtful')

        # Create prediction record
        predictions.append(ModelPrediction(
            prediction_id=str(uuid.uuid4()),
            model_id=model_info.model_id,
            player_lookup=player_lookup,
            game_date=str(game_date),
            game_id=player_data['game_id'],
            team_abbr=player_data.get('team_abbr'),
            opponent_team_abbr=player_data.get('opponent_team_abbr'),
            predicted_points=round(predicted, 2),
            confidence_score=75.0,  # Default confidence
            recommendation=recommendation,
            betting_line=vegas_line,
            edge_vs_line=round(edge, 2) if edge else None,
            vegas_opening_line=player_data.get('vegas_opening'),
            injury_status=injury_status,
            injury_warning=injury_warning or False,
            feature_version=model_info.feature_count,
            feature_count=model_info.feature_count,
            features_hash=None,  # TODO: compute hash for reproducibility
            prediction_time=datetime.now().isoformat(),
        ))

    logger.info(f"  {model_info.model_id}: {len(predictions)} predictions, "
                f"skipped {skipped_out} OUT, {skipped_error} errors")

    return predictions


def write_predictions(
    client: bigquery.Client,
    predictions: List[ModelPrediction],
    dry_run: bool = False
) -> int:
    """Write predictions to BigQuery"""
    if not predictions:
        return 0

    if dry_run:
        logger.info(f"DRY RUN: Would write {len(predictions)} predictions")
        return len(predictions)

    # Convert to rows
    rows = [asdict(p) for p in predictions]

    # Fix field names to match schema
    for row in rows:
        row['feature_version'] = str(row['feature_version'])

    table_id = f"{PROJECT_ID}.nba_predictions.ml_model_predictions"

    errors = client.insert_rows_json(table_id, rows)

    if errors:
        logger.error(f"BigQuery insert errors: {errors[:3]}...")
        return 0

    logger.info(f"Wrote {len(rows)} predictions to {table_id}")
    return len(rows)


def print_summary(
    models: List[ModelInfo],
    all_predictions: Dict[str, List[ModelPrediction]],
    game_date: date
):
    """Print summary of experiment run"""
    print("\n" + "=" * 70)
    print(f"ML EXPERIMENT RUNNER - {game_date}")
    print("=" * 70)

    print(f"\nModels run: {len(models)}")
    for model in models:
        preds = all_predictions.get(model.model_id, [])
        print(f"  - {model.model_id}: {len(preds)} predictions")

    # Prediction comparison
    if len(all_predictions) >= 2:
        print("\nPrediction Comparison (first 5 players):")
        model_ids = list(all_predictions.keys())

        # Get players present in all models
        all_players = set()
        for preds in all_predictions.values():
            all_players.update(p.player_lookup for p in preds)

        common_players = all_players
        for preds in all_predictions.values():
            common_players &= set(p.player_lookup for p in preds)

        if common_players:
            print(f"\n{'Player':<25}", end="")
            for mid in model_ids:
                print(f"{mid:<15}", end="")
            print()
            print("-" * (25 + 15 * len(model_ids)))

            for i, player in enumerate(sorted(common_players)[:5]):
                print(f"{player:<25}", end="")
                for mid in model_ids:
                    preds = all_predictions[mid]
                    pred = next((p for p in preds if p.player_lookup == player), None)
                    if pred:
                        print(f"{pred.predicted_points:<15.1f}", end="")
                    else:
                        print(f"{'--':<15}", end="")
                print()

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Run ML experiment predictions")
    parser.add_argument("--date", type=str, help="Date to run (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to BigQuery")
    parser.add_argument("--model", type=str, help="Run specific model only")
    args = parser.parse_args()

    # Parse date
    game_date = date.fromisoformat(args.date) if args.date else date.today()
    logger.info(f"Running ML experiments for {game_date}")

    # Initialize
    client = bigquery.Client(project=PROJECT_ID)

    # Get enabled models from registry
    logger.info("Loading enabled models from registry...")
    models = get_enabled_models(client)

    if args.model:
        models = [m for m in models if m.model_id == args.model]

    if not models:
        logger.warning("No enabled models found in registry")
        print("\nNo models enabled. Register a model first:")
        print("  INSERT INTO nba_predictions.ml_model_registry ...")
        return

    logger.info(f"Found {len(models)} enabled models: {[m.model_id for m in models]}")

    # Load players with features
    logger.info("Loading players with features...")
    players = get_players_with_features(client, game_date)
    logger.info(f"Found {len(players)} players with features")

    if not players:
        logger.warning("No players found for this date")
        return

    # Run each model
    all_predictions = {}

    for model_info in models:
        logger.info(f"Loading model: {model_info.model_id}")
        model = get_cached_model(model_info)

        if model is None:
            logger.error(f"Failed to load model: {model_info.model_id}")
            continue

        logger.info(f"Running predictions for {model_info.model_id}...")
        predictions = run_model_predictions(
            model.model,
            model_info,
            players,
            game_date
        )

        all_predictions[model_info.model_id] = predictions

        # Write to BigQuery
        write_predictions(client, predictions, dry_run=args.dry_run)

    # Print summary
    print_summary(models, all_predictions, game_date)


if __name__ == "__main__":
    main()
