#!/usr/bin/env python3
"""
Production Training Script: CatBoost V2 MLB Pitcher Strikeouts Regressor

Trains the CatBoostRegressor model that powers catboost_v2_regressor predictions.
Uses the same 40 features, SQL query, and data pipeline as the walk-forward
simulation and production predictor.

Target: actual_value (raw strikeout count)
Edge: predicted_K - over_line (real K units)
Direction: OVER if predicted_K > line, UNDER otherwise

Governance gates (must ALL pass before model is saved):
  1. Validation MAE < 2.0
  2. OVER HR >= 55% at edge >= 0.75 on validation set
  3. N >= 30 graded predictions on validation set
  4. No extreme directional bias (OVER rate between 30-70%)

Usage:
    PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \\
        --training-end 2025-09-28 \\
        --window 120 \\
        --output-dir models/mlb/

    PYTHONPATH=. python scripts/mlb/training/train_regressor_v2.py \\
        --training-start 2024-06-01 \\
        --training-end 2025-09-28 \\
        --output-dir models/mlb/ \\
        --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from google.cloud import bigquery
from catboost import CatBoostRegressor

PROJECT_ID = "nba-props-platform"

# ============================================================================
# Feature contract — MUST match production predictor exactly
# Source: predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py
#
# Session 444: Removed 5 dead/duplicate features (36 features, was 40):
#   - f17_month_of_season, f18_days_into_season, f24_is_postseason (dead)
#   - f67_season_starts (duplicate of f08_season_games)
#   - f69_recent_workload_ratio (duplicate of f21_games_last_30_days / 6.0)
# ============================================================================
FEATURE_COLS = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f19_season_swstr_pct', 'f19b_season_csw_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f25_is_day_game',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff', 'f44_over_implied_prob',
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
    'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
    'f68_k_per_pitch',
    'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
]

# Model hyperparameters — validated via walk-forward simulation
HYPERPARAMS = {
    'depth': 5,
    'learning_rate': 0.015,
    'iterations': 500,
    'l2_leaf_reg': 3,
    'subsample': 0.8,
    'random_seed': 42,
    'verbose': 100,
    'loss_function': 'RMSE',
}

# Governance gate thresholds
GOVERNANCE = {
    'max_mae': 2.0,
    'min_over_hr_at_edge': 55.0,     # % OVER HR at edge >= 0.75
    'edge_threshold': 0.75,           # K edge for HR gate
    'min_validation_n': 30,           # minimum graded predictions
    'min_over_rate': 30.0,            # % — reject extreme UNDER bias
    'max_over_rate': 70.0,            # % — reject extreme OVER bias
}

HOLDOUT_DAYS = 14  # Last N days of training window used as validation


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train CatBoost V2 MLB Pitcher Strikeouts Regressor"
    )
    parser.add_argument(
        "--training-start", type=str, default=None,
        help="Training start date (YYYY-MM-DD). Default: 120 days before --training-end"
    )
    parser.add_argument(
        "--training-end", type=str, default=None,
        help="Training end date (YYYY-MM-DD). Default: today"
    )
    parser.add_argument(
        "--window", type=int, default=None,
        help="Training window in days. If set, overrides --training-start to be "
             "this many days before --training-end"
    )
    parser.add_argument(
        "--output-dir", type=str, default="models/mlb/",
        help="Output directory for model and metadata (default: models/mlb/)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run training and evaluation but skip saving model to disk"
    )
    return parser.parse_args()


def resolve_dates(args) -> tuple:
    """Resolve training start/end dates from args."""
    if args.training_end:
        training_end = pd.Timestamp(args.training_end)
    else:
        training_end = pd.Timestamp(datetime.now().strftime('%Y-%m-%d'))

    if args.window:
        training_start = training_end - pd.Timedelta(days=args.window)
    elif args.training_start:
        training_start = pd.Timestamp(args.training_start)
    else:
        training_start = training_end - pd.Timedelta(days=120)

    return training_start, training_end


def load_data(client: bigquery.Client, training_start: pd.Timestamp,
              training_end: pd.Timestamp) -> pd.DataFrame:
    """
    Load training data from BigQuery.

    Uses the same SQL query as walk_forward_simulation.py and
    mlb_regression_test.py. Date range is parameterized.
    """
    print("Loading data from BigQuery...")
    print(f"  Date range: {training_start.date()} to {training_end.date()}")

    # Need buffer before training_start for rolling features to be populated
    query_start = training_start - pd.Timedelta(days=30)

    query = f"""
    WITH statcast_rolling AS (
        SELECT DISTINCT
            player_lookup,
            game_date,
            swstr_pct_last_3,
            swstr_pct_last_5,
            swstr_pct_season_prior,
            fb_velocity_last_3,
            fb_velocity_season_prior
        FROM `mlb_analytics.pitcher_rolling_statcast`
        WHERE statcast_games_count >= 3
    )
    SELECT
        bp.game_date,
        bp.player_name,
        bp.player_lookup AS bp_player_lookup,
        bp.over_line,
        bp.projection_value,
        bp.actual_value,
        bp.over_odds,
        CASE WHEN bp.actual_value > bp.over_line THEN 1 ELSE 0 END as went_over,

        -- Metadata (not features)
        pgs.player_lookup,
        pgs.team_abbr,
        pgs.opponent_team_abbr,

        -- Features (40 total — must match FEATURE_COLS order)
        pgs.k_avg_last_3 as f00_k_avg_last_3,
        pgs.k_avg_last_5 as f01_k_avg_last_5,
        pgs.k_avg_last_10 as f02_k_avg_last_10,
        pgs.k_std_last_10 as f03_k_std_last_10,
        pgs.ip_avg_last_5 as f04_ip_avg_last_5,
        pgs.season_k_per_9 as f05_season_k_per_9,
        pgs.era_rolling_10 as f06_season_era,
        pgs.whip_rolling_10 as f07_season_whip,
        pgs.season_games_started as f08_season_games,
        pgs.season_strikeouts as f09_season_k_total,
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        pgs.opponent_team_k_rate as f15_opponent_team_k_rate,
        pgs.ballpark_k_factor as f16_ballpark_k_factor,
        pgs.month_of_season as f17_month_of_season,
        pgs.days_into_season as f18_days_into_season,
        pgs.season_swstr_pct as f19_season_swstr_pct,
        pgs.season_csw_pct as f19b_season_csw_pct,
        pgs.days_rest as f20_days_rest,
        pgs.games_last_30_days as f21_games_last_30_days,
        pgs.pitch_count_avg_last_5 as f22_pitch_count_avg,
        pgs.season_innings as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,

        -- Line-relative features
        (pgs.k_avg_last_5 - bp.over_line) as f30_k_avg_vs_line,
        bp.over_line as f32_line_level,

        -- BettingPros features
        bp.projection_value as f40_bp_projection,
        (bp.projection_value - bp.over_line) as f41_projection_diff,
        CASE
            WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
            ELSE 100.0 / (bp.over_odds + 100.0)
        END as f44_over_implied_prob,

        -- Rolling Statcast Features with COALESCE fallbacks
        COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct) as f50_swstr_pct_last_3,
        COALESCE(sc.fb_velocity_last_3, sc.fb_velocity_season_prior) as f51_fb_velocity_last_3,
        COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
        COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change,

        -- Pitcher matchup features
        pgs.vs_opponent_k_per_9 as f65_vs_opp_k_per_9,
        pgs.vs_opponent_games as f66_vs_opp_games,

        -- Deep workload features
        pgs.season_games_started as f67_season_starts,
        SAFE_DIVIDE(pgs.k_avg_last_5, NULLIF(pgs.pitch_count_avg_last_5, 0)) as f68_k_per_pitch,
        SAFE_DIVIDE(pgs.games_last_30_days, 6.0) as f69_recent_workload_ratio,

        -- FanGraphs advanced pitching features
        fg.o_swing_pct as f70_o_swing_pct,
        fg.z_contact_pct as f71_z_contact_pct,
        fg.fip as f72_fip,
        fg.gb_pct as f73_gb_pct

    FROM `mlb_raw.bp_pitcher_props` bp
    JOIN `mlb_analytics.pitcher_game_summary` pgs
        ON pgs.game_date = bp.game_date
        AND LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', '')) = bp.player_lookup
    LEFT JOIN statcast_rolling sc
        ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
        AND pgs.game_date = sc.game_date
    LEFT JOIN `mlb_raw.fangraphs_pitcher_season_stats` fg
        ON LOWER(REGEXP_REPLACE(NORMALIZE(fg.player_lookup, NFD), r'[\\W_]+', ''))
            = LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', ''))
        AND fg.season_year = EXTRACT(YEAR FROM pgs.game_date)
    WHERE bp.market_id = 285
      AND bp.actual_value IS NOT NULL
      AND bp.projection_value IS NOT NULL
      AND bp.over_line IS NOT NULL
      AND pgs.innings_pitched >= 3.0
      AND pgs.rolling_stats_games >= 3
      AND pgs.game_date >= '{query_start.strftime('%Y-%m-%d')}'
      AND pgs.game_date <= '{training_end.strftime('%Y-%m-%d')}'
    ORDER BY bp.game_date
    """

    df = client.query(query).to_dataframe()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values('game_date').reset_index(drop=True)

    # Filter to requested date range (query_start buffer was for rolling features)
    df = df[df['game_date'] >= training_start].reset_index(drop=True)

    print(f"  Loaded {len(df):,} samples")
    if len(df) > 0:
        print(f"  Actual date range: {df['game_date'].min().date()} to {df['game_date'].max().date()}")

    # Report Statcast coverage
    sc_cols = [c for c in df.columns if c.startswith('f5')]
    if sc_cols:
        sc_coverage = df[sc_cols[0]].notna().mean() * 100
        print(f"  Statcast feature coverage: {sc_coverage:.1f}%")

    # Report FanGraphs coverage
    fg_cols = [c for c in df.columns if c.startswith('f7')]
    if fg_cols:
        fg_coverage = df[fg_cols[0]].notna().mean() * 100
        print(f"  FanGraphs feature coverage: {fg_coverage:.1f}%")

    return df


def verify_features(df: pd.DataFrame) -> list:
    """Verify all 40 features are present in the DataFrame."""
    missing = [f for f in FEATURE_COLS if f not in df.columns]
    if missing:
        print(f"\nFATAL: {len(missing)} features missing from query results:")
        for f in missing:
            print(f"  - {f}")
        sys.exit(1)

    present = [f for f in FEATURE_COLS if f in df.columns]
    print(f"\nFeature contract verified: {len(present)}/40 features present")
    return present


def split_train_val(df: pd.DataFrame, holdout_days: int = HOLDOUT_DAYS) -> tuple:
    """Split data into training and validation sets.

    Validation = last holdout_days of the date range (temporal split).
    """
    max_date = df['game_date'].max()
    val_cutoff = max_date - pd.Timedelta(days=holdout_days)

    train_df = df[df['game_date'] <= val_cutoff].copy()
    val_df = df[df['game_date'] > val_cutoff].copy()

    print(f"\nTrain/Val split (holdout = last {holdout_days} days):")
    print(f"  Training:   {len(train_df):,} samples "
          f"({train_df['game_date'].min().date()} to {train_df['game_date'].max().date()})")
    print(f"  Validation: {len(val_df):,} samples "
          f"({val_df['game_date'].min().date()} to {val_df['game_date'].max().date()})")

    return train_df, val_df


def prepare_features(df: pd.DataFrame, feature_cols: list) -> pd.DataFrame:
    """Prepare feature matrix — coerce to numeric, preserve NaN for CatBoost."""
    X = df[feature_cols].copy()
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors='coerce')
    return X


def train_model(X_train: pd.DataFrame, y_train: pd.Series) -> CatBoostRegressor:
    """Train CatBoostRegressor with production hyperparameters."""
    model = CatBoostRegressor(**HYPERPARAMS)
    model.fit(X_train, y_train)
    return model


def evaluate_model(model: CatBoostRegressor, val_df: pd.DataFrame,
                   feature_cols: list) -> dict:
    """Evaluate model on validation set and return metrics."""
    X_val = prepare_features(val_df, feature_cols)
    y_actual = val_df['actual_value'].astype(float).values
    lines = val_df['over_line'].astype(float).values
    went_over = val_df['went_over'].astype(int).values

    # Predict
    predicted_k = model.predict(X_val)

    # Core regression metrics
    residuals = predicted_k - y_actual
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    bias = float(np.mean(residuals))

    # Direction metrics
    edge = predicted_k - lines
    predicted_over = (edge > 0).astype(int)
    correct = (predicted_over == went_over).astype(int)
    overall_hr = float(correct.mean() * 100)
    over_rate = float(predicted_over.mean() * 100)

    # OVER HR at edge threshold
    abs_edge = np.abs(edge)
    edge_mask = abs_edge >= GOVERNANCE['edge_threshold']
    n_at_edge = int(edge_mask.sum())

    over_at_edge_mask = (edge >= GOVERNANCE['edge_threshold'])
    n_over_at_edge = int(over_at_edge_mask.sum())
    if n_over_at_edge > 0:
        over_hr_at_edge = float(
            correct[over_at_edge_mask].mean() * 100
        )
    else:
        over_hr_at_edge = 0.0

    # UNDER HR at edge threshold
    under_at_edge_mask = (edge <= -GOVERNANCE['edge_threshold'])
    n_under_at_edge = int(under_at_edge_mask.sum())
    if n_under_at_edge > 0:
        under_hr_at_edge = float(
            correct[under_at_edge_mask].mean() * 100
        )
    else:
        under_hr_at_edge = 0.0

    # HR at edge threshold (both directions)
    if n_at_edge > 0:
        hr_at_edge = float(correct[edge_mask].mean() * 100)
    else:
        hr_at_edge = 0.0

    metrics = {
        'n_validation': len(val_df),
        'mae': round(mae, 4),
        'rmse': round(rmse, 4),
        'bias': round(bias, 4),
        'overall_hr': round(overall_hr, 2),
        'over_rate': round(over_rate, 2),
        'hr_at_edge': round(hr_at_edge, 2),
        'over_hr_at_edge': round(over_hr_at_edge, 2),
        'under_hr_at_edge': round(under_hr_at_edge, 2),
        'n_at_edge': n_at_edge,
        'n_over_at_edge': n_over_at_edge,
        'n_under_at_edge': n_under_at_edge,
        'edge_threshold': GOVERNANCE['edge_threshold'],
        'mean_predicted_k': round(float(predicted_k.mean()), 3),
        'mean_actual_k': round(float(y_actual.mean()), 3),
        'mean_abs_edge': round(float(abs_edge.mean()), 3),
    }

    return metrics


def check_governance_gates(metrics: dict) -> dict:
    """Check all governance gates. Returns gate results dict."""
    gates = {}

    # Gate 1: MAE < 2.0
    gates['mae_gate'] = {
        'passed': metrics['mae'] < GOVERNANCE['max_mae'],
        'value': metrics['mae'],
        'threshold': GOVERNANCE['max_mae'],
        'description': f"MAE {metrics['mae']:.4f} < {GOVERNANCE['max_mae']}"
    }

    # Gate 2: OVER HR >= 55% at edge >= 0.75
    gates['over_hr_gate'] = {
        'passed': metrics['over_hr_at_edge'] >= GOVERNANCE['min_over_hr_at_edge'],
        'value': metrics['over_hr_at_edge'],
        'threshold': GOVERNANCE['min_over_hr_at_edge'],
        'description': (
            f"OVER HR {metrics['over_hr_at_edge']:.1f}% >= "
            f"{GOVERNANCE['min_over_hr_at_edge']}% at edge >= {GOVERNANCE['edge_threshold']}"
        ),
        'n_over_at_edge': metrics['n_over_at_edge'],
    }

    # Gate 3: N >= 30 on validation set
    gates['n_gate'] = {
        'passed': metrics['n_validation'] >= GOVERNANCE['min_validation_n'],
        'value': metrics['n_validation'],
        'threshold': GOVERNANCE['min_validation_n'],
        'description': f"N={metrics['n_validation']} >= {GOVERNANCE['min_validation_n']}"
    }

    # Gate 4: No extreme directional bias (OVER rate between 30-70%)
    gates['bias_gate'] = {
        'passed': (GOVERNANCE['min_over_rate'] <= metrics['over_rate'] <= GOVERNANCE['max_over_rate']),
        'value': metrics['over_rate'],
        'threshold': f"{GOVERNANCE['min_over_rate']}-{GOVERNANCE['max_over_rate']}",
        'description': (
            f"OVER rate {metrics['over_rate']:.1f}% in "
            f"[{GOVERNANCE['min_over_rate']}, {GOVERNANCE['max_over_rate']}]"
        )
    }

    all_passed = all(g['passed'] for g in gates.values())
    gates['all_passed'] = all_passed

    return gates


def print_feature_importance(model: CatBoostRegressor, feature_cols: list,
                             top_n: int = 15):
    """Print top N features by importance."""
    importances = model.get_feature_importance()
    feature_importance = sorted(
        zip(feature_cols, importances),
        key=lambda x: x[1],
        reverse=True
    )

    print(f"\nTop {top_n} Features by Importance:")
    print(f"{'Rank':>4}  {'Feature':<30} {'Importance':>10}")
    print("-" * 48)
    for i, (feat, imp) in enumerate(feature_importance[:top_n], 1):
        print(f"{i:>4}  {feat:<30} {imp:>9.2f}%")

    return feature_importance


def print_summary(metrics: dict, gates: dict, training_start: pd.Timestamp,
                  training_end: pd.Timestamp, n_train: int):
    """Print training summary."""
    print("\n" + "=" * 70)
    print("  TRAINING SUMMARY")
    print("=" * 70)

    print(f"\n  Training period: {training_start.date()} to {training_end.date()}")
    print(f"  Training samples: {n_train:,}")
    print(f"  Features: {len(FEATURE_COLS)}")
    print(f"  Hyperparameters: depth={HYPERPARAMS['depth']}, "
          f"lr={HYPERPARAMS['learning_rate']}, "
          f"iters={HYPERPARAMS['iterations']}, "
          f"l2={HYPERPARAMS['l2_leaf_reg']}")

    print(f"\n  --- Validation Metrics ---")
    print(f"  N:             {metrics['n_validation']}")
    print(f"  MAE:           {metrics['mae']:.4f} K")
    print(f"  RMSE:          {metrics['rmse']:.4f} K")
    print(f"  Bias:          {metrics['bias']:+.4f} K")
    print(f"  Mean pred K:   {metrics['mean_predicted_k']:.3f}")
    print(f"  Mean actual K: {metrics['mean_actual_k']:.3f}")
    print(f"  Overall HR:    {metrics['overall_hr']:.1f}%")
    print(f"  OVER rate:     {metrics['over_rate']:.1f}%")
    print(f"  Mean |edge|:   {metrics['mean_abs_edge']:.3f} K")

    print(f"\n  --- At Edge >= {GOVERNANCE['edge_threshold']} K ---")
    print(f"  HR:            {metrics['hr_at_edge']:.1f}% (N={metrics['n_at_edge']})")
    print(f"  OVER HR:       {metrics['over_hr_at_edge']:.1f}% (N={metrics['n_over_at_edge']})")
    print(f"  UNDER HR:      {metrics['under_hr_at_edge']:.1f}% (N={metrics['n_under_at_edge']})")

    print(f"\n  --- Governance Gates ---")
    all_passed = gates.get('all_passed', False)
    for gate_name, gate in gates.items():
        if gate_name == 'all_passed':
            continue
        status = "PASS" if gate['passed'] else "FAIL"
        print(f"  [{status}] {gate['description']}")

    if all_passed:
        print(f"\n  >>> ALL GATES PASSED <<<")
    else:
        print(f"\n  >>> GOVERNANCE GATES FAILED — model will NOT be saved <<<")
        failed = [k for k, v in gates.items() if k != 'all_passed' and not v['passed']]
        print(f"  Failed gates: {', '.join(failed)}")

    print("=" * 70)


def save_model(model: CatBoostRegressor, metadata: dict, output_dir: str,
               training_end: pd.Timestamp):
    """Save model and metadata to disk."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    date_str = training_end.strftime('%Y%m%d')
    model_name = f"catboost_mlb_v2_regressor_40f_{date_str}"
    model_path = output_path / f"{model_name}.cbm"
    metadata_path = output_path / f"{model_name}_metadata.json"

    # Save model
    model.save_model(str(model_path))
    print(f"\nModel saved: {model_path}")

    # Save metadata
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Metadata saved: {metadata_path}")

    return str(model_path), str(metadata_path)


def main():
    args = parse_args()
    training_start, training_end = resolve_dates(args)

    print("=" * 70)
    print("  CatBoost V2 MLB Pitcher Strikeouts Regressor — Production Training")
    print("=" * 70)
    print(f"\n  Training window: {training_start.date()} to {training_end.date()}")
    print(f"  Window size: {(training_end - training_start).days} days")
    print(f"  Features: {len(FEATURE_COLS)}")
    print(f"  Target: actual_value (raw strikeout count)")
    print(f"  Holdout: last {HOLDOUT_DAYS} days for validation")
    print(f"  Output: {args.output_dir}")
    if args.dry_run:
        print(f"  DRY RUN — model will not be saved")
    print()

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    client = bigquery.Client(project=PROJECT_ID)
    df = load_data(client, training_start, training_end)

    if len(df) == 0:
        print("\nFATAL: No data loaded. Check date range and BigQuery tables.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Verify feature contract
    # ------------------------------------------------------------------
    feature_cols = verify_features(df)

    # ------------------------------------------------------------------
    # 3. Split train / validation
    # ------------------------------------------------------------------
    train_df, val_df = split_train_val(df, HOLDOUT_DAYS)

    if len(train_df) < 50:
        print(f"\nFATAL: Only {len(train_df)} training samples (need >= 50).")
        sys.exit(1)

    if len(val_df) < GOVERNANCE['min_validation_n']:
        print(f"\nWARNING: Only {len(val_df)} validation samples "
              f"(governance requires >= {GOVERNANCE['min_validation_n']})")

    # ------------------------------------------------------------------
    # 4. Prepare features and target
    # ------------------------------------------------------------------
    X_train = prepare_features(train_df, feature_cols)
    y_train = train_df['actual_value'].astype(float)

    print(f"\nTraining target stats:")
    print(f"  Mean: {y_train.mean():.2f} K")
    print(f"  Std:  {y_train.std():.2f} K")
    print(f"  Min:  {y_train.min():.0f} K")
    print(f"  Max:  {y_train.max():.0f} K")

    # ------------------------------------------------------------------
    # 5. Train model
    # ------------------------------------------------------------------
    print(f"\nTraining CatBoostRegressor ({len(X_train):,} samples, "
          f"{len(feature_cols)} features)...")
    model = train_model(X_train, y_train)

    # Training MAE (sanity check)
    train_preds = model.predict(X_train)
    train_mae = float(np.mean(np.abs(train_preds - y_train.values)))
    print(f"\nTraining MAE: {train_mae:.4f} K (sanity check — should be low)")

    # ------------------------------------------------------------------
    # 6. Evaluate on validation set
    # ------------------------------------------------------------------
    print(f"\nEvaluating on validation set ({len(val_df):,} samples)...")
    metrics = evaluate_model(model, val_df, feature_cols)

    # ------------------------------------------------------------------
    # 7. Governance gates
    # ------------------------------------------------------------------
    gates = check_governance_gates(metrics)

    # ------------------------------------------------------------------
    # 8. Feature importance
    # ------------------------------------------------------------------
    feature_importance = print_feature_importance(model, feature_cols)

    # ------------------------------------------------------------------
    # 9. Print summary
    # ------------------------------------------------------------------
    print_summary(metrics, gates, training_start, training_end, len(train_df))

    # ------------------------------------------------------------------
    # 10. Save model (if gates pass and not dry-run)
    # ------------------------------------------------------------------
    metadata = {
        'model_type': 'CatBoostRegressor',
        'system_id': 'catboost_v2_regressor',
        'model_version': 'catboost_mlb_v2_regressor_40f',
        'training_start': str(training_start.date()),
        'training_end': str(training_end.date()),
        'training_window_days': (training_end - training_start).days,
        'training_samples': len(train_df),
        'holdout_days': HOLDOUT_DAYS,
        'features': feature_cols,
        'feature_count': len(feature_cols),
        'hyperparameters': {k: v for k, v in HYPERPARAMS.items() if k != 'verbose'},
        'target': 'actual_value',
        'validation_metrics': metrics,
        'governance_gates': {
            k: {kk: vv for kk, vv in v.items()}
            for k, v in gates.items()
            if k != 'all_passed'
        },
        'governance_passed': gates['all_passed'],
        'feature_importance_top15': [
            {'feature': feat, 'importance': round(imp, 4)}
            for feat, imp in feature_importance[:15]
        ],
        'training_mae': round(train_mae, 4),
        'trained_at': datetime.now().isoformat(),
    }

    if args.dry_run:
        print(f"\nDRY RUN — skipping model save")
        print(f"Metadata that would be saved:")
        print(json.dumps(metadata, indent=2))
        return

    if not gates['all_passed']:
        print(f"\nGovernance gates FAILED — model NOT saved.")
        print(f"Fix the issues above and retrain.")
        sys.exit(1)

    model_path, metadata_path = save_model(
        model, metadata, args.output_dir, training_end
    )

    print(f"\nDone. Next steps:")
    print(f"  1. Review metadata: {metadata_path}")
    print(f"  2. Upload to GCS:")
    print(f"     gsutil cp {model_path} gs://nba-props-platform-ml-models/mlb/")
    print(f"     gsutil cp {metadata_path} gs://nba-props-platform-ml-models/mlb/")
    print(f"  3. Update worker env var if model path changed:")
    print(f"     gcloud run services update mlb-prediction-worker \\")
    print(f"       --region=us-west2 \\")
    print(f"       --update-env-vars=\"MLB_CATBOOST_V2_MODEL_PATH="
          f"gs://nba-props-platform-ml-models/mlb/{Path(model_path).name}\"")


if __name__ == "__main__":
    main()
