#!/usr/bin/env python3
"""Adversarial Validation — detect feature drift between time periods.

Trains a classifier to distinguish Period A from Period B data.
If AUC > 0.65, meaningful drift exists. Top features by importance
show which features are drifting most.

Session 370: Created for February OVER collapse diagnosis.

Usage:
    # Default: Dec-Jan vs Feb
    PYTHONPATH=. python bin/adversarial_validation.py

    # Custom periods
    PYTHONPATH=. python bin/adversarial_validation.py \
        --period-a-start 2025-12-01 --period-a-end 2026-01-31 \
        --period-b-start 2026-02-01 --period-b-end 2026-02-27

    # Split by direction
    PYTHONPATH=. python bin/adversarial_validation.py --by-direction

    # Previous season
    PYTHONPATH=. python bin/adversarial_validation.py \
        --period-a-start 2024-12-01 --period-a-end 2025-01-31 \
        --period-b-start 2025-02-01 --period-b-end 2025-02-28
"""

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import cross_val_score

logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def load_feature_data(bq_client, start_date: str, end_date: str,
                      direction: str = None) -> pd.DataFrame:
    """Load feature store data for a date range.

    Returns DataFrame with feature columns and metadata.
    """
    from shared.ml.feature_contract import FEATURE_STORE_FEATURE_COUNT, FEATURE_STORE_NAMES

    feature_cols = ',\n        '.join(
        f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
    )

    direction_filter = ""
    if direction:
        direction_filter = f"AND p.recommendation = '{direction}'"

    query = f"""
    SELECT
        mf.game_date,
        mf.player_lookup,
        {feature_cols}
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
        ON mf.player_lookup = p.player_lookup
        AND mf.game_date = p.game_date
    WHERE mf.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND p.game_date BETWEEN '{start_date}' AND '{end_date}'
        AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
        AND mf.feature_quality_score >= 70
        {direction_filter}
    """
    df = bq_client.query(query).to_dataframe()

    # Rename columns to feature names
    rename_map = {
        f'feature_{i}_value': FEATURE_STORE_NAMES[i]
        for i in range(min(FEATURE_STORE_FEATURE_COUNT, len(FEATURE_STORE_NAMES)))
    }
    df.rename(columns=rename_map, inplace=True)

    return df


def run_adversarial_validation(df_a: pd.DataFrame, df_b: pd.DataFrame,
                                feature_names: list,
                                label: str = "A vs B") -> dict:
    """Train discriminator and report AUC + top features.

    Returns dict with AUC, feature importances, and interpretation.
    """
    # Select only feature columns that exist in both DataFrames
    common_features = [f for f in feature_names
                       if f in df_a.columns and f in df_b.columns]

    X_a = df_a[common_features].fillna(0).values
    X_b = df_b[common_features].fillna(0).values

    X = np.vstack([X_a, X_b])
    y = np.concatenate([np.zeros(len(X_a)), np.ones(len(X_b))])

    # Train discriminator
    clf = GradientBoostingClassifier(
        n_estimators=100, max_depth=3, learning_rate=0.1,
        subsample=0.8, random_state=42,
    )

    # 5-fold cross-validation
    scores = cross_val_score(clf, X, y, cv=5, scoring='roc_auc')
    mean_auc = scores.mean()
    std_auc = scores.std()

    # Fit on all data for feature importances
    clf.fit(X, y)
    importances = clf.feature_importances_

    # Top features
    top_idx = np.argsort(importances)[::-1][:10]
    top_features = [
        {
            'feature': common_features[i],
            'importance': float(importances[i]),
            'mean_a': float(np.nanmean(X_a[:, i])),
            'mean_b': float(np.nanmean(X_b[:, i])),
            'shift': float(np.nanmean(X_b[:, i]) - np.nanmean(X_a[:, i])),
        }
        for i in top_idx
    ]

    # Interpretation
    if mean_auc > 0.75:
        interpretation = "STRONG drift — distributions very different"
    elif mean_auc > 0.65:
        interpretation = "MODERATE drift — meaningful feature shifts"
    elif mean_auc > 0.55:
        interpretation = "MILD drift — some feature movement"
    else:
        interpretation = "NO significant drift — distributions similar"

    result = {
        'label': label,
        'auc_mean': mean_auc,
        'auc_std': std_auc,
        'auc_folds': scores.tolist(),
        'n_a': len(X_a),
        'n_b': len(X_b),
        'n_features': len(common_features),
        'interpretation': interpretation,
        'top_features': top_features,
    }

    return result


def print_result(result: dict):
    """Pretty-print adversarial validation results."""
    print(f"\n{'='*70}")
    print(f"  {result['label']}")
    print(f"{'='*70}")
    print(f"  AUC: {result['auc_mean']:.4f} ± {result['auc_std']:.4f}")
    print(f"  Fold AUCs: {', '.join(f'{s:.3f}' for s in result['auc_folds'])}")
    print(f"  Samples: Period A = {result['n_a']}, Period B = {result['n_b']}")
    print(f"  Features: {result['n_features']}")
    print(f"  → {result['interpretation']}")

    print(f"\n  Top 10 Drifting Features:")
    print(f"  {'Feature':30s} {'Import%':>8s} {'Mean A':>8s} {'Mean B':>8s} {'Shift':>8s}")
    print(f"  {'-'*62}")
    for f in result['top_features']:
        print(f"  {f['feature']:30s} {f['importance']:7.1%} "
              f"{f['mean_a']:8.2f} {f['mean_b']:8.2f} {f['shift']:+8.2f}")


def main():
    parser = argparse.ArgumentParser(
        description='Adversarial validation — detect feature drift between periods'
    )
    parser.add_argument('--period-a-start', default='2025-12-01',
                        help='Period A start date')
    parser.add_argument('--period-a-end', default='2026-01-31',
                        help='Period A end date')
    parser.add_argument('--period-b-start', default='2026-02-01',
                        help='Period B start date')
    parser.add_argument('--period-b-end', default='2026-02-27',
                        help='Period B end date')
    parser.add_argument('--by-direction', action='store_true',
                        help='Split analysis by OVER/UNDER direction')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    from google.cloud import bigquery
    from shared.ml.feature_contract import FEATURE_STORE_NAMES

    bq_client = bigquery.Client(project=PROJECT_ID)

    print(f"Adversarial Validation")
    print(f"Period A: {args.period_a_start} → {args.period_a_end}")
    print(f"Period B: {args.period_b_start} → {args.period_b_end}")

    if args.by_direction:
        for direction in ['OVER', 'UNDER']:
            print(f"\n{'#'*70}")
            print(f"  Direction: {direction}")
            print(f"{'#'*70}")

            df_a = load_feature_data(bq_client, args.period_a_start, args.period_a_end,
                                     direction=direction)
            df_b = load_feature_data(bq_client, args.period_b_start, args.period_b_end,
                                     direction=direction)

            print(f"  Period A: {len(df_a)} samples, Period B: {len(df_b)} samples")

            if len(df_a) < 50 or len(df_b) < 50:
                print(f"  SKIPPED — insufficient samples")
                continue

            result = run_adversarial_validation(
                df_a, df_b, FEATURE_STORE_NAMES,
                label=f"{direction}: {args.period_a_start}–{args.period_a_end} vs {args.period_b_start}–{args.period_b_end}"
            )
            print_result(result)
    else:
        # Overall analysis
        df_a = load_feature_data(bq_client, args.period_a_start, args.period_a_end)
        df_b = load_feature_data(bq_client, args.period_b_start, args.period_b_end)

        print(f"Period A: {len(df_a)} samples, Period B: {len(df_b)} samples")

        if len(df_a) < 50 or len(df_b) < 50:
            print("ERROR: Insufficient samples")
            return

        result = run_adversarial_validation(
            df_a, df_b, FEATURE_STORE_NAMES,
            label=f"ALL: {args.period_a_start}–{args.period_a_end} vs {args.period_b_start}–{args.period_b_end}"
        )
        print_result(result)


if __name__ == '__main__':
    main()
