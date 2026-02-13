#!/usr/bin/env python3
"""
Backfill V12 Predictions — Generate historical predictions for CatBoost V12 shadow model.

Session 239: Generates V12 predictions on historical dates where the feature store has
54 features (backfilled). Uses stored features from ml_feature_store_v2 and production
V9 lines. Writes to player_prop_predictions so grading picks them up automatically.

V12 is vegas-free (50 features, excludes indices 25-28). Only processes rows with
ARRAY_LENGTH(features) >= 54 to ensure V12-specific features (37-53) are available.

Usage:
    # Dry run — show what would be backfilled
    PYTHONPATH=. python bin/backfill-v12-predictions.py --dry-run

    # Backfill all dates with 54-feature data
    PYTHONPATH=. python bin/backfill-v12-predictions.py

    # Custom date range
    PYTHONPATH=. python bin/backfill-v12-predictions.py --start 2026-02-01 --end 2026-02-09

    # Backfill specific date
    PYTHONPATH=. python bin/backfill-v12-predictions.py --start 2026-02-05 --end 2026-02-05
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
import uuid
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from google.cloud import bigquery

from predictions.worker.prediction_systems.catboost_v12 import (
    CatBoostV12, V12_NOVEG_FEATURES, DEFAULT_MODEL_GCS
)
from shared.ml.feature_contract import FEATURE_DEFAULTS, FEATURE_STORE_NAMES, FEATURE_STORE_FEATURE_COUNT

PROJECT_ID = "nba-props-platform"
TABLE_ID = f"{PROJECT_ID}.nba_predictions.player_prop_predictions"

SYSTEM_ID = "catboost_v12"
TRAIN_START = "2025-11-02"
TRAIN_END = "2026-01-31"
FEATURE_COUNT = 50
ACTIONABLE_EDGE = 3.0


def parse_args():
    parser = argparse.ArgumentParser(description='Backfill V12 shadow model predictions')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD, default: day after train_end)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--dry-run', action='store_true', help='Show plan without writing')
    parser.add_argument('--batch-size', type=int, default=500, help='BQ insert batch size')
    return parser.parse_args()


def query_features_and_lines(client, start_date, end_date):
    """Query features from feature store and production lines from V9 predictions.

    Uses individual feature columns (feature_N_value) for NULL-aware reads.
    NULLs in individual columns correctly represent missing features (NaN for CatBoost).

    Excludes player-dates that already have V12 predictions (per-player dedup).
    """
    # Build individual column list for NULL-aware feature reads
    feature_cols = ', '.join(
        f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
    )
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
    ),
    existing_v12 AS (
        SELECT DISTINCT player_lookup, game_date
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE system_id = '{SYSTEM_ID}'
          AND game_date BETWEEN '{start_date}' AND '{end_date}'
    )
    SELECT
        mf.player_lookup,
        mf.game_date,
        {feature_cols},
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
    LEFT JOIN existing_v12 ev
        ON mf.player_lookup = ev.player_lookup AND mf.game_date = ev.game_date
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND ARRAY_LENGTH(mf.features) >= 54
      AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
      AND mf.feature_quality_score >= 70
      AND ev.player_lookup IS NULL
    ORDER BY mf.game_date, mf.player_lookup
    """
    return client.query(query).to_dataframe()


def extract_v12_features(row):
    """Extract 50-feature V12 vector from a feature store row.

    Uses individual columns (feature_N_value) for NULL-aware reads.
    NULLs correctly become NaN for CatBoost (handles missing natively).
    Falls back to features array if individual columns not available.
    """
    # Build name→value dict from individual columns (NULL-aware)
    features_dict = {}
    has_individual = hasattr(row, 'feature_0_value') or 'feature_0_value' in row.index
    if has_individual:
        for i, name in enumerate(FEATURE_STORE_NAMES):
            val = row.get(f'feature_{i}_value')
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                features_dict[name] = float(val)
            # NULL/NaN → not in dict → prediction system handles as missing
    else:
        # Fallback: use features array (legacy path)
        feature_values = row['features']
        feature_names = row['feature_names']
        if len(feature_values) != len(feature_names):
            min_len = min(len(feature_values), len(feature_names))
            feature_values = feature_values[:min_len]
            feature_names = feature_names[:min_len]
        features_dict = dict(zip(feature_names, feature_values))

    vector = []
    for name in V12_NOVEG_FEATURES:
        val = features_dict.get(name)
        if val is not None:
            vector.append(float(val))
        elif name in ('pct_paint', 'pct_mid_range', 'pct_three'):
            vector.append(np.nan)
        elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
            vector.append(float(FEATURE_DEFAULTS[name]))
        else:
            vector.append(np.nan)

    return np.array(vector)


def compute_v12_confidence(features_dict):
    """Compute V12 confidence score — matches CatBoostV12._calculate_confidence."""
    confidence = 75.0

    quality = features_dict.get('feature_quality_score', 80)
    if quality is None or (isinstance(quality, float) and np.isnan(quality)):
        quality = 80
    if quality >= 90:
        confidence += 10
    elif quality >= 80:
        confidence += 7
    elif quality >= 70:
        confidence += 5
    else:
        confidence += 2

    std_dev = features_dict.get('points_std_last_10', 5)
    if std_dev is None or (isinstance(std_dev, float) and np.isnan(std_dev)):
        std_dev = 5
    if std_dev < 4:
        confidence += 10
    elif std_dev < 6:
        confidence += 7
    elif std_dev < 8:
        confidence += 5
    else:
        confidence += 2

    return max(0, min(100, confidence))


def generate_predictions(model, df, model_file_name, model_sha256):
    """Generate V12 predictions for all rows and return list of BQ records."""
    records = []

    # Build feature matrix
    feature_matrix = np.array([extract_v12_features(row) for _, row in df.iterrows()])
    predicted_points_raw = model.predict(feature_matrix)

    for i, (_, row) in enumerate(df.iterrows()):
        pred = float(max(0, min(60, predicted_points_raw[i])))
        line = float(row['vegas_line'])
        edge = pred - line

        if edge >= 1.0:
            recommendation = 'OVER'
        elif edge <= -1.0:
            recommendation = 'UNDER'
        else:
            recommendation = 'PASS'

        # Build features dict for confidence calculation
        feature_values = row['features']
        feature_names = row['feature_names']
        min_len = min(len(feature_values), len(feature_names))
        features_dict = dict(zip(feature_names[:min_len], feature_values[:min_len]))
        features_dict['feature_quality_score'] = row.get('feature_quality_score')

        confidence = compute_v12_confidence(features_dict)
        is_actionable = abs(edge) >= ACTIONABLE_EDGE

        # Filter reason for non-actionable
        filter_reason = None
        if not is_actionable:
            if abs(edge) < ACTIONABLE_EDGE:
                filter_reason = 'low_edge'
        if recommendation == 'PASS':
            is_actionable = False
            filter_reason = 'low_edge'

        # Features snapshot (first 50 features by V12 name)
        v12_features = extract_v12_features(row)
        features_snapshot = json.dumps(dict(zip(
            V12_NOVEG_FEATURES,
            [float(v) if not np.isnan(v) else None for v in v12_features]
        )))

        record = {
            'prediction_id': str(uuid.uuid4()),
            'system_id': SYSTEM_ID,
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
            'filter_reason': filter_reason,
            'has_prop_line': True,
            'model_version': SYSTEM_ID,
            'model_file_name': model_file_name,
            'model_training_start_date': TRAIN_START,
            'model_training_end_date': TRAIN_END,
            'prediction_run_mode': 'BACKFILL',
            'prediction_made_before_game': False,
            'feature_count': FEATURE_COUNT,
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

    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    default_start = (datetime.strptime(TRAIN_END, '%Y-%m-%d').date() + timedelta(days=1)).strftime('%Y-%m-%d')
    start_date = args.start or default_start
    end_date = args.end or yesterday

    print("=" * 70)
    print(" V12 (NOVA) PREDICTION BACKFILL")
    print("=" * 70)
    print(f"  System ID:    {SYSTEM_ID}")
    print(f"  Model:        {DEFAULT_MODEL_GCS}")
    print(f"  Training:     {TRAIN_START} to {TRAIN_END}")
    print(f"  Backfill:     {start_date} to {end_date}")
    print(f"  Features:     {FEATURE_COUNT} (vegas-free)")
    print(f"  Mode:         Post-training only (training dates excluded)")

    if args.dry_run:
        # In dry-run, query how many player-dates need backfill (per-player dedup)
        print(f"\n  Checking for gaps (per-player dedup)...")
        count_query = f"""
        WITH prod_lines AS (
            SELECT player_lookup, game_date
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE system_id = 'catboost_v9'
              AND game_date BETWEEN '{start_date}' AND '{end_date}'
              AND is_active = TRUE AND current_points_line IS NOT NULL
        ),
        existing_v12 AS (
            SELECT DISTINCT player_lookup, game_date
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE system_id = '{SYSTEM_ID}'
              AND game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT mf.game_date) as dates,
            MIN(mf.game_date) as earliest,
            MAX(mf.game_date) as latest
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        JOIN prod_lines pl
            ON mf.player_lookup = pl.player_lookup AND mf.game_date = pl.game_date
        LEFT JOIN existing_v12 ev
            ON mf.player_lookup = ev.player_lookup AND mf.game_date = ev.game_date
        WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
          AND ARRAY_LENGTH(mf.features) >= 54
          AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
          AND mf.feature_quality_score >= 70
          AND ev.player_lookup IS NULL
        """
        counts = client.query(count_query).to_dataframe()
        r = counts.iloc[0]
        print(f"\n  DRY RUN — would backfill:")
        print(f"    Dates:   {int(r['dates'])} ({r['earliest']} to {r['latest']})")
        print(f"    Players: {int(r['total_rows'])} (after per-player dedup)")
        print(f"\n  Run without --dry-run to execute.")
        return

    # Load V12 model
    print(f"\n  Loading CatBoost V12 model...")
    v12 = CatBoostV12()
    model_file_name = v12._model_file_name
    model_sha256 = v12._model_sha256
    print(f"  Loaded: {model_file_name} (sha256: {model_sha256})")

    # Query features and lines
    print(f"\n  Querying features and production lines...")
    df = query_features_and_lines(client, start_date, end_date)
    print(f"  Retrieved {len(df)} player-date rows with 54 features")

    if len(df) == 0:
        print("  No gaps found — all player-dates already have V12 predictions")
        return

    # Generate predictions
    print(f"\n  Generating V12 predictions...")
    records = generate_predictions(v12.model, df, model_file_name, model_sha256)
    print(f"  Generated {len(records)} predictions")

    # Summary stats
    preds = np.array([r['predicted_points'] for r in records])
    lines = np.array([r['current_points_line'] for r in records])
    edges = preds - lines
    n_actionable = sum(1 for r in records if r['is_actionable'])
    n_over = sum(1 for r in records if r['recommendation'] == 'OVER')
    n_under = sum(1 for r in records if r['recommendation'] == 'UNDER')
    n_pass = sum(1 for r in records if r['recommendation'] == 'PASS')

    game_dates = sorted(set(r['game_date'] for r in records))
    print(f"\n  Summary:")
    print(f"    Game dates:          {len(game_dates)} ({game_dates[0]} to {game_dates[-1]})")
    print(f"    Total predictions:   {len(records)}")
    print(f"    Actionable (edge 3+): {n_actionable} ({100*n_actionable/len(records):.1f}%)")
    print(f"    Direction:           {n_over} OVER, {n_under} UNDER, {n_pass} PASS")
    print(f"    Avg predicted:       {np.mean(preds):.1f}")
    print(f"    Avg edge:            {np.mean(edges):+.2f}")
    print(f"    Avg |edge|:          {np.mean(np.abs(edges)):.2f}")

    # Write to BQ
    print(f"\n  Writing to BigQuery...")
    errors = write_predictions(client, records, args.batch_size)
    if errors:
        print(f"\n  WARNING: {errors} total insert errors")
    else:
        print(f"\n  SUCCESS: {len(records)} V12 predictions written")

    print(f"\n{'=' * 70}")
    print(" BACKFILL COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Trigger grading backfill:")
    print(f"     PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\")
    print(f"       --start-date {game_dates[0]} --end-date {game_dates[-1]}")
    print("  2. Check V12 performance:")
    print(f"     PYTHONPATH=. python bin/compare-model-performance.py catboost_v12 --days 14")


if __name__ == "__main__":
    main()
