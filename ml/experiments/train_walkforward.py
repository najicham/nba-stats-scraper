#!/usr/bin/env python3
"""
Walk-Forward Training Script for CatBoost V8 Experiments

Trains a CatBoost V8 model on a specified date range. This script is designed
for walk-forward validation experiments to understand optimal training strategies.

Features:
- Configurable training date range via command line
- Same 33-feature architecture as production V8
- Saves model with experiment naming convention
- Outputs metadata JSON for reproducibility

Usage:
    # Train on 2021-22 season
    PYTHONPATH=. python ml/experiments/train_walkforward.py \
        --train-start 2021-11-01 \
        --train-end 2022-06-30 \
        --experiment-id A1

    # Train on multiple seasons
    PYTHONPATH=. python ml/experiments/train_walkforward.py \
        --train-start 2021-11-01 \
        --train-end 2024-06-01 \
        --experiment-id A3
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
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path(__file__).parent / "results"

# Feature names - must match feature store and production V8 exactly (33 features)
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
    "minutes_avg_last_10", "ppm_avg_last_10"
]


def get_training_query(train_start: str, train_end: str) -> str:
    """
    Generate BigQuery SQL for fetching training data.

    The feature store (ml_feature_store_v2) contains all 33 features already.
    We just need to join with actuals to get the target variable.
    """
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
  AND mf.feature_count = 33  -- Must have all 33 features
  AND ARRAY_LENGTH(mf.features) = 33
  AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict]:
    """
    Prepare feature matrix from raw dataframe.

    The feature store already has all 33 features, so we just need to
    unpack the features array into a DataFrame.

    Returns:
        X: Feature matrix (33 features)
        y: Target values (actual_points)
        medians: Median values for imputation (to be saved and used at inference)
    """
    # Unpack features array into DataFrame with named columns
    X = pd.DataFrame(df['features'].tolist(), columns=ALL_FEATURES)

    # Calculate medians before imputation for saving
    medians = X.median().to_dict()

    # Fill any NaN values with median
    X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    return X, y, medians


def train_catboost_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    verbose: bool = False
) -> cb.CatBoostRegressor:
    """
    Train CatBoost model with V8 hyperparameters

    Uses the same hyperparameters as production V8 for fair comparison.
    """
    model = cb.CatBoostRegressor(
        depth=6,
        learning_rate=0.07,
        l2_leaf_reg=3.8,
        subsample=0.72,
        min_data_in_leaf=16,
        iterations=1000,
        random_seed=42,
        verbose=verbose,
        early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val))
    return model


def main():
    parser = argparse.ArgumentParser(description="Train CatBoost V8 model for walk-forward experiments")
    parser.add_argument("--train-start", required=True, help="Training start date (YYYY-MM-DD)")
    parser.add_argument("--train-end", required=True, help="Training end date (YYYY-MM-DD)")
    parser.add_argument("--experiment-id", required=True, help="Experiment identifier (e.g., A1, B2)")
    parser.add_argument("--verbose", action="store_true", help="Show training progress")
    args = parser.parse_args()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_name = f"catboost_v9_exp_{args.experiment_id}_{timestamp}"

    print("=" * 80)
    print(f" WALK-FORWARD TRAINING: Experiment {args.experiment_id}")
    print("=" * 80)
    print(f"Training period: {args.train_start} to {args.train_end}")
    print(f"Model name: {model_name}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Load data
    print("Loading training data...")
    client = bigquery.Client(project=PROJECT_ID)
    query = get_training_query(args.train_start, args.train_end)
    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} samples")

    # Date range validation
    actual_start = df['game_date'].min()
    actual_end = df['game_date'].max()
    print(f"Actual date range: {actual_start} to {actual_end}")

    # Prepare features
    print("\nPreparing features...")
    X, y, medians = prepare_features(df)
    print(f"Features: {X.shape[1]}")

    # Sort by date for chronological split
    df_sorted = df.sort_values('game_date').reset_index(drop=True)
    X = X.iloc[df_sorted.index].reset_index(drop=True)
    y = y.iloc[df_sorted.index].reset_index(drop=True)

    # Split 85/15 for early stopping
    n = len(X)
    split_idx = int(n * 0.85)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"Train: {len(X_train):,}, Validation: {len(X_val):,}")

    # Train model
    print("\nTraining CatBoost...")
    model = train_catboost_model(X_train, y_train, X_val, y_val, verbose=args.verbose)

    best_iter = model.get_best_iteration()
    print(f"Best iteration: {best_iter}")

    # Evaluate on training validation split
    val_pred = model.predict(X_val)
    val_mae = mean_absolute_error(y_val, val_pred)
    print(f"Validation MAE: {val_mae:.4f}")

    # Full training set MAE (for comparison)
    full_pred = model.predict(X)
    full_mae = mean_absolute_error(y, full_pred)
    print(f"Full training MAE: {full_mae:.4f}")

    # Save model
    MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_OUTPUT_DIR / f"{model_name}.cbm"
    model.save_model(str(model_path))
    print(f"\nSaved model to {model_path}")

    # Save metadata
    metadata = {
        "experiment_id": args.experiment_id,
        "model_name": model_name,
        "model_path": str(model_path),
        "train_period": {
            "start": args.train_start,
            "end": args.train_end,
            "actual_start": str(actual_start),
            "actual_end": str(actual_end),
            "samples": len(df),
        },
        "features": ALL_FEATURES,
        "feature_count": len(ALL_FEATURES),
        "feature_medians": medians,
        "hyperparameters": {
            "depth": 6,
            "learning_rate": 0.07,
            "l2_leaf_reg": 3.8,
            "subsample": 0.72,
            "min_data_in_leaf": 16,
            "iterations": 1000,
            "early_stopping_rounds": 50,
        },
        "training_results": {
            "best_iteration": best_iter,
            "validation_mae": float(val_mae),
            "full_training_mae": float(full_mae),
        },
        "trained_at": datetime.now().isoformat(),
    }

    metadata_path = MODEL_OUTPUT_DIR / f"{model_name}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved metadata to {metadata_path}")

    # Summary
    print("\n" + "=" * 80)
    print("TRAINING COMPLETE")
    print("=" * 80)
    print(f"""
Experiment: {args.experiment_id}
Model: {model_name}
Training samples: {len(df):,}
Training period: {args.train_start} to {args.train_end}
Validation MAE: {val_mae:.4f}

Files created:
  - {model_path}
  - {metadata_path}

Next step: Run evaluation with ml/experiments/evaluate_model.py
""")

    return metadata


if __name__ == "__main__":
    main()
