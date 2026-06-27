"""WORTH_TRYING UNDER tests through the formal discovery gate (2026-06-23, session 3).

Sanctioned by the 34-agent review. Runs the cross-season-validatable candidates
through the project's mandatory gate (binomial vs baseline + block-bootstrap CI +
cross-season consistency + BH-FDR across the family).

Tests:
  1. slow_pace_under  — opponent_pace <= 99 (raw), UNDER, edge3+. In shadow at a
     claimed 56.6% HR (N=777) but NEVER formally gated.
  2. b2b x high_line x home 3-way — days_rest==1 & line>=25 & is_home, UNDER,
     edge3+. Synergy only if joint HR > max(individual b2b 63.2 / high_line 59.9 /
     home ~63.9). Review predicted INCONCLUSIVE on thin N.

DROPPED: stars_out>=2 UNDER — star_teammates_out is 0% populated 2021-25, 100% only
2025-26 (same single-season artifact as is_b2b). Cannot be cross-season validated.

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/runnow_worth_trying.py
"""

import logging
import numpy as np

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.stats_utils import (
    BASELINE_HR, compute_hypothesis_stats, benjamini_hochberg,
)

logging.basicConfig(level=logging.WARNING, format='%(message)s')
NOMINAL_BE, REAL_BE = 0.524, 0.535


def show(name, sub, family):
    st = compute_hypothesis_stats(sub, baseline=BASELINE_HR)
    if st is None:
        print(f"\n### {name}: N={len(sub)} < MIN_N_TOTAL(100) — INSUFFICIENT, fails gate on volume")
        return None
    c = st['consistency']
    print(f"\n### {name}")
    print(f"  N={st['total_n']}  HR={st['hr']:.1%}  ({'>BE' if st['hr']>REAL_BE else '<BE'})  effect={st['effect_pp']:+.1f}pp  p={st['p_value']}")
    print(f"  bootstrap CI=[{st['bootstrap_ci_lo']:.3f},{st['bootstrap_ci_hi']:.3f}]  excludes_baseline={st['ci_excludes_baseline']}")
    print(f"  cross-season: {c['seasons_consistent']}/{c['seasons_valid']} above baseline, CV={c.get('cv')}, GATE_PASS={c['pass']}")
    ps = "  ".join(f"{s}:{v['hr']:.0%}(N={v['n']})" for s, v in c.get('per_season', {}).items())
    print(f"  {ps}")
    family.append((name, st))
    return st


def main():
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df = df[df['abs_edge'] >= 3.0]
    U = df['direction'] == 'UNDER'
    family = []

    print("=" * 80)
    print("FORMAL GATE — WORTH_TRYING UNDER candidates (edge3+, 5 seasons)")
    print(f"baseline={BASELINE_HR}  nominal_BE={NOMINAL_BE}  real_BE={REAL_BE}")
    print("=" * 80)

    # --- Test 1: slow_pace_under (+ stricter variant) ---
    show('slow_pace_under (opp_pace<=99)', df[U & (df['opponent_pace'] <= 99)], family)
    show('slow_pace_under (opp_pace<=98, strict)', df[U & (df['opponent_pace'] <= 98)], family)

    # --- Test 3: b2b x high_line x home 3-way synergy ---
    b2b = U & (df['days_rest'] == 1)
    high = U & (df['line'] >= 25)
    home = U & (df['is_home'] == 1)
    joint = b2b & high & home
    print("\n" + "-" * 80)
    print("3-WAY SYNERGY: b2b(days_rest=1) x high_line(>=25) x home")
    for nm, m in [('b2b_under', b2b), ('high_line_under', high), ('home_under', home)]:
        sub = df[m]
        print(f"  individual {nm:<16} N={len(sub):>4} HR={sub['correct'].mean():.1%}")
    st_j = show('b2b x high_line x home (joint)', df[joint], family)
    if st_j:
        indiv_max = max(df[b2b]['correct'].mean(), df[high]['correct'].mean(), df[home]['correct'].mean())
        print(f"  >>> joint HR {st_j['hr']:.1%} vs max-individual {indiv_max:.1%} = synergy {100*(st_j['hr']-indiv_max):+.1f}pp")

    # --- BH-FDR across the family ---
    if family:
        pvals = np.array([st['p_value'] for _, st in family])
        rej, adj = benjamini_hochberg(pvals, alpha=0.05)
        print("\n" + "=" * 80)
        print("BH-FDR ACROSS FAMILY (alpha=0.05)")
        print("=" * 80)
        for (name, st), r, a in zip(family, rej, adj):
            verdict = 'PASS' if (r and st['consistency']['pass'] and st['hr'] > REAL_BE) else 'FAIL'
            print(f"  {verdict}  {name:<42} adj_p={a:.4f}  fdr_sig={bool(r)}  xseason_pass={st['consistency']['pass']}")
        print("\nGATE = fdr_significant AND cross-season-pass (>=3/5, CV<0.15) AND HR>real_BE.")


if __name__ == '__main__':
    main()
