#!/usr/bin/env python3
"""
MLB Experiment Runner — Systematic feature and model experiments.

Runs walk-forward simulation with different feature sets and model types,
comparing against a baseline. Reports cross-season HR, ROI, and feature importance.

Usage:
    # Run all experiments
    PYTHONPATH=. python ml/training/mlb/experiment_runner.py --all

    # Run specific experiment
    PYTHONPATH=. python ml/training/mlb/experiment_runner.py --experiment lineup_k

    # List available experiments
    PYTHONPATH=. python ml/training/mlb/experiment_runner.py --list
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = "nba-props-platform"
OUTPUT_DIR = "results/experiments"

# ============================================================
# BASELINE FEATURES (current production V1 — 31 features)
# ============================================================
BASELINE_FEATURES = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f17_month_of_season', 'f18_days_into_season',
    'f19_season_swstr_pct', 'f19b_season_csw_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff', 'f44_over_implied_prob',
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
]

# ============================================================
# EXPERIMENT DEFINITIONS
# ============================================================

EXPERIMENTS = {
    'lineup_k': {
        'name': 'Opposing Lineup K Rate',
        'hypothesis': 'Bottom-up lineup K rate adds signal beyond team-level K rate',
        'extra_features': ['f63_lineup_avg_k_rate', 'f64_lineup_top3_k_rate'],
        'extra_sql': '',  # Loaded via kitchen_sink superset query
        'extra_select': '',
    },

    'k_trajectory': {
        'name': 'K Trajectory (Derived)',
        'hypothesis': 'K momentum (last3 - last10) captures hot/cold streaks better than raw avgs',
        'extra_features': ['f60_k_trajectory', 'f61_k_accel', 'f62_ip_k_efficiency'],
        'extra_sql': '',
        'extra_select': '',
    },

    'multi_book_odds': {
        'name': 'Multi-Book Odds Divergence',
        'hypothesis': 'DK vs FanDuel line disagreement signals sharp money',
        'extra_features': ['f70_dk_fd_spread', 'f71_dk_over_implied', 'f72_fd_over_implied'],
        # These need a separate query — loaded separately below
        'needs_separate_load': True,
        'extra_sql': '',
        'extra_select': '',
    },

    'fangraphs_advanced': {
        'name': 'FanGraphs Advanced Pitching',
        'hypothesis': 'o-swing%, z-contact%, FIP add pitcher quality signal',
        'extra_features': ['f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct'],
        # These need a separate query — loaded separately below
        'needs_separate_load': True,
        'extra_sql': '',
        'extra_select': '',
    },

    'pitcher_matchup': {
        'name': 'Pitcher vs Team History',
        'hypothesis': 'Pitcher-specific history vs this opponent adds edge',
        'extra_features': ['f65_vs_opp_k_per_9', 'f66_vs_opp_games'],
        'extra_sql': '',
        'extra_select': '',
    },

    'workload_deep': {
        'name': 'Deep Workload Features',
        'hypothesis': 'Pitch count trends and fatigue indicators matter',
        'extra_features': ['f67_season_starts', 'f68_k_per_pitch', 'f69_recent_workload_ratio'],
        'extra_sql': '',
        'extra_select': '',
    },

    'kitchen_sink': {
        'name': 'Kitchen Sink (All New Features)',
        'hypothesis': 'Combining all new features with CatBoost feature selection',
        'extra_features': [
            'f60_k_trajectory', 'f61_k_accel', 'f62_ip_k_efficiency',
            'f63_lineup_avg_k_rate', 'f64_lineup_top3_k_rate',
            'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
            'f67_season_starts', 'f68_k_per_pitch', 'f69_recent_workload_ratio',
        ],
        'extra_sql': """
            LEFT JOIN (
                SELECT
                    game_date,
                    opponent_team_abbr as team_abbr,
                    ROUND(AVG(COALESCE(k_rate_last_5, season_k_rate)), 4) as lineup_avg_k_rate,
                    ROUND(AVG(CASE WHEN batting_order <= 3
                        THEN COALESCE(k_rate_last_5, season_k_rate) END), 4) as lineup_top3_k_rate
                FROM `mlb_analytics.batter_game_summary`
                WHERE rolling_stats_games >= 3
                GROUP BY 1, 2
            ) lineup ON lineup.game_date = bp.game_date
                AND lineup.team_abbr = pgs.team_abbr
        """,
        'extra_select': """
            -- K trajectory features
            (pgs.k_avg_last_3 - pgs.k_avg_last_10) as f60_k_trajectory,
            (pgs.k_avg_last_3 - pgs.k_avg_last_5) as f61_k_accel,
            SAFE_DIVIDE(pgs.k_avg_last_5, NULLIF(pgs.ip_avg_last_5, 0)) as f62_ip_k_efficiency,
            -- Lineup K features
            lineup.lineup_avg_k_rate as f63_lineup_avg_k_rate,
            lineup.lineup_top3_k_rate as f64_lineup_top3_k_rate,
            -- Pitcher matchup features
            pgs.vs_opponent_k_per_9 as f65_vs_opp_k_per_9,
            pgs.vs_opponent_games as f66_vs_opp_games,
            -- Workload features
            pgs.season_games_started as f67_season_starts,
            SAFE_DIVIDE(pgs.k_avg_last_5, NULLIF(pgs.pitch_count_avg_last_5, 0)) as f68_k_per_pitch,
            SAFE_DIVIDE(pgs.games_last_30_days, 6.0) as f69_recent_workload_ratio,
        """,
    },
}

# Model type experiments
MODEL_EXPERIMENTS = {
    'lightgbm': {
        'name': 'LightGBM',
        'hypothesis': 'LightGBM may find different splits than CatBoost',
    },
    'catboost_deeper': {
        'name': 'CatBoost Deeper Trees',
        'hypothesis': 'Depth 7 with more regularization may capture interactions',
    },
    'catboost_wider': {
        'name': 'CatBoost More Iterations',
        'hypothesis': '500 iterations with lower LR may converge better',
    },
}


def build_query(experiment_id: Optional[str] = None) -> str:
    """Build training data query with optional experiment features."""
    exp = EXPERIMENTS.get(experiment_id, {})
    extra_select = exp.get('extra_select', '')
    extra_sql = exp.get('extra_sql', '')

    query = f"""
    WITH statcast_rolling AS (
        SELECT DISTINCT
            player_lookup, game_date,
            swstr_pct_last_3, swstr_pct_last_5, swstr_pct_season_prior,
            fb_velocity_last_3, fb_velocity_season_prior
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
        COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change

        {"," + extra_select if extra_select else ""}

    FROM `mlb_raw.bp_pitcher_props` bp
    JOIN `mlb_analytics.pitcher_game_summary` pgs
        ON pgs.game_date = bp.game_date
        AND LOWER(REGEXP_REPLACE(NORMALIZE(pgs.player_lookup, NFD), r'[\\W_]+', '')) = bp.player_lookup
    LEFT JOIN statcast_rolling sc
        ON REPLACE(pgs.player_lookup, '_', '') = REPLACE(sc.player_lookup, '_', '')
        AND pgs.game_date = sc.game_date
    {extra_sql}
    WHERE bp.market_id = 285
      AND bp.actual_value IS NOT NULL
      AND bp.projection_value IS NOT NULL
      AND bp.over_line IS NOT NULL
      AND pgs.innings_pitched >= 3.0
      AND pgs.rolling_stats_games >= 3
      AND pgs.game_date >= '2024-01-01'
    ORDER BY bp.game_date
    """
    return query


def train_model(X_train, y_train, model_type: str = 'catboost',
                seed: int = 42, hyperparams: Optional[Dict] = None):
    """Train a model of the specified type."""
    if model_type == 'catboost':
        from catboost import CatBoostClassifier
        params = {
            'depth': 5, 'learning_rate': 0.03, 'iterations': 300,
            'l2_leaf_reg': 3, 'subsample': 0.8, 'random_seed': seed,
            'verbose': 0, 'auto_class_weights': 'Balanced',
        }
        if hyperparams:
            params.update(hyperparams)
        model = CatBoostClassifier(**params)
        model.fit(X_train, y_train)
        return model

    elif model_type == 'xgboost':
        import xgboost as xgb
        params = {
            'max_depth': 5, 'learning_rate': 0.03, 'n_estimators': 300,
            'min_child_weight': 5, 'subsample': 0.8, 'colsample_bytree': 0.8,
            'gamma': 0.2, 'reg_alpha': 0.5, 'reg_lambda': 2,
            'random_state': seed, 'objective': 'binary:logistic',
            'eval_metric': 'logloss',
        }
        if hyperparams:
            params.update(hyperparams)
        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, verbose=False)
        return model

    elif model_type == 'lightgbm':
        import lightgbm as lgb
        params = {
            'max_depth': 5, 'learning_rate': 0.03, 'n_estimators': 300,
            'min_child_samples': 20, 'subsample': 0.8,
            'colsample_bytree': 0.8, 'reg_alpha': 0.5, 'reg_lambda': 2,
            'random_state': seed, 'objective': 'binary',
            'metric': 'binary_logloss', 'verbose': -1,
            'is_unbalance': True,
        }
        if hyperparams:
            params.update(hyperparams)
        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train)
        return model

    elif model_type == 'catboost_deeper':
        from catboost import CatBoostClassifier
        model = CatBoostClassifier(
            depth=7, learning_rate=0.02, iterations=400,
            l2_leaf_reg=5, subsample=0.7, random_seed=seed,
            verbose=0, auto_class_weights='Balanced',
        )
        model.fit(X_train, y_train)
        return model

    elif model_type == 'catboost_wider':
        from catboost import CatBoostClassifier
        model = CatBoostClassifier(
            depth=5, learning_rate=0.015, iterations=500,
            l2_leaf_reg=3, subsample=0.8, random_seed=seed,
            verbose=0, auto_class_weights='Balanced',
        )
        model.fit(X_train, y_train)
        return model

    else:
        raise ValueError(f"Unknown model type: {model_type}")


def run_walk_forward(df: pd.DataFrame, feature_cols: List[str],
                     model_type: str = 'catboost', window: int = 120,
                     retrain_days: int = 14, seed: int = 42,
                     hyperparams: Optional[Dict] = None) -> pd.DataFrame:
    """Run walk-forward simulation. Returns DataFrame of daily predictions."""
    results = []
    model = None
    last_train_date = None

    dates = sorted(df['game_date'].unique())
    available = [f for f in feature_cols if f in df.columns]

    for current_date in dates:
        # Check if we need to (re)train
        need_train = (model is None or
                      (current_date - last_train_date).days >= retrain_days)

        if need_train:
            train_end = current_date
            train_start = current_date - pd.Timedelta(days=window)
            train_mask = (df['game_date'] >= train_start) & (df['game_date'] < train_end)
            train_df = df[train_mask]

            if len(train_df) < 50:
                continue

            X_train = train_df[available].copy()
            for col in X_train.columns:
                X_train[col] = pd.to_numeric(X_train[col], errors='coerce')
            y_train = train_df['went_over'].astype(int)

            try:
                model = train_model(X_train, y_train, model_type, seed, hyperparams)
                last_train_date = current_date
            except Exception as e:
                logger.warning(f"Training failed at {current_date}: {e}")
                continue

        # Predict today
        today_mask = df['game_date'] == current_date
        today_df = df[today_mask]

        if len(today_df) == 0:
            continue

        X_test = today_df[available].copy()
        for col in X_test.columns:
            X_test[col] = pd.to_numeric(X_test[col], errors='coerce')

        try:
            proba = model.predict_proba(X_test)[:, 1]
        except Exception:
            continue

        for i, (_, row) in enumerate(today_df.iterrows()):
            edge = abs(proba[i] - 0.5) * 10
            predicted_over = int(proba[i] > 0.5)
            actual_over = int(row['actual_value'] > row['over_line'])
            correct = int(predicted_over == actual_over)

            results.append({
                'game_date': row['game_date'],
                'player_lookup': row.get('player_lookup', row.get('bp_player_lookup', '')),
                'line': row['over_line'],
                'actual': row['actual_value'],
                'probability': proba[i],
                'edge': edge,
                'predicted_over': predicted_over,
                'actual_over': actual_over,
                'correct': correct,
                'recommendation': 'OVER' if predicted_over else 'UNDER',
            })

    return pd.DataFrame(results)


def evaluate_predictions(preds: pd.DataFrame, label: str) -> Dict:
    """Evaluate walk-forward predictions with best-bets metrics."""
    if len(preds) == 0:
        return {'label': label, 'error': 'No predictions'}

    over = preds[preds['recommendation'] == 'OVER']
    under = preds[preds['recommendation'] == 'UNDER']

    result = {
        'label': label,
        'total_n': len(preds),
        'overall_hr': round(preds['correct'].mean() * 100, 1),
        'over_hr': round(over['correct'].mean() * 100, 1) if len(over) > 0 else None,
        'over_n': len(over),
        'under_hr': round(under['correct'].mean() * 100, 1) if len(under) > 0 else None,
        'under_n': len(under),
    }

    # Edge-filtered HR (production-relevant metrics)
    for edge_min in [1.0, 1.5, 2.0]:
        filtered = over[over['edge'] >= edge_min]
        if len(filtered) >= 10:
            hr = filtered['correct'].mean() * 100
            roi = (filtered['correct'].sum() * 91 - (len(filtered) - filtered['correct'].sum()) * 100) / (len(filtered) * 100) * 100
            result[f'over_e{edge_min}_hr'] = round(hr, 1)
            result[f'over_e{edge_min}_n'] = len(filtered)
            result[f'over_e{edge_min}_roi'] = round(roi, 1)

    # Top-1 per day (best bets simulation)
    capped = over[(over['edge'] >= 1.5) & (over['probability'] <= 0.75)]
    if len(capped) >= 10:
        top1 = capped.sort_values('edge', ascending=False).groupby('game_date').first().reset_index()
        hr = top1['correct'].mean() * 100
        roi = (top1['correct'].sum() * 91 - (len(top1) - top1['correct'].sum()) * 100) / (len(top1) * 100) * 100
        result['bb_top1_hr'] = round(hr, 1)
        result['bb_top1_n'] = len(top1)
        result['bb_top1_roi'] = round(roi, 1)

    # Top-2 per day
    if len(capped) >= 10:
        top2 = capped.sort_values('edge', ascending=False).groupby('game_date').head(2).reset_index(drop=True)
        hr = top2['correct'].mean() * 100
        roi = (top2['correct'].sum() * 91 - (len(top2) - top2['correct'].sum()) * 100) / (len(top2) * 100) * 100
        result['bb_top2_hr'] = round(hr, 1)
        result['bb_top2_n'] = len(top2)
        result['bb_top2_roi'] = round(roi, 1)

    return result


def run_experiment(experiment_id: str, df: pd.DataFrame,
                   model_type: str = 'catboost', seeds: List[int] = None) -> Dict:
    """Run a single experiment with multiple seeds."""
    seeds = seeds or [42, 123, 456]
    exp = EXPERIMENTS.get(experiment_id, {})
    extra_features = exp.get('extra_features', [])
    feature_cols = BASELINE_FEATURES + extra_features

    print(f"\n{'='*70}")
    print(f"EXPERIMENT: {exp.get('name', experiment_id)}")
    print(f"Hypothesis: {exp.get('hypothesis', 'N/A')}")
    print(f"Features: {len(BASELINE_FEATURES)} baseline + {len(extra_features)} new = {len(feature_cols)}")
    print(f"Seeds: {seeds}")
    print(f"{'='*70}")

    all_evals = []
    for seed in seeds:
        t0 = time.time()
        preds = run_walk_forward(df, feature_cols, model_type, seed=seed)
        elapsed = time.time() - t0
        ev = evaluate_predictions(preds, f"{experiment_id}_seed{seed}")
        ev['seed'] = seed
        ev['elapsed_s'] = round(elapsed, 1)
        all_evals.append(ev)

        bb = ev.get('bb_top1_hr', 'N/A')
        print(f"  Seed {seed}: OVER e1.5+ = {ev.get('over_e1.5_hr', 'N/A')}% "
              f"(N={ev.get('over_e1.5_n', 0)}), BB top1 = {bb}% — {elapsed:.0f}s")

    # Aggregate across seeds
    agg = {}
    for key in ['overall_hr', 'over_hr', 'over_e1.0_hr', 'over_e1.5_hr', 'over_e2.0_hr',
                'bb_top1_hr', 'bb_top2_hr', 'bb_top1_roi', 'bb_top2_roi']:
        vals = [e[key] for e in all_evals if key in e and e[key] is not None]
        if vals:
            agg[f'{key}_mean'] = round(np.mean(vals), 1)
            agg[f'{key}_std'] = round(np.std(vals), 1)

    return {
        'experiment_id': experiment_id,
        'name': exp.get('name', experiment_id),
        'hypothesis': exp.get('hypothesis', ''),
        'model_type': model_type,
        'n_features': len(feature_cols),
        'extra_features': extra_features,
        'seeds': seeds,
        'per_seed': all_evals,
        'aggregate': agg,
    }


def run_model_experiment(model_type: str, df: pd.DataFrame,
                         seeds: List[int] = None,
                         hyperparams: Optional[Dict] = None) -> Dict:
    """Run a model-type experiment (same features, different model)."""
    seeds = seeds or [42, 123, 456]
    exp = MODEL_EXPERIMENTS.get(model_type, {'name': model_type, 'hypothesis': ''})

    print(f"\n{'='*70}")
    print(f"MODEL EXPERIMENT: {exp['name']}")
    print(f"Hypothesis: {exp['hypothesis']}")
    print(f"Seeds: {seeds}")
    print(f"{'='*70}")

    all_evals = []
    for seed in seeds:
        t0 = time.time()
        preds = run_walk_forward(df, BASELINE_FEATURES, model_type, seed=seed,
                                 hyperparams=hyperparams)
        elapsed = time.time() - t0
        ev = evaluate_predictions(preds, f"{model_type}_seed{seed}")
        ev['seed'] = seed
        ev['elapsed_s'] = round(elapsed, 1)
        all_evals.append(ev)

        bb = ev.get('bb_top1_hr', 'N/A')
        print(f"  Seed {seed}: OVER e1.5+ = {ev.get('over_e1.5_hr', 'N/A')}% "
              f"(N={ev.get('over_e1.5_n', 0)}), BB top1 = {bb}% — {elapsed:.0f}s")

    agg = {}
    for key in ['overall_hr', 'over_hr', 'over_e1.5_hr', 'bb_top1_hr', 'bb_top1_roi']:
        vals = [e[key] for e in all_evals if key in e and e[key] is not None]
        if vals:
            agg[f'{key}_mean'] = round(np.mean(vals), 1)
            agg[f'{key}_std'] = round(np.std(vals), 1)

    return {
        'experiment_id': model_type,
        'name': exp['name'],
        'model_type': model_type,
        'seeds': seeds,
        'per_seed': all_evals,
        'aggregate': agg,
    }


def print_comparison(baseline_result: Dict, experiment_results: List[Dict]):
    """Print comparison table."""
    print(f"\n{'='*90}")
    print("EXPERIMENT RESULTS COMPARISON")
    print(f"{'='*90}")

    header = f"{'Experiment':<25} {'OVER e1.5 HR':>12} {'BB Top1 HR':>12} {'BB Top1 ROI':>12} {'Verdict':>10}"
    print(header)
    print("-" * 90)

    baseline_bb = baseline_result['aggregate'].get('bb_top1_hr_mean')
    baseline_row = (
        f"{'BASELINE (CatBoost V1)':<25} "
        f"{baseline_result['aggregate'].get('over_e1.5_hr_mean', 'N/A'):>12} "
        f"{baseline_bb or 'N/A':>12} "
        f"{baseline_result['aggregate'].get('bb_top1_roi_mean', 'N/A'):>12} "
        f"{'---':>10}"
    )
    print(baseline_row)

    for exp in experiment_results:
        exp_bb = exp['aggregate'].get('bb_top1_hr_mean')
        delta = ''
        verdict = 'N/A'
        if baseline_bb and exp_bb:
            d = exp_bb - baseline_bb
            delta = f"({d:+.1f}pp)"
            if d >= 3.0:
                verdict = 'PROMOTE'
            elif d >= 1.5:
                verdict = 'PROMISING'
            elif d >= -1.5:
                verdict = 'NOISE'
            else:
                verdict = 'DEAD_END'

        name = exp.get('name', exp['experiment_id'])[:24]
        row = (
            f"{name:<25} "
            f"{exp['aggregate'].get('over_e1.5_hr_mean', 'N/A'):>12} "
            f"{f'{exp_bb} {delta}' if exp_bb else 'N/A':>12} "
            f"{exp['aggregate'].get('bb_top1_roi_mean', 'N/A'):>12} "
            f"{verdict:>10}"
        )
        print(row)

    print(f"\nVerdicts: PROMOTE (>=+3pp), PROMISING (+1.5-3pp), NOISE (±1.5pp), DEAD_END (<-1.5pp)")


def main():
    parser = argparse.ArgumentParser(description="MLB Experiment Runner")
    parser.add_argument("--experiment", nargs='*', help="Specific experiment(s) to run")
    parser.add_argument("--model-experiment", nargs='*', help="Model type experiment(s)")
    parser.add_argument("--all", action="store_true", help="Run all experiments")
    parser.add_argument("--list", action="store_true", help="List available experiments")
    parser.add_argument("--seeds", default="42,123,456", help="Comma-separated seeds")
    args = parser.parse_args()

    if args.list:
        print("\nFeature Experiments:")
        for eid, exp in EXPERIMENTS.items():
            print(f"  {eid:20s} — {exp['name']} (+{len(exp['extra_features'])} features)")
        print("\nModel Experiments:")
        for mid, mexp in MODEL_EXPERIMENTS.items():
            print(f"  {mid:20s} — {mexp['name']}")
        return

    seeds = [int(s) for s in args.seeds.split(',')]

    # Determine which experiments to run
    feature_exps = []
    model_exps = []
    if args.all:
        feature_exps = list(EXPERIMENTS.keys())
        model_exps = list(MODEL_EXPERIMENTS.keys())
    else:
        feature_exps = args.experiment or []
        model_exps = args.model_experiment or []

    if not feature_exps and not model_exps:
        print("No experiments specified. Use --all, --experiment, or --model-experiment")
        print("Use --list to see available experiments")
        return

    # Load data (query depends on whether we need extra features)
    client = bigquery.Client(project=PROJECT_ID)

    # Always load with kitchen_sink query (superset of all JOINs + derived features)
    query = build_query('kitchen_sink')

    print("Loading training data from BigQuery...")
    df = client.query(query).to_dataframe()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values('game_date').reset_index(drop=True)
    print(f"Loaded {len(df):,} samples ({df['game_date'].min().date()} to {df['game_date'].max().date()})")
    print(f"Available columns: {len(df.columns)}")

    # Load separate data for experiments that need extra JOINs
    if 'multi_book_odds' in feature_exps or args.all:
        print("Loading multi-book odds data...")
        odds_q = """
        SELECT game_date, player_lookup,
            bookmaker, point, over_implied_prob
        FROM `mlb_raw.oddsa_pitcher_props`
        WHERE market_key = 'pitcher_strikeouts'
            AND bookmaker IN ('draftkings', 'fanduel')
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY game_date, player_lookup, bookmaker
            ORDER BY snapshot_time DESC
        ) = 1
        """
        odds_df = client.query(odds_q).to_dataframe()
        dk = odds_df[odds_df['bookmaker'] == 'draftkings'].set_index(['game_date', 'player_lookup'])
        fd = odds_df[odds_df['bookmaker'] == 'fanduel'].set_index(['game_date', 'player_lookup'])

        # Merge DK/FD odds onto main df
        df['_key'] = list(zip(df['game_date'], df['bp_player_lookup']))
        dk_map = dk['over_implied_prob'].to_dict()
        fd_map = fd['over_implied_prob'].to_dict()
        dk_pt = dk['point'].to_dict()
        fd_pt = fd['point'].to_dict()
        df['f70_dk_fd_spread'] = df['_key'].apply(
            lambda k: (dk_pt.get(k, 0) or 0) - (fd_pt.get(k, 0) or 0))
        df['f71_dk_over_implied'] = df['_key'].apply(lambda k: dk_map.get(k))
        df['f72_fd_over_implied'] = df['_key'].apply(lambda k: fd_map.get(k))
        df.drop(columns=['_key'], inplace=True)
        print(f"  Multi-book: {df['f71_dk_over_implied'].notna().sum()} DK, "
              f"{df['f72_fd_over_implied'].notna().sum()} FD matches")

    if 'fangraphs_advanced' in feature_exps or args.all:
        print("Loading FanGraphs advanced stats...")
        fg_q = """
        SELECT player_lookup, season_year,
            o_swing_pct, z_contact_pct, fip, gb_pct
        FROM `mlb_raw.fangraphs_pitcher_season_stats`
        """
        fg_df = client.query(fg_q).to_dataframe()
        fg_df = fg_df.set_index(['player_lookup', 'season_year'])
        df['_year'] = df['game_date'].dt.year
        df['_fg_key'] = list(zip(df['player_lookup'], df['_year']))
        for col, fg_col in [('f70_o_swing_pct', 'o_swing_pct'),
                             ('f71_z_contact_pct', 'z_contact_pct'),
                             ('f72_fip', 'fip'), ('f73_gb_pct', 'gb_pct')]:
            col_map = fg_df[fg_col].to_dict()
            df[col] = df['_fg_key'].apply(lambda k: col_map.get(k))
        df.drop(columns=['_year', '_fg_key'], inplace=True)
        n_fg = df['f70_o_swing_pct'].notna().sum()
        print(f"  FanGraphs: {n_fg}/{len(df)} matched ({n_fg/len(df)*100:.0f}%)")

    # Run baseline
    print("\n" + "="*70)
    print("BASELINE: CatBoost V1 (31 features)")
    print("="*70)
    baseline = run_model_experiment('catboost', df, seeds=seeds)

    # Run feature experiments
    feature_results = []
    for eid in feature_exps:
        result = run_experiment(eid, df, seeds=seeds)
        feature_results.append(result)

    # Run model experiments
    model_results = []
    for mid in model_exps:
        result = run_model_experiment(mid, df, seeds=seeds)
        model_results.append(result)

    # Print comparison
    all_results = feature_results + model_results
    if all_results:
        print_comparison(baseline, all_results)

    # Save results
    output_path = Path(OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results_file = output_path / f"mlb_experiments_{timestamp}.json"

    save_data = {
        'timestamp': timestamp,
        'seeds': seeds,
        'baseline': baseline,
        'feature_experiments': feature_results,
        'model_experiments': model_results,
    }

    with open(results_file, 'w') as f:
        json.dump(save_data, f, indent=2, default=str)

    print(f"\nResults saved to {results_file}")


if __name__ == "__main__":
    main()
