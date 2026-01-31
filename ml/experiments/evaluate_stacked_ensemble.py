#!/usr/bin/env python3
"""
Evaluate Stacked Ensemble on Evaluation Period

Loads a trained stacked ensemble (XGBoost + LightGBM + CatBoost + Ridge)
and evaluates on a specified date range with full metrics.

Usage:
    PYTHONPATH=. python ml/experiments/evaluate_stacked_ensemble.py \
        --metadata-path "ml/experiments/results/ensemble_exp_ENS_REC60_*.json" \
        --eval-start 2026-01-01 \
        --eval-end 2026-01-30

Output:
    - Overall MAE, hit rate by edge threshold
    - Breakdown by player tier
    - Comparison with production V8
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import argparse
import numpy as np
import pandas as pd
import json
import glob
from datetime import datetime
from google.cloud import bigquery
from sklearn.metrics import mean_absolute_error
from sklearn.linear_model import Ridge
import xgboost as xgb
import lightgbm as lgb
import catboost as cb

PROJECT_ID = "nba-props-platform"


def get_eval_query(eval_start: str, eval_end: str) -> str:
    """Generate evaluation data query with Vegas lines and actuals."""
    return f"""
WITH feature_data AS (
  SELECT mf.player_lookup, mf.game_date, mf.features, mf.feature_count
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2` mf
  WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
    AND mf.feature_count >= 33
    AND ARRAY_LENGTH(mf.features) >= 33
),
vegas_lines AS (
  SELECT game_date, player_lookup, points_line as betting_line
  FROM `nba-props-platform.nba_raw.bettingpros_player_points_props`
  WHERE bookmaker = 'BettingPros Consensus' AND bet_side = 'over'
    AND game_date BETWEEN '{eval_start}' AND '{eval_end}'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup ORDER BY processed_at DESC) = 1
),
actuals AS (
  SELECT player_lookup, game_date, points as actual_points
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date BETWEEN '{eval_start}' AND '{eval_end}'
    AND points IS NOT NULL
),
player_tiers AS (
  SELECT player_lookup,
    CASE
      WHEN AVG(points) >= 25 THEN 'Star'
      WHEN AVG(points) >= 18 THEN 'Starter'
      WHEN AVG(points) >= 12 THEN 'Rotation'
      ELSE 'Bench'
    END as tier
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB('{eval_start}', INTERVAL 60 DAY)
    AND game_date < '{eval_start}'
  GROUP BY player_lookup
)
SELECT fd.player_lookup, fd.game_date, fd.features,
       v.betting_line, a.actual_points, pt.tier
FROM feature_data fd
INNER JOIN actuals a ON fd.player_lookup = a.player_lookup AND fd.game_date = a.game_date
LEFT JOIN vegas_lines v ON fd.player_lookup = v.player_lookup AND fd.game_date = v.game_date
LEFT JOIN player_tiers pt ON fd.player_lookup = pt.player_lookup
WHERE v.betting_line IS NOT NULL
ORDER BY fd.game_date
"""


def prepare_features(df: pd.DataFrame, feature_names: list) -> pd.DataFrame:
    """Prepare feature matrix matching training features."""
    X = pd.DataFrame(
        [row[:len(feature_names)] for row in df['features'].tolist()],
        columns=feature_names
    )
    X = X.fillna(X.median())
    return X


def calculate_metrics(df: pd.DataFrame, pred_col: str, min_edge: float = 1.0) -> dict:
    """Calculate evaluation metrics."""
    df = df.copy()

    # Edge calculation
    df['edge'] = df[pred_col] - df['betting_line']
    df['abs_edge'] = np.abs(df['edge'])

    # Prediction correct (over/under)
    df['pred_over'] = df[pred_col] > df['betting_line']
    df['actual_over'] = df['actual_points'] > df['betting_line']
    df['correct'] = df['pred_over'] == df['actual_over']

    # Filter by edge
    filtered = df[df['abs_edge'] >= min_edge]

    if len(filtered) == 0:
        return {'hit_rate': None, 'bets': 0, 'mae': None}

    return {
        'hit_rate': 100.0 * filtered['correct'].mean(),
        'bets': len(filtered),
        'mae': mean_absolute_error(filtered['actual_points'], filtered[pred_col]),
        'avg_edge': float(filtered['abs_edge'].mean()),
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate stacked ensemble")
    parser.add_argument("--metadata-path", required=True, help="Path to metadata JSON (glob supported)")
    parser.add_argument("--eval-start", required=True, help="Evaluation start date")
    parser.add_argument("--eval-end", required=True, help="Evaluation end date")
    args = parser.parse_args()

    # Find metadata file
    metadata_files = sorted(glob.glob(args.metadata_path))
    if not metadata_files:
        print(f"Error: No files matching {args.metadata_path}")
        return

    metadata_path = Path(metadata_files[-1])  # Use most recent
    print(f"Loading metadata from: {metadata_path}")

    with open(metadata_path) as f:
        metadata = json.load(f)

    print("=" * 80)
    print(f" STACKED ENSEMBLE EVALUATION: {metadata['experiment_id']}")
    print("=" * 80)
    print(f"Eval period: {args.eval_start} to {args.eval_end}")
    print(f"Recency: {'ENABLED (half-life: ' + str(metadata['recency_weighting']['half_life_days']) + ' days)' if metadata['recency_weighting']['enabled'] else 'DISABLED'}")
    print()

    # Load models
    print("Loading models...")
    results_dir = metadata_path.parent

    xgb_model = xgb.Booster()
    xgb_model.load_model(metadata['model_files']['xgboost'])

    lgb_model = lgb.Booster(model_file=metadata['model_files']['lightgbm'])

    cb_model = cb.CatBoostRegressor()
    cb_model.load_model(metadata['model_files']['catboost'])

    # Reconstruct Ridge meta-learner
    meta = Ridge(alpha=1.0)
    meta.coef_ = np.array(metadata['results']['Stacked']['coefs'])
    meta.intercept_ = metadata['results']['Stacked']['intercept']

    print(f"  Loaded XGBoost, LightGBM, CatBoost")
    print(f"  Ridge coefs: {meta.coef_}")

    # Load evaluation data
    print("\nLoading evaluation data...")
    client = bigquery.Client(project=PROJECT_ID)
    query = get_eval_query(args.eval_start, args.eval_end)
    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df):,} samples with betting lines")

    # Prepare features
    X = prepare_features(df, metadata['features'])

    # Generate predictions
    print("\nGenerating predictions...")

    # XGBoost prediction
    dmatrix = xgb.DMatrix(X)
    xgb_pred = xgb_model.predict(dmatrix)
    df['xgb_pred'] = xgb_pred

    # LightGBM prediction
    lgb_pred = lgb_model.predict(X)
    df['lgb_pred'] = lgb_pred

    # CatBoost prediction
    cb_pred = cb_model.predict(X)
    df['cb_pred'] = cb_pred

    # Stacked ensemble prediction
    stack = np.column_stack([xgb_pred, lgb_pred, cb_pred])
    stacked_pred = meta.predict(stack)
    df['stacked_pred'] = stacked_pred

    # Simple average
    df['avg_pred'] = (xgb_pred + lgb_pred + cb_pred) / 3

    # Calculate metrics
    print("\n" + "=" * 80)
    print("OVERALL RESULTS")
    print("=" * 80)

    models = ['xgb_pred', 'lgb_pred', 'cb_pred', 'avg_pred', 'stacked_pred']
    model_names = ['XGBoost', 'LightGBM', 'CatBoost', 'Simple Avg', 'Stacked']

    print(f"\n{'Model':<12} | {'MAE':>6} | {'1+ Edge':>12} | {'2+ Edge':>12} | {'3+ Edge':>12} | {'5+ Edge':>12}")
    print("-" * 80)

    for model_col, name in zip(models, model_names):
        mae = mean_absolute_error(df['actual_points'], df[model_col])
        m1 = calculate_metrics(df, model_col, 1.0)
        m2 = calculate_metrics(df, model_col, 2.0)
        m3 = calculate_metrics(df, model_col, 3.0)
        m5 = calculate_metrics(df, model_col, 5.0)

        hit1 = f"{m1['hit_rate']:.1f}% ({m1['bets']})" if m1['hit_rate'] else "N/A"
        hit2 = f"{m2['hit_rate']:.1f}% ({m2['bets']})" if m2['hit_rate'] else "N/A"
        hit3 = f"{m3['hit_rate']:.1f}% ({m3['bets']})" if m3['hit_rate'] else "N/A"
        hit5 = f"{m5['hit_rate']:.1f}% ({m5['bets']})" if m5['hit_rate'] else "N/A"

        marker = " ***" if name == 'Stacked' else ""
        print(f"{name:<12} | {mae:>6.2f} | {hit1:>12} | {hit2:>12} | {hit3:>12} | {hit5:>12}{marker}")

    # Tier breakdown
    print("\n" + "=" * 80)
    print("RESULTS BY TIER (2+ Edge)")
    print("=" * 80)

    tiers = ['Star', 'Starter', 'Rotation', 'Bench']

    print(f"\n{'Tier':<10} | {'XGBoost':>15} | {'CatBoost':>15} | {'Stacked':>15}")
    print("-" * 60)

    for tier in tiers:
        tier_df = df[df['tier'] == tier]
        if len(tier_df) == 0:
            continue

        xgb_m = calculate_metrics(tier_df, 'xgb_pred', 2.0)
        cb_m = calculate_metrics(tier_df, 'cb_pred', 2.0)
        stack_m = calculate_metrics(tier_df, 'stacked_pred', 2.0)

        xgb_str = f"{xgb_m['hit_rate']:.1f}% ({xgb_m['bets']})" if xgb_m['hit_rate'] else "N/A"
        cb_str = f"{cb_m['hit_rate']:.1f}% ({cb_m['bets']})" if cb_m['hit_rate'] else "N/A"
        stack_str = f"{stack_m['hit_rate']:.1f}% ({stack_m['bets']})" if stack_m['hit_rate'] else "N/A"

        print(f"{tier:<10} | {xgb_str:>15} | {cb_str:>15} | {stack_str:>15}")

    # Summary
    stacked_metrics = calculate_metrics(df, 'stacked_pred', 3.0)
    cb_metrics = calculate_metrics(df, 'cb_pred', 3.0)

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"""
Experiment: {metadata['experiment_id']}
Recency: {'ENABLED (' + str(metadata['recency_weighting']['half_life_days']) + ' days)' if metadata['recency_weighting']['enabled'] else 'DISABLED'}

Stacked Ensemble at 3+ edge:
  Hit Rate: {stacked_metrics['hit_rate']:.1f}% ({stacked_metrics['bets']} bets)
  MAE: {stacked_metrics['mae']:.2f}

CatBoost at 3+ edge:
  Hit Rate: {cb_metrics['hit_rate']:.1f}% ({cb_metrics['bets']} bets)
  MAE: {cb_metrics['mae']:.2f}

Ensemble vs CatBoost: {stacked_metrics['hit_rate'] - cb_metrics['hit_rate']:+.1f}% hit rate difference
""")

    # Save results
    results = {
        "experiment_id": metadata['experiment_id'],
        "eval_period": {"start": args.eval_start, "end": args.eval_end},
        "samples": len(df),
        "recency_weighting": metadata['recency_weighting'],
        "overall_metrics": {
            name: {
                "mae": float(mean_absolute_error(df['actual_points'], df[col])),
                "hit_rate_1plus": calculate_metrics(df, col, 1.0),
                "hit_rate_2plus": calculate_metrics(df, col, 2.0),
                "hit_rate_3plus": calculate_metrics(df, col, 3.0),
                "hit_rate_5plus": calculate_metrics(df, col, 5.0),
            }
            for col, name in zip(models, model_names)
        },
        "tier_metrics": {
            tier: {
                name: calculate_metrics(df[df['tier'] == tier], col, 2.0)
                for col, name in zip(models, model_names)
            }
            for tier in tiers if len(df[df['tier'] == tier]) > 0
        },
        "evaluated_at": datetime.now().isoformat(),
    }

    results_path = results_dir / f"{metadata['experiment_id']}_eval_{args.eval_start}_{args.eval_end}.json"
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Saved results to {results_path}")


if __name__ == "__main__":
    main()
