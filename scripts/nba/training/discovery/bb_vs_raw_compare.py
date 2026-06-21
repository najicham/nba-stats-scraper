#!/usr/bin/env python3
"""INC-4 measurement: compare the BB-pipeline-selected picks (from bb_injection_run.py
--out) against the RAW single-model edge picks from the walk-forward cache, over the
SAME season window. Answers: do signals+filters add value over raw model edge?

Both are graded against the identical cache `correct` column (same predictions, line,
direction, edge), so this is a clean apples-to-apples HR comparison: RAW = every cache
prediction at an edge band; BB = the pipeline-selected subset.

Usage:
  PYTHONPATH=. python scripts/nba/training/discovery/bb_vs_raw_compare.py \
      --bb results/bb_simulator/bb_injection_picks_2025_26.csv \
      --start 2025-10-28 --end 2026-04-12
"""
import argparse
from pathlib import Path

import pandas as pd

CACHE = ['results/nba_walkforward_2021/predictions_w56_r7.csv',
         'results/nba_walkforward_2022/predictions_w56_r7.csv',
         'results/nba_walkforward_clean/predictions_w56_r7.csv',
         'results/bb_simulator/predictions_2025_26_all_models.csv']


def hr(df, col='correct'):
    return (100 * df[col].mean(), len(df)) if len(df) else (float('nan'), 0)


def band_table(df, edge_col, rec_col, label):
    print(f"\n{label}:")
    a = hr(df)
    print(f"  ALL: {a[0]:.1f}% (N={a[1]})")
    for lo, lab in [(3, 'edge3+'), (5, 'edge5+'), (6, 'edge6+'), (7, 'edge7+')]:
        s = df[df[edge_col] >= lo]
        o = s[s[rec_col] == 'OVER']
        u = s[s[rec_col] == 'UNDER']
        aa, oo, uu = hr(s), hr(o), hr(u)
        print(f"  {lab}: {aa[0]:.1f}% (N={aa[1]}) | OVER {oo[0]:.1f}% (N={oo[1]}) | "
              f"UNDER {uu[0]:.1f}% (N={uu[1]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bb', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    args = ap.parse_args()

    cache = pd.concat([pd.read_csv(f) for f in CACHE if Path(f).exists()], ignore_index=True)
    cache = cache.drop_duplicates(['game_date', 'player_lookup', 'line'])
    cache['game_date'] = cache['game_date'].astype(str)
    cache = cache[(cache.game_date >= args.start) & (cache.game_date <= args.end)].copy()
    cache['ae'] = cache['edge'].abs()

    bb = pd.read_csv(args.bb)
    bb['game_date'] = bb['game_date'].astype(str)
    bb = bb[bb['correct'].notna()].copy()
    bb['correct'] = bb['correct'].astype(int)

    print("=" * 70)
    print(f"  BB-PIPELINE vs RAW — single model wf_sim_v12noveg [{args.start}..{args.end}]")
    print("=" * 70)
    band_table(cache, 'ae', 'direction', "RAW (all cache predictions at edge band)")
    band_table(bb, 'abs_edge', 'rec', "BB-PIPELINE (signal/filter-selected picks)")

    # Volume + monthly
    bb['month'] = bb['game_date'].str[:7]
    print("\nBB picks by month:")
    for m, grp in bb.groupby('month'):
        h = hr(grp)
        print(f"  {m}: {h[0]:.1f}% (N={h[1]})")

    # Headline deltas at edge5+
    rawe5 = cache[cache.ae >= 5]
    bbe5 = bb[bb.abs_edge >= 5]
    print("\nHEADLINE (edge5+):")
    print(f"  RAW edge5+: {hr(rawe5)[0]:.1f}% (N={hr(rawe5)[1]})")
    print(f"  BB  edge5+: {hr(bbe5)[0]:.1f}% (N={hr(bbe5)[1]})")
    print(f"  BB total picks: {len(bb)} over the window")


if __name__ == '__main__':
    main()
