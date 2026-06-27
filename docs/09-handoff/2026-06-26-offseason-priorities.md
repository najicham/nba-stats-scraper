# Off-season priorities — prioritized plan (2026-06-26)

Synthesis of a 5-agent whole-system review + this session's verifications. NBA is off-season
(2026-27 opens ~Oct); MLB pitcher-K betting is concluded (no edge, CLV measured negative) and
mothballed (28 scheduler jobs paused, reversible). Standing verdict: **improve the NBA core,
don't expand** ([[expand-vs-improve-2026-06]]).

## Two decisive findings from this session (resolve the plan)

1. **NO live production training-leakage bugs.** All three claims (random train/val split,
   no-holdout governance, V12 feature-augmentation window) describe pre-2026-05-20 code, fixed in
   commit `60279b20` (temporal 85/15 split, held-out 28-day eval, CI-aware gates, + regression
   test `tests/ml/unit/test_v12_augmentation_leakage.py`). Production retrain is
   `orchestration/cloud_functions/weekly_retrain/main.py` (self-contained). **The "research has
   converged / features are done" story holds → no October firefight.**
2. **NBA feature pipeline is CLEAN of the MLB same-season-snapshot leak class.** Every
   `season_year =` join is paired with `game_date < analysis_date`; source `*_game_summary`
   tables are point-in-time, not snapshots. **The "NBA leak audit" task is DROPPED** (the MLB
   project's flagged follow-on does not apply here).

⇒ The real off-season work is the **strategic UNDER-rebalance**, not a bug hunt.

## TIER 0 — Hygiene (DONE this session except the merge)

- [x] Versioned the deployed-but-unversioned MLB CF source + CLV artifacts (commit `1ef205a3`).
- [x] Committed the early-hook-UNDER finding doc.
- [x] Confirmed the season-start fix (`986d9c5c`) is already merged to main via PR #7 — not at risk.
- [x] Fixed stale CLAUDE.md (Task #35 orphans gone, `catboost_v9` workaround removed,
      quality_scorer mismatch resolved, "Edge 5+ money zone" → UNDER-only).
- [ ] **DECISION PENDING: merge branch `offseason-eval-foundation-2026-06` → main.** All commits
      are additive (research scripts, monitoring harness, docs, mothballed MLB CF source). Merging
      pushes to main = auto-deploy; the new MLB CF dirs would redeploy (no-op, schedulers paused).
      Low risk but a conscious step — left for owner go-ahead.

## TIER 2 — Off-season prep (stage now; flip at open; needs sign-off)

| Item | What | Effort | When |
|------|------|--------|------|
| UNDER-rebalance (highest leverage) | System is directionally overfit to the 2025-26 soft market. Build the OVER scoring-environment gate; keep OVER high-floor/shadow until 2026-27 confirms; treat UNDER as the engine. Code now, A/B at open. | M | stage now |
| OVER signal-decay playbook | `over_decay_watch.py` exists (now committed). Re-grade `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over` by Dec 2026; demote if not >breakeven at N≥30. | S | stage now / run Dec |
| Ops readiness | Verify `weekly-retrain` CF fires year-round / from Oct; scheduler month-ranges include Oct; assists/rebounds data clock still firing (cheap insurance, no model build). | S | before Oct |

## TIER 3 — Season-open exec (Oct+, gated on LIVE data — do NOT flip early)

- Promote `b2b_fatigue_under` shadow→active after live N≥30 @ HR≥58% (sign-off).
- Deploy the CLV live de-risk rule ("drop a pick if by tip the close moved ≥0.5 against it")
  after 2026-27 true-close data accrues (N≥100).
- Add `high_line_under` at weight 1.0 as a pairing signal (after overlap check).
- Run the 7d→14d retrain-cadence A/B (adopt-eligible on cost; edge5+ inconclusive; sign-off).
- HSE rescue floor: off → observe → active (gate on CF HR ≤45%, N≥30).

## DROP / DON'T DO (settled)

NBA leak audit (clean) · GBDT/feature-set/MQ diversity grids (clones, dead end) · new
sports / MLB / batter markets (settled skip) · relax the OVER edge-6.0 floor or
`cap_to_pre_late_season` · build assists/rebounds models before Feb 2027 · Task #39
`model_bb_candidates` 15-NULL provenance cols (cosmetic, defer).

## Loose ends (low priority)

- ~42 untracked historical docs (handoffs back to 2026-04-18) — commit or run `cleanup-projects`.
- `check-deployment-drift.sh` timed out at 90s — re-run with 300s+ for a definitive NBA drift read (off-season, low stakes).
- MLB worker full retirement (re-source the tonight-slate line from a scraper table) — only if you ever want to delete the worker; not needed for cost (idle = ~$0).
