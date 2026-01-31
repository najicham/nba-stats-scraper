#!/usr/bin/env python3
"""
Stacked Ensemble with Recency Weighting Experiment

This script trains a full stacked ensemble (XGBoost + LightGBM + CatBoost + Ridge)
with optional recency weighting to answer the key question from Sessions 52-55:

**Does recency weighting help the ENSEMBLE, not just single CatBoost?**

Session 52: Single CatBoost + 60d recency → 65% high-conf hit rate
Session 53: Ensemble outperforms single CatBoost (57% vs 51%)
Session 55: This experiment combines both

Usage:
    # Train ensemble with 60-day recency weighting
    PYTHONPATH=. python ml/experiments/train_stacked_ensemble_recency.py \
        --train-start 2021-11-01 \
        --train-end 2024-06-30 \
        --experiment-id ENS_REC60 \
        --use-recency-weights \
        --half-life 60

    # Train ensemble without recency (baseline)
    PYTHONPATH=. python ml/experiments/train_stacked_ensemble_recency.py \
        --train-start 2021-11-01 \
        --train-end 2024-06-30 \
        --experiment-id ENS_BASELINE
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
import json
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
import xgboost as xgb
import lightgbm as lgb
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path(__file__).parent / "results"


def calculate_sample_weights(dates: pd.Series, half_life_days: int = 60) -> np.ndarray:
    """
    Calculate sample weights based on recency with exponential decay.

    Args:
        dates: Series of game dates
        half_life_days: Days for weight to decay by 50%

    Returns:
        Normalized weights (mean = 1.0)
    """
    dates = pd.to_datetime(dates)
    max_date = dates.max()
    days_old = (max_date - dates).dt.days
    decay_rate = np.log(2) / half_life_days
    weights = np.exp(-days_old * decay_rate)
    weights = weights / weights.mean()  # Normalize
    return weights.values


# Feature names matching V8/V9 architecture
ALL_FEATURES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10",
]


def get_training_query(train_start: str, train_end: str) -> str:
    """Generate BigQuery SQL for fetching training data."""
    return f"""
SELECT
  mf.player_lookup,
  mf.game_date,
  mf.features,
  mf.feature_count,
  pgs.points as actual_points
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON mf.player_lookup = pgs.player_lookup
  AND mf.game_date = pgs.game_date
WHERE mf.game_date BETWEEN '{train_start}' AND '{train_end}'
  AND mf.feature_count >= 33
  AND ARRAY_LENGTH(mf.features) >= 33
  AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""


def prepare_features(df: pd.DataFrame) -> tuple:
    """Prepare feature matrix from raw dataframe."""
    sample_features = df.iloc[0]['features']
    actual_count = len(sample_features)
    feature_names = ALL_FEATURES[:min(actual_count, 33)]

    X = pd.DataFrame(
        [row[:len(feature_names)] for row in df['features'].tolist()],
        columns=feature_names
    )

    medians = X.median().to_dict()
    X = X.fillna(X.median())
    y = df['actual_points'].astype(float)

    return X, y, medians, feature_names


def train_xgboost(X_train, y_train, X_val, y_val, sample_weight=None):
    """Train XGBoost with V8 hyperparameters."""
    model = xgb.XGBRegressor(
        max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
        subsample=0.7, colsample_bytree=0.7, gamma=0.1, reg_alpha=0.5, reg_lambda=5.0,
        random_state=42, objective='reg:squarederror', eval_metric='mae',
        early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False,
              sample_weight=sample_weight)
    return model


def train_lightgbm(X_train, y_train, X_val, y_val, sample_weight=None):
    """Train LightGBM with V8 hyperparameters."""
    model = lgb.LGBMRegressor(
        max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
        subsample=0.7, colsample_bytree=0.7, reg_alpha=0.5, reg_lambda=5.0,
        random_state=42, verbose=-1
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)],
              callbacks=[lgb.early_stopping(50, verbose=False)],
              sample_weight=sample_weight)
    return model


def train_catboost(X_train, y_train, X_val, y_val, sample_weight=None):
    """Train CatBoost with V8 hyperparameters."""
    model = cb.CatBoostRegressor(
        depth=6, learning_rate=0.07, l2_leaf_reg=3.8, subsample=0.72,
        min_data_in_leaf=16, iterations=1000, random_seed=42, verbose=False,
        early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val), sample_weight=sample_weight)
    return model


def main():
    parser = argparse.ArgumentParser(description="Train stacked ensemble with recency weighting")
    parser.add_argument("--train-start", required=True, help="Training start date")
    parser.add_argument("--train-end", required=True, help="Training end date")
    parser.add_argument("--experiment-id", required=True, help="Experiment identifier")
    parser.add_argument("--use-recency-weights", action="store_true",
                       help="Apply exponential recency weighting")
    parser.add_argument("--half-life", type=int, default=60,
                       help="Recency half-life in days (default: 60)")
    args = parser.parse_args()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_prefix = f"ensemble_exp_{args.experiment_id}_{timestamp}"

    print("=" * 80)
    print(f" STACKED ENSEMBLE EXPERIMENT: {args.experiment_id}")
    print("=" * 80)
    print(f"Training period: {args.train_start} to {args.train_end}")
    print(f"Recency weighting: {'ENABLED (half-life: ' + str(args.half_life) + ' days)' if args.use_recency_weights else 'DISABLED'}")
    print()

    # Load data
    print("Loading training data...")
    client = bigquery.Client(project=PROJECT_ID)
    query = get_training_query(args.train_start, args.train_end)
    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} samples")

    # Prepare features
    print("Preparing features...")
    X, y, medians, feature_names = prepare_features(df)
    print(f"Features: {len(feature_names)}")

    # Chronological split
    df_sorted = df.sort_values('game_date').reset_index(drop=True)
    X = X.iloc[df_sorted.index].reset_index(drop=True)
    y = y.iloc[df_sorted.index].reset_index(drop=True)

    n = len(X)
    train_end_idx = int(n * 0.70)
    val_end_idx = int(n * 0.85)

    X_train, X_val, X_test = X.iloc[:train_end_idx], X.iloc[train_end_idx:val_end_idx], X.iloc[val_end_idx:]
    y_train, y_val, y_test = y.iloc[:train_end_idx], y.iloc[train_end_idx:val_end_idx], y.iloc[val_end_idx:]

    print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")

    # Calculate sample weights
    sample_weights = None
    weight_stats = None
    if args.use_recency_weights:
        print(f"\nCalculating recency weights (half-life: {args.half_life} days)...")
        train_dates = df_sorted.iloc[:train_end_idx]['game_date']
        sample_weights = calculate_sample_weights(train_dates, args.half_life)
        weight_stats = {
            "min": float(sample_weights.min()),
            "max": float(sample_weights.max()),
            "mean": float(sample_weights.mean()),
            "std": float(sample_weights.std()),
        }
        print(f"Weight stats: min={weight_stats['min']:.4f}, max={weight_stats['max']:.4f}")

    # Train base models
    results = {}

    print("\n[1/3] Training XGBoost...")
    xgb_model = train_xgboost(X_train, y_train, X_val, y_val, sample_weights)
    xgb_test_pred = xgb_model.predict(X_test)
    results['XGBoost'] = {'mae': mean_absolute_error(y_test, xgb_test_pred)}
    print(f"    XGBoost Test MAE: {results['XGBoost']['mae']:.4f}")

    print("\n[2/3] Training LightGBM...")
    lgb_model = train_lightgbm(X_train, y_train, X_val, y_val, sample_weights)
    lgb_test_pred = lgb_model.predict(X_test)
    results['LightGBM'] = {'mae': mean_absolute_error(y_test, lgb_test_pred)}
    print(f"    LightGBM Test MAE: {results['LightGBM']['mae']:.4f}")

    print("\n[3/3] Training CatBoost...")
    cb_model = train_catboost(X_train, y_train, X_val, y_val, sample_weights)
    cb_test_pred = cb_model.predict(X_test)
    results['CatBoost'] = {'mae': mean_absolute_error(y_test, cb_test_pred)}
    print(f"    CatBoost Test MAE: {results['CatBoost']['mae']:.4f}")

    # Create ensembles
    print("\n" + "=" * 80)
    print("ENSEMBLE METHODS")
    print("=" * 80)

    # Simple average
    avg_pred = (xgb_test_pred + lgb_test_pred + cb_test_pred) / 3
    results['Simple_Avg'] = {'mae': mean_absolute_error(y_test, avg_pred)}
    print(f"\nSimple Average MAE: {results['Simple_Avg']['mae']:.4f}")

    # Stacked with Ridge meta-learner
    xgb_val_pred = xgb_model.predict(X_val)
    lgb_val_pred = lgb_model.predict(X_val)
    cb_val_pred = cb_model.predict(X_val)

    stack_val = np.column_stack([xgb_val_pred, lgb_val_pred, cb_val_pred])
    stack_test = np.column_stack([xgb_test_pred, lgb_test_pred, cb_test_pred])

    meta = Ridge(alpha=1.0)
    meta.fit(stack_val, y_val)
    stacked_pred = meta.predict(stack_test)
    results['Stacked'] = {
        'mae': mean_absolute_error(y_test, stacked_pred),
        'coefs': meta.coef_.tolist(),
        'intercept': float(meta.intercept_)
    }
    print(f"Stacked (Ridge) MAE: {results['Stacked']['mae']:.4f}")
    print(f"  Coefficients: XGB={meta.coef_[0]:.4f}, LGB={meta.coef_[1]:.4f}, CB={meta.coef_[2]:.4f}")

    # Summary
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)

    V8_MAE = 3.40  # Production V8 stacked ensemble baseline
    print(f"\n{'Model':<15} {'Test MAE':>10} {'vs V8':>10}")
    print("-" * 40)
    for name in ['XGBoost', 'LightGBM', 'CatBoost', 'Simple_Avg', 'Stacked']:
        mae = results[name]['mae']
        vs_v8 = ((V8_MAE - mae) / V8_MAE) * 100
        marker = " ***" if name == 'Stacked' else ""
        print(f"{name:<15} {mae:>10.4f} {vs_v8:>+9.1f}%{marker}")

    best_model = min(results.items(), key=lambda x: x[1]['mae'])
    print(f"\nBEST: {best_model[0]} = {best_model[1]['mae']:.4f}")

    # Save models
    MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    xgb_path = MODEL_OUTPUT_DIR / f"{model_prefix}_xgboost.json"
    lgb_path = MODEL_OUTPUT_DIR / f"{model_prefix}_lightgbm.txt"
    cb_path = MODEL_OUTPUT_DIR / f"{model_prefix}_catboost.cbm"

    xgb_model.get_booster().save_model(str(xgb_path))
    lgb_model.booster_.save_model(str(lgb_path))
    cb_model.save_model(str(cb_path))

    print(f"\nSaved models:")
    print(f"  - {xgb_path}")
    print(f"  - {lgb_path}")
    print(f"  - {cb_path}")

    # Save metadata
    metadata = {
        "experiment_id": args.experiment_id,
        "model_prefix": model_prefix,
        "train_period": {
            "start": args.train_start,
            "end": args.train_end,
            "samples": len(df),
        },
        "features": feature_names,
        "feature_count": len(feature_names),
        "recency_weighting": {
            "enabled": args.use_recency_weights,
            "half_life_days": args.half_life if args.use_recency_weights else None,
            "weight_stats": weight_stats,
        },
        "results": {
            "XGBoost": {"mae": results['XGBoost']['mae']},
            "LightGBM": {"mae": results['LightGBM']['mae']},
            "CatBoost": {"mae": results['CatBoost']['mae']},
            "Simple_Avg": {"mae": results['Simple_Avg']['mae']},
            "Stacked": {
                "mae": results['Stacked']['mae'],
                "coefs": results['Stacked']['coefs'],
                "intercept": results['Stacked']['intercept'],
            },
        },
        "model_files": {
            "xgboost": str(xgb_path),
            "lightgbm": str(lgb_path),
            "catboost": str(cb_path),
        },
        "trained_at": datetime.now().isoformat(),
    }

    metadata_path = MODEL_OUTPUT_DIR / f"{model_prefix}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata to {metadata_path}")

    print("\n" + "=" * 80)
    print("TRAINING COMPLETE")
    print("=" * 80)
    print(f"""
Next steps:
1. Evaluate on January 2026:
   PYTHONPATH=. python ml/experiments/evaluate_stacked_ensemble.py \\
       --metadata-path "{metadata_path}" \\
       --eval-start 2026-01-01 --eval-end 2026-01-30

2. Compare with single CatBoost:
   - This ensemble: {results['Stacked']['mae']:.4f} MAE
   - Production V8: 3.40 MAE
   - Difference: {((3.40 - results['Stacked']['mae']) / 3.40) * 100:+.1f}%
""")

    return metadata


if __name__ == "__main__":
    main()
