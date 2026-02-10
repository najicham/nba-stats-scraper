#!/usr/bin/env python3
"""
Backfill Challenger Predictions — Generate historical predictions for shadow models.

Session 177: Generates predictions for challenger models on post-training dates
using stored features from ml_feature_store_v2 and production lines. Writes to
player_prop_predictions so the grading pipeline picks them up automatically.

Usage:
    # Backfill all enabled challengers
    PYTHONPATH=. python bin/backfill-challenger-predictions.py

    # Backfill a specific challenger
    PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108

    # Custom date range
    PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108 \
        --start 2026-01-09 --end 2026-02-08

    # Dry run (show what would be backfilled)
    PYTHONPATH=. python bin/backfill-challenger-predictions.py --dry-run
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import hashlib
import json
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from google.cloud import bigquery

from predictions.worker.prediction_systems.catboost_monthly import MONTHLY_MODELS
from shared.ml.feature_contract import V9_CONTRACT, V9_FEATURE_NAMES, FEATURE_DEFAULTS

PROJECT_ID = "nba-props-platform"
TABLE_ID = f"{PROJECT_ID}.nba_predictions.player_prop_predictions"

# Minimum edge for actionable predictions
ACTIONABLE_EDGE = 3.0


def parse_args():
    parser = argparse.ArgumentParser(description='Backfill challenger model predictions')
    parser.add_argument('--model', help='Specific model_id to backfill (default: all enabled)')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD, default: day after train_end)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--dry-run', action='store_true', help='Show plan without writing')
    parser.add_argument('--batch-size', type=int, default=500, help='BQ insert batch size')
    return parser.parse_args()


def load_model_from_config(model_id, config):
    """Load a CatBoost model from its config path."""
    import catboost as cb

    model_path = config["model_path"]
    print(f"  Loading model from: {model_path}")

    if model_path.startswith("gs://"):
        from shared.clients import get_storage_client
        parts = model_path.replace("gs://", "").split("/", 1)
        bucket_name, blob_path = parts[0], parts[1]

        client = get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        local_path = f"/tmp/backfill_{model_id}.cbm"
        blob.download_to_filename(local_path)

        model = cb.CatBoostRegressor()
        model.load_model(local_path)
        model_file_name = Path(blob_path).name

        sha256 = hashlib.sha256()
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        model_sha256 = sha256.hexdigest()[:16]
    else:
        if not model_path.startswith('/'):
            repo_root = Path(__file__).parent.parent
            model_path = str(repo_root / model_path)

        model = cb.CatBoostRegressor()
        model.load_model(model_path)
        model_file_name = Path(model_path).name

        sha256 = hashlib.sha256()
        with open(model_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        model_sha256 = sha256.hexdigest()[:16]

    print(f"  Loaded: {model_file_name} (sha256: {model_sha256})")
    return model, model_file_name, model_sha256


def query_features_and_lines(client, start_date, end_date):
    """Query features from feature store and production lines from predictions.

    Uses production catboost_v9 predictions as the line source — same lines
    the champion used, so grading is apples-to-apples.
    """
    query = f"""
    WITH prod_lines AS (
        SELECT player_lookup, game_date, game_id, current_points_line,
               universal_player_id, line_source, sportsbook,
               scoring_tier, injury_status_at_prediction,
               feature_quality_score as prod_quality_score
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE system_id = 'catboost_v9'
          AND game_date BETWEEN '{start_date}' AND '{end_date}'
          AND is_active = TRUE
          AND current_points_line IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup, game_date
            ORDER BY created_at DESC
        ) = 1
    )
    SELECT
        mf.player_lookup,
        mf.game_date,
        mf.features,
        mf.feature_names,
        mf.feature_quality_score,
        mf.default_feature_count,
        mf.default_feature_indices,
        mf.required_default_count,
        mf.quality_alert_level,
        mf.matchup_quality_pct,
        mf.is_quality_ready,
        pl.game_id,
        pl.universal_player_id,
        CAST(pl.current_points_line AS FLOAT64) as vegas_line,
        pl.line_source,
        pl.sportsbook,
        pl.scoring_tier,
        pl.injury_status_at_prediction
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN prod_lines pl
        ON mf.player_lookup = pl.player_lookup AND mf.game_date = pl.game_date
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND mf.feature_count >= 33
      AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
      AND mf.feature_quality_score >= 70
    ORDER BY mf.game_date, mf.player_lookup
    """
    return client.query(query).to_dataframe()


def extract_features(row, contract=V9_CONTRACT):
    """Extract feature vector from a single row, matching V9 contract order."""
    feature_values = row['features']
    feature_names = row['feature_names']

    if len(feature_values) != len(feature_names):
        min_len = min(len(feature_values), len(feature_names))
        feature_values = feature_values[:min_len]
        feature_names = feature_names[:min_len]

    features_dict = dict(zip(feature_names, feature_values))

    result = []
    for name in contract.feature_names:
        if name in features_dict and features_dict[name] is not None:
            result.append(float(features_dict[name]))
        elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
            result.append(float(FEATURE_DEFAULTS[name]))
        else:
            result.append(0.0)

    return np.array(result)


def compute_confidence(edge_abs):
    """Compute confidence score from absolute edge, matching worker logic."""
    if edge_abs >= 5.0:
        return 95.0
    elif edge_abs >= 3.0:
        return 90.0
    elif edge_abs >= 1.0:
        return 85.0
    else:
        return 80.0


def generate_predictions(model, df, model_id, model_file_name, model_sha256, config):
    """Generate predictions for all rows and return list of BQ records."""
    records = []

    # Build feature matrix
    feature_matrix = np.array([extract_features(row) for _, row in df.iterrows()])
    predicted_points = model.predict(feature_matrix)

    for i, (_, row) in enumerate(df.iterrows()):
        pred = float(predicted_points[i])
        line = float(row['vegas_line'])
        edge = pred - line

        if edge > 0:
            recommendation = 'OVER'
        elif edge < 0:
            recommendation = 'UNDER'
        else:
            recommendation = 'PASS'

        confidence = compute_confidence(abs(edge))
        is_actionable = abs(edge) >= ACTIONABLE_EDGE

        # Build features snapshot
        feature_values = row['features']
        feature_names = row['feature_names']
        if len(feature_values) == len(feature_names):
            features_snapshot = json.dumps(dict(zip(
                [str(n) for n in feature_names[:33]],
                [float(v) if v is not None else None for v in feature_values[:33]]
            )))
        else:
            features_snapshot = None

        record = {
            'prediction_id': str(uuid.uuid4()),
            'system_id': model_id,
            'player_lookup': row['player_lookup'],
            'universal_player_id': row.get('universal_player_id'),
            'game_date': str(row['game_date']),
            'game_id': row.get('game_id'),
            'predicted_points': round(pred, 2),
            'adjusted_points': round(pred, 2),
            'current_points_line': line,
            'line_margin': round(edge, 2),
            'confidence_score': confidence,
            'recommendation': recommendation,
            'is_active': True,
            'is_actionable': is_actionable,
            'model_version': model_id,
            'model_file_name': model_file_name,
            'model_training_start_date': config.get('train_start'),
            'model_training_end_date': config.get('train_end'),
            'model_expected_mae': config.get('backtest_mae') or config.get('mae'),
            'prediction_run_mode': 'BACKFILL',
            'prediction_made_before_game': False,
            'feature_count': 33,
            'feature_quality_score': float(row['feature_quality_score']) if pd.notna(row.get('feature_quality_score')) else None,
            'default_feature_count': int(row['default_feature_count']) if pd.notna(row.get('default_feature_count')) else 0,
            'default_feature_indices': [int(x) for x in row['default_feature_indices']] if row.get('default_feature_indices') is not None and not (isinstance(row.get('default_feature_indices'), float) and pd.isna(row.get('default_feature_indices'))) else [],
            'required_default_count': int(row['required_default_count']) if pd.notna(row.get('required_default_count')) else 0,
            'quality_alert_level': str(row['quality_alert_level']) if pd.notna(row.get('quality_alert_level')) else None,
            'matchup_quality_pct': float(row['matchup_quality_pct']) if pd.notna(row.get('matchup_quality_pct')) else None,
            'is_quality_ready': bool(row['is_quality_ready']) if pd.notna(row.get('is_quality_ready')) else True,
            'features_snapshot': features_snapshot,
            'line_source': row.get('line_source'),
            'sportsbook': row.get('sportsbook'),
            'scoring_tier': row.get('scoring_tier'),
            'injury_status_at_prediction': row.get('injury_status_at_prediction'),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'predicted_at': datetime.now(timezone.utc).isoformat(),
            'superseded': False,
        }
        records.append(record)

    return records


def check_existing_predictions(client, model_id, start_date, end_date):
    """Check if predictions already exist for this model/date range."""
    query = f"""
    SELECT game_date, COUNT(*) as n
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE system_id = '{model_id}'
      AND game_date BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY 1
    ORDER BY 1
    """
    result = client.query(query).to_dataframe()
    return result


def write_predictions(client, records, batch_size=500):
    """Write prediction records to BigQuery in batches."""
    total = len(records)
    errors_total = 0

    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        errors = client.insert_rows_json(TABLE_ID, batch)
        if errors:
            errors_total += len(errors)
            print(f"    Batch {i//batch_size + 1}: {len(errors)} errors")
            for err in errors[:3]:
                print(f"      {err}")
        else:
            print(f"    Batch {i//batch_size + 1}: {len(batch)} rows written")

    return errors_total


def main():
    args = parse_args()
    client = bigquery.Client(project=PROJECT_ID)

    # Determine which models to backfill
    if args.model:
        if args.model not in MONTHLY_MODELS:
            print(f"ERROR: Unknown model_id: {args.model}")
            print(f"Available: {list(MONTHLY_MODELS.keys())}")
            return
        models_to_backfill = {args.model: MONTHLY_MODELS[args.model]}
    else:
        models_to_backfill = {
            k: v for k, v in MONTHLY_MODELS.items() if v.get('enabled', False)
        }

    if not models_to_backfill:
        print("No enabled models to backfill.")
        return

    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    print("=" * 70)
    print(" CHALLENGER MODEL BACKFILL")
    print("=" * 70)

    for model_id, config in models_to_backfill.items():
        print(f"\n{'=' * 70}")
        print(f" {model_id}")
        print(f"{'=' * 70}")

        # Determine date range
        train_end = config['train_end']
        start_date = args.start or (datetime.strptime(train_end, '%Y-%m-%d').date() + timedelta(days=1)).strftime('%Y-%m-%d')
        end_date = args.end or yesterday

        if start_date > end_date:
            print(f"  SKIP: Start date {start_date} > end date {end_date}")
            print(f"  (Model trained through {train_end}, no post-training dates to backfill)")
            continue

        print(f"  Training: {config['train_start']} to {train_end}")
        print(f"  Backfill: {start_date} to {end_date}")
        print(f"  Description: {config.get('description', 'N/A')}")

        # Check for existing predictions
        existing = check_existing_predictions(client, model_id, start_date, end_date)
        if len(existing) > 0:
            total_existing = existing['n'].sum()
            print(f"\n  WARNING: {total_existing} predictions already exist for {len(existing)} dates")
            print(f"  Dates with predictions: {', '.join(str(d) for d in existing['game_date'].tolist())}")
            print(f"  Skipping dates with existing predictions to avoid duplicates.")
            # Filter out dates that already have predictions
            existing_dates = set(str(d) for d in existing['game_date'].tolist())
        else:
            existing_dates = set()

        if args.dry_run:
            print(f"\n  DRY RUN: Would backfill {start_date} to {end_date}")
            print(f"  (Skipping {len(existing_dates)} dates with existing predictions)")
            continue

        # Load model
        print(f"\n  Loading model...")
        model, model_file_name, model_sha256 = load_model_from_config(model_id, config)

        # Query features and lines
        print(f"  Querying features and production lines...")
        df = query_features_and_lines(client, start_date, end_date)
        print(f"  Retrieved {len(df)} player-date rows")

        if len(df) == 0:
            print("  No data found — check that production predictions exist for this period")
            continue

        # Filter out dates that already have predictions
        if existing_dates:
            df = df[~df['game_date'].astype(str).isin(existing_dates)]
            print(f"  After filtering existing: {len(df)} rows to process")

        if len(df) == 0:
            print("  All dates already have predictions — nothing to backfill")
            continue

        # Generate predictions
        print(f"  Generating predictions...")
        records = generate_predictions(model, df, model_id, model_file_name, model_sha256, config)
        print(f"  Generated {len(records)} predictions")

        # Summary stats
        preds = np.array([r['predicted_points'] for r in records])
        lines = np.array([r['current_points_line'] for r in records])
        edges = preds - lines
        n_actionable = sum(1 for r in records if r['is_actionable'])
        n_over = sum(1 for r in records if r['recommendation'] == 'OVER')
        n_under = sum(1 for r in records if r['recommendation'] == 'UNDER')

        game_dates = sorted(set(r['game_date'] for r in records))
        print(f"\n  Summary:")
        print(f"    Game dates: {len(game_dates)} ({game_dates[0]} to {game_dates[-1]})")
        print(f"    Total predictions: {len(records)}")
        print(f"    Actionable (edge 3+): {n_actionable}")
        print(f"    Direction: {n_over} OVER, {n_under} UNDER")
        print(f"    Avg predicted: {np.mean(preds):.1f}")
        print(f"    Avg edge: {np.mean(edges):+.2f}")
        print(f"    Avg |edge|: {np.mean(np.abs(edges)):.2f}")

        # Write to BQ
        print(f"\n  Writing to BigQuery...")
        errors = write_predictions(client, records, args.batch_size)
        if errors:
            print(f"  WARNING: {errors} total insert errors")
        else:
            print(f"  SUCCESS: {len(records)} predictions written")

    print(f"\n{'=' * 70}")
    print(" BACKFILL COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Trigger grading for the backfilled dates")
    print("  2. Run comparison: python bin/compare-model-performance.py <system_id>")


if __name__ == "__main__":
    main()
