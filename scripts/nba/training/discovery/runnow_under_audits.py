"""Two RUN_NOW audits from the 34-agent review (2026-06-23, session 3).

(1) UNDER real_sc bucket stratification — audits the LIVE `under_low_rsc` gate
    (requires real_sc>=2 at edge<5), which has been flipped on single-day noise
    (Sessions 512/514). If real_sc=1 holds ~breakeven-plus cross-season, the gate
    is over-restrictive and could relax to add UNDER volume.

(2) high_line_under marginal P/L — unit-level ROI of the 159 ORTHOGONAL picks
    (fire no existing UNDER signal) vs the 347 overlapping, per season, to settle
    the weight (shadow / 1.0 / 1.5) before any season-open add. The review flagged
    the SESSION-3 "add at 1.5" as overstated (live star_line_under is 35.3% HR N=17).

CAVEAT: real_sc here is RECONSTRUCTED from combo_tester column proxies, not the
production tag set — it is directional evidence, not a production replica. Proxies
match the overlap analysis exactly (EXISTING_UNDER_PROXIES).

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/runnow_under_audits.py
"""

import logging
import numpy as np
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset
from scripts.nba.training.discovery.combo_tester import define_signal_conditions

logging.basicConfig(level=logging.WARNING, format='%(message)s')

NOMINAL_BE = 0.524
REAL_BE = 0.535
WIN, LOSS = 0.909, -1.0  # -110 unit P/L

# Real (non-base, non-shadow) UNDER signal proxies — identical to the overlap analysis.
REAL_UNDER_PROXIES = [
    'hot_3pt_under', 'home_under', 'volatile_under',
    'bp_dropped_under', 'bp_dropped_heavy_under', 'line_drop_under',
    'book_disagree_under',
]


def roi(sub):
    if len(sub) == 0:
        return float('nan'), float('nan')
    w = sub['correct'].sum()
    pl = w * WIN + (len(sub) - w) * LOSS
    return pl / len(sub), pl


def boot_roi_ci(sub, n_boot=5000, seed=42):
    if len(sub) == 0:
        return (float('nan'), float('nan'))
    rng = np.random.RandomState(seed)
    by_date = sub.groupby('game_date')['correct'].agg(['sum', 'count'])
    s, c = by_date['sum'].values, by_date['count'].values
    nb = len(s)
    out = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.randint(0, nb, nb)
        w, n = s[idx].sum(), c[idx].sum()
        out[i] = (w * WIN + (n - w) * LOSS) / n if n else 0.0
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)))


def per_season_above(sub, thr=NOMINAL_BE, min_n=10):
    rows, above, nseas = [], 0, 0
    for s, g in sub.groupby('season'):
        hr = g['correct'].mean()
        rows.append(f"{s}:{hr:.0%}(N={len(g)})")
        if len(g) >= min_n:
            nseas += 1
            if hr > thr:
                above += 1
    return "  ".join(rows), above, nseas


def main():
    df = DiscoveryDataset(min_edge=0.0).df.copy()
    df = df[df['abs_edge'] >= 3.0]
    sigs = define_signal_conditions(df)
    avail = [s for s in REAL_UNDER_PROXIES if s in sigs]

    # Reconstruct real_sc: count of real UNDER signals firing per row
    real_sc = pd.Series(0, index=df.index)
    for s in avail:
        real_sc = real_sc + sigs[s].astype(int)
    df['real_sc'] = real_sc

    under = df[df['direction'] == 'UNDER'].copy()

    # ============ AUDIT 1: real_sc stratification ============
    print("=" * 84)
    print("AUDIT 1 — UNDER edge3+ HR & ROI by reconstructed real_sc bucket (5 seasons)")
    print(f"  proxies: {avail}")
    print("=" * 84)
    print(f"  {'bucket':<8} {'N':>5} {'HR':>7} {'ROI/u':>8} {'ROI 95% CI':>18} {'seasons>BE':>11}")
    for label, mask in [
        ('rsc=0', under['real_sc'] == 0),
        ('rsc=1', under['real_sc'] == 1),
        ('rsc=2', under['real_sc'] == 2),
        ('rsc>=3', under['real_sc'] >= 3),
        ('rsc>=2', under['real_sc'] >= 2),
    ]:
        sub = under[mask]
        hr = sub['correct'].mean() if len(sub) else float('nan')
        r, _ = roi(sub)
        lo, hi = boot_roi_ci(sub)
        _, above, nseas = per_season_above(sub)
        print(f"  {label:<8} {len(sub):>5} {hr:>6.1%} {r:>+7.1%}  [{lo:>+5.1%},{hi:>+5.1%}]  {above:>5}/{nseas}")

    print("\n  Per-season detail:")
    for label, mask in [('rsc=1', under['real_sc'] == 1), ('rsc>=2', under['real_sc'] >= 2)]:
        ps, _, _ = per_season_above(under[mask])
        print(f"    {label:<8} {ps}")
    # Edge split for rsc=1 (live gate allows solo only at edge5+)
    print("\n  rsc=1 by edge band (live under_low_rsc allows solo rsc=1 only at edge5+):")
    for lab, m in [('edge3-5', (under['real_sc'] == 1) & (under['abs_edge'] < 5)),
                   ('edge5+', (under['real_sc'] == 1) & (under['abs_edge'] >= 5))]:
        sub = under[m]
        hr = sub['correct'].mean() if len(sub) else float('nan')
        r, _ = roi(sub)
        ps, above, nseas = per_season_above(sub)
        print(f"    {lab:<8} N={len(sub):>4} HR={hr:>5.1%} ROI={r:>+6.1%} ({above}/{nseas} szn>BE) | {ps}")

    # ============ AUDIT 2: high_line_under marginal P/L ============
    print("\n" + "=" * 84)
    print("AUDIT 2 — high_line_under (UNDER line>=25): marginal P/L, orthogonal vs overlap")
    print("=" * 84)
    hlu = sigs['star_line_under']
    fires_existing = pd.Series(False, index=df.index)
    for s in avail:
        fires_existing = fires_existing | sigs[s]
    orth = df[hlu & ~fires_existing]
    over = df[hlu & fires_existing]
    for label, sub in [('ALL high_line_under', df[hlu]),
                       ('  OVERLAP (fires existing sig)', over),
                       ('  ORTHOGONAL (fires none)', orth)]:
        hr = sub['correct'].mean() if len(sub) else float('nan')
        r, pl = roi(sub)
        lo, hi = boot_roi_ci(sub)
        ps, above, nseas = per_season_above(sub)
        print(f"  {label:<32} N={len(sub):>4} HR={hr:>5.1%} ROI={r:>+6.1%} [{lo:>+5.1%},{hi:>+5.1%}] tot={pl:>+6.1f}u ({above}/{nseas}>BE)")
        print(f"      {ps}")

    print("\n  ORTHOGONAL by edge band (only edge5+ becomes a pick SOLO; edge3-5 needs a pairing):")
    for lab, m in [('orth edge3-5', hlu & ~fires_existing & (df['abs_edge'] < 5)),
                   ('orth edge5+', hlu & ~fires_existing & (df['abs_edge'] >= 5))]:
        sub = df[m]
        hr = sub['correct'].mean() if len(sub) else float('nan')
        r, _ = roi(sub)
        ps, above, nseas = per_season_above(sub)
        print(f"    {lab:<14} N={len(sub):>4} HR={hr:>5.1%} ROI={r:>+6.1%} ({above}/{nseas}>BE) | {ps}")

    print("\n  READOUT: weight justified only if ORTHOGONAL ROI is positive cross-season")
    print("  (>=3/5 above breakeven, bootstrap ROI CI excludes 0). Else shadow/1.0, not 1.5.")


if __name__ == '__main__':
    main()
