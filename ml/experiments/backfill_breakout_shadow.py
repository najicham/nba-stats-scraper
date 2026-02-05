#!/usr/bin/env python3
"""
Backfill Breakout Classifier Shadow Predictions

Runs the breakout classifier on historical games to evaluate performance
on a holdout period. Uses a model trained up to a cutoff date to predict
breakouts for games after that date.

This directly loads the CatBoost model and uses the same feature preparation
as the training script (breakout_experiment_runner.py).

Usage:
    # Backfill Jan 11 - Feb 5 using Jan 10 model
    PYTHONPATH=. python ml/experiments/backfill_breakout_shadow.py \
        --model gs://nba-props-platform-models/breakout/v1/breakout_v1_20251102_20260110.cbm \
        --start-date 2026-01-11 \
        --end-date 2026-02-05 \
        --output-table nba_predictions.breakout_shadow_backfill

Session 134: Breakout classifier backfill for evaluation
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List

import numpy as np
import pandas as pd
from google.cloud import bigquery
import catboost as cb

PROJECT_ID = "nba-props-platform"

# Features in order used by experiment runner (DEFAULT_FEATURES)
TRAINING_FEATURES = [
    "pts_vs_season_zscore",
    "points_std_last_10",
    "explosion_ratio",
    "days_since_breakout",
    "opponent_def_rating",
    "home_away",
    "back_to_back",
    "points_avg_last_5",
    "points_avg_season",
    "minutes_avg_last_10",
]


def load_model(model_path: str) -> cb.CatBoostClassifier:
    """Load CatBoost model from path (local or GCS)."""
    print(f"Loading model from: {model_path}")

    if model_path.startswith("gs://"):
        from shared.clients import get_storage_client

        parts = model_path.replace("gs://", "").split("/", 1)
        bucket_name, blob_path = parts[0], parts[1]

        client = get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        local_path = "/tmp/breakout_backfill_model.cbm"
        blob.download_to_filename(local_path)
        print(f"  Downloaded to {local_path}")

        model = cb.CatBoostClassifier()
        model.load_model(local_path)
    else:
        model = cb.CatBoostClassifier()
        model.load_model(model_path)

    print(f"  Model loaded: {Path(model_path).name}")
    return model


def load_games_with_features(
    client: bigquery.Client,
    start_date: str,
    end_date: str,
    min_ppg: float = 6.0,
    max_ppg: float = 20.0,
    breakout_mult: float = 1.5,
) -> pd.DataFrame:
    """Load games with all required features for classification."""
    query = f"""
    WITH role_player_games AS (
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.game_id,
        pgs.points as actual_points,
        pgs.minutes_played,
        dc.points_avg_season,
        dc.points_std_last_10,
        dc.points_avg_last_5,
        dc.points_avg_last_10,
        dc.minutes_avg_last_10,
        -- Breakout outcome
        CASE
          WHEN pgs.points >= dc.points_avg_season * {breakout_mult} THEN 1
          ELSE 0
        END as is_breakout
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      JOIN `{PROJECT_ID}.nba_precompute.player_daily_cache` dc
        ON pgs.player_lookup = dc.player_lookup
        AND pgs.game_date = dc.cache_date
      WHERE pgs.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND dc.points_avg_season BETWEEN {min_ppg} AND {max_ppg}
        AND pgs.minutes_played > 0
        AND pgs.points IS NOT NULL
    ),
    with_features AS (
      SELECT
        rpg.*,
        mf.features,
        mf.feature_names
      FROM role_player_games rpg
      LEFT JOIN `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        ON rpg.player_lookup = mf.player_lookup
        AND rpg.game_date = mf.game_date
    )
    SELECT * FROM with_features
    ORDER BY game_date, player_lookup
    """

    print(f"Loading games from {start_date} to {end_date}...")
    df = client.query(query).to_dataframe()

    # Convert Decimal columns to float
    numeric_cols = [
        'actual_points', 'minutes_played', 'points_avg_season',
        'points_std_last_10', 'points_avg_last_5', 'points_avg_last_10',
        'minutes_avg_last_10', 'is_breakout'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"  Found {len(df):,} role player games")
    print(f"  Breakout rate: {df['is_breakout'].mean()*100:.1f}%")
    return df


def extract_feature(features, feature_names, name, default=0.0):
    """Extract a feature from the feature store arrays."""
    if features is None or feature_names is None:
        return default
    feature_names_list = list(feature_names) if feature_names is not None else []
    if name in feature_names_list:
        idx = feature_names_list.index(name)
        if idx < len(features) and features[idx] is not None:
            return float(features[idx])
    return default


def prepare_feature_vector(row: pd.Series) -> np.ndarray:
    """
    Prepare feature vector matching training order.

    Returns numpy array with 10 features in exact order:
    1. pts_vs_season_zscore
    2. points_std_last_10
    3. explosion_ratio
    4. days_since_breakout
    5. opponent_def_rating
    6. home_away
    7. back_to_back
    8. points_avg_last_5
    9. points_avg_season
    10. minutes_avg_last_10
    """
    features = row.get('features')
    feature_names = row.get('feature_names')

    # Convert feature store arrays
    if features is not None:
        features = [float(f) if f is not None else None for f in features]

    # Get values from row and feature store
    points_avg_season = float(row['points_avg_season']) if row['points_avg_season'] is not None else 12.0
    points_std = float(row['points_std_last_10']) if row['points_std_last_10'] is not None else 5.0
    points_avg_last_5 = float(row['points_avg_last_5']) if row['points_avg_last_5'] is not None else 10.0
    minutes_avg = float(row['minutes_avg_last_10']) if row['minutes_avg_last_10'] is not None else 25.0

    # Compute pts_vs_season_zscore
    pts_vs_season_zscore = (points_avg_last_5 - points_avg_season) / points_std if points_std > 0 else 0.0

    # Get from feature store
    opponent_def_rating = extract_feature(features, feature_names, 'opponent_def_rating', 112.0)
    home_away = extract_feature(features, feature_names, 'home_away', 0.5)
    back_to_back = extract_feature(features, feature_names, 'back_to_back', 0.0)

    # Build vector in training order
    vector = np.array([
        pts_vs_season_zscore,     # 1
        points_std,               # 2
        1.5,                      # 3. explosion_ratio (default)
        30.0,                     # 4. days_since_breakout (default)
        opponent_def_rating,      # 5
        home_away,                # 6
        back_to_back,             # 7
        points_avg_last_5,        # 8
        points_avg_season,        # 9
        minutes_avg,              # 10
    ]).reshape(1, -1)

    return vector


def run_backfill(
    model: cb.CatBoostClassifier,
    df: pd.DataFrame,
    threshold: float = 0.5,
    verbose: bool = False,
) -> List[Dict[str, Any]]:
    """Run model on all games and collect results."""
    results = []
    errors = 0

    for idx, row in df.iterrows():
        player_lookup = row['player_lookup']
        game_date = row['game_date']

        try:
            # Prepare features
            feature_vector = prepare_feature_vector(row)

            # Get prediction
            probabilities = model.predict_proba(feature_vector)
            risk_score = float(probabilities[0][1])

            # Categorize
            if risk_score >= 0.769:
                risk_category = "HIGH_RISK"
            elif risk_score >= 0.5:
                risk_category = "MEDIUM_RISK"
            else:
                risk_category = "LOW_RISK"

            skip_reason = None

        except Exception as e:
            if errors < 5:
                print(f"Error for {player_lookup}: {e}")
            errors += 1
            risk_score = None
            risk_category = "ERROR"
            skip_reason = str(e)[:100]

        # Build result record
        points_avg = float(row['points_avg_season']) if row['points_avg_season'] is not None else 10.0
        record = {
            'player_lookup': player_lookup,
            'game_date': str(game_date)[:10],
            'game_id': row['game_id'],
            'actual_points': int(row['actual_points']) if row['actual_points'] is not None else 0,
            'points_avg_season': points_avg,
            'is_breakout': int(row['is_breakout']) if row['is_breakout'] is not None else 0,
            'breakout_threshold': round(points_avg * 1.5, 1),
            'risk_score': risk_score,
            'risk_category': risk_category,
            'is_role_player': True,
            'skip_reason': skip_reason,
            'model_version': 'v1_backfill',
            'model_file': 'breakout_v1_20251102_20260110.cbm',
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        results.append(record)

        if verbose and idx > 0 and idx % 500 == 0:
            print(f"  Processed {idx:,} games... ({errors} errors)")

    if errors > 0:
        print(f"  Total errors: {errors}")

    return results


def analyze_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze backfill results."""
    df = pd.DataFrame(results)

    # Filter to successfully classified games
    classified = df[df['risk_score'].notna()]

    print("\n" + "=" * 60)
    print(" BACKFILL ANALYSIS")
    print("=" * 60)

    print(f"\nTotal games: {len(df):,}")
    print(f"Classified: {len(classified):,}")
    print(f"Errors: {len(df) - len(classified):,}")

    if len(classified) == 0:
        print("No games classified - cannot analyze")
        return {}

    # Breakout rate by risk category
    print("\nBreakout Rate by Risk Category:")
    for cat in ['HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK']:
        subset = classified[classified['risk_category'] == cat]
        if len(subset) > 0:
            rate = subset['is_breakout'].mean() * 100
            count = len(subset)
            breakouts = subset['is_breakout'].sum()
            print(f"  {cat}: {rate:.1f}% breakout rate ({breakouts}/{count})")

    # Threshold analysis
    print("\nThreshold Analysis:")
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7, 0.769]:
        flagged = classified[classified['risk_score'] >= thresh]
        if len(flagged) > 0:
            precision = flagged['is_breakout'].mean() * 100
            total_breakouts = classified['is_breakout'].sum()
            recall = flagged['is_breakout'].sum() / total_breakouts * 100 if total_breakouts > 0 else 0
            print(f"  >= {thresh:.3f}: Precision={precision:.1f}%, Recall={recall:.1f}%, N={len(flagged)}")

    # Calculate AUC
    try:
        from sklearn.metrics import roc_auc_score
        auc = roc_auc_score(classified['is_breakout'], classified['risk_score'])
        print(f"\nAUC-ROC: {auc:.4f}")
    except Exception as e:
        print(f"\nCould not calculate AUC: {e}")
        auc = None

    return {
        'total_games': len(df),
        'classified_games': len(classified),
        'breakout_rate': classified['is_breakout'].mean(),
        'auc_roc': auc,
    }


def save_to_bigquery(
    client: bigquery.Client,
    results: List[Dict[str, Any]],
    table_id: str,
) -> int:
    """Save results to BigQuery table."""
    full_table_id = f"{PROJECT_ID}.{table_id}"

    # Create table schema
    schema = [
        bigquery.SchemaField("player_lookup", "STRING"),
        bigquery.SchemaField("game_date", "DATE"),
        bigquery.SchemaField("game_id", "STRING"),
        bigquery.SchemaField("actual_points", "INT64"),
        bigquery.SchemaField("points_avg_season", "FLOAT64"),
        bigquery.SchemaField("is_breakout", "INT64"),
        bigquery.SchemaField("breakout_threshold", "FLOAT64"),
        bigquery.SchemaField("risk_score", "FLOAT64"),
        bigquery.SchemaField("risk_category", "STRING"),
        bigquery.SchemaField("is_role_player", "BOOL"),
        bigquery.SchemaField("skip_reason", "STRING"),
        bigquery.SchemaField("model_version", "STRING"),
        bigquery.SchemaField("model_file", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP"),
    ]

    table = bigquery.Table(full_table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="game_date",
    )

    try:
        client.create_table(table)
        print(f"Created table {full_table_id}")
    except Exception:
        pass  # Table exists

    # Insert rows
    errors = client.insert_rows_json(full_table_id, results)
    if errors:
        print(f"Errors inserting rows: {errors[:3]}")
        return 0

    print(f"Inserted {len(results):,} rows to {full_table_id}")
    return len(results)


def main():
    parser = argparse.ArgumentParser(description='Backfill breakout shadow predictions')
    parser.add_argument('--model', required=True, help='Model path (local or gs://)')
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--output-table', default='nba_predictions.breakout_shadow_backfill',
                       help='Output BigQuery table')
    parser.add_argument('--min-ppg', type=float, default=6.0, help='Min PPG for role player')
    parser.add_argument('--max-ppg', type=float, default=20.0, help='Max PPG for role player')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--dry-run', action='store_true', help='Analyze only, don\'t save')
    args = parser.parse_args()

    print("=" * 60)
    print(" BREAKOUT CLASSIFIER BACKFILL")
    print("=" * 60)
    print(f"Model: {args.model}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Role player range: {args.min_ppg}-{args.max_ppg} PPG")
    print()

    # Load model
    model = load_model(args.model)

    # Load games
    client = bigquery.Client(project=PROJECT_ID)
    df = load_games_with_features(
        client, args.start_date, args.end_date,
        args.min_ppg, args.max_ppg
    )

    if len(df) == 0:
        print("No games found!")
        return

    # Run backfill
    print("\nRunning classification...")
    results = run_backfill(model, df, verbose=args.verbose)
    print(f"  Classified {len(results):,} games")

    # Analyze
    analysis = analyze_results(results)

    # Save
    if not args.dry_run:
        print()
        save_to_bigquery(client, results, args.output_table)
    else:
        print("\nDry run - results not saved")

    print("\n" + "=" * 60)
    print(" BACKFILL COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
