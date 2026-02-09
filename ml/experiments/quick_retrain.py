#!/usr/bin/env python3
"""
Quick Model Retrain - Simple Monthly Retraining Script

Designed for the /model-experiment skill and monthly retraining pipeline.
Trains a CatBoost model on recent data and evaluates against V9 baseline.

Model Governance (Session 163):
- Models are saved with standard naming: catboost_v9_{train_end}_{timestamp}.cbm
- SHA256 hash computed and displayed for registry
- Vegas bias check: BLOCKS if avg pred_vs_vegas outside +/- 1.5
- Tier bias check: BLOCKS if any tier > +/- 5 points
- Must pass ALL gates before manual promotion to production
- Use ./bin/model-registry.sh to manage the registry

Promotion Checklist (do NOT skip):
1. Holdout evaluation on >= 7 days (this script)
2. High-edge (3+) hit rate >= 60%
3. pred_vs_vegas bias within +/- 1.5
4. No critical tier bias (> +/- 5)
5. Register in model_registry table
6. Upload to GCS with standard naming
7. Shadow test for 2+ days before switching CATBOOST_V9_MODEL_PATH

Usage:
    # Quick retrain with defaults (last 60 days training, last 7 days eval)
    PYTHONPATH=. python ml/experiments/quick_retrain.py --name "FEB_MONTHLY"

    # Custom dates
    PYTHONPATH=. python ml/experiments/quick_retrain.py \
        --name "JAN_CUSTOM" \
        --train-start 2025-12-01 --train-end 2026-01-20 \
        --eval-start 2026-01-21 --eval-end 2026-01-28

    # Dry run
    PYTHONPATH=. python ml/experiments/quick_retrain.py --name "TEST" --dry-run

Session 58 - Monthly Retraining Infrastructure
Session 163 - Model Governance Gates
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import hashlib
import uuid
import json
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
import catboost as cb

# Import canonical feature contract - SINGLE SOURCE OF TRUTH
from shared.ml.feature_contract import (
    V9_CONTRACT,
    V9_FEATURE_NAMES,
    FEATURE_DEFAULTS,
    get_contract,
    validate_all_contracts,
)

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

# V9 baseline (computed from production prediction_accuracy Feb 2026)
# Based on catboost_v9 graded predictions since 2025-11-02
V9_BASELINE = {
    "mae": 5.14,
    "hit_rate_all": 54.53,
    "hit_rate_edge_3plus": 63.72,  # 3+ edge (medium quality)
    "hit_rate_edge_5plus": 75.33,  # 5+ edge (high quality)
    # Tier bias baselines (target: 0 for all tiers)
    "bias_stars": 0.0,      # 25+ points
    "bias_starters": 0.0,   # 15-24 points
    "bias_role": 0.0,       # 5-14 points
    "bias_bench": 0.0,      # <5 points
}

# Use canonical feature names from contract - DO NOT DUPLICATE
FEATURES = V9_FEATURE_NAMES


def parse_args():
    parser = argparse.ArgumentParser(description='Quick model retrain for monthly updates')
    parser.add_argument('--name', required=True, help='Experiment name (e.g., FEB_MONTHLY)')
    parser.add_argument('--hypothesis', default='', help='What we are testing')
    parser.add_argument('--tags', default='monthly', help='Comma-separated tags')

    # Explicit dates
    parser.add_argument('--train-start', help='Training start (YYYY-MM-DD)')
    parser.add_argument('--train-end', help='Training end (YYYY-MM-DD)')
    parser.add_argument('--eval-start', help='Eval start (YYYY-MM-DD)')
    parser.add_argument('--eval-end', help='Eval end (YYYY-MM-DD)')

    # Relative dates (defaults)
    parser.add_argument('--train-days', type=int, default=60, help='Days of training (default: 60)')
    parser.add_argument('--eval-days', type=int, default=7, help='Days of eval (default: 7)')

    # Line source for evaluation
    parser.add_argument('--use-production-lines', action='store_true', default=True,
                       help='Use production lines from prediction_accuracy (default: True)')
    parser.add_argument('--no-production-lines', dest='use_production_lines', action='store_false',
                       help='Use raw sportsbook lines instead of production lines')
    parser.add_argument('--line-source', choices=['draftkings', 'bettingpros', 'fanduel'],
                       default='draftkings',
                       help='Sportsbook for eval lines when --no-production-lines (default: draftkings)')

    parser.add_argument('--dry-run', action='store_true', help='Show plan only')
    parser.add_argument('--skip-register', action='store_true', help='Skip ml_experiments')
    parser.add_argument('--force', action='store_true', help='Force retrain even if duplicate training dates exist')
    return parser.parse_args()


def get_dates(args):
    """Compute date ranges."""
    if args.train_start and args.train_end and args.eval_start and args.eval_end:
        return {
            'train_start': args.train_start,
            'train_end': args.train_end,
            'eval_start': args.eval_start,
            'eval_end': args.eval_end,
        }

    yesterday = date.today() - timedelta(days=1)
    eval_end = yesterday
    eval_start = eval_end - timedelta(days=args.eval_days - 1)
    train_end = eval_start - timedelta(days=1)
    train_start = train_end - timedelta(days=args.train_days - 1)

    return {
        'train_start': train_start.strftime('%Y-%m-%d'),
        'train_end': train_end.strftime('%Y-%m-%d'),
        'eval_start': eval_start.strftime('%Y-%m-%d'),
        'eval_end': eval_end.strftime('%Y-%m-%d'),
    }


def check_training_data_quality(client, start, end):
    """
    Report on training data quality before training.

    Outputs a quality summary and returns True if data quality is acceptable.
    Session 104: Prevent training on low-quality data.
    Session 139: Uses is_training_ready flag and quality visibility fields.
    """
    query = f"""
    SELECT
      COUNT(*) as total_records,
      COUNTIF(is_training_ready = TRUE) as training_ready,
      COUNTIF(is_quality_ready = TRUE) as quality_ready,
      COUNTIF(quality_alert_level = 'green') as green_alerts,
      COUNTIF(quality_alert_level = 'yellow') as yellow_alerts,
      COUNTIF(quality_alert_level = 'red') as red_alerts,
      COUNTIF(feature_quality_score >= 85) as high_quality,
      COUNTIF(feature_quality_score >= 70 AND feature_quality_score < 85) as medium_quality,
      COUNTIF(feature_quality_score < 70) as low_quality,
      COUNTIF(data_source = 'phase4_partial') as partial_data,
      COUNTIF(data_source = 'early_season') as early_season_data,
      ROUND(AVG(feature_quality_score), 1) as avg_quality,
      ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
    WHERE game_date BETWEEN '{start}' AND '{end}'
      AND feature_count >= 33
    """
    result = client.query(query).to_dataframe()

    total = result['total_records'].iloc[0]
    training_ready = result['training_ready'].iloc[0]
    quality_ready = result['quality_ready'].iloc[0]
    high_q = result['high_quality'].iloc[0]
    low_q = result['low_quality'].iloc[0]
    partial = result['partial_data'].iloc[0]
    early = result['early_season_data'].iloc[0]
    avg_q = result['avg_quality'].iloc[0]
    green = result['green_alerts'].iloc[0]
    yellow = result['yellow_alerts'].iloc[0]
    red = result['red_alerts'].iloc[0]
    avg_matchup = result['avg_matchup_quality'].iloc[0]

    print("\n=== Training Data Quality ===")
    print(f"Total records: {total:,}")
    print(f"Training-ready (is_training_ready): {training_ready:,} ({100*training_ready/total:.1f}%)")
    print(f"Quality-ready (is_quality_ready): {quality_ready:,} ({100*quality_ready/total:.1f}%)")
    print(f"Alert levels: {green:,} green, {yellow:,} yellow, {red:,} red")
    print(f"Avg matchup quality: {avg_matchup:.1f}%")
    print(f"High quality (85+): {high_q:,} ({100*high_q/total:.1f}%)")
    print(f"Medium quality (70-84): {result['medium_quality'].iloc[0]:,}")
    print(f"Low quality (<70): {low_q:,} ({100*low_q/total:.1f}%)")
    print(f"Partial data: {partial:,}")
    print(f"Early season data: {early:,}")
    print(f"Avg quality score: {avg_q:.1f}")

    # Warn if quality is poor
    if training_ready < total * 0.7:
        print("WARNING: <70% training-ready data. Check missing processors.")
    if red > total * 0.1:
        print("WARNING: >10% red alerts in training set")
    if low_q > total * 0.1:
        print("WARNING: >10% low quality data in training set")
    if partial > total * 0.05:
        print("WARNING: >5% partial data in training set")
    if early > total * 0.2:
        print("WARNING: >20% early season data in training set")

    return {'total': total, 'low_quality_pct': 100*low_q/total if total > 0 else 0, 'avg_quality': avg_q,
            'training_ready_pct': 100*training_ready/total if total > 0 else 0}


def check_duplicate_model(client, train_start, train_end):
    """
    Check if a model with the same training dates already exists in the registry.

    Session 164: Prevent accidentally retraining the same model.

    Returns:
        List of existing models with same training dates, or empty list if none found.
    """
    query = f"""
    SELECT model_id, status, is_production, sha256_hash, created_at
    FROM nba_predictions.model_registry
    WHERE training_start_date = '{train_start}'
      AND training_end_date = '{train_end}'
    ORDER BY created_at DESC
    """
    result = client.query(query).to_dataframe()
    return result.to_dict('records') if len(result) > 0 else []


def load_train_data(client, start, end, min_quality_score=70):
    """
    Load training data from feature store with quality filters.

    Uses shared.ml.training_data_loader for enforced zero-tolerance quality gates.
    Session 157: Migrated to shared loader to prevent contamination bugs.

    Args:
        client: BigQuery client
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        min_quality_score: Minimum feature_quality_score (default 70)
    """
    from shared.ml.training_data_loader import load_clean_training_data

    # Session 107: Exclude records where pts_avg_last_5 is default 10.0 but pts_avg_last_10
    # shows the player should be higher. These are cold start errors (only 15 records total).
    bad_default_filter = "NOT (mf.features[OFFSET(0)] = 10.0 AND mf.features[OFFSET(1)] > 15)"

    return load_clean_training_data(
        client, start, end,
        min_quality_score=min_quality_score,
        additional_where=bad_default_filter,
    )


def load_eval_data_from_production(client, start, end, system_id='catboost_v9'):
    """Load eval features + production lines for apples-to-apples comparison.

    Uses prediction_accuracy which has the EXACT lines production used at prediction
    time (multi-source cascade: DK → FD → BetMGM with OddsAPI → BettingPros fallback).
    This eliminates the mismatch between experiment eval and production performance.

    Session 166: Replaces DraftKings-only eval with production line matching.

    Args:
        client: BigQuery client
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        system_id: Model system ID to match (default: 'catboost_v9')
    """
    from shared.ml.training_data_loader import get_quality_where_clause
    quality_clause = get_quality_where_clause("mf")

    query = f"""
    WITH production_lines AS (
        SELECT player_lookup, game_date, line_value, actual_points,
               prediction_correct, recommendation
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date BETWEEN '{start}' AND '{end}'
          AND system_id = '{system_id}'
          AND recommendation IN ('OVER', 'UNDER')
          AND prediction_correct IS NOT NULL
          AND line_value IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY player_lookup, game_date
            ORDER BY line_value DESC
        ) = 1
    )
    SELECT mf.features, mf.feature_names,
           CAST(pl.actual_points AS FLOAT64) as actual_points,
           CAST(pl.line_value AS FLOAT64) as vegas_line
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN production_lines pl
        ON mf.player_lookup = pl.player_lookup AND mf.game_date = pl.game_date
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND {quality_clause}
    """
    return client.query(query).to_dataframe()


def load_eval_data(client, start, end, line_source='draftkings'):
    """Load eval data with raw prop lines (fallback when no production predictions exist).

    Uses shared.ml.training_data_loader for enforced zero-tolerance quality gates.
    Session 157: Migrated to shared loader to prevent contamination bugs.

    Args:
        client: BigQuery client
        start: Start date (YYYY-MM-DD)
        end: End date (YYYY-MM-DD)
        line_source: 'draftkings' (default), 'bettingpros', or 'fanduel'
    """
    from shared.ml.training_data_loader import get_quality_where_clause

    # Configure table and filter based on line source
    if line_source == 'draftkings':
        table = f"`{PROJECT_ID}.nba_raw.odds_api_player_points_props`"
        bookmaker_filter = "bookmaker = 'draftkings'"
        line_col = "points_line"
    elif line_source == 'fanduel':
        table = f"`{PROJECT_ID}.nba_raw.odds_api_player_points_props`"
        bookmaker_filter = "bookmaker = 'fanduel'"
        line_col = "points_line"
    else:  # bettingpros
        table = f"`{PROJECT_ID}.nba_raw.bettingpros_player_points_props`"
        bookmaker_filter = "bookmaker = 'BettingPros Consensus' AND bet_side = 'over'"
        line_col = "points_line"

    quality_clause = get_quality_where_clause("mf")

    query = f"""
    WITH lines AS (
      SELECT game_date, player_lookup, {line_col} as line
      FROM {table}
      WHERE {bookmaker_filter}
        AND game_date BETWEEN '{start}' AND '{end}'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
    )
    SELECT mf.features, mf.feature_names, pgs.points as actual_points, l.line as vegas_line
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    JOIN lines l ON mf.player_lookup = l.player_lookup AND mf.game_date = l.game_date
    WHERE mf.game_date BETWEEN '{start}' AND '{end}'
      AND {quality_clause}
      AND pgs.points IS NOT NULL
      AND (l.line - FLOOR(l.line)) IN (0, 0.5)
    """
    return client.query(query).to_dataframe()


def prepare_features(df, contract=V9_CONTRACT):
    """
    Prepare feature matrix using NAME-BASED extraction (not position-based).

    Session 107: Changed from position slicing (row[:33]) to name-based extraction.
    This is SAFE even if feature store column order changes.

    Args:
        df: DataFrame with 'features' and 'feature_names' columns
        contract: ModelFeatureContract defining expected features (default V9)

    Returns:
        X: Feature DataFrame with columns in contract order
        y: Target Series (actual_points)
    """
    rows = []
    for _, row in df.iterrows():
        feature_values = row['features']
        feature_names = row['feature_names']

        # Convert parallel arrays to dictionary
        if len(feature_values) != len(feature_names):
            min_len = min(len(feature_values), len(feature_names))
            feature_values = feature_values[:min_len]
            feature_names = feature_names[:min_len]

        features_dict = dict(zip(feature_names, feature_values))

        # Extract features BY NAME in contract order
        row_data = {}
        for name in contract.feature_names:
            if name in features_dict and features_dict[name] is not None:
                row_data[name] = float(features_dict[name])
            elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
                row_data[name] = float(FEATURE_DEFAULTS[name])
            else:
                row_data[name] = np.nan  # Will be filled by median

        rows.append(row_data)

    X = pd.DataFrame(rows, columns=contract.feature_names)
    X = X.fillna(X.median())
    y = df['actual_points'].astype(float)
    return X, y


def compute_hit_rate(preds, actuals, lines, min_edge=1.0):
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


def compute_tier_bias(preds, actuals, season_avgs=None):
    """
    Compute prediction bias by player tier based on season average (pre-game info).

    Session 166: Fixed to use points_avg_season (feature index 2) instead of
    actual_points. Using actuals was hindsight bias — Session 124 proved tiers
    should be based on what the model knows pre-game.

    Tier definitions (based on season average, not actual points):
    - Stars: 25+ ppg season avg
    - Starters: 15-24 ppg season avg
    - Role: 5-14 ppg season avg
    - Bench: <5 ppg season avg

    Args:
        preds: Model predictions
        actuals: Actual points scored (for computing bias = pred - actual)
        season_avgs: Pre-game season averages for tier classification.
                     Falls back to actuals if not provided (backward compat).

    Returns dict with bias for each tier and warning flag if any tier > ±5.
    """
    tier_values = season_avgs if season_avgs is not None else actuals

    tiers = {
        'Stars (25+)': tier_values >= 25,
        'Starters (15-24)': (tier_values >= 15) & (tier_values < 25),
        'Role (5-14)': (tier_values >= 5) & (tier_values < 15),
        'Bench (<5)': tier_values < 5
    }

    results = {}
    has_critical_bias = False

    for tier_name, mask in tiers.items():
        if mask.sum() > 0:
            tier_preds = preds[mask]
            tier_actuals = actuals[mask]
            bias = np.mean(tier_preds - tier_actuals)
            results[tier_name] = {
                'bias': round(bias, 2),
                'count': int(mask.sum()),
                'critical': abs(bias) > 5
            }
            if abs(bias) > 5:
                has_critical_bias = True
        else:
            results[tier_name] = {'bias': None, 'count': 0, 'critical': False}

    results['has_critical_bias'] = has_critical_bias
    return results


def main():
    args = parse_args()
    dates = get_dates(args)
    exp_id = str(uuid.uuid4())[:8]

    # Validate feature contract BEFORE doing anything (Session 107)
    print("Validating feature contracts...")
    try:
        validate_all_contracts()
        print(f"  Using {V9_CONTRACT.model_version} contract: {V9_CONTRACT.feature_count} features")
    except Exception as e:
        print(f"❌ Feature contract validation FAILED: {e}")
        print("   Fix shared/ml/feature_contract.py before training!")
        return

    # Compute actual day counts from dates
    train_start_dt = datetime.strptime(dates['train_start'], '%Y-%m-%d').date()
    train_end_dt = datetime.strptime(dates['train_end'], '%Y-%m-%d').date()
    eval_start_dt = datetime.strptime(dates['eval_start'], '%Y-%m-%d').date()
    eval_end_dt = datetime.strptime(dates['eval_end'], '%Y-%m-%d').date()
    train_days_actual = (train_end_dt - train_start_dt).days + 1
    eval_days_actual = (eval_end_dt - eval_start_dt).days + 1

    print("=" * 70)
    print(f" QUICK RETRAIN: {args.name}")
    print("=" * 70)
    print(f"Training:   {dates['train_start']} to {dates['train_end']} ({train_days_actual} days)")
    print(f"Evaluation: {dates['eval_start']} to {dates['eval_end']} ({eval_days_actual} days)")
    line_source_desc = "production (prediction_accuracy)" if args.use_production_lines else args.line_source
    print(f"Line Source: {line_source_desc}")
    print()

    if args.dry_run:
        print("DRY RUN - would train on above dates and compare to V8 baseline")
        return

    client = bigquery.Client(project=PROJECT_ID)

    # Check for duplicate models (Session 164: prevent accidental retrains)
    print("\nChecking for existing models with same training dates...")
    existing_models = check_duplicate_model(client, dates['train_start'], dates['train_end'])
    if existing_models:
        print(f"⚠️  WARNING: Found {len(existing_models)} existing model(s) with same training dates:")
        for model in existing_models:
            status_emoji = "🟢" if model['is_production'] else "🟡" if model['status'] == 'active' else "🔴"
            print(f"  {status_emoji} {model['model_id']} - {model['status']} (created: {model['created_at']})")
            if model.get('sha256_hash'):
                print(f"     SHA256: {model['sha256_hash'][:12]}...")
        print()
        if not args.force:
            print("❌ ERROR: Duplicate training dates detected!")
            print("   This model may have already been trained and evaluated.")
            print("   Use --force to proceed anyway (not recommended)")
            return
        else:
            print("--force flag provided, proceeding with retrain...")

    # Check training data quality BEFORE loading (Session 104)
    quality_stats = check_training_data_quality(client, dates['train_start'], dates['train_end'])
    if quality_stats['avg_quality'] < 60:
        print("\n❌ ERROR: Average quality score too low (<60). Check data sources.")
        return

    # Load data
    print("\nLoading training data (with quality filter >= 70)...")
    df_train = load_train_data(client, dates['train_start'], dates['train_end'])
    print(f"  {len(df_train):,} samples")

    print("Loading evaluation data...")
    if args.use_production_lines:
        print("  Using production lines (prediction_accuracy — multi-source cascade)")
        df_eval = load_eval_data_from_production(client, dates['eval_start'], dates['eval_end'])
        if len(df_eval) == 0:
            print("  WARNING: No production predictions found for eval period.")
            print(f"  Falling back to raw {args.line_source} lines...")
            df_eval = load_eval_data(client, dates['eval_start'], dates['eval_end'], args.line_source)
    else:
        print(f"  Using raw {args.line_source} lines")
        df_eval = load_eval_data(client, dates['eval_start'], dates['eval_end'], args.line_source)
    print(f"  {len(df_eval):,} samples")

    if len(df_train) < 1000 or len(df_eval) < 100:
        print("ERROR: Not enough data")
        return

    # Prepare
    X_train_full, y_train_full = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    lines = df_eval['vegas_line'].values

    X_train, X_val, y_train, y_val = train_test_split(X_train_full, y_train_full, test_size=0.15, random_state=42)

    # Train
    print("\nTraining CatBoost...")
    model = cb.CatBoostRegressor(
        iterations=1000, learning_rate=0.05, depth=6,
        l2_leaf_reg=3, random_seed=42, verbose=100, early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=100)

    # Evaluate
    print("\nEvaluating...")
    preds = model.predict(X_eval)
    mae = mean_absolute_error(y_eval, preds)

    hr_all, bets_all = compute_hit_rate(preds, y_eval.values, lines, min_edge=1.0)
    hr_edge3, bets_edge3 = compute_hit_rate(preds, y_eval.values, lines, min_edge=3.0)
    hr_edge5, bets_edge5 = compute_hit_rate(preds, y_eval.values, lines, min_edge=5.0)

    # Compute tier bias using pre-game season average (Session 166: fix hindsight bias)
    # Feature index 2 = points_avg_season (from V9 contract)
    season_avgs = X_eval['points_avg_season'].values if 'points_avg_season' in X_eval.columns else None
    tier_bias = compute_tier_bias(preds, y_eval.values, season_avgs=season_avgs)

    # Vegas bias gate (Session 163 — the Feb 2 retrain had good MAE but -2.26 Vegas bias)
    pred_vs_vegas = np.mean(preds - lines)
    VEGAS_BIAS_LIMIT = 1.5

    # Save model with standard naming (Session 164: include train start-end range in filename)
    MODEL_OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    train_start_compact = dates['train_start'].replace('-', '')
    train_end_compact = dates['train_end'].replace('-', '')
    model_path = MODEL_OUTPUT_DIR / f"catboost_v9_33f_train{train_start_compact}-{train_end_compact}_{ts}.cbm"
    model.save_model(str(model_path))

    # Compute SHA256 for registry
    sha256 = hashlib.sha256()
    with open(model_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    model_sha256 = sha256.hexdigest()

    # Results
    print("\n" + "=" * 70)
    print(" RESULTS vs V9 BASELINE")
    print("=" * 70)

    MIN_BETS_RELIABLE = 50  # Minimum bets for statistically reliable hit rate

    def compare(name, new_val, baseline, n_bets, higher_better=True):
        if new_val is None:
            return f"{name}: N/A", None
        diff = new_val - baseline
        symbol = "+" if diff > 0 else ""
        better = (diff > 0) == higher_better

        # Add sample size warning
        size_warn = "" if n_bets >= MIN_BETS_RELIABLE else f" (n={n_bets}, LOW)"

        emoji = "✅" if better else "❌" if abs(diff) > 2 else "⚠️"
        return f"{name}: {new_val:.2f}% vs {baseline:.2f}% ({symbol}{diff:.2f}%) {emoji}{size_warn}", better

    mae_diff = mae - V9_BASELINE['mae']
    mae_emoji = "✅" if mae_diff < 0 else "❌" if mae_diff > 0.2 else "⚠️"
    print(f"MAE: {mae:.4f} vs {V9_BASELINE['mae']:.4f} ({mae_diff:+.4f}) {mae_emoji}")
    print()

    hr_all_str, hr_all_better = compare("Hit Rate (all)", hr_all, V9_BASELINE['hit_rate_all'], bets_all)
    hr_edge3_str, hr_edge3_better = compare("Hit Rate (edge 3+)", hr_edge3, V9_BASELINE['hit_rate_edge_3plus'], bets_edge3)
    hr_edge5_str, hr_edge5_better = compare("Hit Rate (edge 5+)", hr_edge5, V9_BASELINE['hit_rate_edge_5plus'], bets_edge5)

    print(hr_all_str)
    print(hr_edge3_str)
    print(hr_edge5_str)

    # Tier Bias Analysis (NEW: Session 104)
    print("\n" + "-" * 40)
    print("TIER BIAS ANALYSIS (target: 0 for all)")
    print("-" * 40)
    for tier_name, data in tier_bias.items():
        if tier_name == 'has_critical_bias':
            continue
        if data['count'] > 0:
            emoji = "🔴" if data['critical'] else "✅"
            print(f"  {tier_name}: {data['bias']:+.2f} pts (n={data['count']}) {emoji}")
        else:
            print(f"  {tier_name}: N/A (no samples)")

    if tier_bias['has_critical_bias']:
        print("\nCRITICAL: Tier bias > +/-5 detected! Model has regression-to-mean issue.")

    # Vegas Bias Analysis (Session 163 — most important single metric)
    print("\n" + "-" * 40)
    print("VEGAS BIAS (pred_vs_vegas)")
    print("-" * 40)
    vegas_emoji = "OK" if abs(pred_vs_vegas) <= VEGAS_BIAS_LIMIT else "FAIL"
    print(f"  avg(predicted - vegas_line) = {pred_vs_vegas:+.2f} [{vegas_emoji}]")
    print(f"  (limit: +/-{VEGAS_BIAS_LIMIT}. Feb 2 retrain was -2.26 = UNDER bias disaster)")
    if abs(pred_vs_vegas) > VEGAS_BIAS_LIMIT:
        print(f"  BLOCKED: Vegas bias outside +/-{VEGAS_BIAS_LIMIT} — model is miscalibrated vs market")

    # Governance Gate Summary
    print("\n" + "=" * 70)
    print(" GOVERNANCE GATES")
    print("=" * 70)
    mae_better = mae < V9_BASELINE['mae']
    edge3_reliable = bets_edge3 >= MIN_BETS_RELIABLE
    edge5_reliable = bets_edge5 >= MIN_BETS_RELIABLE

    gates = []
    gates.append(("MAE improvement", mae_better, f"{mae:.4f} vs {V9_BASELINE['mae']:.4f}"))
    gates.append(("Hit rate (3+) >= 60%", (hr_edge3 or 0) >= 60, f"{hr_edge3}% (n={bets_edge3})"))
    gates.append(("Hit rate (3+) sample >= 50", edge3_reliable, f"n={bets_edge3}"))
    gates.append((f"Vegas bias within +/-{VEGAS_BIAS_LIMIT}", abs(pred_vs_vegas) <= VEGAS_BIAS_LIMIT, f"{pred_vs_vegas:+.2f}"))
    gates.append(("No critical tier bias", not tier_bias['has_critical_bias'], ""))

    all_passed = True
    for gate_name, passed, detail in gates:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False
        print(f"  [{status}] {gate_name}: {detail}")

    print()
    if all_passed:
        print("ALL GATES PASSED — model eligible for shadow testing")
        print("Next steps:")
        print(f"  1. Upload: gsutil cp {model_path} gs://nba-props-platform-models/catboost/v9/{model_path.name}")
        print(f"  2. Register: ./bin/model-registry.sh  (add to BQ + manifest)")
        print(f"  3. Shadow test 2+ days, then update CATBOOST_V9_MODEL_PATH env var")
    else:
        print("GATES FAILED — do NOT deploy this model")
        print("Fix the failing gates or try different training parameters")

    print(f"\nModel saved: {model_path}")
    print(f"SHA256: {model_sha256}")
    print(f"Size: {model_path.stat().st_size:,} bytes")

    # Register
    if not args.skip_register:
        try:
            row = {
                'experiment_id': exp_id,
                'experiment_name': args.name,
                'experiment_type': 'monthly_retrain',
                'hypothesis': args.hypothesis or f'Monthly retrain {train_days_actual}d train, {eval_days_actual}d eval',
                'config_json': json.dumps({'train_days': train_days_actual, 'eval_days': eval_days_actual, 'features': 33, 'line_source': 'production' if args.use_production_lines else args.line_source}),
                'train_period': {'start_date': dates['train_start'], 'end_date': dates['train_end'], 'samples': len(df_train)},
                'eval_period': {'start_date': dates['eval_start'], 'end_date': dates['eval_end'], 'samples': len(df_eval)},
                'results_json': json.dumps({
                    'mae': round(mae, 4),
                    'hit_rate_all': hr_all, 'bets_all': bets_all,
                    'hit_rate_edge_3plus': hr_edge3, 'bets_edge_3plus': bets_edge3,
                    'hit_rate_edge_5plus': hr_edge5, 'bets_edge_5plus': bets_edge5,
                    'tier_bias': {k: {sk: (bool(sv) if isinstance(sv, (bool, np.bool_)) else sv) for sk, sv in v.items()} for k, v in tier_bias.items() if k != 'has_critical_bias'},
                    'has_critical_bias': bool(tier_bias['has_critical_bias']),
                    'pred_vs_vegas_bias': round(float(pred_vs_vegas), 4),
                    'all_gates_passed': all_passed,
                    'model_sha256': model_sha256,
                }),
                'model_path': str(model_path),
                'status': 'completed',
                'tags': [t.strip() for t in args.tags.split(',') if t.strip()],
                'created_at': datetime.now(timezone.utc).isoformat(),
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }
            errors = client.insert_rows_json(f"{PROJECT_ID}.nba_predictions.ml_experiments", [row])
            if not errors:
                print(f"Registered in ml_experiments (ID: {exp_id})")
        except Exception as e:
            print(f"Warning: Could not register: {e}")


if __name__ == "__main__":
    main()
