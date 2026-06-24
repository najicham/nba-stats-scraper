"""Shadow-signal backlog — formal 5-season gate (2026-06-24).

The disciplined "test more angles on previous seasons": ~32 shadow signals are
accumulating prod data but most were NEVER run through the formal discovery gate.
slow_pace_under (just gated → PASS) proved there are gems in the backlog. Here we gate
every shadow signal that maps to the cross-season-testable surface (62 cols; see
coverage_audit.py) using REAL measured scales (NOT combo_tester's predicates — those are
mis-scaled for this cache: opponent_pace>=0.75 vs raw 91-111, slope -0.03..-0.01 vs ±1.6,
line_std>=1.0 vs max 0.58). BH-FDR across the family.

GATE = BH-FDR significant AND cross-season pass (>=3/5 seasons above baseline, CV<0.15)
       AND pooled HR > real breakeven (53.5%).

NOT testable on the cache (need prod feeds / single-season-only) → reported, not gated:
  projection_consensus_under, sharp_money_under, dvp_favorable_over, quantile_floor_over,
  sharp_book_lean_over, sharp_consensus_under, starter_away_overtrend_under (starter
  look-ahead), star_favorite_under (spread is 2025-26-only), day_of_week_under (ill-defined).
Already gated (skip): slow_pace_under (PASS), b2b_fatigue_under (PASS), star_line_under.

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/shadow_backlog_gate.py
"""

import logging
import numpy as np
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.stats_utils import (
    BASELINE_HR, compute_hypothesis_stats, benjamini_hochberg,
)

logging.basicConfig(level=logging.WARNING, format='%(message)s')
REAL_BE = 0.535


def predicates(df):
    """Reconstruct each testable shadow signal from REAL measured column scales."""
    U = df['direction'] == 'UNDER'
    O = df['direction'] == 'OVER'
    p = {}
    # --- UNDER shadow concepts ---
    p['over_streak_reversion_under'] = U & (df['prop_over_streak'] >= 2)
    p['mean_reversion_under']        = U & (df['deviation_from_avg_last3'] >= 0.5)   # scored >avg recently
    p['downtrend_under']             = U & (df['scoring_trend_slope'] <= -0.5)       # real downtrend
    p['ft_anomaly_under']            = U & (df['fta_cv_last_10'] >= 0.5) & (df['fta_avg_last_10'] >= 5)
    p['extended_rest_under']         = U & (df['days_rest'] >= 3)                    # = rested (expect fail)
    p['book_disagree_under']         = U & (df['line_std'] >= 0.48)                  # p75 real-scale dispersion
    # --- OVER shadow concepts ---
    p['usage_surge_over']            = O & ((df['usage_rate_last_5'] - df['usage_rate']) >= 3.0)
    p['career_matchup_over']         = O & (df['avg_pts_vs_opponent'] >= df['points_avg_season'] + 2) & (df['games_vs_opponent'] >= 3)
    p['consistent_scorer_over']      = O & (df['points_std_last_10'] <= 4.0)         # low variance
    p['over_trend_over']             = O & (df['over_rate_last_10'] >= 0.7)
    p['minutes_load_over']           = O & (df['minutes_load_last_7d'] >= 100)       # p75 load
    return p


def main():
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df = df[df['abs_edge'] >= 3.0].copy()
    p = predicates(df)

    print("=" * 96)
    print("SHADOW-BACKLOG FORMAL GATE — edge3+, 5 seasons, real-scale predicates")
    print(f"baseline={BASELINE_HR}  real_BE={REAL_BE}")
    print("=" * 96)

    results = []
    for name, mask in p.items():
        sub = df[mask]
        st = compute_hypothesis_stats(sub, baseline=BASELINE_HR)
        if st is None:
            print(f"\n{name:<30} N={len(sub)} < 100 — INSUFFICIENT")
            continue
        results.append((name, st, sub))

    # BH-FDR across the family
    pvals = np.array([st['p_value'] for _, st, _ in results])
    rej, adj = benjamini_hochberg(pvals, alpha=0.05)

    print(f"\n  {'signal':<30} {'dir':>5} {'N':>5} {'HR':>6} {'eff':>6} {'adj_p':>8} {'xseason':>8} {'VERDICT':>8}")
    print("  " + "-" * 92)
    rows = []
    for (name, st, sub), r, a in sorted(zip(results, rej, adj), key=lambda z: -z[0][1]['hr']):
        c = st['consistency']
        d = sub['direction'].mode().iloc[0]
        gate = bool(r) and c['pass'] and st['hr'] > REAL_BE
        verdict = 'PASS' if gate else ('~marginal' if (st['hr'] > REAL_BE and c['seasons_consistent'] >= 3) else 'FAIL')
        rows.append((name, st, sub, gate, d))
        print(f"  {name:<30} {d:>5} {st['total_n']:>5} {st['hr']:>5.1%} {st['effect_pp']:>+5.1f} "
              f"{a:>8.4f} {c['seasons_consistent']}/{c['seasons_valid']}      {verdict:>8}")

    print("\n  Per-season detail (signals at/above real_BE only):")
    for name, st, sub, gate, d in rows:
        if st['hr'] > REAL_BE:
            ps = "  ".join(f"{s}:{v['hr']:.0%}(N={v['n']})" for s, v in st['consistency'].get('per_season', {}).items())
            print(f"    {name:<30} {ps}")

    passes = [name for name, st, sub, gate, d in rows if gate]
    print("\n" + "=" * 96)
    print("RESULT")
    print("=" * 96)
    if passes:
        print(f"  PASS (promote-candidates, need live N>=30 + sign-off): {passes}")
    else:
        print("  No NEW shadow signal clears the full gate (FDR-sig + 3/5 cross-season + HR>53.5%).")
    print("  NOT testable on cache (prod feeds / single-season): projection_consensus_under,")
    print("  sharp_money_under, dvp_favorable_over, quantile_floor_over, sharp_book_lean_over,")
    print("  sharp_consensus_under, starter_away_overtrend_under, star_favorite_under, day_of_week_under.")


if __name__ == '__main__':
    main()
