"""high_line_under overlap analysis (2026-06-23, session 3).

Question for the season-open action list: `high_line_under` (UNDER, line>=25)
passed the formal discovery gate (59.9%, 5/5 seasons, p=0.0007). Before adding it
as a new ACTIVE UNDER signal we must answer: does it OVERLAP with the existing
UNDER signal layer, or does it tag NEW winners the current signals miss?

A signal that only re-tags picks an existing UNDER signal already fires adds no
incremental coverage (real_sc would already be >=1 on those picks). The decision
hinges on the ORTHOGONAL subset: high_line_under picks that fire NO existing real
UNDER signal. If that subset is large AND above breakeven cross-season, the signal
is additive. If small or weak, it is redundant.

Reuses combo_tester.define_signal_conditions() so the signal predicates match the
rest of the discovery suite exactly.

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/high_line_under_overlap.py
"""

import logging

import numpy as np
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.combo_tester import define_signal_conditions
from scripts.nba.training.discovery.stats_utils import (
    BASELINE_HR,
    compute_hypothesis_stats,
)

logging.basicConfig(level=logging.WARNING, format='%(message)s')

# Real-breakeven at -110 (~53.5%); nominal is 52.4%. Use nominal for "above BE".
BREAKEVEN = 0.524

# Existing ACTIVE UNDER signals (UNDER_SIGNAL_WEIGHTS, non-shadow) that have a
# column proxy in define_signal_conditions(). These are what would already give a
# line>=25 UNDER pick real_sc >= 1 today.
#   sharp_line_drop_under  -> bp_dropped_heavy_under (line_movement <= -1.0)
#   line_drifted_down_under-> bp_dropped_under + line_drop_under (drift down)
#   book_disagree*         -> book_disagree_under (line_std >= 1.0)
#   home_under             -> home_under (UNDER & home & line>=15)
#   volatile_starter_under -> volatile_under (proxy is line-capped 18-25; see note)
#   hot_3pt_under          -> hot_3pt_under
# Excluded: bench_under (look-ahead bias, not deployable pre-game), quantile_ceiling
# (MQ-only, not in this single-model WF cache), book_disagreement (== book_disagree_under proxy).
EXISTING_UNDER_PROXIES = [
    'hot_3pt_under',
    'home_under',
    'volatile_under',
    'bp_dropped_under',
    'bp_dropped_heavy_under',
    'line_drop_under',
    'book_disagree_under',
]


def hr_line(label, sub):
    if len(sub) == 0:
        return f"  {label:<42} N=0"
    hr = sub['correct'].mean()
    return f"  {label:<42} N={len(sub):>4}  HR={hr:>6.1%}  ({int(sub['correct'].sum())}-{len(sub) - int(sub['correct'].sum())})"


def per_season(sub):
    out = []
    for s, g in sub.groupby('season'):
        out.append(f"{s}:{g['correct'].mean():.0%}(N={len(g)})")
    return "  ".join(out)


def main():
    ds = DiscoveryDataset(min_edge=0.0)
    df = ds.df.copy()
    df = df[df['abs_edge'] >= 3.0]  # the band a deployed UNDER signal operates in
    print(f"Loaded {len(df)} edge3+ rows, seasons {sorted(df['season'].unique())}\n")

    sigs = define_signal_conditions(df)
    available = [s for s in EXISTING_UNDER_PROXIES if s in sigs]
    missing = [s for s in EXISTING_UNDER_PROXIES if s not in sigs]
    if missing:
        print(f"WARNING: no column proxy for {missing} (cols absent in cache)\n")

    # high_line_under = star_line_under in combo_tester
    hlu = sigs['star_line_under']  # UNDER & line >= 25
    hlu_df = df[hlu]

    print("=" * 78)
    print("high_line_under (UNDER, line>=25, edge3+) — standalone")
    print("=" * 78)
    print(hr_line("high_line_under", hlu_df))
    st = compute_hypothesis_stats(hlu_df, baseline=BASELINE_HR)
    if st:
        c = st['consistency']
        print(f"  p={st['p_value']}  boot_CI=[{st['bootstrap_ci_lo']:.3f},{st['bootstrap_ci_hi']:.3f}]"
              f"  seasons_above_BE={c['seasons_consistent']}/{c['seasons_valid']}")
    print(f"  {per_season(hlu_df)}\n")

    # Existing-signal coverage WITHIN the high_line_under population
    print("=" * 78)
    print("Overlap: which EXISTING UNDER signals also fire on high_line_under picks")
    print("=" * 78)
    fires_any = pd.Series(False, index=df.index)
    for s in available:
        m = sigs[s] & hlu
        fires_any = fires_any | sigs[s]
        n = int(m.sum())
        frac = n / len(hlu_df) if len(hlu_df) else 0
        hr = df[m]['correct'].mean() if n else float('nan')
        print(f"  {s:<26} co-fires {n:>4} / {len(hlu_df)} ({frac:>5.1%})  HR={hr:>6.1%}" if n
              else f"  {s:<26} co-fires    0")

    # Partition high_line_under into overlapping vs orthogonal
    overlap_mask = hlu & fires_any
    orth_mask = hlu & ~fires_any
    overlap_df = df[overlap_mask]
    orth_df = df[orth_mask]

    print("\n" + "=" * 78)
    print("DECISION SPLIT — high_line_under partitioned by existing-signal coverage")
    print("=" * 78)
    print(hr_line("ALREADY covered (fires >=1 existing UNDER sig)", overlap_df))
    if len(overlap_df):
        print(f"      {per_season(overlap_df)}")
    print(hr_line("ORTHOGONAL (fires NO existing UNDER sig)", orth_df))
    orth_pct = len(orth_df) / len(hlu_df) if len(hlu_df) else 0
    print(f"      orthogonal share = {orth_pct:.1%} of all high_line_under picks")
    if len(orth_df):
        print(f"      {per_season(orth_df)}")
        st_o = compute_hypothesis_stats(orth_df, baseline=BASELINE_HR)
        if st_o:
            c = st_o['consistency']
            above = sum(1 for s, g in orth_df.groupby('season')
                        if len(g) >= 10 and g['correct'].mean() > BREAKEVEN)
            nseas = sum(1 for s, g in orth_df.groupby('season') if len(g) >= 10)
            print(f"      p={st_o['p_value']}  boot_CI=[{st_o['bootstrap_ci_lo']:.3f},{st_o['bootstrap_ci_hi']:.3f}]")
            print(f"      seasons above breakeven (N>=10): {above}/{nseas}")

    # Incremental real_sc lift: of all edge3+ UNDER picks, how many gain real_sc>=1
    # ONLY because of high_line_under (i.e. orthogonal ones)?
    under_e3 = df[df['direction'] == 'UNDER']
    print("\n" + "=" * 78)
    print("INCREMENTAL COVERAGE (context: all edge3+ UNDER picks)")
    print("=" * 78)
    print(f"  edge3+ UNDER picks total:                {len(under_e3)}")
    print(f"  ...high_line_under picks:                {len(hlu_df)} ({len(hlu_df)/len(under_e3):.1%})")
    print(f"  ...NEWLY covered by high_line_under only: {len(orth_df)} ({len(orth_df)/len(under_e3):.1%})")
    print("\nVERDICT GUIDE: additive if orthogonal subset is BOTH sizeable (say >40% of")
    print("the signal, >=80 picks) AND above breakeven in >=3 seasons. Redundant if the")
    print("orthogonal subset is small or sub-breakeven.")


if __name__ == '__main__':
    main()
