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
    V10_CONTRACT,
    V10_FEATURE_NAMES,
    V11_CONTRACT,
    V11_FEATURE_NAMES,
    V12_CONTRACT,
    V12_FEATURE_NAMES,
    FEATURE_DEFAULTS,
    FEATURE_STORE_NAMES,
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

# Vegas features (indices 25-28) — used by --no-vegas and --two-stage modes
VEGAS_FEATURE_NAMES = ['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line']

# Feature categories for --category-weight (Session 179)
# Maps category name → list of feature names in that category
FEATURE_CATEGORIES = {
    'recent_performance': ['points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
                           'points_std_last_10', 'games_in_last_7_days'],
    'composite': ['fatigue_score', 'shot_zone_mismatch_score', 'pace_score', 'usage_spike_score'],
    'derived': ['rest_advantage', 'injury_risk', 'recent_trend', 'minutes_change'],
    'matchup': ['opponent_def_rating', 'opponent_pace', 'home_away', 'back_to_back', 'playoff_game'],
    'shot_zone': ['pct_paint', 'pct_mid_range', 'pct_three', 'pct_free_throw'],
    'team_context': ['team_pace', 'team_off_rating', 'team_win_pct'],
    'vegas': ['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line'],
    'opponent_history': ['avg_points_vs_opponent', 'games_vs_opponent'],
    'minutes_efficiency': ['minutes_avg_last_10', 'ppm_avg_last_10'],
}


def parse_feature_weights(feature_weights_str, category_weights_str, active_features):
    """
    Parse --feature-weights and --category-weight into CatBoost feature_weights dict.

    Args:
        feature_weights_str: Comma-separated 'name=weight' pairs (e.g., 'vegas_points_line=0.3,fatigue_score=0.5')
        category_weights_str: Comma-separated 'category=weight' pairs (e.g., 'vegas=0.3,composite=0.5')
        active_features: List of feature names in the model (order matters for CatBoost)

    Returns:
        Dict mapping feature index (in active_features) to weight, or None if no weights specified.
        CatBoost expects: {feature_index: weight} where unspecified features default to 1.0.
    """
    if not feature_weights_str and not category_weights_str:
        return None

    weights = {}  # feature_name -> weight

    # Apply category weights first (individual feature weights override)
    if category_weights_str:
        for pair in category_weights_str.split(','):
            pair = pair.strip()
            if '=' not in pair:
                print(f"  WARNING: Skipping invalid category weight '{pair}' (expected 'category=weight')")
                continue
            cat_name, weight_str = pair.split('=', 1)
            cat_name = cat_name.strip()
            if cat_name not in FEATURE_CATEGORIES:
                print(f"  WARNING: Unknown category '{cat_name}'. Available: {list(FEATURE_CATEGORIES.keys())}")
                continue
            weight = float(weight_str.strip())
            for feat_name in FEATURE_CATEGORIES[cat_name]:
                weights[feat_name] = weight

    # Apply individual feature weights (override categories)
    if feature_weights_str:
        for pair in feature_weights_str.split(','):
            pair = pair.strip()
            if '=' not in pair:
                print(f"  WARNING: Skipping invalid feature weight '{pair}' (expected 'name=weight')")
                continue
            feat_name, weight_str = pair.split('=', 1)
            feat_name = feat_name.strip()
            weight = float(weight_str.strip())
            weights[feat_name] = weight

    if not weights:
        return None

    # Convert to CatBoost format: {index: weight} for features in active_features
    cb_weights = {}
    for feat_name, weight in weights.items():
        if feat_name in active_features:
            idx = active_features.index(feat_name)
            cb_weights[idx] = weight
        else:
            print(f"  WARNING: Feature '{feat_name}' not in active features (may be excluded), skipping weight")

    return cb_weights if cb_weights else None


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

    # Feature set selection
    parser.add_argument('--feature-set', choices=['v9', 'v10', 'v11', 'v12'], default='v9',
                       help='Feature set to use (v9=33, v10=37, v11=39, v12=54 features)')

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

    # Alternative experiment modes (Session 179: decouple from Vegas dependency)
    parser.add_argument('--no-vegas', action='store_true',
                       help='Drop vegas features (25-28) from training')
    parser.add_argument('--residual', action='store_true',
                       help='Train on residuals (actual - vegas_line) instead of absolute points')
    parser.add_argument('--two-stage', action='store_true',
                       help='Train without vegas features, compute edge as pred - vegas_line at eval time')
    parser.add_argument('--quantile-alpha', type=float, default=None, metavar='ALPHA',
                       help='Use quantile regression with alpha (e.g., 0.55 = predict above median)')
    parser.add_argument('--exclude-features', default=None,
                       help='Comma-separated feature names to exclude from training')
    parser.add_argument('--feature-weights', default=None,
                       help='Per-feature weights as name=weight pairs (e.g., "vegas_points_line=0.3,fatigue_score=0.5")')
    parser.add_argument('--category-weight', default=None,
                       help='Per-category weights (e.g., "vegas=0.3,composite=0.5"). '
                            'Categories: recent_performance, composite, derived, matchup, '
                            'shot_zone, team_context, vegas, opponent_history, minutes_efficiency')

    # Advanced CatBoost training params (Session 179)
    parser.add_argument('--rsm', type=float, default=None,
                       help='Feature subsampling per split (0.0-1.0). 0.5 = 50%% features per level. '
                            'Reduces dominant feature influence. Best with --grow-policy Depthwise.')
    parser.add_argument('--grow-policy', choices=['SymmetricTree', 'Depthwise', 'Lossguide'],
                       default=None, help='Tree growth strategy. Depthwise unlocks rsm/min-data-in-leaf fully.')
    parser.add_argument('--min-data-in-leaf', type=int, default=None,
                       help='Min samples per leaf (requires --grow-policy Depthwise/Lossguide)')
    parser.add_argument('--bootstrap', choices=['Bayesian', 'Bernoulli', 'MVS', 'No'],
                       default=None, help='Bootstrap type. MVS = importance sampling on hard examples.')
    parser.add_argument('--subsample', type=float, default=None,
                       help='Row subsampling fraction (0.0-1.0). Requires --bootstrap Bernoulli/MVS.')
    parser.add_argument('--random-strength', type=float, default=None,
                       help='Split score noise multiplier (default 1). Higher = more split diversity.')
    parser.add_argument('--loss-function', default=None,
                       help='CatBoost loss function (e.g., "Huber:delta=5", "LogCosh", "RMSE", "MAE")')
    parser.add_argument('--monotone-constraints', type=str, default=None,
                       help='Comma-separated -1/0/1 per feature for CatBoost monotone_constraints. '
                            'Example for V9 (33): "0,1,0,...,1,0". '
                            'V11 (39): append ",1,1" for star_teammates_out(+1), game_total_line(+1)')

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

    if args.train_start and args.train_end:
        # Auto-calculate eval dates from train-end
        train_end_dt = datetime.strptime(args.train_end, '%Y-%m-%d').date()
        eval_start = train_end_dt + timedelta(days=1)
        eval_end = eval_start + timedelta(days=args.eval_days - 1)
        print(f"  [dates] Train dates explicit, auto-calculating eval: {eval_start} to {eval_end} ({args.eval_days} days)")
        return {
            'train_start': args.train_start,
            'train_end': args.train_end,
            'eval_start': eval_start.strftime('%Y-%m-%d'),
            'eval_end': eval_end.strftime('%Y-%m-%d'),
        }

    # Full auto-calculation fallback
    if args.train_start or args.train_end or args.eval_start or args.eval_end:
        print(f"  [WARNING] Partial explicit dates ignored — provide both train-start and train-end, or all four dates.")

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
    SELECT mf.player_lookup, mf.features, mf.feature_names,
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
    SELECT mf.player_lookup, mf.features, mf.feature_names, pgs.points as actual_points, l.line as vegas_line,
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


def augment_v11_features(client, df):
    """
    Augment training/eval DataFrame with V11 features from Phase 3.

    For historical data where the feature store arrays don't contain
    star_teammates_out or game_total_line, this function LEFT JOINs
    upstream_player_game_context to inject these columns.

    The augmented columns are injected into each row's features/feature_names
    arrays so prepare_features() can extract them by name.

    Args:
        client: BigQuery client
        df: DataFrame with player_lookup, game_date, features, feature_names columns

    Returns:
        DataFrame with V11 features injected into features/feature_names arrays
    """
    if df.empty:
        return df

    if 'player_lookup' not in df.columns:
        print("  WARNING: No player_lookup column — skipping V11 augmentation")
        return df

    # Get date range for efficient query
    min_date = df['game_date'].min()
    max_date = df['game_date'].max()

    query = f"""
    SELECT
        player_lookup,
        game_date,
        COALESCE(star_teammates_out, 0) as star_teammates_out,
        game_total as game_total_line
    FROM `{PROJECT_ID}.nba_analytics.upcoming_player_game_context`
    WHERE game_date BETWEEN '{min_date}' AND '{max_date}'
    """
    v11_data = client.query(query).to_dataframe()

    if v11_data.empty:
        print(f"  WARNING: No V11 data found for {min_date} to {max_date}")
        return df

    # Build lookup: (player_lookup, game_date) -> {star_teammates_out, game_total_line}
    v11_lookup = {}
    for _, row in v11_data.iterrows():
        key = (row['player_lookup'], str(row['game_date']))
        v11_lookup[key] = {
            'star_teammates_out': row['star_teammates_out'],
            'game_total_line': row['game_total_line'],
        }

    # Inject V11 features into each row's features/feature_names arrays
    augmented_count = 0
    for idx in range(len(df)):
        row = df.iloc[idx]
        features = list(row['features'])
        feature_names = list(row['feature_names'])
        game_date_str = str(row['game_date'])
        key = (row['player_lookup'], game_date_str)

        v11 = v11_lookup.get(key, {})

        # Only inject if not already present
        if 'star_teammates_out' not in feature_names:
            star_out = v11.get('star_teammates_out', 0.0)
            game_total = v11.get('game_total_line')

            features.append(float(star_out) if star_out is not None else 0.0)
            feature_names.append('star_teammates_out')
            features.append(float(game_total) if game_total is not None else np.nan)
            feature_names.append('game_total_line')

            df.at[df.index[idx], 'features'] = features
            df.at[df.index[idx], 'feature_names'] = feature_names

            if v11:
                augmented_count += 1

    print(f"  V11 augmentation: {augmented_count}/{len(df)} rows matched ({100*augmented_count/len(df):.0f}%)")
    return df


def augment_v12_features(client, df):
    """
    Augment training/eval DataFrame with V12 features (15 new features, indices 39-53).

    Queries three upstream sources:
    1. UPCG: days_rest, minutes_load, spread, total, prop streaks
    2. player_game_summary: scoring trends, usage, structural changes
    3. odds_api: multi-book line std

    Then computes derived features (implied_team_total, line_vs_season_avg)
    and injects all 15 features into each row's features/feature_names arrays.

    Args:
        client: BigQuery client
        df: DataFrame with player_lookup, game_date, features, feature_names columns
            (must already have V11 features augmented)

    Returns:
        DataFrame with V12 features injected into features/feature_names arrays
    """
    if df.empty:
        return df

    if 'player_lookup' not in df.columns:
        print("  WARNING: No player_lookup column — skipping V12 augmentation")
        return df

    min_date = df['game_date'].min()
    max_date = df['game_date'].max()

    # --- Sub-query 1: UPCG data (Tier 1 features) ---
    upcg_query = f"""
    SELECT
        player_lookup,
        game_date,
        COALESCE(days_rest, 1) as days_rest,
        COALESCE(minutes_in_last_7_days, 80.0) as minutes_load_last_7d,
        COALESCE(game_spread, 0.0) as game_spread,
        COALESCE(game_total, 224.0) as game_total,
        COALESCE(home_game, FALSE) as home_game,
        COALESCE(prop_over_streak, 0) as prop_over_streak,
        COALESCE(prop_under_streak, 0) as prop_under_streak
    FROM `{PROJECT_ID}.nba_analytics.upcoming_player_game_context`
    WHERE game_date BETWEEN '{min_date}' AND '{max_date}'
    """
    print("  V12: Querying UPCG data...")
    upcg_data = client.query(upcg_query).to_dataframe()

    # Build UPCG lookup
    upcg_lookup = {}
    for _, row in upcg_data.iterrows():
        key = (row['player_lookup'], str(row['game_date']))
        spread = float(row['game_spread'])
        total = float(row['game_total'])
        is_home = bool(row['home_game'])
        # implied_team_total: home = (total - spread) / 2, away = (total + spread) / 2
        # game_spread is HOME perspective (negative = home favored)
        if is_home:
            implied_tt = (total - spread) / 2.0
        else:
            implied_tt = (total + spread) / 2.0

        upcg_lookup[key] = {
            'days_rest': float(row['days_rest']),
            'minutes_load_last_7d': float(row['minutes_load_last_7d']),
            'spread_magnitude': abs(spread),
            'implied_team_total': implied_tt,
            'prop_over_streak': float(row['prop_over_streak']),
            'prop_under_streak': float(row['prop_under_streak']),
        }
    print(f"  V12: UPCG lookup built ({len(upcg_lookup)} rows)")

    # --- Sub-query 2: Player stats (Tier 2 features) ---
    # We need a wider date window to compute rolling stats
    lookback_date = (pd.to_datetime(str(min_date)) - pd.Timedelta(days=60)).strftime('%Y-%m-%d')

    stats_query = f"""
    WITH player_games AS (
        SELECT
            player_lookup,
            game_date,
            points,
            usage_rate,
            team_abbr,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn_all,
            LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_game_date,
            LAG(team_abbr) OVER (PARTITION BY player_lookup ORDER BY game_date) as prev_team_abbr
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '{lookback_date}' AND '{max_date}'
          AND points IS NOT NULL
          AND minutes_played > 0
    ),
    season_stats AS (
        SELECT
            player_lookup,
            AVG(points) as season_avg,
            STDDEV(points) as season_std
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '2025-10-22' AND '{max_date}'
          AND points IS NOT NULL
          AND minutes_played > 0
        GROUP BY player_lookup
    ),
    rolling AS (
        SELECT
            pg.player_lookup,
            pg.game_date,
            pg.points,
            pg.usage_rate,
            pg.team_abbr,
            pg.prev_game_date,
            pg.prev_team_abbr,
            ss.season_avg,
            ss.season_std,
            -- Last 3 average
            AVG(pg2.points) as avg_last_3,
            COUNT(pg2.points) as cnt_last_3
        FROM player_games pg
        JOIN season_stats ss ON pg.player_lookup = ss.player_lookup
        LEFT JOIN (
            SELECT player_lookup, game_date, points,
                   ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
            FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
            WHERE game_date BETWEEN '{lookback_date}' AND '{max_date}'
              AND points IS NOT NULL AND minutes_played > 0
        ) pg2 ON pg.player_lookup = pg2.player_lookup
             AND pg2.game_date < pg.game_date
             AND pg2.rn <= pg.rn_all + 3
        WHERE pg.game_date BETWEEN '{min_date}' AND '{max_date}'
        GROUP BY pg.player_lookup, pg.game_date, pg.points, pg.usage_rate,
                 pg.team_abbr, pg.prev_game_date, pg.prev_team_abbr,
                 ss.season_avg, ss.season_std
    )
    SELECT * FROM rolling
    """
    # The rolling join above is complex; let's use a simpler approach with arrays
    stats_query_v2 = f"""
    WITH target_players AS (
        SELECT DISTINCT player_lookup
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
        WHERE game_date BETWEEN '{min_date}' AND '{max_date}'
    ),
    all_games AS (
        SELECT
            pgs.player_lookup,
            pgs.game_date,
            pgs.points,
            pgs.usage_rate,
            pgs.team_abbr
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
        JOIN target_players tp ON pgs.player_lookup = tp.player_lookup
        WHERE pgs.game_date BETWEEN '{lookback_date}' AND '{max_date}'
          AND pgs.points IS NOT NULL
          AND pgs.minutes_played > 0
        ORDER BY pgs.player_lookup, pgs.game_date
    ),
    season_stats AS (
        SELECT
            player_lookup,
            AVG(points) as season_avg,
            STDDEV(points) as season_std
        FROM all_games
        GROUP BY player_lookup
    ),
    per_game_with_context AS (
        SELECT
            ag.player_lookup,
            ag.game_date,
            ag.points,
            ag.usage_rate,
            ag.team_abbr,
            ss.season_avg,
            ss.season_std,
            LAG(ag.game_date) OVER (PARTITION BY ag.player_lookup ORDER BY ag.game_date) as prev_game_date,
            LAG(ag.team_abbr) OVER (PARTITION BY ag.player_lookup ORDER BY ag.game_date) as prev_team_abbr,
            -- Arrays for rolling computations (last 10 games before this one)
            ARRAY_AGG(COALESCE(ag.points, 0.0)) OVER (
                PARTITION BY ag.player_lookup ORDER BY ag.game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as prev_points,
            ARRAY_AGG(COALESCE(ag.usage_rate, 0.0)) OVER (
                PARTITION BY ag.player_lookup ORDER BY ag.game_date
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as prev_usage_rates
        FROM all_games ag
        JOIN season_stats ss ON ag.player_lookup = ss.player_lookup
    )
    SELECT *
    FROM per_game_with_context
    WHERE game_date BETWEEN '{min_date}' AND '{max_date}'
    """

    print("  V12: Querying player stats...")
    stats_data = client.query(stats_query_v2).to_dataframe()

    # Build stats lookup
    stats_lookup = {}
    for _, row in stats_data.iterrows():
        key = (row['player_lookup'], str(row['game_date']))
        prev_points = list(row['prev_points']) if row['prev_points'] is not None else []
        prev_usage = list(row['prev_usage_rates']) if row['prev_usage_rates'] is not None else []
        season_avg = float(row['season_avg']) if row['season_avg'] is not None else 10.0
        season_std = float(row['season_std']) if row['season_std'] is not None and row['season_std'] > 0 else 5.0

        # points_avg_last_3: need at least 2 prev games
        if len(prev_points) >= 2:
            last_3 = prev_points[-3:] if len(prev_points) >= 3 else prev_points
            points_avg_last_3 = float(np.mean(last_3))
        else:
            points_avg_last_3 = season_avg

        # scoring_trend_slope: OLS on last 7, need at least 4
        recent_7 = prev_points[-7:] if len(prev_points) >= 4 else None
        if recent_7 is not None and len(recent_7) >= 4:
            n = len(recent_7)
            # x = 1 (oldest) to n (most recent)
            x = np.arange(1, n + 1, dtype=float)
            y = np.array(recent_7, dtype=float)
            # OLS slope: (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x^2) - (sum(x))^2)
            sum_x = x.sum()
            sum_y = y.sum()
            sum_xy = (x * y).sum()
            sum_x2 = (x * x).sum()
            denom = n * sum_x2 - sum_x * sum_x
            scoring_trend_slope = float((n * sum_xy - sum_x * sum_y) / denom) if denom != 0 else 0.0
        else:
            scoring_trend_slope = 0.0

        # deviation_from_avg_last3: z-score
        deviation_from_avg_last3 = (points_avg_last_3 - season_avg) / season_std

        # consecutive_games_below_avg: count from most recent going back
        consecutive_below = 0
        for pts in reversed(prev_points):
            if pts < season_avg:
                consecutive_below += 1
            else:
                break

        # usage_rate_last_5: need at least 3
        valid_usage = [u for u in prev_usage if u is not None]
        if len(valid_usage) >= 3:
            usage_rate_last_5 = float(np.mean(valid_usage[-5:]))
        else:
            usage_rate_last_5 = 20.0

        # games_since_structural_change: detect team change or >14-day gap
        games_since_change = 30.0  # default
        prev_date = row['prev_game_date']
        prev_team = row['prev_team_abbr']
        current_team = row['team_abbr']

        if prev_date is not None and prev_team is not None:
            days_gap = (pd.to_datetime(str(row['game_date'])) - pd.to_datetime(str(prev_date))).days
            if current_team != prev_team:
                games_since_change = 0.0
            elif days_gap > 14:
                games_since_change = 0.0
            else:
                # Simple approximation: count games since start of season
                # A proper implementation would track across all prior games
                games_since_change = min(len(prev_points), 30.0)

        # Check for ASB 2026 (Feb 14-19)
        game_dt = pd.to_datetime(str(row['game_date']))
        asb_end = pd.Timestamp('2026-02-19')
        asb_start = pd.Timestamp('2026-02-14')
        if game_dt > asb_end:
            days_since_asb = (game_dt - asb_end).days
            if days_since_asb < games_since_change:
                games_since_change = float(days_since_asb)

        stats_lookup[key] = {
            'points_avg_last_3': points_avg_last_3,
            'scoring_trend_slope': scoring_trend_slope,
            'deviation_from_avg_last3': float(deviation_from_avg_last3),
            'consecutive_games_below_avg': float(consecutive_below),
            'usage_rate_last_5': usage_rate_last_5,
            'games_since_structural_change': float(games_since_change),
        }
    print(f"  V12: Stats lookup built ({len(stats_lookup)} rows)")

    # --- Sub-query 3: Multi-book line std ---
    odds_query = f"""
    SELECT
        player_lookup,
        game_date,
        STDDEV(points_line) as line_std,
        COUNT(DISTINCT bookmaker) as n_books
    FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
    WHERE game_date BETWEEN '{min_date}' AND '{max_date}'
      AND points_line IS NOT NULL
    GROUP BY player_lookup, game_date
    HAVING COUNT(DISTINCT bookmaker) >= 3
    """
    print("  V12: Querying multi-book line std...")
    odds_data = client.query(odds_query).to_dataframe()

    odds_lookup = {}
    for _, row in odds_data.iterrows():
        key = (row['player_lookup'], str(row['game_date']))
        odds_lookup[key] = float(row['line_std']) if row['line_std'] is not None else np.nan
    print(f"  V12: Odds lookup built ({len(odds_lookup)} rows)")

    # --- Inject V12 features into each row ---
    augmented_counts = {
        'upcg': 0, 'stats': 0, 'odds': 0
    }
    for idx in range(len(df)):
        row = df.iloc[idx]
        features = list(row['features'])
        feature_names = list(row['feature_names'])
        game_date_str = str(row['game_date'])
        key = (row['player_lookup'], game_date_str)

        # Skip if V12 features already present
        if 'days_rest' in feature_names:
            continue

        upcg = upcg_lookup.get(key, {})
        stats = stats_lookup.get(key, {})
        odds_std = odds_lookup.get(key, np.nan)

        if upcg:
            augmented_counts['upcg'] += 1
        if stats:
            augmented_counts['stats'] += 1
        if key in odds_lookup:
            augmented_counts['odds'] += 1

        # Compute line_vs_season_avg from existing features in the row
        features_dict = dict(zip(feature_names, features))
        vegas_line = features_dict.get('vegas_points_line')
        season_avg = features_dict.get('points_avg_season', 10.0)
        if vegas_line is not None and vegas_line > 0:
            line_vs_season_avg = float(vegas_line) - float(season_avg)
        else:
            line_vs_season_avg = 0.0

        # Append all 15 V12 features in order (indices 39-53)
        v12_features = [
            ('days_rest', upcg.get('days_rest', 1.0)),
            ('minutes_load_last_7d', upcg.get('minutes_load_last_7d', 80.0)),
            ('spread_magnitude', upcg.get('spread_magnitude', 5.0)),
            ('implied_team_total', upcg.get('implied_team_total', 112.0)),
            ('points_avg_last_3', stats.get('points_avg_last_3', 10.0)),
            ('scoring_trend_slope', stats.get('scoring_trend_slope', 0.0)),
            ('deviation_from_avg_last3', stats.get('deviation_from_avg_last3', 0.0)),
            ('consecutive_games_below_avg', stats.get('consecutive_games_below_avg', 0.0)),
            ('teammate_usage_available', 0.0),  # Default for now (complex query)
            ('usage_rate_last_5', stats.get('usage_rate_last_5', 20.0)),
            ('games_since_structural_change', stats.get('games_since_structural_change', 30.0)),
            ('multi_book_line_std', odds_std),
            ('prop_over_streak', upcg.get('prop_over_streak', 0.0)),
            ('prop_under_streak', upcg.get('prop_under_streak', 0.0)),
            ('line_vs_season_avg', line_vs_season_avg),
        ]

        for fname, fval in v12_features:
            feature_names.append(fname)
            features.append(float(fval) if fval is not None and not (isinstance(fval, float) and np.isnan(fval)) else np.nan)

        df.at[df.index[idx], 'features'] = features
        df.at[df.index[idx], 'feature_names'] = feature_names

    total = len(df)
    print(f"  V12 augmentation coverage:")
    print(f"    UPCG (Tier 1):  {augmented_counts['upcg']}/{total} ({100*augmented_counts['upcg']/total:.0f}%)")
    print(f"    Stats (Tier 2): {augmented_counts['stats']}/{total} ({100*augmented_counts['stats']/total:.0f}%)")
    print(f"    Odds (Tier 3):  {augmented_counts['odds']}/{total} ({100*augmented_counts['odds']/total:.0f}%)")
    return df


def prepare_features(df, contract=V9_CONTRACT, exclude_features=None):
    """
    Prepare feature matrix using NAME-BASED extraction (not position-based).

    Session 107: Changed from position slicing (row[:33]) to name-based extraction.
    This is SAFE even if feature store column order changes.

    Session 179: Added exclude_features to support --no-vegas, --two-stage,
    and --exclude-features experiment modes.

    Session 238: Prefers individual feature_N_value columns (NULL-aware).
    NULL → np.nan → CatBoost handles natively (no more fake defaults).
    Falls back to array-based extraction for older data without individual columns.

    Args:
        df: DataFrame with 'features' and 'feature_names' columns
        contract: ModelFeatureContract defining expected features (default V9)
        exclude_features: Optional list of feature names to exclude from the matrix

    Returns:
        X: Feature DataFrame with columns in contract order (minus excluded)
        y: Target Series (actual_points)
    """
    exclude_set = set(exclude_features or [])
    active_features = [f for f in contract.feature_names if f not in exclude_set]

    # Session 238: Build name→column_index mapping for individual columns
    store_name_to_idx = {name: i for i, name in enumerate(FEATURE_STORE_NAMES)}
    use_individual_columns = 'feature_0_value' in df.columns

    rows = []
    for _, row in df.iterrows():
        row_data = {}

        if use_individual_columns:
            # New path: prefer individual columns (NULL-aware).
            # NULL means no real data → np.nan (CatBoost handles natively).
            # Fallback to array for features where individual column is NULL
            # but array has a value (handles backfill gap for pre-source-tracking rows).
            arr_dict = {}
            feature_values = row.get('features')
            feature_names_arr = row.get('feature_names')
            if feature_values is not None and feature_names_arr is not None:
                min_len = min(len(feature_values), len(feature_names_arr))
                arr_dict = dict(zip(feature_names_arr[:min_len], feature_values[:min_len]))

            for name in active_features:
                idx = store_name_to_idx.get(name)
                if idx is not None:
                    val = row.get(f'feature_{idx}_value')
                    if val is not None and not pd.isna(val):
                        row_data[name] = float(val)
                    elif name in arr_dict and arr_dict[name] is not None:
                        # Backfill gap: column NULL but array has value.
                        # Zero-tolerance ensures required features are real.
                        row_data[name] = float(arr_dict[name])
                    else:
                        row_data[name] = np.nan
                else:
                    row_data[name] = np.nan
        else:
            # Legacy path: read from arrays (backward compat for older data)
            feature_values = row['features']
            feature_names = row['feature_names']

            if len(feature_values) != len(feature_names):
                min_len = min(len(feature_values), len(feature_names))
                feature_values = feature_values[:min_len]
                feature_names = feature_names[:min_len]

            features_dict = dict(zip(feature_names, feature_values))

            for name in active_features:
                if name in features_dict and features_dict[name] is not None:
                    row_data[name] = float(features_dict[name])
                elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
                    row_data[name] = float(FEATURE_DEFAULTS[name])
                else:
                    row_data[name] = np.nan

        rows.append(row_data)

    X = pd.DataFrame(rows, columns=active_features)

    if use_individual_columns:
        # CatBoost handles NaN natively — no imputation needed for new data.
        # For rows with array fallback, values are real (zero-tolerance enforced).
        nan_pct = X.isna().mean().mean() * 100
        if nan_pct > 0:
            print(f"  Feature matrix: {X.shape[0]} rows x {X.shape[1]} cols, {nan_pct:.1f}% NaN (CatBoost native)")
    else:
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


def compute_segmented_hit_rates(preds, actuals, lines, season_avgs=None, min_edge=3.0):
    """
    Compute hit rates across multiple dimensions for experiment analysis.

    Session 180: Discovered C4_MATCHUP_ONLY has 70.6% UNDER HR and C1_CHAOS has
    71.4% UNDER HR — invisible in overall edge 3+ HR. This function breaks down
    HR by tier, direction, tier x direction, edge bucket, and line range.

    Args:
        preds: Model predictions (numpy array)
        actuals: Actual points scored (numpy array)
        lines: Vegas lines (numpy array)
        season_avgs: Pre-game season averages for tier classification (optional)
        min_edge: Minimum edge threshold (default 3.0)

    Returns:
        dict with by_tier, by_direction, by_tier_direction, by_edge_bucket, by_line_range.
        Each cell: {hr, n, wins} (hr=None if n=0)
    """
    edges = preds - lines
    mask = np.abs(edges) >= min_edge

    tier_values = season_avgs if season_avgs is not None else actuals

    tier_defs = {
        'Stars (25+)': tier_values >= 25,
        'Starters (15-24)': (tier_values >= 15) & (tier_values < 25),
        'Role (5-14)': (tier_values >= 5) & (tier_values < 15),
        'Bench (<5)': tier_values < 5,
    }

    direction_defs = {
        'OVER': edges > 0,
        'UNDER': edges < 0,
    }

    edge_bucket_defs = {
        '[3-5)': (np.abs(edges) >= 3) & (np.abs(edges) < 5),
        '[5-7)': (np.abs(edges) >= 5) & (np.abs(edges) < 7),
        '[7+)': np.abs(edges) >= 7,
    }

    line_range_defs = {
        'Low (<12.5)': lines < 12.5,
        'Mid (12.5-20.5)': (lines >= 12.5) & (lines <= 20.5),
        'High (>20.5)': lines > 20.5,
    }

    def _hr_for_mask(seg_mask):
        """Compute HR for a combined mask (must already include min_edge filter)."""
        combined = mask & seg_mask
        n = int(combined.sum())
        if n == 0:
            return {'hr': None, 'n': 0, 'wins': 0}
        seg_actual = actuals[combined]
        seg_lines = lines[combined]
        seg_over = edges[combined] > 0
        wins = int(((seg_actual > seg_lines) & seg_over).sum()
                    + ((seg_actual < seg_lines) & ~seg_over).sum())
        pushes = int((seg_actual == seg_lines).sum())
        graded = n - pushes
        if graded == 0:
            return {'hr': None, 'n': n, 'wins': 0}
        return {'hr': round(wins / graded * 100, 1), 'n': graded, 'wins': wins}

    # By tier
    by_tier = {name: _hr_for_mask(tmask) for name, tmask in tier_defs.items()}

    # By direction
    by_direction = {name: _hr_for_mask(dmask) for name, dmask in direction_defs.items()}

    # By tier x direction (8 cells)
    by_tier_direction = {}
    for tname, tmask in tier_defs.items():
        for dname, dmask in direction_defs.items():
            by_tier_direction[f"{tname} {dname}"] = _hr_for_mask(tmask & dmask)

    # By edge bucket
    by_edge_bucket = {name: _hr_for_mask(emask) for name, emask in edge_bucket_defs.items()}

    # By line range
    by_line_range = {name: _hr_for_mask(lmask) for name, lmask in line_range_defs.items()}

    return {
        'by_tier': by_tier,
        'by_direction': by_direction,
        'by_tier_direction': by_tier_direction,
        'by_edge_bucket': by_edge_bucket,
        'by_line_range': by_line_range,
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

    # Select feature contract based on --feature-set
    if args.feature_set == 'v12':
        selected_contract = V12_CONTRACT
        selected_feature_names = V12_FEATURE_NAMES
    elif args.feature_set == 'v11':
        selected_contract = V11_CONTRACT
        selected_feature_names = V11_FEATURE_NAMES
    elif args.feature_set == 'v10':
        selected_contract = V10_CONTRACT
        selected_feature_names = V10_FEATURE_NAMES
    else:
        selected_contract = V9_CONTRACT
        selected_feature_names = V9_FEATURE_NAMES

    # Validate feature contract BEFORE doing anything (Session 107)
    print("Validating feature contracts...")
    try:
        validate_all_contracts()
        print(f"  Using {selected_contract.model_version} contract: {selected_contract.feature_count} features")
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
    print(f"Feature Set: {args.feature_set} ({selected_contract.feature_count} features)")
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
    # Alternative experiment modes (Session 179)
    if args.no_vegas:
        print(f"Mode: NO-VEGAS (dropping features 25-28)")
    if args.residual:
        print(f"Mode: RESIDUAL (training on actual - vegas_line)")
    if args.two_stage:
        print(f"Mode: TWO-STAGE (train without vegas, edge = pred - vegas at eval)")
    if args.quantile_alpha:
        print(f"Mode: QUANTILE (alpha={args.quantile_alpha})")
    if args.exclude_features:
        print(f"Excluding features: {args.exclude_features}")
    if args.feature_weights:
        print(f"Feature Weights: {args.feature_weights}")
    if args.category_weight:
        print(f"Category Weights: {args.category_weight}")
    if args.monotone_constraints:
        print(f"Monotone Constraints: {args.monotone_constraints}")
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
        print(f"  Feature set: {args.feature_set} ({selected_contract.feature_count} features)")
        print(f"  Flags: recency_weight={args.recency_weight}, tune={args.tune}, walkforward={args.walkforward}")
        print(f"  Modes: no_vegas={args.no_vegas}, residual={args.residual}, "
              f"two_stage={args.two_stage}, quantile_alpha={args.quantile_alpha}")
        if args.exclude_features:
            print(f"  Exclude: {args.exclude_features}")
        if args.feature_weights:
            print(f"  Feature weights: {args.feature_weights}")
        if args.category_weight:
            print(f"  Category weights: {args.category_weight}")
        if args.monotone_constraints:
            print(f"  Monotone constraints: {args.monotone_constraints}")
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

    # V11: Augment feature arrays with star_teammates_out + game_total_line
    # Historical data doesn't have these in the feature store arrays,
    # so we JOIN from upstream_player_game_context at training time
    if args.feature_set == 'v11':
        print("\nAugmenting with V11 features (star_teammates_out, game_total_line)...")
        df_train = augment_v11_features(client, df_train)
        df_eval = augment_v11_features(client, df_eval)

    # V12: First augment with V11 (V12 extends V11), then add 15 new V12 features
    if args.feature_set == 'v12':
        print("\nAugmenting with V11 features (star_teammates_out, game_total_line)...")
        df_train = augment_v11_features(client, df_train)
        df_eval = augment_v11_features(client, df_eval)
        print("\nAugmenting with V12 features (15 new features)...")
        df_train = augment_v12_features(client, df_train)
        df_eval = augment_v12_features(client, df_eval)

    if len(df_train) < 1000 or len(df_eval) < 100:
        print("ERROR: Not enough data")
        return

    # Determine feature exclusions (Session 179)
    exclude_features = []
    if args.no_vegas or args.two_stage:
        exclude_features = VEGAS_FEATURE_NAMES.copy()
    if args.exclude_features:
        exclude_features.extend([f.strip() for f in args.exclude_features.split(',')])
    # Deduplicate
    exclude_features = list(set(exclude_features))

    if exclude_features:
        print(f"\nExcluding {len(exclude_features)} features: {exclude_features}")

    # Prepare features (with exclusions for no-vegas/two-stage/custom)
    # For residual mode, we need vegas_points_line in the feature matrix to extract it,
    # so we prepare full features first, then handle residual target separately.
    if args.residual:
        # Residual needs full features (including vegas) for training
        X_train_full, y_train_full = prepare_features(df_train, contract=selected_contract)
        X_eval_full, y_eval = prepare_features(df_eval, contract=selected_contract)
    else:
        X_train_full, y_train_full = prepare_features(df_train, contract=selected_contract, exclude_features=exclude_features)
        X_eval_full, y_eval = prepare_features(df_eval, contract=selected_contract, exclude_features=exclude_features)

    lines = df_eval['vegas_line'].values
    active_feature_names = list(X_train_full.columns)

    # Residual modeling: transform target to (actual - vegas_line), filter to valid vegas
    if args.residual:
        print("\nResidual mode: transforming target to (actual - vegas_line)...")
        vegas_train = X_train_full['vegas_points_line'].values
        valid_train = vegas_train > 0
        X_train_full = X_train_full[valid_train].reset_index(drop=True)
        y_train_full = (y_train_full[valid_train].reset_index(drop=True)
                        - vegas_train[valid_train])
        print(f"  Training: {valid_train.sum():,} of {len(valid_train):,} samples have vegas lines")

        vegas_eval = X_eval_full['vegas_points_line'].values
        valid_eval = vegas_eval > 0
        X_eval_full = X_eval_full[valid_eval].reset_index(drop=True)
        y_eval_residual = (y_eval[valid_eval].reset_index(drop=True)
                           - vegas_eval[valid_eval])
        y_eval_actual = y_eval[valid_eval].reset_index(drop=True)
        lines = lines[valid_eval]
        vegas_eval_filtered = vegas_eval[valid_eval]
        print(f"  Eval: {valid_eval.sum():,} of {len(valid_eval):,} samples have vegas lines")

        # Update df_train/df_eval for downstream (recency weights, walk-forward)
        df_train = df_train[valid_train].reset_index(drop=True)
        df_eval = df_eval[valid_eval].reset_index(drop=True)
        # y_eval is kept as actual points for final metric computation
        y_eval = y_eval_actual

    # For two-stage: also prepare full-feature eval for extracting vegas line
    X_eval = X_eval_full

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

    # Quantile regression: override loss function (Session 179)
    if args.quantile_alpha:
        hp['loss_function'] = f'Quantile:alpha={args.quantile_alpha}'
        print(f"  Quantile loss: alpha={args.quantile_alpha}")

    # General loss function override (Session 179)
    if args.loss_function:
        hp['loss_function'] = args.loss_function
        print(f"  Loss function: {args.loss_function}")

    # Advanced CatBoost training params (Session 179)
    if args.grow_policy:
        hp['grow_policy'] = args.grow_policy
        print(f"  Grow policy: {args.grow_policy}")
    if args.rsm is not None:
        hp['rsm'] = args.rsm
        print(f"  RSM (feature subsampling): {args.rsm}")
    if args.min_data_in_leaf is not None:
        hp['min_data_in_leaf'] = args.min_data_in_leaf
        print(f"  Min data in leaf: {args.min_data_in_leaf}")
    if args.bootstrap:
        hp['bootstrap_type'] = args.bootstrap
        print(f"  Bootstrap type: {args.bootstrap}")
    if args.subsample is not None:
        hp['subsample'] = args.subsample
        print(f"  Subsample: {args.subsample}")
    if args.random_strength is not None:
        hp['random_strength'] = args.random_strength
        print(f"  Random strength: {args.random_strength}")

    # Feature weights: dampen or boost specific features (Session 179)
    feature_weights_map = parse_feature_weights(
        args.feature_weights, args.category_weight, active_feature_names
    )
    if feature_weights_map:
        hp['feature_weights'] = feature_weights_map
        print(f"\n  Feature weights applied ({len(feature_weights_map)} features):")
        for idx, weight in sorted(feature_weights_map.items()):
            print(f"    [{idx:2d}] {active_feature_names[idx]:<30s} = {weight}")

    # Monotone constraints: enforce directional relationships (Session 225)
    if args.monotone_constraints:
        constraints = [int(x) for x in args.monotone_constraints.split(',')]
        if len(constraints) != len(active_feature_names):
            print(f"\n❌ ERROR: monotone_constraints length ({len(constraints)}) != feature count ({len(active_feature_names)})")
            print(f"  Active features: {len(active_feature_names)}")
            print(f"  Expected format: comma-separated list of {len(active_feature_names)} values (-1/0/1)")
            return
        hp['monotone_constraints'] = constraints
        print(f"\n  Monotone constraints applied ({len(constraints)} features):")
        for idx, constraint in enumerate(constraints):
            if constraint != 0:
                direction = "↑ increasing" if constraint == 1 else "↓ decreasing"
                print(f"    [{idx:2d}] {active_feature_names[idx]:<30s} = {constraint:+2d} ({direction})")

    model = cb.CatBoostRegressor(**hp)
    model.fit(X_train, y_train, eval_set=(X_val, y_val), sample_weight=w_train, verbose=100)

    # Feature importance (always on)
    feature_importance = display_feature_importance(model, active_feature_names)

    # Evaluate
    print("\nEvaluating...")
    raw_preds = model.predict(X_eval)

    # Reconstruct absolute predictions for alternative modes (Session 179)
    if args.residual:
        # Model predicted residuals (actual - vegas), reconstruct absolute
        preds = vegas_eval_filtered + raw_preds
        print(f"  Residual mode: reconstructed {len(preds)} absolute predictions")
        print(f"  Residual stats: mean={raw_preds.mean():.2f}, std={raw_preds.std():.2f}")
    elif args.two_stage:
        # Model predicts points independently; edge = pred - vegas_line
        preds = raw_preds
        print(f"  Two-stage mode: model predicts independently, edge = pred - vegas")
        print(f"  Raw pred stats: mean={preds.mean():.2f}, std={preds.std():.2f}")
        print(f"  Vegas line stats: mean={lines.mean():.2f}")
    else:
        preds = raw_preds

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

    # Segmented hit rates (Session 180 — per-tier/direction/edge/line breakdowns)
    segmented = compute_segmented_hit_rates(preds, y_eval.values, lines, season_avgs=season_avgs, min_edge=3.0)

    # Walk-forward per-week breakdown (if --walkforward)
    walkforward_results = None
    if args.walkforward:
        walkforward_results = run_walkforward_eval(model, df_eval, X_eval, y_eval, lines)

    # Vegas bias gate (Session 163 — the Feb 2 retrain had good MAE but -2.26 Vegas bias)
    pred_vs_vegas = np.mean(preds - lines)
    VEGAS_BIAS_LIMIT = 1.5

    # Determine experiment mode suffix for filename (Session 179)
    n_features = len(active_feature_names)
    mode_suffix = ""
    if args.no_vegas:
        mode_suffix = "_noveg"
    elif args.residual:
        mode_suffix = "_resid"
    elif args.two_stage:
        mode_suffix = "_2stg"
    elif args.quantile_alpha:
        mode_suffix = f"_q{args.quantile_alpha}"
    if feature_weights_map:
        mode_suffix += "_wt"

    # Save model with standard naming (Session 164: include train start-end range in filename)
    MODEL_OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    train_start_compact = dates['train_start'].replace('-', '')
    train_end_compact = dates['train_end'].replace('-', '')
    model_path = MODEL_OUTPUT_DIR / f"catboost_v9_{n_features}f{mode_suffix}_train{train_start_compact}-{train_end_compact}_{ts}.cbm"
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

    # Segmented Hit Rate Breakdown (Session 180 — find model "specialties")
    print("\n" + "-" * 50)
    print("SEGMENTED HIT RATES (edge 3+)")
    print("-" * 50)

    # Tier HR
    print("\n  By Tier:")
    print(f"    {'Tier':<20s} {'HR':>7s} {'N':>5s}")
    for tier_name, data in segmented['by_tier'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] is not None else "N/A"
        print(f"    {tier_name:<20s} {hr_s:>7s} {data['n']:5d}")

    # Direction x Tier matrix
    print("\n  Direction x Tier:")
    print(f"    {'Segment':<30s} {'HR':>7s} {'N':>5s}")
    for seg_name, data in segmented['by_tier_direction'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] is not None else "N/A"
        if data['n'] > 0:
            print(f"    {seg_name:<30s} {hr_s:>7s} {data['n']:5d}")

    # Edge buckets
    print("\n  By Edge Bucket:")
    print(f"    {'Bucket':<20s} {'HR':>7s} {'N':>5s}")
    for bucket_name, data in segmented['by_edge_bucket'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] is not None else "N/A"
        print(f"    {bucket_name:<20s} {hr_s:>7s} {data['n']:5d}")

    # Line ranges
    print("\n  By Line Range:")
    print(f"    {'Range':<20s} {'HR':>7s} {'N':>5s}")
    for range_name, data in segmented['by_line_range'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] is not None else "N/A"
        print(f"    {range_name:<20s} {hr_s:>7s} {data['n']:5d}")

    # Flag best segments
    best_segments = []
    for section_name, section_data in segmented.items():
        for seg_name, data in section_data.items():
            if data['hr'] is not None and data['hr'] >= 58.0 and data['n'] >= 5:
                best_segments.append((seg_name, data['hr'], data['n']))
    if best_segments:
        print("\n  ** Best segments (HR >= 58%, N >= 5):")
        for seg_name, hr, n in sorted(best_segments, key=lambda x: -x[1]):
            print(f"     {seg_name}: {hr:.1f}% (n={n})")

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
        print()

        # Generate ready-to-paste MONTHLY_MODELS config snippet (Session 177)
        train_start_short = dates['train_start'].replace('-', '')[4:]  # MMDD
        train_end_short = dates['train_end'].replace('-', '')[4:]      # MMDD
        system_id_suggestion = f"catboost_v9_train{train_start_short}_{train_end_short}"
        gcs_monthly_path = f"gs://nba-props-platform-models/catboost/v9/monthly/{model_path.name}"

        print("=" * 70)
        print(" MONTHLY_MODELS CONFIG (paste into catboost_monthly.py)")
        print("=" * 70)
        print(f'    "{system_id_suggestion}": {{')
        print(f'        "model_path": "{gcs_monthly_path}",')
        print(f'        "train_start": "{dates["train_start"]}",')
        print(f'        "train_end": "{dates["train_end"]}",')
        print(f'        "backtest_mae": {round(mae, 3)},')
        print(f'        "backtest_hit_rate_all": {hr_all},')
        print(f'        "backtest_hit_rate_edge_3plus": {hr_edge3},')
        print(f'        "backtest_n_edge_3plus": {bets_edge3},')
        print(f'        "enabled": True,')
        print(f'        "description": "{args.name}",')
        print(f'    }},')
        print()

        print("Next steps:")
        print(f"  1. Upload: gsutil cp {model_path} {gcs_monthly_path}")
        print(f"  2. Paste config above into catboost_monthly.py MONTHLY_MODELS dict")
        print(f"  3. Deploy worker (push to main)")
        print(f"  4. Monitor: python bin/compare-model-performance.py {system_id_suggestion}")
        print(f"  5. After 2+ days shadow: promote or retire")
    else:
        print("GATES FAILED — do NOT deploy this model")
        print("Fix the failing gates or try different training parameters")

    print(f"\nModel saved: {model_path}")
    print(f"SHA256: {model_sha256}")
    print(f"Size: {model_path.stat().st_size:,} bytes")

    # Register
    if not args.skip_register:
        # Determine experiment_type based on mode (Session 179)
        if args.no_vegas:
            experiment_type = 'monthly_retrain_no_vegas'
        elif args.residual:
            experiment_type = 'monthly_retrain_residual'
        elif args.two_stage:
            experiment_type = 'monthly_retrain_two_stage'
        elif args.quantile_alpha:
            experiment_type = 'monthly_retrain_quantile'
        elif args.feature_weights or args.category_weight:
            experiment_type = 'monthly_retrain_weighted'
        else:
            experiment_type = 'monthly_retrain'

        try:
            row = {
                'experiment_id': exp_id,
                'experiment_name': args.name,
                'experiment_type': experiment_type,
                'hypothesis': args.hypothesis or f'Monthly retrain {train_days_actual}d train, {eval_days_actual}d eval',
                'config_json': json.dumps({
                    'train_days': train_days_actual, 'eval_days': eval_days_actual,
                    'features': n_features, 'feature_set': args.feature_set,
                    'line_source': 'production' if args.use_production_lines else args.line_source,
                    'recency_weight': args.recency_weight,
                    'tuned': args.tune, 'tuned_params': tuned_params,
                    'hyperparameters': {k: v for k, v in hp.items() if k != 'verbose'},
                    'no_vegas': args.no_vegas,
                    'residual': args.residual,
                    'two_stage': args.two_stage,
                    'quantile_alpha': args.quantile_alpha,
                    'exclude_features': exclude_features if exclude_features else None,
                    'feature_weights': args.feature_weights,
                    'category_weight': args.category_weight,
                    'feature_weights_resolved': {active_feature_names[k]: v for k, v in feature_weights_map.items()} if feature_weights_map else None,
                    'monotone_constraints': args.monotone_constraints,
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
                    'segmented_hit_rates': segmented,
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
