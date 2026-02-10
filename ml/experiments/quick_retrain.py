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
5. Directional balance: both OVER and UNDER edge 3+ hit rate >= 52.4%
6. Register in model_registry table
7. Upload to GCS with standard naming
8. Shadow test for 2+ days before switching CATBOOST_V9_MODEL_PATH

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

    # New experiment features
    parser.add_argument('--recency-weight', type=int, default=None, metavar='DAYS',
                       help='Recency weight half-life in days (e.g., 30). Exponential decay.')
    parser.add_argument('--walkforward', action='store_true',
                       help='Run walk-forward validation (per-week eval breakdown)')
    parser.add_argument('--tune', action='store_true',
                       help='Run hyperparameter grid search before final training')

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
           CAST(pl.line_value AS FLOAT64) as vegas_line,
           mf.game_date
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
    SELECT mf.features, mf.feature_names, pgs.points as actual_points, l.line as vegas_line,
           mf.game_date
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


def calculate_sample_weights(dates, half_life_days):
    """
    Calculate exponential recency weights for training samples.

    More recent samples get higher weights, decaying exponentially.
    Ported from ml/archive/experiments/train_walkforward.py.

    Args:
        dates: Series of game dates
        half_life_days: Number of days for weight to decay by 50%

    Returns:
        Normalized weights array (mean = 1.0 to preserve effective sample size)
    """
    dates = pd.to_datetime(dates)
    max_date = dates.max()
    days_old = (max_date - dates).dt.days

    decay_rate = np.log(2) / half_life_days
    weights = np.exp(-days_old * decay_rate)

    # Normalize so mean weight = 1.0
    weights = weights / weights.mean()
    return weights.values


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


def display_feature_importance(model, feature_names, top_n=10):
    """
    Display and return CatBoost feature importance rankings.

    Args:
        model: Trained CatBoostRegressor
        feature_names: List of feature names
        top_n: Number of top features to display

    Returns:
        List of (feature_name, importance) tuples sorted descending.
    """
    importances = model.get_feature_importance()
    pairs = sorted(zip(feature_names, importances), key=lambda x: -x[1])

    print("\n" + "-" * 40)
    print(f"FEATURE IMPORTANCE (top {top_n})")
    print("-" * 40)
    for i, (name, imp) in enumerate(pairs[:top_n], 1):
        bar = "█" * int(imp / pairs[0][1] * 20)
        print(f"  {i:2d}. {name:<30s} {imp:6.2f}  {bar}")

    # Show bottom 5 too
    if len(pairs) > top_n:
        print(f"  ...")
        for name, imp in pairs[-5:]:
            print(f"      {name:<30s} {imp:6.2f}")

    return pairs


def compute_directional_hit_rates(preds, actuals, lines, min_edge=3.0):
    """
    Compute OVER/UNDER directional hit rates for governance gate.

    Session 175: Session 173 discovered OVER collapsed from 76.8% -> 44.1%
    while overall edge 3+ only showed moderate decline. This gate catches
    directional imbalance that the overall hit rate misses.

    Args:
        preds: Model predictions (numpy array)
        actuals: Actual points scored (numpy array)
        lines: Vegas lines (numpy array)
        min_edge: Minimum edge threshold (default 3.0)

    Returns:
        dict with over_hit_rate, under_hit_rate, directional_balance_ok,
        worst_direction, worst_rate, over_graded, under_graded.
    """
    BREAKEVEN = 52.4  # Breakeven at -110 odds

    edges = preds - lines
    mask = np.abs(edges) >= min_edge

    # OVER: model predicts above line
    over_mask = mask & (edges > 0)
    under_mask = mask & (edges < 0)

    over_hit_rate = None
    under_hit_rate = None
    over_graded = 0
    under_graded = 0

    if over_mask.sum() > 0:
        over_actual = actuals[over_mask]
        over_lines = lines[over_mask]
        over_wins = over_actual > over_lines
        over_pushes = over_actual == over_lines
        over_graded = int(over_mask.sum() - over_pushes.sum())
        if over_graded > 0:
            over_hit_rate = round(over_wins.sum() / over_graded * 100, 1)

    if under_mask.sum() > 0:
        under_actual = actuals[under_mask]
        under_lines = lines[under_mask]
        under_wins = under_actual < under_lines
        under_pushes = under_actual == under_lines
        under_graded = int(under_mask.sum() - under_pushes.sum())
        if under_graded > 0:
            under_hit_rate = round(under_wins.sum() / under_graded * 100, 1)

    # Determine balance
    over_ok = over_hit_rate is None or over_hit_rate >= BREAKEVEN
    under_ok = under_hit_rate is None or under_hit_rate >= BREAKEVEN
    balance_ok = over_ok and under_ok

    # Find worst direction
    worst_direction = None
    worst_rate = None
    if over_hit_rate is not None and under_hit_rate is not None:
        if over_hit_rate <= under_hit_rate:
            worst_direction = 'OVER'
            worst_rate = over_hit_rate
        else:
            worst_direction = 'UNDER'
            worst_rate = under_hit_rate
    elif over_hit_rate is not None:
        worst_direction = 'OVER'
        worst_rate = over_hit_rate
    elif under_hit_rate is not None:
        worst_direction = 'UNDER'
        worst_rate = under_hit_rate

    return {
        'over_hit_rate': over_hit_rate,
        'under_hit_rate': under_hit_rate,
        'over_graded': over_graded,
        'under_graded': under_graded,
        'directional_balance_ok': balance_ok,
        'worst_direction': worst_direction,
        'worst_rate': worst_rate,
    }


def run_walkforward_eval(model, df_eval, X_eval, y_eval, lines):
    """
    Run walk-forward evaluation: split eval period into weekly chunks.

    Reports per-week MAE, hit rates (all, 3+, 5+), and Vegas bias so
    we can see if model performance is stable or degrading over time.

    Args:
        model: Trained CatBoostRegressor
        df_eval: Eval DataFrame (must have 'game_date' column)
        X_eval: Feature matrix
        y_eval: Target series
        lines: Vegas lines array

    Returns:
        List of per-week result dicts.
    """
    preds = model.predict(X_eval)
    game_dates = pd.to_datetime(df_eval['game_date'])

    # Create weekly bins from Monday
    week_labels = game_dates.dt.to_period('W-SUN')
    unique_weeks = sorted(week_labels.unique())

    print("\n" + "=" * 70)
    print(" WALK-FORWARD EVALUATION (per-week)")
    print("=" * 70)
    print(f"{'Week':<22s} {'N':>5s} {'MAE':>6s} {'HR All':>7s} {'HR 3+':>7s} {'HR 5+':>7s} {'Bias':>7s}")
    print("-" * 70)

    week_results = []
    for week in unique_weeks:
        mask = (week_labels == week).values
        w_preds = preds[mask]
        w_actuals = y_eval.values[mask]
        w_lines = lines[mask]
        n = mask.sum()

        w_mae = mean_absolute_error(w_actuals, w_preds)
        w_hr_all, w_n_all = compute_hit_rate(w_preds, w_actuals, w_lines, min_edge=1.0)
        w_hr_3, w_n_3 = compute_hit_rate(w_preds, w_actuals, w_lines, min_edge=3.0)
        w_hr_5, w_n_5 = compute_hit_rate(w_preds, w_actuals, w_lines, min_edge=5.0)
        w_bias = float(np.mean(w_preds - w_lines))

        hr_all_s = f"{w_hr_all:.1f}%" if w_hr_all is not None else "N/A"
        hr_3_s = f"{w_hr_3:.1f}%" if w_hr_3 is not None else "N/A"
        hr_5_s = f"{w_hr_5:.1f}%" if w_hr_5 is not None else "N/A"

        week_str = str(week)
        print(f"  {week_str:<20s} {n:5d} {w_mae:6.2f} {hr_all_s:>7s} {hr_3_s:>7s} {hr_5_s:>7s} {w_bias:+7.2f}")

        week_results.append({
            'week': week_str,
            'n': int(n),
            'mae': round(w_mae, 4),
            'hr_all': w_hr_all,
            'hr_edge3': w_hr_3,
            'hr_edge5': w_hr_5,
            'bias': round(w_bias, 4),
        })

    print("-" * 70)
    return week_results


def run_hyperparam_search(X_train, y_train, X_val, y_val, lines_val, w_train=None):
    """
    Small grid search over depth × l2_leaf_reg × learning_rate.

    Selects best params by edge 3+ hit rate, with MAE as tiebreaker.
    Uses val split for evaluation (approximate lines from vegas_points_line feature).

    Args:
        X_train, y_train: Training data
        X_val, y_val: Validation data
        lines_val: Vegas lines for val set (approximate, from features)
        w_train: Optional sample weights

    Returns:
        Dict of best hyperparameters.
    """
    grid = {
        'depth': [5, 6, 7],
        'l2_leaf_reg': [1.5, 3.0, 5.0],
        'learning_rate': [0.03, 0.05],
    }

    combos = []
    for d in grid['depth']:
        for l2 in grid['l2_leaf_reg']:
            for lr in grid['learning_rate']:
                combos.append({'depth': d, 'l2_leaf_reg': l2, 'learning_rate': lr})

    print(f"\n{'=' * 70}")
    print(f" HYPERPARAMETER SEARCH ({len(combos)} combinations)")
    print(f"{'=' * 70}")
    print(f"{'#':>3s} {'Depth':>5s} {'L2':>5s} {'LR':>6s} {'MAE':>7s} {'HR 3+':>7s} {'N 3+':>5s}")
    print("-" * 50)

    results = []
    for i, params in enumerate(combos, 1):
        m = cb.CatBoostRegressor(
            iterations=1000,
            depth=params['depth'],
            l2_leaf_reg=params['l2_leaf_reg'],
            learning_rate=params['learning_rate'],
            random_seed=42,
            verbose=0,
            early_stopping_rounds=50,
        )
        m.fit(X_train, y_train, eval_set=(X_val, y_val), sample_weight=w_train, verbose=0)

        val_preds = m.predict(X_val)
        mae = mean_absolute_error(y_val, val_preds)
        hr_3, n_3 = compute_hit_rate(val_preds, y_val.values, lines_val, min_edge=3.0)

        hr_3_s = f"{hr_3:.1f}%" if hr_3 is not None else "N/A"
        print(f"  {i:2d}  {params['depth']:5d} {params['l2_leaf_reg']:5.1f} {params['learning_rate']:6.3f} {mae:7.4f} {hr_3_s:>7s} {n_3:5d}")

        results.append({
            'params': params,
            'mae': mae,
            'hr_edge3': hr_3 if hr_3 is not None else 0,
            'n_edge3': n_3,
        })

    # Sort by: edge 3+ HR descending, then MAE ascending
    results.sort(key=lambda r: (-r['hr_edge3'], r['mae']))
    best = results[0]

    print("-" * 50)
    print(f"  Best: depth={best['params']['depth']}, "
          f"l2={best['params']['l2_leaf_reg']}, "
          f"lr={best['params']['learning_rate']} "
          f"(HR 3+={best['hr_edge3']:.1f}%, MAE={best['mae']:.4f})")

    return best['params']


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
    if args.recency_weight:
        print(f"Recency Weight: {args.recency_weight}-day half-life")
    if args.tune:
        print(f"Hyperparameter Tuning: ON (18-combo grid search)")
    if args.walkforward:
        print(f"Walk-Forward Eval: ON (per-week breakdown)")
    print()

    # DATE OVERLAP GUARD (Session 176: 90%+ hit rates were caused by training on eval data)
    if train_end_dt >= eval_start_dt:
        print("=" * 70)
        print(" BLOCKED: TRAINING/EVAL DATE OVERLAP DETECTED")
        print("=" * 70)
        overlap_days = (train_end_dt - eval_start_dt).days + 1
        print(f"  Training ends:    {dates['train_end']}")
        print(f"  Evaluation starts: {dates['eval_start']}")
        print(f"  Overlap: {overlap_days} days")
        print()
        print("  This causes inflated hit rates (87%+ instead of real 62%).")
        print("  The model trains on the same games it evaluates on.")
        print()
        print(f"  Fix: Use --train-end {(eval_start_dt - timedelta(days=1)).strftime('%Y-%m-%d')} or earlier")
        return

    if args.dry_run:
        print("DRY RUN - would train on above dates")
        print(f"  Flags: recency_weight={args.recency_weight}, tune={args.tune}, walkforward={args.walkforward}")
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

    # Prepare features
    X_train_full, y_train_full = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    lines = df_eval['vegas_line'].values

    # Recency weighting (if --recency-weight)
    w_train_full = None
    if args.recency_weight:
        print(f"\nCalculating recency weights (half-life: {args.recency_weight} days)...")
        w_train_full = calculate_sample_weights(df_train['game_date'], args.recency_weight)
        print(f"  Weight stats: min={w_train_full.min():.4f}, max={w_train_full.max():.4f}, "
              f"mean={w_train_full.mean():.4f}, std={w_train_full.std():.4f}")

    # Train/val split (carry weights through)
    if w_train_full is not None:
        X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
            X_train_full, y_train_full, w_train_full, test_size=0.15, random_state=42)
    else:
        X_train, X_val, y_train, y_val = train_test_split(
            X_train_full, y_train_full, test_size=0.15, random_state=42)
        w_train = None

    # Hyperparameter search (if --tune)
    tuned_params = None
    if args.tune:
        # Use vegas_points_line feature as approximate lines for val-split hit rate
        lines_val = X_val['vegas_points_line'].values if 'vegas_points_line' in X_val.columns else None
        if lines_val is not None:
            tuned_params = run_hyperparam_search(X_train, y_train, X_val, y_val, lines_val, w_train)
        else:
            print("\nWARNING: vegas_points_line not in features, skipping --tune")

    # Build hyperparameters (tuned or default)
    if tuned_params:
        hp = {
            'iterations': 1000,
            'depth': tuned_params['depth'],
            'l2_leaf_reg': tuned_params['l2_leaf_reg'],
            'learning_rate': tuned_params['learning_rate'],
            'random_seed': 42,
            'verbose': 100,
            'early_stopping_rounds': 50,
        }
        print(f"\nTraining CatBoost with TUNED params (depth={hp['depth']}, l2={hp['l2_leaf_reg']}, lr={hp['learning_rate']})...")
    else:
        hp = {
            'iterations': 1000,
            'learning_rate': 0.05,
            'depth': 6,
            'l2_leaf_reg': 3,
            'random_seed': 42,
            'verbose': 100,
            'early_stopping_rounds': 50,
        }
        print("\nTraining CatBoost with default params...")

    model = cb.CatBoostRegressor(**hp)
    model.fit(X_train, y_train, eval_set=(X_val, y_val), sample_weight=w_train, verbose=100)

    # Feature importance (always on)
    feature_importance = display_feature_importance(model, FEATURES)

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

    # Directional hit rates (Session 175 — Session 173 discovered OVER collapsed to 44.1%)
    directional = compute_directional_hit_rates(preds, y_eval.values, lines, min_edge=3.0)

    # Walk-forward per-week breakdown (if --walkforward)
    walkforward_results = None
    if args.walkforward:
        walkforward_results = run_walkforward_eval(model, df_eval, X_eval, y_eval, lines)

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

    # Directional Balance Analysis (Session 175 — catches OVER/UNDER collapse)
    BREAKEVEN = 52.4
    print("\n" + "-" * 40)
    print("DIRECTIONAL BALANCE (OVER/UNDER edge 3+)")
    print("-" * 40)
    over_status = "PASS" if directional['over_hit_rate'] is None or directional['over_hit_rate'] >= BREAKEVEN else "FAIL"
    under_status = "PASS" if directional['under_hit_rate'] is None or directional['under_hit_rate'] >= BREAKEVEN else "FAIL"
    over_str = f"{directional['over_hit_rate']:.1f}%" if directional['over_hit_rate'] is not None else "N/A"
    under_str = f"{directional['under_hit_rate']:.1f}%" if directional['under_hit_rate'] is not None else "N/A"
    print(f"  OVER:  {over_str} ({directional['over_graded']} graded) [{over_status}]")
    print(f"  UNDER: {under_str} ({directional['under_graded']} graded) [{under_status}]")
    if not directional['directional_balance_ok']:
        print(f"  BLOCKED: {directional['worst_direction']} at {directional['worst_rate']:.1f}% (below breakeven {BREAKEVEN}%)")

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
    gates.append(("Directional balance (OVER+UNDER >= 52.4%)",
                  directional['directional_balance_ok'],
                  f"OVER={over_str}, UNDER={under_str}"))

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
                'config_json': json.dumps({
                    'train_days': train_days_actual, 'eval_days': eval_days_actual,
                    'features': 33, 'line_source': 'production' if args.use_production_lines else args.line_source,
                    'recency_weight': args.recency_weight,
                    'tuned': args.tune, 'tuned_params': tuned_params,
                    'hyperparameters': {k: v for k, v in hp.items() if k != 'verbose'},
                }),
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
                    'directional_balance': {
                        'over_hit_rate': directional['over_hit_rate'],
                        'under_hit_rate': directional['under_hit_rate'],
                        'over_graded': directional['over_graded'],
                        'under_graded': directional['under_graded'],
                        'balance_ok': bool(directional['directional_balance_ok']),
                    },
                    'all_gates_passed': all_passed,
                    'model_sha256': model_sha256,
                    'feature_importance': {name: round(float(imp), 2) for name, imp in feature_importance[:10]},
                    'walkforward': walkforward_results,
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
