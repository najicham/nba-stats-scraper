#!/usr/bin/env python3
"""
XGBoost V1 Production Training Script - Option D Phase 5A

This script trains the production XGBoost V1 model for NBA player points prediction.
Replaces the mock_xgboost_model with a real trained model.

Features:
- 33 features from ml_feature_store_v2 (v2_33features)
- Chronological train/validation split to prevent data leakage
- Early stopping on validation MAE
- Model versioning and GCS upload
- Comprehensive metrics and metadata tracking

Target Performance:
- Training MAE: ≤ 4.0 points
- Validation MAE: ≤ 4.5 points
- Better than mock model (~4.8 MAE)

Usage:
    # Local training (uses available historical data)
    PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py

    # With GCS upload
    PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py --upload-gcs

    # Specify date range
    PYTHONPATH=. python ml_models/nba/train_xgboost_v1.py --start-date 2021-11-01 --end-date 2024-06-01

Environment Variables:
    GCP_PROJECT_ID: GCP project (default: nba-props-platform)
    GCS_MODEL_BUCKET: GCS bucket for models (default: nba-ml-models)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import json
import os
from datetime import datetime
from typing import Dict, Tuple, List

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery, storage
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Configuration (from environment variables with defaults)
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
GCS_MODEL_BUCKET = os.environ.get('GCS_MODEL_BUCKET', 'nba-ml-models')
MODEL_OUTPUT_DIR = Path("models")
MODEL_OUTPUT_DIR.mkdir(exist_ok=True)

# Feature configuration - must match ml_feature_store_v2
FEATURE_VERSION = "v2_33features"
EXPECTED_FEATURE_COUNT = 33

BASE_FEATURE_NAMES = [
    "points_avg_last_5", "points_avg_last_10", "points_avg_season",
    "points_std_last_10", "games_in_last_7_days", "fatigue_score",
    "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
    "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
    "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
    "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
    "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct"
]

VEGAS_FEATURE_NAMES = [
    "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"
]

OPPONENT_FEATURE_NAMES = [
    "avg_points_vs_opponent", "games_vs_opponent"
]

MINUTES_FEATURE_NAMES = [
    "minutes_avg_last_10", "ppm_avg_last_10"
]

ALL_FEATURE_NAMES = (
    BASE_FEATURE_NAMES +
    VEGAS_FEATURE_NAMES +
    OPPONENT_FEATURE_NAMES +
    MINUTES_FEATURE_NAMES
)

# XGBoost hyperparameters (proven from v7)
XGBOOST_PARAMS = {
    'max_depth': 6,
    'min_child_weight': 10,
    'learning_rate': 0.03,
    'n_estimators': 1000,
    'subsample': 0.7,
    'colsample_bytree': 0.7,
    'colsample_bylevel': 0.7,
    'gamma': 0.1,
    'reg_alpha': 0.5,
    'reg_lambda': 5.0,
    'random_state': 42,
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'early_stopping_rounds': 50
}


def print_section(title: str):
    """Print formatted section header"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def load_training_data(
    client: bigquery.Client,
    start_date: str = "2021-11-01",
    end_date: str = "2024-06-01"
) -> pd.DataFrame:
    """
    Load training data from BigQuery.

    The ml_feature_store_v2 with feature_version='v2_33features' already contains
    all 33 features (base + Vegas + opponent + minutes/PPM) in the features array.

    We just need to join with actual points for the target variable.

    Returns DataFrame with features array and actual_points
    """
    print_section("STEP 1: LOADING DATA FROM BIGQUERY")

    print(f"Date range: {start_date} to {end_date}")
    print(f"Feature version: {FEATURE_VERSION} (all 33 features)")
    print("Querying BigQuery (this may take 1-2 minutes)...")

    query = f"""
    WITH
    -- Features from ml_feature_store_v2 (already includes all 33 features)
    feature_data AS (
      SELECT
        mf.player_lookup,
        mf.game_date,
        mf.features,
        mf.feature_count,
        mf.feature_version
      FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
      WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND mf.feature_version = '{FEATURE_VERSION}'
        AND mf.feature_count = {EXPECTED_FEATURE_COUNT}
        AND ARRAY_LENGTH(mf.features) = {EXPECTED_FEATURE_COUNT}
    ),

    -- Actual points (target variable)
    actuals AS (
      SELECT
        player_lookup,
        game_date,
        points as actual_points
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        AND points IS NOT NULL
    )

    SELECT
      fd.player_lookup,
      fd.game_date,
      fd.features,
      fd.feature_count,
      fd.feature_version,
      a.actual_points

    FROM feature_data fd
    INNER JOIN actuals a
      ON fd.player_lookup = a.player_lookup
      AND fd.game_date = a.game_date

    ORDER BY fd.game_date, fd.player_lookup
    """

    df = client.query(query).to_dataframe()

    print(f"\nLoaded {len(df):,} player-game samples")
    print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"Unique players: {df['player_lookup'].nunique()}")
    print(f"Features per sample: {df['feature_count'].iloc[0]}")

    return df


def prepare_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Prepare feature matrix and target vector.

    The ml_feature_store_v2 with v2_33features already contains all 33 features
    in the correct order in the features array. We just extract them.

    Returns (X, y) where X has 33 features and y is actual_points
    """
    print_section("STEP 2: PREPARING FEATURES")

    # Extract all 33 features from array
    print("Extracting 33 features from ml_feature_store_v2...")
    X = pd.DataFrame(df['features'].tolist(), columns=ALL_FEATURE_NAMES)
    y = df['actual_points'].astype(float)

    # Check for nulls (should be rare since feature store handles imputation)
    null_counts = X.isnull().sum()
    if null_counts.sum() > 0:
        print(f"\nWarning: Found {null_counts.sum()} null values, filling with median:")
        for col in null_counts[null_counts > 0].index:
            print(f"  {col}: {null_counts[col]}")
        X = X.fillna(X.median())
    else:
        print("No null values found!")

    print(f"\nFeature matrix shape: {X.shape}")
    print(f"Target vector shape: {y.shape}")
    print(f"\nFeature breakdown:")
    print(f"  Base features: {len(BASE_FEATURE_NAMES)}")
    print(f"  Vegas features: {len(VEGAS_FEATURE_NAMES)}")
    print(f"  Opponent features: {len(OPPONENT_FEATURE_NAMES)}")
    print(f"  Minutes/PPM features: {len(MINUTES_FEATURE_NAMES)}")
    print(f"  Total: {len(ALL_FEATURE_NAMES)}")

    # Basic statistics
    print(f"\nFeature statistics:")
    print(f"  Mean: {X.mean().mean():.2f}")
    print(f"  Std: {X.std().mean():.2f}")
    print(f"  Target (points) mean: {y.mean():.2f}")
    print(f"  Target (points) std: {y.std():.2f}")

    return X, y


def split_data_chronologically(
    X: pd.DataFrame,
    y: pd.Series,
    df: pd.DataFrame,
    train_pct: float = 0.80,
    val_pct: float = 0.20
) -> Tuple:
    """
    Split data chronologically to prevent data leakage.

    Important: Train/val split by date, NOT random sampling.
    This ensures validation set uses only future data.

    Returns (X_train, X_val, y_train, y_val, train_dates, val_dates)
    """
    print_section("STEP 3: CHRONOLOGICAL TRAIN/VALIDATION SPLIT")

    # Sort by date
    df_sorted = df.sort_values('game_date').reset_index(drop=True)
    X = X.iloc[df_sorted.index].reset_index(drop=True)
    y = y.iloc[df_sorted.index].reset_index(drop=True)

    # Split indices
    n = len(df_sorted)
    train_end = int(n * train_pct)

    train_idx = range(train_end)
    val_idx = range(train_end, n)

    X_train, y_train = X.iloc[train_idx], y.iloc[train_idx]
    X_val, y_val = X.iloc[val_idx], y.iloc[val_idx]

    train_dates = df_sorted.iloc[train_idx]
    val_dates = df_sorted.iloc[val_idx]

    print(f"Training set:   {len(X_train):,} samples")
    print(f"  Date range: {train_dates['game_date'].min()} to {train_dates['game_date'].max()}")

    print(f"\nValidation set: {len(X_val):,} samples")
    print(f"  Date range: {val_dates['game_date'].min()} to {val_dates['game_date'].max()}")

    print(f"\nSplit ratio: {train_pct:.0%} train, {val_pct:.0%} validation")

    # Show Vegas coverage from features (feature index 28 is has_vegas_line)
    train_vegas_coverage = X_train.iloc[:, 28].mean()  # has_vegas_line feature
    val_vegas_coverage = X_val.iloc[:, 28].mean()
    print(f"\nVegas line coverage:")
    print(f"  Train: {train_vegas_coverage:.1%}")
    print(f"  Val: {val_vegas_coverage:.1%}")

    return X_train, X_val, y_train, y_val, train_dates, val_dates


def train_model(X_train, X_val, y_train, y_val) -> xgb.XGBRegressor:
    """Train XGBoost model with early stopping on validation set"""
    print_section("STEP 4: TRAINING XGBOOST V1")

    print("Hyperparameters:")
    for key, value in XGBOOST_PARAMS.items():
        if key not in ['eval_metric', 'objective', 'early_stopping_rounds']:
            print(f"  {key}: {value}")

    print(f"\nTraining with {len(ALL_FEATURE_NAMES)} features...")
    print("Early stopping: 50 rounds on validation MAE\n")

    model = xgb.XGBRegressor(**XGBOOST_PARAMS)

    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        verbose=50  # Print every 50 rounds
    )

    print(f"\nTraining complete!")
    print(f"Best iteration: {model.best_iteration}")
    print(f"Best validation MAE: {model.best_score:.4f}")

    return model


def evaluate_model(model, X_train, X_val, y_train, y_val) -> Dict:
    """Evaluate model performance on train and validation sets"""
    print_section("STEP 5: MODEL EVALUATION")

    train_pred = model.predict(X_train)
    val_pred = model.predict(X_val)

    results = {}

    for name, y_true, y_pred in [
        ("Training", y_train, train_pred),
        ("Validation", y_val, val_pred)
    ]:
        mae = mean_absolute_error(y_true, y_pred)
        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        errors = np.abs(y_true - y_pred)
        within_3 = (errors <= 3).mean() * 100
        within_5 = (errors <= 5).mean() * 100

        results[name.lower()] = {
            'mae': float(mae),
            'rmse': float(rmse),
            'within_3_pct': float(within_3),
            'within_5_pct': float(within_5)
        }

        print(f"\n{name} Set:")
        print(f"  MAE:  {mae:.3f} points")
        print(f"  RMSE: {rmse:.3f} points")
        print(f"  Within 3 pts: {within_3:.1f}%")
        print(f"  Within 5 pts: {within_5:.1f}%")

    train_val_gap = results['validation']['mae'] - results['training']['mae']
    print(f"\nTrain/Validation Gap: {train_val_gap:.3f} points")
    results['train_val_gap'] = float(train_val_gap)

    return results


def compare_to_baselines(results: Dict):
    """Compare model performance to baselines"""
    print_section("STEP 6: COMPARISON TO BASELINES")

    MOCK_V1_MAE = 4.80
    MOCK_V2_MAE = 4.50  # Improved mock
    CATBOOST_V8_MAE = 3.40  # Current champion

    val_mae = results['validation']['mae']

    print(f"\n{'Model':<25} {'MAE':>8} {'vs Mock V1':>12} {'vs V8':>12}")
    print("-" * 60)
    print(f"{'Mock XGBoost V1':<25} {MOCK_V1_MAE:>8.2f} {'baseline':>12} {'+41.2%':>12}")
    print(f"{'Mock XGBoost V2':<25} {MOCK_V2_MAE:>8.2f} {'-6.3%':>12} {'+32.4%':>12}")
    print(f"{'CatBoost V8 (best)':<25} {CATBOOST_V8_MAE:>8.2f} {'-29.2%':>12} {'baseline':>12}")

    vs_mock = ((MOCK_V1_MAE - val_mae) / MOCK_V1_MAE) * 100
    vs_v8 = ((CATBOOST_V8_MAE - val_mae) / CATBOOST_V8_MAE) * 100

    print(f"{'XGBoost V1 (NEW)':<25} {val_mae:>8.2f} {vs_mock:>+11.1f}% {vs_v8:>+11.1f}%")

    print(f"\n" + "=" * 60)
    if val_mae < MOCK_V1_MAE:
        print(f"✓ SUCCESS: Beats Mock V1 by {MOCK_V1_MAE - val_mae:.3f} MAE ({vs_mock:+.1f}%)")
    else:
        print(f"✗ FAILURE: Worse than Mock V1 by {val_mae - MOCK_V1_MAE:.3f} MAE")

    if val_mae <= 4.5:
        print(f"✓ TARGET MET: Validation MAE ≤ 4.5 ({val_mae:.3f})")
    else:
        print(f"✗ TARGET MISSED: Validation MAE > 4.5 ({val_mae:.3f})")


def analyze_feature_importance(model):
    """Analyze and display feature importance"""
    print_section("STEP 7: FEATURE IMPORTANCE ANALYSIS")

    importance = model.feature_importances_
    feat_imp = pd.DataFrame({
        'feature': ALL_FEATURE_NAMES,
        'importance': importance
    }).sort_values('importance', ascending=False)

    print(f"\n{'Rank':<5} {'Feature':<30} {'Importance':>10} {'Type':>12}")
    print("-" * 62)

    for rank, (_, row) in enumerate(feat_imp.head(20).iterrows(), 1):
        feat = row['feature']

        if feat in VEGAS_FEATURE_NAMES:
            feat_type = "Vegas"
        elif feat in OPPONENT_FEATURE_NAMES:
            feat_type = "Opponent"
        elif feat in MINUTES_FEATURE_NAMES:
            feat_type = "Minutes/PPM"
        else:
            feat_type = "Base"

        print(f"{rank:<5} {feat:<30} {row['importance']*100:>9.1f}% {feat_type:>12}")

    return feat_imp


def save_model(
    model: xgb.XGBRegressor,
    results: Dict,
    feat_imp: pd.DataFrame,
    df: pd.DataFrame,
    upload_gcs: bool = False
) -> Tuple[Path, Path]:
    """Save model and metadata to disk and optionally GCS"""
    print_section("STEP 8: SAVING MODEL")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_id = f"xgboost_v1_33features_{timestamp}"

    # Save model
    model_path = MODEL_OUTPUT_DIR / f"{model_id}.json"
    model.get_booster().save_model(str(model_path))
    print(f"Model saved: {model_path}")

    # Create metadata
    metadata = {
        'model_id': model_id,
        'version': 'v1',
        'model_type': 'xgboost',
        'trained_at': datetime.now().isoformat(),
        'training_samples': len(df),
        'feature_version': FEATURE_VERSION,
        'features': ALL_FEATURE_NAMES,
        'feature_count': len(ALL_FEATURE_NAMES),
        'hyperparameters': XGBOOST_PARAMS,
        'best_iteration': int(model.best_iteration),
        'results': results,
        'feature_importance_top10': [
            {'feature': row['feature'], 'importance': float(row['importance'])}
            for _, row in feat_imp.head(10).iterrows()
        ],
        'date_range': {
            'start': str(df['game_date'].min()),
            'end': str(df['game_date'].max())
        },
        'baselines': {
            'mock_v1_mae': 4.80,
            'mock_v2_mae': 4.50,
            'catboost_v8_mae': 3.40
        }
    }

    metadata_path = MODEL_OUTPUT_DIR / f"{model_id}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"Metadata saved: {metadata_path}")

    # Upload to GCS if requested
    if upload_gcs:
        print("\nUploading to GCS...")
        try:
            storage_client = storage.Client(project=PROJECT_ID)
            bucket_name = GCS_MODEL_BUCKET
            bucket = storage_client.bucket(bucket_name)

            # Upload model
            model_blob = bucket.blob(f"xgboost_v1/{model_id}.json")
            model_blob.upload_from_filename(str(model_path))
            print(f"  Model uploaded: gs://{bucket_name}/xgboost_v1/{model_id}.json")

            # Upload metadata
            metadata_blob = bucket.blob(f"xgboost_v1/{model_id}_metadata.json")
            metadata_blob.upload_from_filename(str(metadata_path))
            print(f"  Metadata uploaded: gs://{bucket_name}/xgboost_v1/{model_id}_metadata.json")

            metadata['gcs_paths'] = {
                'model': f"gs://{bucket_name}/xgboost_v1/{model_id}.json",
                'metadata': f"gs://{bucket_name}/xgboost_v1/{model_id}_metadata.json"
            }

            # Re-save metadata with GCS paths
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2, default=str)

        except Exception as e:
            print(f"  Warning: GCS upload failed: {e}")
            print("  Model saved locally only")

    return model_path, metadata_path


def main():
    parser = argparse.ArgumentParser(description='Train XGBoost V1 production model')
    parser.add_argument('--start-date', default='2021-11-01', help='Training start date')
    parser.add_argument('--end-date', default='2024-06-01', help='Training end date')
    parser.add_argument('--upload-gcs', action='store_true', help='Upload model to GCS')
    args = parser.parse_args()

    print("=" * 80)
    print(" XGBOOST V1 PRODUCTION TRAINING - OPTION D PHASE 5A")
    print("=" * 80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Project: {PROJECT_ID}")
    print(f"Feature version: {FEATURE_VERSION}")
    print()

    # Initialize BigQuery client
    client = bigquery.Client(project=PROJECT_ID)

    # Step 1: Load data
    df = load_training_data(client, args.start_date, args.end_date)

    # Step 2: Prepare features
    X, y = prepare_features(df)

    # Step 3: Split data chronologically
    X_train, X_val, y_train, y_val, train_dates, val_dates = split_data_chronologically(X, y, df)

    # Step 4: Train model
    model = train_model(X_train, X_val, y_train, y_val)

    # Step 5: Evaluate
    results = evaluate_model(model, X_train, X_val, y_train, y_val)

    # Step 6: Compare to baselines
    compare_to_baselines(results)

    # Step 7: Feature importance
    feat_imp = analyze_feature_importance(model)

    # Step 8: Save model
    model_path, metadata_path = save_model(model, results, feat_imp, df, args.upload_gcs)

    # Final summary
    print_section("TRAINING COMPLETE - SUMMARY")

    print(f"""
Model ID: {model_path.stem}
Training samples: {len(df):,}
Features: {len(ALL_FEATURE_NAMES)} ({FEATURE_VERSION})
Date range: {args.start_date} to {args.end_date}

Performance:
  Training MAE:   {results['training']['mae']:.3f}
  Validation MAE: {results['validation']['mae']:.3f}
  Train/Val Gap:  {results['train_val_gap']:.3f}

Files:
  Model:    {model_path}
  Metadata: {metadata_path}
    """)

    val_mae = results['validation']['mae']
    if val_mae <= 4.5:
        print("✓ SUCCESS: Model meets production criteria (MAE ≤ 4.5)")
        print("\nNext steps:")
        print("  1. Update prediction worker to load this model")
        print("  2. Test predictions in staging")
        print("  3. Deploy to production")
    else:
        print(f"⚠ WARNING: Model MAE ({val_mae:.3f}) exceeds target (4.5)")
        print("  Consider: More training data, feature engineering, or hyperparameter tuning")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
