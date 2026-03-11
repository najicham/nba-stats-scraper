#!/usr/bin/env python3
"""
Production Training Script: XGBoost V1 MLB Pitcher Strikeouts Regressor

Same 36-feature contract, data pipeline, and governance gates as CatBoost V2.
Adds model diversity to the MLB fleet.

Usage:
    PYTHONPATH=. python scripts/mlb/training/train_xgboost_v1.py \
        --training-end 2026-03-20 --window 120 --output-dir models/mlb/

    PYTHONPATH=. python scripts/mlb/training/train_xgboost_v1.py \
        --training-end 2025-09-28 --window 120 --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from google.cloud import bigquery
import xgboost as xgb

# Reuse shared components from CatBoost V2 training script
from scripts.mlb.training.train_regressor_v2 import (
    PROJECT_ID,
    FEATURE_COLS,
    GOVERNANCE,
    HOLDOUT_DAYS,
    load_data,
    verify_features,
    split_train_val,
    prepare_features,
    check_governance_gates,
    print_summary,
)

# XGBoost hyperparameters — conservative starting point matching CatBoost complexity
HYPERPARAMS = {
    'objective': 'reg:squarederror',
    'eval_metric': 'mae',
    'max_depth': 4,
    'learning_rate': 0.015,
    'n_estimators': 500,
    'reg_lambda': 10.0,        # L2 regularization
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'random_state': 42,
    'tree_method': 'hist',
    'verbosity': 0,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train XGBoost V1 MLB Pitcher Strikeouts Regressor"
    )
    parser.add_argument("--training-start", type=str, default=None)
    parser.add_argument("--training-end", type=str, default=None)
    parser.add_argument("--window", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default="models/mlb/")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_dates(args):
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


def train_model(X_train, y_train):
    """Train XGBoost regressor."""
    model = xgb.XGBRegressor(**HYPERPARAMS)
    model.fit(X_train, y_train)
    return model


def evaluate_model(model, val_df, feature_cols):
    """Evaluate model on validation set — same metrics as CatBoost."""
    X_val = prepare_features(val_df, feature_cols)
    y_actual = val_df['actual_value'].astype(float).values
    lines = val_df['over_line'].astype(float).values
    went_over = val_df['went_over'].astype(int).values

    predicted_k = model.predict(X_val)

    residuals = predicted_k - y_actual
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    bias = float(np.mean(residuals))

    edge = predicted_k - lines
    predicted_over = (edge > 0).astype(int)
    correct = (predicted_over == went_over).astype(int)
    overall_hr = float(correct.mean() * 100)
    over_rate = float(predicted_over.mean() * 100)

    abs_edge = np.abs(edge)
    edge_mask = abs_edge >= GOVERNANCE['edge_threshold']
    n_at_edge = int(edge_mask.sum())

    over_at_edge_mask = (edge >= GOVERNANCE['edge_threshold'])
    n_over_at_edge = int(over_at_edge_mask.sum())
    over_hr_at_edge = float(correct[over_at_edge_mask].mean() * 100) if n_over_at_edge > 0 else 0.0

    under_at_edge_mask = (edge <= -GOVERNANCE['edge_threshold'])
    n_under_at_edge = int(under_at_edge_mask.sum())
    under_hr_at_edge = float(correct[under_at_edge_mask].mean() * 100) if n_under_at_edge > 0 else 0.0

    hr_at_edge = float(correct[edge_mask].mean() * 100) if n_at_edge > 0 else 0.0

    return {
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


def main():
    args = parse_args()
    training_start, training_end = resolve_dates(args)

    print("=" * 70)
    print("  XGBoost V1 MLB Pitcher Strikeouts Regressor — Production Training")
    print("=" * 70)
    print(f"\n  Training window: {training_start.date()} to {training_end.date()}")
    print(f"  Features: {len(FEATURE_COLS)}")
    print(f"  Target: actual_value (raw strikeout count)")
    if args.dry_run:
        print(f"  DRY RUN — model will not be saved")
    print()

    client = bigquery.Client(project=PROJECT_ID)
    df = load_data(client, training_start, training_end)

    if len(df) == 0:
        print("\nFATAL: No data loaded.")
        sys.exit(1)

    feature_cols = verify_features(df)
    train_df, val_df = split_train_val(df, HOLDOUT_DAYS)

    if len(train_df) < 50:
        print(f"\nFATAL: Only {len(train_df)} training samples.")
        sys.exit(1)

    X_train = prepare_features(train_df, feature_cols)
    y_train = train_df['actual_value'].astype(float)

    print(f"\nTraining XGBoost ({len(X_train):,} samples, {len(feature_cols)} features)...")
    model = train_model(X_train, y_train)

    train_preds = model.predict(X_train)
    train_mae = float(np.mean(np.abs(train_preds - y_train.values)))
    print(f"\nTraining MAE: {train_mae:.4f} K")

    print(f"\nEvaluating on validation set ({len(val_df):,} samples)...")
    metrics = evaluate_model(model, val_df, feature_cols)
    gates = check_governance_gates(metrics)

    # Feature importance
    importances = model.feature_importances_
    fi = sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)
    print(f"\nTop 15 Features:")
    for i, (feat, imp) in enumerate(fi[:15], 1):
        print(f"  {i:>2}. {feat:<30} {imp:>8.4f}")

    print_summary(metrics, gates, training_start, training_end, len(train_df))

    metadata = {
        'model_type': 'XGBRegressor',
        'system_id': 'xgboost_v1_regressor',
        'training_start': str(training_start.date()),
        'training_end': str(training_end.date()),
        'training_window_days': (training_end - training_start).days,
        'training_samples': len(train_df),
        'features': feature_cols,
        'feature_count': len(feature_cols),
        'hyperparameters': {k: v for k, v in HYPERPARAMS.items() if k != 'verbosity'},
        'validation_metrics': metrics,
        'governance_passed': gates['all_passed'],
        'training_mae': round(train_mae, 4),
        'trained_at': datetime.now().isoformat(),
    }

    if args.dry_run:
        print(f"\nDRY RUN — skipping model save")
        return

    if not gates['all_passed']:
        print(f"\nGovernance gates FAILED — model NOT saved.")
        sys.exit(1)

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    date_str = training_end.strftime('%Y%m%d')
    model_name = f"xgboost_mlb_v1_regressor_36f_{date_str}"

    model_path = output_path / f"{model_name}.json"
    model.save_model(str(model_path))
    print(f"\nModel saved: {model_path}")

    metadata_path = output_path / f"{model_name}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Metadata saved: {metadata_path}")

    print(f"\nNext steps:")
    print(f"  gsutil cp {model_path} gs://nba-props-platform-ml-models/mlb/")
    print(f"  gsutil cp {metadata_path} gs://nba-props-platform-ml-models/mlb/")


if __name__ == "__main__":
    main()
