"""Structural selection signals — price (no-vig) + CLV proxy (2026-06-23).

Post error-decomposition (which proved the model is well-specified → no feature to
add), these are tested as SELECTION signals, not model features. Both use columns that
are cross-season-populated (96-100% all 5 seasons), unlike implied_team_total/game_total
(0% pre-2025 — DROPPED, single-season artifact, the 3rd such case after is_b2b and
star_teammates_out).

A. No-vig / over-price juice: over_odds_median (American). When the book juices the OVER
   (more negative odds), it is leaning OVER → hypothesis: FADE it (UNDER wins more / OVER
   wins less). Error-decomp already showed over_odds rho=-0.018 with residual.
B. CLV proxy: line_movement. Did the line move TOWARD our pick (UNDER & moved down, or
   OVER & moved up)? Being on the side sharp money moved toward should predict winning.
   This is the closest in-cache proxy to closing-line value (true CLV needs production
   closing lines — a separate BQ pull).

Gate discipline: HR + Wilson CI + per-season above-breakeven (>=3/5) + binomial p.

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/structural_selection_signals.py
"""

import logging
import math
import numpy as np
import pandas as pd
from scipy import stats

from scripts.nba.training.discovery.data_loader import DiscoveryDataset

logging.basicConfig(level=logging.WARNING, format='%(message)s')
NOMINAL_BE, REAL_BE, BASE = 0.524, 0.535, 0.515


def wilson(w, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def american_to_prob(o):
    return np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))


def line(label, sub):
    if len(sub) < 30:
        return f"  {label:<40} N={len(sub):>4}  (insufficient)"
    w = int(sub['correct'].sum())
    hr = w / len(sub)
    lo, hi = wilson(w, len(sub))
    p = stats.binomtest(w, len(sub), BASE, alternative='greater').pvalue
    above = sum(1 for _, g in sub.groupby('season')
                if len(g) >= 20 and g['correct'].mean() > NOMINAL_BE)
    nseas = sum(1 for _, g in sub.groupby('season') if len(g) >= 20)
    flag = '>BE' if hr > REAL_BE else ('~BE' if hr > NOMINAL_BE else '<BE')
    return (f"  {label:<40} N={len(sub):>4}  HR={hr:>5.1%}  CI[{lo:.0%},{hi:.0%}]  "
            f"p={p:.3f}  {above}/{nseas}szn>BE  {flag}")


def main():
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df = df[df['abs_edge'] >= 3.0].copy()
    df['oo'] = df['over_odds_median'].where(df['over_odds_median'].between(-1000, 1000))
    df['over_implied'] = american_to_prob(df['oo'])
    U = df['direction'] == 'UNDER'
    O = df['direction'] == 'OVER'

    print("=" * 88)
    print("STRUCTURAL SELECTION SIGNALS (edge3+, 5 seasons) — breakeven 52.4% / real 53.5%")
    print("=" * 88)

    # ---- A. No-vig / over-price juice ----
    print("\n### A. Over-price juice (over_odds_median, American). Median over-price is ~-115.")
    print("    'over_juiced' = over_odds <= -130 (book leans OVER → fade hypothesis).")
    juiced = df['oo'] <= -130
    cheap = df['oo'] >= -105
    print("\n  UNDER picks (fade the juiced over → expect HR up when over juiced):")
    print(line('UNDER | over juiced (<=-130)', df[U & juiced]))
    print(line('UNDER | over normal (-130..-105)', df[U & ~juiced & ~cheap]))
    print(line('UNDER | over cheap (>=-105)', df[U & cheap]))
    print("\n  OVER picks (juiced over = book agrees with us → expect HR down if fade is right):")
    print(line('OVER | over juiced (<=-130)', df[O & juiced]))
    print(line('OVER | over cheap (>=-105)', df[O & cheap]))

    # price-implied calibration sanity: does over_implied predict over outcome?
    ov = df[O].dropna(subset=['over_implied'])
    if len(ov) > 200:
        hi_imp = ov[ov['over_implied'] >= ov['over_implied'].median()]
        lo_imp = ov[ov['over_implied'] < ov['over_implied'].median()]
        print("\n  Sanity — OVER HR by price-implied prob (market informative?):")
        print(line('OVER | high over-implied price', hi_imp))
        print(line('OVER | low over-implied price', lo_imp))

    # ---- B. CLV proxy: line_movement toward our pick ----
    print("\n### B. CLV proxy — did the line move TOWARD our pick? (UNDER&move<0 or OVER&move>0)")
    mv = df['line_movement']
    toward = (U & (mv < 0)) | (O & (mv > 0))
    against = (U & (mv > 0)) | (O & (mv < 0))
    nomove = mv == 0
    toward_big = (U & (mv <= -1)) | (O & (mv >= 1))
    print(line('line moved TOWARD pick', df[toward]))
    print(line('line moved AGAINST pick', df[against]))
    print(line('line did NOT move', df[nomove]))
    print(line('line moved TOWARD pick by >=1.0', df[toward_big]))
    print("\n  Split by direction (is the CLV proxy UNDER- or OVER-specific?):")
    print(line('UNDER | line moved toward (down)', df[U & (mv < 0)]))
    print(line('UNDER | line moved against (up)', df[U & (mv > 0)]))
    print(line('OVER  | line moved toward (up)', df[O & (mv > 0)]))
    print(line('OVER  | line moved against (down)', df[O & (mv < 0)]))

    print("\n" + "=" * 88)
    print("READ: a signal is real only if HR>53.5%, CI excludes baseline, AND >=3/5 seasons>BE.")
    print("DROPPED (not cross-season testable): line-vs-game-total — implied_team_total/")
    print("game_total are 0% populated pre-2025 (only 2025-26). True CLV needs production")
    print("closing lines (separate BQ pull); line_movement here is a pick-time proxy.")


if __name__ == '__main__':
    main()
