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


def cycles(start, end, cadence=CADENCE):
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    es = s + timedelta(days=WINDOW)
    while es <= e:
        ee = min(es + timedelta(days=cadence - 1), e)
        yield es, ee
        es = ee + timedelta(days=1)


def grade(res):
    """Add edge/direction/correct columns; drop pushes. Mirrors run_season."""
    res = res.copy()
    res['edge'] = res['predicted_points'] - res['line']
    res['direction'] = np.where(res['edge'] > 0, 'OVER', 'UNDER')
    res = res[res['actual_points'] != res['line']].copy()  # drop pushes
    res['correct'] = np.where(
        ((res['actual_points'] > res['line']) & (res['direction'] == 'OVER')) |
        ((res['actual_points'] < res['line']) & (res['direction'] == 'UNDER')), 1, 0)
    return res


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


def run_arm(df, start, end, cadence, freeze_date, label):
    """Walk-forward over a pre-loaded season df under a retrain-staleness regime.

    cadence: retrain every `cadence` days (model serving the last eval day of a
      window is up to cadence-1 days stale). window=WINDOW fixed.
    freeze_date: if set, train fresh weekly UNTIL the model's train window ends
      after freeze_date, then FREEZE — reuse the last model trained on data
      through ~freeze_date for the rest of the season (simulates production where
      retraining stopped). When set, `cadence` is forced to 7 for fine eval
      coverage so pre/post-freeze months are comparable.
    """
    if freeze_date is not None:
        cadence = 7
        freeze_ts = pd.Timestamp(freeze_date)
    out_rows = []
    frozen_model = None
    n_trains = 0
    for ci, (es, ee) in enumerate(cycles(start, end, cadence), 1):
        ts = pd.Timestamp(es) - timedelta(days=WINDOW)
        te = pd.Timestamp(es) - timedelta(days=1)
        ev = df[(df['game_date'] >= pd.Timestamp(es)) & (df['game_date'] <= pd.Timestamp(ee))]
        ev = ev[ev['line'].notna() & (ev['line'] > 0)]
        ev = ev[((ev['line'] * 2) % 1 == 0)]
        if len(ev) == 0:
            continue
        use_frozen = freeze_date is not None and frozen_model is not None and te > freeze_ts
        if use_frozen:
            model = frozen_model
        else:
            train = df[(df['game_date'] >= ts) & (df['game_date'] <= te)]
            if len(train) < 500:
                continue
            Xtr, ytr = prepare_features(train, V12_CONTRACT, exclude_features=VEGAS_FEATURE_NAMES)
            Xt, Xv, yt, yv = _train_val_split(Xtr, ytr, val_frac=0.15)
            model = cb.CatBoostRegressor(**DEFAULT_CATBOOST_PARAMS)
            model.fit(Xt, yt, eval_set=(Xv, yv), verbose=0)
            n_trains += 1
            # keep the most recent model whose train window ends on/before the freeze
            if freeze_date is not None and te <= freeze_ts:
                frozen_model = model
        Xev, yev = prepare_features(ev, V12_CONTRACT, exclude_features=VEGAS_FEATURE_NAMES)
        preds = model.predict(Xev)
        out_rows.append(pd.DataFrame({
            'game_date': ev['game_date'].dt.strftime('%Y-%m-%d').values,
            'player_lookup': ev['player_lookup'].values,
            'predicted_points': np.asarray(preds, dtype=float),
            'line': ev['line'].astype(float).values,
            'actual_points': ev['actual_points'].astype(float).values,
        }))
    res = grade(pd.concat(out_rows, ignore_index=True))
    res['month'] = pd.to_datetime(res['game_date']).dt.strftime('%Y-%m')
    res['arm'] = label
    e3 = res[res.edge.abs() >= 3]; e5 = res[res.edge.abs() >= 5]
    print(f"\n[{label}] trains={n_trains} graded={len(res):,} "
          f"| HR@e3+={100*e3.correct.mean():.1f}% (N={len(e3)}) "
          f"| HR@e5+={100*e5.correct.mean():.1f}% (N={len(e5)})", flush=True)
    return res


def stale_arms(client, season='2025-26'):
    """STEP 5a: reproduce (or refute) the production late-season collapse as a
    retrain-STALENESS effect. Run the same season+window(56) at 4 retrain
    regimes and compare monthly HR. If HR only sags Mar/Apr in the long-cadence /
    frozen arms -> staleness reproduced. If even frozen-Feb28 holds -> collapse
    is NOT staleness; STOP and keep cap_to_pre_late_season only as insurance."""
    start, end, _ = SEASONS[season]
    print(f"\n=== STALENESS ARMS {season} ({start}..{end}), window={WINDOW} fixed ===", flush=True)
    df = load_season(client, start, end)
    print(f"  loaded {len(df):,} quality rows", flush=True)
    arms = [
        ('cad7_fresh', 7, None),
        ('cad21', 21, None),
        ('cad28', 28, None),
        ('frozen_feb28', 7, '2026-02-28'),
    ]
    all_res = []
    for label, cadence, freeze in arms:
        all_res.append(run_arm(df, start, end, cadence, freeze, label))
    full = pd.concat(all_res, ignore_index=True)

    # Monthly HR table (all picks) per arm
    print("\n--- Monthly HR (all picks) ---", flush=True)
    piv = full.pivot_table(index='month', columns='arm', values='correct',
                           aggfunc='mean') * 100
    cnt = full.pivot_table(index='month', columns='arm', values='correct', aggfunc='count')
    arm_order = [a[0] for a in arms]
    piv = piv[[c for c in arm_order if c in piv.columns]]
    print(piv.round(1).to_string(), flush=True)
    print("\n--- Monthly N ---", flush=True)
    print(cnt[[c for c in arm_order if c in cnt.columns]].to_string(), flush=True)

    # Mar+Apr edge5+ pooled HR per arm (the production collapse window)
    print("\n--- Mar+Apr pooled HR by arm (the collapse window) ---", flush=True)
    late = full[full.month.isin(['2026-03', '2026-04'])]
    for label in arm_order:
        a = late[late.arm == label]
        a3 = a[a.edge.abs() >= 3]; a5 = a[a.edge.abs() >= 5]
        print(f"  {label:14s} all={100*a.correct.mean():5.1f}% (N={len(a)}) "
              f"| e3+={100*a3.correct.mean():5.1f}% (N={len(a3)}) "
              f"| e5+={100*a5.correct.mean() if len(a5) else float('nan'):5.1f}% (N={len(a5)})", flush=True)

    outdir = Path('results/nba_staleness')
    outdir.mkdir(parents=True, exist_ok=True)
    full.to_csv(outdir / 'staleness_arms_2025_26.csv', index=False)
    piv.round(2).to_csv(outdir / 'staleness_monthly_hr_2025_26.csv')
    print(f"\nWROTE {outdir}/staleness_arms_2025_26.csv ({len(full):,} rows) + monthly HR", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default=','.join(SEASONS), help='comma-separated seasons')
    ap.add_argument('--stale-arms', action='store_true',
                    help='STEP 5a: run 2025-26 staleness arms (cad 7/21/28 + frozen-Feb28) instead of cache rebuild')
    args = ap.parse_args()
    client = bigquery.Client(project=PROJECT_ID)
    if args.stale_arms:
        stale_arms(client)
        return
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
