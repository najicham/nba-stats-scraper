#!/usr/bin/env python3
"""Rebuild the walk-forward prediction cache the discovery stack consumes.

The discovery loader (scripts/nba/training/discovery/data_loader.py) reads
leak-clean walk-forward predictions from:
  results/nba_walkforward_2021/predictions_w56_r7.csv   (2021-22)
  results/nba_walkforward_2022/predictions_w56_r7.csv   (2022-23)
  results/nba_walkforward_clean/predictions_w56_r7.csv  (2023-24 + 2024-25)
  results/bb_simulator/predictions_2025_26_all_models.csv (2025-26)
These were produced by the now-LOST bb_enriched_simulator.py. This script
regenerates them.

Method (per season): one bulk BQ load of the feature store + actuals + the
in-store vegas line (feature_25_value, the only line source covering all 5
seasons), then a rolling w56_r7 walk-forward (train on prior 56d, predict next
7d, step 7d). Model = CatBoost V12_NOVEG (production base; noveg keeps edge
non-circular since the model never sees the line). Every cycle trains only on
PAST data -> inherently leak-safe.

Output columns (per data_loader contract): game_date, player_lookup,
predicted_points, line, edge, correct, direction, actual_points. Pushes
(actual==line) dropped. NO writes to BQ/GCS.

Usage:
  PYTHONPATH=. python -u scripts/nba/training/discovery/build_walkforward_predictions.py
  PYTHONPATH=. python -u scripts/nba/training/discovery/build_walkforward_predictions.py --seasons 2024-25  # smoke
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import numpy as np
import pandas as pd
from google.cloud import bigquery
import catboost as cb

from shared.ml.feature_contract import (
    V12_CONTRACT, FEATURE_STORE_FEATURE_COUNT, FEATURE_STORE_NAMES,
)
from shared.ml.training_data_loader import get_quality_where_clause
from ml.experiments.season_walkforward import (
    prepare_features, _train_val_split, DEFAULT_CATBOOST_PARAMS,
)

PROJECT_ID = "nba-props-platform"
VEGAS_FEATURE_NAMES = ['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line']
LINE_IDX = FEATURE_STORE_NAMES.index('vegas_points_line')  # feature_25 historically

# season -> (regular-season start, end, output_path, combine_group)
SEASONS = {
    '2021-22': ('2021-10-19', '2022-04-10', 'results/nba_walkforward_2021/predictions_w56_r7.csv'),
    '2022-23': ('2022-10-18', '2023-04-09', 'results/nba_walkforward_2022/predictions_w56_r7.csv'),
    '2023-24': ('2023-10-24', '2024-04-14', 'results/nba_walkforward_clean/predictions_w56_r7.csv'),
    '2024-25': ('2024-10-22', '2025-04-13', 'results/nba_walkforward_clean/predictions_w56_r7.csv'),
    '2025-26': ('2025-10-28', '2026-04-12', 'results/bb_simulator/predictions_2025_26_all_models.csv'),
}
WINDOW = 56
CADENCE = 7


def load_season(client, start, end):
    """Bulk-load quality-ready feature rows + actuals + in-store line for a season (+56d lead)."""
    load_start = (date.fromisoformat(start) - timedelta(days=WINDOW + 3)).isoformat()
    quality = get_quality_where_clause("mf")
    feat_cols = ',\n      '.join(f'mf.feature_{i}_value' for i in range(FEATURE_STORE_FEATURE_COUNT))
    q = f"""
    SELECT mf.player_lookup, mf.game_date,
      {feat_cols},
      pgs.points AS actual_points
    FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2` mf
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` pgs
      ON mf.player_lookup = pgs.player_lookup AND mf.game_date = pgs.game_date
    WHERE mf.game_date BETWEEN '{load_start}' AND '{end}'
      AND {quality}
      AND pgs.points IS NOT NULL AND pgs.minutes_played > 0
    """
    df = client.query(q).to_dataframe()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df['line'] = pd.to_numeric(df[f'feature_{LINE_IDX}_value'], errors='coerce')
    return df


def cycles(start, end):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    es = s + timedelta(days=WINDOW)
    while es <= e:
        ee = min(es + timedelta(days=CADENCE - 1), e)
        yield es, ee
        es = ee + timedelta(days=1)


def run_season(client, season, start, end):
    print(f"\n=== {season} ({start}..{end}) ===", flush=True)
    df = load_season(client, start, end)
    print(f"  loaded {len(df):,} quality rows", flush=True)
    out_rows = []
    for ci, (es, ee) in enumerate(cycles(start, end), 1):
        ts = pd.Timestamp(es) - timedelta(days=WINDOW)
        te = pd.Timestamp(es) - timedelta(days=1)
        train = df[(df['game_date'] >= ts) & (df['game_date'] <= te)]
        ev = df[(df['game_date'] >= pd.Timestamp(es)) & (df['game_date'] <= pd.Timestamp(ee))]
        # eval requires a valid pre-game line (.0/.5)
        ev = ev[ev['line'].notna() & (ev['line'] > 0)]
        ev = ev[((ev['line'] * 2) % 1 == 0)]
        if len(train) < 500 or len(ev) == 0:
            continue
        Xtr, ytr = prepare_features(train, V12_CONTRACT, exclude_features=VEGAS_FEATURE_NAMES)
        Xt, Xv, yt, yv = _train_val_split(Xtr, ytr, val_frac=0.15)
        model = cb.CatBoostRegressor(**DEFAULT_CATBOOST_PARAMS)
        model.fit(Xt, yt, eval_set=(Xv, yv), verbose=0)
        Xev, yev = prepare_features(ev, V12_CONTRACT, exclude_features=VEGAS_FEATURE_NAMES)
        preds = model.predict(Xev)
        sub = pd.DataFrame({
            'game_date': ev['game_date'].dt.strftime('%Y-%m-%d').values,
            'player_lookup': ev['player_lookup'].values,
            'predicted_points': np.asarray(preds, dtype=float),
            'line': ev['line'].astype(float).values,
            'actual_points': ev['actual_points'].astype(float).values,
        })
        out_rows.append(sub)
        if ci % 5 == 0:
            print(f"  cycle {ci}: eval {es}..{ee} N={len(ev)} train={len(train)}", flush=True)
    if not out_rows:
        print(f"  WARNING: no predictions for {season}", flush=True)
        return None
    res = pd.concat(out_rows, ignore_index=True)
    res['edge'] = res['predicted_points'] - res['line']
    res['direction'] = np.where(res['edge'] > 0, 'OVER', 'UNDER')
    res = res[res['actual_points'] != res['line']].copy()  # drop pushes
    res['correct'] = np.where(
        ((res['actual_points'] > res['line']) & (res['direction'] == 'OVER')) |
        ((res['actual_points'] < res['line']) & (res['direction'] == 'UNDER')), 1, 0)
    print(f"  -> {len(res):,} graded preds | HR@e3+={100*res[res.edge.abs()>=3]['correct'].mean():.1f}% "
          f"| HR@e5+={100*res[res.edge.abs()>=5]['correct'].mean():.1f}% (N5={int((res.edge.abs()>=5).sum())})", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default=','.join(SEASONS), help='comma-separated seasons')
    args = ap.parse_args()
    client = bigquery.Client(project=PROJECT_ID)
    want = [s.strip() for s in args.seasons.split(',')]
    # group by output path so 2023-24 + 2024-25 concat into _clean
    by_path = {}
    for season in want:
        start, end, outpath = SEASONS[season]
        res = run_season(client, season, start, end)
        if res is not None:
            by_path.setdefault(outpath, []).append(res)
    for outpath, frames in by_path.items():
        Path(outpath).parent.mkdir(parents=True, exist_ok=True)
        full = pd.concat(frames, ignore_index=True)
        full.to_csv(outpath, index=False)
        print(f"\nWROTE {outpath}: {len(full):,} rows", flush=True)


if __name__ == '__main__':
    main()
