# Next-session pointer — NBA off-season is converged; one open decision

**Date:** 2026-06-27 · **State:** MLB review CONCLUDED + committed (see
`2026-06-27-2-mlb-full-review-FINDINGS.md`). NBA off-season research is **converged — "do little,
add no features."** Nothing here is urgent.

## The one open decision — RESOLVED 2026-06-27 (merged)

**`offseason-eval-foundation-2026-06` is MERGED to `main` and pushed** (merge commit `14c01583`;
`origin/main` == local `main` == `4ab89d5f`). Verified `git merge-base --is-ancestor` — the branch
head is a full ancestor of main; commit `99941b41` is present in main. Nothing left to merge.

What landed (all inert/reversible, zero live impact while the off-season halt is active):
- **Staged OVER-layer demotion** (commit `99941b41`, in `ml/signals/aggregator.py` `SHADOW_SIGNALS`):
  `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over`, `b2b_boost_over`.
  Weights retained as restore targets. 5-season WF re-grade: all 5 FAIL the ≥3/5-season breakeven gate
  (edge was the 2025-26 anomaly). Each must EARN weight back on live 2026-27 (N≥30 HR≥58%) via
  `over_decay_watch.py`.
- **`b2b_fatigue_under` reinstated in SHADOW** (`aggregator.py:132`; excluded from real_sc, NOT in
  `UNDER_SIGNAL_WEIGHTS`): ZERO pick impact until promoted at season open after live N≥30 HR≥58%.

No further action — the merge stages these changes; it changes nothing live (no NBA picks generated in
the off-season). The remaining sign-off items are the season-open *promotions* below, not the merge.

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
