"""OVER scoring-environment gate — design + 5-season backtest (2026-06-23).

Research finding (broad-research-findings.md): OVER edge3+ is profitable in ONLY
1/5 seasons (2025-26), a soft/high-scoring market. The existing TIGHT gate
(vegas_mae_7d < 4.5) throttles OVER *volume* but does not make OVER *profitable* —
it keys on book accuracy, not on whether the league is actually scoring above
expectation. The strategic ask for 2026-27 is a direct scoring-environment gate:
only lean into OVER when the league is genuinely scoring above line expectation
(the regime that made 2025-26 OVER win), and treat OVER as unproven otherwise.

This script (a) defines a deployable, PRE-GAME-SAFE scoring-environment metric and
(b) backtests whether it separates the OVER-profitable regime across ALL 5 seasons
— not just re-discovers 2025-26.

METRIC: `scoring_env_10d` = mean(actual_points - line) over ALL graded picks in the
prior 10 game-days, lagged by >=1 day (today's results excluded → no leakage).
Positive => players are beating their lines lately (hot scoring env). This is
computable in production from prediction_accuracy / league_macro_daily.

DECISION: the gate is worth building only if, POOLED ACROSS SEASONS, OVER edge3+ HR
in the "hot env" bucket clears breakeven AND the "cold env" bucket is clearly below
it — i.e. the metric, not the calendar, is doing the separating.

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/over_scoring_env_gate.py
"""

import logging

import numpy as np
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset

logging.basicConfig(level=logging.WARNING, format='%(message)s')

BREAKEVEN = 0.524        # nominal -110
REAL_BREAKEVEN = 0.535   # with vig realism
TRAIL_DAYS = 10          # trailing game-days for the env metric


def wilson(wins, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    d = 1 + z**2 / n
    c = p + z**2 / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return ((c - m) / d, (c + m) / d)


def hrline(label, sub):
    if len(sub) == 0:
        return f"  {label:<34} N=0"
    w = int(sub['correct'].sum())
    hr = w / len(sub)
    lo, hi = wilson(w, len(sub))
    flag = ">BE" if hr > REAL_BREAKEVEN else ("~BE" if hr > BREAKEVEN else "<BE")
    return f"  {label:<34} N={len(sub):>4}  HR={hr:>6.1%}  [{lo:.0%},{hi:.0%}]  {flag}"


def main():
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df = df.dropna(subset=['actual_points', 'line']).copy()
    df['beat'] = df['actual_points'] - df['line']          # realized over/under margin
    df['game_date'] = pd.to_datetime(df['game_date'])

    # --- Build the trailing, lagged scoring-env metric on the WHOLE market ---
    # Daily league mean(actual - line) across all graded picks that day...
    daily = df.groupby('game_date')['beat'].mean().sort_index()
    # ...then trailing mean over the prior TRAIL_DAYS game-days, shifted by 1 so
    # the current day's outcomes are NOT in its own gate value (no leakage).
    trail = daily.shift(1).rolling(TRAIL_DAYS, min_periods=5).mean()
    df['scoring_env_10d'] = df['game_date'].map(trail)

    print(f"Rows with actuals: {len(df)}; with env metric: {df['scoring_env_10d'].notna().sum()}\n")

    # --- Sanity: season-level scoring env vs OVER HR (does the metric track reality?) ---
    print("=" * 78)
    print("SEASON SCORING ENV vs OVER edge3+ HR  (does env explain when OVER wins?)")
    print("=" * 78)
    print(f"  {'season':<9} {'mean(act-line)':>14} {'OVER e3+ HR':>12} {'N':>5}   {'UNDER e3+ HR':>12} {'N':>5}")
    for s, g in df.groupby('season'):
        env = g['beat'].mean()
        ov = g[(g['direction'] == 'OVER') & (g['abs_edge'] >= 3)]
        un = g[(g['direction'] == 'UNDER') & (g['abs_edge'] >= 3)]
        ov_hr = ov['correct'].mean() if len(ov) else float('nan')
        un_hr = un['correct'].mean() if len(un) else float('nan')
        print(f"  {s:<9} {env:>+14.2f} {ov_hr:>11.1%} {len(ov):>5}   {un_hr:>11.1%} {len(un):>5}")

    # --- The gate test: OVER edge3+ bucketed by the TRAILING env metric ---
    ov = df[(df['direction'] == 'OVER') & (df['abs_edge'] >= 3) & df['scoring_env_10d'].notna()].copy()
    print("\n" + "=" * 78)
    print(f"GATE TEST — OVER edge3+ by trailing {TRAIL_DAYS}d scoring env (POOLED 5 seasons)")
    print("=" * 78)
    # Threshold at 0 (league beating lines) and at a stricter +0.5.
    for thr in (0.0, 0.5):
        hot = ov[ov['scoring_env_10d'] >= thr]
        cold = ov[ov['scoring_env_10d'] < thr]
        print(f"\n  threshold env >= {thr:+.1f}:")
        print(hrline(f"OVER | HOT env (>= {thr:+.1f})", hot))
        print(hrline(f"OVER | COLD env (< {thr:+.1f})", cold))
        # per-season HR of the HOT bucket — the key cross-season check
        rows = []
        for s, gg in hot.groupby('season'):
            if len(gg) >= 10:
                rows.append(f"{s}:{gg['correct'].mean():.0%}(N={len(gg)})")
        print(f"      HOT per-season (N>=10): {'  '.join(rows) if rows else 'none'}")

    # --- Volume cost: how much OVER would the gate remove, and at what HR? ---
    print("\n" + "=" * 78)
    print("WHAT THE GATE COSTS — OVER volume removed vs kept (threshold env >= 0)")
    print("=" * 78)
    kept = ov[ov['scoring_env_10d'] >= 0]
    removed = ov[ov['scoring_env_10d'] < 0]
    print(hrline("KEPT (env>=0, OVER allowed)", kept))
    print(hrline("REMOVED (env<0, OVER blocked)", removed))
    print(f"  gate removes {len(removed)}/{len(ov)} = {len(removed)/len(ov):.0%} of OVER edge3+ picks")

    # --- Contrast with current gate (vegas_mae proxy via env? no mae here) ---
    print("\n" + "=" * 78)
    print("READOUT")
    print("=" * 78)
    pooled_hot = ov[ov['scoring_env_10d'] >= 0]
    ph = pooled_hot['correct'].mean()
    pc = ov[ov['scoring_env_10d'] < 0]['correct'].mean()
    print(f"  Pooled OVER e3+ HOT={ph:.1%}  COLD={pc:.1%}  spread={100*(ph-pc):+.1f}pp")
    print("  Gate is worth building IF: HOT clears ~{:.0%} AND is >BE in >=3 seasons,".format(REAL_BREAKEVEN))
    print("  AND COLD is clearly below it. Otherwise the calendar (2025-26), not the")
    print("  metric, is doing the work → keep 'OVER unproven' posture instead.")


if __name__ == '__main__':
    main()
