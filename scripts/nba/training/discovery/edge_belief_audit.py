#!/usr/bin/env python3
"""First payload on the rebuilt walk-forward cache: edge->HR calibration across 5
clean seasons + re-validation of the documented edge-strategy beliefs.

Beliefs under test (from CLAUDE.md / MEMORY):
  B1: OVER is net-negative at edge 3-5 in 4/5 seasons (43-50% HR).
  B2: UNDER is stable ~57-58% across ALL edge levels.
  B3: edge 6-8 = ~61% HR, consistent across all seasons (edge 6-7 breaks in 2022-23).
  B4: edge5+ is the money zone (>=60%).
Cache = single CatBoost V12_NOVEG walk-forward (w56_r7), in-store vegas line. Flat -110.
"""
import glob
from pathlib import Path
import numpy as np
import pandas as pd

FILES = [
    'results/nba_walkforward_2021/predictions_w56_r7.csv',
    'results/nba_walkforward_2022/predictions_w56_r7.csv',
    'results/nba_walkforward_clean/predictions_w56_r7.csv',
    'results/bb_simulator/predictions_2025_26_all_models.csv',
]
RANGES = {'2021-22': ('2021-10-01', '2022-07-01'), '2022-23': ('2022-10-01', '2023-07-01'),
          '2023-24': ('2023-10-01', '2024-07-01'), '2024-25': ('2024-10-01', '2025-07-01'),
          '2025-26': ('2025-10-01', '2026-07-01')}

def season_of(d):
    for s, (a, b) in RANGES.items():
        if a <= d <= b:
            return s
    return '?'

frames = []
for f in FILES:
    if Path(f).exists():
        df = pd.read_csv(f)
        frames.append(df)
ALL = pd.concat(frames, ignore_index=True).drop_duplicates(['game_date', 'player_lookup', 'line'])
ALL['season'] = ALL['game_date'].astype(str).map(season_of)
ALL['abs_edge'] = ALL['edge'].abs()
print(f"Total graded preds: {len(ALL):,} | seasons: {sorted(ALL.season.unique())}")
print("Per season N:", {s: int(n) for s, n in ALL.season.value_counts().items()})

def hr(df):
    n = len(df); return (100*df.correct.mean() if n else float('nan')), n

def table(df, label):
    print(f"\n===== {label} =====")
    print(f"  {'edge':>7} | {'ALL HR (N)':>16} | {'OVER HR (N)':>16} | {'UNDER HR (N)':>16}")
    buckets = [(0,3,'0-3'),(3,5,'3-5'),(5,7,'5-7'),(7,10,'7-10'),(5,99,'5+'),(6,8,'6-8'),(3,99,'3+')]
    for lo,hi,lab in buckets:
        s = df[(df.abs_edge>=lo)&(df.abs_edge<hi)]
        a,an = hr(s); o,on = hr(s[s.direction=='OVER']); u,un = hr(s[s.direction=='UNDER'])
        print(f"  {lab:>7} | {a:6.1f}% ({an:5d}) | {o:6.1f}% ({on:4d}) | {u:6.1f}% ({un:4d})")

table(ALL, "POOLED (5 seasons)")
for s in sorted(ALL.season.unique()):
    table(ALL[ALL.season==s], f"SEASON {s}")

print("\n\n##### BELIEF RE-VALIDATION (per-season consistency) #####")
seasons = sorted(ALL.season.unique())
def cell(df, lo, hi, direction=None):
    s = df[(df.abs_edge>=lo)&(df.abs_edge<hi)]
    if direction: s = s[s.direction==direction]
    h,n = hr(s); return h,n

print("\nB1: OVER edge 3-5 HR by season (claim: net-neg 43-50% in 4/5):")
b1=0
for s in seasons:
    h,n=cell(ALL[ALL.season==s],3,5,'OVER')
    neg = (not np.isnan(h)) and h<52.4
    b1 += neg
    print(f"  {s}: {h:5.1f}% (N={n}) {'NET-NEG' if neg else 'profitable' if not np.isnan(h) else 'n/a'}")
print(f"  -> net-negative in {b1}/{len(seasons)} seasons")

print("\nB2: UNDER HR across edge bands (claim: stable ~57-58%):")
for lo,hi,lab in [(0,3,'0-3'),(3,5,'3-5'),(5,99,'5+')]:
    h,n=cell(ALL,lo,hi,'UNDER'); print(f"  UNDER edge {lab}: {h:5.1f}% (N={n})")

print("\nB3: edge 6-8 HR by season (claim: ~61% consistent):")
for s in seasons:
    h,n=cell(ALL[ALL.season==s],6,8); print(f"  {s}: {h:5.1f}% (N={n})")
h,n=cell(ALL,6,8); print(f"  POOLED: {h:5.1f}% (N={n})")

print("\nB4: edge5+ money zone by season (claim: >=60%):")
for s in seasons:
    h,n=cell(ALL[ALL.season==s],5,99); print(f"  {s}: {h:5.1f}% (N={n})")
h,n=cell(ALL,5,99); print(f"  POOLED: {h:5.1f}% (N={n})")
