#!/usr/bin/env python3
"""
MLB CatBoost Regressor Feature Analysis

Comprehensive analysis of the 40-feature CatBoost regressor:
1. Feature importance (gain-based + SHAP)
2. Feature ablation study (40f -> 20f -> 10f -> 5f)
3. Feature correlation analysis
4. Derived feature experiments
5. Feature stability across retrain windows
6. Learning curves (training set size vs validation MAE)

Usage:
    PYTHONPATH=. python scripts/mlb/training/feature_analysis.py
"""

import os
import sys
import json
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
from google.cloud import bigquery
from catboost import CatBoostRegressor, Pool
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

PROJECT_ID = "nba-props-platform"
OUTPUT_DIR = Path("results/experiments/mlb_feature_analysis")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ===========================================================================
# Feature list — matches production exactly
# ===========================================================================
FEATURE_COLS = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f17_month_of_season', 'f18_days_into_season',
    'f19_season_swstr_pct', 'f19b_season_csw_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason', 'f25_is_day_game',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff', 'f44_over_implied_prob',
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
    'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
    'f67_season_starts', 'f68_k_per_pitch', 'f69_recent_workload_ratio',
    'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
]

HYPERPARAMS = {
    'depth': 5,
    'learning_rate': 0.015,
    'iterations': 500,
    'l2_leaf_reg': 3,
    'subsample': 0.8,
    'random_seed': 42,
    'verbose': 0,
    'loss_function': 'RMSE',
}


def load_data(client: bigquery.Client) -> pd.DataFrame:
    """Load all available data (same query as walk_forward_simulation.py)."""
    print("Loading data from BigQuery...")

    query = """
    WITH statcast_rolling AS (
        SELECT DISTINCT
            player_lookup,
            game_date,
            swstr_pct_last_3,
            swstr_pct_last_5,
            swstr_pct_season_prior,
            fb_velocity_last_3,
            fb_velocity_season_prior
        FROM `mlb_analytics.pitcher_rolling_statcast`
        WHERE statcast_games_count >= 3
    )
    SELECT
        bp.game_date,
        bp.player_name,
        bp.player_lookup AS bp_player_lookup,
        bp.over_line,
        bp.projection_value,
        bp.actual_value,
        bp.over_odds,
        CASE WHEN bp.actual_value > bp.over_line THEN 1 ELSE 0 END as went_over,

        pgs.player_lookup,
        pgs.team_abbr,
        pgs.opponent_team_abbr,
        pgs.venue,
        pgs.k_avg_last_3 as f00_k_avg_last_3,
        pgs.k_avg_last_5 as f01_k_avg_last_5,
        pgs.k_avg_last_10 as f02_k_avg_last_10,
        pgs.k_std_last_10 as f03_k_std_last_10,
        pgs.ip_avg_last_5 as f04_ip_avg_last_5,
        pgs.season_k_per_9 as f05_season_k_per_9,
        pgs.era_rolling_10 as f06_season_era,
        pgs.whip_rolling_10 as f07_season_whip,
        pgs.season_games_started as f08_season_games,
        pgs.season_strikeouts as f09_season_k_total,
        IF(pgs.is_home, 1.0, 0.0) as f10_is_home,
        pgs.opponent_team_k_rate as f15_opponent_team_k_rate,
        pgs.ballpark_k_factor as f16_ballpark_k_factor,
        pgs.month_of_season as f17_month_of_season,
        pgs.days_into_season as f18_days_into_season,
        pgs.season_swstr_pct as f19_season_swstr_pct,
        pgs.season_csw_pct as f19b_season_csw_pct,
        pgs.days_rest as f20_days_rest,
        pgs.games_last_30_days as f21_games_last_30_days,
        pgs.pitch_count_avg_last_5 as f22_pitch_count_avg,
        pgs.season_innings as f23_season_ip_total,
        IF(pgs.is_postseason, 1.0, 0.0) as f24_is_postseason,
        IF(pgs.is_day_game, 1.0, 0.0) as f25_is_day_game,

        (pgs.k_avg_last_5 - bp.over_line) as f30_k_avg_vs_line,
        bp.over_line as f32_line_level,

        bp.projection_value as f40_bp_projection,
        (bp.projection_value - bp.over_line) as f41_projection_diff,
        CASE
            WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
            ELSE 100.0 / (bp.over_odds + 100.0)
        END as f44_over_implied_prob,

        COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct) as f50_swstr_pct_last_3,
        COALESCE(sc.fb_velocity_last_3, sc.fb_velocity_season_prior) as f51_fb_velocity_last_3,
        COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
        COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change,

        pgs.vs_opponent_k_per_9 as f65_vs_opp_k_per_9,
        pgs.vs_opponent_games as f66_vs_opp_games,

        pgs.season_games_started as f67_season_starts,
        SAFE_DIVIDE(pgs.k_avg_last_5, NULLIF(pgs.pitch_count_avg_last_5, 0)) as f68_k_per_pitch,
        SAFE_DIVIDE(pgs.games_last_30_days, 6.0) as f69_recent_workload_ratio,

        fg.o_swing_pct as f70_o_swing_pct,
        fg.z_contact_pct as f71_z_contact_pct,
        fg.fip as f72_fip,
        fg.gb_pct as f73_gb_pct

    FROM `mlb_raw.bp_pitcher_props` bp
    JOIN `mlb_analytics.pitcher_game_summary` pgs
        ON pgs.game_date = bp.game_date
        AND LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', '')) = bp.player_lookup
    LEFT JOIN statcast_rolling sc
        ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
        AND pgs.game_date = sc.game_date
    LEFT JOIN `mlb_raw.fangraphs_pitcher_season_stats` fg
        ON LOWER(REGEXP_REPLACE(NORMALIZE(fg.player_lookup, NFD), r'[\\W_]+', ''))
            = LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', ''))
        AND fg.season_year = EXTRACT(YEAR FROM pgs.game_date)
    WHERE bp.market_id = 285
      AND bp.actual_value IS NOT NULL
      AND bp.projection_value IS NOT NULL
      AND bp.over_line IS NOT NULL
      AND pgs.innings_pitched >= 3.0
      AND pgs.rolling_stats_games >= 3
      AND pgs.game_date >= '2024-01-01'
    ORDER BY bp.game_date
    """

    df = client.query(query).to_dataframe()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values('game_date').reset_index(drop=True)

    print(f"Loaded {len(df):,} samples")
    print(f"Date range: {df['game_date'].min().date()} to {df['game_date'].max().date()}")

    # Coverage stats
    for prefix, label in [('f5', 'Statcast'), ('f7', 'FanGraphs'), ('f65', 'Matchup')]:
        cols = [c for c in df.columns if c.startswith(prefix)]
        if cols:
            coverage = df[cols[0]].notna().mean() * 100
            print(f"  {label} coverage: {coverage:.1f}%")

    return df


def get_available_features(df):
    """Return feature columns that exist in the DataFrame."""
    return [f for f in FEATURE_COLS if f in df.columns]


def train_regressor(X_train, y_train, seed=42, **override_params):
    """Train a CatBoost regressor."""
    params = {**HYPERPARAMS, 'random_seed': seed}
    params.update(override_params)
    model = CatBoostRegressor(**params)
    model.fit(X_train, y_train)
    return model


def evaluate_regressor(model, X_test, y_actual, lines, went_over):
    """Evaluate a regressor on test data. Returns dict of metrics."""
    predicted_k = model.predict(X_test)
    residuals = predicted_k - y_actual
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    bias = float(np.mean(residuals))

    edge = predicted_k - lines
    predicted_over = (edge > 0).astype(int)
    correct = (predicted_over == went_over).astype(int)
    overall_hr = float(correct.mean() * 100) if len(correct) > 0 else 0.0

    # HR at various edge thresholds
    hr_by_edge = {}
    for thresh in [0.5, 0.75, 1.0, 1.5, 2.0]:
        mask = np.abs(edge) >= thresh
        if mask.sum() > 0:
            hr_by_edge[thresh] = {
                'hr': float(correct[mask].mean() * 100),
                'n': int(mask.sum()),
            }

    return {
        'mae': mae,
        'rmse': rmse,
        'bias': bias,
        'overall_hr': overall_hr,
        'n': len(y_actual),
        'hr_by_edge': hr_by_edge,
    }


def prepare_X(df, feature_cols):
    """Prepare feature matrix with numeric coercion."""
    X = df[feature_cols].copy()
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors='coerce')
    return X


# ===========================================================================
# ANALYSIS 1: Feature Importance (Gain + SHAP)
# ===========================================================================
def analysis_1_feature_importance(df):
    """Train a single model on latest 120d window, extract importance."""
    print("\n" + "=" * 80)
    print(" ANALYSIS 1: Feature Importance (Gain + SHAP)")
    print("=" * 80)

    # Training window: 120d ending at 2025-09-28
    end_date = pd.Timestamp('2025-09-28')
    start_date = end_date - pd.Timedelta(days=120)

    train_mask = (df['game_date'] >= start_date) & (df['game_date'] <= end_date)
    train_df = df[train_mask].copy()

    feature_cols = get_available_features(train_df)
    print(f"\nTraining on {len(train_df)} samples ({start_date.date()} to {end_date.date()})")
    print(f"Features: {len(feature_cols)}")

    X_train = prepare_X(train_df, feature_cols)
    y_train = train_df['actual_value'].astype(float)

    model = train_regressor(X_train, y_train)

    # --- Gain-based importance ---
    gain_importance = model.get_feature_importance(type='PredictionValuesChange')
    gain_pairs = sorted(zip(feature_cols, gain_importance), key=lambda x: x[1], reverse=True)

    print(f"\n--- Gain-Based Feature Importance ---")
    print(f"{'Rank':>4}  {'Feature':<30}  {'Importance':>10}  {'Pct':>6}")
    print("-" * 56)
    total_imp = sum(gain_importance)
    for i, (feat, imp) in enumerate(gain_pairs, 1):
        pct = imp / total_imp * 100 if total_imp > 0 else 0
        marker = " <<<" if pct < 0.5 else ""
        print(f"{i:>4}  {feat:<30}  {imp:>10.4f}  {pct:>5.1f}%{marker}")

    # --- SHAP values ---
    print(f"\n--- SHAP Analysis ---")
    pool = Pool(X_train)
    shap_values = model.get_feature_importance(type='ShapValues', data=pool)
    # ShapValues returns N x (F+1) — last column is bias
    shap_features = shap_values[:, :-1]

    # Mean absolute SHAP
    mean_abs_shap = np.mean(np.abs(shap_features), axis=0)
    shap_pairs = sorted(zip(feature_cols, mean_abs_shap), key=lambda x: x[1], reverse=True)

    print(f"\n{'Rank':>4}  {'Feature':<30}  {'Mean |SHAP|':>12}  {'Mean SHAP':>10}")
    print("-" * 62)
    mean_shap = np.mean(shap_features, axis=0)
    shap_lookup = dict(zip(feature_cols, mean_shap))
    for i, (feat, abs_val) in enumerate(shap_pairs, 1):
        direction = shap_lookup[feat]
        marker = ""
        if abs_val < 0.01:
            marker = " <<< NEAR-ZERO"
        print(f"{i:>4}  {feat:<30}  {abs_val:>12.4f}  {direction:>+10.4f}{marker}")

    # Top 10 and Bottom 10
    print(f"\n--- TOP 10 Features (by SHAP) ---")
    for feat, val in shap_pairs[:10]:
        print(f"  {feat}: {val:.4f}")

    print(f"\n--- BOTTOM 10 Features (by SHAP) ---")
    for feat, val in shap_pairs[-10:]:
        print(f"  {feat}: {val:.4f}")

    # Features potentially HURTING the model (mean SHAP strongly negative for
    # features where we'd expect positive, or near-zero — they add noise)
    print(f"\n--- Features potentially hurting the model ---")
    near_zero = [(f, v) for f, v in shap_pairs if v < 0.02]
    print(f"  {len(near_zero)} features with mean |SHAP| < 0.02:")
    for f, v in near_zero:
        print(f"    {f}: {v:.4f}")

    # Save results
    results = {
        'gain_importance': [(f, float(v)) for f, v in gain_pairs],
        'shap_importance': [(f, float(v)) for f, v in shap_pairs],
        'near_zero_features': [f for f, v in near_zero],
        'training_samples': len(train_df),
    }

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(16, 10))

    # Gain importance
    top_20_gain = gain_pairs[:20]
    ax = axes[0]
    feats = [f[0] for f in top_20_gain][::-1]
    vals = [f[1] for f in top_20_gain][::-1]
    ax.barh(range(len(feats)), vals)
    ax.set_yticks(range(len(feats)))
    ax.set_yticklabels(feats, fontsize=8)
    ax.set_title('Top 20 Features (Gain-Based)')
    ax.set_xlabel('Importance')

    # SHAP importance
    top_20_shap = shap_pairs[:20]
    ax = axes[1]
    feats = [f[0] for f in top_20_shap][::-1]
    vals = [f[1] for f in top_20_shap][::-1]
    ax.barh(range(len(feats)), vals)
    ax.set_yticks(range(len(feats)))
    ax.set_yticklabels(feats, fontsize=8)
    ax.set_title('Top 20 Features (Mean |SHAP|)')
    ax.set_xlabel('Mean |SHAP| Value')

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'feature_importance.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: {OUTPUT_DIR / 'feature_importance.png'}")

    return results


# ===========================================================================
# ANALYSIS 2: Feature Ablation Study (Walk-Forward)
# ===========================================================================
def run_walkforward(df, feature_cols, window_days=120, retrain_days=14,
                    sim_start='2024-04-01', sim_end='2025-09-28', label=''):
    """Run walk-forward simulation with given features. Returns aggregated metrics."""
    sim_start = pd.Timestamp(sim_start)
    sim_end = pd.Timestamp(sim_end)

    game_dates = sorted(df[
        (df['game_date'] >= sim_start) & (df['game_date'] <= sim_end)
    ]['game_date'].unique())

    current_model = None
    last_train_date = None
    all_preds = []

    for game_date in game_dates:
        needs_retrain = (
            current_model is None or
            last_train_date is None or
            (game_date - last_train_date).days >= retrain_days
        )

        if needs_retrain:
            train_start = game_date - pd.Timedelta(days=window_days)
            train_mask = (df['game_date'] >= train_start) & (df['game_date'] < game_date)
            train_df = df[train_mask]

            X_train = prepare_X(train_df, feature_cols)
            y_train = train_df['actual_value'].astype(float)

            if len(X_train) < 50:
                continue

            current_model = train_regressor(X_train, y_train)
            last_train_date = game_date

        test_mask = df['game_date'] == game_date
        test_df = df[test_mask].copy()

        X_test = prepare_X(test_df, feature_cols)
        if len(X_test) == 0:
            continue

        y_actual = test_df['actual_value'].astype(float).values
        lines = test_df['over_line'].astype(float).values
        went_over = test_df['went_over'].astype(int).values

        predicted_k = current_model.predict(X_test)
        edge = predicted_k - lines
        predicted_over = (edge > 0).astype(int)
        correct = (predicted_over == went_over).astype(int)

        for i in range(len(correct)):
            all_preds.append({
                'game_date': str(game_date.date()),
                'predicted_k': float(predicted_k[i]),
                'actual_k': float(y_actual[i]),
                'line': float(lines[i]),
                'edge': float(edge[i]),
                'correct': int(correct[i]),
                'went_over': int(went_over[i]),
                'predicted_over': int(predicted_over[i]),
            })

    if not all_preds:
        return {'mae': 999, 'hr': 0, 'n': 0, 'hr_by_edge': {}}

    preds_arr = np.array([p['predicted_k'] for p in all_preds])
    actuals_arr = np.array([p['actual_k'] for p in all_preds])
    correct_arr = np.array([p['correct'] for p in all_preds])
    edge_arr = np.abs(np.array([p['edge'] for p in all_preds]))

    mae = float(np.mean(np.abs(preds_arr - actuals_arr)))
    hr = float(correct_arr.mean() * 100)

    hr_by_edge = {}
    for thresh in [0.5, 0.75, 1.0, 1.5, 2.0]:
        mask = edge_arr >= thresh
        if mask.sum() > 0:
            hr_by_edge[thresh] = {
                'hr': float(correct_arr[mask].mean() * 100),
                'n': int(mask.sum()),
            }

    return {
        'mae': mae,
        'hr': hr,
        'n': len(all_preds),
        'hr_by_edge': hr_by_edge,
        'all_preds': all_preds,
    }


def analysis_2_ablation(df, importance_results):
    """Feature ablation: test 40f, 20f, 10f, 5f using walk-forward."""
    print("\n" + "=" * 80)
    print(" ANALYSIS 2: Feature Ablation Study (Walk-Forward)")
    print("=" * 80)

    # Get feature ranking from gain importance
    gain_ranking = [f for f, _ in importance_results['gain_importance']]
    available = get_available_features(df)
    gain_ranking = [f for f in gain_ranking if f in available]

    # Define feature subsets
    subsets = {
        f'all_{len(available)}f': available,
        f'top_20f': gain_ranking[:20],
        f'top_10f': gain_ranking[:10],
        f'top_5f': gain_ranking[:5],
    }

    results = {}
    for name, features in subsets.items():
        print(f"\n--- {name}: {features[:5]}{'...' if len(features) > 5 else ''} ---")
        t0 = time.time()
        result = run_walkforward(df, features, label=name)
        elapsed = time.time() - t0
        results[name] = result

        print(f"  MAE: {result['mae']:.4f}")
        print(f"  Overall HR: {result['hr']:.1f}% (N={result['n']})")
        for thresh in [0.5, 0.75, 1.0, 1.5]:
            if thresh in result['hr_by_edge']:
                e = result['hr_by_edge'][thresh]
                print(f"  Edge >= {thresh}: {e['hr']:.1f}% HR (N={e['n']})")
        print(f"  Time: {elapsed:.0f}s")

    # Summary table
    print(f"\n--- ABLATION SUMMARY ---")
    print(f"{'Subset':<15} {'MAE':>6} {'HR':>6} {'N':>6}", end="")
    for t in [0.5, 0.75, 1.0, 1.5]:
        print(f"  {'e>=' + str(t):>10}", end="")
    print()
    print("-" * 75)

    for name, result in results.items():
        print(f"{name:<15} {result['mae']:>6.3f} {result['hr']:>5.1f}% {result['n']:>5}", end="")
        for t in [0.5, 0.75, 1.0, 1.5]:
            if t in result['hr_by_edge']:
                e = result['hr_by_edge'][t]
                print(f"  {e['hr']:5.1f}%/{e['n']:<4}", end="")
            else:
                print(f"  {'N/A':>10}", end="")
        print()

    return results


# ===========================================================================
# ANALYSIS 3: Feature Correlation Analysis
# ===========================================================================
def analysis_3_correlation(df):
    """Analyze feature correlations and identify redundant features."""
    print("\n" + "=" * 80)
    print(" ANALYSIS 3: Feature Correlation Analysis")
    print("=" * 80)

    feature_cols = get_available_features(df)
    X = prepare_X(df, feature_cols)

    # Compute correlation matrix
    corr = X.corr()

    # Find highly correlated pairs (|r| > 0.8)
    high_corr_pairs = []
    for i in range(len(feature_cols)):
        for j in range(i + 1, len(feature_cols)):
            r = corr.iloc[i, j]
            if abs(r) > 0.8:
                high_corr_pairs.append((feature_cols[i], feature_cols[j], r))

    high_corr_pairs.sort(key=lambda x: abs(x[2]), reverse=True)

    print(f"\n--- Highly Correlated Feature Pairs (|r| > 0.8) ---")
    print(f"{'Feature 1':<30} {'Feature 2':<30} {'r':>8}")
    print("-" * 70)
    for f1, f2, r in high_corr_pairs:
        print(f"{f1:<30} {f2:<30} {r:>+8.3f}")

    print(f"\nTotal pairs with |r| > 0.8: {len(high_corr_pairs)}")

    # Identify features that appear in multiple high-correlation pairs
    corr_counts = defaultdict(int)
    for f1, f2, r in high_corr_pairs:
        corr_counts[f1] += 1
        corr_counts[f2] += 1

    if corr_counts:
        print(f"\n--- Features in Multiple High-Correlation Pairs ---")
        for feat, count in sorted(corr_counts.items(), key=lambda x: x[1], reverse=True):
            if count >= 2:
                print(f"  {feat}: {count} pairs")

    # Correlation with target
    y = df['actual_value'].astype(float)
    target_corr = []
    for col in feature_cols:
        vals = pd.to_numeric(X[col], errors='coerce')
        r = vals.corr(y)
        target_corr.append((col, r))

    target_corr.sort(key=lambda x: abs(x[1]), reverse=True)

    print(f"\n--- Feature-Target Correlation (sorted by |r|) ---")
    print(f"{'Feature':<30} {'r':>8}")
    print("-" * 40)
    for feat, r in target_corr:
        marker = " <<<" if abs(r) < 0.05 else ""
        print(f"{feat:<30} {r:>+8.3f}{marker}")

    # Save correlation matrix plot
    fig, ax = plt.subplots(figsize=(18, 15))
    im = ax.imshow(corr.values, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(feature_cols)))
    ax.set_yticks(range(len(feature_cols)))
    ax.set_xticklabels(feature_cols, rotation=90, fontsize=6)
    ax.set_yticklabels(feature_cols, fontsize=6)
    plt.colorbar(im)
    ax.set_title('Feature Correlation Matrix')
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'correlation_matrix.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: {OUTPUT_DIR / 'correlation_matrix.png'}")

    # Test: remove correlated features and walk-forward
    # Strategy: for each highly correlated pair, keep the one with higher target correlation
    features_to_remove = set()
    target_corr_lookup = dict(target_corr)
    for f1, f2, r in high_corr_pairs:
        tc1 = abs(target_corr_lookup.get(f1, 0))
        tc2 = abs(target_corr_lookup.get(f2, 0))
        if tc1 >= tc2:
            features_to_remove.add(f2)
        else:
            features_to_remove.add(f1)

    print(f"\n--- Features to remove (lower target corr in each pair) ---")
    for f in sorted(features_to_remove):
        print(f"  {f}")

    reduced_features = [f for f in feature_cols if f not in features_to_remove]
    print(f"\nReduced feature set: {len(reduced_features)} features (removed {len(features_to_remove)})")

    print(f"\nRunning walk-forward with de-correlated features...")
    t0 = time.time()
    result = run_walkforward(df, reduced_features, label='decorrelated')
    elapsed = time.time() - t0

    print(f"  De-correlated ({len(reduced_features)}f):")
    print(f"    MAE: {result['mae']:.4f}")
    print(f"    HR: {result['hr']:.1f}% (N={result['n']})")
    for thresh in [0.5, 0.75, 1.0, 1.5]:
        if thresh in result['hr_by_edge']:
            e = result['hr_by_edge'][thresh]
            print(f"    Edge >= {thresh}: {e['hr']:.1f}% (N={e['n']})")
    print(f"  Time: {elapsed:.0f}s")

    return {
        'high_corr_pairs': [(f1, f2, float(r)) for f1, f2, r in high_corr_pairs],
        'target_correlations': [(f, float(r)) for f, r in target_corr],
        'features_removed': list(features_to_remove),
        'reduced_features': reduced_features,
        'decorrelated_result': {k: v for k, v in result.items() if k != 'all_preds'},
    }


# ===========================================================================
# ANALYSIS 4: Derived Feature Experiments
# ===========================================================================
def analysis_4_derived_features(df):
    """Test derived features that could add value."""
    print("\n" + "=" * 80)
    print(" ANALYSIS 4: Derived Feature Experiments")
    print("=" * 80)

    # Create derived features
    df_derived = df.copy()

    # 1. Interaction: k_avg_last_5 * is_home
    df_derived['d_k_home_interaction'] = (
        pd.to_numeric(df_derived['f01_k_avg_last_5'], errors='coerce') *
        pd.to_numeric(df_derived['f10_is_home'], errors='coerce')
    )

    # 2. Ratio: k_avg_last_5 / over_line (form vs expectation)
    df_derived['d_k_form_vs_line_ratio'] = (
        pd.to_numeric(df_derived['f01_k_avg_last_5'], errors='coerce') /
        pd.to_numeric(df_derived['over_line'], errors='coerce').replace(0, np.nan)
    )

    # 3. Delta: season_k_per_9 - k_avg_last_5 (season vs recent divergence)
    df_derived['d_season_vs_recent_delta'] = (
        pd.to_numeric(df_derived['f05_season_k_per_9'], errors='coerce') -
        pd.to_numeric(df_derived['f01_k_avg_last_5'], errors='coerce')
    )

    # 4. Volatility: k_std_last_10 already exists as f03, but let's add
    # coefficient of variation: std/mean
    df_derived['d_k_cv'] = (
        pd.to_numeric(df_derived['f03_k_std_last_10'], errors='coerce') /
        pd.to_numeric(df_derived['f02_k_avg_last_10'], errors='coerce').replace(0, np.nan)
    )

    # 5. Projection agreement: bp_projection - k_avg_last_5
    df_derived['d_projection_vs_recent'] = (
        pd.to_numeric(df_derived['f40_bp_projection'], errors='coerce') -
        pd.to_numeric(df_derived['f01_k_avg_last_5'], errors='coerce')
    )

    # 6. Opponent + pitcher interaction: opponent_k_rate * season_k_per_9
    df_derived['d_opp_pitcher_k_interaction'] = (
        pd.to_numeric(df_derived['f15_opponent_team_k_rate'], errors='coerce') *
        pd.to_numeric(df_derived['f05_season_k_per_9'], errors='coerce')
    )

    derived_features = [
        'd_k_home_interaction',
        'd_k_form_vs_line_ratio',
        'd_season_vs_recent_delta',
        'd_k_cv',
        'd_projection_vs_recent',
        'd_opp_pitcher_k_interaction',
    ]

    base_features = get_available_features(df_derived)

    # Run baseline first
    print(f"\n--- Baseline (no derived features) ---")
    t0 = time.time()
    baseline = run_walkforward(df_derived, base_features, label='baseline')
    elapsed = time.time() - t0
    print(f"  MAE: {baseline['mae']:.4f}, HR: {baseline['hr']:.1f}% (N={baseline['n']}), Time: {elapsed:.0f}s")

    # Test each derived feature individually
    results = {'baseline': {k: v for k, v in baseline.items() if k != 'all_preds'}}

    for feat in derived_features:
        print(f"\n--- + {feat} ---")
        test_features = base_features + [feat]
        t0 = time.time()
        result = run_walkforward(df_derived, test_features, label=feat)
        elapsed = time.time() - t0

        mae_delta = result['mae'] - baseline['mae']
        hr_delta = result['hr'] - baseline['hr']
        verdict = "BETTER" if (mae_delta < -0.005 and hr_delta > 0.5) else \
                  "WORSE" if (mae_delta > 0.005 or hr_delta < -0.5) else "NOISE"

        print(f"  MAE: {result['mae']:.4f} ({mae_delta:+.4f})")
        print(f"  HR: {result['hr']:.1f}% ({hr_delta:+.1f}pp)")
        for thresh in [0.75, 1.0]:
            b = baseline['hr_by_edge'].get(thresh, {})
            r = result['hr_by_edge'].get(thresh, {})
            if b and r:
                print(f"  Edge >= {thresh}: {r['hr']:.1f}% vs {b['hr']:.1f}% (N={r['n']} vs {b['n']})")
        print(f"  Verdict: {verdict}")
        print(f"  Time: {elapsed:.0f}s")

        results[feat] = {
            'mae': result['mae'],
            'hr': result['hr'],
            'n': result['n'],
            'mae_delta': mae_delta,
            'hr_delta': hr_delta,
            'verdict': verdict,
            'hr_by_edge': result['hr_by_edge'],
        }

    # Test all derived features together
    print(f"\n--- All derived features combined ---")
    all_features = base_features + derived_features
    t0 = time.time()
    result = run_walkforward(df_derived, all_features, label='all_derived')
    elapsed = time.time() - t0
    mae_delta = result['mae'] - baseline['mae']
    hr_delta = result['hr'] - baseline['hr']
    print(f"  MAE: {result['mae']:.4f} ({mae_delta:+.4f})")
    print(f"  HR: {result['hr']:.1f}% ({hr_delta:+.1f}pp)")
    print(f"  Time: {elapsed:.0f}s")

    results['all_derived'] = {
        'mae': result['mae'],
        'hr': result['hr'],
        'n': result['n'],
        'mae_delta': mae_delta,
        'hr_delta': hr_delta,
        'hr_by_edge': result['hr_by_edge'],
    }

    # Summary
    print(f"\n--- DERIVED FEATURE SUMMARY ---")
    print(f"{'Feature':<35} {'MAE Delta':>10} {'HR Delta':>10} {'Verdict':>8}")
    print("-" * 65)
    for feat in derived_features + ['all_derived']:
        r = results[feat]
        print(f"{feat:<35} {r['mae_delta']:>+10.4f} {r['hr_delta']:>+9.1f}pp {r.get('verdict', ''):>8}")

    return results


# ===========================================================================
# ANALYSIS 5: Feature Stability Across Retrains
# ===========================================================================
def analysis_5_stability(df):
    """Check if feature importance rankings are stable across retrain windows."""
    print("\n" + "=" * 80)
    print(" ANALYSIS 5: Feature Stability Across Retrains")
    print("=" * 80)

    feature_cols = get_available_features(df)
    end_date = pd.Timestamp('2025-09-28')

    # Train models at different points in time
    retrain_points = []
    for offset in range(0, 420, 14):  # Every 14 days going back
        d = end_date - pd.Timedelta(days=offset)
        if d < pd.Timestamp('2024-06-01'):
            break
        retrain_points.append(d)

    retrain_points.reverse()  # Chronological order
    print(f"Training {len(retrain_points)} models (every 14d)")

    importance_history = []
    top5_history = []

    for i, train_end in enumerate(retrain_points):
        train_start = train_end - pd.Timedelta(days=120)
        mask = (df['game_date'] >= train_start) & (df['game_date'] < train_end)
        train_df = df[mask]

        X_train = prepare_X(train_df, feature_cols)
        y_train = train_df['actual_value'].astype(float)

        if len(X_train) < 50:
            continue

        model = train_regressor(X_train, y_train)
        gain = model.get_feature_importance()
        gain_pairs = sorted(zip(feature_cols, gain), key=lambda x: x[1], reverse=True)

        importance_history.append({
            'train_end': str(train_end.date()),
            'ranking': [f for f, _ in gain_pairs],
            'importances': {f: float(v) for f, v in gain_pairs},
        })
        top5_history.append([f for f, _ in gain_pairs[:5]])

    # Analyze stability
    print(f"\n--- Top 5 Features Per Retrain Window ---")
    for i, entry in enumerate(importance_history):
        print(f"  {entry['train_end']}: {', '.join(entry['ranking'][:5])}")

    # Compute rank correlation between consecutive windows
    from scipy.stats import spearmanr
    rank_corrs = []
    for i in range(1, len(importance_history)):
        prev_ranking = importance_history[i - 1]['ranking']
        curr_ranking = importance_history[i]['ranking']

        prev_ranks = {f: r for r, f in enumerate(prev_ranking)}
        curr_ranks = {f: r for r, f in enumerate(curr_ranking)}

        common = set(prev_ranks.keys()) & set(curr_ranks.keys())
        prev_r = [prev_ranks[f] for f in common]
        curr_r = [curr_ranks[f] for f in common]

        rho, _ = spearmanr(prev_r, curr_r)
        rank_corrs.append({
            'window': importance_history[i]['train_end'],
            'spearman_rho': float(rho),
        })

    print(f"\n--- Rank Stability (Spearman rho between consecutive windows) ---")
    rhos = [r['spearman_rho'] for r in rank_corrs]
    print(f"  Mean rho: {np.mean(rhos):.3f}")
    print(f"  Std rho:  {np.std(rhos):.3f}")
    print(f"  Min rho:  {np.min(rhos):.3f}")
    print(f"  Max rho:  {np.max(rhos):.3f}")

    if np.mean(rhos) > 0.85:
        verdict = "STABLE — feature rankings are consistent across retrains"
    elif np.mean(rhos) > 0.7:
        verdict = "MODERATELY STABLE — some drift but core features consistent"
    else:
        verdict = "UNSTABLE — feature rankings shift significantly (brittle model)"

    print(f"\n  Verdict: {verdict}")

    # Which features are ALWAYS in top 10?
    always_top10 = set(importance_history[0]['ranking'][:10])
    for entry in importance_history[1:]:
        always_top10 &= set(entry['ranking'][:10])

    print(f"\n--- Features ALWAYS in Top 10 ({len(always_top10)}) ---")
    for f in sorted(always_top10):
        print(f"  {f}")

    # Features that bounce around the most
    rank_variance = {}
    for f in feature_cols:
        ranks = []
        for entry in importance_history:
            ranks.append(entry['ranking'].index(f) if f in entry['ranking'] else len(feature_cols))
        rank_variance[f] = float(np.std(ranks))

    most_volatile = sorted(rank_variance.items(), key=lambda x: x[1], reverse=True)
    print(f"\n--- Most Volatile Feature Rankings (highest rank std) ---")
    for f, std in most_volatile[:10]:
        avg_rank = np.mean([entry['ranking'].index(f) for entry in importance_history if f in entry['ranking']])
        print(f"  {f}: avg rank {avg_rank:.1f}, std {std:.1f}")

    # Plot stability
    fig, ax = plt.subplots(figsize=(12, 6))
    for feat in list(always_top10)[:7]:  # Plot top consistently important features
        ranks = []
        dates = []
        for entry in importance_history:
            if feat in entry['ranking']:
                ranks.append(entry['ranking'].index(feat) + 1)
                dates.append(entry['train_end'])
        ax.plot(range(len(ranks)), ranks, label=feat, marker='o', markersize=3)

    ax.set_xlabel('Retrain Window')
    ax.set_ylabel('Feature Rank (1=most important)')
    ax.set_title('Feature Rank Stability Across Retrains')
    ax.legend(fontsize=7, loc='upper right')
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'feature_stability.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: {OUTPUT_DIR / 'feature_stability.png'}")

    return {
        'mean_rho': float(np.mean(rhos)),
        'always_top10': list(always_top10),
        'most_volatile': most_volatile[:10],
        'rank_correlations': rank_corrs,
        'verdict': verdict,
    }


# ===========================================================================
# ANALYSIS 6: Learning Curves (Training Set Size vs MAE)
# ===========================================================================
def analysis_6_learning_curves(df):
    """Test if 120d is truly optimal or if more/less data helps."""
    print("\n" + "=" * 80)
    print(" ANALYSIS 6: Learning Curves (Training Window Size)")
    print("=" * 80)

    feature_cols = get_available_features(df)
    windows = [30, 42, 56, 70, 90, 120, 150, 180, 240, 365]

    results = {}
    for window in windows:
        print(f"\n--- Window: {window}d ---")
        t0 = time.time()
        result = run_walkforward(df, feature_cols, window_days=window, label=f'{window}d')
        elapsed = time.time() - t0

        results[window] = {
            'mae': result['mae'],
            'hr': result['hr'],
            'n': result['n'],
            'hr_by_edge': result['hr_by_edge'],
        }

        print(f"  MAE: {result['mae']:.4f}")
        print(f"  HR: {result['hr']:.1f}% (N={result['n']})")
        for thresh in [0.75, 1.0]:
            if thresh in result['hr_by_edge']:
                e = result['hr_by_edge'][thresh]
                print(f"  Edge >= {thresh}: {e['hr']:.1f}% (N={e['n']})")
        print(f"  Time: {elapsed:.0f}s")

    # Summary
    print(f"\n--- LEARNING CURVE SUMMARY ---")
    print(f"{'Window':>8} {'MAE':>8} {'HR':>8} {'N':>6}", end="")
    for t in [0.75, 1.0, 1.5]:
        print(f"  {'e>=' + str(t):>10}", end="")
    print()
    print("-" * 70)

    best_mae = min(r['mae'] for r in results.values())
    best_hr = max(r['hr'] for r in results.values())

    for window in windows:
        r = results[window]
        mae_marker = " *" if r['mae'] == best_mae else ""
        hr_marker = " *" if r['hr'] == best_hr else ""
        print(f"{window:>6}d {r['mae']:>7.4f}{mae_marker} {r['hr']:>6.1f}%{hr_marker} {r['n']:>5}", end="")
        for t in [0.75, 1.0, 1.5]:
            if t in r['hr_by_edge']:
                e = r['hr_by_edge'][t]
                print(f"  {e['hr']:5.1f}%/{e['n']:<4}", end="")
            else:
                print(f"  {'N/A':>10}", end="")
        print()

    # Find optimal
    # Weight MAE and HR: prefer lower MAE, higher HR
    optimal = min(results.items(), key=lambda x: x[1]['mae'] - x[1]['hr'] / 200)
    print(f"\n  Optimal window (MAE-weighted): {optimal[0]}d")
    print(f"  MAE: {optimal[1]['mae']:.4f}, HR: {optimal[1]['hr']:.1f}%")

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    ws = list(results.keys())
    maes = [results[w]['mae'] for w in ws]
    hrs = [results[w]['hr'] for w in ws]

    ax1.plot(ws, maes, 'bo-')
    ax1.set_xlabel('Training Window (days)')
    ax1.set_ylabel('MAE (K)')
    ax1.set_title('Training Window vs MAE')
    ax1.axhline(y=min(maes), color='r', linestyle='--', alpha=0.5)

    ax2.plot(ws, hrs, 'go-')
    ax2.set_xlabel('Training Window (days)')
    ax2.set_ylabel('Hit Rate (%)')
    ax2.set_title('Training Window vs HR')
    ax2.axhline(y=max(hrs), color='r', linestyle='--', alpha=0.5)

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'learning_curves.png', dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved: {OUTPUT_DIR / 'learning_curves.png'}")

    return results


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("=" * 80)
    print(" MLB CatBoost Regressor — Comprehensive Feature Analysis")
    print("=" * 80)
    print(f"Output directory: {OUTPUT_DIR}")
    t_start = time.time()

    client = bigquery.Client(project=PROJECT_ID)
    df = load_data(client)

    # Run all analyses
    all_results = {}

    # 1. Feature importance
    importance_results = analysis_1_feature_importance(df)
    all_results['importance'] = importance_results

    # 2. Ablation study
    ablation_results = analysis_2_ablation(df, importance_results)
    all_results['ablation'] = {k: {kk: vv for kk, vv in v.items() if kk != 'all_preds'}
                               for k, v in ablation_results.items()}

    # 3. Correlation analysis
    correlation_results = analysis_3_correlation(df)
    all_results['correlation'] = correlation_results

    # 4. Derived features
    derived_results = analysis_4_derived_features(df)
    all_results['derived'] = derived_results

    # 5. Stability analysis
    stability_results = analysis_5_stability(df)
    all_results['stability'] = stability_results

    # 6. Learning curves
    learning_results = analysis_6_learning_curves(df)
    all_results['learning_curves'] = {str(k): v for k, v in learning_results.items()}

    # ===========================================================================
    # FINAL RECOMMENDATIONS
    # ===========================================================================
    print("\n" + "=" * 80)
    print(" FINAL RECOMMENDATIONS")
    print("=" * 80)

    # Recommend optimal feature set
    print("\n1. FEATURE SET RECOMMENDATIONS:")

    near_zero = importance_results.get('near_zero_features', [])
    if near_zero:
        print(f"   Remove {len(near_zero)} near-zero SHAP features: {near_zero}")
    else:
        print(f"   No features have near-zero SHAP — all contribute.")

    # Compare ablation results
    if 'ablation' in all_results:
        abl = all_results['ablation']
        baseline_key = [k for k in abl if k.startswith('all_')][0] if abl else None
        if baseline_key:
            baseline_hr = abl[baseline_key].get('hr', 0)
            for name in ['top_20f', 'top_10f', 'top_5f']:
                if name in abl:
                    delta = abl[name].get('hr', 0) - baseline_hr
                    print(f"   {name}: {delta:+.1f}pp vs baseline")

    print(f"\n2. CORRELATION FINDINGS:")
    if correlation_results['high_corr_pairs']:
        print(f"   {len(correlation_results['high_corr_pairs'])} highly correlated pairs found.")
        dcr = correlation_results.get('decorrelated_result', {})
        if dcr:
            print(f"   De-correlated ({len(correlation_results['reduced_features'])}f): "
                  f"MAE={dcr.get('mae', 'N/A'):.4f}, HR={dcr.get('hr', 'N/A'):.1f}%")
    else:
        print(f"   No highly correlated pairs (|r| > 0.8).")

    print(f"\n3. DERIVED FEATURES:")
    for feat, result in derived_results.items():
        if feat == 'baseline':
            continue
        if isinstance(result, dict) and result.get('verdict') == 'BETTER':
            print(f"   ADD: {feat} ({result['hr_delta']:+.1f}pp HR, {result['mae_delta']:+.4f} MAE)")

    none_helped = all(
        isinstance(r, dict) and r.get('verdict') != 'BETTER'
        for f, r in derived_results.items() if f != 'baseline'
    )
    if none_helped:
        print(f"   No derived features provided meaningful improvement.")

    print(f"\n4. STABILITY:")
    print(f"   {stability_results['verdict']}")
    print(f"   Always top 10: {stability_results['always_top10']}")

    print(f"\n5. OPTIMAL TRAINING WINDOW:")
    if learning_results:
        best_w = min(learning_results.items(), key=lambda x: x[1]['mae'])
        print(f"   Best MAE: {best_w[0]}d ({best_w[1]['mae']:.4f})")
        best_hr_w = max(learning_results.items(), key=lambda x: x[1]['hr'])
        print(f"   Best HR: {best_hr_w[0]}d ({best_hr_w[1]['hr']:.1f}%)")

    total_time = time.time() - t_start
    print(f"\n\nTotal analysis time: {total_time / 60:.1f} minutes")

    # Save all results
    # Convert numpy types for JSON serialization
    def convert_numpy(obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [convert_numpy(v) for v in obj]
        return obj

    with open(OUTPUT_DIR / 'feature_analysis_results.json', 'w') as f:
        json.dump(convert_numpy(all_results), f, indent=2, default=str)

    print(f"\nResults saved to: {OUTPUT_DIR / 'feature_analysis_results.json'}")
    print(f"Plots saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
