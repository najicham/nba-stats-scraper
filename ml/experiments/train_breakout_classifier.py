#!/usr/bin/env python3
"""
Breakout Classifier Training Script

Trains a binary classifier to predict breakout games for role players.
A "breakout" is defined as scoring >= 1.5x season average points.

Target Population: Role players (8-16 PPG season average)
- These players have high variance and breakout potential
- Provides signal that main regression model may miss

Features:
- pts_vs_season_zscore: Hot streak indicator (from feature store)
- points_std_last_10: Volatility (from feature store)
- explosion_ratio: max(last 5 games) / season_avg (computed)
- days_since_breakout: Recency of last breakout (computed)
- opponent_def_rating: Defensive weakness (from feature store)
- home_away: Home court advantage (from feature store)
- back_to_back: Fatigue indicator (from feature store)

Model: CatBoost binary classifier with scale_pos_weight for class imbalance
Expected breakout rate: ~17% for role players

Usage:
    # Default: Last 60 days training, 7 days eval
    PYTHONPATH=. python ml/experiments/train_breakout_classifier.py --name "BREAKOUT_V1"

    # Custom dates
    PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
        --name "BREAKOUT_JAN" \
        --train-start 2025-11-01 --train-end 2026-01-15 \
        --eval-start 2026-01-16 --eval-end 2026-01-31

    # Dry run
    PYTHONPATH=. python ml/experiments/train_breakout_classifier.py --name "TEST" --dry-run

Session 125 - Breakout Classifier Infrastructure
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import uuid
import json
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from google.cloud import bigquery
from sklearn.metrics import (
    roc_auc_score, precision_recall_curve, average_precision_score,
    classification_report, confusion_matrix
)
from sklearn.model_selection import train_test_split
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

# Breakout definition
BREAKOUT_MULTIPLIER = 1.5  # actual_points >= season_avg * 1.5

# Role player definition (PPG range)
ROLE_PLAYER_MIN_PPG = 8.0
ROLE_PLAYER_MAX_PPG = 16.0

# Features for breakout classifier
BREAKOUT_FEATURES = [
    # Hot streak / momentum
    "pts_vs_season_zscore",      # Z-score vs season avg (from feature store)
    "points_std_last_10",        # Volatility measure

    # Computed features (will be added in query)
    "explosion_ratio",           # max(L5) / season_avg
    "days_since_breakout",       # Days since last breakout game

    # Matchup context (from feature store)
    "opponent_def_rating",       # Lower = weaker defense = more opportunity
    "home_away",                 # 1 = home, 0 = away
    "back_to_back",              # Fatigue indicator

    # Additional context
    "points_avg_last_5",         # Recent scoring form
    "points_avg_season",         # Baseline for context
    "minutes_avg_last_10",       # Playing time stability
]


def parse_args():
    parser = argparse.ArgumentParser(description='Train breakout classifier for role players')
    parser.add_argument('--name', required=True, help='Experiment name (e.g., BREAKOUT_V1)')
    parser.add_argument('--hypothesis', default='', help='What we are testing')
    parser.add_argument('--tags', default='breakout,classifier', help='Comma-separated tags')

    # Explicit dates
    parser.add_argument('--train-start', help='Training start (YYYY-MM-DD)')
    parser.add_argument('--train-end', help='Training end (YYYY-MM-DD)')
    parser.add_argument('--eval-start', help='Eval start (YYYY-MM-DD)')
    parser.add_argument('--eval-end', help='Eval end (YYYY-MM-DD)')

    # Relative dates (defaults)
    parser.add_argument('--train-days', type=int, default=60, help='Days of training (default: 60)')
    parser.add_argument('--eval-days', type=int, default=7, help='Days of eval (default: 7)')

    # Model parameters
    parser.add_argument('--breakout-multiplier', type=float, default=1.5,
                       help='Breakout threshold multiplier (default: 1.5x season avg)')
    parser.add_argument('--min-ppg', type=float, default=8.0,
                       help='Min season PPG for role player (default: 8)')
    parser.add_argument('--max-ppg', type=float, default=16.0,
                       help='Max season PPG for role player (default: 16)')

    parser.add_argument('--dry-run', action='store_true', help='Show plan only')
    parser.add_argument('--skip-register', action='store_true', help='Skip ml_experiments')
    return parser.parse_args()


def get_dates(args):
    """Compute date ranges."""
    if args.train_start and args.train_end and args.eval_start and args.eval_end:
        return {
            'train_start': args.train_start,
            'train_end': args.train_end,
            'eval_start': args.eval_start,
            'eval_end': args.eval_end,
        }

    yesterday = date.today() - timedelta(days=1)
    eval_end = yesterday
    eval_start = eval_end - timedelta(days=args.eval_days - 1)
    train_end = eval_start - timedelta(days=1)
    train_start = train_end - timedelta(days=args.train_days - 1)

    return {
        'train_start': train_start.strftime('%Y-%m-%d'),
        'train_end': train_end.strftime('%Y-%m-%d'),
        'eval_start': eval_start.strftime('%Y-%m-%d'),
        'eval_end': eval_end.strftime('%Y-%m-%d'),
    }


def load_breakout_training_data(client, start, end, min_ppg, max_ppg, breakout_mult):
    """
    Load training data for breakout classifier.

    This query:
    1. Filters to role players (season avg between min_ppg and max_ppg)
    2. Computes is_breakout label (actual >= season_avg * breakout_mult)
    3. Computes explosion_ratio: max points in L5 / season_avg
    4. Computes days_since_breakout: days since player's last breakout game

    The explosion_ratio captures whether the player has shown recent ability
    to explode, which may predict future breakouts.
    """
    query = f"""
    WITH player_history AS (
      -- Get all games for players in the date range to compute derived features
      SELECT
        pgs.player_lookup,
        pgs.game_date,
        pgs.points,
        dc.points_avg_season,
        dc.points_std_last_10,
        dc.points_avg_last_5,
        dc.minutes_avg_last_10,
        -- Get max points in last 5 games for explosion_ratio
        MAX(pgs2.points) OVER (
          PARTITION BY pgs.player_lookup
          ORDER BY pgs.game_date
          ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) as max_points_last_5,
        -- Mark if this game was a breakout
        CASE WHEN pgs.points >= dc.points_avg_season * {breakout_mult} THEN 1 ELSE 0 END as is_breakout_game
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      JOIN `{PROJECT_ID}.nba_precompute.player_daily_cache` dc
        ON pgs.player_lookup = dc.player_lookup AND pgs.game_date = dc.cache_date
      LEFT JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs2
        ON pgs.player_lookup = pgs2.player_lookup
        AND pgs2.game_date >= DATE_SUB(pgs.game_date, INTERVAL 30 DAY)
        AND pgs2.game_date < pgs.game_date
      WHERE pgs.game_date >= DATE_SUB(DATE('{start}'), INTERVAL 60 DAY)  -- Need history
        AND pgs.game_date <= '{end}'
        AND dc.points_avg_season BETWEEN {min_ppg} AND {max_ppg}
        AND pgs.minutes_played > 0
        AND pgs.points IS NOT NULL
    ),
    with_breakout_history AS (
      -- Compute days since last breakout for each game
      SELECT
        ph.*,
        LAG(game_date) OVER (
          PARTITION BY player_lookup, is_breakout_game
          ORDER BY game_date
        ) as last_breakout_date
      FROM player_history ph
    ),
    final_features AS (
      SELECT
        wbh.player_lookup,
        wbh.game_date,
        wbh.points as actual_points,
        wbh.points_avg_season,

        -- Target variable
        CASE WHEN wbh.points >= wbh.points_avg_season * {breakout_mult} THEN 1 ELSE 0 END as is_breakout,

        -- From daily cache
        wbh.points_std_last_10,
        wbh.points_avg_last_5,
        wbh.minutes_avg_last_10,

        -- Computed features
        SAFE_DIVIDE(wbh.max_points_last_5, wbh.points_avg_season) as explosion_ratio,
        COALESCE(
          DATE_DIFF(wbh.game_date, wbh.last_breakout_date, DAY),
          30  -- Default if no prior breakout
        ) as days_since_breakout,

        -- From feature store (will join)
        mf.features,
        mf.feature_names

      FROM with_breakout_history wbh
      JOIN `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
        ON wbh.player_lookup = mf.player_lookup AND wbh.game_date = mf.game_date
      WHERE wbh.game_date BETWEEN '{start}' AND '{end}'
        AND mf.feature_count >= 33
        AND wbh.is_breakout_game IS NOT NULL  -- Filter to rows where we computed breakout
        -- Session 156: Quality gate for training data
        AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
        AND COALESCE(mf.feature_quality_score, 0) >= 70
    )
    SELECT DISTINCT
      player_lookup,
      game_date,
      actual_points,
      points_avg_season,
      is_breakout,
      points_std_last_10,
      points_avg_last_5,
      minutes_avg_last_10,
      explosion_ratio,
      days_since_breakout,
      features,
      feature_names
    FROM final_features
    WHERE explosion_ratio IS NOT NULL  -- Must have L5 history
    ORDER BY game_date, player_lookup
    """
    return client.query(query).to_dataframe()


def extract_feature_from_store(features, feature_names, target_name, default=None):
    """Extract a single feature from the feature store arrays."""
    if target_name in feature_names:
        idx = feature_names.index(target_name)
        if idx < len(features) and features[idx] is not None:
            return float(features[idx])
    return default


def prepare_breakout_features(df):
    """
    Prepare feature matrix for breakout classifier.

    Combines:
    - Computed features from query (explosion_ratio, days_since_breakout)
    - Features extracted from feature store (pts_vs_season_zscore, opponent_def_rating, etc.)
    """
    rows = []
    for _, row in df.iterrows():
        feature_values = row['features']
        feature_names = list(row['feature_names'])

        # Build feature dict combining query results and feature store
        feature_dict = {
            # From query
            'points_std_last_10': row['points_std_last_10'],
            'explosion_ratio': row['explosion_ratio'],
            'days_since_breakout': row['days_since_breakout'],
            'points_avg_last_5': row['points_avg_last_5'],
            'points_avg_season': row['points_avg_season'],
            'minutes_avg_last_10': row['minutes_avg_last_10'],
        }

        # Extract from feature store
        feature_dict['pts_vs_season_zscore'] = extract_feature_from_store(
            feature_values, feature_names, 'pts_vs_season_zscore', default=0.0
        )
        feature_dict['opponent_def_rating'] = extract_feature_from_store(
            feature_values, feature_names, 'opponent_def_rating', default=112.0
        )
        feature_dict['home_away'] = extract_feature_from_store(
            feature_values, feature_names, 'home_away', default=0.5
        )
        feature_dict['back_to_back'] = extract_feature_from_store(
            feature_values, feature_names, 'back_to_back', default=0.0
        )

        rows.append(feature_dict)

    X = pd.DataFrame(rows, columns=BREAKOUT_FEATURES)

    # Handle missing values
    X = X.fillna(X.median())

    # Replace any inf values
    X = X.replace([np.inf, -np.inf], np.nan).fillna(X.median())

    y = df['is_breakout'].astype(int)

    return X, y


def compute_class_weight(y):
    """Compute scale_pos_weight for imbalanced classes."""
    n_neg = (y == 0).sum()
    n_pos = (y == 1).sum()
    if n_pos == 0:
        return 1.0
    return n_neg / n_pos


def find_optimal_threshold(y_true, y_prob, target_precision=0.60):
    """
    Find optimal probability threshold for deployment.

    For betting, we want high precision (fewer false positives) at acceptable recall.
    Returns threshold that achieves target precision, or best available.
    """
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_prob)

    # Find threshold achieving target precision
    for i, (p, r, t) in enumerate(zip(precisions, recalls, thresholds)):
        if p >= target_precision:
            return {
                'threshold': float(t),
                'precision': float(p),
                'recall': float(r),
                'f1': 2 * p * r / (p + r) if (p + r) > 0 else 0
            }

    # Fallback: return threshold with best F1
    f1_scores = 2 * precisions * recalls / (precisions + recalls + 1e-10)
    best_idx = np.argmax(f1_scores[:-1])  # Exclude last (precision=1, recall=0)
    return {
        'threshold': float(thresholds[best_idx]),
        'precision': float(precisions[best_idx]),
        'recall': float(recalls[best_idx]),
        'f1': float(f1_scores[best_idx])
    }


def main():
    args = parse_args()
    dates = get_dates(args)
    exp_id = str(uuid.uuid4())[:8]

    # Use parameters from args
    breakout_mult = args.breakout_multiplier
    min_ppg = args.min_ppg
    max_ppg = args.max_ppg

    # Compute actual day counts
    train_start_dt = datetime.strptime(dates['train_start'], '%Y-%m-%d').date()
    train_end_dt = datetime.strptime(dates['train_end'], '%Y-%m-%d').date()
    eval_start_dt = datetime.strptime(dates['eval_start'], '%Y-%m-%d').date()
    eval_end_dt = datetime.strptime(dates['eval_end'], '%Y-%m-%d').date()
    train_days_actual = (train_end_dt - train_start_dt).days + 1
    eval_days_actual = (eval_end_dt - eval_start_dt).days + 1

    print("=" * 70)
    print(f" BREAKOUT CLASSIFIER: {args.name}")
    print("=" * 70)
    print(f"Training:   {dates['train_start']} to {dates['train_end']} ({train_days_actual} days)")
    print(f"Evaluation: {dates['eval_start']} to {dates['eval_end']} ({eval_days_actual} days)")
    print()
    print(f"Target: Role players ({min_ppg}-{max_ppg} PPG season avg)")
    print(f"Breakout: >= {breakout_mult}x season average")
    print()

    if args.dry_run:
        print("DRY RUN - would train breakout classifier on above dates")
        return

    client = bigquery.Client(project=PROJECT_ID)

    # Load training data
    print("Loading training data...")
    df_train = load_breakout_training_data(
        client, dates['train_start'], dates['train_end'],
        min_ppg, max_ppg, breakout_mult
    )
    print(f"  {len(df_train):,} samples")

    # Load evaluation data
    print("Loading evaluation data...")
    df_eval = load_breakout_training_data(
        client, dates['eval_start'], dates['eval_end'],
        min_ppg, max_ppg, breakout_mult
    )
    print(f"  {len(df_eval):,} samples")

    if len(df_train) < 500:
        print("ERROR: Not enough training data (need 500+)")
        return

    # Check class distribution
    train_breakout_rate = df_train['is_breakout'].mean()
    eval_breakout_rate = df_eval['is_breakout'].mean() if len(df_eval) > 0 else 0

    print(f"\nClass distribution:")
    print(f"  Training: {train_breakout_rate*100:.1f}% breakouts ({df_train['is_breakout'].sum()} of {len(df_train)})")
    print(f"  Eval:     {eval_breakout_rate*100:.1f}% breakouts ({df_eval['is_breakout'].sum()} of {len(df_eval)})")

    # Prepare features
    X_train_full, y_train_full = prepare_breakout_features(df_train)
    X_eval, y_eval = prepare_breakout_features(df_eval)

    # Split training into train/validation
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_full, y_train_full, test_size=0.15, random_state=42, stratify=y_train_full
    )

    print(f"\nDataset sizes:")
    print(f"  Train: {len(X_train):,} | Val: {len(X_val):,} | Eval: {len(X_eval):,}")

    # Compute class weight for imbalance
    class_weight = compute_class_weight(y_train)
    print(f"  Class weight (scale_pos_weight): {class_weight:.2f}")

    # Train CatBoost classifier
    print("\nTraining CatBoost classifier...")
    model = cb.CatBoostClassifier(
        iterations=500,
        learning_rate=0.05,
        depth=5,
        l2_leaf_reg=3,
        scale_pos_weight=class_weight,
        random_seed=42,
        verbose=100,
        early_stopping_rounds=30,
        eval_metric='AUC',
    )

    model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        verbose=100
    )

    # Evaluate
    print("\n" + "=" * 70)
    print(" EVALUATION RESULTS")
    print("=" * 70)

    # Predictions
    eval_probs = model.predict_proba(X_eval)[:, 1]
    val_probs = model.predict_proba(X_val)[:, 1]

    # Core metrics
    eval_auc = roc_auc_score(y_eval, eval_probs) if y_eval.sum() > 0 else 0
    eval_ap = average_precision_score(y_eval, eval_probs) if y_eval.sum() > 0 else 0

    print(f"\nCore Metrics:")
    print(f"  AUC-ROC: {eval_auc:.4f}")
    print(f"  Average Precision: {eval_ap:.4f}")

    # Find optimal threshold
    optimal = find_optimal_threshold(y_eval, eval_probs, target_precision=0.60)
    print(f"\nOptimal Threshold (target 60% precision):")
    print(f"  Threshold: {optimal['threshold']:.3f}")
    print(f"  Precision: {optimal['precision']*100:.1f}%")
    print(f"  Recall: {optimal['recall']*100:.1f}%")
    print(f"  F1: {optimal['f1']:.3f}")

    # Threshold analysis
    print(f"\nThreshold Analysis:")
    for thresh in [0.3, 0.4, 0.5, 0.6, 0.7]:
        preds = (eval_probs >= thresh).astype(int)
        tp = ((preds == 1) & (y_eval == 1)).sum()
        fp = ((preds == 1) & (y_eval == 0)).sum()
        fn = ((preds == 0) & (y_eval == 1)).sum()
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        n_flagged = preds.sum()
        print(f"  {thresh:.1f}: Precision={precision*100:.1f}%, Recall={recall*100:.1f}%, Flagged={n_flagged}")

    # Feature importance
    print(f"\nFeature Importance:")
    importance = dict(zip(BREAKOUT_FEATURES, model.feature_importances_))
    for feat, imp in sorted(importance.items(), key=lambda x: -x[1]):
        print(f"  {feat}: {imp:.4f}")

    # Classification report at optimal threshold
    eval_preds = (eval_probs >= optimal['threshold']).astype(int)
    print(f"\nClassification Report (threshold={optimal['threshold']:.3f}):")
    print(classification_report(y_eval, eval_preds, target_names=['No Breakout', 'Breakout']))

    # Save model
    MODEL_OUTPUT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_path = MODEL_OUTPUT_DIR / f"breakout_classifier_{args.name}_{ts}.cbm"
    model.save_model(str(model_path))

    # Save threshold recommendation
    config_path = MODEL_OUTPUT_DIR / f"breakout_classifier_{args.name}_{ts}_config.json"
    config = {
        'model_path': str(model_path),
        'model_type': 'breakout_classifier',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'features': BREAKOUT_FEATURES,
        'target_population': f'role_players_{min_ppg}_{max_ppg}_ppg',
        'breakout_definition': f'{breakout_mult}x_season_avg',
        'recommended_threshold': optimal['threshold'],
        'threshold_metrics': optimal,
        'training_period': {
            'start': dates['train_start'],
            'end': dates['train_end'],
            'samples': len(df_train),
            'breakout_rate': train_breakout_rate,
        },
        'eval_period': {
            'start': dates['eval_start'],
            'end': dates['eval_end'],
            'samples': len(df_eval),
            'breakout_rate': eval_breakout_rate,
        },
        'eval_metrics': {
            'auc': eval_auc,
            'average_precision': eval_ap,
        }
    }
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"\n✅ Model saved: {model_path}")
    print(f"✅ Config saved: {config_path}")

    # Recommendation
    print("\n" + "-" * 40)
    print("DEPLOYMENT RECOMMENDATION")
    print("-" * 40)

    if eval_auc >= 0.65 and optimal['precision'] >= 0.55:
        print("✅ READY FOR SHADOW MODE")
        print(f"   - Use threshold {optimal['threshold']:.3f} for {optimal['precision']*100:.1f}% precision")
        print(f"   - Will flag ~{(eval_probs >= optimal['threshold']).mean()*100:.1f}% of role player games")
    elif eval_auc >= 0.60:
        print("⚠️  MARGINAL PERFORMANCE")
        print(f"   - AUC ({eval_auc:.3f}) is acceptable but not strong")
        print("   - Consider more training data or feature engineering")
    else:
        print("❌ NEEDS IMPROVEMENT")
        print(f"   - AUC ({eval_auc:.3f}) below 0.60 threshold")
        print("   - Try different features or larger training window")

    # Register experiment
    if not args.skip_register:
        try:
            row = {
                'experiment_id': exp_id,
                'experiment_name': args.name,
                'experiment_type': 'breakout_classifier',
                'hypothesis': args.hypothesis or f'Breakout classifier for role players ({min_ppg}-{max_ppg} PPG)',
                'config_json': json.dumps({
                    'train_days': train_days_actual,
                    'eval_days': eval_days_actual,
                    'features': len(BREAKOUT_FEATURES),
                    'breakout_multiplier': breakout_mult,
                    'min_ppg': min_ppg,
                    'max_ppg': max_ppg,
                }),
                'train_period': {
                    'start_date': dates['train_start'],
                    'end_date': dates['train_end'],
                    'samples': len(df_train)
                },
                'eval_period': {
                    'start_date': dates['eval_start'],
                    'end_date': dates['eval_end'],
                    'samples': len(df_eval)
                },
                'results_json': json.dumps({
                    'auc': round(eval_auc, 4),
                    'average_precision': round(eval_ap, 4),
                    'optimal_threshold': round(optimal['threshold'], 3),
                    'precision_at_optimal': round(optimal['precision'], 4),
                    'recall_at_optimal': round(optimal['recall'], 4),
                    'train_breakout_rate': round(train_breakout_rate, 4),
                    'eval_breakout_rate': round(eval_breakout_rate, 4),
                    'feature_importance': {k: round(v, 4) for k, v in importance.items()},
                }),
                'model_path': str(model_path),
                'status': 'completed',
                'tags': [t.strip() for t in args.tags.split(',') if t.strip()],
                'created_at': datetime.now(timezone.utc).isoformat(),
                'completed_at': datetime.now(timezone.utc).isoformat(),
            }
            errors = client.insert_rows_json(f"{PROJECT_ID}.nba_predictions.ml_experiments", [row])
            if not errors:
                print(f"\nRegistered in ml_experiments (ID: {exp_id})")
        except Exception as e:
            print(f"Warning: Could not register: {e}")


if __name__ == "__main__":
    main()
