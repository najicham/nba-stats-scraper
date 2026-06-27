# Next-session pointer — NBA off-season is converged; one open decision

**Date:** 2026-06-27 · **State:** MLB review CONCLUDED + committed (see
`2026-06-27-2-mlb-full-review-FINDINGS.md`). NBA off-season research is **converged — "do little,
add no features."** Nothing here is urgent.

## The one open decision (5-min, decision-driven — not research)

**Merge the `offseason-eval-foundation-2026-06` branch to `main`, or leave it parked until 2026-27 open?**

That branch carries committed-not-pushed-to-main work, all inert/reversible:
- **Staged OVER-layer demotion** (commit `99941b41`): `fast_pace_over`, `cold_3pt_over`,
  `line_rising_over`, `book_disagree_over`, `b2b_boost_over` → `SHADOW_SIGNALS`. Weights retained as
  restore targets. 5-season WF re-grade: all 5 FAIL the ≥3/5-season breakeven gate (edge was the
  2025-26 anomaly). Each must EARN weight back on live 2026-27 (N≥30 HR≥58%) via `over_decay_watch.py`.
- **`b2b_fatigue_under` reinstated in SHADOW** (excluded from real_sc, not in `UNDER_SIGNAL_WEIGHTS`):
  ZERO pick impact until promoted at season open after live N≥30 HR≥58%.

Both are off-season-safe to merge (inert until season open). The only reason to wait is if you want a
final eyeball before it's on `main`. Recommendation: merge when ready — it just stages the changes; it
changes nothing live (no NBA picks generated in the off-season).

## Everything else = season-open exec (do NOT pre-run)

- UNDER-rebalance (rebuild `b2b_under`, `high_line_under` as a 1.0 pairing signal — NOT rescue).
- OVER decay-watch: re-grade all demoted OVER signals by ~Dec 2026; demote permanently if not
  >breakeven at N≥30.
- `under_low_rsc≥2` gate confirmed keep.
- CLV live de-risk rule ("drop a pick if the close moved ≥0.5 against it") — confirm cross-season on
  live 2026-27.

See `MEMORY.md` Strategic Direction for the full converged picture and the per-finding detail docs.

## MLB — closed, do not reopen

Quintuple-confirmed no-edge, externally corroborated. Stays halted (info product only). All §4
frontiers closed (incl. Pinnacle — not on our Odds API plan + mechanism refuted). Reopening requires a
named §4 frontier materializing, a deliberate separate decision — not more backtesting.
