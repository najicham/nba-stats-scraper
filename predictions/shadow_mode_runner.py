#!/usr/bin/env python3
"""
Shadow Mode Runner

Runs v8 model alongside existing mock model for comparison.
Does NOT affect production predictions - only logs for analysis.

Features:
- Loads players for today's games
- Runs both mock (XGBoostV1) and v8 (CatBoostV8) predictions
- Applies injury filter to skip OUT players
- Logs results to BigQuery for comparison
- Generates daily accuracy report

Usage:
    # Run shadow mode for today
    PYTHONPATH=. python predictions/shadow_mode_runner.py

    # Run for specific date
    PYTHONPATH=. python predictions/shadow_mode_runner.py --date 2026-01-10

    # Dry run (no BigQuery writes)
    PYTHONPATH=. python predictions/shadow_mode_runner.py --dry-run
"""

import argparse
from datetime import date, datetime
from typing import Dict, List, Optional
import json
import logging
from google.cloud import bigquery
from dataclasses import dataclass, asdict

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"


@dataclass
class ShadowPrediction:
    """Result from shadow mode comparison"""
    player_lookup: str
    game_date: date
    game_id: str
    # Mock prediction
    mock_predicted: float
    mock_confidence: float
    mock_recommendation: str
    # V8 prediction
    v8_predicted: float
    v8_confidence: float
    v8_recommendation: str
    # Context
    betting_line: Optional[float]
    injury_status: Optional[str]
    injury_warning: bool
    # Comparison
    prediction_diff: float  # v8 - mock
    edge_vs_line_mock: Optional[float]
    edge_vs_line_v8: Optional[float]
    # Metadata
    timestamp: str


def load_players_for_date(client: bigquery.Client, game_date: date) -> List[Dict]:
    """Load players with games on the specified date"""
    query = """
    WITH
    -- Players with games today
    players AS (
        SELECT DISTINCT
            pgs.player_lookup,
            pgs.game_id,
            pgs.team_abbr,
            pgs.opponent_team_abbr
        FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
        WHERE pgs.game_date = @game_date
    ),
    -- Features from feature store
    features AS (
        SELECT
            mf.player_lookup,
            mf.game_date,
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
    -- Minutes/PPM history
    history AS (
        SELECT
            player_lookup,
            game_date,
            AVG(minutes_played) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as minutes_avg_last_10,
            AVG(SAFE_DIVIDE(points, minutes_played)) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as ppm_avg_last_10
        FROM `nba-props-platform.nba_analytics.player_game_summary`
        WHERE game_date <= @game_date
    )

    SELECT
        p.player_lookup,
        p.game_id,
        p.team_abbr,
        p.opponent_team_abbr,
        f.features,
        v.vegas_line,
        v.vegas_opening,
        h.minutes_avg_last_10,
        h.ppm_avg_last_10
    FROM players p
    LEFT JOIN features f ON p.player_lookup = f.player_lookup
    LEFT JOIN vegas v ON p.player_lookup = v.player_lookup
    LEFT JOIN history h ON p.player_lookup = h.player_lookup AND h.game_date = @game_date
    WHERE f.features IS NOT NULL
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    result = client.query(query, job_config=job_config).result()
    return [dict(row) for row in result]


def features_array_to_dict(features_array: List[float]) -> Dict:
    """Convert features array to named dictionary"""
    feature_names = [
        "points_avg_last_5", "points_avg_last_10", "points_avg_season",
        "points_std_last_10", "games_in_last_7_days", "fatigue_score",
        "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
        "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
        "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
        "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
        "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
    ]

    return {name: float(features_array[i]) for i, name in enumerate(feature_names)}


def run_shadow_predictions(
    players: List[Dict],
    game_date: date,
    injury_filter
) -> List[ShadowPrediction]:
    """Run both mock and v8 predictions for all players"""
    from predictions.worker.prediction_systems.xgboost_v1 import XGBoostV1
    from predictions.worker.prediction_systems.catboost_v8 import CatBoostV8

    # Initialize systems
    mock_system = XGBoostV1()  # Uses mock model by default
    v8_system = CatBoostV8(use_local=True)

    logger.info(f"Mock system: {mock_system.system_id}")
    logger.info(f"V8 system loaded: {v8_system.model is not None}")

    # Check injury status for all players
    player_lookups = [p['player_lookup'] for p in players]
    injury_statuses = injury_filter.check_players_batch(player_lookups, game_date)

    results = []
    skipped = 0
    warned = 0

    for player_data in players:
        player_lookup = player_data['player_lookup']

        # Check injury status
        injury_status = injury_statuses.get(player_lookup)

        if injury_status and injury_status.should_skip:
            skipped += 1
            logger.debug(f"Skipping {player_lookup}: {injury_status.message}")
            continue

        if injury_status and injury_status.has_warning:
            warned += 1

        # Convert features array to dict
        features = features_array_to_dict(player_data['features'])

        # Get Vegas line
        vegas_line = player_data.get('vegas_line')
        vegas_opening = player_data.get('vegas_opening')

        # Run mock prediction
        mock_result = mock_system.predict(
            player_lookup=player_lookup,
            features=features,
            betting_line=vegas_line
        )

        # Run v8 prediction
        v8_result = v8_system.predict(
            player_lookup=player_lookup,
            features=features,
            betting_line=vegas_line,
            vegas_line=vegas_line,
            vegas_opening=vegas_opening,
            minutes_avg_last_10=player_data.get('minutes_avg_last_10'),
            ppm_avg_last_10=player_data.get('ppm_avg_last_10'),
        )

        # Calculate comparison metrics
        mock_pred = mock_result.get('predicted_points', 0) or 0
        v8_pred = v8_result.get('predicted_points', 0) or 0

        edge_mock = (mock_pred - vegas_line) if vegas_line else None
        edge_v8 = (v8_pred - vegas_line) if vegas_line else None

        results.append(ShadowPrediction(
            player_lookup=player_lookup,
            game_date=game_date,
            game_id=player_data['game_id'],
            mock_predicted=mock_pred,
            mock_confidence=mock_result.get('confidence_score', 0),
            mock_recommendation=mock_result.get('recommendation', 'PASS'),
            v8_predicted=v8_pred,
            v8_confidence=v8_result.get('confidence_score', 0),
            v8_recommendation=v8_result.get('recommendation', 'PASS'),
            betting_line=vegas_line,
            injury_status=injury_status.injury_status if injury_status else None,
            injury_warning=injury_status.has_warning if injury_status else False,
            prediction_diff=v8_pred - mock_pred,
            edge_vs_line_mock=edge_mock,
            edge_vs_line_v8=edge_v8,
            timestamp=datetime.now().isoformat(),
        ))

    logger.info(f"Generated {len(results)} predictions")
    logger.info(f"Skipped {skipped} players (OUT status)")
    logger.info(f"Warned {warned} players (QUESTIONABLE/DOUBTFUL)")

    return results


def write_to_bigquery(
    client: bigquery.Client,
    predictions: List[ShadowPrediction],
    dry_run: bool = False
) -> int:
    """Write shadow predictions to BigQuery"""
    if dry_run:
        logger.info(f"DRY RUN: Would write {len(predictions)} predictions")
        return len(predictions)

    # Convert to rows
    rows = [asdict(p) for p in predictions]

    # Convert date objects to strings
    for row in rows:
        row['game_date'] = str(row['game_date'])

    table_id = f"{PROJECT_ID}.nba_predictions.shadow_mode_predictions"

    # Create table if not exists
    schema = [
        bigquery.SchemaField("player_lookup", "STRING"),
        bigquery.SchemaField("game_date", "DATE"),
        bigquery.SchemaField("game_id", "STRING"),
        bigquery.SchemaField("mock_predicted", "FLOAT64"),
        bigquery.SchemaField("mock_confidence", "FLOAT64"),
        bigquery.SchemaField("mock_recommendation", "STRING"),
        bigquery.SchemaField("v8_predicted", "FLOAT64"),
        bigquery.SchemaField("v8_confidence", "FLOAT64"),
        bigquery.SchemaField("v8_recommendation", "STRING"),
        bigquery.SchemaField("betting_line", "FLOAT64"),
        bigquery.SchemaField("injury_status", "STRING"),
        bigquery.SchemaField("injury_warning", "BOOLEAN"),
        bigquery.SchemaField("prediction_diff", "FLOAT64"),
        bigquery.SchemaField("edge_vs_line_mock", "FLOAT64"),
        bigquery.SchemaField("edge_vs_line_v8", "FLOAT64"),
        bigquery.SchemaField("timestamp", "STRING"),
    ]

    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="game_date",
    )

    try:
        client.create_table(table)
        logger.info(f"Created table {table_id}")
    except Exception:
        pass  # Table already exists

    # Insert rows
    errors = client.insert_rows_json(table_id, rows)

    if errors:
        logger.error(f"BigQuery insert errors: {errors}")
        return 0

    logger.info(f"Wrote {len(rows)} predictions to {table_id}")
    return len(rows)


def print_summary(predictions: List[ShadowPrediction]):
    """Print summary statistics"""
    if not predictions:
        print("No predictions generated")
        return

    print("\n" + "=" * 70)
    print("SHADOW MODE SUMMARY")
    print("=" * 70)

    # Basic stats
    print(f"\nTotal predictions: {len(predictions)}")

    # Prediction differences
    diffs = [p.prediction_diff for p in predictions]
    print(f"\nPrediction Differences (v8 - mock):")
    print(f"  Mean: {sum(diffs) / len(diffs):+.2f} points")
    print(f"  Min:  {min(diffs):+.2f} points")
    print(f"  Max:  {max(diffs):+.2f} points")

    # Recommendation comparison
    agree = sum(1 for p in predictions if p.mock_recommendation == p.v8_recommendation)
    print(f"\nRecommendation Agreement:")
    print(f"  Same: {agree} ({100 * agree / len(predictions):.1f}%)")
    print(f"  Different: {len(predictions) - agree} ({100 * (len(predictions) - agree) / len(predictions):.1f}%)")

    # Injury warnings
    warned = sum(1 for p in predictions if p.injury_warning)
    print(f"\nInjury Warnings: {warned} players flagged as QUESTIONABLE/DOUBTFUL")

    # Edge analysis (for players with Vegas lines)
    with_lines = [p for p in predictions if p.betting_line is not None]
    if with_lines:
        print(f"\nEdge Analysis ({len(with_lines)} players with Vegas lines):")

        # V8 edges
        v8_overs = sum(1 for p in with_lines if p.edge_vs_line_v8 and p.edge_vs_line_v8 > 1)
        v8_unders = sum(1 for p in with_lines if p.edge_vs_line_v8 and p.edge_vs_line_v8 < -1)
        print(f"  v8 OVER signals (>1pt edge):  {v8_overs}")
        print(f"  v8 UNDER signals (>1pt edge): {v8_unders}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Run shadow mode predictions")
    parser.add_argument("--date", type=str, help="Date to run (YYYY-MM-DD), default: today")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to BigQuery")
    args = parser.parse_args()

    # Parse date
    if args.date:
        game_date = date.fromisoformat(args.date)
    else:
        game_date = date.today()

    logger.info(f"Running shadow mode for {game_date}")

    # Initialize
    client = bigquery.Client(project=PROJECT_ID)

    # Load injury filter
    from predictions.shared.injury_filter import InjuryFilter
    injury_filter = InjuryFilter()

    # Load players
    logger.info("Loading players...")
    players = load_players_for_date(client, game_date)
    logger.info(f"Found {len(players)} players with features")

    if not players:
        logger.warning("No players found for this date")
        return

    # Run predictions
    logger.info("Running shadow predictions...")
    predictions = run_shadow_predictions(players, game_date, injury_filter)

    # Print summary
    print_summary(predictions)

    # Write to BigQuery
    if predictions:
        write_to_bigquery(client, predictions, dry_run=args.dry_run)

    # Print injury filter stats
    stats = injury_filter.get_stats()
    logger.info(f"Injury filter stats: {stats}")


if __name__ == "__main__":
    main()
