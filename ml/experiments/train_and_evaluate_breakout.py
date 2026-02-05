#!/usr/bin/env python3
"""
Train and Evaluate Breakout Classifier with Shared Features

Uses the shared feature module (ml/features/breakout_features.py) to ensure
consistent feature computation between training and evaluation.

Session 134: Fix for training/evaluation feature mismatch.

Usage:
    PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
        --train-end 2026-01-10 \
        --eval-start 2026-01-11 \
        --eval-end 2026-02-05
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import numpy as np
import pandas as pd
from google.cloud import bigquery
from sklearn.metrics import roc_auc_score, precision_recall_curve
from sklearn.model_selection import train_test_split
import catboost as cb

from ml.features.breakout_features import (
    get_training_data_query,
    prepare_feature_vector,
    validate_feature_distributions,
    BreakoutFeatureConfig,
    BREAKOUT_FEATURE_ORDER,
)

PROJECT_ID = "nba-props-platform"


def load_data(client: bigquery.Client, start: str, end: str, config: BreakoutFeatureConfig) -> pd.DataFrame:
    """Load data using shared feature query."""
    query = get_training_data_query(start, end, config)
    print(f"Loading data from {start} to {end}...")
    df = client.query(query).to_dataframe()

    # Convert Decimal types
    numeric_cols = ['pts_vs_season_zscore', 'points_std_last_10', 'explosion_ratio',
                   'days_since_breakout', 'points_avg_season', 'points_avg_last_5',
                   'minutes_avg_last_10', 'is_breakout', 'actual_points']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"  Loaded {len(df):,} games, breakout rate: {df['is_breakout'].mean()*100:.1f}%")
    return df


def prepare_features(df: pd.DataFrame) -> tuple:
    """Prepare feature matrix and labels using shared prepare_feature_vector."""
    X_list = []
    y_list = []

    for _, row in df.iterrows():
        try:
            vector, _ = prepare_feature_vector(row, validate=True)
            X_list.append(vector.flatten())
            y_list.append(int(row['is_breakout']))
        except Exception as e:
            continue  # Skip problematic rows

    X = np.array(X_list)
    y = np.array(y_list)

    return X, y


def train_model(X_train: np.ndarray, y_train: np.ndarray) -> cb.CatBoostClassifier:
    """Train CatBoost classifier."""
    # Compute class weight
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    scale_pos_weight = n_neg / n_pos if n_pos > 0 else 1.0

    model = cb.CatBoostClassifier(
        iterations=500,
        learning_rate=0.05,
        depth=5,
        l2_leaf_reg=3.0,
        scale_pos_weight=scale_pos_weight,
        random_seed=42,
        verbose=100,
        early_stopping_rounds=30,
        eval_metric='AUC',
    )

    # Split for validation
    X_tr, X_val, y_tr, y_val = train_test_split(
        X_train, y_train, test_size=0.15, random_state=42, stratify=y_train
    )

    # Create DataFrame with named columns for training
    X_tr_df = pd.DataFrame(X_tr, columns=BREAKOUT_FEATURE_ORDER)
    X_val_df = pd.DataFrame(X_val, columns=BREAKOUT_FEATURE_ORDER)

    model.fit(X_tr_df, y_tr, eval_set=(X_val_df, y_val), verbose=100)

    return model


def evaluate_model(model: cb.CatBoostClassifier, X: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    """Evaluate model on test set."""
    probs = model.predict_proba(X)[:, 1]

    # AUC
    auc = roc_auc_score(y, probs)

    # Threshold analysis
    threshold_results = {}
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7, 0.769]:
        preds = (probs >= thresh).astype(int)
        tp = ((preds == 1) & (y == 1)).sum()
        fp = ((preds == 1) & (y == 0)).sum()
        fn = ((preds == 0) & (y == 1)).sum()

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0

        threshold_results[thresh] = {
            'precision': precision,
            'recall': recall,
            'flagged': int(preds.sum()),
        }

    # Risk category analysis
    category_results = {}
    for thresh_low, thresh_high, category in [(0.769, 1.0, 'HIGH_RISK'),
                                               (0.5, 0.769, 'MEDIUM_RISK'),
                                               (0.0, 0.5, 'LOW_RISK')]:
        mask = (probs >= thresh_low) & (probs < thresh_high)
        if mask.sum() > 0:
            category_results[category] = {
                'count': int(mask.sum()),
                'breakout_rate': float(y[mask].mean()),
            }

    return {
        'auc': auc,
        'thresholds': threshold_results,
        'categories': category_results,
    }


def main():
    parser = argparse.ArgumentParser(description='Train and evaluate breakout classifier')
    parser.add_argument('--train-start', default='2025-11-02', help='Training start date')
    parser.add_argument('--train-end', required=True, help='Training end date')
    parser.add_argument('--eval-start', required=True, help='Evaluation start date')
    parser.add_argument('--eval-end', required=True, help='Evaluation end date')
    parser.add_argument('--min-ppg', type=float, default=8.0)
    parser.add_argument('--max-ppg', type=float, default=16.0)
    parser.add_argument('--save-model', help='Path to save model')
    args = parser.parse_args()

    config = BreakoutFeatureConfig(min_ppg=args.min_ppg, max_ppg=args.max_ppg)
    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 60)
    print(" BREAKOUT CLASSIFIER - SHARED FEATURE MODULE")
    print("=" * 60)
    print(f"Training: {args.train_start} to {args.train_end}")
    print(f"Evaluation: {args.eval_start} to {args.eval_end}")
    print(f"Role players: {args.min_ppg}-{args.max_ppg} PPG")
    print()

    # Load training data
    df_train = load_data(client, args.train_start, args.train_end, config)
    validate_feature_distributions(df_train, "training")

    # Load evaluation data
    df_eval = load_data(client, args.eval_start, args.eval_end, config)
    validate_feature_distributions(df_eval, "evaluation")

    # Prepare features
    print("\nPreparing features...")
    X_train, y_train = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    print(f"  Training: {len(X_train):,} samples")
    print(f"  Evaluation: {len(X_eval):,} samples")

    # Train
    print("\nTraining model...")
    model = train_model(X_train, y_train)

    # Feature importance
    print("\nFeature Importance:")
    for name, importance in sorted(zip(BREAKOUT_FEATURE_ORDER, model.feature_importances_),
                                   key=lambda x: -x[1]):
        print(f"  {name}: {importance:.4f}")

    # Evaluate
    print("\n" + "=" * 60)
    print(" EVALUATION RESULTS")
    print("=" * 60)

    results = evaluate_model(model, X_eval, y_eval)

    print(f"\nAUC-ROC: {results['auc']:.4f}")

    print("\nThreshold Analysis:")
    for thresh, stats in results['thresholds'].items():
        print(f"  >= {thresh:.3f}: Precision={stats['precision']*100:.1f}%, "
              f"Recall={stats['recall']*100:.1f}%, N={stats['flagged']}")

    print("\nBreakout Rate by Risk Category:")
    for cat, stats in results['categories'].items():
        print(f"  {cat}: {stats['breakout_rate']*100:.1f}% ({stats['count']} games)")

    # Save model if requested
    if args.save_model:
        model.save_model(args.save_model)
        print(f"\nModel saved to: {args.save_model}")

    print("\n" + "=" * 60)
    print(" COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
