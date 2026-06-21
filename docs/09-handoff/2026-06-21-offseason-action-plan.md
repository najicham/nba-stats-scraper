# Off-season action plan (10-agent reviewed + verified)

**Date:** 2026-06-21
**Method:** `offseason-plan-review` workflow (10 agents: 6 adversarial reviewers → 3 planning lenses → 1
synthesizer), then the strong factual claims were code-verified by hand. Confidence: high.

## What the review CHANGED about the proposed plan (verified)

The reviewers read the actual code and caught that several proposed actions were no-ops or mis-scoped:

| Proposed | Reality (verified) | Action |
|---|---|---|
| "Raise MIN_EDGE toward 3.0" (Action B) | **`MIN_EDGE = 3.0` already** (`aggregator.py:327`) | DROP — no-op. True B = gate the HSE rescue lane. |
| "Fix catboost_v9 eval hardcode" (Action C) | **Already fixed Session 483** (`ml/experiments/quick_retrain.py:590-630`); CLAUDE.md is stale | DROP — keep only the `model_bb_candidates` NULL-cols item. |
| "Push the 4 prod fixes" | **Already on main** as `39133b3f` (= `dbd6619e`) | Step 1 is VERIFY, not push. |
| "Late-season collapse → verify cap lifts Mar/Apr HR" (Action A) | **Clean walk-forward shows NO collapse** (2025-26 was the *strongest* season on fresh WF) — the collapse is a *production* staleness/fleet effect | Re-scope: reproduce staleness FIRST, then test the cap; pool N≥60 across seasons. |
| "Dirty tree mostly CRLF, ~8 real" | **~105 files have real content** (1263 total; ~1158 whitespace/CRLF) | Triage real-content deliberately; renormalize the rest. |
| Assists/rebounds "data clock running" | Schedulers were **created but likely PAUSED** (off-season pause batch) — _verify_ | RESUME before NBA opening night or the Feb-2027 backtest slips a year. |

## The plan (ordered)

**1. (S) VERIFY the deployed prod fixes** — they're on main as `39133b3f` and auto-deploying. Confirm:
`gcloud builds list --region=us-west2 --project=nba-props-platform --limit=10` shows SUCCESS on the
cloudbuild-functions trigger; `gcloud functions describe phase6-export --gen2 --region=us-west2
--format='value(updateTime)'` post-dates the commit; `./bin/check-deployment-drift.sh --verbose` shows no
publishing/phase6 drift; **and re-run `bb_injection_run.py`** (the harness that surfaced the crash) clean — the
real functional proof while the system is auto-halted (don't use pick output as the health signal).

**2. (S) Repo hygiene — DONE (whitespace bucket) + triage remaining (real-content).**
DIAGNOSIS CORRECTED: the churn is **trailing-whitespace stripping, NOT CRLF** (verified: 0 carriage-return
diffs) — so the reviewer's `.gitattributes eol=lf` / `core.autocrlf` remedy was the wrong tool. ✅ Committed
`c9d7d891` "chore: strip pre-existing trailing whitespace (1158 files, content-free)" — staged ONLY the
whitespace-only bucket with two verify gates (`git diff --cached --ignore-all-space` empty; 0 real-content
files staged); aligns the tree with the trim-trailing-whitespace pre-commit hook so it stops re-dirtying.
Tree went 1263 → 105 modified.
REMAINING — triage the **105 real-content files** (pre-existing, unauthored by these sessions; left UNSTAGED
on purpose, never `git checkout .` wholesale):
- **Substantive (real decisions):** `bin/monitoring/deployment_drift_alerter.py` (+137/-8) and
  `deployment_drift_alerter_cloudrun.py` (+134/-13) — looks like real monitoring work someone built and never
  committed; `ml/experiments/quick_retrain.py` (+22) — the `--dump-eval-predictions` MQ infra (intended);
  `config/scraper_parameters.yaml` (+1). Commit-with-intent on the branch or discard deliberately.
- **Low-stakes (~75 files):** docs/* single-line deletions (`0 1` each across handoff/projects/archive) + a
  dozen `0 1` code files (scrapers/pbpstats, scrapers/utils, tests, validation/queries, shared/config) — one
  removed line each, almost certainly the same cosmetic churn; safe to discard or commit en masse.
- Also: 84 untracked (results/CSV artifacts → gitignore; review the untracked MLB CF code, no secrets).
Full list: `git diff --ignore-all-space --numstat`.

**3. (S, ship WITH the HSE floor) Gate the HSE OVER-rescue lane — the TRUE Action B.** INC-4 refuted the
`high_scoring_environment_over` "100% (3-0)" carve-out at N=133 ≈ 55% (~breakeven). Add an explicit floor to the
HSE rescue exemption (`aggregator.py:653` neighborhood, which bypasses the 6.0 OVER floor + bench/role blocks):
require **`line_value ≥ 18` AND `edge ≥ 4.0`** before HSE can bypass. Correct the falsified "100% (3-0)" comments
(lines 170, 196, 538) to cite INC-4. **Behind a config flag + user sign-off** (live `aggregator.py`); keep
`MIN_EDGE` and the 6.0 floor unchanged; shadow via `filter_counterfactual` and require CF HR ≤ 45% at N ≥ 30
before promoting. Do NOT raise global thresholds.

**4. (M) Gated re-run — measurement that sizes how much production ALREADY suppresses the HSE lane.** Lower
priority than 3 (the floor doesn't need to wait for it). Fix the recipe: pass `signal_health` **and**
`regime_context` into the `BestBetsAggregator(...)` at `simulate_best_bets.py:185` (both currently omitted),
**and** join real `ml_feature_store_v2.feature_quality_score` (not 100.0) so `quality_floor` behaves like prod.
Report only the **relative HSE-lane shrink** and the **broad-N (~208) HR** — NOT the N=12 edge5+ point estimate.
Label the `regime_state` path as production-history-derived, not counterfactual.

**5. (M) Re-scoped Action A — reproduce, then test the cap.** 5a: staleness arm on
`build_walkforward_predictions.py` — rebuild 2025-26 at cadence 7d/21d/28d/frozen-Feb28 (window=56 fixed). If HR
only collapses in the frozen/28d arms → staleness reproduced (and the foundation can see it). If even
frozen-Feb28 holds → the collapse is NOT staleness, the cap can't fix it → **STOP, downgrade A to "keep
`cap_to_pre_late_season` as insurance."** 5b (only if 5a reproduces): capped vs uncapped across ALL clean
seasons; pre-register; require Mar+Apr edge5+ **N≥60 pooled** (single-season N=24 is a non-starter), ≥3-arm
directional consistency, p<0.05 paired (McNemar). Do NOT re-run the 7d-vs-14d HR grid (settled, p=0.81).

**6. (S) Close the one real coupling bug — `model_bb_candidates`.** Schema = 45 fields; writer
(`signal_best_bets_exporter.py:1357`) leaves ~15 runtime-NULL (Task #39). Confirm which, then populate or trim.
Skip catboost_v9 (already fixed).

**7. (S, time-bound) RESUME the assists/rebounds schedulers before NBA opening night (late Oct 2026).**
The cheap, non-regret option — but only if the schedulers actually fire. Verify state; if PAUSED, resume so a
season of REB/AST lines+actuals accrues for a *real* multi-season backtest by ~Feb-Mar 2027. No model build.

## Deprioritized / deferred
- **DEFER to ~Dec 2026:** the structurally-different non-tree model (improvement #3) — its only justification
  (combo_3way) is already downgraded to 60.5% N=38, and the edge-5+-accuracy half has failed 5×. Instead lean on
  `book_disagreement` (cross-BOOK, fleet-independent) + shadow-accumulate `bp_dropped_heavy_under` /
  `book_disagree_under` until each clears forward N≥30. Revisit only behind a read-only test that the existing
  weak-diverse models extract any combo value.
- **DEFER to ~Dec 2026:** the assists/rebounds INFO-ONLY product (launch with real regular-season data).
- **DO NOT:** new market/sport build, MLB strikeout betting, GBDT/feature-set/MQ diversity grids, 7d-vs-14d
  grids, raising the OVER floor, pushing volume into edge 3-5, demoting filters on thin CF HR.

## Open questions (need a human decision)
1. Step 3 touches live `aggregator.py` — confirm config-flag + branch isolation + sign-off before it ships.
2. Assists/rebounds schedulers — PAUSED or live? **UNVERIFIED — `gcloud scheduler jobs list` hangs in this
   WSL env (timed out 90s).** The partial list that returned showed a broad off-season pause batch
   (`decay-detection`, `missing-prediction-check`, `fantasypros`, `player-movement` all PAUSED), so they're
   *plausibly* paused too — verify from a faster environment (or the GCP console) before relying on the data
   clock. This gates whether a Feb-2027 backtest is even possible, so check it well before NBA opening night.
3. `model_bb_candidates` 15 NULL cols — populate or trim?

## Governance guardrail (from the ops review)
Do all experiment work (steps 3-6) on the **feature branch**, never main — push-to-main auto-deploys
prediction-worker + phase6 CFs from HEAD (Session 388). Keep training/eval-only changes (`quick_retrain.py`,
`bin/simulate_best_bets.py`, `ml/experiments/**`) in **separate commits** from anything under
`predictions/worker/**` or `ml/signals/**`, so a model experiment can never silently ship a live-path change.
