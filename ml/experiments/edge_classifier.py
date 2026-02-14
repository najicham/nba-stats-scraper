#!/usr/bin/env python3
"""
Edge Classifier (Model 2) - Phase 2 of V2 Architecture

Two-model pipeline:
  Model 1: Vegas-free CatBoost regressor (predicts actual points scored)
  Model 2: Binary classifier (predicts whether Model 1's edge will hit)

Combined bet selection:
  edge >= 3 AND model2_confidence >= threshold

Architecture:
  Model 1 prediction → edge = pred - vegas_line → Model 2 features → P(edge hits)

Usage:
    # Train edge classifier on Jan 2026 eval window
    PYTHONPATH=. python ml/experiments/edge_classifier.py \
        --name "EDGE_CLF_JAN26" \
        --model1-path models/catboost_v9_50f_noveg_train20251022-20251231_20260212_234328.cbm \
        --feature-set v12 \
        --train-start 2025-10-22 --train-end 2025-12-31 \
        --eval-start 2026-01-01 --eval-end 2026-01-31 \
        --walkforward --force --skip-register

Session 229 - Phase 2 Edge Classifier
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error, roc_auc_score, precision_score, recall_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import catboost as cb

from shared.ml.feature_contract import (
    V12_CONTRACT, V12_FEATURE_NAMES,
    V11_CONTRACT, V11_FEATURE_NAMES,
    V9_CONTRACT, V9_FEATURE_NAMES,
    FEATURE_DEFAULTS, validate_all_contracts,
)

# Reuse data loading from quick_retrain
from ml.experiments.quick_retrain import (
    load_train_data, load_eval_data, load_eval_data_from_production,
    augment_v11_features, augment_v12_features,
    prepare_features, compute_hit_rate, compute_directional_hit_rates,
    compute_segmented_hit_rates,
)

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")
VEGAS_FEATURE_NAMES = ['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line']

# Model 2 feature names (10 features)
MODEL2_FEATURE_NAMES = [
    'raw_edge_size',
    'edge_direction',
    'player_volatility',
    'line_vs_season_avg',
    'player_tier',
    'prop_over_streak',
    'prop_under_streak',
    'game_total_line',
    'days_rest',
    'scoring_trend_slope',
]


def parse_args():
    parser = argparse.ArgumentParser(description='Edge Classifier (Model 2) - Phase 2')
    parser.add_argument('--name', required=True, help='Experiment name')
    parser.add_argument('--model1-path', required=True, help='Path to saved Model 1 .cbm file')
    parser.add_argument('--feature-set', choices=['v9', 'v11', 'v12'], default='v12',
                        help='Feature set for Model 1 (default: v12)')

    parser.add_argument('--train-start', required=True, help='Training start (YYYY-MM-DD)')
    parser.add_argument('--train-end', required=True, help='Training end (YYYY-MM-DD)')
    parser.add_argument('--eval-start', required=True, help='Eval start (YYYY-MM-DD)')
    parser.add_argument('--eval-end', required=True, help='Eval end (YYYY-MM-DD)')

    parser.add_argument('--min-edge-train', type=float, default=2.0,
                        help='Minimum |edge| for Model 2 training (default: 2.0)')
    parser.add_argument('--confidence-thresholds', default='0.50,0.55,0.60,0.65,0.70',
                        help='Comma-separated confidence thresholds to evaluate')
    parser.add_argument('--walkforward', action='store_true',
                        help='Show per-week eval breakdown')

    parser.add_argument('--use-production-lines', action='store_true', default=True)
    parser.add_argument('--no-production-lines', dest='use_production_lines', action='store_false')
    parser.add_argument('--line-source', default='draftkings')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--skip-register', action='store_true')
    return parser.parse_args()


def extract_vegas_from_features(df):
    """Extract vegas_points_line from features array into a column."""
    vegas_lines = []
    for _, row in df.iterrows():
        fd = dict(zip(row['feature_names'], row['features']))
        vl = fd.get('vegas_points_line')
        vegas_lines.append(float(vl) if vl is not None and float(vl) > 0 else np.nan)
    df = df.copy()
    df['vegas_line'] = vegas_lines
    return df


def build_model2_features(df, model1_preds, vegas_lines):
    """
    Build Model 2 feature matrix from Model 1 predictions + context.

    Features:
      1. raw_edge_size:      |model1_pred - vegas_line|
      2. edge_direction:     +1 (OVER) or -1 (UNDER)
      3. player_volatility:  points_std_last_10
      4. line_vs_season_avg: vegas_line - points_avg_season
      5. player_tier:        0=bench(<8), 1=role(8-15), 2=mid(15-25), 3=star(25+)
      6. prop_over_streak
      7. prop_under_streak
      8. game_total_line
      9. days_rest
     10. scoring_trend_slope
    """
    edges = model1_preds - vegas_lines
    rows = []

    for i, (_, row) in enumerate(df.iterrows()):
        fd = dict(zip(row['feature_names'], row['features']))
        season_avg = float(fd.get('points_avg_season', 10.0))
        edge = edges[i]

        rows.append({
            'raw_edge_size': abs(edge),
            'edge_direction': 1.0 if edge > 0 else -1.0,
            'player_volatility': float(fd.get('points_std_last_10', 5.0)),
            'line_vs_season_avg': float(vegas_lines[i]) - season_avg,
            'player_tier': (3.0 if season_avg >= 25 else
                           2.0 if season_avg >= 15 else
                           1.0 if season_avg >= 8 else 0.0),
            'prop_over_streak': float(fd.get('prop_over_streak', 0.0)),
            'prop_under_streak': float(fd.get('prop_under_streak', 0.0)),
            'game_total_line': float(fd.get('game_total_line', 224.0)),
            'days_rest': float(fd.get('days_rest', 1.0)),
            'scoring_trend_slope': float(fd.get('scoring_trend_slope', 0.0)),
        })

    result = pd.DataFrame(rows, columns=MODEL2_FEATURE_NAMES)
    # Fill NaN with column medians (handles missing upstream data)
    result = result.fillna(result.median())
    # If median is still NaN (all missing), use defaults
    defaults = {
        'raw_edge_size': 3.0, 'edge_direction': 0.0, 'player_volatility': 5.0,
        'line_vs_season_avg': 0.0, 'player_tier': 1.0, 'prop_over_streak': 0.0,
        'prop_under_streak': 0.0, 'game_total_line': 224.0, 'days_rest': 1.0,
        'scoring_trend_slope': 0.0,
    }
    for col, default in defaults.items():
        if col in result.columns:
            result[col] = result[col].fillna(default)
    return result


def compute_target(model1_preds, vegas_lines, actual_points):
    """
    Compute binary target: did the edge hit?

    OVER (edge > 0):  hit if actual > vegas_line
    UNDER (edge < 0): hit if actual < vegas_line
    Push:             NaN (excluded)
    """
    edges = model1_preds - vegas_lines
    is_over = edges > 0
    is_push = actual_points == vegas_lines

    hit = np.where(
        is_over,
        (actual_points > vegas_lines).astype(float),
        (actual_points < vegas_lines).astype(float),
    )
    hit = hit.astype(float)
    hit[is_push] = np.nan
    return hit


def generate_oof_predictions(X_train, y_train, game_dates, n_folds=5):
    """
    Generate out-of-fold (OOF) predictions using temporal cross-validation.

    Model 1 in-sample predictions have ~88% hit rate (overfit to training data),
    making it impossible for Model 2 to learn what distinguishes winners from losers.
    OOF predictions give realistic ~55-60% hit rate, matching eval-time behavior.

    Uses TimeSeriesSplit: each fold trains on earlier data, predicts on later data.
    """
    from sklearn.model_selection import TimeSeriesSplit

    # Sort by date for temporal split
    dates = pd.to_datetime(game_dates)
    sort_idx = dates.argsort().values
    X_sorted = X_train.iloc[sort_idx].reset_index(drop=True)
    y_sorted = y_train.iloc[sort_idx].reset_index(drop=True)

    oof_preds = np.full(len(X_train), np.nan)
    tscv = TimeSeriesSplit(n_splits=n_folds)

    print(f"  Generating OOF predictions ({n_folds}-fold temporal CV)...")
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X_sorted)):
        model = cb.CatBoostRegressor(
            iterations=500, depth=6, learning_rate=0.05,
            l2_leaf_reg=3.0, random_seed=42, verbose=0,
            early_stopping_rounds=50, loss_function='MAE',
        )
        model.fit(
            X_sorted.iloc[train_idx], y_sorted.iloc[train_idx],
            eval_set=(X_sorted.iloc[val_idx], y_sorted.iloc[val_idx]),
            verbose=0,
        )
        fold_preds = model.predict(X_sorted.iloc[val_idx])
        # Map back to original indices
        original_idx = sort_idx[val_idx]
        oof_preds[original_idx] = fold_preds

        fold_mae = mean_absolute_error(y_sorted.iloc[val_idx], fold_preds)
        print(f"    Fold {fold+1}/{n_folds}: train={len(train_idx)}, val={len(val_idx)}, MAE={fold_mae:.2f}")

    # Rows from fold 0 (earliest data) have no OOF predictions since TimeSeriesSplit
    # starts with fold 1 having the smallest training set. Fill with NaN (will be filtered).
    valid_oof = ~np.isnan(oof_preds)
    if valid_oof.sum() > 0:
        oof_mae = mean_absolute_error(y_train.values[valid_oof], oof_preds[valid_oof])
        print(f"    OOF coverage: {valid_oof.sum()}/{len(oof_preds)} ({100*valid_oof.mean():.0f}%)")
        print(f"    OOF MAE: {oof_mae:.2f}")

    return oof_preds, valid_oof


def train_logistic(X_train, y_train):
    """Train a LogisticRegression baseline."""
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)
    model = LogisticRegression(max_iter=1000, random_state=42, C=1.0)
    model.fit(X_scaled, y_train)
    return model, scaler


def train_catboost_classifier(X_train, y_train):
    """Train a CatBoost binary classifier."""
    model = cb.CatBoostClassifier(
        iterations=500,
        depth=4,
        learning_rate=0.05,
        l2_leaf_reg=3.0,
        random_seed=42,
        verbose=0,
        early_stopping_rounds=50,
        loss_function='Logloss',
        eval_metric='AUC',
        auto_class_weights='Balanced',
    )
    # Split for early stopping
    from sklearn.model_selection import train_test_split
    X_tr, X_val, y_tr, y_val = train_test_split(
        X_train, y_train, test_size=0.15, random_state=42, stratify=y_train
    )
    model.fit(X_tr, y_tr, eval_set=(X_val, y_val), verbose=0)
    return model


def evaluate_model2(name, y_true, probs):
    """Evaluate Model 2 classification metrics."""
    auc = roc_auc_score(y_true, probs) if len(np.unique(y_true)) > 1 else 0.0
    print(f"\n  {name}:")
    print(f"    AUC-ROC: {auc:.4f}")
    print(f"    Base rate: {y_true.mean():.3f} ({y_true.sum():.0f}/{len(y_true)} hits)")

    # Precision at various thresholds
    for t in [0.50, 0.55, 0.60, 0.65, 0.70]:
        preds_t = (probs >= t).astype(int)
        n_pos = preds_t.sum()
        if n_pos > 0:
            prec = precision_score(y_true, preds_t, zero_division=0)
            rec = recall_score(y_true, preds_t, zero_division=0)
            print(f"    @{t:.2f}: precision={prec:.3f}, recall={rec:.3f}, n={n_pos}")
        else:
            print(f"    @{t:.2f}: no predictions above threshold")

    return auc


def evaluate_combined(model1_preds, model2_probs, vegas_lines, actual_points,
                      min_edge=3.0, thresholds=None):
    """
    Compare Model 1 alone vs Model 1+2 combined at various thresholds.

    Returns dict of results for each threshold.
    """
    if thresholds is None:
        thresholds = [0.50, 0.55, 0.60, 0.65, 0.70]

    edges = model1_preds - vegas_lines
    abs_edges = np.abs(edges)

    # Model 1 alone baseline
    m1_hr, m1_n = compute_hit_rate(model1_preds, actual_points, vegas_lines, min_edge=min_edge)
    m1_dir = compute_directional_hit_rates(model1_preds, actual_points, vegas_lines, min_edge=min_edge)

    print(f"\n{'='*70}")
    print(f" COMBINED PIPELINE EVALUATION (edge >= {min_edge})")
    print(f"{'='*70}")
    print(f"\n  Model 1 alone:")
    m1_hr_s = f"{m1_hr:.1f}%" if m1_hr else "N/A"
    print(f"    HR: {m1_hr_s} ({m1_n} picks)")
    print(f"    OVER:  {m1_dir['over_hit_rate']}% ({m1_dir['over_graded']} picks)" if m1_dir['over_hit_rate'] else "    OVER: N/A")
    print(f"    UNDER: {m1_dir['under_hit_rate']}% ({m1_dir['under_graded']} picks)" if m1_dir['under_hit_rate'] else "    UNDER: N/A")

    results = {'model1_alone': {'hr': m1_hr, 'n': m1_n, 'dir': m1_dir}}

    print(f"\n  {'Threshold':<12s} {'HR':>8s} {'N':>5s} {'OVER HR':>10s} {'OVER N':>7s} {'UNDER HR':>10s} {'UNDER N':>8s} {'vs M1':>8s}")
    print(f"  {'-'*68}")

    m1_mask = abs_edges >= min_edge

    for thresh in thresholds:
        combined_mask = m1_mask & (model2_probs >= thresh)
        n_picks = int(combined_mask.sum())

        if n_picks == 0:
            print(f"  {thresh:<12.2f} {'N/A':>8s} {0:>5d} {'N/A':>10s} {0:>7d} {'N/A':>10s} {0:>8d} {'N/A':>8s}")
            results[f'thresh_{thresh}'] = {'hr': None, 'n': 0}
            continue

        c_preds = model1_preds[combined_mask]
        c_actuals = actual_points[combined_mask]
        c_lines = vegas_lines[combined_mask]
        c_edges = edges[combined_mask]

        # Overall HR
        c_hr, c_graded = compute_hit_rate(c_preds, c_actuals, c_lines, min_edge=0.0)

        # OVER/UNDER breakdown
        over_m = c_edges > 0
        under_m = c_edges < 0

        if over_m.sum() > 0:
            o_wins = (c_actuals[over_m] > c_lines[over_m]).sum()
            o_push = (c_actuals[over_m] == c_lines[over_m]).sum()
            o_graded = int(over_m.sum() - o_push)
            o_hr = round(o_wins / o_graded * 100, 1) if o_graded > 0 else None
        else:
            o_hr, o_graded = None, 0

        if under_m.sum() > 0:
            u_wins = (c_actuals[under_m] < c_lines[under_m]).sum()
            u_push = (c_actuals[under_m] == c_lines[under_m]).sum()
            u_graded = int(under_m.sum() - u_push)
            u_hr = round(u_wins / u_graded * 100, 1) if u_graded > 0 else None
        else:
            u_hr, u_graded = None, 0

        # Delta vs M1
        delta = ""
        if c_hr is not None and m1_hr is not None:
            d = c_hr - m1_hr
            delta = f"{d:+.1f}pp"

        c_hr_s = f"{c_hr:.1f}%" if c_hr else "N/A"
        o_hr_s = f"{o_hr:.1f}%" if o_hr else "N/A"
        u_hr_s = f"{u_hr:.1f}%" if u_hr else "N/A"

        print(f"  {thresh:<12.2f} {c_hr_s:>8s} {c_graded:>5d} {o_hr_s:>10s} {o_graded:>7d} {u_hr_s:>10s} {u_graded:>8d} {delta:>8s}")

        results[f'thresh_{thresh}'] = {
            'hr': c_hr, 'n': c_graded,
            'over_hr': o_hr, 'over_n': o_graded,
            'under_hr': u_hr, 'under_n': u_graded,
        }

    return results


def walkforward_combined(model1_preds, model2_probs, vegas_lines, actual_points,
                         game_dates, min_edge=3.0, threshold=0.55):
    """Per-week breakdown of combined pipeline."""
    dates_pd = pd.Series(pd.to_datetime(game_dates))
    week_labels = dates_pd.dt.to_period('W-SUN')
    unique_weeks = sorted(week_labels.unique())

    edges = model1_preds - vegas_lines
    abs_edges = np.abs(edges)

    print(f"\n{'='*80}")
    print(f" WALK-FORWARD: Model 1 alone vs Combined (threshold={threshold})")
    print(f"{'='*80}")
    print(f"  {'Week':<22s} {'M1 HR':>7s} {'M1 N':>5s} {'Comb HR':>8s} {'Comb N':>6s} {'Delta':>7s}")
    print(f"  {'-'*60}")

    for week in unique_weeks:
        mask = (week_labels == week).values

        # Model 1 alone
        w_m1_mask = mask & (abs_edges >= min_edge)
        if w_m1_mask.sum() > 0:
            m1_hr, m1_n = compute_hit_rate(
                model1_preds[w_m1_mask], actual_points[w_m1_mask],
                vegas_lines[w_m1_mask], min_edge=0.0)
        else:
            m1_hr, m1_n = None, 0

        # Combined
        w_c_mask = mask & (abs_edges >= min_edge) & (model2_probs >= threshold)
        if w_c_mask.sum() > 0:
            c_hr, c_n = compute_hit_rate(
                model1_preds[w_c_mask], actual_points[w_c_mask],
                vegas_lines[w_c_mask], min_edge=0.0)
        else:
            c_hr, c_n = None, 0

        m1_s = f"{m1_hr:.1f}%" if m1_hr else "N/A"
        c_s = f"{c_hr:.1f}%" if c_hr else "N/A"
        delta = ""
        if c_hr is not None and m1_hr is not None:
            delta = f"{c_hr - m1_hr:+.1f}pp"

        print(f"  {str(week):<22s} {m1_s:>7s} {m1_n:>5d} {c_s:>8s} {c_n:>6d} {delta:>7s}")


def display_model2_feature_importance(model, feature_names, model_type='catboost'):
    """Display Model 2 feature importance."""
    if model_type == 'logistic':
        coefs = np.abs(model.coef_[0])
        pairs = sorted(zip(feature_names, coefs), key=lambda x: -x[1])
        print(f"\n  Logistic Regression Coefficients (absolute):")
    else:
        importances = model.get_feature_importance()
        pairs = sorted(zip(feature_names, importances), key=lambda x: -x[1])
        print(f"\n  CatBoost Feature Importance:")

    for i, (name, imp) in enumerate(pairs, 1):
        bar = "█" * int(imp / max(pairs[0][1], 0.001) * 20)
        print(f"    {i:2d}. {name:<25s} {imp:7.3f}  {bar}")


def main():
    args = parse_args()

    # Select contract
    if args.feature_set == 'v12':
        contract = V12_CONTRACT
    elif args.feature_set == 'v11':
        contract = V11_CONTRACT
    else:
        contract = V9_CONTRACT

    print("=" * 70)
    print(f" EDGE CLASSIFIER (Model 2): {args.name}")
    print("=" * 70)
    print(f"Model 1:     {args.model1_path}")
    print(f"Feature Set: {args.feature_set} ({contract.feature_count} features)")
    print(f"Training:    {args.train_start} to {args.train_end}")
    print(f"Evaluation:  {args.eval_start} to {args.eval_end}")
    print(f"Min edge:    {args.min_edge_train}")
    print()

    # Validate dates
    train_end_dt = datetime.strptime(args.train_end, '%Y-%m-%d').date()
    eval_start_dt = datetime.strptime(args.eval_start, '%Y-%m-%d').date()
    if train_end_dt >= eval_start_dt:
        print("BLOCKED: Training/eval date overlap!")
        return

    # Load Model 1
    model1_path = Path(args.model1_path)
    if not model1_path.exists():
        print(f"ERROR: Model 1 not found at {model1_path}")
        return
    print(f"Loading Model 1 from {model1_path}...")
    model1 = cb.CatBoostRegressor()
    model1.load_model(str(model1_path))
    print(f"  Model 1 loaded ({model1.tree_count_} trees)")

    # Connect to BigQuery
    client = bigquery.Client(project=PROJECT_ID)

    # --- Load Training Data ---
    print(f"\nLoading training data ({args.train_start} to {args.train_end})...")
    df_train = load_train_data(client, args.train_start, args.train_end)
    print(f"  {len(df_train):,} samples loaded")

    # Augment features
    if args.feature_set in ('v11', 'v12'):
        print("  Augmenting V11 features...")
        df_train = augment_v11_features(client, df_train)
    if args.feature_set == 'v12':
        print("  Augmenting V12 features...")
        df_train = augment_v12_features(client, df_train)

    # Extract vegas lines from features array (training data doesn't have vegas_line column)
    df_train = extract_vegas_from_features(df_train)
    valid_vegas = df_train['vegas_line'].notna()
    print(f"  Vegas line coverage: {valid_vegas.sum():,}/{len(df_train):,} ({100*valid_vegas.mean():.0f}%)")
    df_train = df_train[valid_vegas].reset_index(drop=True)

    # --- Load Eval Data ---
    print(f"\nLoading eval data ({args.eval_start} to {args.eval_end})...")
    if args.use_production_lines:
        df_eval = load_eval_data_from_production(client, args.eval_start, args.eval_end)
        if len(df_eval) == 0:
            print("  No production lines, falling back to raw lines...")
            df_eval = load_eval_data(client, args.eval_start, args.eval_end, args.line_source)
    else:
        df_eval = load_eval_data(client, args.eval_start, args.eval_end, args.line_source)
    print(f"  {len(df_eval):,} samples loaded")

    if args.feature_set in ('v11', 'v12'):
        print("  Augmenting V11 features...")
        df_eval = augment_v11_features(client, df_eval)
    if args.feature_set == 'v12':
        print("  Augmenting V12 features...")
        df_eval = augment_v12_features(client, df_eval)

    if len(df_train) < 500 or len(df_eval) < 50:
        print(f"ERROR: Not enough data (train={len(df_train)}, eval={len(df_eval)})")
        return

    # --- Prepare Model 1 Features ---
    # Model 1 is no-vegas, so exclude vegas features
    exclude = VEGAS_FEATURE_NAMES.copy()
    print(f"\nPreparing Model 1 features (excluding {len(exclude)} vegas features)...")
    X_train_m1, y_train = prepare_features(df_train, contract=contract, exclude_features=exclude)
    X_eval_m1, y_eval = prepare_features(df_eval, contract=contract, exclude_features=exclude)
    print(f"  Train: {X_train_m1.shape}, Eval: {X_eval_m1.shape}")

    vegas_train = df_train['vegas_line'].values
    vegas_eval = df_eval['vegas_line'].values
    actual_train = y_train.values
    actual_eval = y_eval.values

    # --- Generate Model 1 Predictions ---
    print("\nGenerating Model 1 predictions (eval)...")
    m1_preds_eval = model1.predict(X_eval_m1)

    eval_mae = mean_absolute_error(actual_eval, m1_preds_eval)
    m1_hr_eval, m1_n_eval = compute_hit_rate(m1_preds_eval, actual_eval, vegas_eval, min_edge=3.0)
    print(f"  Eval MAE:  {eval_mae:.2f}")
    print(f"  Eval HR 3+: {m1_hr_eval:.1f}% ({m1_n_eval} picks)" if m1_hr_eval else "  Eval HR 3+: N/A")

    # --- Generate OOF Predictions for Model 2 Training ---
    # CRITICAL: In-sample Model 1 predictions have ~88% hit rate (overfit).
    # Model 2 can't learn from 88% positive class. OOF gives realistic ~55% hit rate.
    print("\nGenerating out-of-fold predictions for Model 2 training...")
    m1_preds_oof, oof_valid_mask = generate_oof_predictions(
        X_train_m1, y_train, df_train['game_date'], n_folds=5
    )

    # Also show in-sample for comparison
    m1_preds_insample = model1.predict(X_train_m1)
    insample_mae = mean_absolute_error(actual_train, m1_preds_insample)
    insample_hr, insample_n = compute_hit_rate(m1_preds_insample, actual_train, vegas_train, min_edge=2.0)
    print(f"  In-sample MAE: {insample_mae:.2f}, HR |edge|>=2: {insample_hr:.1f}% ({insample_n} picks)")

    oof_hr_all, oof_n_all = compute_hit_rate(
        m1_preds_oof[oof_valid_mask], actual_train[oof_valid_mask],
        vegas_train[oof_valid_mask], min_edge=2.0)
    if oof_hr_all:
        print(f"  OOF HR |edge|>=2: {oof_hr_all:.1f}% ({oof_n_all} picks)  <-- realistic")

    # Filter to rows with OOF predictions
    df_train_oof = df_train[oof_valid_mask].reset_index(drop=True)
    m1_preds_train = m1_preds_oof[oof_valid_mask]
    vegas_train_oof = vegas_train[oof_valid_mask]
    actual_train_oof = actual_train[oof_valid_mask]

    # --- Build Model 2 Features ---
    print("\nBuilding Model 2 features...")
    X2_train = build_model2_features(df_train_oof, m1_preds_train, vegas_train_oof)
    X2_eval = build_model2_features(df_eval, m1_preds_eval, vegas_eval)

    # Compute binary target
    y2_train_raw = compute_target(m1_preds_train, vegas_train_oof, actual_train_oof)
    y2_eval_raw = compute_target(m1_preds_eval, vegas_eval, actual_eval)

    # Filter out pushes
    valid_train_m2 = ~np.isnan(y2_train_raw)
    valid_eval = ~np.isnan(y2_eval_raw)

    X2_train_valid = X2_train[valid_train_m2].reset_index(drop=True)
    y2_train_valid = y2_train_raw[valid_train_m2]
    edges_train = m1_preds_train - vegas_train_oof
    edges_train_valid = edges_train[valid_train_m2]

    X2_eval_valid = X2_eval[valid_eval].reset_index(drop=True)
    y2_eval_valid = y2_eval_raw[valid_eval]

    print(f"  Train (OOF, no pushes): {len(y2_train_valid)} ({y2_train_valid.mean():.3f} hit rate)")
    print(f"  Eval (no pushes):       {len(y2_eval_valid)} ({y2_eval_valid.mean():.3f} hit rate)")

    # Filter training to |edge| >= min_edge_train
    edge_mask = np.abs(edges_train_valid) >= args.min_edge_train
    X2_train_filtered = X2_train_valid[edge_mask].reset_index(drop=True)
    y2_train_filtered = y2_train_valid[edge_mask]

    print(f"  Train (|edge| >= {args.min_edge_train}): {len(y2_train_filtered)} ({y2_train_filtered.mean():.3f} hit rate)")

    if len(y2_train_filtered) < 100:
        print(f"ERROR: Too few training samples after edge filter ({len(y2_train_filtered)})")
        return

    # --- Feature Statistics ---
    print(f"\n{'='*70}")
    print(f" MODEL 2 FEATURE STATISTICS (training set, |edge| >= {args.min_edge_train})")
    print(f"{'='*70}")
    for col in MODEL2_FEATURE_NAMES:
        vals = X2_train_filtered[col]
        print(f"  {col:<25s}  mean={vals.mean():8.3f}  std={vals.std():7.3f}  "
              f"min={vals.min():7.2f}  max={vals.max():7.2f}")

    # --- Train Logistic Regression (Baseline) ---
    print(f"\n{'='*70}")
    print(f" LOGISTIC REGRESSION (baseline)")
    print(f"{'='*70}")
    lr_model, lr_scaler = train_logistic(X2_train_filtered, y2_train_filtered)

    # Predict on eval
    X2_eval_scaled = lr_scaler.transform(X2_eval_valid)
    lr_probs_eval = lr_model.predict_proba(X2_eval_scaled)[:, 1]
    lr_auc = evaluate_model2("Logistic Regression (eval)", y2_eval_valid, lr_probs_eval)

    # Logistic coefficients
    display_model2_feature_importance(lr_model, MODEL2_FEATURE_NAMES, model_type='logistic')

    # --- Train CatBoost Classifier ---
    print(f"\n{'='*70}")
    print(f" CATBOOST CLASSIFIER")
    print(f"{'='*70}")

    if len(y2_train_filtered) >= 200:
        cb_model = train_catboost_classifier(X2_train_filtered, y2_train_filtered)
        cb_probs_eval = cb_model.predict_proba(X2_eval_valid)[:, 1]
        cb_auc = evaluate_model2("CatBoost Classifier (eval)", y2_eval_valid, cb_probs_eval)
        display_model2_feature_importance(cb_model, MODEL2_FEATURE_NAMES, model_type='catboost')
    else:
        print("  Skipping CatBoost (need >= 200 training samples)")
        cb_model = None
        cb_probs_eval = None
        cb_auc = 0.0

    # --- Select Best Model 2 ---
    if cb_model is not None and cb_auc > lr_auc:
        best_name = "CatBoost"
        best_probs_eval = cb_probs_eval
        best_auc = cb_auc
    else:
        best_name = "LogisticRegression"
        best_probs_eval = lr_probs_eval
        best_auc = lr_auc

    print(f"\n  Best Model 2: {best_name} (AUC={best_auc:.4f})")

    # --- Combined Pipeline Evaluation ---
    thresholds = [float(t) for t in args.confidence_thresholds.split(',')]

    # We need the probs aligned to the full eval set (not just valid)
    # Create full-length probs array (pushes get 0.0 so they won't pass threshold)
    full_probs = np.zeros(len(m1_preds_eval))
    full_probs[valid_eval] = best_probs_eval

    results = evaluate_combined(
        m1_preds_eval, full_probs, vegas_eval, actual_eval,
        min_edge=3.0, thresholds=thresholds,
    )

    # Also show edge 5+ combined
    print(f"\n  --- Edge 5+ combined ---")
    evaluate_combined(
        m1_preds_eval, full_probs, vegas_eval, actual_eval,
        min_edge=5.0, thresholds=thresholds,
    )

    # --- Walk-Forward (per-week) ---
    if args.walkforward:
        # Find best threshold (highest HR with >= 3 picks/day)
        eval_days = (datetime.strptime(args.eval_end, '%Y-%m-%d') -
                     datetime.strptime(args.eval_start, '%Y-%m-%d')).days + 1
        best_thresh = thresholds[0]
        for t in thresholds:
            key = f'thresh_{t}'
            if key in results and results[key]['n'] is not None:
                picks_per_day = results[key]['n'] / max(eval_days, 1)
                if picks_per_day >= 3 and results[key].get('hr') is not None:
                    if results[key]['hr'] >= (results.get(f'thresh_{best_thresh}', {}).get('hr') or 0):
                        best_thresh = t

        walkforward_combined(
            m1_preds_eval, full_probs, vegas_eval, actual_eval,
            df_eval['game_date'].values,
            min_edge=3.0, threshold=best_thresh,
        )

    # --- Segmented Analysis ---
    print(f"\n{'='*70}")
    print(f" SEGMENTED ANALYSIS (Model 1 alone, edge >= 3)")
    print(f"{'='*70}")

    # Extract season averages for tier analysis
    season_avgs = []
    for _, row in df_eval.iterrows():
        fd = dict(zip(row['feature_names'], row['features']))
        season_avgs.append(float(fd.get('points_avg_season', 10.0)))
    season_avgs = np.array(season_avgs)

    seg = compute_segmented_hit_rates(
        m1_preds_eval, actual_eval, vegas_eval,
        season_avgs=season_avgs, min_edge=3.0,
    )

    print("\n  By Tier:")
    for name, data in seg['by_tier'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] else "N/A"
        print(f"    {name:<20s} {hr_s:>8s} ({data['n']} picks)")

    print("\n  By Direction:")
    for name, data in seg['by_direction'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] else "N/A"
        print(f"    {name:<20s} {hr_s:>8s} ({data['n']} picks)")

    print("\n  By Tier x Direction:")
    for name, data in seg['by_tier_direction'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] else "N/A"
        print(f"    {name:<30s} {hr_s:>8s} ({data['n']} picks)")

    print("\n  By Edge Bucket:")
    for name, data in seg['by_edge_bucket'].items():
        hr_s = f"{data['hr']:.1f}%" if data['hr'] else "N/A"
        print(f"    {name:<20s} {hr_s:>8s} ({data['n']} picks)")

    # --- Summary ---
    print(f"\n{'='*70}")
    print(f" SUMMARY")
    print(f"{'='*70}")
    print(f"  Experiment:     {args.name}")
    print(f"  Model 1:        {args.model1_path}")
    print(f"  Model 2:        {best_name} (AUC={best_auc:.4f})")
    m1_hr_s = f"{m1_hr_eval:.1f}%" if m1_hr_eval else "N/A"
    print(f"  Model 1 alone:  {m1_hr_s} HR @ edge 3+ ({m1_n_eval} picks)")

    # Best combined result
    best_result = None
    for t in thresholds:
        key = f'thresh_{t}'
        if key in results and results[key].get('hr') is not None:
            if best_result is None or results[key]['hr'] > best_result['hr']:
                best_result = results[key]
                best_result['threshold'] = t

    if best_result and best_result.get('hr'):
        print(f"  Best combined:  {best_result['hr']:.1f}% HR @ edge 3+ & conf >= {best_result['threshold']} ({best_result['n']} picks)")
        if m1_hr_eval:
            delta = best_result['hr'] - m1_hr_eval
            print(f"  Delta:          {delta:+.1f}pp")
    else:
        print(f"  Best combined:  N/A (no valid threshold)")

    verdict = "INCONCLUSIVE"
    if best_auc > 0.55 and best_result and best_result.get('hr') and m1_hr_eval:
        if best_result['hr'] > m1_hr_eval and best_result['n'] >= 30:
            verdict = "MODEL 2 ADDS VALUE"
        elif best_result['hr'] >= m1_hr_eval:
            verdict = "MODEL 2 NEUTRAL (no degradation)"
        else:
            verdict = "MODEL 2 HURTS (use Model 1 alone)"
    elif best_auc <= 0.55:
        verdict = "MODEL 2 NOT USEFUL (AUC <= 0.55)"

    print(f"  Verdict:        {verdict}")
    print()


if __name__ == '__main__':
    main()
