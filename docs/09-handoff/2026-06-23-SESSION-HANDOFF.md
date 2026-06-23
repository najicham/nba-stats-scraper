# Session handoff — off-season eval foundation COMPLETE + merged to main

**Date:** 2026-06-23
**Branch:** `offseason-eval-foundation-2026-06` (MERGED to `main` via PR #7, merge commit `63973538`)
**Status:** Off-season action plan fully closed. Branch landed to main, full redeploy verified green.
**Nothing pending that needs continuity.** Remaining items are all gated/deferred (see below).

---

## TL;DR for the next session
Everything from the off-season improve-the-core engagement is DONE and DEPLOYED. The live betting path is
unchanged in behavior (the one behavior-affecting piece — the HSE floor — shipped **default OFF**). Start
any new discrete task fresh; this doc + `memory/MEMORY.md` carry full context. **gcloud AND the Python BQ
client both work in this env** (gotcha update — see below). Local gcloud default project is wrong
(`dmhr-platform`): always pass `--project=nba-props-platform`.

## Strategic frame (unchanged)
**IMPROVE the NBA points engine; do NOT expand** to new markets/sports (52-agent verdict). Pipeline is
points-locked. Keep the REB/AST data clock as a cheap option only. Refs:
`docs/09-handoff/2026-06-20-expand-vs-improve-strategy.md`, `memory/expand-vs-improve-2026-06.md`.

## What shipped to main (`63973538`, 20/20 Cloud Builds SUCCESS)
- **`ml/signals/supplemental_data.py`** — FIX: dynamic `@season_start` (was 7× hardcoded `'2025-10-22'`).
  Prod-safe (2025-26 → 2025-10-21, no games between); also fixes a latent 2026-27 bug + enabled
  multi-season eval. LIVE.
- **`ml/signals/aggregator.py`** — HSE OVER-rescue floor, **3-state `HSE_RESCUE_FLOOR_MODE` (default `off`
  → ZERO behavior change)**. `observe` records `hse_rescue_floor` to `best_bets_filtered_picks` (CF data)
  without blocking; `active` blocks (line<18 or edge<4 HSE picks fall through to the 6.0 floor + bench/role).
  6 falsified "100% (3-0)" HSE comments corrected. `HSE_RESCUE_FLOOR_MODE` is **NOT set in prod** → off.
- Eval tooling (`bin/simulate_best_bets.py`, `scripts/nba/training/discovery/*`), docs, the 1,158-file
  whitespace strip (caused the full-fleet redeploy), and monitoring (`deployment_drift_alerter`).

## Findings this engagement (all documented in docs/09-handoff/)
1. **Late-season collapse is NOT model staleness.** No retrain-cadence arm (7/21/28/frozen-Feb28)
   reproduces the prod Mar collapse on clean walk-forward; **`cap_to_pre_late_season` is REFUTED as a
   profit lever** (≈ frozen arm = worst; fresh-incl-March is best). Cadence ≤28d ≈ weekly.
   → `2026-06-21-STEP5-staleness-RESULT.md`, `memory/staleness-arm-2026-06.md`.
2. **The HSE "100% (3-0)" carve-out is an N=3 artifact** — ~55% at N=133. Production regime gating only
   suppresses the lane ~32% (all in Mar/Apr); the targeted floor is the right tool. Floor in-sim: HSE lane
   133→0, surviving OVER 5@100%. → `2026-06-21-STEP4-gated-rerun-RESULT.md`.
3. **"+13.7pp filter lift" is 2025-26-ONLY.** Multi-season BB-vs-raw on 2023-24/2024-25 degenerates to an
   all-UNDER slate because OVER-side feeds (pace/projections/sharp/HSE) are data-dead pre-2025. Treat the
   lift as single-season-supported; robust number is INC-4's +6.7pp broad-N. The testable low-edge UNDER
   lane does NOT beat raw (corroborates the sub-edge-3-UNDER vig trap).
   → `2026-06-22-multiseason-BB-extension-RESULT.md`.
4. **`model_bb_candidates`** has only 33 rows ever (Mar 9–Apr 7); 17 NULL cols are upstream propagation
   gaps (some conditional). Low value to fix until it accumulates at volume next season.

## Operational state changes made
- **REB/AST data-clock schedulers RESUMED** (2026-06-22, all 4 ENABLED). Off-season no-ops until NBA
  opening night; the point is a full 2026-27 season of lines+actuals for the gated Feb-2027 backtest.
- **STEP 1 deploy verify** done (prod crash/DvP fixes `39133b3f` were live; now superseded by `63973538`).

## What's NEXT — all gated/deferred, none urgent
- **HSE floor promotion** (needs sign-off; data-gated): merge already done → set
  `HSE_RESCUE_FLOOR_MODE=observe` on `prediction-worker` (+ coordinator) via `--update-env-vars` (NEVER
  `--set-env-vars`). Accrues `hse_rescue_floor` CF rows **only once NBA games resume (~late Oct 2026)**.
  Promote to `active` only at CF HR ≤ 45%, N ≥ 30. Runbook: `2026-06-21-gcloud-session-runbook.md`.
- **Structurally-different non-tree model** (~Dec 2026) — the only real fleet-diversity lever left; lean
  on `book_disagreement` (cross-book, fleet-independent) meanwhile. DO NOT retry GBDT/feature-set/MQ grids.
- **REB/AST info-only product + multi-season backtest** — Feb-Mar 2027, after a full season of data.
- **`model_bb_candidates` NULL cols** — populate/trim when it matters (next season volume).

## Guardrails / DON'Ts (carry forward)
- Push-to-main auto-deploys ALL services from HEAD. Keep eval-only commits separate from `ml/signals/**`
  and `predictions/worker/**`. NEVER `git add -A` (pre-existing dirty tree: ~36 modified + ~80 untracked,
  unauthored — leave it).
- DON'T: new market/sport, MLB strikeout betting, GBDT/feature-set/MQ diversity grids, 7d-vs-14d grids,
  raise the OVER floor, push volume into edge 3-5, demote filters on thin CF HR, enable the HSE floor blind.
- Real breakeven ≈ 53.5% (real odds, not 52.4%). edge5+ is the money zone both directions.

## Env gotchas (updated)
- **gcloud works** this env (the earlier "gcloud hangs" was intermittent); `scheduler/builds list` are
  slow (~1-2 min) — use `timeout` + per-job `describe`/`resume`. Always `--project=nba-props-platform`.
- **bq CLI hangs** — use the Python BQ client (`bigquery.Client(project='nba-props-platform')`).
- `results/` caches are gitignored; rebuild via `build_walkforward_predictions.py` then
  `build_bb_simulator_cache.py`. Scratch table `nba_predictions.walkforward_sim_predictions` at
  `feature_quality_score=100` (sim-only).
</content>
