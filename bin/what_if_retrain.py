#!/usr/bin/env python3
"""What-If Retrain Tool — Counterfactual simulation for model retraining.

Answers questions like: "What if we had retrained on Jan 31 and used that
model for Feb 8-14 instead of the stale one?"

Two modes:
1. Train from scratch: --train-end trains a new model in-memory
2. Load saved model:   --model-path loads an actual .cbm from GCS or local

Both modes generate predictions against the feature store, grade against
actuals, and report hit rates at multiple edge thresholds with OVER/UNDER
direction breakdown. NO writes to BigQuery or GCS.

Usage:
    # Train a new model to Jan 31, evaluate Feb 8-14
    PYTHONPATH=. python bin/what_if_retrain.py \
        --train-end 2026-01-31 --eval-start 2026-02-08 --eval-end 2026-02-14

    # Load the ACTUAL stale production model and see what it picks
    PYTHONPATH=. python bin/what_if_retrain.py \
        --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
        --eval-start 2026-02-08 --eval-end 2026-02-14

    # Compare two saved models
    PYTHONPATH=. python bin/what_if_retrain.py \
        --model-path gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260131_20260209_212708.cbm \
        --eval-start 2026-02-01 --eval-end 2026-02-14 \
        --compare-with gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm

Session 314C — Counterfactual retrain simulation
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import tempfile
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from google.cloud import bigquery, storage
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import catboost as cb

from shared.ml.feature_contract import (
    V9_CONTRACT,
    FEATURE_STORE_FEATURE_COUNT,
    FEATURE_STORE_NAMES,
)
from shared.ml.training_data_loader import get_quality_where_clause

PROJECT_ID = "nba-props-platform"

DEFAULT_HP = {
    'iterations': 1000,
    'learning_rate': 0.05,
    'depth': 6,
    'l2_leaf_reg': 3,
    'random_seed': 42,
    'verbose': 0,
    'early_stopping_rounds': 50,
}

STORE_NAME_TO_IDX = {name: i for i, name in enumerate(FEATURE_STORE_NAMES)}


def parse_args():
    parser = argparse.ArgumentParser(
        description='What-if retrain simulation — counterfactual model evaluation'
    )
    # Model source: train from scratch OR load saved model
    parser.add_argument('--train-end', default=None,
                        help='Train data cutoff (YYYY-MM-DD). Trains a new model.')
    parser.add_argument('--model-path', default=None,
                        help='Path to saved .cbm model (GCS gs:// or local). Skips training.')
    parser.add_argument('--train-days', type=int, default=42,
                        help='Rolling training window size in days (default: 42)')

    # Eval period
    parser.add_argument('--eval-start', required=True,
                        help='Start of simulation period (YYYY-MM-DD)')
    parser.add_argument('--eval-end', required=True,
                        help='End of simulation period (YYYY-MM-DD)')

    # Comparison
    parser.add_argument('--compare-with', default=None,
                        help='Second --train-end date OR --model-path for A/B comparison')

    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show per-player pick details for edge 1+ picks')

    args = parser.parse_args()
    if not args.train_end and not args.model_path:
        parser.error('Provide either --train-end (train new model) or --model-path (load saved model)')
    return args


def load_model_from_path(model_path):
    """Load a CatBoost model from GCS or local path."""
    model = cb.CatBoostRegressor()
    if model_path.startswith("gs://"):
        parts = model_path.replace("gs://", "").split("/", 1)
        bucket_name, blob_path = parts[0], parts[1]
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        with tempfile.NamedTemporaryFile(suffix='.cbm', delete=False) as f:
            blob.download_to_filename(f.name)
            model.load_model(f.name)
        return model, Path(blob_path).name
    else:
        model.load_model(model_path)
        return model, Path(model_path).name


def load_training_data(client, train_start, train_end):
    """Load clean training data from feature store + actuals."""
    quality_clause = get_quality_where_clause("mf")
    feature_cols = ',\n      '.join(
        f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
    )
    query = f"""
    SELECT mf.player_lookup, mf.game_date, {feature_cols},
      pgs.points as actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{train_start}' AND '{train_end}'
      AND {quality_clause}
      AND pgs.points IS NOT NULL AND pgs.minutes_played > 0
      AND NOT (mf.feature_0_value = 10.0 AND mf.feature_1_value > 15)
    """
    return client.query(query).to_dataframe()


def load_eval_data(client, eval_start, eval_end):
    """Load eval data: features + prop lines + actuals."""
    quality_clause = get_quality_where_clause("mf")
    feature_cols = ',\n      '.join(
        f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT)
    )
    query = f"""
    WITH best_lines AS (
      SELECT player_lookup, game_date, current_points_line, game_id
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
      WHERE game_date BETWEEN '{eval_start}' AND '{eval_end}'
        AND system_id = 'catboost_v9'
        AND is_active = TRUE
        AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup, game_date ORDER BY current_points_line DESC
      ) = 1
    )
    SELECT mf.player_lookup, mf.game_date, mf.feature_quality_score,
      {feature_cols},
      bl.current_points_line as prop_line, bl.game_id,
      mf.feature_54_value as prop_line_delta,
      pgs.points as actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN best_lines bl
      ON mf.player_lookup = bl.player_lookup AND mf.game_date = bl.game_date
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{eval_start}' AND '{eval_end}'
      AND {quality_clause} AND pgs.points IS NOT NULL
    """
    return client.query(query).to_dataframe()


def prepare_features(df, contract=V9_CONTRACT):
    """Extract feature matrix from DataFrame using feature_N_value columns."""
    rows = []
    for _, row in df.iterrows():
        row_data = {}
        for name in contract.feature_names:
            idx = STORE_NAME_TO_IDX.get(name)
            if idx is not None:
                val = row.get(f'feature_{idx}_value')
                if val is not None and not pd.isna(val):
                    row_data[name] = float(val)
                else:
                    row_data[name] = np.nan
            else:
                row_data[name] = np.nan
        rows.append(row_data)
    return pd.DataFrame(rows, columns=contract.feature_names)


def train_model(X_train, y_train):
    """Train CatBoost model with production-equivalent hyperparams."""
    X_t, X_v, y_t, y_v = train_test_split(
        X_train, y_train, test_size=0.15, random_state=42
    )
    model = cb.CatBoostRegressor(**DEFAULT_HP)
    model.fit(X_t, y_t, eval_set=(X_v, y_v), verbose=0)
    return model


def grade_predictions(df):
    """Grade each prediction. Returns DataFrame with 'correct' column."""
    df = df.copy()

    def _grade(row):
        actual = row['actual_points']
        line = row['prop_line']
        rec = row['recommendation']
        if actual > line:
            return rec == 'OVER'
        elif actual < line:
            return rec == 'UNDER'
        return None

    df['correct'] = df.apply(_grade, axis=1)
    return df


def compute_hit_rate(df, min_edge=0, direction=None):
    """Compute hit rate for predictions at a given edge threshold and direction."""
    subset = df if min_edge == 0 else df[df['abs_edge'] >= min_edge]
    if direction:
        subset = subset[subset['recommendation'] == direction]
    graded = subset[subset['correct'].notna()]
    if graded.empty:
        return 0, 0, 0, 0
    wins = int(graded['correct'].sum())
    losses = len(graded) - wins
    hr = round(wins / len(graded) * 100, 1)
    pnl = int(wins * 100 - losses * 110)
    return wins, losses, hr, pnl


def apply_under_filters(df):
    """Apply UNDER-specific negative filters from production aggregator."""
    mask = pd.Series(True, index=df.index)
    mask &= ~((df['recommendation'] == 'UNDER') & (df['abs_edge'] >= 7.0))
    mask &= ~((df['recommendation'] == 'UNDER') & (df['prop_line'] < 12))
    mask &= ~((df['recommendation'] == 'UNDER') &
              (df['prop_line_delta'].notna()) & (df['prop_line_delta'] >= 2.0))
    mask &= ~((df['recommendation'] == 'UNDER') &
              (df['prop_line_delta'].notna()) & (df['prop_line_delta'] <= -2.0))
    return df[mask]


def print_threshold_table(df_filtered, label=""):
    """Print hit rate table at multiple thresholds with direction breakdown."""
    header = f"  {'Edge':>8s}  {'W':>4s}  {'L':>4s}  {'HR':>7s}  {'P&L':>8s}  {'N':>5s}"
    if label:
        print(f"\n  {label}")
    print(header)
    print(f"  {'-'*8}  {'-'*4}  {'-'*4}  {'-'*7}  {'-'*8}  {'-'*5}")

    threshold_results = {}
    for threshold in [0, 1, 2, 3, 5]:
        w, l, hr, pnl = compute_hit_rate(df_filtered, min_edge=threshold)
        n = w + l
        threshold_results[threshold] = {'w': w, 'l': l, 'hr': hr, 'pnl': pnl, 'n': n}
        t_label = f">= {threshold}" if threshold > 0 else "All"
        hr_str = f"{hr:.1f}%" if n > 0 else "N/A"
        warn = "  *" if 0 < n < 20 else ""
        print(f"  {t_label:>8s}  {w:>4d}  {l:>4d}  {hr_str:>7s}  ${pnl:>+7,d}  {n:>5d}{warn}")

    return threshold_results


def print_direction_table(df_filtered):
    """Print OVER vs UNDER breakdown at key thresholds."""
    print(f"\n  Direction breakdown:")
    print(f"  {'':>8s}  {'--- OVER ---':>18s}  {'--- UNDER ---':>18s}")
    print(f"  {'Edge':>8s}  {'W-L':>8s}  {'HR':>7s}  {'W-L':>8s}  {'HR':>7s}")
    print(f"  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*8}  {'-'*7}")

    dir_results = {}
    for threshold in [0, 1, 2, 3, 5]:
        ow, ol, ohr, opnl = compute_hit_rate(df_filtered, min_edge=threshold, direction='OVER')
        uw, ul, uhr, upnl = compute_hit_rate(df_filtered, min_edge=threshold, direction='UNDER')
        on, un = ow + ol, uw + ul
        dir_results[threshold] = {
            'over': {'w': ow, 'l': ol, 'hr': ohr, 'pnl': opnl, 'n': on},
            'under': {'w': uw, 'l': ul, 'hr': uhr, 'pnl': upnl, 'n': un},
        }
        t_label = f">= {threshold}" if threshold > 0 else "All"
        ohr_str = f"{ohr:.1f}%" if on > 0 else "N/A"
        uhr_str = f"{uhr:.1f}%" if un > 0 else "N/A"
        owlstr = f"{ow}W-{ol}L"
        uwlstr = f"{uw}W-{ul}L"
        print(f"  {t_label:>8s}  {owlstr:>8s}  {ohr_str:>7s}  {uwlstr:>8s}  {uhr_str:>7s}")

    return dir_results


def run_simulation(bq_client, eval_start_str, eval_end_str,
                   train_end_str=None, model_path=None,
                   train_days=42, verbose=False):
    """Run a single what-if simulation. Returns results dict."""
    eval_start = datetime.strptime(eval_start_str, '%Y-%m-%d').date()
    eval_end = datetime.strptime(eval_end_str, '%Y-%m-%d').date()

    # Determine model source
    if model_path:
        mode_label = Path(model_path).stem if not model_path.startswith("gs://") else model_path.split("/")[-1].replace(".cbm", "")
        print(f"\n{'='*70}")
        print(f"  WHAT-IF: Load saved model")
        print(f"  Model:      {mode_label}")
        print(f"  Simulation: {eval_start} to {eval_end}")
        print(f"{'='*70}")

        print(f"\n  Loading model from {'GCS' if model_path.startswith('gs://') else 'local'}...")
        model, model_name = load_model_from_path(model_path)
        print(f"  Model loaded: {model_name} ({model.tree_count_} trees)")
    else:
        train_end = datetime.strptime(train_end_str, '%Y-%m-%d').date()
        train_start = train_end - timedelta(days=train_days - 1)
        mode_label = f"train>{train_end_str}"

        if train_end >= eval_start:
            print(f"  ERROR: Training ends {train_end} >= eval starts {eval_start}")
            print(f"  This would leak future data. Aborting.")
            return None

        print(f"\n{'='*70}")
        print(f"  WHAT-IF: Train to {train_end_str} ({train_days}d window)")
        print(f"  Training:   {train_start} to {train_end}")
        print(f"  Simulation: {eval_start} to {eval_end}")
        print(f"{'='*70}")

        print(f"\n  Loading training data...")
        df_train = load_training_data(bq_client, train_start.strftime('%Y-%m-%d'), train_end_str)
        print(f"  Training samples: {len(df_train):,}")
        if len(df_train) < 100:
            print(f"  ERROR: Only {len(df_train)} training samples. Need >= 100.")
            return None

        print(f"  Preparing features...")
        X_train = prepare_features(df_train)
        y_train = df_train['actual_points'].astype(float)

        print(f"  Training CatBoost ({X_train.shape[1]} features, "
              f"{X_train.shape[0]:,} samples)...")
        model = train_model(X_train, y_train)
        model_name = f"what_if_train_{train_end_str}"
        print(f"  Model trained ({model.tree_count_} trees)")

    # Load eval data
    print(f"  Loading eval data...")
    df_eval = load_eval_data(bq_client, eval_start_str, eval_end_str)
    print(f"  Eval players with prop lines: {len(df_eval):,}")
    if df_eval.empty:
        print(f"  ERROR: No eval data found.")
        return None

    print(f"  Preparing eval features...")
    X_eval = prepare_features(df_eval)

    # Generate predictions
    preds = model.predict(X_eval)
    df_eval = df_eval.copy()
    df_eval['predicted_points'] = preds
    df_eval['edge'] = df_eval['predicted_points'] - df_eval['prop_line']
    df_eval['abs_edge'] = df_eval['edge'].abs()
    df_eval['recommendation'] = df_eval['edge'].apply(
        lambda e: 'OVER' if e > 0 else 'UNDER'
    )

    # Grade
    df_eval = grade_predictions(df_eval)

    # UNDER filters
    n_before = len(df_eval)
    df_filtered = apply_under_filters(df_eval)
    n_removed = n_before - len(df_filtered)

    # Stats
    mae = mean_absolute_error(df_eval['actual_points'], df_eval['predicted_points'])
    vegas_bias = float(np.mean(df_eval['predicted_points'].values - df_eval['prop_line'].values))

    print(f"\n  Model stats: MAE={mae:.2f}, Vegas bias={vegas_bias:+.2f}")
    print(f"  UNDER filters removed: {n_removed} predictions")

    # Edge distribution
    print(f"\n  Edge distribution:")
    for t in [0, 1, 2, 3, 5, 7, 10]:
        n = (df_filtered['abs_edge'] >= t).sum()
        if n > 0 or t <= 5:
            print(f"    Edge >= {t}: {n} predictions")

    # Hit rate table
    threshold_results = print_threshold_table(df_filtered)

    # Direction breakdown
    dir_results = print_direction_table(df_filtered)

    # Daily breakdown (edge 1+)
    print(f"\n  Daily breakdown (edge >= 1):")
    daily_results = []
    df_e1 = df_filtered[df_filtered['abs_edge'] >= 1]

    if not df_e1.empty:
        for game_date in sorted(df_e1['game_date'].unique()):
            day_df = df_e1[df_e1['game_date'] == game_date]
            date_str = str(game_date)[:10]
            graded = day_df[day_df['correct'].notna()]
            wins = int(graded['correct'].sum()) if not graded.empty else 0
            losses = len(graded) - wins
            n_over = (day_df['recommendation'] == 'OVER').sum()
            n_under = (day_df['recommendation'] == 'UNDER').sum()
            hr = wins / len(graded) * 100 if len(graded) > 0 else 0
            hr_str = f"{hr:.0f}%" if len(graded) > 0 else "N/A"

            daily_results.append({
                'date': date_str, 'picks': len(day_df),
                'wins': wins, 'losses': losses, 'hr': hr,
            })

            print(f"    {date_str}  |  {len(day_df):2d} picks ({n_over}O/{n_under}U)  |  "
                  f"{wins}W-{losses}L  ({hr_str})")

            if verbose:
                for _, p in day_df.sort_values('abs_edge', ascending=False).iterrows():
                    mark = '?' if p['correct'] is None else ('W' if p['correct'] else 'L')
                    print(f"      {mark} {p['player_lookup']:25s} {p['recommendation']:5s} "
                          f"edge={p['abs_edge']:4.1f} pred={p['predicted_points']:5.1f} "
                          f"line={p['prop_line']:5.1f} actual={int(p['actual_points'])}")

    # Summary
    e3 = threshold_results.get(3, {})
    e3o = dir_results.get(3, {}).get('over', {})
    e3u = dir_results.get(3, {}).get('under', {})
    print(f"\n{'='*70}")
    print(f"  SUMMARY: {mode_label}")
    print(f"{'='*70}")
    print(f"  Period:         {eval_start_str} to {eval_end_str}")
    print(f"  MAE:            {mae:.2f}")
    print(f"  Vegas bias:     {vegas_bias:+.2f}")
    n3 = e3.get('n', 0)
    warn3 = " (low N!)" if 0 < n3 < 20 else ""
    print(f"  Edge 3+ HR:     {e3.get('hr', 0):.1f}% ({e3.get('w', 0)}W-{e3.get('l', 0)}L, "
          f"N={n3}){warn3}")
    print(f"    OVER:         {e3o.get('hr', 0):.1f}% ({e3o.get('w', 0)}W-{e3o.get('l', 0)}L, "
          f"N={e3o.get('n', 0)})")
    print(f"    UNDER:        {e3u.get('hr', 0):.1f}% ({e3u.get('w', 0)}W-{e3u.get('l', 0)}L, "
          f"N={e3u.get('n', 0)})")
    print(f"  Edge 3+ P&L:    ${e3.get('pnl', 0):+,d}")

    return {
        'label': mode_label,
        'eval_start': eval_start_str,
        'eval_end': eval_end_str,
        'mae': mae,
        'vegas_bias': vegas_bias,
        'thresholds': threshold_results,
        'directions': dir_results,
        'daily': daily_results,
    }


def print_comparison(result_a, result_b):
    """Print side-by-side comparison of two simulations."""
    print(f"\n{'='*70}")
    print(f"  COMPARISON")
    print(f"{'='*70}")
    # Shorten labels: extract the distinguishing train-end date
    def _short_label(label):
        # From model names like catboost_v9_33f_train20251102-20260108_...
        # extract the train-end date: 20260108 -> 2026-01-08
        if 'train' in label:
            parts = label.split('train')[-1]
            # parts = "20251102-20260108_..." or "20260106-20260205_..."
            if '-' in parts:
                end_part = parts.split('-')[1][:8]  # "20260108"
                if len(end_part) == 8:
                    return f"train>{end_part[:4]}-{end_part[4:6]}-{end_part[6:]}"
            return 'train' + parts[:13]
        return label[:22]
    col_a = _short_label(result_a['label'])
    col_b = _short_label(result_b['label'])
    print(f"  {'Metric':<20s} {col_a:>22s} {col_b:>22s} {'Delta':>10s}")
    print(f"  {'-'*20} {'-'*22} {'-'*22} {'-'*10}")

    mae_d = result_a['mae'] - result_b['mae']
    print(f"  {'MAE':<20s} {result_a['mae']:>22.2f} {result_b['mae']:>22.2f} "
          f"{mae_d:>+10.2f}")

    vb_d = result_a['vegas_bias'] - result_b['vegas_bias']
    print(f"  {'Vegas Bias':<20s} {result_a['vegas_bias']:>+22.2f} "
          f"{result_b['vegas_bias']:>+22.2f} {vb_d:>+10.2f}")

    for t in [1, 3, 5]:
        ta = result_a['thresholds'].get(t, {})
        tb = result_b['thresholds'].get(t, {})
        hr_a, hr_b = ta.get('hr', 0), tb.get('hr', 0)
        pnl_a, pnl_b = ta.get('pnl', 0), tb.get('pnl', 0)

        wl_a = f"{ta.get('w', 0)}W-{ta.get('l', 0)}L"
        wl_b = f"{tb.get('w', 0)}W-{tb.get('l', 0)}L"
        pnl_a_str, pnl_b_str = f"${pnl_a:+,d}", f"${pnl_b:+,d}"
        pnl_d_str = f"${pnl_a - pnl_b:+,d}"

        print(f"  {'Edge ' + str(t) + '+ HR':<20s} {hr_a:>21.1f}% {hr_b:>21.1f}% "
              f"{hr_a - hr_b:>+9.1f}%")
        print(f"  {'  W-L':<20s} {wl_a:>22s} {wl_b:>22s}")
        print(f"  {'  P&L':<20s} {pnl_a_str:>22s} {pnl_b_str:>22s} {pnl_d_str:>10s}")

        # Direction sub-rows
        da = result_a['directions'].get(t, {})
        db = result_b['directions'].get(t, {})
        for direction in ['over', 'under']:
            dda = da.get(direction, {})
            ddb = db.get(direction, {})
            dhr_a, dhr_b = dda.get('hr', 0), ddb.get('hr', 0)
            dwl_a = f"{dda.get('w', 0)}W-{dda.get('l', 0)}L"
            dwl_b = f"{ddb.get('w', 0)}W-{ddb.get('l', 0)}L"
            label = f"    {direction.upper()}"
            print(f"  {label:<20s} {dwl_a + ' ' + str(dhr_a) + '%':>22s} "
                  f"{dwl_b + ' ' + str(dhr_b) + '%':>22s}")


def main():
    args = parse_args()
    bq_client = bigquery.Client(project=PROJECT_ID)

    print("What-If Retrain Simulation")
    print("Pure simulation — no writes to BigQuery or GCS")

    # Primary simulation
    result_a = run_simulation(
        bq_client, args.eval_start, args.eval_end,
        train_end_str=args.train_end, model_path=args.model_path,
        train_days=args.train_days, verbose=args.verbose,
    )

    # Comparison simulation
    result_b = None
    if args.compare_with:
        # Detect if compare_with is a date or a model path
        is_path = args.compare_with.startswith("gs://") or args.compare_with.endswith(".cbm")
        result_b = run_simulation(
            bq_client, args.eval_start, args.eval_end,
            train_end_str=None if is_path else args.compare_with,
            model_path=args.compare_with if is_path else None,
            train_days=args.train_days, verbose=args.verbose,
        )

    if result_a and result_b:
        print_comparison(result_a, result_b)


if __name__ == '__main__':
    main()
