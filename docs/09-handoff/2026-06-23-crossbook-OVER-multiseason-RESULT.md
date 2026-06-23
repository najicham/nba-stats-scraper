# RESULT: Cross-book OVER signals are 2025-26-only artifacts (multi-season walk-forward)

**Date:** 2026-06-23 · **Status:** Closed — the "cross-book OVER test left on the table" resolves AGAINST a
durable OVER edge. **Scope:** 5-season walk-forward BB-eligible population (edge ≥ 3), N small per cell —
treat as a screening result strong enough to flag signals as recency-dependent, not to delete them.

## Motivation
The 24-agent review (2026-06-22) partially refuted "OVER feeds are data-dead pre-2025": BettingPros multibook
features (`line_std`, `book_count`, `line_movement`) have FULL pre-2025 *coverage* (non-null), so cross-book
OVER signals were claimed "historically testable" — a test left on the table. This ran it.

## Method
`scripts/nba/training/discovery/data_loader.py::DiscoveryDataset(min_edge=3.0)` — walk-forward CatBoost
V12_NOVEG predictions joined to `results/bb_simulator/bettingpros_multibook.csv` (87,566 rows, 2021-10→2026-04)
on (game_date, player_lookup). OVER edge≥3 population = 822 picks across 5 seasons. HR by season × threshold,
Wilson 95% CIs, Fisher exact for 2025-26 vs prior.

## Key finding: "coverage" ≠ "signal-bearing variance"
`line_std` is non-null pre-2025 but its **median is 0.000 in 2021/2022/2023** (5-book regime — books agree or
lines too quantized to disperse). `line_std ≥ 1.5` barely fires pre-2024. So the premise ("testable because
non-null") is technically true but practically empty for the disagreement signals.

## Results (OVER, edge ≥ 3)

**`line_rising_over` basis — `line_movement ≥ 0.5` → OVER:**
| Era | N | HR | Wilson 95% |
|---|---|---|---|
| 2021-24 (low-book) | 80 | 52.5% | [41.7, 63.1] |
| 2024-25 alone | 30 | 53.3% | [36.1, 69.8] |
| **2025-26 alone** | 44 | **81.8%** | [68.0, 90.5] |
| Pooled 5-season | 154 | 61.0% | [53.2, 68.4] |

**2025-26 (81.8%) vs all prior 2021-25 (52.7%): Fisher p = 0.001.** Breakeven in every prior season; the edge
is one-season. The signal's headline "96.6% HR (N=30, Jan+Feb 2026)" is the same 2025-26 small-N artifact.

**`book_disagree_over` basis — `line_std ≥ 1.0` → OVER:** pooled 56.1% [41.0, 70.1] N=41; 2025-26 vs prior
Fisher **p = 0.726** (no edge in any era). At `line_std ≥ 1.5`: pooled 54.2% [35.1, 72.1] N=24.

**For contrast — `line_drifted_down_under` basis (`-0.5 ≤ line_movement < -0.1` → UNDER):** pooled 56.8%
[47.5, 65.6] N=111; more consistent in recent seasons (2023-24 57.8%, 2024-25 62.1%, 2025-26 51.7%). Modest,
the most cross-season-stable of the three, consistent with its ACTIVE status.

## Conclusion
- **No cross-book OVER signal is a robust cross-season edge.** Both `line_rising_over` and `book_disagree_over`
  derive their apparent strength almost entirely from 2025-26 (p=0.001 and n.s. respectively). Pre-2024 they
  are at or below breakeven.
- This **generalizes** the "+13.7pp filter lift is 2025-26-only" finding down to the OVER *signal* layer: the
  OVER side's strength is a regime-recency artifact — which is mechanically why OVER collapsed Jan→Mar 2026.
- **The system's posture is correct:** high OVER floor (6.0), edge-based auto-halt, no chasing OVER signals.

## Action: flag for season-resume re-validation (NOT a deploy change now)
`line_rising_over` (weight 3.0, rescue) and `book_disagree_over` (weight 3.0) are over-weighted on one-season
evidence. When 2026-27 opens they are prime decay candidates. Do NOT delete (off-season, no live data), but:
- Add to the season-resume watch list: re-grade both by ~Dec 2026; if 2026-27 HR < 58% at N≥30, demote weight.
- `line_drifted_down_under` (UNDER) is the more defensible cross-book signal; keep ACTIVE.
- Recorded in `memory/offseason-review-corrections-2026-06.md` and the season-resume runbook.
