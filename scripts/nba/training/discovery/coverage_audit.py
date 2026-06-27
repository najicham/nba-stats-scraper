"""Coverage audit — draw the boundary of what's cross-season testable (2026-06-24).

We kept discovering single-season-coverage holes one at a time (is_b2b, star_teammates_out,
implied_team_total/game_total were all 0% pre-2025, 100% only 2025-26). This maps EVERY
column's per-season fill rate ONCE, so a new session knows up front what can be cross-season
validated vs what is a 2025-26-only trap (testing those single-season → the overfit mistake
that already burned us on OVER signals).

A column counts as INFORMATIVE in a season only if it is BOTH filled (notna rate >=
FILL_THRESHOLD) AND non-degenerate (not >99.5% a single value). The 2nd condition catches
the worst trap: is_b2b / back_to_back are 100% non-null but all-False pre-2025 (look fine by
null-rate, carry zero signal) — exactly the artifact that got b2b_under wrongly removed.

Classification per column (by # of seasons it is INFORMATIVE):
  CROSS_SEASON   informative in >=4 of 5 seasons       -> testable through the formal gate
  RECENT_ONLY    informative in 2025-26 but NOT early   -> TRAP class (single-season)
  PARTIAL        spotty / mixed                         -> usable only with care
  SPARSE         informative in <2 seasons             -> not testable

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/coverage_audit.py
"""

import logging
import pandas as pd

from scripts.nba.training.discovery.data_loader import DiscoveryDataset

logging.basicConfig(level=logging.WARNING, format='%(message)s')

FILL_THRESHOLD = 0.60          # notna rate to count a column "filled" for a season
SEASONS = ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26']
EARLY = ['2021-22', '2022-23', '2023-24']   # pre-2025 seasons


def classify(filled):
    """filled: dict season -> bool."""
    n = sum(filled.values())
    early_filled = sum(filled[s] for s in EARLY if s in filled)
    recent_filled = filled.get('2025-26', False)
    if n >= 4:
        return 'CROSS_SEASON'
    if recent_filled and early_filled == 0:
        return 'RECENT_ONLY'
    if n >= 2:
        return 'PARTIAL'
    return 'SPARSE'


def main():
    df = DiscoveryDataset(min_edge=0.0).df
    rows = []
    for c in df.columns:
        per = {}
        filled = {}
        degenerate = []
        for s in SEASONS:
            g = df[df['season'] == s]
            col = g[c].dropna()
            rate = len(col) / len(g) if len(g) else 0.0
            per[s] = rate
            # informative = filled AND not near-constant (>99.5% a single value)
            modal_frac = (col.value_counts(normalize=True).iloc[0]
                          if len(col) else 1.0)
            is_filled = rate >= FILL_THRESHOLD
            is_live = is_filled and modal_frac < 0.995
            filled[s] = is_live
            if is_filled and not is_live:
                degenerate.append(s[2:])    # filled-but-degenerate that season
        rows.append({'col': c, 'klass': classify(filled),
                     'degen': ",".join(degenerate),
                     **{s: per[s] for s in SEASONS}})
    res = pd.DataFrame(rows)

    order = {'CROSS_SEASON': 0, 'PARTIAL': 1, 'RECENT_ONLY': 2, 'SPARSE': 3}
    res['_o'] = res['klass'].map(order)
    res = res.sort_values(['_o', 'col'])

    counts = res['klass'].value_counts()
    print("=" * 92)
    print(f"COVERAGE AUDIT — {len(df)} rows, {len(df.columns)} columns, fill threshold {FILL_THRESHOLD:.0%}")
    print("=" * 92)
    for k in ['CROSS_SEASON', 'PARTIAL', 'RECENT_ONLY', 'SPARSE']:
        print(f"  {k:<14} {counts.get(k, 0)}")

    def dump(klass, note):
        sub = res[res['klass'] == klass]
        print(f"\n{'─' * 92}\n{klass} ({len(sub)}) — {note}\n{'─' * 92}")
        print(f"  {'column':<30} " + " ".join(f"{s[2:]:>6}" for s in SEASONS) + "  degenerate-seasons")
        for _, r in sub.iterrows():
            d = f"  ⚠️ all-constant: {r['degen']}" if r['degen'] else ""
            print(f"  {r['col']:<30} " + " ".join(f"{r[s]:>6.0%}" for s in SEASONS) + d)

    # The two that matter most for planning
    dump('RECENT_ONLY', "2025-26-only TRAP class — do NOT cross-season test; need backfill")
    dump('PARTIAL', "usable with care (note which seasons drop out)")
    dump('CROSS_SEASON', "testable through the formal 5-season gate")
    if (res['klass'] == 'SPARSE').any():
        dump('SPARSE', "not testable")

    print("\n" + "=" * 92)
    print("TAKEAWAYS")
    print("=" * 92)
    recent = res[res['klass'] == 'RECENT_ONLY']['col'].tolist()
    degen_any = res[res['degen'] != '']['col'].tolist()
    print(f"  • {len(recent)} RECENT_ONLY columns can ONLY be measured on 2025-26 (the anomaly")
    print(f"    season). Any 'feature' built on these is a single-season result — the overfit trap:")
    print(f"      {recent}")
    print(f"  • {len(degen_any)} columns are filled-but-DEGENERATE in some seasons (present but")
    print(f"    near-constant → zero signal; the null-rate looks fine but the column is dead):")
    print(f"      {degen_any}")
    print(f"  • {counts.get('CROSS_SEASON', 0)} columns are genuinely cross-season testable — that")
    print(f"    is the real surface for any new formal-gate work (e.g. the shadow-signal backlog).")
    print(f"  • To unlock the trap columns: backfill cache enrichment for 2021-25, or query prod BQ.")


if __name__ == '__main__':
    main()
