#!/usr/bin/env python3
"""
Challenger Model v10 - Extended Training Data

This trains a challenger to the current champion (catboost_v8) using:
- Same architecture: CatBoost with 33 features + stacked ensemble
- Extended data: Nov 2021 through Jan 2026 (adds 2024-25 season)

The champion was trained on data ending June 2024 (1.7 years stale).
This challenger adds ~7 months of new 2024-25 season data.

Usage:
    PYTHONPATH=. python ml/train_challenger_v10.py
    PYTHONPATH=. python ml/train_challenger_v10.py --dry-run  # Check data availability
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import numpy as np
import pandas as pd
import json
from datetime import datetime, date
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
import xgboost as xgb
import lightgbm as lgb
import catboost as cb

PROJECT_ID = "nba-props-platform"
MODEL_OUTPUT_DIR = Path("models")

# Champion baseline (for comparison)
CHAMPION_MAE = 3.404  # catboost_v8 stacked MAE
CHAMPION_VERSION = "v8"

def parse_args():
    parser = argparse.ArgumentParser(description='Train challenger model v10')
    parser.add_argument('--dry-run', action='store_true', help='Check data availability without training')
    parser.add_argument('--end-date', type=str, default=None, help='End date for training data (YYYY-MM-DD)')
    return parser.parse_args()

def main():
    args = parse_args()

    # Determine end date - use yesterday to ensure complete data
    if args.end_date:
        end_date = args.end_date
    else:
        end_date = (date.today() - pd.Timedelta(days=1)).strftime('%Y-%m-%d')

    print("=" * 80)
    print(" CHALLENGER MODEL V10 - EXTENDED TRAINING DATA")
    print("=" * 80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Training data: 2021-11-01 to {end_date}")
    print(f"Champion baseline: {CHAMPION_VERSION} MAE = {CHAMPION_MAE}")
    print()

    # ============================================================================
    # STEP 1: LOAD DATA
    # ============================================================================

    print("=" * 80)
    print("STEP 1: LOADING DATA")
    print("=" * 80)

    client = bigquery.Client(project=PROJECT_ID)

    # The feature store v2 already contains all 33 features pre-calculated:
    # Indices 0-24: Base features (scoring, matchup, team context)
    # Indices 25-28: Vegas lines (points_line, opening_line, line_move, has_vegas_line)
    # Indices 29-30: Opponent history (avg_points_vs_opponent, games_vs_opponent)
    # Indices 31-32: Minutes/efficiency (minutes_avg_last_10, ppm_avg_last_10)
    query = f"""
    SELECT
      mf.player_lookup,
      mf.game_date,
      mf.features,
      pgs.points as actual_points
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
    INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '2021-11-01' AND '{end_date}'
      AND mf.feature_count = 33
      AND ARRAY_LENGTH(mf.features) = 33
      AND pgs.points IS NOT NULL
      AND pgs.minutes_played > 0
    ORDER BY mf.game_date
    """

    print("Fetching data...")
    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} samples")

    # Data breakdown by season
    df['season'] = df['game_date'].apply(lambda d: f"{d.year}-{d.year+1}" if d.month >= 10 else f"{d.year-1}-{d.year}")
    season_counts = df.groupby('season').size()
    print("\nSamples by season:")
    for season, count in season_counts.items():
        marker = " (NEW)" if season in ['2024-2025'] else ""
        print(f"  {season}: {count:,}{marker}")

    # Compare to champion
    champion_samples = 76863  # From v8 metadata
    new_samples = len(df) - champion_samples
    print(f"\nCompared to champion ({CHAMPION_VERSION}):")
    print(f"  Champion samples: {champion_samples:,}")
    print(f"  New samples added: {new_samples:,} ({new_samples/champion_samples*100:.1f}% more)")
    print()

    if args.dry_run:
        print("=" * 80)
        print("DRY RUN - Stopping before training")
        print("=" * 80)
        print(f"Would train on {len(df):,} samples")
        print(f"Data range: {df['game_date'].min()} to {df['game_date'].max()}")
        return

    # ============================================================================
    # STEP 2: PREPARE FEATURES
    # ============================================================================

    print("=" * 80)
    print("STEP 2: PREPARING FEATURES")
    print("=" * 80)

    # All 33 features are already in the feature store in order
    all_features = [
        # Base features (indices 0-24)
        "points_avg_last_5", "points_avg_last_10", "points_avg_season",
        "points_std_last_10", "games_in_last_7_days", "fatigue_score",
        "shot_zone_mismatch_score", "pace_score", "usage_spike_score",
        "rest_advantage", "injury_risk", "recent_trend", "minutes_change",
        "opponent_def_rating", "opponent_pace", "home_away", "back_to_back",
        "playoff_game", "pct_paint", "pct_mid_range", "pct_three",
        "pct_free_throw", "team_pace", "team_off_rating", "team_win_pct",
        # Vegas features (indices 25-28)
        "vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line",
        # Opponent history (indices 29-30)
        "avg_points_vs_opponent", "games_vs_opponent",
        # Minutes/efficiency (indices 31-32)
        "minutes_avg_last_10", "ppm_avg_last_10"
    ]

    # Extract features directly from the feature array
    X = pd.DataFrame(df['features'].tolist(), columns=all_features)

    # Handle any NaN values (impute with median)
    X = X.fillna(X.median())

    y = df['actual_points'].astype(float)

    print(f"Features: {len(all_features)}")
    print(f"  Base: 25 (indices 0-24)")
    print(f"  Vegas: 4 (indices 25-28)")
    print(f"  Opponent: 2 (indices 29-30)")
    print(f"  Minutes/PPM: 2 (indices 31-32)")
    print()

    # ============================================================================
    # STEP 3: SPLIT DATA
    # ============================================================================

    print("=" * 80)
    print("STEP 3: CHRONOLOGICAL SPLIT")
    print("=" * 80)

    df_sorted = df.sort_values('game_date').reset_index(drop=True)
    X = X.iloc[df_sorted.index].reset_index(drop=True)
    y = y.iloc[df_sorted.index].reset_index(drop=True)

    n = len(df)
    train_end, val_end = int(n * 0.70), int(n * 0.85)

    X_train, X_val, X_test = X.iloc[:train_end], X.iloc[train_end:val_end], X.iloc[val_end:]
    y_train, y_val, y_test = y.iloc[:train_end], y.iloc[train_end:val_end], y.iloc[val_end:]

    print(f"Train: {len(X_train):,}  Val: {len(X_val):,}  Test: {len(X_test):,}")
    print(f"Test set date range: {df_sorted.iloc[val_end:]['game_date'].min()} to {df_sorted.iloc[val_end:]['game_date'].max()}")
    print()

    # ============================================================================
    # STEP 4: TRAIN MODELS
    # ============================================================================

    print("=" * 80)
    print("STEP 4: TRAINING MODELS")
    print("=" * 80)

    results = {}

    # XGBoost
    print("\n[1/3] Training XGBoost...")
    xgb_model = xgb.XGBRegressor(
        max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
        subsample=0.7, colsample_bytree=0.7, gamma=0.1, reg_alpha=0.5, reg_lambda=5.0,
        random_state=42, objective='reg:squarederror', eval_metric='mae', early_stopping_rounds=50
    )
    xgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    xgb_pred = xgb_model.predict(X_test)
    results['XGBoost'] = {'pred': xgb_pred, 'mae': mean_absolute_error(y_test, xgb_pred)}
    print(f"    XGBoost MAE: {results['XGBoost']['mae']:.4f}")

    # LightGBM
    print("\n[2/3] Training LightGBM...")
    lgb_model = lgb.LGBMRegressor(
        max_depth=6, min_child_weight=10, learning_rate=0.03, n_estimators=1000,
        subsample=0.7, colsample_bytree=0.7, reg_alpha=0.5, reg_lambda=5.0,
        random_state=42, verbose=-1
    )
    lgb_model.fit(X_train, y_train, eval_set=[(X_val, y_val)], callbacks=[lgb.early_stopping(50, verbose=False)])
    lgb_pred = lgb_model.predict(X_test)
    results['LightGBM'] = {'pred': lgb_pred, 'mae': mean_absolute_error(y_test, lgb_pred)}
    print(f"    LightGBM MAE: {results['LightGBM']['mae']:.4f}")

    # CatBoost (with Optuna params)
    print("\n[3/3] Training CatBoost...")
    cb_model = cb.CatBoostRegressor(
        depth=6, learning_rate=0.07, l2_leaf_reg=3.8, subsample=0.72, min_data_in_leaf=16,
        iterations=1000, random_seed=42, verbose=False, early_stopping_rounds=50
    )
    cb_model.fit(X_train, y_train, eval_set=(X_val, y_val))
    cb_pred = cb_model.predict(X_test)
    results['CatBoost'] = {'pred': cb_pred, 'mae': mean_absolute_error(y_test, cb_pred)}
    print(f"    CatBoost MAE: {results['CatBoost']['mae']:.4f}")

    # ============================================================================
    # STEP 5: ENSEMBLES
    # ============================================================================

    print("\n" + "=" * 80)
    print("STEP 5: ENSEMBLE METHODS")
    print("=" * 80)

    # Simple average
    avg_pred = (xgb_pred + lgb_pred + cb_pred) / 3
    results['Simple Avg'] = {'pred': avg_pred, 'mae': mean_absolute_error(y_test, avg_pred)}
    print(f"\nSimple Average: {results['Simple Avg']['mae']:.4f}")

    # Stacked with Ridge
    xgb_val = xgb_model.predict(X_val)
    lgb_val = lgb_model.predict(X_val)
    cb_val = cb_model.predict(X_val)

    stack_val = np.column_stack([xgb_val, lgb_val, cb_val])
    stack_test = np.column_stack([xgb_pred, lgb_pred, cb_pred])

    meta = Ridge(alpha=1.0)
    meta.fit(stack_val, y_val)
    stacked_pred = meta.predict(stack_test)
    results['Stacked'] = {'pred': stacked_pred, 'mae': mean_absolute_error(y_test, stacked_pred),
                          'coefs': meta.coef_.tolist()}
    print(f"Stacked (Ridge): {results['Stacked']['mae']:.4f} (coefs: {meta.coef_})")

    # ============================================================================
    # STEP 6: CHAMPION COMPARISON
    # ============================================================================

    print("\n" + "=" * 80)
    print("STEP 6: CHAMPION COMPARISON")
    print("=" * 80)

    best_name = min(results, key=lambda k: results[k]['mae'])
    best_mae = results[best_name]['mae']

    improvement = ((CHAMPION_MAE - best_mae) / CHAMPION_MAE) * 100
    mae_diff = CHAMPION_MAE - best_mae

    print(f"\n{'Model':<20} {'MAE':>8} {'vs Champion':>12}")
    print("-" * 45)
    print(f"{'Champion (v8)':<20} {CHAMPION_MAE:>8.4f} {'--':>12}")
    print("-" * 45)

    for name, data in sorted(results.items(), key=lambda x: x[1]['mae']):
        mae = data['mae']
        vs_champ = ((CHAMPION_MAE - mae) / CHAMPION_MAE) * 100
        marker = " ***" if name == best_name else ""
        print(f"{name:<20} {mae:>8.4f} {vs_champ:>+11.2f}%{marker}")

    print("\n" + "=" * 60)
    print(f"CHALLENGER BEST: {best_name} = {best_mae:.4f}")
    print(f"vs Champion ({CHAMPION_VERSION}): {improvement:+.2f}% ({mae_diff:+.3f} MAE)")

    if improvement >= 0.2 * 100 / CHAMPION_MAE:  # 0.2 point improvement
        print("STATUS: MEETS MAE IMPROVEMENT THRESHOLD (0.2 points)")
    else:
        print(f"STATUS: Does not meet 0.2pt threshold (need {CHAMPION_MAE - 0.2:.3f} MAE)")

    # ============================================================================
    # STEP 7: FEATURE IMPORTANCE
    # ============================================================================

    print("\n" + "=" * 80)
    print("STEP 7: TOP 15 FEATURE IMPORTANCE (CatBoost)")
    print("=" * 80)

    importance = cb_model.get_feature_importance()
    feat_imp = pd.DataFrame({'feature': all_features, 'importance': importance})
    feat_imp = feat_imp.sort_values('importance', ascending=False)

    print(f"\n{'Rank':<5} {'Feature':<30} {'Importance':>10}")
    print("-" * 50)
    for rank, (_, row) in enumerate(feat_imp.head(15).iterrows(), 1):
        print(f"{rank:<5} {row['feature']:<30} {row['importance']:>9.1f}%")

    # ============================================================================
    # STEP 8: SAVE
    # ============================================================================

    print("\n" + "=" * 80)
    print("STEP 8: SAVING MODELS")
    print("=" * 80)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    xgb_path = MODEL_OUTPUT_DIR / f"xgboost_v10_33features_{timestamp}.json"
    lgb_path = MODEL_OUTPUT_DIR / f"lightgbm_v10_33features_{timestamp}.txt"
    cb_path = MODEL_OUTPUT_DIR / f"catboost_v10_33features_{timestamp}.cbm"

    xgb_model.get_booster().save_model(str(xgb_path))
    lgb_model.booster_.save_model(str(lgb_path))
    cb_model.save_model(str(cb_path))

    metadata = {
        'version': 'v10',
        'model_type': 'challenger',
        'champion_version': CHAMPION_VERSION,
        'timestamp': timestamp,
        'training_date_range': {
            'start': '2021-11-01',
            'end': end_date
        },
        'features': all_features,
        'feature_count': len(all_features),
        'training_samples': len(df),
        'samples_by_season': season_counts.to_dict(),
        'new_samples_vs_champion': new_samples,
        'results': {name: {'mae': float(data['mae'])} for name, data in results.items()},
        'stacked_coefs': results['Stacked']['coefs'],
        'best_model': best_name,
        'best_mae': float(best_mae),
        'champion_comparison': {
            'champion_mae': CHAMPION_MAE,
            'improvement_pct': float(improvement),
            'mae_difference': float(mae_diff)
        },
        'model_files': {
            'xgboost': str(xgb_path.name),
            'lightgbm': str(lgb_path.name),
            'catboost': str(cb_path.name)
        }
    }

    metadata_path = MODEL_OUTPUT_DIR / f"challenger_v10_{timestamp}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Saved models:")
    print(f"  XGBoost:  {xgb_path.name}")
    print(f"  LightGBM: {lgb_path.name}")
    print(f"  CatBoost: {cb_path.name}")
    print(f"  Metadata: {metadata_path.name}")

    # ============================================================================
    # SUMMARY
    # ============================================================================

    print("\n" + "=" * 80)
    print("TRAINING SUMMARY")
    print("=" * 80)
    print(f"""
Training Data:
  Date Range: 2021-11-01 to {end_date}
  Total Samples: {len(df):,}
  New vs Champion: +{new_samples:,} samples ({new_samples/champion_samples*100:.1f}% more)

Results:
  XGBoost:  {results['XGBoost']['mae']:.4f}
  LightGBM: {results['LightGBM']['mae']:.4f}
  CatBoost: {results['CatBoost']['mae']:.4f}
  Stacked:  {results['Stacked']['mae']:.4f}

CHALLENGER BEST: {best_name} = {best_mae:.4f}

vs Champion ({CHAMPION_VERSION} = {CHAMPION_MAE}):
  Improvement: {improvement:+.2f}%
  MAE Difference: {mae_diff:+.3f}

Next Steps:
  1. Register in ml_model_registry with is_production=FALSE
  2. Run shadow mode: python predictions/shadow_mode_runner.py
  3. Compare after 7+ days with 100+ picks
  4. Promote if meets criteria (3%+ win rate, 0.2pt MAE)
""")
    print("=" * 80)

if __name__ == '__main__':
    main()
