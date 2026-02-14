#!/usr/bin/env python3
"""
Backfill V9 NO_PROP_LINE Predictions — Generate historical V9 predictions for players
who had no prop lines but were quality-ready in the feature store.

Session 241: Generates V9 predictions for players who were skipped because they
lacked prop lines. Uses stored features from ml_feature_store_v2 and produces
NO_PROP_LINE predictions for MAE evaluation on the full population.

V9 uses 33 features including vegas (indices 25-28) which are optional.
Players without lines will have NaN for vegas features — CatBoost handles natively.

Safety: Hard-coded training end dates per model. Script refuses to predict on dates
within the training window to prevent data leakage.

Usage:
    # Dry run — show what would be backfilled
    PYTHONPATH=. python bin/backfill-v9-no-line-predictions.py --dry-run

    # Backfill champion V9 (default)
    PYTHONPATH=. python bin/backfill-v9-no-line-predictions.py

    # Custom date range
    PYTHONPATH=. python bin/backfill-v9-no-line-predictions.py --start 2026-01-15 --end 2026-02-12

    # Backfill a shadow model
    PYTHONPATH=. python bin/backfill-v9-no-line-predictions.py --system-id catboost_v9_q43_train1102_0131
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

from predictions.worker.prediction_systems.catboost_v8 import V8_FEATURES
from shared.ml.feature_contract import FEATURE_DEFAULTS, FEATURE_STORE_NAMES, FEATURE_STORE_FEATURE_COUNT

PROJECT_ID = "nba-props-platform"
TABLE_ID = f"{PROJECT_ID}.nba_predictions.player_prop_predictions"

FEATURE_COUNT = 33  # V9 uses same 33 features as V8
ACTIONABLE_EDGE = 3.0

# Training end dates per system — NEVER predict within training window
SYSTEM_TRAINING_ENDS = {
    'catboost_v9': '2026-01-08',                      # Champion
    'catboost_v9_train1102_0108': '2026-01-08',        # Shadow
    'catboost_v9_0131_tuned': '2026-01-31',            # Shadow tuned
    'catboost_v9_q43_train1102_0131': '2026-01-31',    # Q43 shadow
    'catboost_v9_q45_train1102_0131': '2026-01-31',    # Q45 shadow
}


def parse_args():
    parser = argparse.ArgumentParser(description='Backfill V9 NO_PROP_LINE predictions')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD, default: day after train_end)')
    parser.add_argument('--end', help='End date (YYYY-MM-DD, default: yesterday)')
    parser.add_argument('--system-id', default='catboost_v9',
                       help='System ID to backfill (default: catboost_v9 champion)')
    parser.add_argument('--dry-run', action='store_true', help='Show plan without writing')
    parser.add_argument('--batch-size', type=int, default=500, help='BQ insert batch size')
    return parser.parse_args()


def query_missing_players(client, system_id, start_date, end_date):
    """Query quality-ready players who have NO V9 prediction for each date.

    Finds players in ml_feature_store_v2 who pass quality gates but have no
    prediction for the given system_id. These are players who were skipped
    because they lacked prop lines at prediction time.

    Uses individual feature columns (feature_N_value) for NULL-aware reads.
    """
    feature_cols = ', '.join(
        f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
    )
    query = f"""
    WITH existing AS (
        SELECT DISTINCT player_lookup, game_date
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE system_id = '{system_id}'
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
        mf.game_id,
        mf.universal_player_id
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    LEFT JOIN existing ex
        ON mf.player_lookup = ex.player_lookup AND mf.game_date = ex.game_date
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
      AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
      AND mf.feature_quality_score >= 70
      AND mf.quality_alert_level != 'red'
      AND mf.matchup_quality_pct >= 50
      AND ex.player_lookup IS NULL
    ORDER BY mf.game_date, mf.player_lookup
    """
    return client.query(query).to_dataframe()


def extract_v9_features(row):
    """Extract 33-feature V9 vector from a feature store row.

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
    else:
        # Fallback: use features array
        feature_values = row['features']
        feature_names = row['feature_names']
        if len(feature_values) != len(feature_names):
            min_len = min(len(feature_values), len(feature_names))
            feature_values = feature_values[:min_len]
            feature_names = feature_names[:min_len]
        features_dict = dict(zip(feature_names, feature_values))

    # Build V9 vector in exact V8_FEATURES order (V9 = same features as V8)
    vector = []
    for name in V8_FEATURES:
        val = features_dict.get(name)
        if val is not None:
            vector.append(float(val))
        elif name in ('pct_paint', 'pct_mid_range', 'pct_three'):
            # Shot zone features: nullable, CatBoost handles NaN
            vector.append(np.nan)
        elif name in ('vegas_points_line', 'vegas_opening_line', 'vegas_line_move'):
            # Vegas features: nullable for NO_PROP_LINE players
            vector.append(np.nan)
        elif name == 'has_vegas_line':
            # No vegas data for these players
            vector.append(0.0)
        elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
            vector.append(float(FEATURE_DEFAULTS[name]))
        else:
            vector.append(np.nan)

    return np.array(vector)


def compute_confidence(features_dict):
    """Compute confidence score — matches CatBoostV8._calculate_confidence."""
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


def generate_predictions(model, df, system_id, model_file_name, model_sha256, train_start, train_end):
    """Generate V9 NO_PROP_LINE predictions for all rows.

    All predictions are NO_PROP_LINE since these are players without prop lines.
    Still predicts points for MAE evaluation.
    """
    records = []

    # Build feature matrix
    feature_matrix = np.array([extract_v9_features(row) for _, row in df.iterrows()])
    predicted_points_raw = model.predict(feature_matrix)

    for i, (_, row) in enumerate(df.iterrows()):
        pred = float(max(0, min(60, predicted_points_raw[i])))

        # Build features dict for confidence calculation
        feature_values = row['features']
        feature_names = row['feature_names']
        min_len = min(len(feature_values), len(feature_names))
        features_dict = dict(zip(feature_names[:min_len], feature_values[:min_len]))
        features_dict['feature_quality_score'] = row.get('feature_quality_score')

        confidence = compute_confidence(features_dict)

        # Features snapshot (first 33 features by V9/V8 name)
        v9_features = extract_v9_features(row)
        features_snapshot = json.dumps(dict(zip(
            V8_FEATURES,
            [float(v) if not np.isnan(v) else None for v in v9_features]
        )))

        record = {
            'prediction_id': str(uuid.uuid4()),
            'system_id': system_id,
            'player_lookup': row['player_lookup'],
            'universal_player_id': row.get('universal_player_id'),
            'game_date': str(row['game_date']),
            'game_id': row.get('game_id'),
            'predicted_points': round(pred, 2),
            'adjusted_points': round(pred, 2),
            'current_points_line': None,
            'line_margin': None,
            'confidence_score': confidence,
            'recommendation': 'NO_LINE',
            'is_active': True,
            'is_actionable': False,
            'filter_reason': 'no_prop_line',
            'has_prop_line': False,
            'model_version': system_id,
            'model_file_name': model_file_name,
            'model_training_start_date': train_start,
            'model_training_end_date': train_end,
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
            'line_source': 'NO_PROP_LINE',
            'sportsbook': None,
            'scoring_tier': None,
            'injury_status_at_prediction': None,
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

    system_id = args.system_id
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Validate system_id
    if system_id not in SYSTEM_TRAINING_ENDS:
        print(f"ERROR: Unknown system_id '{system_id}'")
        print(f"Known systems: {', '.join(SYSTEM_TRAINING_ENDS.keys())}")
        sys.exit(1)

    train_end = SYSTEM_TRAINING_ENDS[system_id]
    # Training start is always 2025-11-02 for all V9 models
    train_start = '2025-11-02'

    default_start = (datetime.strptime(train_end, '%Y-%m-%d').date() + timedelta(days=1)).strftime('%Y-%m-%d')
    start_date = args.start or default_start
    end_date = args.end or yesterday

    # Safety: refuse to predict within training window
    if start_date <= train_end:
        print(f"ERROR: start_date {start_date} is within training window (ends {train_end})")
        print(f"  Minimum safe start: {default_start}")
        sys.exit(1)

    print("=" * 70)
    print(" V9 NO_PROP_LINE PREDICTION BACKFILL")
    print("=" * 70)
    print(f"  System ID:    {system_id}")
    print(f"  Training:     {train_start} to {train_end}")
    print(f"  Backfill:     {start_date} to {end_date}")
    print(f"  Features:     {FEATURE_COUNT} (V9, vegas optional)")
    print(f"  Mode:         NO_PROP_LINE only (players missing predictions)")

    if args.dry_run:
        print(f"\n  Checking for gaps...")
        count_query = f"""
        WITH existing AS (
            SELECT DISTINCT player_lookup, game_date
            FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
            WHERE system_id = '{system_id}'
              AND game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT mf.game_date) as dates,
            MIN(mf.game_date) as earliest,
            MAX(mf.game_date) as latest
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        LEFT JOIN existing ex
            ON mf.player_lookup = ex.player_lookup AND mf.game_date = ex.game_date
        WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
          AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
          AND mf.feature_quality_score >= 70
          AND mf.quality_alert_level != 'red'
          AND mf.matchup_quality_pct >= 50
          AND ex.player_lookup IS NULL
        """
        counts = client.query(count_query).to_dataframe()
        r = counts.iloc[0]
        print(f"\n  DRY RUN - would backfill:")
        print(f"    Dates:       {int(r['dates'])} ({r['earliest']} to {r['latest']})")
        print(f"    Players:     {int(r['total_rows'])} total (NO_PROP_LINE)")
        print(f"\n  Run without --dry-run to execute.")
        return

    # Load V9 model
    print(f"\n  Loading CatBoost V9 model...")
    from predictions.worker.prediction_systems.catboost_v9 import CatBoostV9
    v9 = CatBoostV9()
    model_file_name = v9._model_file_name
    model_sha256 = v9._model_sha256
    print(f"  Loaded: {model_file_name} (sha256: {model_sha256})")

    # Query missing players
    print(f"\n  Querying quality-ready players without {system_id} predictions...")
    df = query_missing_players(client, system_id, start_date, end_date)
    print(f"  Retrieved {len(df)} player-date rows")

    if len(df) == 0:
        print("  No gaps found - all quality-ready players already have predictions")
        return

    # Generate predictions
    print(f"\n  Generating V9 NO_PROP_LINE predictions...")
    records = generate_predictions(
        v9.model, df, system_id, model_file_name, model_sha256, train_start, train_end
    )
    print(f"  Generated {len(records)} predictions")

    # Summary stats
    preds = np.array([r['predicted_points'] for r in records])
    game_dates = sorted(set(r['game_date'] for r in records))
    print(f"\n  Summary:")
    print(f"    Game dates:        {len(game_dates)} ({game_dates[0]} to {game_dates[-1]})")
    print(f"    Total predictions: {len(records)} (all NO_PROP_LINE)")
    print(f"    Avg predicted:     {np.mean(preds):.1f}")
    print(f"    Median predicted:  {np.median(preds):.1f}")
    print(f"    Range:             {np.min(preds):.1f} - {np.max(preds):.1f}")

    # Write to BQ
    print(f"\n  Writing to BigQuery...")
    errors = write_predictions(client, records, args.batch_size)
    if errors:
        print(f"\n  WARNING: {errors} total insert errors")
    else:
        print(f"\n  SUCCESS: {len(records)} V9 NO_PROP_LINE predictions written")

    print(f"\n{'=' * 70}")
    print(" BACKFILL COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Trigger grading backfill:")
    print(f"     PYTHONPATH=. python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\")
    print(f"       --start-date {game_dates[0]} --end-date {game_dates[-1]}")
    print("  2. Verify coverage:")
    print(f"     SELECT game_date,")
    print(f"       COUNTIF(line_source = 'NO_PROP_LINE') as no_line,")
    print(f"       COUNTIF(line_source != 'NO_PROP_LINE') as has_line,")
    print(f"       COUNT(*) as total")
    print(f"     FROM nba_predictions.player_prop_predictions")
    print(f"     WHERE system_id = '{system_id}' AND game_date >= '{game_dates[0]}'")
    print(f"     GROUP BY 1 ORDER BY 1")


if __name__ == "__main__":
    main()
