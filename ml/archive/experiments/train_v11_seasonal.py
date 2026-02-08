#!/usr/bin/env python3
"""
V11 Seasonal Features Training Script

Tests the hypothesis that seasonal patterns (All-Star effects, time-of-season)
improve predictions. Adds 4-6 seasonal features to V8's 33-feature baseline.

This script calculates seasonal features at training time from game_date,
avoiding feature store modifications for rapid experimentation.

Features Added:
    - week_of_season: Weeks since season start (0-42)
    - pct_season_completed: Fraction of season elapsed (0.0-1.0)
    - days_to_all_star: Days until All-Star break (negative after)
    - is_post_all_star: Boolean flag for post-All-Star games

Usage:
    # V11 baseline experiment (seasonal features, no recency)
    PYTHONPATH=. python ml/experiments/train_v11_seasonal.py \
        --train-start 2021-11-01 \
        --train-end 2025-12-31 \
        --experiment-id V11_SEASONAL_A1 \
        --verbose

    # Compare with V8 baseline (no seasonal features)
    PYTHONPATH=. python ml/experiments/train_v11_seasonal.py \
        --train-start 2021-11-01 \
        --train-end 2025-12-31 \
        --experiment-id V11_BASELINE_A1 \
        --no-seasonal \
        --verbose
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
import json
from datetime import datetime, date
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path(__file__).parent / "results"

# All-Star Sunday dates by season year
# Season year is when the season starts (e.g., 2024 for 2024-25 season)
ALL_STAR_DATES = {
    2021: date(2022, 2, 20),  # 2021-22 season
    2022: date(2023, 2, 19),  # 2022-23 season
    2023: date(2024, 2, 18),  # 2023-24 season
    2024: date(2025, 2, 16),  # 2024-25 season
    2025: date(2026, 2, 15),  # 2025-26 season (estimated)
}

# Season start dates (fallback if shared config unavailable)
SEASON_START_DATES = {
    2021: date(2021, 10, 19),
    2022: date(2022, 10, 18),
    2023: date(2023, 10, 24),
    2024: date(2024, 10, 22),
    2025: date(2025, 10, 21),  # Estimated
}


def get_season_year(game_date: date) -> int:
    """Determine season year from game date."""
    if game_date.month >= 10:
        return game_date.year
    else:
        return game_date.year - 1


def get_season_start(season_year: int) -> date:
    """Get season start date."""
    try:
        from shared.config.nba_season_dates import get_season_start_date
        return get_season_start_date(season_year)
    except ImportError:
        return SEASON_START_DATES.get(season_year, date(season_year, 10, 22))


def get_all_star_date(season_year: int) -> date:
    """Get All-Star Sunday date for a season."""
    return ALL_STAR_DATES.get(season_year, date(season_year + 1, 2, 17))


def calculate_seasonal_features(game_dates: pd.Series) -> pd.DataFrame:
    """
    Calculate seasonal features from game dates.

    Uses vectorized operations for performance with large datasets.

    Args:
        game_dates: Series of game dates

    Returns:
        DataFrame with seasonal feature columns
    """
    # Convert to datetime if needed
    dates = pd.to_datetime(game_dates)

    # Vectorized season year calculation
    # NBA seasons run Oct-Jun, so Oct-Dec = same year, Jan-Sep = previous year
    season_years = dates.dt.year.where(dates.dt.month >= 10, dates.dt.year - 1)

    # Pre-compute season starts and All-Star dates for each unique season
    unique_seasons = season_years.unique()
    season_start_map = {sy: SEASON_START_DATES.get(sy, date(sy, 10, 22)) for sy in unique_seasons}
    all_star_map = {sy: ALL_STAR_DATES.get(sy, date(sy + 1, 2, 17)) for sy in unique_seasons}

    # Map to each row
    season_starts = season_years.map(lambda sy: pd.Timestamp(season_start_map[sy]))
    all_star_dates = season_years.map(lambda sy: pd.Timestamp(all_star_map[sy]))

    # Calculate days
    days_into_season = (dates - season_starts).dt.days
    days_to_all_star = (all_star_dates - dates).dt.days

    # Build features DataFrame
    features = pd.DataFrame({
        'week_of_season': (days_into_season // 7).clip(lower=0),
        'pct_season_completed': (days_into_season / 250).clip(0, 1),
        'days_to_all_star': days_to_all_star,
        'is_post_all_star': (days_to_all_star < 0).astype(float),
    })

    return features


# V8 Feature names (33 features)
V8_FEATURES = [
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
]

# V11 adds 4 seasonal features
V11_SEASONAL_FEATURES = [
    "week_of_season",
    "pct_season_completed",
    "days_to_all_star",
    "is_post_all_star",
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


def prepare_features(df: pd.DataFrame, add_seasonal: bool = True) -> tuple:
    """
    Prepare feature matrix from raw dataframe.

    Args:
        df: Raw dataframe with features array and game_date
        add_seasonal: Whether to add seasonal features

    Returns:
        X: Feature matrix
        y: Target values
        medians: Median values for imputation
        feature_names: List of feature names
    """
    # Extract V8 features (first 33)
    X = pd.DataFrame(
        [row[:33] for row in df['features'].tolist()],
        columns=V8_FEATURES
    )

    feature_names = V8_FEATURES.copy()

    # Add seasonal features if requested
    if add_seasonal:
        seasonal_df = calculate_seasonal_features(df['game_date'])
        X = pd.concat([X, seasonal_df], axis=1)
        feature_names.extend(V11_SEASONAL_FEATURES)

    # Calculate medians before imputation
    medians = X.median().to_dict()

    # Fill NaN with median
    X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    return X, y, medians, feature_names


def train_catboost_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    verbose: bool = False
) -> cb.CatBoostRegressor:
    """Train CatBoost model with V8 hyperparameters."""
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
    parser = argparse.ArgumentParser(description="Train CatBoost V11 with seasonal features")
    parser.add_argument("--train-start", required=True, help="Training start date (YYYY-MM-DD)")
    parser.add_argument("--train-end", required=True, help="Training end date (YYYY-MM-DD)")
    parser.add_argument("--experiment-id", required=True, help="Experiment identifier")
    parser.add_argument("--verbose", action="store_true", help="Show training progress")
    parser.add_argument("--no-seasonal", action="store_true",
                       help="Disable seasonal features (for baseline comparison)")
    args = parser.parse_args()

    add_seasonal = not args.no_seasonal
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_name = f"catboost_v11_exp_{args.experiment_id}_{timestamp}"

    print("=" * 80)
    print(f" V11 SEASONAL TRAINING: Experiment {args.experiment_id}")
    print("=" * 80)
    print(f"Training period: {args.train_start} to {args.train_end}")
    print(f"Seasonal features: {'ENABLED' if add_seasonal else 'DISABLED (baseline)'}")
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
    X, y, medians, feature_names = prepare_features(df, add_seasonal=add_seasonal)
    print(f"Features: {X.shape[1]} (V8: 33 + Seasonal: {4 if add_seasonal else 0})")

    if add_seasonal:
        # Show seasonal feature stats
        print("\nSeasonal feature statistics:")
        for feat in V11_SEASONAL_FEATURES:
            print(f"  {feat}: min={X[feat].min():.2f}, max={X[feat].max():.2f}, mean={X[feat].mean():.2f}")

    # Sort by date for chronological split
    df_sorted = df.sort_values('game_date').reset_index(drop=True)
    X = X.iloc[df_sorted.index].reset_index(drop=True)
    y = y.iloc[df_sorted.index].reset_index(drop=True)

    # Split 85/15 for early stopping
    n = len(X)
    split_idx = int(n * 0.85)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"\nTrain: {len(X_train):,}, Validation: {len(X_val):,}")

    # Train model
    print("\nTraining CatBoost...")
    model = train_catboost_model(X_train, y_train, X_val, y_val, verbose=args.verbose)

    best_iter = model.get_best_iteration()
    print(f"Best iteration: {best_iter}")

    # Evaluate
    val_pred = model.predict(X_val)
    val_mae = mean_absolute_error(y_val, val_pred)
    print(f"Validation MAE: {val_mae:.4f}")

    full_pred = model.predict(X)
    full_mae = mean_absolute_error(y, full_pred)
    print(f"Full training MAE: {full_mae:.4f}")

    # Feature importance
    print("\nTop 10 Feature Importances:")
    importance = model.get_feature_importance()
    importance_df = pd.DataFrame({
        'feature': feature_names,
        'importance': importance
    }).sort_values('importance', ascending=False)
    for i, row in importance_df.head(10).iterrows():
        seasonal_marker = " (SEASONAL)" if row['feature'] in V11_SEASONAL_FEATURES else ""
        print(f"  {row['feature']}: {row['importance']:.2f}{seasonal_marker}")

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
        "version": "v11",
        "train_period": {
            "start": args.train_start,
            "end": args.train_end,
            "actual_start": str(actual_start),
            "actual_end": str(actual_end),
            "samples": len(df),
        },
        "features": feature_names,
        "feature_count": len(feature_names),
        "feature_medians": medians,
        "seasonal_features": {
            "enabled": add_seasonal,
            "features": V11_SEASONAL_FEATURES if add_seasonal else [],
        },
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
        "feature_importance": {
            row['feature']: float(row['importance'])
            for _, row in importance_df.iterrows()
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
Seasonal features: {'ENABLED (4 features)' if add_seasonal else 'DISABLED'}
Feature count: {len(feature_names)}
Validation MAE: {val_mae:.4f}

Files created:
  - {model_path}
  - {metadata_path}

Next steps:
  - Compare MAE to V8 baseline (4.0235 from V9 experiments)
  - If improved, create catboost_v11.py prediction system
""")


if __name__ == "__main__":
    main()
