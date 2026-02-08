#!/usr/bin/env python3
"""
Trajectory Features Experiment

Tests whether adding trajectory features (pts_slope_10g, pts_vs_season_zscore, breakout_flag)
improves model performance compared to the 33-feature baseline.

Features tested:
- pts_slope_10g: 10-game scoring trend (positive = improving)
- pts_vs_season_zscore: Points z-score vs season average
- breakout_flag: Binary indicator for recent breakout performance

Usage:
    PYTHONPATH=. python ml/experiments/train_trajectory_test.py

Output:
    - Models saved to models/
    - Results compared to 33-feature baseline
    - Evaluation on held-out test set

Session 58 - Testing trajectory features
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
from sklearn.model_selection import train_test_split
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

# Feature names for 33 and 37 feature variants
FEATURES_33 = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days",
    "fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back", "playoff_game",
    "pct_paint", "pct_mid_range", "pct_three", "pct_free_throw",
    "team_pace", "team_off_rating", "team_win_pct",
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
    "avg_points_vs_opponent", "games_vs_opponent",
    "minutes_avg_last_10", "ppm_avg_last_10",
]

FEATURES_37 = FEATURES_33 + [
    "dnp_rate",
    "pts_slope_10g", "pts_vs_season_zscore", "breakout_flag",
]


def load_data(client: bigquery.Client, feature_count: int, train_start: str, train_end: str) -> pd.DataFrame:
    """Load training data from feature store."""
    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      mf.feature_count,
      pgs.points as actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    INNER JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{train_start}' AND '{train_end}'
      AND mf.feature_count >= {feature_count}
      AND ARRAY_LENGTH(mf.features) >= {feature_count}
      AND pgs.points IS NOT NULL
      AND pgs.minutes_played > 0
    ORDER BY mf.game_date
    """
    return client.query(query).to_dataframe()


def prepare_features(df: pd.DataFrame, feature_count: int) -> tuple:
    """Prepare feature matrix and targets."""
    feature_names = FEATURES_33 if feature_count == 33 else FEATURES_37

    # Unpack features array into DataFrame
    X = pd.DataFrame(
        [row[:feature_count] for row in df['features'].tolist()],
        columns=feature_names
    )

    # Handle missing values
    X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    return X, y, feature_names


def train_catboost(X_train, y_train, X_val, y_val, feature_names):
    """Train CatBoost model."""
    model = cb.CatBoostRegressor(
        iterations=1000,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=3,
        random_strength=0.5,
        bagging_temperature=0.5,
        random_seed=42,
        verbose=100,
        early_stopping_rounds=50,
    )

    model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        verbose=100
    )

    return model


def main():
    parser = argparse.ArgumentParser(description='Test trajectory features')
    parser.add_argument('--train-start', default='2025-11-01', help='Training start date')
    parser.add_argument('--train-end', default='2026-01-20', help='Training end date')
    parser.add_argument('--test-start', default='2026-01-21', help='Test start date')
    parser.add_argument('--test-end', default='2026-01-28', help='Test end date')
    args = parser.parse_args()

    print("=" * 80)
    print(" TRAJECTORY FEATURES EXPERIMENT")
    print("=" * 80)
    print(f"Training period: {args.train_start} to {args.train_end}")
    print(f"Test period: {args.test_start} to {args.test_end}")
    print()

    client = bigquery.Client(project=PROJECT_ID)
    results = {}

    for feature_count in [33, 37]:
        print("=" * 80)
        print(f" TRAINING {feature_count}-FEATURE MODEL")
        print("=" * 80)

        # Load training data
        print("Loading training data...")
        df_train = load_data(client, feature_count, args.train_start, args.train_end)
        print(f"Loaded {len(df_train):,} training samples")

        # Load test data
        print("Loading test data...")
        df_test = load_data(client, feature_count, args.test_start, args.test_end)
        print(f"Loaded {len(df_test):,} test samples")

        if len(df_train) < 1000:
            print(f"ERROR: Not enough training data ({len(df_train)} < 1000)")
            continue

        # Prepare features
        X_train_full, y_train_full, feature_names = prepare_features(df_train, feature_count)
        X_test, y_test, _ = prepare_features(df_test, feature_count)

        # Split training into train/validation
        X_train, X_val, y_train, y_val = train_test_split(
            X_train_full, y_train_full, test_size=0.15, random_state=42
        )

        print(f"Training: {len(X_train):,}, Validation: {len(X_val):,}, Test: {len(X_test):,}")

        # Train model
        print("\nTraining CatBoost...")
        model = train_catboost(X_train, y_train, X_val, y_val, feature_names)

        # Evaluate on test set
        print("\nEvaluating on test set...")
        test_preds = model.predict(X_test)
        test_mae = mean_absolute_error(y_test, test_preds)

        # Calculate betting metrics
        if 'vegas_points_line' in X_test.columns:
            lines = X_test['vegas_points_line'].values
            has_real = X_test['has_vegas_line'].values == 1.0

            # Filter to real lines only
            valid = has_real & ~np.isnan(lines)
            if valid.sum() > 0:
                v_preds = test_preds[valid]
                v_actual = y_test.values[valid]
                v_lines = lines[valid]

                edges = v_preds - v_lines
                over_bets = edges >= 1.0
                under_bets = edges <= -1.0
                bet_mask = over_bets | under_bets

                if bet_mask.sum() > 0:
                    b_actual = v_actual[bet_mask]
                    b_lines = v_lines[bet_mask]
                    b_over = over_bets[bet_mask]

                    over_wins = (b_actual > b_lines) & b_over
                    under_wins = (b_actual < b_lines) & ~b_over
                    hits = (over_wins | under_wins).sum()
                    pushes = (b_actual == b_lines).sum()
                    graded = len(b_actual) - pushes
                    hit_rate = hits / graded if graded > 0 else 0
        else:
            hit_rate = None

        # Get feature importance for trajectory features
        importance = dict(zip(feature_names, model.feature_importances_))
        trajectory_importance = {
            k: v for k, v in importance.items()
            if k in ['pts_slope_10g', 'pts_vs_season_zscore', 'breakout_flag', 'dnp_rate']
        }

        # Store results
        results[f'{feature_count}_features'] = {
            'test_mae': round(test_mae, 4),
            'test_samples': len(X_test),
            'hit_rate': round(hit_rate * 100, 2) if hit_rate else None,
            'trajectory_importance': trajectory_importance if feature_count == 37 else {},
        }

        print(f"\n--- {feature_count} Features Results ---")
        print(f"Test MAE: {test_mae:.4f}")
        if hit_rate:
            print(f"Hit Rate: {hit_rate*100:.2f}%")

        if trajectory_importance:
            print("\nTrajectory Feature Importance:")
            for feat, imp in sorted(trajectory_importance.items(), key=lambda x: -x[1]):
                print(f"  {feat}: {imp:.4f}")

        # Save model
        model_path = MODEL_OUTPUT_DIR / f"catboost_trajectory_test_{feature_count}f_{datetime.now().strftime('%Y%m%d_%H%M%S')}.cbm"
        model.save_model(str(model_path))
        print(f"\nModel saved: {model_path}")

    # Summary comparison
    print("\n" + "=" * 80)
    print(" COMPARISON SUMMARY")
    print("=" * 80)

    if '33_features' in results and '37_features' in results:
        r33 = results['33_features']
        r37 = results['37_features']

        mae_diff = r37['test_mae'] - r33['test_mae']
        mae_pct = (mae_diff / r33['test_mae']) * 100

        print(f"33-feature MAE: {r33['test_mae']:.4f}")
        print(f"37-feature MAE: {r37['test_mae']:.4f}")
        print(f"Difference: {mae_diff:+.4f} ({mae_pct:+.2f}%)")

        if r33.get('hit_rate') and r37.get('hit_rate'):
            hr_diff = r37['hit_rate'] - r33['hit_rate']
            print(f"\n33-feature Hit Rate: {r33['hit_rate']:.2f}%")
            print(f"37-feature Hit Rate: {r37['hit_rate']:.2f}%")
            print(f"Difference: {hr_diff:+.2f}%")

        if mae_diff < 0:
            print("\n✅ Trajectory features IMPROVED model (lower MAE)")
        else:
            print("\n⚠️ Trajectory features did not improve model")

    # Save results
    results_path = Path("ml/experiments/results") / f"trajectory_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {results_path}")


if __name__ == "__main__":
    main()
