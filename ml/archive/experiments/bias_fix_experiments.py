#!/usr/bin/env python3
"""
Bias Fix Experiments - Test Different Approaches to Fix Regression-to-Mean

Session 107: Comprehensive testing of approaches to fix star under-prediction.
Session 108: Added gentler calibration variants and edge-specific strategies.

Approaches:
1. Sample Weighting - Weight star samples higher during training
2. Quantile Regression - Predict 55-60th percentile instead of mean
3. Residual Modeling - Predict (actual - vegas) instead of raw points
4. Post-hoc Calibration - Adjust predictions after the model
   - Original (aggressive) calibration
   - Gentle calibration (Session 108)
5. Combined Approaches - Mix multiple methods
6. Edge-Specific Strategies - Different calibration for different edge tiers

Usage:
    # Test all approaches
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --all

    # Test specific approach
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach sample_weighting
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach quantile
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach residual
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach calibration
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach gentle
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach combined
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --approach edge_specific

    # Dry run
    PYTHONPATH=. python ml/experiments/bias_fix_experiments.py --all --dry-run
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
import catboost as cb

# Import from quick_retrain for consistency
from ml.experiments.quick_retrain import (
    load_train_data,
    load_eval_data,
    prepare_features,
    compute_hit_rate,
    compute_tier_bias,
    FEATURES,
    V9_BASELINE,
    PROJECT_ID,
    MODEL_OUTPUT_DIR,
)

# =============================================================================
# APPROACH 1: Sample Weighting
# =============================================================================

def calculate_tier_weights(y_train: pd.Series, star_boost: float = 3.0) -> np.ndarray:
    """
    Weight star player samples higher during training.

    Args:
        y_train: Target values (actual points scored in that game)
        star_boost: How much to weight 25+ point performances (default 3x)

    Returns:
        Normalized weights array
    """
    weights = np.ones(len(y_train))

    # Weight based on actual points scored (not player tier)
    # This boosts games where players scored high
    weights[y_train >= 25] = star_boost        # Star performances
    weights[(y_train >= 15) & (y_train < 25)] = 2.0  # Starter performances
    weights[(y_train >= 8) & (y_train < 15)] = 1.0   # Role performances
    weights[y_train < 8] = 0.5                  # Bench performances (downweight)

    # Normalize to preserve effective sample size
    weights = weights / weights.mean()

    return weights


def train_with_sample_weights(X_train, y_train, X_val, y_val, star_boost=3.0):
    """Train CatBoost with tier-based sample weights."""
    weights = calculate_tier_weights(y_train, star_boost)

    model = cb.CatBoostRegressor(
        iterations=1000,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=3.0,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50
    )

    model.fit(X_train, y_train, eval_set=(X_val, y_val),
              sample_weight=weights, verbose=False)

    return model


# =============================================================================
# APPROACH 2: Quantile Regression
# =============================================================================

def train_quantile_model(X_train, y_train, X_val, y_val, alpha=0.55):
    """
    Train quantile regression model.

    Args:
        alpha: Quantile to predict (0.5 = median, 0.55 = slightly above median)
               Higher alpha biases predictions upward.
    """
    model = cb.CatBoostRegressor(
        loss_function=f'Quantile:alpha={alpha}',
        iterations=1000,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=3.0,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50
    )

    model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=False)

    return model


# =============================================================================
# APPROACH 3: Residual Modeling
# =============================================================================

def prepare_residual_data(df, features_col='features', feature_names_col='feature_names'):
    """
    Prepare data for residual modeling: target = actual - vegas_line.

    Vegas line is at index 25 in the feature array.
    """
    X, y_actual = prepare_features(df)

    # Extract vegas line from features (index 25)
    vegas_lines = X['vegas_points_line'].values

    # Filter to only records with vegas lines
    has_vegas = vegas_lines > 0
    X_filtered = X[has_vegas].reset_index(drop=True)
    y_actual_filtered = y_actual[has_vegas].reset_index(drop=True)
    vegas_filtered = vegas_lines[has_vegas]

    # Target is the residual (actual - vegas)
    y_residual = y_actual_filtered - vegas_filtered

    return X_filtered, y_residual, y_actual_filtered, vegas_filtered


def train_residual_model(X_train, y_residual_train, X_val, y_residual_val):
    """Train model to predict deviation from Vegas line."""
    model = cb.CatBoostRegressor(
        iterations=1000,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=3.0,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50
    )

    model.fit(X_train, y_residual_train, eval_set=(X_val, y_residual_val), verbose=False)

    return model


def predict_with_residual_model(model, X, vegas_lines):
    """Final prediction = Vegas + model(features)."""
    residual_preds = model.predict(X)
    return vegas_lines + residual_preds


# =============================================================================
# APPROACH 4: Post-hoc Calibration
# =============================================================================

def calibrate_by_tier_multiplicative(predictions, season_avgs, factors=None):
    """
    Apply tier-based multiplicative calibration.

    Args:
        predictions: Raw model predictions
        season_avgs: Player season averages (to determine tier)
        factors: Dict of tier -> multiplier (default based on bias analysis)
    """
    if factors is None:
        # Based on Session 107 bias analysis:
        # Stars: -9.1 bias → need ~1.4x boost
        # Starters: -2.6 bias → need ~1.15x boost
        # Role: +1.9 bias → need ~0.85x reduction
        # Bench: +6.2 bias → need ~0.5x reduction
        factors = {
            'star': 1.40,      # 25+ ppg
            'high_starter': 1.25,  # 20-25 ppg
            'starter': 1.15,   # 15-20 ppg
            'role': 0.90,      # 8-15 ppg
            'bench': 0.60,     # <8 ppg
        }

    calibrated = np.zeros_like(predictions)

    for i, (pred, avg) in enumerate(zip(predictions, season_avgs)):
        if avg >= 25:
            calibrated[i] = pred * factors['star']
        elif avg >= 20:
            calibrated[i] = pred * factors['high_starter']
        elif avg >= 15:
            calibrated[i] = pred * factors['starter']
        elif avg >= 8:
            calibrated[i] = pred * factors['role']
        else:
            calibrated[i] = pred * factors['bench']

    return calibrated


def calibrate_by_tier_additive(predictions, season_avgs, offsets=None):
    """
    Apply tier-based additive calibration.

    Args:
        predictions: Raw model predictions
        season_avgs: Player season averages (to determine tier)
        offsets: Dict of tier -> points to add (default based on bias analysis)
    """
    if offsets is None:
        # Based on Session 107 bias analysis
        offsets = {
            'star': 8.0,       # 25+ ppg: add 8 points
            'high_starter': 5.0,   # 20-25 ppg
            'starter': 2.5,    # 15-20 ppg
            'role': -1.5,      # 8-15 ppg
            'bench': -5.0,     # <8 ppg
        }

    calibrated = np.zeros_like(predictions)

    for i, (pred, avg) in enumerate(zip(predictions, season_avgs)):
        if avg >= 25:
            calibrated[i] = pred + offsets['star']
        elif avg >= 20:
            calibrated[i] = pred + offsets['high_starter']
        elif avg >= 15:
            calibrated[i] = pred + offsets['starter']
        elif avg >= 8:
            calibrated[i] = pred + offsets['role']
        else:
            calibrated[i] = pred + offsets['bench']

    return calibrated


# =============================================================================
# SESSION 108: GENTLE CALIBRATION VARIANTS
# =============================================================================

# Gentler additive calibration offsets (Session 108)
GENTLE_ADDITIVE_OFFSETS = {
    'star': 3.0,        # 25+ ppg: add 3 points (was +8)
    'high_starter': 2.0,    # 20-25 ppg (was +5)
    'starter': 1.5,     # 15-20 ppg (was +2.5)
    'role': 0.0,        # 8-15 ppg (was -1.5)
    'bench': -2.0,      # <8 ppg (was -5)
}

# Gentler multiplicative calibration factors (Session 108)
GENTLE_MULTIPLICATIVE_FACTORS = {
    'star': 1.15,       # 25+ ppg (was 1.40)
    'high_starter': 1.10,   # 20-25 ppg (was 1.25)
    'starter': 1.05,    # 15-20 ppg (was 1.15)
    'role': 1.0,        # 8-15 ppg (was 0.90)
    'bench': 0.90,      # <8 ppg (was 0.60)
}


def calibrate_edge_specific(predictions, season_avgs, vegas_lines,
                            high_edge_threshold=5.0, medium_edge_threshold=3.0):
    """
    Apply calibration only to high-edge picks.

    Session 108: Different calibration strategies by edge tier:
    - High edge (5+): Apply gentle additive calibration
    - Medium edge (3-5): Apply very gentle calibration (50% of gentle)
    - Low edge (<3): No calibration (these are "PASS" in production anyway)

    Args:
        predictions: Raw model predictions
        season_avgs: Player season averages
        vegas_lines: Vegas point lines
        high_edge_threshold: Threshold for full calibration (default 5.0)
        medium_edge_threshold: Threshold for partial calibration (default 3.0)

    Returns:
        Calibrated predictions
    """
    calibrated = predictions.copy()
    edges = np.abs(predictions - vegas_lines)

    for i, (pred, avg, edge) in enumerate(zip(predictions, season_avgs, edges)):
        if edge >= high_edge_threshold:
            # Full gentle calibration for high-edge picks
            if avg >= 25:
                calibrated[i] = pred + 3.0
            elif avg >= 20:
                calibrated[i] = pred + 2.0
            elif avg >= 15:
                calibrated[i] = pred + 1.5
            elif avg >= 8:
                calibrated[i] = pred + 0.0
            else:
                calibrated[i] = pred - 2.0
        elif edge >= medium_edge_threshold:
            # Half calibration for medium-edge picks
            if avg >= 25:
                calibrated[i] = pred + 1.5
            elif avg >= 20:
                calibrated[i] = pred + 1.0
            elif avg >= 15:
                calibrated[i] = pred + 0.75
            elif avg >= 8:
                calibrated[i] = pred + 0.0
            else:
                calibrated[i] = pred - 1.0
        # Low edge: keep original prediction

    return calibrated


def calibrate_combined_sw_gentle(model, X_train, y_train, X_val, y_val, X_eval, season_avgs):
    """
    Combined approach: Sample weighting (2x) + Gentle additive calibration.

    Session 108: Test if combining training-time and prediction-time adjustments
    works better than either alone.
    """
    # Train with sample weighting
    weights = calculate_tier_weights(y_train, star_boost=2.0)  # Gentler 2x vs 3x

    model = cb.CatBoostRegressor(
        iterations=1000,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=3.0,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=50
    )
    model.fit(X_train, y_train, eval_set=(X_val, y_val),
              sample_weight=weights, verbose=False)

    # Get base predictions
    preds = model.predict(X_eval)

    # Apply gentle calibration
    calibrated = calibrate_by_tier_additive(preds, season_avgs, GENTLE_ADDITIVE_OFFSETS)

    return calibrated, model


# =============================================================================
# EVALUATION
# =============================================================================

def evaluate_approach(name, preds, y_actual, vegas_lines, season_avgs=None):
    """Evaluate predictions and return metrics."""
    mae = mean_absolute_error(y_actual, preds)

    hr_all, bets_all = compute_hit_rate(preds, y_actual.values, vegas_lines, min_edge=1.0)
    hr_edge3, bets_edge3 = compute_hit_rate(preds, y_actual.values, vegas_lines, min_edge=3.0)
    hr_edge5, bets_edge5 = compute_hit_rate(preds, y_actual.values, vegas_lines, min_edge=5.0)

    tier_bias = compute_tier_bias(preds, y_actual.values)

    return {
        'name': name,
        'mae': round(mae, 3),
        'hr_all': hr_all,
        'hr_edge3': hr_edge3,
        'hr_edge5': hr_edge5,
        'bets_all': bets_all,
        'bets_edge3': bets_edge3,
        'bets_edge5': bets_edge5,
        'tier_bias': tier_bias,
    }


def print_results(results):
    """Print comparison table of results."""
    print("\n" + "=" * 80)
    print("RESULTS COMPARISON")
    print("=" * 80)

    print(f"\n{'Approach':<30} {'MAE':>8} {'HR All':>8} {'HR 3+':>8} {'HR 5+':>8}")
    print("-" * 70)

    for r in results:
        hr_all = f"{r['hr_all']:.1f}%" if r['hr_all'] else "N/A"
        hr_3 = f"{r['hr_edge3']:.1f}%" if r['hr_edge3'] else "N/A"
        hr_5 = f"{r['hr_edge5']:.1f}%" if r['hr_edge5'] else "N/A"
        print(f"{r['name']:<30} {r['mae']:>8.3f} {hr_all:>8} {hr_3:>8} {hr_5:>8}")

    print("\n" + "-" * 80)
    print("TIER BIAS (Target: 0 for all tiers)")
    print("-" * 80)

    print(f"\n{'Approach':<30} {'Stars':>10} {'Starters':>10} {'Role':>10} {'Bench':>10}")
    print("-" * 70)

    for r in results:
        tb = r['tier_bias']
        stars = f"{tb['Stars (25+)']['bias']:+.1f}" if tb['Stars (25+)']['bias'] else "N/A"
        starters = f"{tb['Starters (15-24)']['bias']:+.1f}" if tb['Starters (15-24)']['bias'] else "N/A"
        role = f"{tb['Role (5-14)']['bias']:+.1f}" if tb['Role (5-14)']['bias'] else "N/A"
        bench = f"{tb['Bench (<5)']['bias']:+.1f}" if tb['Bench (<5)']['bias'] else "N/A"
        print(f"{r['name']:<30} {stars:>10} {starters:>10} {role:>10} {bench:>10}")

    # Highlight best approach
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)

    # Find approach with lowest star bias
    best_star_bias = min(results, key=lambda x: abs(x['tier_bias']['Stars (25+)']['bias'] or 999))
    best_hr = max(results, key=lambda x: x['hr_edge3'] or 0)

    print(f"\nBest for star bias: {best_star_bias['name']} (bias: {best_star_bias['tier_bias']['Stars (25+)']['bias']:+.1f})")
    print(f"Best for hit rate (3+): {best_hr['name']} ({best_hr['hr_edge3']:.1f}%)")


# =============================================================================
# MAIN
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description='Test bias fix approaches')
    parser.add_argument('--approach', choices=[
        'sample_weighting', 'quantile', 'residual', 'calibration',
        'gentle', 'combined', 'edge_specific', 'all'
    ], default='all', help='Which approach to test')
    parser.add_argument('--train-start', default='2025-11-13', help='Training start date')
    parser.add_argument('--train-end', default='2026-01-25', help='Training end date')
    parser.add_argument('--eval-start', default='2026-01-26', help='Eval start date')
    parser.add_argument('--eval-end', default='2026-02-02', help='Eval end date')
    parser.add_argument('--dry-run', action='store_true', help='Show plan only')
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 80)
    print("BIAS FIX EXPERIMENTS - Session 107")
    print("=" * 80)
    print(f"\nTraining:   {args.train_start} to {args.train_end}")
    print(f"Evaluation: {args.eval_start} to {args.eval_end}")
    print(f"Approach:   {args.approach}")

    if args.dry_run:
        print("\nDRY RUN - would test the following approaches:")
        if args.approach in ['sample_weighting', 'all']:
            print("  - Sample Weighting (3x boost for 25+ pt games)")
            print("  - Sample Weighting (5x boost for 25+ pt games)")
        if args.approach in ['quantile', 'all']:
            print("  - Quantile Regression (alpha=0.55, 0.60)")
        if args.approach in ['residual', 'all']:
            print("  - Residual Modeling (predict actual - vegas)")
        if args.approach in ['calibration', 'all']:
            print("  - Post-hoc Calibration (additive and multiplicative - original aggressive)")
        if args.approach in ['gentle', 'all']:
            print("  - GENTLE Additive Calibration (star:+3, starter:+1.5, role:0, bench:-2)")
            print("  - GENTLE Multiplicative Calibration (star:1.15, starter:1.05, role:1.0, bench:0.9)")
            print("  - Quantile 0.52 (very slight upward bias)")
        if args.approach in ['combined', 'all']:
            print("  - Combined: Sample Weighting (2x) + Gentle Additive Calibration")
        if args.approach in ['edge_specific', 'all']:
            print("  - Edge-Specific: Full calibration for 5+ edge, half for 3-5, none for <3")
        return

    client = bigquery.Client(project=PROJECT_ID)

    # Load data
    print("\nLoading training data...")
    df_train = load_train_data(client, args.train_start, args.train_end)
    print(f"  {len(df_train):,} samples")

    print("Loading evaluation data...")
    df_eval = load_eval_data(client, args.eval_start, args.eval_end)
    print(f"  {len(df_eval):,} samples")

    # Prepare features
    X_train_full, y_train_full = prepare_features(df_train)
    X_eval, y_eval = prepare_features(df_eval)
    vegas_lines = df_eval['vegas_line'].values
    season_avgs = X_eval['points_avg_season'].values

    X_train, X_val, y_train, y_val = train_test_split(
        X_train_full, y_train_full, test_size=0.15, random_state=42
    )

    results = []

    # Baseline
    print("\nTraining baseline model...")
    baseline_model = cb.CatBoostRegressor(
        iterations=1000, learning_rate=0.05, depth=6,
        l2_leaf_reg=3.0, random_seed=42, verbose=False, early_stopping_rounds=50
    )
    baseline_model.fit(X_train, y_train, eval_set=(X_val, y_val), verbose=False)
    baseline_preds = baseline_model.predict(X_eval)
    results.append(evaluate_approach("Baseline (V9-style)", baseline_preds, y_eval, vegas_lines))

    # Approach 1: Sample Weighting
    if args.approach in ['sample_weighting', 'all']:
        print("Training with sample weighting (3x stars)...")
        sw_model = train_with_sample_weights(X_train, y_train, X_val, y_val, star_boost=3.0)
        sw_preds = sw_model.predict(X_eval)
        results.append(evaluate_approach("Sample Weighting (3x)", sw_preds, y_eval, vegas_lines))

        print("Training with sample weighting (5x stars)...")
        sw_model_5x = train_with_sample_weights(X_train, y_train, X_val, y_val, star_boost=5.0)
        sw_preds_5x = sw_model_5x.predict(X_eval)
        results.append(evaluate_approach("Sample Weighting (5x)", sw_preds_5x, y_eval, vegas_lines))

    # Approach 2: Quantile Regression
    if args.approach in ['quantile', 'all']:
        for alpha in [0.55, 0.60]:
            print(f"Training quantile model (alpha={alpha})...")
            q_model = train_quantile_model(X_train, y_train, X_val, y_val, alpha=alpha)
            q_preds = q_model.predict(X_eval)
            results.append(evaluate_approach(f"Quantile (alpha={alpha})", q_preds, y_eval, vegas_lines))

    # Approach 3: Residual Modeling
    if args.approach in ['residual', 'all']:
        print("Preparing residual data...")
        # Need to reload and filter for vegas availability
        X_res_train, y_res_train, y_actual_train, vegas_train = prepare_residual_data(df_train)
        X_res_eval, y_res_eval, y_actual_eval, vegas_eval = prepare_residual_data(df_eval)

        if len(X_res_train) > 1000 and len(X_res_eval) > 100:
            X_rt, X_rv, y_rt, y_rv = train_test_split(
                X_res_train, y_res_train, test_size=0.15, random_state=42
            )

            print("Training residual model...")
            res_model = train_residual_model(X_rt, y_rt, X_rv, y_rv)
            res_preds = predict_with_residual_model(res_model, X_res_eval, vegas_eval)
            results.append(evaluate_approach("Residual Model", res_preds, y_actual_eval, vegas_eval))
        else:
            print("  Not enough data with Vegas lines for residual modeling")

    # Approach 4: Post-hoc Calibration (using baseline model) - ORIGINAL AGGRESSIVE
    if args.approach in ['calibration', 'all']:
        print("Applying additive calibration (original)...")
        cal_add_preds = calibrate_by_tier_additive(baseline_preds, season_avgs)
        results.append(evaluate_approach("Calibration (Additive-Orig)", cal_add_preds, y_eval, vegas_lines))

        print("Applying multiplicative calibration (original)...")
        cal_mult_preds = calibrate_by_tier_multiplicative(baseline_preds, season_avgs)
        results.append(evaluate_approach("Calibration (Mult-Orig)", cal_mult_preds, y_eval, vegas_lines))

    # Approach 5: GENTLE Calibration (Session 108)
    if args.approach in ['gentle', 'all']:
        print("\n--- GENTLE CALIBRATION EXPERIMENTS (Session 108) ---")

        print("Applying GENTLE additive calibration...")
        gentle_add_preds = calibrate_by_tier_additive(baseline_preds, season_avgs, GENTLE_ADDITIVE_OFFSETS)
        results.append(evaluate_approach("GENTLE Additive", gentle_add_preds, y_eval, vegas_lines))

        print("Applying GENTLE multiplicative calibration...")
        gentle_mult_preds = calibrate_by_tier_multiplicative(baseline_preds, season_avgs, GENTLE_MULTIPLICATIVE_FACTORS)
        results.append(evaluate_approach("GENTLE Multiplicative", gentle_mult_preds, y_eval, vegas_lines))

        print("Training quantile model (alpha=0.52 - very slight upward)...")
        q_model_052 = train_quantile_model(X_train, y_train, X_val, y_val, alpha=0.52)
        q_preds_052 = q_model_052.predict(X_eval)
        results.append(evaluate_approach("Quantile (alpha=0.52)", q_preds_052, y_eval, vegas_lines))

    # Approach 6: Combined Approaches (Session 108)
    if args.approach in ['combined', 'all']:
        print("\n--- COMBINED APPROACHES (Session 108) ---")

        print("Training: Sample Weighting (2x) + Gentle Calibration...")
        combined_preds, _ = calibrate_combined_sw_gentle(
            None, X_train, y_train, X_val, y_val, X_eval, season_avgs
        )
        results.append(evaluate_approach("SW(2x) + Gentle Add", combined_preds, y_eval, vegas_lines))

        # Quantile + gentle calibration
        print("Training: Quantile (0.52) + Half-Gentle Calibration...")
        q_base = q_model_052.predict(X_eval) if 'q_model_052' in dir() else train_quantile_model(
            X_train, y_train, X_val, y_val, alpha=0.52
        ).predict(X_eval)
        half_gentle_offsets = {k: v/2 for k, v in GENTLE_ADDITIVE_OFFSETS.items()}
        q_plus_gentle = calibrate_by_tier_additive(q_base, season_avgs, half_gentle_offsets)
        results.append(evaluate_approach("Quantile(0.52)+HalfGentle", q_plus_gentle, y_eval, vegas_lines))

    # Approach 7: Edge-Specific Calibration (Session 108)
    if args.approach in ['edge_specific', 'all']:
        print("\n--- EDGE-SPECIFIC CALIBRATION (Session 108) ---")

        print("Applying edge-specific calibration (full for 5+, half for 3-5)...")
        edge_spec_preds = calibrate_edge_specific(baseline_preds, season_avgs, vegas_lines)
        results.append(evaluate_approach("Edge-Specific Calibration", edge_spec_preds, y_eval, vegas_lines))

        # Also try edge-specific with gentler thresholds
        print("Applying edge-specific (full for 4+, half for 2-4)...")
        edge_spec_lower_preds = calibrate_edge_specific(
            baseline_preds, season_avgs, vegas_lines,
            high_edge_threshold=4.0, medium_edge_threshold=2.0
        )
        results.append(evaluate_approach("Edge-Specific (4+/2+)", edge_spec_lower_preds, y_eval, vegas_lines))

    # Print results
    print_results(results)


if __name__ == "__main__":
    main()
