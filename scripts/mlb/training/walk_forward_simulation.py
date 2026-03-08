#!/usr/bin/env python3
"""
Walk-Forward Simulation for MLB Pitcher Strikeouts

Replays the 2025 season as if it were real-time to test:
1. Training windows: 42, 56, 90, 120 days
2. Edge thresholds: 0.5, 0.75, 1.0, 1.5, 2.0 K
3. Retrain cadence (every 14 days)
4. Model drift detection
5. Signal effectiveness

For each game_date in the simulation period:
  - Build features using ONLY data available before game_date
  - Train model if retrain interval reached
  - Generate predictions with current model
  - Grade against actuals
  - Track HR, MAE, edge calibration

Usage:
    PYTHONPATH=. python scripts/mlb/training/walk_forward_simulation.py \\
        --start-date 2025-04-01 \\
        --end-date 2025-09-28 \\
        --training-windows 42,56,90,120 \\
        --edge-thresholds 0.5,0.75,1.0,1.5,2.0 \\
        --retrain-interval 14 \\
        --output-dir results/mlb_walkforward_2025/
"""

import argparse
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict

import numpy as np
import pandas as pd
import xgboost as xgb
from google.cloud import bigquery
from sklearn.metrics import accuracy_score, mean_absolute_error

PROJECT_ID = "nba-props-platform"


def parse_args():
    parser = argparse.ArgumentParser(description="MLB Walk-Forward Simulation")
    parser.add_argument("--start-date", default="2025-04-01",
                       help="Simulation start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2025-09-28",
                       help="Simulation end date (YYYY-MM-DD)")
    parser.add_argument("--training-windows", default="42,56,90,120",
                       help="Comma-separated training window sizes in days")
    parser.add_argument("--edge-thresholds", default="0.5,0.75,1.0,1.5,2.0",
                       help="Comma-separated edge thresholds in K")
    parser.add_argument("--retrain-interval", type=int, default=14,
                       help="Days between retrains")
    parser.add_argument("--output-dir", default="results/mlb_walkforward_2025/",
                       help="Output directory")
    parser.add_argument("--model-type", default="both",
                       choices=["xgboost", "catboost", "both"],
                       help="Model type to test")
    parser.add_argument("--filter-nan-predictions", action="store_true",
                       help="Hybrid: train on all data, predict only for clean-statcast pitchers")
    return parser.parse_args()


def load_data(client: bigquery.Client) -> pd.DataFrame:
    """Load all available data for the simulation period (V3: 40 features)."""
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

        -- Features
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

        -- Line-relative features
        (pgs.k_avg_last_5 - bp.over_line) as f30_k_avg_vs_line,
        bp.over_line as f32_line_level,

        -- BettingPros features
        bp.projection_value as f40_bp_projection,
        (bp.projection_value - bp.over_line) as f41_projection_diff,
        CASE
            WHEN bp.over_odds < 0 THEN ABS(bp.over_odds) / (ABS(bp.over_odds) + 100.0)
            ELSE 100.0 / (bp.over_odds + 100.0)
        END as f44_over_implied_prob,

        -- Rolling Statcast Features with COALESCE fallbacks (Session 433)
        COALESCE(sc.swstr_pct_last_3, pgs.season_swstr_pct) as f50_swstr_pct_last_3,
        COALESCE(sc.fb_velocity_last_3, sc.fb_velocity_season_prior) as f51_fb_velocity_last_3,
        COALESCE(sc.swstr_pct_last_3 - sc.swstr_pct_season_prior, 0.0) as f52_swstr_trend,
        COALESCE(sc.fb_velocity_season_prior - sc.fb_velocity_last_3, 0.0) as f53_velocity_change,

        -- Pitcher matchup features (Session 435/437 — derived from gamebook)
        pgs.vs_opponent_k_per_9 as f65_vs_opp_k_per_9,
        pgs.vs_opponent_games as f66_vs_opp_games,

        -- Deep workload features (Session 435)
        pgs.season_games_started as f67_season_starts,
        SAFE_DIVIDE(pgs.k_avg_last_5, NULLIF(pgs.pitch_count_avg_last_5, 0)) as f68_k_per_pitch,
        SAFE_DIVIDE(pgs.games_last_30_days, 6.0) as f69_recent_workload_ratio,

        -- FanGraphs advanced pitching features (Session 436)
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

    # Report Statcast coverage
    sc_cols = [c for c in df.columns if c.startswith('f5')]
    if sc_cols:
        sc_coverage = df[sc_cols[0]].notna().mean() * 100
        print(f"Statcast feature coverage: {sc_coverage:.1f}%")

    return df


def get_features(df: pd.DataFrame) -> list:
    """Get available feature columns (V3: 40 features)."""
    feature_cols = [
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
        # Rolling Statcast (LEFT JOIN — may be NULL, handled natively by models)
        'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
        'f52_swstr_trend', 'f53_velocity_change',
        # Pitcher matchup (Session 435/437 — may be NULL for first matchups)
        'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
        # Deep workload (Session 435)
        'f67_season_starts', 'f68_k_per_pitch', 'f69_recent_workload_ratio',
        # FanGraphs advanced (Session 436 — LEFT JOIN, NaN-tolerant)
        'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
    ]
    return [f for f in feature_cols if f in df.columns]


def train_model(X_train: pd.DataFrame, y_train: pd.Series,
                model_type: str = 'xgboost') -> object:
    """Train classifier with standard params."""
    if model_type == 'catboost':
        from catboost import CatBoostClassifier
        model = CatBoostClassifier(
            depth=5,
            learning_rate=0.015,    # V3 wider config
            iterations=500,         # V3 wider config
            l2_leaf_reg=3,
            subsample=0.8,
            random_seed=42,
            verbose=0,
            auto_class_weights='Balanced',
        )
        model.fit(X_train, y_train)
    else:
        params = {
            'max_depth': 5,
            'learning_rate': 0.03,
            'n_estimators': 300,
            'min_child_weight': 5,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'gamma': 0.2,
            'reg_alpha': 0.5,
            'reg_lambda': 2,
            'random_state': 42,
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
        }
        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, verbose=False)
    return model


def simulate_window(
    df: pd.DataFrame,
    feature_cols: list,
    training_window_days: int,
    edge_thresholds: list,
    retrain_interval: int,
    sim_start: pd.Timestamp,
    sim_end: pd.Timestamp,
    model_type: str = 'xgboost',
    filter_nan_predictions: bool = False,
) -> Dict:
    """Run walk-forward simulation for a single training window size.

    If filter_nan_predictions=True, predictions are only generated for
    pitchers with complete statcast data (hybrid: train on all, predict on clean).
    """
    results_by_threshold = {t: [] for t in edge_thresholds}
    retrain_log = []
    daily_metrics = []

    current_model = None
    last_train_date = None
    game_dates = sorted(df[
        (df['game_date'] >= sim_start) & (df['game_date'] <= sim_end)
    ]['game_date'].unique())

    for game_date in game_dates:
        # Check if we need to retrain
        needs_retrain = (
            current_model is None or
            last_train_date is None or
            (game_date - last_train_date).days >= retrain_interval
        )

        if needs_retrain:
            # Training data: window_days before this game_date
            train_start = game_date - pd.Timedelta(days=training_window_days)
            train_mask = (df['game_date'] >= train_start) & (df['game_date'] < game_date)
            train_df = df[train_mask]

            X_train = train_df[feature_cols].copy()
            for col in X_train.columns:
                X_train[col] = pd.to_numeric(X_train[col], errors='coerce')
            y_train = train_df['went_over'].astype(int)

            # CatBoost/XGBoost handle NaN natively — don't drop rows
            if len(X_train) < 50:
                continue

            current_model = train_model(X_train, y_train, model_type=model_type)
            last_train_date = game_date
            retrain_log.append({
                'game_date': str(game_date.date()),
                'training_window': training_window_days,
                'train_samples': len(X_train),
                'train_start': str(train_start.date()),
            })

        # Get test data for this game_date
        test_mask = df['game_date'] == game_date
        test_df = df[test_mask].copy()

        X_test = test_df[feature_cols].copy()
        for col in X_test.columns:
            X_test[col] = pd.to_numeric(X_test[col], errors='coerce')

        # Hybrid mode: filter predictions to clean-statcast pitchers only
        if filter_nan_predictions:
            statcast_cols = ['f50_swstr_pct_last_3', 'f51_fb_velocity_last_3']
            sc_cols_present = [c for c in statcast_cols if c in X_test.columns]
            if sc_cols_present:
                clean_mask = ~X_test[sc_cols_present].isna().any(axis=1)
                X_test = X_test[clean_mask]
                test_df = test_df[clean_mask]

        if len(X_test) == 0:
            continue

        y_test = test_df['went_over'].astype(int)

        # Generate predictions
        y_proba = current_model.predict_proba(X_test)[:, 1]

        # Calculate edge for each prediction
        # Edge proxy: (probability - 0.5) mapped to K scale
        # More precisely: how far the prediction is from the line
        predicted_over = y_proba > 0.5
        model_edge = np.abs(y_proba - 0.5) * 10  # Scale to approximate K edge

        # Evaluate at each edge threshold
        for threshold in edge_thresholds:
            edge_mask = model_edge >= threshold
            if edge_mask.sum() == 0:
                continue

            y_filtered = y_test.values[edge_mask]
            y_pred_filtered = predicted_over[edge_mask]
            correct = (y_pred_filtered == y_filtered).astype(int)

            for idx in range(len(correct)):
                results_by_threshold[threshold].append({
                    'game_date': str(game_date.date()),
                    'correct': int(correct[idx]),
                    'actual_over': int(y_filtered[idx]),
                    'predicted_over': int(y_pred_filtered[idx]),
                    'proba': float(y_proba[edge_mask][idx]),
                    'edge': float(model_edge[edge_mask][idx]),
                })

        # Daily summary (no edge filter)
        y_pred_all = (y_proba > 0.5).astype(int)
        daily_correct = (y_pred_all == y_test.values).astype(int)
        daily_metrics.append({
            'game_date': str(game_date.date()),
            'predictions': len(y_test),
            'correct': int(daily_correct.sum()),
            'hr': round(daily_correct.mean() * 100, 1),
            'over_rate': round(y_test.mean() * 100, 1),
        })

    return {
        'results_by_threshold': results_by_threshold,
        'retrain_log': retrain_log,
        'daily_metrics': daily_metrics,
    }


def main():
    args = parse_args()

    training_windows = [int(w) for w in args.training_windows.split(',')]
    edge_thresholds = [float(t) for t in args.edge_thresholds.split(',')]
    sim_start = pd.Timestamp(args.start_date)
    sim_end = pd.Timestamp(args.end_date)

    if args.model_type == 'both':
        model_types = ['xgboost', 'catboost']
    else:
        model_types = [args.model_type]

    print("=" * 80)
    print(" MLB WALK-FORWARD SIMULATION")
    print("=" * 80)
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Training windows: {training_windows}")
    print(f"Edge thresholds: {edge_thresholds}")
    print(f"Model types: {model_types}")
    print(f"Retrain interval: {args.retrain_interval} days")
    print()

    # Load data
    client = bigquery.Client(project=PROJECT_ID)
    df = load_data(client)
    feature_cols = get_features(df)
    print(f"Using {len(feature_cols)} features: {feature_cols}")
    print()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run simulation for each model type and training window
    # Key: (model_type, window) -> result
    all_results = {}

    for model_type in model_types:
        print(f"\n{'#'*80}")
        print(f"# MODEL TYPE: {model_type.upper()}")
        print(f"{'#'*80}")

        for window in training_windows:
            print(f"\n{'='*60}")
            print(f"[{model_type}] Training Window: {window} days")
            print(f"{'='*60}")

            result = simulate_window(
                df=df,
                feature_cols=feature_cols,
                training_window_days=window,
                edge_thresholds=edge_thresholds,
                retrain_interval=args.retrain_interval,
                sim_start=sim_start,
                sim_end=sim_end,
                model_type=model_type,
                filter_nan_predictions=args.filter_nan_predictions,
            )

            all_results[(model_type, window)] = result

            # Print summary for this window
            print(f"\nRetrains: {len(result['retrain_log'])}")
            print(f"Game days with predictions: {len(result['daily_metrics'])}")

            print(f"\n{'Edge':>8} {'Picks':>8} {'HR':>8} {'Edge Avg':>10}")
            print("-" * 40)

            for threshold in edge_thresholds:
                picks = result['results_by_threshold'][threshold]
                if picks:
                    n = len(picks)
                    hr = sum(p['correct'] for p in picks) / n * 100
                    avg_edge = np.mean([p['edge'] for p in picks])
                    print(f"{threshold:>8.1f} {n:>8} {hr:>7.1f}% {avg_edge:>9.2f}")
                else:
                    print(f"{threshold:>8.1f} {'0':>8} {'N/A':>8} {'N/A':>10}")

    # ==========================================================================
    # CROSS-WINDOW COMPARISON (per model type)
    # ==========================================================================
    for model_type in model_types:
        print("\n" + "=" * 80)
        print(f"CROSS-WINDOW COMPARISON — {model_type.upper()}")
        print("=" * 80)

        print(f"\n{'Window':>8}", end="")
        for t in edge_thresholds:
            print(f"  edge>={t:.1f}", end="")
        print()
        print("-" * (8 + len(edge_thresholds) * 12))

        for window in training_windows:
            print(f"{window:>6}d", end="")
            for threshold in edge_thresholds:
                picks = all_results[(model_type, window)]['results_by_threshold'][threshold]
                if picks:
                    hr = sum(p['correct'] for p in picks) / len(picks) * 100
                    n = len(picks)
                    print(f"  {hr:5.1f}%/{n:<4}", end="")
                else:
                    print(f"  {'N/A':>10}", end="")
            print()

    # ==========================================================================
    # HEAD-TO-HEAD: XGBoost vs CatBoost (if both)
    # ==========================================================================
    if len(model_types) > 1:
        print("\n" + "=" * 80)
        print("HEAD-TO-HEAD: XGBoost vs CatBoost")
        print("=" * 80)

        print(f"\n{'Window':>8} {'Edge':>6}", end="")
        for mt in model_types:
            print(f"  {mt:>14}", end="")
        print(f"  {'Delta':>8}")
        print("-" * 60)

        for window in training_windows:
            for threshold in edge_thresholds:
                hrs = {}
                ns = {}
                for mt in model_types:
                    picks = all_results[(mt, window)]['results_by_threshold'][threshold]
                    if picks:
                        hrs[mt] = sum(p['correct'] for p in picks) / len(picks) * 100
                        ns[mt] = len(picks)
                    else:
                        hrs[mt] = None
                        ns[mt] = 0

                if all(hrs.get(mt) is not None for mt in model_types):
                    print(f"{window:>6}d {threshold:>5.1f}", end="")
                    for mt in model_types:
                        print(f"  {hrs[mt]:5.1f}%/{ns[mt]:<4}", end="")
                    delta = hrs['catboost'] - hrs['xgboost']
                    print(f"  {delta:>+7.1f}pp")

    # ==========================================================================
    # SAVE RESULTS
    # ==========================================================================

    # Save detailed results
    for (model_type, window), result in all_results.items():
        prefix = f"{model_type}_{window}d"

        # Daily predictions
        daily_df = pd.DataFrame(result['daily_metrics'])
        daily_df.to_csv(output_dir / f"daily_metrics_{prefix}.csv", index=False)

        # Retrain log
        retrain_df = pd.DataFrame(result['retrain_log'])
        retrain_df.to_csv(output_dir / f"retrain_log_{prefix}.csv", index=False)

        # Per-threshold results
        for threshold in edge_thresholds:
            picks = result['results_by_threshold'][threshold]
            if picks:
                picks_df = pd.DataFrame(picks)
                fname = f"predictions_{prefix}_edge{threshold:.1f}.csv"
                picks_df.to_csv(output_dir / fname, index=False)

    # Save summary
    summary = {
        'simulation_period': f"{args.start_date} to {args.end_date}",
        'training_windows': training_windows,
        'edge_thresholds': edge_thresholds,
        'model_types': model_types,
        'retrain_interval': args.retrain_interval,
        'total_samples': len(df),
        'features': feature_cols,
        'results': {},
    }

    for (model_type, window), result in all_results.items():
        key = f"{model_type}_{window}d"
        summary['results'][key] = {}
        for threshold in edge_thresholds:
            picks = result['results_by_threshold'][threshold]
            if picks:
                n = len(picks)
                hr = sum(p['correct'] for p in picks) / n * 100
                summary['results'][key][str(threshold)] = {
                    'n': n,
                    'hr': round(hr, 2),
                }

    with open(output_dir / "simulation_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)

    # ==========================================================================
    # MONTHLY BREAKDOWN (best config)
    # ==========================================================================
    print("\n" + "=" * 80)
    print("MONTHLY BREAKDOWN (best config)")
    print("=" * 80)

    # Find best model/window/threshold combo
    best_hr = 0
    best_combo = ('xgboost', 56, 1.0)
    for (model_type, window), result in all_results.items():
        for threshold in edge_thresholds:
            picks = result['results_by_threshold'][threshold]
            if picks and len(picks) >= 30:
                hr = sum(p['correct'] for p in picks) / len(picks) * 100
                if hr > best_hr:
                    best_hr = hr
                    best_combo = (model_type, window, threshold)

    best_model, best_window, best_threshold = best_combo
    print(f"\nBest combo: {best_model} {best_window}d window, edge >= {best_threshold} ({best_hr:.1f}% HR)")

    picks = all_results[(best_model, best_window)]['results_by_threshold'][best_threshold]
    if picks:
        picks_df = pd.DataFrame(picks)
        picks_df['month'] = pd.to_datetime(picks_df['game_date']).dt.to_period('M')
        monthly = picks_df.groupby('month').agg({
            'correct': ['sum', 'count', 'mean']
        })
        monthly.columns = ['wins', 'total', 'hr']
        monthly['hr'] = (monthly['hr'] * 100).round(1)
        print(monthly.to_string())

    # OVER vs UNDER breakdown for best config
    if picks:
        print(f"\nDirection breakdown ({best_model} {best_window}d, edge >= {best_threshold}):")
        over_picks = [p for p in picks if p['predicted_over'] == 1]
        under_picks = [p for p in picks if p['predicted_over'] == 0]
        if over_picks:
            over_hr = sum(p['correct'] for p in over_picks) / len(over_picks) * 100
            print(f"  OVER:  {sum(p['correct'] for p in over_picks)}-"
                  f"{len(over_picks)-sum(p['correct'] for p in over_picks)} "
                  f"({over_hr:.1f}% HR, N={len(over_picks)})")
        if under_picks:
            under_hr = sum(p['correct'] for p in under_picks) / len(under_picks) * 100
            print(f"  UNDER: {sum(p['correct'] for p in under_picks)}-"
                  f"{len(under_picks)-sum(p['correct'] for p in under_picks)} "
                  f"({under_hr:.1f}% HR, N={len(under_picks)})")

    print("\n" + "=" * 80)
    print(f"Results saved to: {output_dir}")
    print("=" * 80)


if __name__ == "__main__":
    main()
