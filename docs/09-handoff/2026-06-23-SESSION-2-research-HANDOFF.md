# Session handoff — off-season review + 5-season research + b2b reinstatement

**Date:** 2026-06-23 (second session of the day; follows `2026-06-23-SESSION-HANDOFF.md`)
**Branch:** `offseason-eval-foundation-2026-06` — **11 commits ahead of `origin/main`, pushed, NOT merged.**
**Deploy state: NOTHING IS DEPLOYED.** Auto-deploy fires only on push to `main`; this is a feature branch.

---

## TL;DR for the next session
A 24-agent review + a deep 5-season walk-forward research arc produced **one real prod bug fix**, **a set of
core-framing corrections**, and **one validated, shadow-wired signal reinstatement (`b2b_fatigue_under`)**.
The through-line: **the OVER side is structurally fragile (no cross-season edge — signals AND the edge→HR
relationship are 2025-26 artifacts); UNDER + edge is the durable engine.** The 2025-26 boom→collapse was a
soft-market anomaly, not a model/seasonal flaw, and the March collapse is production-side. Nothing is merged;
the season-start fix should merge before opening night, everything else is gated/sign-off.

## Branch state — the 10 commits (oldest→newest), on top of prior handoff `58941cce`
```
986d9c5c fix(signals): dynamic season-start in per-model pipeline + signal_health   <- REAL PROD FIX (merge pre-opener)
23624848 chore(gitignore): ignore mlb/nba replay + staleness scratch caches (93MB)   <- hygiene
8d1bb362 docs: season-resume 2026-27 runbook + off-season review corrections
ae923825 research: cross-book OVER signals are 2025-26-only artifacts
2fb0086e research: UNDER edge3+ stable 57.3%; low-line/low-var archetype does not reproduce
df0fcde2 research: signal trust-map — OVER layer pervasively 2025-26-overfit
8a6fe843 research: 'edge5+ money zone' is OVER-FALSE — high-edge OVER has no cross-season edge
64f0c148 research: broad 5-season findings — UNDER-only robust, b2b_under wrongly removed
ebe12187 feat(signals): reinstate b2b_fatigue_under in SHADOW (5-season validated)    <- ZERO pick impact
1f6610b3 docs: b2b promotion path; flag b2b_boost_over + high_line_under
```

## What actually changed code-wise (2 things; both safe/inert)
1. **Season-start prod fix (`986d9c5c`)** — 6 hardcoded `'2025-10-22'`/`'2025-10-01'` floors in
   `per_model_pipeline.py` (×5) + `signal_health.py` (×2) parameterized to `@season_start` via
   `_season_start_for`. In 2026-27 these blended 2025-26+2026-27 rows into season aggregates / signal-health
   windows. Preserves 2025-26 behavior; fixes 2026-27. **Residual: add 2026 to `FALLBACK_SEASON_START_DATES`
   in `shared/config/nba_season_dates.py` once the schedule publishes (~Aug-Sep 2026)** — until then 2026-27
   falls to the Oct-22 default (safe, never blends, ~1-day imprecise). **This is the one change that should
   MERGE TO MAIN before opening night.**
2. **`b2b_fatigue_under` shadow reinstatement (`ebe12187`)** — registered + in `SHADOW_SIGNALS`, NOT in
   `UNDER_SIGNAL_WEIGHTS` → **ZERO pick impact**. Ready to promote at season open (see action list).

Everything else this session is docs/research/memory. The pre-existing dirty tree (~36 modified + ~80
untracked, unauthored) was left untouched per prior guidance — DO NOT `git add -A`.

## CORE FRAMING CORRECTIONS (act on these, not the old beliefs)
1. **"edge5+ is the money zone" is OVER-FALSE.** High-edge OVER has NO cross-season edge: edge≥6 OVER (the
   floor-allowed band) = **38.9% in the prior 4 seasons** (below breakeven all four), only 92.6% in 2025-26
   (p<0.001). UNDER edge≥6 IS durable (61% cross-season). → Make the framing direction-specific. **Fix the
   CLAUDE.md "Edge 5+ is the money zone" line.** Detail: `2026-06-23-edge-calibration-RESULT.md`.
2. **The OVER signal layer is pervasively 2025-26-overfit** (4/5 active OVER signals are recency artifacts;
   `fast_pace_over`, `cold_3pt_over` are sub-breakeven in prior seasons, p<0.001). Detail:
   `2026-06-23-signal-trustmap-RESULT.md`.
3. **The March-2026 collapse is PRODUCTION-side, not model.** Clean walk-forward raw model held up in March
   (UNDER 58%, OVER 73%) while prod BB hit 46.7% → cause is selection/overfit-signals/live-market, not model
   quality or "March is unbeatable." Consistent with the staleness STEP5 refutation.
4. **The 2025-26 anomaly = a soft market (bigger edges that paid), NOT model bias** (model is unbiased every
   season; it carries a small structural OVER lean that manufactures losing OVER picks).
5. **From the 24-agent review (prior, still applies):** don't relax `cap_to_pre_late_season`; cadence 14d is
   cost-eligible not HR-equal; +13.7/+6.7pp not robust → gated 47.4%; `combo_3way` is single-MODEL.
   Detail: `memory/offseason-review-corrections-2026-06.md`.

## PRIORITIZED 2026-27 ACTION LIST
**Do before opening night (~late Oct 2026):**
- [ ] **Merge `986d9c5c` (season-start fix) to main** — real prod fix; offline-verified; deploys phase6/worker.
- [ ] **Add 2026 to `FALLBACK_SEASON_START_DATES`** once the schedule publishes (closes the residual).
- [ ] **Flip HSE floor off→observe** on prediction-worker + coordinator (`--update-env-vars
      HSE_RESCUE_FLOOR_MODE=observe`, NEVER `--set-env-vars`).
- [ ] **Resume paused schedulers; verify REB/AST data clock ENABLED.**

**UNDER-dominant posture (the strategic core for 2026-27):**
- [ ] **Treat OVER as UNPROVEN at season open** — add an early-season scoring-environment gate (only lean into
      OVER if the league is scoring above line/model expectation like 2025-26; check `league_macro_daily`).
- [ ] **Promote `b2b_fatigue_under` shadow→active** after live N≥30 at HR≥58%: move it out of `SHADOW_SIGNALS`
      and add to `UNDER_SIGNAL_WEIGHTS` (~2.0) in `aggregator.py`. (Already wired in shadow; needs sign-off.)
- [ ] **OVER decay watch** — re-grade `fast_pace_over`, `cold_3pt_over`, `line_rising_over`,
      `book_disagree_over`, `b2b_boost_over` by ~Dec 2026; demote any not clearly above breakeven at N≥30.
      `cold_3pt_over` is the worst (sub-breakeven 4/5 seasons) — strongest proactive-demote candidate.
- [ ] **Consider `high_line_under`** (star UNDER, line≥25): passes the formal gate strongly (59.9%, 5/5
      seasons, p=0.0007). Check overlap with existing UNDER signals before adding.

**Phase6-path items (staged — merge at season resume, can't validate offline):**
- [ ] `pipeline_merger.RESCUE_SIGNAL_PRIORITY` is documented to trim by priority but trims by composite_score
      (constant only used in a log) — decide priority-vs-composite, add unit tests for the rescue/team/volume
      caps.
- [ ] Auto-halt edge query lacks `current_points_line IS NOT NULL`/`has_prop_line` → NULL-line rows dilute
      `pct_edge_5plus` (biases toward over-halt; safe direction but inaccurate). Also whitelist the dynamic
      `halt_reason` (else first halt day mislabels as status='degraded') + emit a halt-flip metric.
- [ ] `filters.yaml` drifted from `aggregator.py` tag names (`high_book_std_under`→`_block`,
      `line_jumped_under`→`_obs`, `hse_rescue_floor` unregistered) → can break `filter_audit` joins.

**Gated/deferred (unchanged):** non-tree diversity model (NO-GO; lean on `book_disagreement`), REB/AST model
(data-only until Feb-2027 backtest), `model_bb_candidates` NULL cols, cadence 14d A/B (season-start, sign-off).

## DON'Ts (carry forward)
- Don't relax `cap_to_pre_late_season`; don't flip cadence or enable HSE 'active' on thin data; don't
  `--set-env-vars`; don't `git add -A` (pre-existing dirty tree); don't trust OVER signals at their current
  weights in 2026-27; don't project the 63.8% BB record forward as stable. Real breakeven ≈ 53.5%.
- Don't re-run the broad mining unguarded — diminishing returns + false-discovery risk; use the formal
  discovery gate (`scripts/nba/training/discovery/stats_utils.py`: BH-FDR + block bootstrap + cross-season).

## Env / data notes
- **Research data:** `DiscoveryDataset(min_edge=0.0)` from `scripts/nba/training/discovery/data_loader.py` —
  5-season walk-forward CatBoost V12_NOVEG, joined to BettingPros multibook + feature store + PGS. Caches in
  `results/` (gitignored); rebuild via `build_walkforward_predictions.py` then `build_bb_simulator_cache.py`.
- **`bq` CLI hangs** — use the Python BQ client. **gcloud works** but `--project=nba-props-platform`;
  `scheduler/builds list` are slow. **Git push is slow (~1-2min)** — run in background.
- Pre-commit hooks run on commit; the `check-date-comparisons` hook flags `<= @target_date` — annotate
  intentional ones with `-- <= correct: ...`.

## Map of docs created this session (all under docs/09-handoff/)
- `2026-06-23-crossbook-OVER-multiseason-RESULT.md` — cross-book OVER is 2025-26-only; UNDER stable.
- `2026-06-23-signal-trustmap-RESULT.md` — OVER signal layer overfit; UNDER durable-or-neutral.
- `2026-06-23-edge-calibration-RESULT.md` — "edge5+ money zone" is OVER-false (the centerpiece).
- `2026-06-23-broad-research-findings.md` — P/L, late-season decay, calibration, segmentation, b2b.
- `docs/02-operations/runbooks/season-resume-2026-27.md` — the opening-night operating posture (READ THIS).
- `memory/offseason-review-corrections-2026-06.md` — the 24-agent review's narrowed findings.
- This file — the consolidated index.
