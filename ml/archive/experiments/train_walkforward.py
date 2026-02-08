#!/usr/bin/env python3
"""
Walk-Forward Training Script for CatBoost V8 Experiments

Trains a CatBoost V8 model on a specified date range. This script is designed
for walk-forward validation experiments to understand optimal training strategies.

Features:
- Configurable training date range via command line or YAML config
- Same 33-feature architecture as production V8
- Saves model with experiment naming convention
- Outputs metadata JSON for reproducibility
- Optional experiment registry integration for tracking

Usage:
    # Train on 2021-22 season (original way - still works)
    PYTHONPATH=. python ml/experiments/train_walkforward.py \
        --train-start 2021-11-01 \
        --train-end 2022-06-30 \
        --experiment-id A1

    # Train with YAML config
    PYTHONPATH=. python ml/experiments/train_walkforward.py \
        --config configs/my_experiment.yaml

    # Train without registry (skip BigQuery tracking)
    PYTHONPATH=. python ml/experiments/train_walkforward.py \
        --train-start 2021-11-01 \
        --train-end 2022-06-30 \
        --experiment-id A1 \
        --no-registry
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
import json
import yaml
import traceback
from datetime import datetime
from typing import Optional
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
import catboost as cb

from ml.experiments.experiment_registry import ExperimentRegistry, get_git_commit

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path(__file__).parent / "results"


def calculate_sample_weights(dates: pd.Series, half_life_days: int = 180) -> np.ndarray:
    """
    Calculate sample weights based on recency.

    More recent samples get higher weights, decaying exponentially.
    Uses half-life parameter to control decay rate.

    Args:
        dates: Series of game dates
        half_life_days: Number of days for weight to decay by 50% (default: 180 = 6 months)

    Returns:
        Normalized weights array (mean = 1.0 to preserve effective sample size)

    Example:
        - Game from today: weight ~1.0
        - Game from 180 days ago: weight ~0.5
        - Game from 360 days ago: weight ~0.25
    """
    # Convert to datetime if needed
    dates = pd.to_datetime(dates)
    max_date = dates.max()

    # Calculate days old for each sample
    days_old = (max_date - dates).dt.days

    # Exponential decay: weight = exp(-days_old * ln(2) / half_life)
    # This ensures weight = 0.5 when days_old = half_life
    decay_rate = np.log(2) / half_life_days
    weights = np.exp(-days_old * decay_rate)

    # Normalize so mean weight = 1.0 (preserves effective sample size)
    weights = weights / weights.mean()

    return weights.values


# Feature names - must match feature store and production
# v2_37features: 37 features as of Session 28 (Jan 2026)
# Note: For backward compatibility, training queries filter by feature_count
ALL_FEATURES = [
    # Recent Performance (0-4)
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    # Composite Factors (5-8)
    "fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    # Derived Factors (9-12)
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    # Matchup Context (13-17)
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back", "playoff_game",
    # Shot Zones (18-21)
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    # Team Context (22-24)
    "team_pace", "team_off_rating", "team_win_pct",
    # Vegas Lines (25-28)
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    # Opponent History (29-30)
    "avg_points_vs_opponent", "games_vs_opponent",
    # Minutes/Efficiency (31-32)
    "minutes_avg_last_10", "ppm_avg_last_10",
    # DNP Risk (33)
    "dnp_rate",
    # Player Trajectory (34-36) - Session 28 model degradation fix
    "pts_slope_10g", "pts_vs_season_zscore", "breakout_flag",
]

# Feature count for backward compatibility queries
FEATURE_COUNT_V33 = 33  # Legacy (pre-dnp_rate)
FEATURE_COUNT_V34 = 34  # V2.1 with dnp_rate
FEATURE_COUNT_V37 = 37  # V2.37 with trajectory features (current)


def get_training_query(train_start: str, train_end: str, min_feature_count: int = 33) -> str:
    """
    Generate BigQuery SQL for fetching training data.

    The feature store (ml_feature_store_v2) contains feature vectors.
    We join with actuals to get the target variable.

    Args:
        train_start: Training start date (YYYY-MM-DD)
        train_end: Training end date (YYYY-MM-DD)
        min_feature_count: Minimum feature count to accept (default: 33 for backwards compat)
                          Use 37 for v2_37features with trajectory features

    Note: When using feature_count > 33, make sure training data has been backfilled
          with the new features. Historical data may only have 33-34 features.
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
  AND mf.feature_count >= {min_feature_count}
  AND ARRAY_LENGTH(mf.features) >= {min_feature_count}
  AND pgs.points IS NOT NULL
ORDER BY mf.game_date
"""


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict, list]:
    """
    Prepare feature matrix from raw dataframe.

    The feature store contains feature vectors. This function unpacks them
    and handles variable feature counts (33, 34, or 37 features).

    Returns:
        X: Feature matrix
        y: Target values (actual_points)
        medians: Median values for imputation (to be saved and used at inference)
        feature_names: List of feature names used (depends on data)
    """
    # Detect feature count from data
    sample_features = df.iloc[0]['features']
    actual_feature_count = len(sample_features)

    # Use appropriate feature names based on count
    if actual_feature_count >= 37:
        feature_names = ALL_FEATURES[:37]
    elif actual_feature_count >= 34:
        feature_names = ALL_FEATURES[:34]
    else:
        feature_names = ALL_FEATURES[:33]

    print(f"Detected {actual_feature_count} features in data, using {len(feature_names)} feature names")

    # Unpack features array into DataFrame with named columns
    # Truncate features to match feature_names length in case of mismatch
    X = pd.DataFrame(
        [row[:len(feature_names)] for row in df['features'].tolist()],
        columns=feature_names
    )

    # Calculate medians before imputation for saving
    medians = X.median().to_dict()

    # Fill any NaN values with median
    X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    return X, y, medians, feature_names


def train_catboost_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    sample_weight: np.ndarray = None,
    verbose: bool = False
) -> cb.CatBoostRegressor:
    """
    Train CatBoost model with V8 hyperparameters

    Uses the same hyperparameters as production V8 for fair comparison.

    Args:
        X_train: Training features
        y_train: Training targets
        X_val: Validation features
        y_val: Validation targets
        sample_weight: Optional array of sample weights for training data
        verbose: Show training progress
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
    model.fit(X_train, y_train, eval_set=(X_val, y_val), sample_weight=sample_weight)
    return model


def load_config_from_yaml(config_path: str) -> dict:
    """Load experiment configuration from YAML file."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config


def main():
    parser = argparse.ArgumentParser(description="Train CatBoost V8 model for walk-forward experiments")
    parser.add_argument("--train-start", help="Training start date (YYYY-MM-DD)")
    parser.add_argument("--train-end", help="Training end date (YYYY-MM-DD)")
    parser.add_argument("--experiment-id", help="Experiment identifier (e.g., A1, B2)")
    parser.add_argument("--verbose", action="store_true", help="Show training progress")
    parser.add_argument("--use-recency-weights", action="store_true",
                       help="Apply exponential recency weighting to training samples")
    parser.add_argument("--half-life", type=int, default=180,
                       help="Half-life for recency decay in days (default: 180 = 6 months)")
    # New arguments for config and registry
    parser.add_argument("--config", help="Path to YAML config file")
    parser.add_argument("--no-registry", action="store_true",
                       help="Disable experiment registry (skip BigQuery tracking)")
    parser.add_argument("--name", help="Experiment name (for registry)")
    parser.add_argument("--hypothesis", help="Experiment hypothesis (for registry)")
    args = parser.parse_args()

    # Load config from YAML if provided
    if args.config:
        config = load_config_from_yaml(args.config)
        # Override args with config values (command line takes precedence)
        if not args.train_start and 'train_start' in config:
            args.train_start = config['train_start']
        if not args.train_end and 'train_end' in config:
            args.train_end = config['train_end']
        if not args.experiment_id and 'experiment_id' in config:
            args.experiment_id = config['experiment_id']
        if not args.name and 'name' in config:
            args.name = config['name']
        if not args.hypothesis and 'hypothesis' in config:
            args.hypothesis = config['hypothesis']
        if 'use_recency_weights' in config and not args.use_recency_weights:
            args.use_recency_weights = config['use_recency_weights']
        if 'half_life' in config:
            args.half_life = config['half_life']
        if 'verbose' in config and not args.verbose:
            args.verbose = config['verbose']

    # Validate required arguments
    if not args.train_start or not args.train_end or not args.experiment_id:
        parser.error("--train-start, --train-end, and --experiment-id are required "
                    "(either via command line or --config)")

    # Initialize registry if enabled
    registry: Optional[ExperimentRegistry] = None
    if not args.no_registry:
        try:
            registry = ExperimentRegistry()
        except Exception as e:
            print(f"Warning: Could not initialize experiment registry: {e}")
            print("Continuing without registry...")

    # Get git commit for tracking
    git_commit = get_git_commit()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_name = f"catboost_v9_exp_{args.experiment_id}_{timestamp}"

    print("=" * 80)
    print(f" WALK-FORWARD TRAINING: Experiment {args.experiment_id}")
    print("=" * 80)
    print(f"Training period: {args.train_start} to {args.train_end}")
    print(f"Model name: {model_name}")
    if git_commit:
        print(f"Git commit: {git_commit}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Build config for registry
    experiment_config = {
        "train_start": args.train_start,
        "train_end": args.train_end,
        "use_recency_weights": args.use_recency_weights,
        "half_life": args.half_life if args.use_recency_weights else None,
        "model_name": model_name,
        "git_commit": git_commit,
    }

    # Register experiment
    if registry:
        try:
            registry.register(
                experiment_id=args.experiment_id,
                name=args.name or f"Walk-forward training {args.experiment_id}",
                hypothesis=args.hypothesis or "",
                test_type="walkforward",
                config=experiment_config
            )
            registry.update_status(args.experiment_id, "running")
        except Exception as e:
            print(f"Warning: Could not register experiment: {e}")

    # Wrap training in try/except for registry error handling
    try:
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
        X, y, medians, feature_names_used = prepare_features(df)
        print(f"Features: {X.shape[1]} ({feature_names_used[-1]} ... last feature)")

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

        # Calculate sample weights if requested
        sample_weights = None
        if args.use_recency_weights:
            print(f"\nCalculating recency weights (half-life: {args.half_life} days)...")
            # Need to get dates for training samples
            train_dates = df_sorted.iloc[:split_idx]['game_date']
            sample_weights = calculate_sample_weights(train_dates, args.half_life)

            # Log weight statistics
            print(f"Weight stats: min={sample_weights.min():.4f}, max={sample_weights.max():.4f}, "
                  f"mean={sample_weights.mean():.4f}, std={sample_weights.std():.4f}")

            # Show weight at different ages
            ages_to_show = [0, 30, 90, 180, 365, 730]
            print("Weight by sample age:")
            decay_rate = np.log(2) / args.half_life
            for age in ages_to_show:
                weight = np.exp(-age * decay_rate)
                print(f"  {age:3d} days old: weight = {weight:.4f}")

        # Train model
        print("\nTraining CatBoost...")
        model = train_catboost_model(X_train, y_train, X_val, y_val,
                                      sample_weight=sample_weights, verbose=args.verbose)

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
            "git_commit": git_commit,
            "train_period": {
                "start": args.train_start,
                "end": args.train_end,
                "actual_start": str(actual_start),
                "actual_end": str(actual_end),
                "samples": len(df),
            },
            "features": feature_names_used,
            "feature_count": len(feature_names_used),
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
            "recency_weighting": {
                "enabled": args.use_recency_weights,
                "half_life_days": args.half_life if args.use_recency_weights else None,
                "weight_stats": {
                    "min": float(sample_weights.min()) if sample_weights is not None else None,
                    "max": float(sample_weights.max()) if sample_weights is not None else None,
                    "mean": float(sample_weights.mean()) if sample_weights is not None else None,
                    "std": float(sample_weights.std()) if sample_weights is not None else None,
                } if sample_weights is not None else None,
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

        # Complete experiment in registry
        if registry:
            try:
                registry.complete(
                    experiment_id=args.experiment_id,
                    results={
                        "validation_mae": float(val_mae),
                        "full_training_mae": float(full_mae),
                        "best_iteration": best_iter,
                        "sample_size": len(df),
                        "feature_count": len(feature_names_used),
                    },
                    model_path=str(model_path)
                )
            except Exception as e:
                print(f"Warning: Could not complete experiment in registry: {e}")

        # Summary
        print("\n" + "=" * 80)
        print("TRAINING COMPLETE")
        print("=" * 80)

        recency_info = ""
        if args.use_recency_weights:
            recency_info = f"\nRecency weighting: ENABLED (half-life: {args.half_life} days)"
        else:
            recency_info = "\nRecency weighting: DISABLED"

        print(f"""
Experiment: {args.experiment_id}
Model: {model_name}
Training samples: {len(df):,}
Training period: {args.train_start} to {args.train_end}{recency_info}
Validation MAE: {val_mae:.4f}

Files created:
  - {model_path}
  - {metadata_path}

Next step: Run evaluation with ml/experiments/evaluate_model.py
""")

        return metadata

    except Exception as e:
        # Mark experiment as failed in registry
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"\nERROR: Training failed - {error_msg}")
        traceback.print_exc()

        if registry:
            try:
                registry.fail(args.experiment_id, error_msg)
            except Exception as reg_err:
                print(f"Warning: Could not mark experiment as failed in registry: {reg_err}")

        raise


if __name__ == "__main__":
    main()
